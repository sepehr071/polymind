"""Unit tests for the money-visibility tier resolver.

``app.utils.permissions.money_view(user, workspace=None)`` returns the money tier
a viewer is allowed to see (profit redesign 2026-06-29):

  * ``'cost'``  — super-admin (role='admin'): upstream cost + price + margin.
  * ``'price'`` — ``owner`` MEMBER of a TEAM workspace: marked-up price only.
  * ``'none'``  — everyone else: Polymind Credits + tokens, NEVER any $.

Ownership is the membership role, NOT ``workspaces.owner_user_id`` — Keycloak
org workspaces are created with no owner column (mig 0026 era). The shared
"Test Org" from conftest makes managers ``owner`` and plain users ``viewer``.
"""


def _make_team_ws(flask_core, owner, *, name="Acme Co"):
    """Create a TEAM workspace owned by ``owner`` + add them as an owner member."""
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner["_id"], type="team")
        WorkspaceMemberModel.add(ws["_id"], owner["_id"], "owner", status="active")
    return ws


def _money_view(flask_core, user, workspace=None):
    from app.utils.permissions import money_view

    with flask_core.app_context():
        return money_view(user, workspace=workspace)


# ---------------------------------------------------------------------------
# role='admin' -> 'cost' everywhere.
# ---------------------------------------------------------------------------
def test_admin_sees_cost(flask_core, admin_user):
    assert _money_view(flask_core, admin_user) == "cost"


def test_admin_sees_cost_even_scoped_to_a_workspace(flask_core, admin_user, plain_user):
    """The admin short-circuit wins regardless of workspace ownership."""
    foreign_ws = _make_team_ws(flask_core, plain_user, name="Not Admins")
    assert _money_view(flask_core, admin_user, workspace=foreign_ws) == "cost"


# ---------------------------------------------------------------------------
# Team-workspace owner -> 'price'.
# ---------------------------------------------------------------------------
def test_team_workspace_owner_sees_price(flask_core, plain_user):
    """No workspace arg: 'does this user see price ANYWHERE' -> owns a team ws."""
    _make_team_ws(flask_core, plain_user, name="Owned Team")
    assert _money_view(flask_core, plain_user) == "price"


def test_team_workspace_owner_scoped_sees_price(flask_core, plain_user):
    """Scoped to the team ws they own -> 'price'."""
    ws = _make_team_ws(flask_core, plain_user, name="Scoped Team")
    assert _money_view(flask_core, plain_user, workspace=ws) == "price"


# ---------------------------------------------------------------------------
# Membership role decides — not the owner column.
# ---------------------------------------------------------------------------
def test_viewer_member_sees_none(flask_core, plain_user):
    """plain_user is a ``viewer`` of the shared Test Org -> 'none'."""
    assert _money_view(flask_core, plain_user) == "none"


def test_owner_member_of_ownerless_org_sees_price(flask_core, test_user):
    """KC org workspaces have ``owner_user_id=None``; the ``owner`` membership
    role alone must unmask price (the owner_id bug)."""
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        ws = WorkspaceModel.find_by_id(test_user["active_workspace_id"])
    assert ws["owner_id"] is None
    assert _money_view(flask_core, test_user, workspace=ws) == "price"
    assert _money_view(flask_core, test_user) == "price"


def test_owner_column_without_owner_membership_sees_none(flask_core, plain_user):
    """A stale ``owner_user_id`` without the owner membership grants nothing."""
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Column Only", owner_id=plain_user["_id"], type="team")
    assert _money_view(flask_core, plain_user, workspace=ws) == "none"


# ---------------------------------------------------------------------------
# Plain user, scoped to a team ws they do NOT own -> 'none'.
# ---------------------------------------------------------------------------
def test_non_owner_scoped_to_foreign_team_sees_none(flask_core, plain_user, test_user):
    foreign_ws = _make_team_ws(flask_core, test_user, name="Someone Elses")
    assert _money_view(flask_core, plain_user, workspace=foreign_ws) == "none"


# ---------------------------------------------------------------------------
# Defensive: no user -> 'none'.
# ---------------------------------------------------------------------------
def test_no_user_sees_none(flask_core):
    assert _money_view(flask_core, None) == "none"
