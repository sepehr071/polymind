"""Permissions helpers for workspace + project access checks.

Module-level functions only — no class. Decorators that consume these helpers
live in `app.utils.decorators`.
"""

import logging

from app.extensions import db
from app.models.workspace_member import (
    WorkspaceMemberModel,
    ROLE_HIERARCHY,
)

_logger = logging.getLogger(__name__)

# Legacy roles that callers may pass; mapped to canonical equivalents for one transition release.
_LEGACY_ROLE_MAP = {
    'guest': 'viewer',
    'billing-admin': 'editor',
    'admin': 'owner',
}


def _normalize_min_role(min_role: str) -> str:
    """Map legacy min_role values to canonical ones and emit a deprecation warning."""
    if min_role in _LEGACY_ROLE_MAP:
        canonical = _LEGACY_ROLE_MAP[min_role]
        _logger.warning("permissions: legacy min_role=%r mapped to %r", min_role, canonical)
        return canonical
    return min_role


def _is_super_admin(user_id) -> bool:
    """Global super-admin (user.role='admin') bypass — sees + does anything."""
    if user_id is None:
        return False
    try:
        from app.models.user import UserModel
        u = UserModel.find_by_id(user_id)
        return bool(u and u.get('role') == 'admin')
    except Exception:
        return False


def owned_team_workspace_ids(user_id) -> set:
    """Workspace ids the user actively OWNS that are TEAM (not personal).

    The personal workspace EVERY user owns is excluded — gating $-visibility on
    membership-ownership alone would leak price to every user (each owns their
    personal ws as 'owner'). Returns ids in the SAME form
    ``WorkspaceMemberModel.find_by_user`` yields them, so set-intersections at
    call sites (e.g. ``/usage/me`` masking) keep working unchanged.
    """
    from sqlalchemy import select
    from app.models.workspace import Workspace
    from app.utils.ids import to_uuid

    memberships = WorkspaceMemberModel.find_by_user(user_id, status="active")
    owned = {
        m["workspace_id"]
        for m in memberships
        if m.get("role") == "owner" and m.get("workspace_id") is not None
    }
    if not owned:
        return set()
    by_uuid: dict = {}
    for w in owned:
        u = to_uuid(w)
        if u is not None:
            by_uuid[u] = w
    if not by_uuid:
        return set()
    team_uuids = set(
        db.session.execute(
            select(Workspace.id).where(
                Workspace.id.in_(list(by_uuid.keys())),
                Workspace.is_personal.is_(False),
            )
        ).scalars().all()
    )
    return {orig for u, orig in by_uuid.items() if u in team_uuids}


def money_view(user, workspace=None) -> str:
    """Money-visibility tier for a viewer: ``'cost'`` | ``'price'`` | ``'none'``.

    * ``'cost'``  — super-admin (CEO): true upstream cost + price + margin.
    * ``'price'`` — owner of a TEAM workspace: marked-up price only (no margin).
    * ``'none'``  — everyone else: Polymind Credits + tokens, NEVER any $.

    ``workspace`` (a workspace dict) scopes the check to one company; omit it to
    ask "does this user see price ANYWHERE" (owns any team ws). Ownership is the
    active ``owner`` membership role on a TEAM workspace.
    """
    if not user:
        return "none"
    if user.get("role") == "admin":
        return "cost"
    if workspace is not None:
        is_team = (
            workspace.get("type") == "team" or workspace.get("is_personal") is False
        )
        wid = workspace.get("_id") or workspace.get("id")
        if not is_team or not wid:
            return "none"
        # Ownership = the ``owner`` membership role (org-admin). Keycloak org
        # workspaces carry no ``owner_user_id``, so the column is not the truth.
        member = WorkspaceMemberModel.find(str(wid), str(user.get("_id")))
        if member and member.get("status") == "active" and member.get("role") == "owner":
            return "price"
        return "none"
    return "price" if owned_team_workspace_ids(user.get("_id")) else "none"


