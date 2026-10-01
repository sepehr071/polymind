"""Projects API router, translated from app/routes/projects.py.

Every Flask handler maps 1:1 to a FastAPI path operation. The router-level
``Depends(flask_ctx)`` binds a Flask app_context to each request, so the legacy
model facades + permission helpers are reused VERBATIM.

Decorator translation:
    @jwt_required() + @active_user_required      -> Depends(require_active)
    @project_role(min_role=X, id_kwarg='pid')    -> Depends(project_role_dep(X, 'pid'))

Bodies are read via ``await request.json()`` (the legacy routes used
``request.get_json(silent=True) or {}`` and tolerated missing/garbage bodies).
Response shapes are preserved EXACTLY — FLAT JSON, legacy ``_id`` alias from the
model ``to_dict()`` — so the frontend contract is unchanged. ``response_model`` is
deliberately NOT used (it would strip fields).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import (
    flask_ctx,
    project_role_dep,
    require_active,
    require_manager_or_admin,
)
from app.models.budget_allocation import BudgetAllocationModel
from app.models.conversation import ConversationModel
from app.models.folder import FolderModel
from app.models.group import GroupModel
from app.models.group_member import GroupMemberModel
from app.models.project import ProjectModel
from app.models.project_group_access import ProjectGroupAccessModel
from app.models.project_member import ProjectMemberModel
from app.models.project_webhook import ProjectWebhookModel
from app.models.spend_rollup import SpendRollupModel
from app.models.user import UserModel
from app.models.workspace import WorkspaceModel
from app.utils.helpers import serialize_doc, validate_object_id
from app.utils.permissions import check_workspace_access, get_project_role, get_project_roles_bulk

# Router-level dependency: every request runs inside the Flask app_context.
router = APIRouter(dependencies=[Depends(flask_ctx)])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALLOWED_MEMBER_ROLES = {'viewer', 'editor'}
_UPDATABLE_FIELDS = {'name', 'color', 'icon', 'description', 'archived'}


async def _json_body(request: Request) -> dict:
    """Read the request JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _serialize(doc):
    return serialize_doc(doc)


def _count_explicit_owners(project_id) -> int:
    """Count rows in project_members with role='owner' for this project."""
    return ProjectMemberModel.count_by_project_role(project_id, 'owner')


def _serialize_webhook(doc, include_secret=False):
    """Serialize a webhook doc; secret omitted unless explicitly requested."""
    if doc is None:
        return None
    out = _serialize(doc)
    if not include_secret:
        out.pop('secret', None)
    return out


def _budget_remaining(budget: dict | None, spend: float):
    """Remaining = amount - spend for an ENABLED budget with an amount set,
    else None (unlimited / no cap / disabled)."""
    if not budget or not budget.get('enabled'):
        return None
    amount = budget.get('amount_usd')
    if amount is None:
        return None
    return float(amount) - float(spend or 0)


def _budget_cost_visible(user: dict, project: dict) -> bool:
    """$-visibility for the team budget surface — owner-only, like the rest of
    the billing surface (``/usage/me``, ``analytics_service.budget()``).

    The ``$`` figures on ``GET /budget`` expose each member's GLOBAL (cross-
    company) month-to-date spend + per-user/team ceilings. Per the holding policy
    "cost figures are owner-only", those must be masked for non-owner callers.
    Visible iff the caller is a super-admin, an explicit project owner, or the
    parent workspace owner. (``project_role_dep('viewer')`` still gates the route
    itself — this only controls whether the dollar fields are populated.)
    """
    uid = user.get('_id')
    # Super-admin sees everything (mirrors check_project/workspace_access bypass).
    if user.get('role') == 'admin':
        return True
    # Explicit project-owner membership.
    pm = ProjectMemberModel.find(project['_id'], uid)
    if pm and pm.get('role') == 'owner':
        return True
    # Parent workspace owner (workspace owners are implicit project owners).
    from app.models.workspace_member import WorkspaceMemberModel
    wm = WorkspaceMemberModel.find(project.get('workspace_id'), uid)
    if wm and wm.get('role') == 'owner' and wm.get('status') == 'active':
        return True
    return False


