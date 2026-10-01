"""Integration tests for chat sharing — link snapshots + live team grants.

Covers the conversation_shares feature end to end against real Postgres + model
facades (no OpenRouter calls — these routes never invoke the LLM):

  * link snapshot: create -> read by a DIFFERENT user -> frozen (later messages
    don't change it) -> revoke -> 404
  * team share: owner shares a personal chat into a team -> a project member can
    read it and it appears in their team-scope list; a non-member gets 404
  * owner-only management (a non-owner can't share/revoke)
  * sender attribution persists on user messages (facade level)
"""


def _h(mint, user):
    return {
        "Authorization": f"Bearer {mint(user['_id'], role=user.get('role', 'user'))}",
        "Content-Type": "application/json",
    }


def _make_conversation(flask_core, *, user_id, config_id="quick:gpt", title="Chat",
                       project_id=None):
    from app.models.conversation import ConversationModel
    with flask_core.app_context():
        return ConversationModel.create(
            user_id=str(user_id), config_id=config_id, title=title, project_id=project_id,
            workspace_id=_active_ws(user_id),
        )


def _add_message(flask_core, *, conversation_id, role, content, sender_user_id=None):
    from app.models.message import MessageModel
    with flask_core.app_context():
        return MessageModel.create(
            conversation_id=conversation_id, role=role, content=content,
            sender_user_id=sender_user_id,
        )


def _make_team_with_member(flask_core, *, owner_user, member_user=None):
    """Workspace + project; owner = editor; optional member = viewer."""
    from app.models.workspace import WorkspaceModel
    from app.models.project import ProjectModel
    from app.models.project_member import ProjectMemberModel
    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Acme", owner_id=str(owner_user["_id"]), type="team")
        proj = ProjectModel.create(
            workspace_id=ws["_id"], name="Launch", created_by=str(owner_user["_id"]),
        )
        ProjectMemberModel.add(
            project_id=proj["_id"], user_id=str(owner_user["_id"]),
            role="editor", added_by=str(owner_user["_id"]),
        )
        if member_user is not None:
            ProjectMemberModel.add(
                project_id=proj["_id"], user_id=str(member_user["_id"]),
                role="viewer", added_by=str(owner_user["_id"]),
            )
    return ws, proj


