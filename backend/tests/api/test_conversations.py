"""Integration tests for the FastAPI conversations router (tests/api/**).

Mirrors tests/api/test_auth.py: real model facades on Postgres, legacy-shaped
JSON, the conftest fixtures (client, auth_headers, plain_headers, mint_token,
user factories, truncate_all autouse). No external HTTP is involved in this
router (no OpenRouter calls), so nothing is mocked here.

Covered per route: happy path (status + ``_id`` shape on entities), auth gating
(no token -> 401 token_missing), ownership/404, the project-ACL 403 path, and
the documented error codes (400 invalid project_id / cannot_reassign_project /
search query required, 404 not found, 400 main-branch guards).
"""
import json

import pytest


# ---------------------------------------------------------------------------
# Seed helpers — created via the real facades inside an app_context.
# ---------------------------------------------------------------------------
def _make_conversation(flask_core, *, user_id, config_id="quick:gpt", title="Chat",
                       project_id=None, folder_id=None):
    from app.models.conversation import ConversationModel

    with flask_core.app_context():
        return ConversationModel.create(
            user_id=str(user_id), config_id=config_id, title=title,
            project_id=project_id, folder_id=folder_id,
            workspace_id=_active_ws(user_id),
        )


def _add_message(flask_core, *, conversation_id, role, content, branch_id="main",
                 metadata=None):
    from app.models.message import MessageModel

    with flask_core.app_context():
        return MessageModel.create(
            conversation_id=conversation_id, role=role, content=content,
            branch_id=branch_id, metadata=metadata or {},
        )


def _make_project_with_owner(flask_core, *, owner_user):
    """Create a workspace + project, grant the owner editor on the project.

    Returns ``(workspace_dict, project_dict)``. The project membership row
    means ``check_project_access(owner, project, 'editor')`` is True.
    """
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
    return ws, proj