def _mask_budget(budget: dict | None, cost_visible: bool) -> dict | None:
    """Null the dollar ``amount_usd`` on a budget row when cost is not visible.

    Non-$ posture (``enabled``, scope identifiers) is preserved so the UI can
    still show "a cap is configured" without leaking its value."""
    if budget is None or cost_visible:
        return budget
    masked = dict(budget)
    masked['amount_usd'] = None
    return masked


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------

@router.get("/list")
def list_projects(workspace_id: str | None = None, user: dict = Depends(require_active)):
    """List projects in a workspace the caller can access.

    Required query param: ?workspace_id=<wid>
    """
    user_id_str = str(user['_id'])

    if not workspace_id:
        return JSONResponse({'error': 'workspace_id query param is required'}, status_code=400)
    if not validate_object_id(workspace_id):
        return JSONResponse({'error': 'Invalid workspace_id'}, status_code=400)

    workspace = WorkspaceModel.find_by_id(workspace_id)
    if not workspace:
        return JSONResponse({'error': 'Workspace not found'}, status_code=404)

    if not check_workspace_access(user_id_str, workspace_id, 'viewer'):
        return JSONResponse({'error': 'Workspace access denied', 'status': 403}, status_code=403)

    projects = ProjectModel.find_by_workspace(workspace_id, archived=False) or []

    # One batched role resolution instead of get_project_role per project (which
    # re-fetched each row + ran ~4 queries each → 80-200 queries for a full list).
    roles = get_project_roles_bulk(user_id_str, projects)

    out = []
    for p in projects:
        pid_str = str(p['_id'])
        role = roles.get(pid_str)
        # Skip projects the caller has zero access to (explicit membership or
        # group grant only — company membership alone does not open a team).
        if role is None:
            continue
        row = _serialize(p)
        row['member_role'] = role
        out.append(row)

    return out


@router.post("/create")
async def create_project(
    request: Request,
    user: dict = Depends(require_active),
    # Team creation is admin/manager-only (top-down holding model).
    _: dict = Depends(require_manager_or_admin),
):
    """Create a new project. Caller must be editor or owner of the workspace."""
    user_id = user['_id']
    user_id_str = str(user_id)

    data = await _json_body(request)

    workspace_id = data.get('workspace_id')
    if not workspace_id:
        return JSONResponse({'error': 'workspace_id is required'}, status_code=400)
    if not validate_object_id(workspace_id):
        return JSONResponse({'error': 'Invalid workspace_id'}, status_code=400)

    workspace = WorkspaceModel.find_by_id(workspace_id)
    if not workspace:
        return JSONResponse({'error': 'Workspace not found'}, status_code=404)

    if not check_workspace_access(user_id_str, workspace_id, 'editor'):
        return JSONResponse({'error': 'Workspace access denied', 'status': 403}, status_code=403)

    name = (data.get('name') or '').strip()
    if not name:
        return JSONResponse({'error': 'name is required'}, status_code=400)
    if len(name) > 100:
        return JSONResponse({'error': 'name must be at most 100 characters'}, status_code=400)

    color = data.get('color') or '#5c9aed'
    icon = data.get('icon')
    description = data.get('description')

    project = ProjectModel.create(
        workspace_id=workspace_id,
        name=name,
        created_by=user_id,
        color=color,
        icon=icon,
        description=description,
    )

    ProjectMemberModel.add(
        project_id=project['_id'],
        user_id=user_id,
        role='owner',
        added_by=user_id,
    )

    return JSONResponse(_serialize(project), status_code=201)


@router.get("/{pid}")
def get_project(pid: str, user: dict = Depends(project_role_dep('viewer', 'pid'))):
    """Return project doc + caller's role."""
    if not validate_object_id(pid):
        return JSONResponse({'error': 'Invalid project ID'}, status_code=400)

    project = ProjectModel.find_by_id(pid)
    if not project:
        return JSONResponse({'error': 'Project not found'}, status_code=404)

    user_id_str = str(user['_id'])
    role = get_project_role(user_id_str, pid)

    out = _serialize(project)
    out['member_role'] = role
    return out


