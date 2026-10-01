"""Workspaces + Groups routers, translated from app/routes/workspaces.py and
app/routes/groups.py.

Both Flask blueprints mount under the SAME url_prefix (``/api/workspaces``), so
they collapse into ONE FastAPI router here. Every Flask handler maps 1:1 to a
FastAPI path operation; response shapes (incl. the Mongo ``_id`` alias emitted
by the model facades) are preserved byte-for-byte.

Auth gates translate as:
    @jwt_required()+@active_user_required        -> Depends(require_active)
    @manager_or_admin_required                    -> Depends(require_manager_or_admin)
    @workspace_member(min_role, id_kwarg='wid')   -> Depends(workspace_member_dep(min_role, 'wid'))

The router-level ``Depends(flask_ctx)`` binds one Flask app_context per request
so every existing model facade / service runs verbatim.
"""
from __future__ import annotations

import logging
from datetime import datetime

import anyio.to_thread
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    flask_ctx,
    require_active,
    require_admin,
    require_manager_or_admin,
    workspace_member_dep,
)
from app.extensions import db
from app.models.audit_log import AuditLogModel
from app.models.credit_ledger import CreditLedgerModel
from app.models.group import GroupModel
from app.models.group_member import GroupMemberModel
from app.models.project import ProjectModel
from app.models.project_group_access import ProjectGroupAccessModel
from app.models.spend_rollup import SpendRollupModel
from app.models.usage_log import UsageLog, UsageLogModel
from app.models.user import User, UserModel
from app.models.workspace import WorkspaceModel
from app.models.workspace_invite import WorkspaceInviteModel
from app.models.workspace_member import WorkspaceMemberModel
from app.services import analytics_service
from app.utils.helpers import serialize_doc, validate_object_id
from app.utils.credits import to_credits
from app.utils.permissions import (
    check_workspace_access,
    get_workspace_role,
    mask_usd_fields,
    money_view,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(flask_ctx)])


# ---------------------------------------------------------------------------
# Local helpers (ported verbatim from the Flask blueprints).
# ---------------------------------------------------------------------------
import uuid as _uuid

_ALLOWED_INVITE_ROLES = {"viewer", "editor", "owner"}
_ALLOWED_MEMBER_ROLES = {"viewer", "editor", "owner"}


def _serialize(doc):
    return serialize_doc(doc)


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _ws_to_uuid_safe(val):
    if val is None:
        return None
    if isinstance(val, _uuid.UUID):
        return val
    try:
        return _uuid.UUID(str(val))
    except Exception:  # noqa: BLE001
        return None


def _month_start_utc():
    now = datetime.utcnow()
    return datetime(now.year, now.month, 1)


def _parse_iso_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.replace(tzinfo=None)
            return parsed
        except ValueError:
            pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    return None


async def _json_body(request: Request) -> dict:
    """Read the JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Workspace CRUD
# ---------------------------------------------------------------------------
@router.get("/list")
def list_workspaces(user: dict = Depends(require_active)):
    """List all workspaces the caller is an active member of."""
    user_id_str = str(user["_id"])
    workspaces = WorkspaceModel.find_by_member(user_id_str) or []

    out = []
    for ws in workspaces:
        ws_id_str = str(ws["_id"])
        role = get_workspace_role(user_id_str, ws_id_str)
        ws_dict = _serialize(ws)
        ws_dict["member_role"] = role
        out.append(ws_dict)
    return out


@router.post("/create")
async def create_workspace(
    request: Request,
    user: dict = Depends(require_active),
    _: dict = Depends(require_manager_or_admin),
):
    """Create a new team workspace. The caller becomes the owner."""
    user_id = user["_id"]
    data = await _json_body(request)

    name = (data.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    if len(name) > 100:
        return JSONResponse({"error": "name must be at most 100 characters"}, status_code=400)

    avatar = data.get("avatar")
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else None

    ws = WorkspaceModel.create(
        name=name,
        owner_id=user_id,
        type="team",
        avatar=avatar,
        settings=settings,
    )
    WorkspaceMemberModel.add(
        ws["_id"],
        user_id,
        "owner",
        invited_by=user_id,
        status="active",
    )
    return JSONResponse(_serialize(ws), status_code=201)


@router.get("/{wid}")
def get_workspace(wid: str, user: dict = Depends(workspace_member_dep("viewer", "wid"))):
    """Return workspace doc + caller's role."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    ws = WorkspaceModel.find_by_id(wid)
    if not ws:
        return JSONResponse({"error": "Workspace not found"}, status_code=404)

    role = get_workspace_role(str(user["_id"]), wid)
    out = _serialize(ws)
    out["member_role"] = role
    # Members without price tier must not see wallet/budget $ fields.
    view = money_view(user, ws)
    mask_usd_fields(out, view)
    if view == "none":
        rem = WorkspaceModel.credits_remaining_usd(wid)
        out["credits_remaining"] = to_credits(rem)
    return out