# ---------------------------------------------------------------------------
# GET /api/conversations  (list).
# ---------------------------------------------------------------------------
def test_list_conversations_happy(client, auth_headers, flask_core, test_user):
    _make_conversation(flask_core, user_id=test_user["_id"], title="Alpha")
    _make_conversation(flask_core, user_id=test_user["_id"], title="Beta")

    resp = client.get("/api/conversations", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["limit"] == 20
    assert body["has_more"] is False
    assert len(body["conversations"]) == 2
    # Legacy _id alias must survive serialize_doc.
    for c in body["conversations"]:
        assert "_id" in c
        assert c["_id"]


def test_list_conversations_no_token_401(client):
    resp = client.get("/api/conversations")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_list_conversations_invalid_project_id_400(client, auth_headers):
    resp = client.get("/api/conversations?project_id=not-a-uuid", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid project_id"


def test_list_conversations_project_access_denied_403(client, auth_headers):
    # A real-looking but unmembered project UUID -> 403.
    import uuid

    other = str(uuid.uuid4())
    resp = client.get(f"/api/conversations?project_id={other}", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Project access denied"


def test_list_conversations_null_project_filter(client, auth_headers, flask_core,
                                                test_user):
    # project_id=null -> personal-scope only (NULL sentinel).
    _make_conversation(flask_core, user_id=test_user["_id"], title="Personal")
    resp = client.get("/api/conversations?project_id=null", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["conversations"][0]["project_id"] is None


# ---------------------------------------------------------------------------
# POST /api/conversations  (create).
# ---------------------------------------------------------------------------
def test_create_conversation_happy(client, auth_headers):
    resp = client.post("/api/conversations", headers=auth_headers,
                       json={"config_id": "quick:gpt", "title": "Hello"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    conv = body["conversation"]
    assert conv["_id"]
    assert conv["title"] == "Hello"
    assert conv["project_id"] is None


def test_create_conversation_missing_config_400(client, auth_headers):
    resp = client.post("/api/conversations", headers=auth_headers, json={"title": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "config_id is required"


def test_create_conversation_invalid_project_400(client, auth_headers):
    resp = client.post("/api/conversations", headers=auth_headers,
                       json={"config_id": "quick:gpt", "project_id": "garbage"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid project_id"


def test_create_conversation_project_access_denied_403(client, auth_headers):
    import uuid

    resp = client.post("/api/conversations", headers=auth_headers,
                       json={"config_id": "quick:gpt", "project_id": str(uuid.uuid4())})
    assert resp.status_code == 403
    assert resp.json()["error"] == "Project access denied"


def test_create_conversation_with_project_member_201(client, auth_headers, flask_core,
                                                     test_user):
    _ws, proj = _make_project_with_owner(flask_core, owner_user=test_user)
    resp = client.post("/api/conversations", headers=auth_headers,
                       json={"config_id": "quick:gpt", "project_id": proj["_id"]})
    assert resp.status_code == 201, resp.text
    assert str(resp.json()["conversation"]["project_id"]) == str(proj["_id"])


# ---------------------------------------------------------------------------
# GET /api/conversations/{id}  (single + messages).
# ---------------------------------------------------------------------------
def test_get_conversation_happy(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"], title="Get me")
    _add_message(flask_core, conversation_id=conv["_id"], role="user", content="hi")
    _add_message(flask_core, conversation_id=conv["_id"], role="assistant", content="hello")

    resp = client.get(f"/api/conversations/{conv['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["conversation"]["_id"] == str(conv["_id"])
    assert body["active_branch"] == "main"
    assert len(body["messages"]) == 2
    assert body["messages"][0]["_id"]


def test_get_conversation_not_found_404(client, auth_headers):
    import uuid

    resp = client.get(f"/api/conversations/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Conversation not found"


def test_get_conversation_other_user_404(client, auth_headers, flask_core, plain_user):
    # Conversation owned by plain_user; test_user (auth_headers) must not see it.
    conv = _make_conversation(flask_core, user_id=plain_user["_id"], title="Theirs")
    resp = client.get(f"/api/conversations/{conv['_id']}", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/conversations/{id}  (update).
# ---------------------------------------------------------------------------
def test_update_conversation_happy(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"], title="Old")
    resp = client.put(f"/api/conversations/{conv['_id']}", headers=auth_headers,
                      json={"title": "New", "is_pinned": True})
    assert resp.status_code == 200, resp.text
    out = resp.json()["conversation"]
    assert out["title"] == "New"
    assert out["is_pinned"] is True


def test_update_conversation_reassign_project_blocked_400(client, auth_headers,
                                                          flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    resp = client.put(f"/api/conversations/{conv['_id']}", headers=auth_headers,
                      json={"project_id": "anything"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "cannot_reassign_project"


# ---------------------------------------------------------------------------
# POST /api/conversations/{id}/move.
# ---------------------------------------------------------------------------
def test_move_conversation_to_null(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    resp = client.post(f"/api/conversations/{conv['_id']}/move", headers=auth_headers,
                       json={"project_id": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["conversation"]["project_id"] is None


def test_move_conversation_missing_field_400(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    resp = client.post(f"/api/conversations/{conv['_id']}/move", headers=auth_headers,
                       json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "project_id is required"


def test_move_conversation_target_access_denied_403(client, auth_headers, flask_core,
                                                    test_user):
    import uuid

    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    resp = client.post(f"/api/conversations/{conv['_id']}/move", headers=auth_headers,
                       json={"project_id": str(uuid.uuid4())})
    assert resp.status_code == 403
    assert resp.json()["code"] == "project_access_denied"


def test_move_conversation_to_member_project_200(client, auth_headers, flask_core,
                                                 test_user):
    _ws, proj = _make_project_with_owner(flask_core, owner_user=test_user)
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    resp = client.post(f"/api/conversations/{conv['_id']}/move", headers=auth_headers,
                       json={"project_id": proj["_id"]})
    assert resp.status_code == 200, resp.text
    assert str(resp.json()["conversation"]["project_id"]) == str(proj["_id"])


# ---------------------------------------------------------------------------
# DELETE /api/conversations/{id}.
# ---------------------------------------------------------------------------
def test_delete_conversation_happy(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    _add_message(flask_core, conversation_id=conv["_id"], role="user", content="x")

    resp = client.delete(f"/api/conversations/{conv['_id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Conversation deleted"

    # Gone now.
    after = client.get(f"/api/conversations/{conv['_id']}", headers=auth_headers)
    assert after.status_code == 404


def test_delete_conversation_not_found_404(client, auth_headers):
    import uuid

    resp = client.delete(f"/api/conversations/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/conversations/{id}/archive.
# ---------------------------------------------------------------------------
def test_toggle_archive(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    resp = client.post(f"/api/conversations/{conv['_id']}/archive", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_archived"] is True
    assert body["message"] == "Archived"

    # Toggling again flips it back.
    resp2 = client.post(f"/api/conversations/{conv['_id']}/archive", headers=auth_headers)
    assert resp2.json()["is_archived"] is False
    assert resp2.json()["message"] == "Unarchived"


# ---------------------------------------------------------------------------
# GET /api/conversations/search  (title) and /search/messages (content).
# These STATIC paths must NOT be swallowed by /{conversation_id}.
# ---------------------------------------------------------------------------
def test_search_conversations_happy(client, auth_headers, flask_core, test_user):
    _make_conversation(flask_core, user_id=test_user["_id"], title="Marketing plan")
    _make_conversation(flask_core, user_id=test_user["_id"], title="Random chat")

    resp = client.get("/api/conversations/search?q=Marketing", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "Marketing"
    assert len(body["conversations"]) == 1
    assert body["conversations"][0]["title"] == "Marketing plan"


def test_search_conversations_empty_query_400(client, auth_headers):
    resp = client.get("/api/conversations/search?q=", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Search query required"


def test_search_messages_happy(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    _add_message(flask_core, conversation_id=conv["_id"], role="user",
                 content="the quick brown fox")
    _add_message(flask_core, conversation_id=conv["_id"], role="assistant",
                 content="totally unrelated text")

    resp = client.get("/api/conversations/search/messages?q=brown", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "brown"
    assert body["total"] >= 1
    assert any("brown" in r["content"] for r in body["results"])


def test_search_messages_empty_query_400(client, auth_headers):
    resp = client.get("/api/conversations/search/messages?q=  ", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Search query required"


def test_search_messages_no_conversations_returns_empty(client, auth_headers):
    resp = client.get("/api/conversations/search/messages?q=anything", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == []
    assert body["total"] == 0


# ---------------------------------------------------------------------------
# GET /api/conversations/{id}/export  (file download — JSON + Markdown).
# ---------------------------------------------------------------------------
def _disposition_filename(header: str) -> str:
    import re
    match = re.search(r'filename="([^"]+)"', header or "")
    assert match, header
    return match.group(1)


def test_export_conversation_markdown_default(client, auth_headers, flask_core,
                                              test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"], title="Export Me")
    _add_message(flask_core, conversation_id=conv["_id"], role="user", content="hello world")
    _add_message(flask_core, conversation_id=conv["_id"], role="system",
                 content="SECRET-PROMPT")

    resp = client.get(f"/api/conversations/{conv['_id']}/export", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/markdown")
    name = _disposition_filename(resp.headers["content-disposition"])
    assert name.startswith("polymind-") and name.endswith(".md")
    assert "/" not in name and "\\" not in name
    text = resp.text
    assert "# Export Me" in text
    assert "hello world" in text
    assert "**کاربر**" in text
    assert "## تنظیمات دستیار" in text
    settings, _sep, dialogue = text.partition("## گفتگو")
    assert "SECRET-PROMPT" in settings
    assert "SECRET-PROMPT" not in dialogue


def test_export_conversation_json(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(
        flask_core, user_id=test_user["_id"], title="JSON Export",
        config_id="quick:google/gemini-3.5-flash-lite",
    )
    _add_message(flask_core, conversation_id=conv["_id"], role="user", content="payload")
    _add_message(
        flask_core, conversation_id=conv["_id"], role="assistant", content="answer",
        metadata={"model_id": "google/gemini-3.5-flash-lite", "tokens": {"total": 12}},
    )
    _add_message(flask_core, conversation_id=conv["_id"], role="tool", content="hidden tool")
    _add_message(flask_core, conversation_id=conv["_id"], role="system", content="sys line")

    resp = client.get(f"/api/conversations/{conv['_id']}/export?format=json",
                      headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    name = _disposition_filename(resp.headers["content-disposition"])
    assert name.startswith("polymind-") and name.endswith(".json")
    payload = json.loads(resp.text)
    assert payload["schema"] == "polymind.chat.export/v1"
    assert payload["id"] == f"conv_{conv['_id']}"
    assert payload["exported_at"].endswith("+03:30") or payload["exported_at"].endswith("+04:30")
    assert payload["assistant"]["id"] == "quick:google/gemini-3.5-flash-lite"
    assert payload["assistant"]["name"]
    assert payload["model"]["id"] == "google/gemini-3.5-flash-lite"
    assert payload["workspace"]["type"] in ("person", "organization")
    assert "tokens" in payload["usage"] and payload["usage"]["requests"] == 1
    roles = {m["role"] for m in payload["messages"]}
    assert roles <= {"system", "user", "assistant"}
    assert "tool" not in roles
    assert any(m["role"] == "system" and m["content"] == "sys line" for m in payload["messages"])
    assert payload["messages"][1]["content"] == "payload" or any(
        m["content"] == "payload" for m in payload["messages"]
    )


def test_export_conversation_empty_persian_error(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"], title="Empty")
    resp = client.get(f"/api/conversations/{conv['_id']}/export?format=pdf",
                      headers=auth_headers)
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["error"] == "این مکالمه پیامی برای خروجی ندارد."
    assert not resp.content.startswith(b"%PDF")


def test_export_conversation_pdfa(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"], title="بایگانی")
    _add_message(flask_core, conversation_id=conv["_id"], role="user", content="سلام قرارداد")

    resp = client.get(f"/api/conversations/{conv['_id']}/export?format=pdf",
                      headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/pdf")
    name = _disposition_filename(resp.headers["content-disposition"])
    assert name.startswith("polymind-") and name.endswith(".pdf")
    data = resp.content
    assert data.startswith(b"%PDF")
    assert b"pdfaid:part" in data
    assert b"pdfaid:conformance" in data
    assert b"Vazirmatn" in data


def test_export_conversation_not_found_404(client, auth_headers):
    import uuid

    resp = client.get(f"/api/conversations/{uuid.uuid4()}/export", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Branch management.
# ---------------------------------------------------------------------------
def _seed_conv_with_messages(flask_core, user_id, n=3):
    conv = _make_conversation(flask_core, user_id=user_id, title="Branchy")
    msgs = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append(_add_message(flask_core, conversation_id=conv["_id"], role=role,
                                 content=f"msg {i}"))
    return conv, msgs


def test_create_branch_happy(client, auth_headers, flask_core, test_user):
    conv, msgs = _seed_conv_with_messages(flask_core, test_user["_id"], n=3)
    branch_point = msgs[1]

    resp = client.post(
        f"/api/conversations/{conv['_id']}/branch/{branch_point['_id']}",
        headers=auth_headers, json={"name": "Side quest"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["branch_id"]
    assert body["active_branch"] == body["branch_id"]
    # main + the new branch.
    branch_keys = {b["id"] for b in body["branches"]}
    assert "main" in branch_keys
    assert body["branch_id"] in branch_keys
    # Messages up to and including the branch point were copied.
    assert len(body["messages"]) == 2


def test_create_branch_message_not_found_404(client, auth_headers, flask_core, test_user):
    import uuid

    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    resp = client.post(
        f"/api/conversations/{conv['_id']}/branch/{uuid.uuid4()}",
        headers=auth_headers, json={},
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Message not found"


def test_branch_to_new_conversation(client, auth_headers, flask_core, test_user):
    conv, msgs = _seed_conv_with_messages(flask_core, test_user["_id"], n=3)
    resp = client.post(
        f"/api/conversations/{conv['_id']}/branch-to-new/{msgs[2]['_id']}",
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["conversation_id"]
    assert body["conversation_id"] != str(conv["_id"])
    assert body["message_count"] == 3
    assert body["title"].endswith("(branch)")


def test_branch_to_new_no_messages_400(client, auth_headers, flask_core, test_user):
    import uuid

    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    resp = client.post(
        f"/api/conversations/{conv['_id']}/branch-to-new/{uuid.uuid4()}",
        headers=auth_headers,
    )
    # Message lookup fails first -> 404 (mirror Flask order).
    assert resp.status_code == 404


def test_list_branches(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    resp = client.get(f"/api/conversations/{conv['_id']}/branches", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active_branch"] == "main"
    assert any(b["id"] == "main" for b in body["branches"])


def test_switch_branch_not_found_404(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    resp = client.put(f"/api/conversations/{conv['_id']}/branch/doesnotexist",
                      headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Branch not found"


def test_switch_branch_happy(client, auth_headers, flask_core, test_user):
    conv, msgs = _seed_conv_with_messages(flask_core, test_user["_id"], n=2)
    # Create a branch, then switch back to main.
    created = client.post(
        f"/api/conversations/{conv['_id']}/branch/{msgs[0]['_id']}",
        headers=auth_headers, json={},
    ).json()
    new_branch = created["branch_id"]

    resp = client.put(f"/api/conversations/{conv['_id']}/branch/{new_branch}",
                      headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["active_branch"] == new_branch


def test_delete_branch_main_guard_400(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    resp = client.delete(f"/api/conversations/{conv['_id']}/branch/main",
                         headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Cannot delete the main branch"


def test_delete_branch_happy(client, auth_headers, flask_core, test_user):
    conv, msgs = _seed_conv_with_messages(flask_core, test_user["_id"], n=2)
    created = client.post(
        f"/api/conversations/{conv['_id']}/branch/{msgs[0]['_id']}",
        headers=auth_headers, json={},
    ).json()
    new_branch = created["branch_id"]

    resp = client.delete(f"/api/conversations/{conv['_id']}/branch/{new_branch}",
                         headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_delete_branch_not_found_404(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    resp = client.delete(f"/api/conversations/{conv['_id']}/branch/nope",
                         headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Branch not found"


def test_rename_branch_main_guard_400(client, auth_headers, flask_core, test_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"])
    resp = client.put(f"/api/conversations/{conv['_id']}/branch/main/rename",
                      headers=auth_headers, json={"name": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Cannot rename the main branch"


def test_rename_branch_happy(client, auth_headers, flask_core, test_user):
    conv, msgs = _seed_conv_with_messages(flask_core, test_user["_id"], n=2)
    created = client.post(
        f"/api/conversations/{conv['_id']}/branch/{msgs[0]['_id']}",
        headers=auth_headers, json={},
    ).json()
    new_branch = created["branch_id"]

    resp = client.put(f"/api/conversations/{conv['_id']}/branch/{new_branch}/rename",
                      headers=auth_headers, json={"name": "Renamed"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["branch"]["name"] == "Renamed"


def test_rename_branch_empty_name_400(client, auth_headers, flask_core, test_user):
    conv, msgs = _seed_conv_with_messages(flask_core, test_user["_id"], n=2)
    created = client.post(
        f"/api/conversations/{conv['_id']}/branch/{msgs[0]['_id']}",
        headers=auth_headers, json={},
    ).json()
    new_branch = created["branch_id"]

    resp = client.put(f"/api/conversations/{conv['_id']}/branch/{new_branch}/rename",
                      headers=auth_headers, json={"name": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Branch name is required"


# ---------------------------------------------------------------------------
# Project-ACL on an existing project-scoped conversation: a non-member loses
# read access even though the row exists (mirror _fetch_owned_conversation).
# ---------------------------------------------------------------------------
def test_project_scoped_conversation_denies_removed_member_403(
    client, auth_headers, flask_core, test_user
):
    _ws, proj = _make_project_with_owner(flask_core, owner_user=test_user)
    conv = _make_conversation(flask_core, user_id=test_user["_id"],
                              project_id=proj["_id"])

    # Owner (member) can read it.
    ok = client.get(f"/api/conversations/{conv['_id']}", headers=auth_headers)
    assert ok.status_code == 200, ok.text

    # Now strip the membership: the owner is no longer in the project ACL.
    from app.models.project_member import ProjectMemberModel

    with flask_core.app_context():
        ProjectMemberModel.remove(proj["_id"], str(test_user["_id"]))

    denied = client.get(f"/api/conversations/{conv['_id']}", headers=auth_headers)
    assert denied.status_code == 403
    assert denied.json()["error"] == "Project access denied"


# ---------------------------------------------------------------------------
# Route registration smoke + static-path precedence.
# ---------------------------------------------------------------------------
def test_conversations_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/conversations" in paths
    assert "/api/conversations/search" in paths
    assert "/api/conversations/search/messages" in paths
    assert "/api/conversations/{conversation_id}" in paths
    assert "/api/conversations/{conversation_id}/export" in paths
    assert "/api/conversations/{conversation_id}/move" in paths
    assert "/api/conversations/{conversation_id}/branches" in paths
    assert "/api/conversations/{conversation_id}/branch/{message_id}" in paths
    assert "/api/conversations/{conversation_id}/branch/{branch_id}/rename" in paths


def _active_ws(user_id):
    """The user's org (conftest puts every fixture user in "Test Org")."""
    from app.models.user import UserModel

    return (UserModel.find_by_id(user_id) or {}).get("active_workspace_id")