@router.patch("/{pid}")
async def update_project(pid: str, request: Request,
                         user: dict = Depends(project_role_dep('owner', 'pid'))):
    """Whitelisted update — name, color, icon, description, archived."""
    if not validate_object_id(pid):
        return JSONResponse({'error': 'Invalid project ID'}, status_code=400)

    project = ProjectModel.find_by_id(pid)
    if not project:
        return JSONResponse({'error': 'Project not found'}, status_code=404)

    data = await _json_body(request)
    update_data = {}

    if 'name' in data:
        name = (data['name'] or '').strip()
        if not name:
            return JSONResponse({'error': 'name cannot be empty'}, status_code=400)
        if len(name) > 100:
            return JSONResponse({'error': 'name must be at most 100 characters'}, status_code=400)
        update_data['name'] = name

    if 'color' in data:
        update_data['color'] = data['color']

    if 'icon' in data:
        update_data['icon'] = data['icon']

    if 'description' in data:
        update_data['description'] = data['description']

    if 'archived' in data:
        if not isinstance(data['archived'], bool):
            return JSONResponse({'error': 'archived must be a boolean'}, status_code=400)
        update_data['archived'] = data['archived']

    if 'default_model' in data:
        update_data['default_model'] = data['default_model']

    if 'default_temperature' in data:
        update_data['default_temperature'] = data['default_temperature']

    if not update_data:
        return JSONResponse({'error': 'No valid fields to update'}, status_code=400)

    try:
        ProjectModel.update(pid, update_data)
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)
    updated = ProjectModel.find_by_id(pid)
    return _serialize(updated)


@router.delete("/{pid}")
def delete_project(pid: str, user: dict = Depends(project_role_dep('owner', 'pid'))):
    """Hard-delete project + cascade member rows. Folders + conversations
    with this `project_id` get reset to NULL (back to "Unfiled" personal scope).
    """
    if not validate_object_id(pid):
        return JSONResponse({'error': 'Invalid project ID'}, status_code=400)

    project = ProjectModel.find_by_id(pid)
    if not project:
        return JSONResponse({'error': 'Project not found'}, status_code=404)

    # Cascade-delete project_members.
    ProjectMemberModel.delete_by_project(pid)

    # Reset project_id on folders + conversations to NULL.
    FolderModel.null_project_for_project(pid)
    ConversationModel.null_project_for_project(pid)

    ProjectModel.delete(pid)

    return {'message': 'Project deleted'}


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@router.get("/{pid}/members")
def list_members(pid: str, user: dict = Depends(project_role_dep('viewer', 'pid'))):
    """List all project members hydrated with user info.

    Workspace owners are NOT auto-injected here — only rows that exist in
    project_members. Project owners can run the page, see the explicit list,
    and add anyone from the parent workspace via POST.
    """
    if not validate_object_id(pid):
        return JSONResponse({'error': 'Invalid project ID'}, status_code=400)

    rows = ProjectMemberModel.find_by_project(pid) or []

    user_ids = [r['user_id'] for r in rows if r.get('user_id') is not None]

    user_map = {}
    if user_ids:
        for u in UserModel.find_by_ids(user_ids):
            user_map[str(u['_id'])] = {
                'email': u.get('email'),
                'display_name': (u.get('profile') or {}).get('display_name'),
                'avatar_url': (u.get('profile') or {}).get('avatar_url'),
            }

    out = []
    for r in rows:
        row = _serialize(r)
        uid_str = str(r.get('user_id')) if r.get('user_id') is not None else None
        info = user_map.get(uid_str, {}) if uid_str else {}
        row['user'] = {
            'id': uid_str,
            'email': info.get('email'),
            'display_name': info.get('display_name'),
            'avatar_url': info.get('avatar_url'),
        }
        out.append(row)

    return out


@router.post("/{pid}/members")
async def add_member(pid: str, request: Request,
                     user: dict = Depends(project_role_dep('owner', 'pid'))):
    """Add a member to a project. Target user must already be a member of
    the project's parent workspace.
    """
    if not validate_object_id(pid):
        return JSONResponse({'error': 'Invalid project ID'}, status_code=400)

    project = ProjectModel.find_by_id(pid)
    if not project:
        return JSONResponse({'error': 'Project not found'}, status_code=404)

    data = await _json_body(request)
    user_id = (data.get('user_id') or '').strip()
    role = (data.get('role') or '').strip().lower()

    if not user_id or not validate_object_id(user_id):
        return JSONResponse({'error': 'Valid user_id is required'}, status_code=400)
    if role not in _ALLOWED_MEMBER_ROLES:
        return JSONResponse({
            'error': f"role must be one of {sorted(_ALLOWED_MEMBER_ROLES)}",
        }, status_code=400)

    # Target user must exist.
    target_user = UserModel.find_by_id(user_id)
    if not target_user:
        return JSONResponse({'error': 'User not found'}, status_code=404)

    # Target must already be in the parent workspace.
    workspace_id = project.get('workspace_id')
    if not check_workspace_access(user_id, workspace_id, 'viewer'):
        return JSONResponse({
            'error': 'User is not a member of the parent workspace',
            'code': 'not_in_workspace',
        }, status_code=400)

    member = ProjectMemberModel.add(
        project_id=pid,
        user_id=user_id,
        role=role,
        added_by=user['_id'],
    )

    return JSONResponse(_serialize(member), status_code=201)