@router.patch("/{wid}")
async def update_workspace(
    wid: str,
    request: Request,
    user: dict = Depends(workspace_member_dep("owner", "wid")),
):
    """Update workspace name / avatar / settings (owner only)."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    ws = WorkspaceModel.find_by_id(wid)
    if not ws:
        return JSONResponse({"error": "Workspace not found"}, status_code=404)

    data = await _json_body(request)
    update_data = {}

    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            return JSONResponse({"error": "name cannot be empty"}, status_code=400)
        if len(name) > 100:
            return JSONResponse({"error": "name must be at most 100 characters"}, status_code=400)
        update_data["name"] = name

    if "avatar" in data:
        update_data["avatar"] = data["avatar"]

    if "settings" in data:
        if not isinstance(data["settings"], dict):
            return JSONResponse({"error": "settings must be an object"}, status_code=400)
        update_data["settings"] = data["settings"]

    for field in (
        "ip_allowlist", "enforce_2fa", "plan_tier",
        "budget_mtd_usd", "seats_total", "renews_at", "spend_caps",
    ):
        if field in data:
            update_data[field] = data[field]

    if not update_data:
        return JSONResponse({"error": "No valid fields to update"}, status_code=400)

    try:
        WorkspaceModel.update(wid, update_data)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    updated = WorkspaceModel.find_by_id(wid)
    return _serialize(updated)


@router.delete("/{wid}")
def delete_workspace(wid: str, user: dict = Depends(workspace_member_dep("owner", "wid"))):
    """Delete a team workspace (owner only)."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    ws = WorkspaceModel.find_by_id(wid)
    if not ws:
        return JSONResponse({"error": "Workspace not found"}, status_code=404)

    from app.services.workspace_cascade import cascade_delete

    cascade_counts = cascade_delete(wid)
    UserModel.null_active_workspace_for_workspace(wid)

    try:
        AuditLogModel.create(
            action="workspace_deleted",
            admin_id=user["_id"],
            target_type="workspace",
            target_id=wid,
            details={"cascade_counts": cascade_counts},
        )
    except Exception:  # noqa: BLE001
        pass  # audit failures must not break the delete response

    return {"message": "Workspace deleted", "cascade": cascade_counts}


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------
@router.post("/{wid}/invites")
async def create_invite(
    wid: str,
    request: Request,
    user: dict = Depends(workspace_member_dep("owner", "wid")),
):
    """Create an invite for a given email + role."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    data = await _json_body(request)

    email = _normalize_email(data.get("email", ""))
    if not email or "@" not in email:
        return JSONResponse({"error": "Valid email is required"}, status_code=400)

    role = (data.get("role") or "").strip().lower()
    if role not in _ALLOWED_INVITE_ROLES:
        return JSONResponse(
            {"error": f"role must be one of {sorted(_ALLOWED_INVITE_ROLES)}"},
            status_code=400,
        )

    invite = WorkspaceInviteModel.create(
        workspace_id=wid,
        email=email,
        role=role,
        invited_by=user["_id"],
    )

    ws = WorkspaceModel.find_by_id(wid)
    accept_url = f"/invite/{invite['token']}"
    inviter_name = (user.get("profile") or {}).get("display_name") or user.get("email", "")
    from app.services.email_service import send_invite_email

    def _send() -> bool:
        return send_invite_email(
            to=email,
            workspace_name=ws.get("name", "") if ws else "",
            accept_url=accept_url,
            inviter_name=inviter_name,
            role=role,
        )

    email_sent = await anyio.to_thread.run_sync(_send)

    out = _serialize(invite)
    out["invite_url"] = accept_url
    out["email_sent"] = email_sent
    return JSONResponse(out, status_code=201)


@router.get("/{wid}/invitable-users")
def invitable_users(
    wid: str,
    q: str = Query(""),
    limit: int = Query(10),
    user: dict = Depends(workspace_member_dep("owner", "wid")),
):
    """Typeahead for the invite dialog: existing users not yet in this workspace.

    Searches users by email / display_name substring, excluding active members,
    emails that already hold a pending invite, and platform-admin emails.
    """
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    q = (q or "").strip()
    if len(q) < 2:
        return JSONResponse([], status_code=200)

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(25, limit))

    # Active members of this workspace are not invitable.
    member_rows = WorkspaceMemberModel.find_by_workspace(wid, status="active") or []
    member_ids = [
        _ws_to_uuid_safe(r.get("user_id"))
        for r in member_rows
        if r.get("user_id") is not None
    ]
    member_ids = [m for m in member_ids if m is not None]

    # Emails that already have a pending invite are not invitable.
    pending_invites = WorkspaceInviteModel.find_by_workspace(wid, pending_only=True) or []
    pending_emails = {
        _normalize_email(i.get("email")) for i in pending_invites if i.get("email")
    }

    like = f"%{q}%"
    stmt = select(User).where(
        or_(
            User.email.ilike(like),
            User.display_name.ilike(like),
            User.profile["display_name"].astext.ilike(like),
        )
    )
    if member_ids:
        stmt = stmt.where(User.id.notin_(member_ids))
    stmt = stmt.order_by(User.created_at.desc()).limit(limit)

    rows = db.session.execute(stmt).scalars().all()

    out = []
    for u in rows:
        email_norm = _normalize_email(u.email)
        if email_norm in pending_emails:
            continue
        profile = u.profile or {}
        out.append({
            "id": str(u.id),
            "email": u.email,
            "display_name": profile.get("display_name") or u.display_name,
            "avatar_url": profile.get("avatar_url"),
        })

    return JSONResponse(out, status_code=200)


@router.get("/{wid}/invites")
def list_invites(wid: str, user: dict = Depends(workspace_member_dep("owner", "wid"))):
    """List pending invites for this workspace."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    invites = WorkspaceInviteModel.find_by_workspace(wid, pending_only=True) or []
    return [_serialize(i) for i in invites]


