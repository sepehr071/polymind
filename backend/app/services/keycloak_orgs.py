"""Mirror Keycloak organizations into company workspaces.

Keycloak is the source of membership. A team workspace is keyed by
``settings.keycloak_org_id``. ``org-admin`` is the company owner;
``workspace-member`` is a non-owner member. ``platform-admin`` may enter
with no organization.
"""
from __future__ import annotations

import logging

from app.models.user import UserModel
from app.models.workspace import WorkspaceModel
from app.models.workspace_member import WorkspaceMemberModel
from app.services.keycloak import KeycloakClient

logger = logging.getLogger(__name__)


class KcAccessDenied(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def product_member_role(realm_roles: list[str] | set[str]) -> str:
    """Company membership implied by realm roles. Owner only for org-admin."""
    roles = set(realm_roles or [])
    if KeycloakClient.ROLE_ORG_ADMIN in roles or KeycloakClient.ROLE_PLATFORM_ADMIN in roles:
        return 'owner'
    return 'viewer'


def resolve_organizations(
    client: KeycloakClient,
    claims: dict,
    user_sub: str,
    access_token: str | None = None,
) -> list[dict]:
    """Org membership beside realm roles.

    The user's own account API is the source. Admin API and the token
    ``organization`` claim are fallbacks (admin creds are often unset, and
    the client may not have the organization scope).
    """
    if access_token:
        try:
            owned = client.account_organizations(access_token)
        except Exception as exc:  # noqa: BLE001 — claim fallback still gates login
            logger.warning('keycloak account org lookup failed: %s', exc)
            owned = None
        if owned is not None:
            return owned
    try:
        remote = client.organizations_for_user(user_sub)
    except Exception as exc:  # noqa: BLE001 — claim fallback still gates login
        logger.warning('keycloak org lookup failed: %s', exc)
        remote = None
    if remote is not None:
        return remote
    return KeycloakClient.organizations_from_claims(claims)


def assert_can_enter(product_role: str | None, orgs: list[dict]) -> None:
    if not product_role:
        raise KcAccessDenied(
            'kc_role_required',
            'برای ورود یکی از نقش‌های platform-admin، org-admin یا workspace-member لازم است.',
        )
    if product_role != 'admin' and not orgs:
        raise KcAccessDenied(
            'kc_org_required',
            'حساب شما عضو هیچ سازمانی نیست.',
        )


def sync_user_organizations(user: dict, orgs: list[dict], realm_roles: set[str]) -> None:
    """Ensure this user is a member of exactly the Keycloak orgs they belong to."""
    member_role = product_member_role(realm_roles)
    user_id = str(user['_id'])
    linked: set[str] = set()
    ordered: list[str] = []
    for org in orgs:
        ws = _ensure_org_workspace(org)
        wid = str(ws['_id'])
        if wid not in linked:
            ordered.append(wid)
        linked.add(wid)
        _ensure_membership(wid, user_id, member_role)
    _drop_stale_org_memberships(user_id, linked)
    _sync_active_workspace(user, ordered)


def _sync_active_workspace(user: dict, linked_ordered: list[str]) -> None:
    """Point ``active_workspace_id`` at a linked org when it is not one.

    Admins may hold a non-member company (the admin org switcher), so their
    pointer is only filled when empty.
    """
    current = user.get('active_workspace_id')
    current = str(current) if current else None
    if user.get('role') == 'admin':
        if current or not linked_ordered:
            return
    elif current in linked_ordered:
        return
    target = linked_ordered[0] if linked_ordered else None
    if target == current:
        return
    UserModel.set_active_workspace(str(user['_id']), target)
    user['active_workspace_id'] = target


def refresh_org_members(workspace_id: str, client: KeycloakClient) -> None:
    """Replace the company member list with the live Keycloak org roster."""
    ws = WorkspaceModel.find_by_id(workspace_id)
    if not ws:
        return
    org_id = (ws.get('settings') or {}).get('keycloak_org_id')
    if not org_id:
        return
    try:
        members = client.organization_members(str(org_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning('keycloak member refresh failed: %s', exc)
        return
    if members is None:
        return
    seen: set[str] = set()
    for member in members:
        try:
            user = _upsert_directory_user(member)
        except Exception as exc:  # noqa: BLE001 — one bad row must not wipe the roster
            logger.warning('keycloak member upsert skipped: %s', exc)
            continue
        if not user:
            continue
        uid = str(user['_id'])
        seen.add(uid)
        _ensure_membership(
            str(ws['_id']),
            uid,
            product_member_role(member.get('realm_roles') or []),
        )
    for row in WorkspaceMemberModel.find_by_workspace(str(ws['_id']), status='active') or []:
        uid = str(row.get('user_id') or '')
        if uid and uid not in seen:
            WorkspaceMemberModel.remove(str(ws['_id']), uid)


def _ensure_org_workspace(org: dict) -> dict:
    existing = WorkspaceModel.find_by_keycloak_org_id(org['id'])
    if existing:
        return existing
    # No single owner: ownership is the ``owner`` membership role (org-admin),
    # never whoever happened to log in first.
    ws = WorkspaceModel.create(
        name=org.get('name') or org['id'],
        owner_id=None,
        type='team',
        settings={'keycloak_org_id': org['id'], 'keycloak_org_alias': org.get('alias')},
    )
    return ws


def _ensure_membership(workspace_id: str, user_id: str, role: str) -> None:
    current = WorkspaceMemberModel.find(workspace_id, user_id)
    if current is None:
        WorkspaceMemberModel.add(workspace_id, user_id, role, status='active')
        return
    if current.get('role') != role:
        WorkspaceMemberModel.update_role(workspace_id, user_id, role)


def _drop_stale_org_memberships(user_id: str, keep_workspace_ids: set[str]) -> None:
    for row in WorkspaceMemberModel.find_by_user(user_id) or []:
        wid = str(row.get('workspace_id') or '')
        if not wid or wid in keep_workspace_ids:
            continue
        ws = WorkspaceModel.find_by_id(wid)
        if not ws:
            continue
        if (ws.get('settings') or {}).get('keycloak_org_id'):
            WorkspaceMemberModel.remove(wid, user_id)


def _upsert_directory_user(member: dict) -> dict | None:
    sub = member.get('id')
    email = (member.get('email') or '').strip()
    if not email and member.get('username'):
        email = f"{member['username']}@polymind.kc.local"
    if not sub or not email:
        return None
    mapped = KeycloakClient.map_roles({'realm_access': {'roles': member.get('realm_roles') or []}})
    return UserModel.upsert_from_keycloak(
        sub=sub,
        email=email,
        display_name=member.get('display_name') or email,
        role=mapped or 'user',
        email_verified=True,
    )