@router.patch("/{pid}/members/{uid}")
async def update_member_role(pid: str, uid: str, request: Request,
                             user: dict = Depends(project_role_dep('owner', 'pid'))):
    """Change a member's role. Refuses to demote the last explicit owner."""
    if not validate_object_id(pid) or not validate_object_id(uid):
        return JSONResponse({'error': 'Invalid ID'}, status_code=400)

    target = ProjectMemberModel.find(pid, uid)
    if not target:
        return JSONResponse({'error': 'Member not found'}, status_code=404)

    data = await _json_body(request)
    role = (data.get('role') or '').strip().lower()
    if role not in _ALLOWED_MEMBER_ROLES:
        return JSONResponse({
            'error': f"role must be one of {sorted(_ALLOWED_MEMBER_ROLES)}",
        }, status_code=400)

    current_role = target.get('role')
    # Refuse demoting the last explicit owner.
    if current_role == 'owner' and role != 'owner':
        owner_count = _count_explicit_owners(pid)
        if owner_count <= 1:
            return JSONResponse({
                'error': 'Cannot demote the last owner',
                'code': 'last_owner_protected',
            }, status_code=400)

    ProjectMemberModel.update_role(pid, uid, role)
    updated = ProjectMemberModel.find(pid, uid)
    return _serialize(updated)


@router.delete("/{pid}/members/{uid}")
def remove_member(pid: str, uid: str,
                  user: dict = Depends(project_role_dep('owner', 'pid'))):
    """Remove a member. Refuses if the target is the lone explicit owner."""
    if not validate_object_id(pid) or not validate_object_id(uid):
        return JSONResponse({'error': 'Invalid ID'}, status_code=400)

    target = ProjectMemberModel.find(pid, uid)
    if not target:
        return JSONResponse({'error': 'Member not found'}, status_code=404)

    if target.get('role') == 'owner':
        owner_count = _count_explicit_owners(pid)
        if owner_count <= 1:
            return JSONResponse({
                'error': 'Cannot remove the last owner',
                'code': 'last_owner_protected',
            }, status_code=400)

    ProjectMemberModel.remove(pid, uid)
    return {'message': 'Member removed'}


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
# A "team" budget is a budget_allocations row at scope ('team', project_id);
# per-member budgets are GLOBAL user-scope rows at ('user', user_id). The team
# page is just the management surface for those user rows — a user budget binds
# ALL of that user's usage regardless of which team/company the spend lands in.
#
# Attribution note: team spend is tracked ONLY from usage explicitly tagged with
# this project_id (the spend_rollups 'team' scope), hence attribution
# 'project_tagged_only' — usage with no project_id is not counted toward a team.


def _team_budget_block(pid: str) -> dict:
    """The team portion of the GET /budget shape (refreshed after a write)."""
    month = SpendRollupModel.current_period_month()
    team_budget = BudgetAllocationModel.get_any('team', pid)
    spend_mtd = SpendRollupModel.get_spent('team', pid, month)
    return {
        'team_budget': team_budget,
        'spend_mtd': spend_mtd,
        'remaining': _budget_remaining(team_budget, spend_mtd),
    }