@router.delete("/{wid}/invites/{token}")
def revoke_invite(
    wid: str,
    token: str,
    user: dict = Depends(workspace_member_dep("owner", "wid")),
):
    """Revoke an invite by token."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    invite = WorkspaceInviteModel.find_by_token(token)
    if not invite:
        return JSONResponse({"error": "Invite not found"}, status_code=404)
    if str(invite.get("workspace_id")) != str(wid):
        return JSONResponse(
            {"error": "Invite does not belong to this workspace"}, status_code=404
        )

    WorkspaceInviteModel.revoke(token)
    return {"message": "Invite revoked"}


@router.post("/accept-invite")
async def accept_invite(request: Request, user: dict = Depends(require_active)):
    """Accept an invite by token. Adds caller to workspace_members."""
    data = await _json_body(request)
    token = (data.get("token") or "").strip()
    if not token:
        return JSONResponse({"error": "token is required"}, status_code=400)

    invite = WorkspaceInviteModel.find_by_token(token)
    if not invite:
        return JSONResponse(
            {"error": "Invite not found", "code": "invite_not_found"}, status_code=404
        )

    if invite.get("accepted_at") is not None:
        return JSONResponse(
            {"error": "Invite has already been accepted", "code": "invite_already_accepted"},
            status_code=400,
        )

    expires_at = invite.get("expires_at")
    if expires_at and isinstance(expires_at, datetime) and expires_at <= datetime.utcnow():
        return JSONResponse(
            {"error": "Invite has expired", "code": "invite_expired"}, status_code=400
        )

    invite_email = _normalize_email(invite.get("email", ""))
    user_email = _normalize_email(user.get("email", ""))
    if invite_email != user_email:
        return JSONResponse({"error": "invite_email_mismatch"}, status_code=403)

    role = invite.get("role", "viewer")
    if role not in _ALLOWED_MEMBER_ROLES:
        role = "viewer"

    workspace_id = invite["workspace_id"]

    existing = WorkspaceMemberModel.find(workspace_id, user["_id"])
    if existing:
        if existing.get("status") != "active":
            WorkspaceMemberModel.update_status(workspace_id, user["_id"], "active")
    else:
        WorkspaceMemberModel.add(
            workspace_id,
            user["_id"],
            role,
            invited_by=invite.get("invited_by"),
            status="active",
        )

    WorkspaceInviteModel.mark_accepted(token)

    return {"workspace_id": str(workspace_id), "role": role}


@router.post("/{wid}/invites/{token}/resend")
async def resend_invite(
    wid: str,
    token: str,
    request: Request,
    user: dict = Depends(workspace_member_dep("owner", "wid")),
):
    """Rotate invite token, reset expiry, and optionally re-send email."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    invite = WorkspaceInviteModel.find_by_token(token)
    if not invite or str(invite.get("workspace_id")) != str(wid):
        return JSONResponse({"error": "Invite not found"}, status_code=404)

    if invite.get("accepted_at") is not None:
        return JSONResponse(
            {"error": "Invite has already been accepted", "code": "invite_already_accepted"},
            status_code=409,
        )

    updated_invite = WorkspaceInviteModel.refresh(token)
    if not updated_invite:
        return JSONResponse({"error": "Failed to refresh invite"}, status_code=500)

    ws = WorkspaceModel.find_by_id(wid)
    accept_url = f"/invite/{updated_invite['token']}"
    inviter_name = (user.get("profile") or {}).get("display_name") or user.get("email", "")
    from app.services.email_service import send_invite_email

    def _send() -> bool:
        return send_invite_email(
            to=updated_invite.get("email", ""),
            workspace_name=ws.get("name", "") if ws else "",
            accept_url=accept_url,
            inviter_name=inviter_name,
            role=updated_invite.get("role", "viewer"),
        )

    email_sent = await anyio.to_thread.run_sync(_send)

    out = _serialize(updated_invite)
    out["invite_url"] = accept_url
    out["email_sent"] = email_sent
    return {"invite": out, "accept_url": accept_url, "email_sent": email_sent}


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
@router.get("/{wid}/members")
def list_members(wid: str, user: dict = Depends(workspace_member_dep("viewer", "wid"))):
    """List active + pending members, hydrated with user info."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    try:
        from app.services.keycloak import get_keycloak_client
        from app.services.keycloak_orgs import refresh_org_members
        kc = get_keycloak_client()
        if kc is not None:
            refresh_org_members(wid, kc)
    except Exception:  # noqa: BLE001 — local membership list still answers
        pass

    rows = WorkspaceMemberModel.find_by_workspace(wid, status=["active", "pending"]) or []
    user_ids = [r.get("user_id") for r in rows if r.get("user_id") is not None]

    user_map = {}
    if user_ids:
        for u in UserModel.find_by_ids(user_ids):
            # `password_hash` is only present on the legacy dict when the user
            # has one (SSO-only users have None/absent) => derive auth_method.
            # `usage.last_active` is an ISO string already.
            has_password = bool(u.get("password_hash"))
            user_map[str(u["_id"])] = {
                "email": u.get("email"),
                "display_name": (u.get("profile") or {}).get("display_name"),
                "avatar_url": (u.get("profile") or {}).get("avatar_url"),
                "auth_method": "password" if has_password else "sso",
                "last_active_at": (u.get("usage") or {}).get("last_active"),
            }

    out = []
    for r in rows:
        row = _serialize(r)
        uid_str = str(r.get("user_id")) if r.get("user_id") is not None else None
        info = user_map.get(uid_str, {}) if uid_str else {}
        row["user"] = {
            "id": uid_str,
            "email": info.get("email"),
            "display_name": info.get("display_name"),
            "avatar_url": info.get("avatar_url"),
        }
        row["auth_method"] = info.get("auth_method")
        row["last_active_at"] = info.get("last_active_at")
        out.append(row)
    return out


@router.post("/{wid}/members")
async def add_workspace_member(
    wid: str,
    request: Request,
    user: dict = Depends(workspace_member_dep("owner", "wid")),
):
    """Add a user directly to a company as an active member (no email invite)."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    data = await _json_body(request)
    user_id = (data.get("user_id") or "").strip()
    role = (data.get("role") or "").strip().lower()

    if not user_id or not validate_object_id(user_id):
        return JSONResponse({"error": "Valid user_id is required"}, status_code=400)
    # Owner cannot be granted via this endpoint — only viewer/editor.
    if role not in {"viewer", "editor"}:
        return JSONResponse(
            {"error": "role must be one of ['editor', 'viewer']"},
            status_code=400,
        )

    target_user = UserModel.find_by_id(user_id)
    if not target_user:
        return JSONResponse({"error": "User not found"}, status_code=404)

    existing = WorkspaceMemberModel.find(wid, user_id)
    if existing:
        if existing.get("status") != "active":
            WorkspaceMemberModel.update_status(wid, user_id, "active")
        member = WorkspaceMemberModel.find(wid, user_id)
    else:
        member = WorkspaceMemberModel.add(
            wid, user_id, role, invited_by=user["_id"], status="active"
        )

    return JSONResponse(_serialize(member), status_code=201)