# USD-ish keys stripped when money_view == 'none' on workspace / billing blobs.
_WS_USD_KEYS = (
    "credits_balance_usd",
    "credits_remaining_usd",
    "budget_mtd_usd",
    "monthly_allowance_usd",
    "spend_mtd_usd",
    "remaining_usd",
    "cost_usd",
    "total_cost",
    "upstream_cost_usd",
    "margin_usd",
)


def mask_usd_fields(doc, view: str):
    """Null dollar keys on a dict when ``view == 'none'``. Mutates and returns doc.

    Credits-safe fields (``credits``, ``total_credits``) are left alone.
    """
    if not isinstance(doc, dict) or view != "none":
        return doc
    for k in _WS_USD_KEYS:
        if k in doc:
            doc[k] = None
    return doc


def mask_image_money(img, user):
    """Strip ``cost_usd`` / batch totals for non-price viewers; keep ``credits``."""
    if not isinstance(img, dict):
        return img
    view = money_view(user)
    if view != "none":
        return img
    img = dict(img)
    img["cost_usd"] = None
    meta = img.get("metadata")
    if isinstance(meta, dict):
        meta = dict(meta)
        meta.pop("cost_usd", None)
        batch = meta.get("batch")
        if isinstance(batch, dict):
            batch = dict(batch)
            batch.pop("total_cost_usd", None)
            meta["batch"] = batch
        img["metadata"] = meta
    return img


def get_workspace_role(user_id, workspace_id):
    """Return the active role string for a user in a workspace, or None.

    Returns one of the keys of ROLE_HIERARCHY, or None if there is no
    active membership.
    """
    member = WorkspaceMemberModel.find(workspace_id, user_id)
    if not member or member.get('status') != 'active':
        return None
    return member.get('role')


def is_workspace_member_or_admin(user: dict, workspace_id) -> bool:
    """True iff *user* (DB-loaded dict) is super-admin or an ACTIVE member of
    *workspace_id*. Reads ``user['role']`` from the dict — never a JWT claim."""
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    if not workspace_id:
        return False
    return get_workspace_role(user.get("_id"), str(workspace_id)) is not None


WORKSPACE_ACCESS_DENIED = {
    "error": "Workspace access denied",
    "code": "workspace_access_denied",
    "status": 403,
}


def conversation_workspace_denied(conversation, user: dict) -> bool:
    """True when the chat is stamped into an org the caller cannot use.

    Unstamped chats (legacy) fall through to the owner/share checks.
    """
    wid = (conversation or {}).get("workspace_id")
    if not wid:
        return False
    return not is_workspace_member_or_admin(user, wid)


def check_workspace_access(user_id, workspace_id, min_role: str = 'viewer') -> bool:
    """Return True iff the user has at least `min_role` in the workspace.

    Global `user.role='admin'` is a super-admin bypass — always True.
    """
    if _is_super_admin(user_id):
        return True
    min_role = _normalize_min_role(min_role)
    role = get_workspace_role(user_id, workspace_id)
    if role is None:
        return False
    # Normalize actual stored role through legacy map too (handles old DB rows).
    role = _LEGACY_ROLE_MAP.get(role, role)
    if min_role not in ROLE_HIERARCHY or role not in ROLE_HIERARCHY:
        return False
    return ROLE_HIERARCHY[role] >= ROLE_HIERARCHY[min_role]


def _meets(role: str, min_role: str) -> bool:
    """True if role grants at least min_role under the project access semantics."""
    min_role = _normalize_min_role(min_role)
    # Normalize actual stored role through legacy map too (handles old DB rows).
    role = _LEGACY_ROLE_MAP.get(role, role) if role else role
    if not role or role not in ROLE_HIERARCHY or min_role not in ROLE_HIERARCHY:
        return False
    return ROLE_HIERARCHY[role] >= ROLE_HIERARCHY[min_role]