@router.get("/{pid}/budget")
def get_budget(pid: str, user: dict = Depends(project_role_dep('viewer', 'pid'))):
    """Return the team budget + per-member user budgets and their MTD spend.

    Visible to any project member (viewer+). ``per_user`` reuses the member
    hydration idiom from ``list_members``: explicit project_members rows joined
    to user profile info, each annotated with its global user-scope budget +
    current-month spend.
    """
    if not validate_object_id(pid):
        return JSONResponse({'error': 'Invalid project ID'}, status_code=400)

    project = ProjectModel.find_by_id(pid)
    if not project:
        return JSONResponse({'error': 'Project not found'}, status_code=404)

    # Owner-only $-visibility: a low-privilege viewer must NOT read every member's
    # global cross-company spend or the team/per-user ceilings (the implicit
    # workspace->project 'viewer' fallback would otherwise leak it to any company
    # member). When masked, the dollar fields are nulled but membership + role +
    # budget-enabled posture (a non-$ fact) still render.
    cost_visible = _budget_cost_visible(user, project)

    month = SpendRollupModel.current_period_month()

    # Per-member user budgets (member hydration mirrors list_members).
    rows = ProjectMemberModel.find_by_project(pid) or []
    user_ids = [r['user_id'] for r in rows if r.get('user_id') is not None]

    user_map = {}
    if user_ids:
        for u in UserModel.find_by_ids(user_ids):
            user_map[str(u['_id'])] = {
                'email': u.get('email'),
                'display_name': (u.get('profile') or {}).get('display_name'),
                'avatar_url': (u.get('profile') or {}).get('avatar_url'),
            }

    # Bulk-load enabled user budgets in one query, then fill disabled rows lazily.
    budget_map = BudgetAllocationModel.list_for_scope_ids('user', user_ids)

    per_user = []
    for r in rows:
        uid_str = str(r.get('user_id')) if r.get('user_id') is not None else None
        if uid_str is None:
            continue
        info = user_map.get(uid_str, {})
        budget = budget_map.get(uid_str)
        if budget is None:
            # An allocation may exist but be disabled — surface it so the UI can
            # show a toggled-off cap rather than "no budget".
            budget = BudgetAllocationModel.get_any('user', uid_str)
        spend_mtd = SpendRollupModel.get_spent('user', uid_str, month)
        remaining = _budget_remaining(budget, spend_mtd)
        per_user.append({
            'user_id': uid_str,
            'email': info.get('email'),
            'display_name': info.get('display_name'),
            'avatar_url': info.get('avatar_url'),
            'role': r.get('role'),
            'budget': _mask_budget(budget, cost_visible),
            'spend_mtd': spend_mtd if cost_visible else None,
            'remaining': remaining if cost_visible else None,
        })

    out = _team_budget_block(pid)
    if not cost_visible:
        out['team_budget'] = _mask_budget(out['team_budget'], cost_visible)
        out['spend_mtd'] = None
        out['remaining'] = None
    out['per_user'] = per_user
    out['attribution'] = 'project_tagged_only'
    out['cost_visible'] = cost_visible
    return out


@router.put("/{pid}/budget")
async def put_budget(pid: str, request: Request,
                     user: dict = Depends(project_role_dep('owner', 'pid'))):
    """Set / clear the team budget (scope ('team', pid)).

    Body: ``{amount_usd: number|null, enabled?: bool, period?: 'mtd'}``.
    A null ``amount_usd`` clears the allocation entirely. Owner-only.
    """
    if not validate_object_id(pid):
        return JSONResponse({'error': 'Invalid project ID'}, status_code=400)

    project = ProjectModel.find_by_id(pid)
    if not project:
        return JSONResponse({'error': 'Project not found'}, status_code=404)

    data = await _json_body(request)
    amount = data.get('amount_usd')

    if amount is None:
        BudgetAllocationModel.clear_budget('team', pid)
        return _team_budget_block(pid)

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return JSONResponse({'error': 'amount_usd must be a number'}, status_code=400)
    if amount < 0:
        return JSONResponse({'error': 'amount_usd must be >= 0'}, status_code=400)

    enabled = data.get('enabled', True)
    if not isinstance(enabled, bool):
        return JSONResponse({'error': 'enabled must be a boolean'}, status_code=400)

    BudgetAllocationModel.set_budget(
        'team', pid, amount,
        enabled=enabled,
        by=user['_id'],
        parent_scope_type='company',
        parent_scope_id=project.get('workspace_id'),
    )
    return _team_budget_block(pid)