@router.patch("/{wid}/members/{uid}")
async def update_member_role(
    wid: str,
    uid: str,
    request: Request,
    user: dict = Depends(workspace_member_dep("owner", "wid")),
):
    """Change a member's role. Refuses to demote the last owner."""
    if not validate_object_id(wid) or not validate_object_id(uid):
        return JSONResponse({"error": "Invalid ID"}, status_code=400)

    data = await _json_body(request)
    role = (data.get("role") or "").strip().lower()
    if role not in _ALLOWED_MEMBER_ROLES:
        return JSONResponse(
            {"error": f"role must be one of {sorted(_ALLOWED_MEMBER_ROLES)}"},
            status_code=400,
        )

    target = WorkspaceMemberModel.find(wid, uid)
    if not target:
        return JSONResponse({"error": "Member not found"}, status_code=404)

    current_role = target.get("role")
    if current_role == "owner" and role != "owner":
        owner_count = WorkspaceMemberModel.count_owners(wid)
        if owner_count <= 1:
            return JSONResponse(
                {"error": "Cannot demote the last owner", "code": "last_owner_protected"},
                status_code=400,
            )

    WorkspaceMemberModel.update_role(wid, uid, role)
    updated = WorkspaceMemberModel.find(wid, uid)
    return _serialize(updated)


@router.delete("/{wid}/members/{uid}")
def remove_member(
    wid: str,
    uid: str,
    user: dict = Depends(workspace_member_dep("owner", "wid")),
):
    """Remove a member. Self-leave is permitted unless caller is last owner."""
    if not validate_object_id(wid) or not validate_object_id(uid):
        return JSONResponse({"error": "Invalid ID"}, status_code=400)

    target = WorkspaceMemberModel.find(wid, uid)
    if not target:
        return JSONResponse({"error": "Member not found"}, status_code=404)

    if target.get("role") == "owner":
        owner_count = WorkspaceMemberModel.count_owners(wid)
        if owner_count <= 1:
            return JSONResponse(
                {"error": "Cannot remove the last owner", "code": "last_owner_protected"},
                status_code=400,
            )

    WorkspaceMemberModel.remove(wid, uid)
    UserModel.null_active_workspace_for_user_if_match(uid, wid)
    return {"message": "Member removed"}