# ---------------------------------------------------------------------------
# Link snapshot
# ---------------------------------------------------------------------------
def test_link_share_create_view_frozen_revoke(client, flask_core, mint_token, test_user, plain_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"], title="Shared one")
    cid = conv["_id"]
    _add_message(flask_core, conversation_id=cid, role="user", content="first question")

    resp = client.post(f"/api/conversations/{cid}/share/link", headers=_h(mint_token, test_user))
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    assert token

    # A DIFFERENT logged-in user can read the snapshot.
    view = client.get(f"/api/share/{token}", headers=_h(mint_token, plain_user))
    assert view.status_code == 200, view.text
    snap = view.json()["snapshot"]
    assert len(snap["messages"]) == 1
    assert snap["messages"][0]["content"] == "first question"

    # A message added AFTER sharing must not change the frozen snapshot.
    _add_message(flask_core, conversation_id=cid, role="user", content="second question")
    view2 = client.get(f"/api/share/{token}", headers=_h(mint_token, plain_user))
    assert view2.status_code == 200
    assert len(view2.json()["snapshot"]["messages"]) == 1  # still frozen

    # Revoke → the token 404s.
    rev = client.delete(f"/api/conversations/{cid}/share/link", headers=_h(mint_token, test_user))
    assert rev.status_code == 200
    gone = client.get(f"/api/share/{token}", headers=_h(mint_token, plain_user))
    assert gone.status_code == 404


def test_link_share_owner_only(client, flask_core, mint_token, test_user, plain_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    cid = conv["_id"]
    resp = client.post(f"/api/conversations/{cid}/share/link", headers=_h(mint_token, plain_user))
    assert resp.status_code == 404


def test_share_token_bogus_404(client, mint_token, plain_user):
    assert client.get("/api/share/nope", headers=_h(mint_token, plain_user)).status_code == 404


# ---------------------------------------------------------------------------
# Team share — live read access
# ---------------------------------------------------------------------------
def test_team_share_member_reads_nonmember_404(client, flask_core, mint_token,
                                               test_user, plain_user, admin_user):
    _ws, proj = _make_team_with_member(flask_core, owner_user=test_user, member_user=plain_user)
    conv = _make_conversation(flask_core, user_id=test_user["_id"], title="Team chat")
    cid = conv["_id"]

    share = client.put(
        f"/api/conversations/{cid}/share/teams",
        headers=_h(mint_token, test_user), json={"project_ids": [proj["_id"]]},
    )
    assert share.status_code == 200, share.text
    assert proj["_id"] in share.json()["teams"]

    # Member of that team can read the (personal-scope) chat + sees share summary.
    member_read = client.get(f"/api/conversations/{cid}", headers=_h(mint_token, plain_user))
    assert member_read.status_code == 200, member_read.text
    assert member_read.json()["conversation"]["share"]["is_shared"] is True

    # A non-member gets 404 (global admin has no bypass in check_project_access).
    outsider = client.get(f"/api/conversations/{cid}", headers=_h(mint_token, admin_user))
    assert outsider.status_code == 404


def test_team_share_appears_in_member_team_list(client, flask_core, mint_token, test_user, plain_user):
    from app.models.workspace_member import WorkspaceMemberModel

    _ws, proj = _make_team_with_member(flask_core, owner_user=test_user, member_user=plain_user)
    with flask_core.app_context():
        WorkspaceMemberModel.add(_ws["_id"], plain_user["_id"], "viewer", status="active")
    conv = _make_conversation(flask_core, user_id=test_user["_id"], title="Visible to team")
    cid = conv["_id"]
    client.put(
        f"/api/conversations/{cid}/share/teams",
        headers=_h(mint_token, test_user), json={"project_ids": [proj["_id"]]},
    )

    # A team belongs to one org: list it with that org's workspace_id.
    listing = client.get(
        f"/api/conversations?project_id={proj['_id']}&workspace_id={_ws['_id']}",
        headers=_h(mint_token, plain_user),
    )
    assert listing.status_code == 200, listing.text
    assert cid in [c["_id"] for c in listing.json()["conversations"]]


def test_team_share_owner_only(client, flask_core, mint_token, test_user, plain_user):
    _ws, proj = _make_team_with_member(flask_core, owner_user=test_user, member_user=plain_user)
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    cid = conv["_id"]
    resp = client.put(
        f"/api/conversations/{cid}/share/teams",
        headers=_h(mint_token, plain_user), json={"project_ids": [proj["_id"]]},
    )
    assert resp.status_code == 404


def test_team_share_personal_scope_excludes_shared(client, flask_core, mint_token, test_user, plain_user):
    """Personal scope stays owner-only — a shared chat never leaks there."""
    _ws, proj = _make_team_with_member(flask_core, owner_user=test_user, member_user=plain_user)
    conv = _make_conversation(flask_core, user_id=test_user["_id"], title="Not personal")
    cid = conv["_id"]
    client.put(
        f"/api/conversations/{cid}/share/teams",
        headers=_h(mint_token, test_user), json={"project_ids": [proj["_id"]]},
    )
    personal = client.get("/api/conversations?project_id=null", headers=_h(mint_token, plain_user))
    assert personal.status_code == 200
    assert cid not in [c["_id"] for c in personal.json()["conversations"]]


# ---------------------------------------------------------------------------
# Link snapshot purge — deleting the chat erases the snapshot (no resident blob),
# but a recipient's already-saved copy is independent and survives.
# ---------------------------------------------------------------------------
def test_link_purged_on_conversation_delete(client, flask_core, mint_token, test_user, plain_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"], title="Will delete")
    cid = conv["_id"]
    _add_message(flask_core, conversation_id=cid, role="user", content="erase me")
    token = client.post(
        f"/api/conversations/{cid}/share/link", headers=_h(mint_token, test_user)
    ).json()["token"]

    # Owner deletes the original chat → the full-content snapshot is hard-deleted
    # with it (data-erasure: the cross-tenant blob stops residing AND serving).
    assert client.delete(f"/api/conversations/{cid}", headers=_h(mint_token, test_user)).status_code == 200

    # The link no longer resolves.
    gone = client.get(f"/api/share/{token}", headers=_h(mint_token, plain_user))
    assert gone.status_code == 404, gone.text


def test_save_snapshot_creates_independent_copy(client, flask_core, mint_token, test_user, plain_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"], title="Source")
    cid = conv["_id"]
    _add_message(flask_core, conversation_id=cid, role="user", content="hello")
    _add_message(flask_core, conversation_id=cid, role="assistant", content="hi there")
    token = client.post(
        f"/api/conversations/{cid}/share/link", headers=_h(mint_token, test_user)
    ).json()["token"]

    # A different user saves their OWN copy.
    saved = client.post(f"/api/share/{token}/save", headers=_h(mint_token, plain_user))
    assert saved.status_code == 200, saved.text
    new_id = saved.json()["conversation_id"]
    assert new_id and new_id != cid

    # The copy is owned by the saver and carries the messages in order.
    got = client.get(f"/api/conversations/{new_id}", headers=_h(mint_token, plain_user))
    assert got.status_code == 200, got.text
    assert [m["content"] for m in got.json()["messages"]] == ["hello", "hi there"]

    # Independent: deleting the original leaves the copy intact.
    client.delete(f"/api/conversations/{cid}", headers=_h(mint_token, test_user))
    assert client.get(f"/api/conversations/{new_id}", headers=_h(mint_token, plain_user)).status_code == 200


def test_delete_team_shared_revokes_member_access(client, flask_core, mint_token, test_user, plain_user):
    _ws, proj = _make_team_with_member(flask_core, owner_user=test_user, member_user=plain_user)
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    cid = conv["_id"]
    client.put(
        f"/api/conversations/{cid}/share/teams",
        headers=_h(mint_token, test_user), json={"project_ids": [proj["_id"]]},
    )
    assert client.get(f"/api/conversations/{cid}", headers=_h(mint_token, plain_user)).status_code == 200
    # Owner deletes → the live chat is gone, so the member loses access.
    client.delete(f"/api/conversations/{cid}", headers=_h(mint_token, test_user))
    assert client.get(f"/api/conversations/{cid}", headers=_h(mint_token, plain_user)).status_code == 404


# ---------------------------------------------------------------------------
# Sender attribution (facade)
# ---------------------------------------------------------------------------
def test_sender_user_id_enriched_on_read(flask_core, test_user, plain_user):
    from app.models.message import MessageModel
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    cid = conv["_id"]
    _add_message(flask_core, conversation_id=cid, role="user",
                 content="from a teammate", sender_user_id=str(plain_user["_id"]))
    with flask_core.app_context():
        msgs = MessageModel.find_by_conversation(cid)
    assert len(msgs) == 1
    assert msgs[0]["sender"]["id"] == str(plain_user["_id"])
    assert msgs[0]["sender"]["name"]


def _active_ws(user_id):
    """The user's org (conftest puts every fixture user in "Test Org")."""
    from app.models.user import UserModel

    return (UserModel.find_by_id(user_id) or {}).get("active_workspace_id")