@router.put("/{pid}/members/{uid}/budget")
async def put_member_budget(pid: str, uid: str, request: Request,
                            user: dict = Depends(project_role_dep('owner', 'pid'))):
    """Set / clear a member's GLOBAL user budget (scope ('user', uid)).

    Body: ``{amount_usd: number|null, enabled?: bool, period?: 'mtd'}``.
    NOTE: user budgets are GLOBAL — a cap set here binds ALL of that user's
    usage across every team/company, not just spend tagged to THIS project. The
    team page is merely the management surface (parent linkage = ('team', pid)).
    Owner-only. The target must be an explicit member of this project.
    """
    if not validate_object_id(pid) or not validate_object_id(uid):
        return JSONResponse({'error': 'Invalid ID'}, status_code=400)

    project = ProjectModel.find_by_id(pid)
    if not project:
        return JSONResponse({'error': 'Project not found'}, status_code=404)

    # The target must already be a member of this project.
    member = ProjectMemberModel.find(pid, uid)
    if not member:
        return JSONResponse({'error': 'Member not found'}, status_code=404)

    data = await _json_body(request)
    amount = data.get('amount_usd')
    month = SpendRollupModel.current_period_month()

    if amount is None:
        BudgetAllocationModel.clear_budget('user', uid)
        spend_mtd = SpendRollupModel.get_spent('user', uid, month)
        return {
            'user_id': str(uid),
            'budget': None,
            'spend_mtd': spend_mtd,
            'remaining': None,
        }

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return JSONResponse({'error': 'amount_usd must be a number'}, status_code=400)
    if amount < 0:
        return JSONResponse({'error': 'amount_usd must be >= 0'}, status_code=400)

    enabled = data.get('enabled', True)
    if not isinstance(enabled, bool):
        return JSONResponse({'error': 'enabled must be a boolean'}, status_code=400)

    budget = BudgetAllocationModel.set_budget(
        'user', uid, amount,
        enabled=enabled,
        by=user['_id'],
        parent_scope_type='team',
        parent_scope_id=pid,
    )
    spend_mtd = SpendRollupModel.get_spent('user', uid, month)
    return {
        'user_id': str(uid),
        'budget': budget,
        'spend_mtd': spend_mtd,
        'remaining': _budget_remaining(budget, spend_mtd),
    }


# ---------------------------------------------------------------------------
# Decoration: pin / tags
# ---------------------------------------------------------------------------

@router.patch("/{pid}/pin")
async def patch_pin(pid: str, request: Request,
                    user: dict = Depends(project_role_dep('editor', 'pid'))):
    """Toggle the ``pinned`` flag on a project."""
    if not validate_object_id(pid):
        return JSONResponse({'error': 'Invalid project ID'}, status_code=400)

    project = ProjectModel.find_by_id(pid)
    if not project:
        return JSONResponse({'error': 'Project not found'}, status_code=404)

    data = await _json_body(request)
    if 'pinned' not in data or not isinstance(data['pinned'], bool):
        return JSONResponse({'error': 'pinned (boolean) is required'}, status_code=400)

    ProjectModel.pin(pid, data['pinned'])
    return _serialize(ProjectModel.find_by_id(pid))


@router.patch("/{pid}/tags")
async def patch_tags(pid: str, request: Request,
                     user: dict = Depends(project_role_dep('editor', 'pid'))):
    """Replace the tags list for a project."""
    if not validate_object_id(pid):
        return JSONResponse({'error': 'Invalid project ID'}, status_code=400)

    project = ProjectModel.find_by_id(pid)
    if not project:
        return JSONResponse({'error': 'Project not found'}, status_code=404)

    data = await _json_body(request)
    tags = data.get('tags')
    if not isinstance(tags, list):
        return JSONResponse({'error': 'tags must be a list of strings'}, status_code=400)
    if not all(isinstance(t, str) for t in tags):
        return JSONResponse({'error': 'tags must be strings'}, status_code=400)
    if len(tags) > 20:
        return JSONResponse({'error': 'a project may have at most 20 tags'}, status_code=400)

    ProjectModel.set_tags(pid, tags)
    return _serialize(ProjectModel.find_by_id(pid))


# ---------------------------------------------------------------------------
# Project access (groups + direct members)
# ---------------------------------------------------------------------------