@router.post("/{wid}/transfer-ownership")
async def transfer_ownership(
    wid: str,
    request: Request,
    user: dict = Depends(require_active),
):
    """Transfer workspace ownership to another active member.

    Auth: caller must be current workspace owner OR have global role 'admin'.
    Note: the Flask route is NOT wrapped in @workspace_member — it performs an
    in-handler owner/global-admin check — so we mirror that here with the lighter
    require_active gate.
    """
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    caller_id_str = str(user["_id"])

    ws = WorkspaceModel.find_by_id(wid)
    if not ws:
        return JSONResponse({"error": "Workspace not found"}, status_code=404)

    caller_membership = WorkspaceMemberModel.find(wid, caller_id_str)
    is_owner = (
        caller_membership
        and caller_membership.get("role") == "owner"
        and caller_membership.get("status") == "active"
    )
    is_global_admin = user.get("role") == "admin"

    if not is_owner and not is_global_admin:
        return JSONResponse(
            {"error": "Only the workspace owner or a global admin may transfer ownership"},
            status_code=403,
        )

    data = await _json_body(request)
    new_owner_uid = (data.get("new_owner_user_id") or "").strip()
    if not new_owner_uid or not validate_object_id(new_owner_uid):
        return JSONResponse({"error": "Valid new_owner_user_id is required"}, status_code=400)

    if new_owner_uid == caller_id_str:
        return JSONResponse({"error": "Target is already the caller"}, status_code=409)

    target_membership = WorkspaceMemberModel.find(wid, new_owner_uid)
    if not target_membership or target_membership.get("status") != "active":
        return JSONResponse(
            {"error": "Target user is not an active member of this workspace"},
            status_code=400,
        )

    if target_membership.get("role") == "owner":
        return JSONResponse({"error": "Target is already an owner"}, status_code=409)

    try:
        if caller_membership:
            WorkspaceMemberModel.update_role(wid, caller_id_str, "editor")
        WorkspaceMemberModel.update_role(wid, new_owner_uid, "owner")
        WorkspaceModel.set_owner(wid, new_owner_uid)
    except Exception as txn_exc:  # noqa: BLE001
        db.session.rollback()
        logger.warning("transfer_ownership swap failed (%s)", txn_exc)
        return JSONResponse(
            {"error": "Ownership transfer failed; state restored"}, status_code=500
        )

    AuditLogModel.create(
        action="workspace.transfer_ownership",
        admin_id=user["_id"],
        target_id=wid,
        target_type="workspace",
        details={
            "workspace_id": wid,
            "previous_owner_id": caller_id_str,
            "new_owner_id": new_owner_uid,
        },
    )

    updated_ws = WorkspaceModel.find_by_id(wid)
    caller_row = WorkspaceMemberModel.find(wid, caller_id_str)
    target_row = WorkspaceMemberModel.find(wid, new_owner_uid)

    return {
        "workspace": _serialize(updated_ws),
        "previous_owner_membership": _serialize(caller_row) if caller_row else None,
        "new_owner_membership": _serialize(target_row),
    }


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
@router.get("/{wid}/overview")
def workspace_overview(wid: str, user: dict = Depends(workspace_member_dep("viewer", "wid"))):
    """Aggregate dashboard data for the workspace overview page."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    ws = WorkspaceModel.find_by_id(wid)
    if not ws:
        return JSONResponse({"error": "Workspace not found"}, status_code=404)

    month_start = _month_start_utc()

    # MTD spend = the company current-month spend rollup point-read (NOT a
    # SUM(usage_logs) — same counter the spend-gate consults). Missing row for a
    # brand-new company => 0.0, which is correct.
    spend_mtd = SpendRollupModel.get_spent(
        "company", wid, SpendRollupModel.current_period_month()
    )
    seats_used = WorkspaceMemberModel.count_active(wid)
    rem_usd = WorkspaceModel.credits_remaining_usd(wid)
    view = money_view(user, ws)
    billing = {
        "plan_tier": ws.get("plan_tier") or ws.get("plan") or "free",
        # Reconciled headline = Σledger − Σusage (matches the billing tab); the
        # frontend surfaces this as "credits". `credits_balance_usd` below is the
        # lifetime top-ups column (never decrements) kept as a secondary field.
        "credits_remaining_usd": rem_usd if view != "none" else None,
        "credits_balance_usd": float(ws.get("credits_balance_usd") or 0) if view != "none" else None,
        "spend_mtd_usd": float(spend_mtd or 0) if view != "none" else None,
        "credits_remaining": to_credits(rem_usd),
        "spend_mtd_credits": to_credits(spend_mtd or 0),
        "seats_used": seats_used,
        "seats_total": int(ws.get("seats_total") or 0),
        "budget_mtd_usd": float(ws.get("budget_mtd_usd") or 0) if view != "none" else None,
        "renews_at": ws["renews_at"].isoformat()
        if isinstance(ws.get("renews_at"), datetime)
        else ws.get("renews_at"),
        "sso_enforced": bool(ws.get("sso_enforced")),
        "scim_enabled": bool(ws.get("scim_enabled")),
        "domain": ws.get("domain"),
    }

    project_rows = UsageLogModel.aggregate_project_spend(wid, start=month_start)[:5]
    pid_strs = [r["project_id"] for r in project_rows if r.get("project_id")]
    project_map = {}
    if pid_strs:
        for p in ProjectModel.find_by_ids(pid_strs):
            project_map[str(p["_id"])] = p
    top_projects = []
    for r in project_rows:
        pid = r.get("project_id")
        proj = project_map.get(pid) if pid else None
        if not proj:
            continue
        top_projects.append({
            "project_id": pid,
            "name": proj.get("name"),
            "color": proj.get("color"),
            "pinned": bool(proj.get("pinned")),
            "total_cost": r.get("total_cost", 0) if view != "none" else None,
            "total_credits": to_credits(r.get("total_cost", 0)),
            "message_count": r.get("count", 0),
        })

    recent_activity = [
        serialize_doc(a) for a in AuditLogModel.find_by_workspace(wid, limit=5)
    ]

    groups_cursor = GroupModel.find_by_workspace(wid)[:5]
    groups_out = [serialize_doc(g) for g in groups_cursor]

    # One grouped pass yields both the 30-day series and the MTD message count
    # (folds the old aggregate_daily + total_messages_this_month round-trips).
    usage_bundle = UsageLogModel.overview_usage_bundle(wid, days=30)
    daily = usage_bundle["daily"]
    messages_mtd = usage_bundle["messages_mtd"]

    # active_projects counts the `projects` table (non-archived), NOT usage rows
    # — a distinct-project-id count over usage_logs would diverge (idle projects
    # missing, archived-but-used projects wrongly counted). Stays its own read.
    active_projects = ProjectModel.count_by_workspace(wid, archived=False)
    members_active = seats_used

    ws_out = serialize_doc(ws)
    mask_usd_fields(ws_out, view)
    # usage_30d may carry cost_usd — mask for non-price viewers
    usage_out = []
    for row in daily or []:
        if not isinstance(row, dict):
            usage_out.append(row)
            continue
        r = dict(row)
        if view == "none":
            if "cost_usd" in r:
                r["credits"] = to_credits(r.get("cost_usd"))
                r["cost_usd"] = None
            if "total_cost" in r:
                r["total_credits"] = to_credits(r.get("total_cost"))
                r["total_cost"] = None
        usage_out.append(r)

    return {
        "workspace": ws_out,
        "billing": billing,
        "top_projects": top_projects,
        "recent_activity": recent_activity,
        "groups": groups_out,
        "usage_30d": usage_out,
        "stats": {
            "messages_mtd": messages_mtd,
            "active_projects": active_projects,
            "members_active": members_active,
        },
    }


# ---------------------------------------------------------------------------
# Billing — usage aggregation (owner only)
# ---------------------------------------------------------------------------
@router.get("/{wid}/billing/usage")
def billing_usage(
    wid: str,
    request: Request,
    user: dict = Depends(workspace_member_dep("owner", "wid")),
):
    """Multi-axis spend aggregation for the billing tab."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    start = _parse_iso_date(request.query_params.get("start")) or _month_start_utc()
    end = _parse_iso_date(request.query_params.get("end")) or datetime.utcnow()

    by_user = UsageLogModel.aggregate_user_spend(wid, start=start, end=end)
    by_project = UsageLogModel.aggregate_project_spend(wid, start=start, end=end)
    by_model = UsageLogModel.aggregate_model_spend(wid, start=start, end=end)

    wid_uuid = _ws_to_uuid_safe(wid)
    daily = []
    if wid_uuid is not None:
        day_expr = func.to_char(UsageLog.created_at, "YYYY-MM-DD").label("day")
        token_sum = func.coalesce(
            func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0
        ).label("total_tokens")
        cost_sum = func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost_usd")
        rows = db.session.execute(
            select(day_expr, cost_sum, token_sum, func.count().label("messages"))
            .where(
                UsageLog.workspace_id == wid_uuid,
                UsageLog.created_at >= start,
                UsageLog.created_at <= end,
            )
            .group_by("day")
            .order_by("day")
        ).all()
        daily = [
            {
                "date": r.day,
                "cost_usd": float(r.cost_usd or 0),
                "total_tokens": int(r.total_tokens or 0),
                "messages": int(r.messages or 0),
            }
            for r in rows
        ]

    totals = {
        "cost_usd": float(sum(r.get("total_cost", 0) for r in by_user)),
        "total_tokens": int(sum(r.get("total_tokens", 0) for r in by_user)),
        "messages": int(sum(r.get("count", 0) for r in by_user)),
    }

    uid_strs = [r["user_id"] for r in by_user if r.get("user_id")]
    user_map = {}
    if uid_strs:
        for u in UserModel.find_by_ids(uid_strs):
            user_map[str(u["_id"])] = {
                "email": u.get("email"),
                "display_name": (u.get("profile") or {}).get("display_name"),
                "avatar_url": (u.get("profile") or {}).get("avatar_url"),
            }
    for row in by_user:
        info = user_map.get(row.get("user_id") or "", {})
        row["email"] = info.get("email")
        row["display_name"] = info.get("display_name")
        row["avatar_url"] = info.get("avatar_url")

    pid_strs = [r["project_id"] for r in by_project if r.get("project_id")]
    project_map = {}
    if pid_strs:
        for p in ProjectModel.find_by_ids(pid_strs):
            project_map[str(p["_id"])] = p
    for row in by_project:
        proj = project_map.get(row.get("project_id") or "")
        if proj:
            row["name"] = proj.get("name")
            row["color"] = proj.get("color")

    lifetime_topups = float(CreditLedgerModel.sum_credits(wid))
    lifetime_spend = float(UsageLogModel.aggregate_workspace_spend(wid))

    # Budget posture (burn-rate / projected month-end / cap breaches). Always
    # cost-visible here: the owner gate (`workspace_member_dep("owner")`) is the
    # same $-visibility tier the billing tab already shows real spend on.
    budget_block = analytics_service.budget(wid, cost_visible=True)

    cascade = _billing_cascade(wid)

    # Department-plan block: the monthly INCLUDED allowance and how much of it is
    # left this calendar month. ``allowance_usd`` None / 0 (unlimited included /
    # no allowance) -> ``remaining_usd`` is null (nothing to deplete; the wallet
    # is the limiter instead). Owner-gated route, so the raw $ is cost-safe here.
    ws_row = WorkspaceModel.find_by_id(wid) or {}
    allowance_usd = ws_row.get("monthly_allowance_usd")
    plan_remaining_usd = None
    if allowance_usd is not None and float(allowance_usd) > 0:
        company_mtd = SpendRollupModel.get_spent(
            "company", wid, SpendRollupModel.current_period_month()
        )
        plan_remaining_usd = max(0.0, float(allowance_usd) - company_mtd)

    return {
        "by_user": by_user,
        "by_project": by_project,
        "by_model": by_model,
        "daily": daily,
        "totals": totals,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "credits": {
            "lifetime_topups_usd": lifetime_topups,
            "lifetime_spend_usd": lifetime_spend,
            # Single source of truth shared with the overview block.
            "remaining_usd": WorkspaceModel.credits_remaining_usd(wid),
        },
        "plan": {
            "tier": ws_row.get("plan_tier"),
            "allowance_usd": allowance_usd,
            "remaining_usd": plan_remaining_usd,
        },
        "budget": budget_block,
        "cascade": cascade,
    }