def check_project_access(user_id, project_id, min_role: str = 'viewer') -> bool:
    """Bool: user has at least min_role in project.

    Resolution order (any one passing returns True):
      0. Global super-admin (user.role='admin').
      1. Explicit project_members row.
      2. Group-based access: project_group_access × group_members.
    Company membership alone does NOT open a team.
    """
    from app.models.project import ProjectModel
    from app.models.project_member import ProjectMemberModel

    if _is_super_admin(user_id):
        return True

    project = ProjectModel.find_by_id(project_id)
    if not project:
        return False

    # 1. Explicit project membership.
    membership = ProjectMemberModel.find(project_id, user_id)
    if membership and _meets(membership.get('role'), min_role):
        return True

    # 2. Group access — best-effort lookup; never raise on import errors.
    try:
        from app.models.project_group_access import ProjectGroupAccessModel
        group_grants = ProjectGroupAccessModel.find_groups_with_access(project_id, user_id)
        for grant in group_grants:
            if _meets(grant.get('role'), min_role):
                return True
    except Exception:
        # Defensive — collection may not exist in legacy DBs.
        pass

    return False


def resolve_conversation_access(conversation, user_id, min_role: str = 'viewer'):
    """Tiered access for a conversation: owner, shared-team member, or denied.

    Returns ``(role, error)`` where ``role`` is ``'owner'`` | ``'member'`` and
    ``error`` is ``None`` on success, or ``(None, (message, status))`` on
    failure.

    * Owner — the conversation's ``user_id``. A project-scoped chat additionally
      requires the owner to still hold ``min_role`` on that project (an owner
      removed from the project → 403), mirroring the historical
      ``_fetch_owned_conversation`` semantics.
    * Member — not the owner, but a member of at least one team the conversation
      is actively shared into (a ``conversation_shares`` team grant). Members
      read AND contribute (collaborative chat).
    * Denied — neither → 404 (never reveal a chat's existence).

    This is the single source of truth both the conversations router and the
    chat router consult to widen the strict owner check.
    """
    if not conversation:
        return None, ('Conversation not found', 404)
    if str(conversation.get('user_id')) == str(user_id):
        pid = conversation.get('project_id')
        if pid and not check_project_access(user_id, str(pid), min_role):
            return None, ('Project access denied', 403)
        return 'owner', None
    from app.models.conversation_share import ConversationShareModel
    cid = conversation.get('_id') or conversation.get('id')
    if cid and ConversationShareModel.user_can_access(str(cid), user_id):
        return 'member', None
    return None, ('Conversation not found', 404)


def get_project_role(user_id, project_id, project=None):
    """Effective role of user on project (max of explicit membership + group grant).

    Company workspace membership alone does NOT grant a project role.

    ``project`` may be a pre-fetched project row (as returned by
    ``ProjectModel.find_by_id`` / ``find_by_workspace``). When supplied, the
    re-fetch is skipped. Pass it when the caller already holds the row to avoid
    a redundant query.
    """
    from app.models.project import ProjectModel
    from app.models.project_member import ProjectMemberModel

    if project is None:
        project = ProjectModel.find_by_id(project_id)
    if not project:
        return None

    explicit = None
    m = ProjectMemberModel.find(project_id, user_id)
    if m:
        explicit = m.get('role')

    group_role = None
    try:
        from app.models.project_group_access import ProjectGroupAccessModel
        grants = ProjectGroupAccessModel.find_groups_with_access(project_id, user_id)
        for g in grants:
            r = g.get('role')
            if r in ROLE_HIERARCHY:
                if group_role is None or ROLE_HIERARCHY[r] > ROLE_HIERARCHY[group_role]:
                    group_role = r
    except Exception:
        group_role = None

    # No workspace-role fallback — company membership alone must not open a team.
    candidates = [r for r in (explicit, group_role) if r in ROLE_HIERARCHY]
    if not candidates:
        return None
    return max(candidates, key=lambda r: ROLE_HIERARCHY[r])