@router.get("/{pid}/access")
def get_access(pid: str, user: dict = Depends(project_role_dep('viewer', 'pid'))):
    """Return ``{groups, direct_members}`` for the project's access page."""
    if not validate_object_id(pid):
        return JSONResponse({'error': 'Invalid project ID'}, status_code=400)

    project = ProjectModel.find_by_id(pid)
    if not project:
        return JSONResponse({'error': 'Project not found'}, status_code=404)

    # Group grants — hydrate each with name + color.
    grants = ProjectGroupAccessModel.find_by_project(pid) or []
    groups_out = []
    group_user_ids: dict = {}  # group_id -> set of user_ids in that group
    for g in grants:
        group_doc = GroupModel.find_by_id(g['group_id'])
        if not group_doc:
            continue
        group_id_str = str(g['group_id'])
        members = GroupMemberModel.find_by_group(g['group_id']) or []
        group_user_ids[group_id_str] = {str(m['user_id']) for m in members}
        groups_out.append({
            'group_id': group_id_str,
            'name': group_doc.get('name'),
            'color': group_doc.get('color'),
            'role': g.get('role'),
            'expires_at': g['expires_at'].isoformat() if g.get('expires_at') else None,
        })

    # Direct project members.
    rows = ProjectMemberModel.find_by_project(pid) or []
    user_ids_set = {str(r['user_id']) for r in rows if r.get('user_id') is not None}
    # Combine direct + group members for hydration.
    all_uid_strs = set(user_ids_set)
    for ids in group_user_ids.values():
        all_uid_strs.update(ids)

    user_map = {}
    if all_uid_strs:
        for u in UserModel.find_by_ids(list(all_uid_strs)):
            user_map[str(u['_id'])] = {
                'email': u.get('email'),
                'display_name': (u.get('profile') or {}).get('display_name'),
                'avatar_url': (u.get('profile') or {}).get('avatar_url'),
            }

    direct_members = []
    for r in rows:
        uid_str = str(r['user_id']) if r.get('user_id') is not None else None
        info = user_map.get(uid_str, {}) if uid_str else {}
        direct_members.append({
            'user_id': uid_str,
            'name': info.get('display_name'),
            'email': info.get('email'),
            'avatar_url': info.get('avatar_url'),
            'role': r.get('role'),
            'source': 'direct',
        })

    return {
        'groups': groups_out,
        'direct_members': direct_members,
    }


@router.post("/{pid}/access/groups")
async def upsert_group_access(pid: str, request: Request,
                              user: dict = Depends(project_role_dep('owner', 'pid'))):
    """Add or update a group's access role on a project."""
    if not validate_object_id(pid):
        return JSONResponse({'error': 'Invalid project ID'}, status_code=400)

    project = ProjectModel.find_by_id(pid)
    if not project:
        return JSONResponse({'error': 'Project not found'}, status_code=404)

    data = await _json_body(request)
    group_id = (data.get('group_id') or '').strip()
    role = (data.get('role') or '').strip().lower()
    expires_at_raw = data.get('expires_at')

    if not group_id or not validate_object_id(group_id):
        return JSONResponse({'error': 'Valid group_id is required'}, status_code=400)
    if role not in ('viewer', 'editor'):
        return JSONResponse({
            'error': "role must be 'viewer' or 'editor'",
            'code': 'invalid_role',
        }, status_code=400)

    group = GroupModel.find_by_id(group_id)
    if not group:
        return JSONResponse({'error': 'Group not found'}, status_code=404)
    if str(group.get('workspace_id')) != str(project['workspace_id']):
        return JSONResponse({
            'error': "Group does not belong to this project's workspace",
            'code': 'group_workspace_mismatch',
        }, status_code=400)

    expires_at = None
    if expires_at_raw:
        try:
            from datetime import datetime as _dt
            # Accept ISO 8601 with or without seconds.
            expires_at = _dt.fromisoformat(expires_at_raw.replace('Z', '+00:00'))
            # Strip tz to keep parity with model storage (UTC naive).
            if expires_at.tzinfo is not None:
                expires_at = expires_at.replace(tzinfo=None)
        except Exception:
            return JSONResponse({'error': 'expires_at must be ISO 8601'}, status_code=400)

    row = ProjectGroupAccessModel.set(
        project_id=pid,
        group_id=group_id,
        role=role,
        expires_at=expires_at,
        created_by=user['_id'],
    )
    return JSONResponse(_serialize(row), status_code=201)


@router.delete("/{pid}/access/groups/{gid}")
def remove_group_access(pid: str, gid: str,
                        user: dict = Depends(project_role_dep('owner', 'pid'))):
    if not validate_object_id(pid) or not validate_object_id(gid):
        return JSONResponse({'error': 'Invalid ID'}, status_code=400)

    if not ProjectGroupAccessModel.remove(pid, gid):
        return JSONResponse({'error': 'Access entry not found'}, status_code=404)
    return {'message': 'Group access removed'}


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