def _billing_cascade(wid: str) -> dict:
    """Company → teams cascade report for the owner billing tab.

    Reads the live enforcement flag, the company's reconciled remaining wallet,
    its optional MTD ceiling, and a per-team (project) row joining each team's
    configured budget (``budget_allocations``) against its current-month spend
    rollup (``spend_rollups`` — NEVER ``SUM(usage_logs)``). Owner-gated + always
    cost-visible (same $-tier as the rest of the billing response).
    """
    from app.models.budget_allocation import BudgetAllocationModel
    from app.models.platform_settings import PlatformSettingsModel
    from app.models.spend_rollup import SpendRollupModel

    enforcement = bool(
        PlatformSettingsModel.get_features().get("billing_enforcement", False)
    )
    company_remaining = WorkspaceModel.credits_remaining_usd(wid)
    ws = WorkspaceModel.find_by_id(wid) or {}
    company_budget_mtd = ws.get("budget_mtd_usd") or None

    current_month = SpendRollupModel.current_period_month()
    projects = ProjectModel.find_by_workspace(wid)
    pids = [p["_id"] for p in projects if p.get("_id")]
    team_budgets = BudgetAllocationModel.list_for_scope_ids("team", pids)

    teams = []
    for p in projects:
        pid = str(p["_id"])
        alloc = team_budgets.get(pid)
        budget = alloc["amount_usd"] if alloc else None
        spend = SpendRollupModel.get_spent("team", pid, current_month)
        remaining = (budget - spend) if budget is not None else None
        teams.append(
            {
                "project_id": pid,
                "name": p.get("name"),
                "budget": budget,
                "spend": spend,
                "remaining": remaining,
            }
        )

    return {
        "enforcement": enforcement,
        "company_remaining": company_remaining,
        "company_budget_mtd": company_budget_mtd,
        "teams": teams,
    }