def get_project_roles_bulk(user_id, projects):
    """Effective project roles for *user_id* across many project rows, in O(1) queries.

    A batched equivalent of calling :func:`get_project_role` once per project —
    explicit project_members + group grants only (no workspace-role fallback).
    Built for list endpoints where the caller already holds the project rows.

    :param projects: an iterable of project rows (dicts with ``_id``/``id`` +
        ``workspace_id``), e.g. the output of ``ProjectModel.find_by_workspace``.
    :returns: ``{str(project_id): role | None}`` — one entry per input row. A value
        of ``None`` means zero access (the caller should skip such projects exactly
        as the per-call ``role is None: continue`` guard does).
    """
    from sqlalchemy import select
    from app.utils.ids import to_uuid

    projects = list(projects)
    if not projects:
        return {}

    # Map each input row to its project-id UUID + string, grouped by workspace.
    # A bad/garbage id coerces to None and resolves to no access (mirrors the
    # single-path, where to_uuid failure inside ProjectMemberModel.find / the
    # group join / get_workspace_role all yield "no row" → None).
    pid_uuid_by_str: dict = {}
    ws_by_pid_str: dict = {}
    workspace_pids: dict = {}  # workspace_id (raw) -> list[project_id_str]
    result: dict = {}
    for p in projects:
        pid_str = str(p['_id'] if '_id' in p else p['id'])
        result[pid_str] = None  # default: zero access until a candidate is found
        try:
            pid_uuid = to_uuid(pid_str)
        except (ValueError, TypeError):
            pid_uuid = None
        pid_uuid_by_str[pid_str] = pid_uuid
        ws_id = p.get('workspace_id')
        ws_by_pid_str[pid_str] = ws_id
        if pid_uuid is not None:
            workspace_pids.setdefault(ws_id, []).append(pid_str)

    pid_uuids = [u for u in pid_uuid_by_str.values() if u is not None]
    try:
        uid = to_uuid(user_id)
    except (ValueError, TypeError):
        uid = None

    # Accumulate candidate roles per project, then collapse with max-of-hierarchy.
    # Each project's candidate list mirrors get_project_role's (explicit, group_role,
    # ws_role) — only roles present in ROLE_HIERARCHY are ever appended.
    candidates: dict = {pid_str: [] for pid_str in result}

    if uid is not None and pid_uuids:
        # 1. Explicit project_members rows for this user across all listed projects.
        from app.models.project_member import ProjectMember
        rows = db.session.execute(
            select(ProjectMember.project_id, ProjectMember.role).where(
                ProjectMember.project_id.in_(pid_uuids),
                ProjectMember.user_id == uid,
            )
        ).all()
        for project_id, role in rows:
            if role in ROLE_HIERARCHY:
                candidates[str(project_id)].append(role)

        # 2. Group-based grants: project_group_access × group_members the user is in,
        #    inner-joined to groups so a grant whose group no longer exists is dropped
        #    (the single-path's `GroupModel.find_by_id(...) -> continue` skip). Per
        #    project we keep the MAX group role, matching the single-path's loop.
        from app.models.project_group_access import ProjectGroupAccess
        from app.models.group_member import GroupMember
        from app.models.group import Group
        grant_rows = db.session.execute(
            select(ProjectGroupAccess.project_id, ProjectGroupAccess.role)
            .join(GroupMember, GroupMember.group_id == ProjectGroupAccess.group_id)
            .join(Group, Group.id == ProjectGroupAccess.group_id)
            .where(
                ProjectGroupAccess.project_id.in_(pid_uuids),
                GroupMember.user_id == uid,
            )
        ).all()
        group_role_by_pid: dict = {}
        for project_id, role in grant_rows:
            if role not in ROLE_HIERARCHY:
                continue
            key = str(project_id)
            best = group_role_by_pid.get(key)
            if best is None or ROLE_HIERARCHY[role] > ROLE_HIERARCHY[best]:
                group_role_by_pid[key] = role
        for pid_str, role in group_role_by_pid.items():
            candidates[pid_str].append(role)

    # No workspace-role fallback (company membership alone does not open a team).

    for pid_str, cands in candidates.items():
        if cands:
            result[pid_str] = max(cands, key=lambda r: ROLE_HIERARCHY[r])

    return result