@router.get("/{pid}/webhooks")
def list_webhooks(pid: str, user: dict = Depends(project_role_dep('viewer', 'pid'))):
    """List webhooks for a project. ``secret`` is OMITTED from the response."""
    if not validate_object_id(pid):
        return JSONResponse({'error': 'Invalid project ID'}, status_code=400)

    rows = ProjectWebhookModel.find_by_project(pid) or []
    return [_serialize_webhook(r, include_secret=False) for r in rows]


@router.post("/{pid}/webhooks")
async def create_webhook(pid: str, request: Request,
                         user: dict = Depends(project_role_dep('owner', 'pid'))):
    """Create a webhook. The full doc INCLUDING ``secret`` is returned once."""
    if not validate_object_id(pid):
        return JSONResponse({'error': 'Invalid project ID'}, status_code=400)

    project = ProjectModel.find_by_id(pid)
    if not project:
        return JSONResponse({'error': 'Project not found'}, status_code=404)

    data = await _json_body(request)
    name = (data.get('name') or '').strip()
    url = (data.get('url') or '').strip()
    events = data.get('events')

    if not name:
        return JSONResponse({'error': 'name is required'}, status_code=400)
    if not url:
        return JSONResponse({'error': 'url is required'}, status_code=400)
    if events is not None and not isinstance(events, list):
        return JSONResponse({'error': 'events must be a list of strings'}, status_code=400)

    webhook = ProjectWebhookModel.create(
        project_id=pid,
        name=name,
        url=url,
        events=events,
        created_by=user['_id'],
    )

    return JSONResponse(_serialize_webhook(webhook, include_secret=True), status_code=201)


@router.put("/{pid}/webhooks/{whid}")
async def update_webhook(pid: str, whid: str, request: Request,
                         user: dict = Depends(project_role_dep('owner', 'pid'))):
    """Update a webhook (name, url, events, enabled). Secret unaffected."""
    if not validate_object_id(pid) or not validate_object_id(whid):
        return JSONResponse({'error': 'Invalid ID'}, status_code=400)

    webhook = ProjectWebhookModel.find_by_id(whid)
    if not webhook or str(webhook.get('project_id')) != str(pid):
        return JSONResponse({'error': 'Webhook not found'}, status_code=404)

    data = await _json_body(request)
    update_data = {}
    for field in ('name', 'url', 'events', 'enabled'):
        if field in data:
            update_data[field] = data[field]

    if not update_data:
        return JSONResponse({'error': 'No valid fields to update'}, status_code=400)

    try:
        ProjectWebhookModel.update(whid, update_data)
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)

    updated = ProjectWebhookModel.find_by_id(whid)
    return _serialize_webhook(updated, include_secret=False)


@router.delete("/{pid}/webhooks/{whid}")
def delete_webhook(pid: str, whid: str,
                   user: dict = Depends(project_role_dep('owner', 'pid'))):
    """Hard-delete a webhook."""
    if not validate_object_id(pid) or not validate_object_id(whid):
        return JSONResponse({'error': 'Invalid ID'}, status_code=400)

    webhook = ProjectWebhookModel.find_by_id(whid)
    if not webhook or str(webhook.get('project_id')) != str(pid):
        return JSONResponse({'error': 'Webhook not found'}, status_code=404)

    ProjectWebhookModel.delete(whid)
    return {'message': 'Webhook deleted'}


@router.post("/{pid}/webhooks/{whid}/rotate-secret")
def rotate_webhook_secret(pid: str, whid: str,
                          user: dict = Depends(project_role_dep('owner', 'pid'))):
    """Rotate the webhook secret. Returns the new value once."""
    if not validate_object_id(pid) or not validate_object_id(whid):
        return JSONResponse({'error': 'Invalid ID'}, status_code=400)

    webhook = ProjectWebhookModel.find_by_id(whid)
    if not webhook or str(webhook.get('project_id')) != str(pid):
        return JSONResponse({'error': 'Webhook not found'}, status_code=404)

    new_secret = ProjectWebhookModel.rotate_secret(whid)
    return {'secret': new_secret}


__all__ = ["router"]