# ---------------------------------------------------------------------------
# Audit log (owner only)
# ---------------------------------------------------------------------------
@router.get("/{wid}/audit")
def workspace_audit(
    wid: str,
    request: Request,
    user: dict = Depends(workspace_member_dep("owner", "wid")),
):
    """Return paginated audit log entries scoped to this workspace."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    try:
        limit = int(request.query_params.get("limit", 50))
    except (TypeError, ValueError):
        return JSONResponse({"error": "limit must be an integer"}, status_code=400)
    limit = max(1, min(200, limit))

    before = _parse_iso_date(request.query_params.get("before"))
    actor_id = request.query_params.get("actor_id") or None
    if actor_id and not validate_object_id(actor_id):
        return JSONResponse({"error": "Invalid actor_id"}, status_code=400)
    action = request.query_params.get("action") or None

    rows = (
        AuditLogModel.find_by_workspace(
            wid,
            limit=limit,
            before=before,
            actor_id=actor_id,
            action=action,
        )
        or []
    )

    actor_ids = [r.get("admin_id") for r in rows if r.get("admin_id") is not None]
    actor_map = {}
    if actor_ids:
        for u in UserModel.find_by_ids(actor_ids):
            actor_map[str(u["_id"])] = {
                "_id": str(u["_id"]),
                "email": u.get("email"),
                "display_name": (u.get("profile") or {}).get("display_name"),
                "avatar_url": (u.get("profile") or {}).get("avatar_url"),
            }

    entries = []
    last_created_at = None
    for r in rows:
        created = r.get("created_at")
        if isinstance(created, str):
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if created_dt.tzinfo is not None:
                    created_dt = created_dt.replace(tzinfo=None)
            except (ValueError, TypeError):
                created_dt = None
        else:
            created_dt = created if isinstance(created, datetime) else None
        entry = {
            "_id": str(r["_id"]) if r.get("_id") else None,
            "action": r.get("action"),
            "target_type": r.get("target_type"),
            "target_id": str(r["target_id"]) if r.get("target_id") else None,
            "details": serialize_doc(r.get("details") or {}),
            "created_at": created_dt.isoformat() if created_dt else created,
        }
        aid = r.get("admin_id")
        aid_str = str(aid) if aid is not None else None
        entry["actor"] = actor_map.get(aid_str) if aid_str else None
        entries.append(entry)
        if created_dt is not None:
            last_created_at = created_dt

    next_before = None
    if last_created_at is not None and len(rows) >= limit:
        next_before = last_created_at.isoformat()

    return {"entries": entries, "next_before": next_before}


# ---------------------------------------------------------------------------
# Billing — credit ledger (owner only)
# ---------------------------------------------------------------------------
@router.post("/{wid}/billing/credits")
async def add_credits(
    wid: str,
    request: Request,
    user: dict = Depends(require_admin),
):
    """Append a manual ledger entry and update workspace.credits_balance_usd.

    Super-admin ONLY (``require_admin``) — the workspace-member ``owner`` gate it
    used to carry was satisfied by every user on their own auto-provisioned
    personal workspace, which let any account self-mint unlimited credit and
    defeat prepaid billing enforcement. Funding is now an admin/holding-operator
    action, mirroring ``admin_holding.charge_company``. The GET ledger route
    below stays owner-scoped (read-only).
    """
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    data = await _json_body(request)

    try:
        amount = float(data.get("amount_usd"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "amount_usd (number) is required"}, status_code=400)

    type_ = (data.get("type") or "top_up").strip().lower()
    if type_ not in ("top_up", "adjustment", "refund"):
        return JSONResponse(
            {"error": "type must be one of 'top_up' | 'adjustment' | 'refund'"},
            status_code=400,
        )

    # A ``top_up`` must add credit — reject a zero/negative top-up so a funding
    # call can't be used to silently drain a wallet. (adjustment/refund may be
    # signed; that's their purpose.)
    if type_ == "top_up" and amount <= 0:
        return JSONResponse(
            {"error": "amount_usd must be positive for a top_up"},
            status_code=400,
        )

    note = (data.get("note") or "").strip()

    ws = WorkspaceModel.find_by_id(wid)
    if not ws:
        return JSONResponse({"error": "Workspace not found"}, status_code=404)

    entry = CreditLedgerModel.add_entry(
        workspace_id=wid,
        amount_usd=amount,
        type=type_,
        note=note,
        added_by=user["_id"],
    )

    new_balance = float(ws.get("credits_balance_usd") or 0) + amount
    WorkspaceModel.update(wid, {"credits_balance_usd": new_balance})

    return JSONResponse(
        {"entry": serialize_doc(entry), "credits_balance_usd": new_balance},
        status_code=201,
    )


@router.get("/{wid}/billing/ledger")
def list_ledger(
    wid: str,
    request: Request,
    user: dict = Depends(workspace_member_dep("owner", "wid")),
):
    """Return paginated ledger entries (most recent first)."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    try:
        limit = int(request.query_params.get("limit", 100))
        skip = int(request.query_params.get("skip", 0))
    except ValueError:
        return JSONResponse({"error": "limit/skip must be integers"}, status_code=400)
    limit = max(1, min(500, limit))

    rows = CreditLedgerModel.find_by_workspace(wid, limit=limit, skip=skip)

    uid_strs = [r["added_by"] for r in rows if r.get("added_by") is not None]
    user_map = {}
    if uid_strs:
        for u in UserModel.find_by_ids(uid_strs):
            user_map[str(u["_id"])] = {
                "email": u.get("email"),
                "display_name": (u.get("profile") or {}).get("display_name"),
            }

    out = []
    for r in rows:
        row = serialize_doc(r)
        added_by_str = str(r["added_by"]) if r.get("added_by") else None
        info = user_map.get(added_by_str, {}) if added_by_str else {}
        row["added_by_user"] = {
            "id": added_by_str,
            "email": info.get("email"),
            "display_name": info.get("display_name"),
        }
        out.append(row)

    total = float(CreditLedgerModel.sum_credits(wid))
    return {"entries": out, "total_credits_usd": total}


# ===========================================================================
# Groups (translated from app/routes/groups.py — same /api/workspaces prefix)
# ===========================================================================
@router.post("/{wid}/groups")
async def create_group(
    wid: str,
    request: Request,
    user: dict = Depends(workspace_member_dep("admin", "wid")),
):
    """Create a new group within the workspace."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)

    data = await _json_body(request)

    name = (data.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    if len(name) > 80:
        return JSONResponse({"error": "name must be at most 80 characters"}, status_code=400)

    color = data.get("color") or "#5c9aed"
    icon = data.get("icon")
    description = data.get("description")

    try:
        doc = GroupModel.create(
            workspace_id=wid,
            name=name,
            created_by=user["_id"],
            color=color,
            icon=icon,
            description=description,
        )
    except IntegrityError:
        return JSONResponse(
            {
                "error": "A group with that name already exists in this workspace",
                "code": "group_name_exists",
            },
            status_code=409,
        )

    return JSONResponse(_serialize(doc), status_code=201)


@router.get("/{wid}/groups/list")
def list_groups(wid: str, user: dict = Depends(workspace_member_dep("viewer", "wid"))):
    """List all groups in a workspace."""
    if not validate_object_id(wid):
        return JSONResponse({"error": "Invalid workspace ID"}, status_code=400)
    groups = GroupModel.find_by_workspace(wid) or []
    return {"groups": [_serialize(g) for g in groups]}


@router.get("/{wid}/groups/{gid}")
def get_group(
    wid: str,
    gid: str,
    user: dict = Depends(workspace_member_dep("viewer", "wid")),
):
    """Group detail + hydrated member list."""
    if not validate_object_id(wid) or not validate_object_id(gid):
        return JSONResponse({"error": "Invalid ID"}, status_code=400)

    group = GroupModel.find_by_id(gid)
    if not group or str(group.get("workspace_id")) != str(wid):
        return JSONResponse({"error": "Group not found"}, status_code=404)

    rows = GroupMemberModel.find_by_group(gid) or []
    user_ids = [r["user_id"] for r in rows if r.get("user_id") is not None]
    user_map = {}
    if user_ids:
        for u in UserModel.find_by_ids(user_ids):
            user_map[str(u["_id"])] = {
                "email": u.get("email"),
                "display_name": (u.get("profile") or {}).get("display_name"),
                "avatar_url": (u.get("profile") or {}).get("avatar_url"),
            }

    members = []
    for r in rows:
        uid_str = str(r["user_id"]) if r.get("user_id") is not None else None
        info = user_map.get(uid_str, {}) if uid_str else {}
        row = _serialize(r)
        row["user"] = {
            "id": uid_str,
            "email": info.get("email"),
            "display_name": info.get("display_name"),
            "avatar_url": info.get("avatar_url"),
        }
        members.append(row)

    out = _serialize(group)
    out["members"] = members
    return out


@router.put("/{wid}/groups/{gid}")
async def update_group(
    wid: str,
    gid: str,
    request: Request,
    user: dict = Depends(workspace_member_dep("admin", "wid")),
):
    """Whitelisted update — name / color / icon / description."""
    if not validate_object_id(wid) or not validate_object_id(gid):
        return JSONResponse({"error": "Invalid ID"}, status_code=400)

    group = GroupModel.find_by_id(gid)
    if not group or str(group.get("workspace_id")) != str(wid):
        return JSONResponse({"error": "Group not found"}, status_code=404)

    data = await _json_body(request)
    update_data = {}
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            return JSONResponse({"error": "name cannot be empty"}, status_code=400)
        if len(name) > 80:
            return JSONResponse({"error": "name must be at most 80 characters"}, status_code=400)
        update_data["name"] = name
    if "color" in data:
        update_data["color"] = data["color"]
    if "icon" in data:
        update_data["icon"] = data["icon"]
    if "description" in data:
        update_data["description"] = data["description"]

    if not update_data:
        return JSONResponse({"error": "No valid fields to update"}, status_code=400)

    try:
        GroupModel.update(gid, update_data)
    except IntegrityError:
        return JSONResponse(
            {
                "error": "A group with that name already exists in this workspace",
                "code": "group_name_exists",
            },
            status_code=409,
        )
    return _serialize(GroupModel.find_by_id(gid))


@router.delete("/{wid}/groups/{gid}")
def delete_group(
    wid: str,
    gid: str,
    user: dict = Depends(workspace_member_dep("admin", "wid")),
):
    """Hard-delete + cascade (group_members + project_group_access)."""
    if not validate_object_id(wid) or not validate_object_id(gid):
        return JSONResponse({"error": "Invalid ID"}, status_code=400)

    group = GroupModel.find_by_id(gid)
    if not group or str(group.get("workspace_id")) != str(wid):
        return JSONResponse({"error": "Group not found"}, status_code=404)

    GroupMemberModel.delete_by_group(gid)
    ProjectGroupAccessModel.delete_by_group(gid)
    GroupModel.delete(gid)
    return {"message": "Group deleted"}


@router.post("/{wid}/groups/{gid}/members")
async def add_group_member(
    wid: str,
    gid: str,
    request: Request,
    user: dict = Depends(workspace_member_dep("admin", "wid")),
):
    """Add a workspace user to a group. Recomputes ``member_count``."""
    if not validate_object_id(wid) or not validate_object_id(gid):
        return JSONResponse({"error": "Invalid ID"}, status_code=400)

    group = GroupModel.find_by_id(gid)
    if not group or str(group.get("workspace_id")) != str(wid):
        return JSONResponse({"error": "Group not found"}, status_code=404)

    data = await _json_body(request)
    user_id = (data.get("user_id") or "").strip()
    if not user_id or not validate_object_id(user_id):
        return JSONResponse({"error": "Valid user_id is required"}, status_code=400)

    target_user = UserModel.find_by_id(user_id)
    if not target_user:
        return JSONResponse({"error": "User not found"}, status_code=404)

    if not check_workspace_access(user_id, wid, "viewer"):
        return JSONResponse(
            {"error": "User is not a member of the parent workspace", "code": "not_in_workspace"},
            status_code=400,
        )

    member = GroupMemberModel.add(gid, user_id, added_by=user["_id"])
    GroupModel.recompute_member_count(gid)
    return JSONResponse(_serialize(member), status_code=201)


@router.delete("/{wid}/groups/{gid}/members/{uid}")
def remove_group_member(
    wid: str,
    gid: str,
    uid: str,
    user: dict = Depends(workspace_member_dep("admin", "wid")),
):
    """Remove a user from a group. Recomputes ``member_count``."""
    if not validate_object_id(wid) or not validate_object_id(gid) or not validate_object_id(uid):
        return JSONResponse({"error": "Invalid ID"}, status_code=400)

    group = GroupModel.find_by_id(gid)
    if not group or str(group.get("workspace_id")) != str(wid):
        return JSONResponse({"error": "Group not found"}, status_code=404)

    if not GroupMemberModel.is_member(gid, uid):
        return JSONResponse({"error": "Member not found"}, status_code=404)

    GroupMemberModel.remove(gid, uid)
    GroupModel.recompute_member_count(gid)
    return {"message": "Member removed"}


__all__ = ["router"]
