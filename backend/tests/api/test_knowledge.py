"""Integration tests for the knowledge / knowledge-folders / folders routers
(app/api/routers/knowledge.py), mirroring tests/api/test_auth.py style.

Three prefixes under test:
    /api/knowledge          (knowledge_router)
    /api/knowledge-folders  (knowledge_folders_router)
    /api/folders            (folders_router)

These are pure-CRUD routes — no LLM / DLP / external HTTP — so nothing is
mocked. Entities (workspaces / projects / knowledge items+folders / conv
folders) are seeded via the real model facades inside a flask_core app_context.
"""
import uuid

import pytest


# ---------------------------------------------------------------------------
# Seeding helpers — all run inside the Flask app_context.
# ---------------------------------------------------------------------------
def _new_uuid() -> str:
    return str(uuid.uuid4())


def _seed_item(flask_core, *, user_id, title="My Note", content="some content",
               tags=None, project_id=None, workspace_id=None, source_type="chat"):
    from app.models.knowledge_item import KnowledgeItemModel

    with flask_core.app_context():
        return KnowledgeItemModel.create(
            user_id=user_id,
            source_type=source_type,
            source_id=_new_uuid(),
            message_id=_new_uuid(),
            content=content,
            title=title,
            tags=tags or [],
            project_id=project_id,
            workspace_id=workspace_id,
        )


def _seed_workspace(flask_core, *, owner_id, name="Acme"):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner_id, type="team")
        # The POST /workspaces/create route registers the creator as an 'owner'
        # member right after WorkspaceModel.create(); the bare facade does not.
        # Without this row the owner has no workspace role, so check_project_access
        # (which resolves project membership via workspace role) would deny them.
        WorkspaceMemberModel.add(
            ws["_id"], owner_id, "owner", invited_by=owner_id, status="active"
        )
        return ws


def _seed_project(flask_core, *, workspace_id, created_by, name="Launch"):
    from app.models.project import ProjectModel

    with flask_core.app_context():
        return ProjectModel.create(
            workspace_id=workspace_id, name=name, created_by=created_by
        )


def _seed_kfolder(flask_core, *, user_id, name="Research", project_id=None,
                  workspace_id=None):
    from app.models.knowledge_folder import KnowledgeFolderModel

    with flask_core.app_context():
        return KnowledgeFolderModel.create(
            user_id, name, project_id=project_id, workspace_id=workspace_id
        )


def _seed_conv_folder(flask_core, *, user_id, name="Chats", project_id=None):
    from app.models.folder import FolderModel

    with flask_core.app_context():
        return FolderModel.create(user_id=user_id, name=name, project_id=project_id)


# ===========================================================================
# Route registration smoke.
# ===========================================================================
def test_knowledge_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/knowledge/list" in paths
    assert "/api/knowledge/search" in paths
    assert "/api/knowledge/tags" in paths
    assert "/api/knowledge/move" in paths
    assert "/api/knowledge/{item_id}" in paths
    assert "/api/knowledge" in paths  # POST create
    assert "/api/knowledge-folders" in paths
    assert "/api/knowledge-folders/reorder" in paths
    assert "/api/knowledge-folders/{folder_id}" in paths
    assert "/api/folders" in paths
    assert "/api/folders/tree" in paths
    assert "/api/folders/reorder" in paths
    assert "/api/folders/{folder_id}" in paths


# ===========================================================================
# Auth gating — every router rejects missing tokens with token_missing.
# ===========================================================================
@pytest.mark.parametrize("method,path", [
    ("get", "/api/knowledge/list"),
    ("get", "/api/knowledge/search?q=x"),
    ("get", "/api/knowledge/tags"),
    ("post", "/api/knowledge"),
    ("put", "/api/knowledge/move"),
    ("get", "/api/knowledge-folders"),
    ("post", "/api/knowledge-folders"),
    ("put", "/api/knowledge-folders/reorder"),
    ("get", "/api/folders"),
    ("get", "/api/folders/tree"),
    ("post", "/api/folders"),
    ("put", "/api/folders/reorder"),
])
def test_no_token_401_token_missing(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_banned_user_403(client, banned_user, mint_token):
    headers = {"Authorization": f"Bearer {mint_token(banned_user['_id'], role='user')}"}
    resp = client.get("/api/knowledge/list", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Account has been suspended"


# ===========================================================================
# /api/knowledge — create + read.
# ===========================================================================
def test_create_knowledge_item_happy(client, auth_headers, test_user):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "chat",
        "source_id": _new_uuid(),
        "message_id": _new_uuid(),
        "content": "Saved answer",
        "title": "Useful Reply",
        "tags": ["AI", "ai", "  ", "Notes"],
    })
    assert resp.status_code == 201, resp.text
    item = resp.json()["item"]
    assert item["_id"]
    assert item["title"] == "Useful Reply"
    assert str(item["user_id"]) == str(test_user["_id"])
    # Tags are lowercased + deduped.
    assert sorted(item["tags"]) == ["ai", "notes"]


def test_create_invalid_source_type_400(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "bogus", "source_id": _new_uuid(),
        "message_id": _new_uuid(), "content": "x", "title": "y",
    })
    assert resp.status_code == 400
    assert "Invalid source_type" in resp.json()["error"]


def test_create_missing_content_400(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "chat", "source_id": _new_uuid(),
        "message_id": _new_uuid(), "content": "", "title": "y",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Content is required"


def test_create_invalid_source_id_400(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "chat", "source_id": "not-a-uuid",
        "message_id": _new_uuid(), "content": "x", "title": "y",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid or missing source_id"


def test_get_knowledge_item_happy(client, auth_headers, flask_core, test_user):
    item = _seed_item(flask_core, user_id=test_user["_id"], title="Hello")
    resp = client.get(f"/api/knowledge/{item['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()["item"]
    assert body["_id"] == str(item["_id"])
    assert body["title"] == "Hello"


def test_get_knowledge_item_invalid_id_400(client, auth_headers):
    resp = client.get("/api/knowledge/not-a-uuid", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid item ID"


def test_get_knowledge_item_not_found_404(client, auth_headers):
    resp = client.get(f"/api/knowledge/{_new_uuid()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Item not found"


def test_get_other_users_item_404(client, auth_headers, plain_headers, flask_core,
                                  plain_user):
    # Item owned by plain_user; test_user (auth_headers) must not see it.
    item = _seed_item(flask_core, user_id=plain_user["_id"], title="Secret")
    resp = client.get(f"/api/knowledge/{item['_id']}", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /api/knowledge/list + /search + /tags.
# ---------------------------------------------------------------------------
def test_list_knowledge_items(client, auth_headers, flask_core, test_user):
    _seed_item(flask_core, user_id=test_user["_id"], title="One")
    _seed_item(flask_core, user_id=test_user["_id"], title="Two")
    resp = client.get("/api/knowledge/list", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert all(it["_id"] for it in body["items"])
    assert body["page"] == 1 and body["limit"] == 20


def test_list_invalid_project_filter_400(client, auth_headers):
    resp = client.get("/api/knowledge/list?project_id=not-a-uuid", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid project_id"


def test_list_project_access_denied_403(client, auth_headers):
    # A real (well-formed) but non-member project id -> ACL denial.
    resp = client.get(f"/api/knowledge/list?project_id={_new_uuid()}", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Project access denied"


def test_search_requires_query_400(client, auth_headers):
    resp = client.get("/api/knowledge/search", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Search query is required"


def test_search_query_too_long_400(client, auth_headers):
    resp = client.get("/api/knowledge/search?q=" + "a" * 201, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Query too long (max 200 characters)"


def test_search_finds_personal_items(client, auth_headers, flask_core, test_user):
    _seed_item(flask_core, user_id=test_user["_id"], title="Quantum Mechanics",
               content="wavefunction collapse")
    _seed_item(flask_core, user_id=test_user["_id"], title="Cooking",
               content="pasta recipe")
    resp = client.get("/api/knowledge/search?q=quantum", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "quantum"
    assert body["total"] >= 1
    assert any("Quantum" in it["title"] for it in body["items"])


def test_get_user_tags(client, auth_headers, flask_core, test_user):
    _seed_item(flask_core, user_id=test_user["_id"], tags=["alpha", "beta"])
    _seed_item(flask_core, user_id=test_user["_id"], tags=["beta", "gamma"])
    resp = client.get("/api/knowledge/tags", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    tags = resp.json()["tags"]
    assert tags == sorted(tags)
    assert {"alpha", "beta", "gamma"}.issubset(set(tags))


# ---------------------------------------------------------------------------
# /api/knowledge/<id> — update + delete.
# ---------------------------------------------------------------------------
def test_update_knowledge_item_happy(client, auth_headers, flask_core, test_user):
    item = _seed_item(flask_core, user_id=test_user["_id"], title="Before")
    resp = client.put(f"/api/knowledge/{item['_id']}", headers=auth_headers, json={
        "title": "After", "is_favorite": True, "notes": "remember this",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()["item"]
    assert body["_id"] == str(item["_id"])
    assert body["title"] == "After"


def test_update_reassign_project_blocked(client, auth_headers, flask_core, test_user):
    item = _seed_item(flask_core, user_id=test_user["_id"])
    resp = client.put(f"/api/knowledge/{item['_id']}", headers=auth_headers, json={
        "project_id": _new_uuid(),
    })
    assert resp.status_code == 400
    assert resp.json()["code"] == "cannot_reassign_project"


def test_update_no_fields_400(client, auth_headers, flask_core, test_user):
    item = _seed_item(flask_core, user_id=test_user["_id"])
    resp = client.put(f"/api/knowledge/{item['_id']}", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "No valid fields to update"


def test_update_not_found_404(client, auth_headers):
    resp = client.put(f"/api/knowledge/{_new_uuid()}", headers=auth_headers,
                      json={"title": "x"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Item not found"


def test_delete_knowledge_item_happy(client, auth_headers, flask_core, test_user):
    item = _seed_item(flask_core, user_id=test_user["_id"])
    resp = client.delete(f"/api/knowledge/{item['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Item deleted"
    # Now gone.
    assert client.get(f"/api/knowledge/{item['_id']}", headers=auth_headers).status_code == 404


def test_delete_not_found_404(client, auth_headers):
    resp = client.delete(f"/api/knowledge/{_new_uuid()}", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /api/knowledge/move.
# ---------------------------------------------------------------------------
def test_move_items_to_folder(client, auth_headers, flask_core, test_user):
    folder = _seed_kfolder(flask_core, user_id=test_user["_id"], name="Bucket")
    item1 = _seed_item(flask_core, user_id=test_user["_id"])
    item2 = _seed_item(flask_core, user_id=test_user["_id"])
    resp = client.put("/api/knowledge/move", headers=auth_headers, json={
        "item_ids": [str(item1["_id"]), str(item2["_id"])],
        "folder_id": str(folder["_id"]),
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["moved_count"] == 2


def test_move_requires_item_ids_400(client, auth_headers):
    resp = client.put("/api/knowledge/move", headers=auth_headers, json={"item_ids": []})
    assert resp.status_code == 400
    assert resp.json()["error"] == "item_ids array is required"


def test_move_invalid_item_id_400(client, auth_headers):
    resp = client.put("/api/knowledge/move", headers=auth_headers, json={
        "item_ids": ["not-a-uuid"],
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid item ID in list"


def test_move_item_not_found_404(client, auth_headers):
    resp = client.put("/api/knowledge/move", headers=auth_headers, json={
        "item_ids": [_new_uuid()],
    })
    assert resp.status_code == 404


# ===========================================================================
# Project-scoped ACL — workspace owner is an implicit project editor.
# ===========================================================================
def test_create_project_scoped_item_as_workspace_owner(client, auth_headers,
                                                       flask_core, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    proj = _seed_project(flask_core, workspace_id=ws["_id"], created_by=test_user["_id"])
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "chat", "source_id": _new_uuid(),
        "message_id": _new_uuid(), "content": "scoped", "title": "Scoped",
        "project_id": str(proj["_id"]),
    })
    assert resp.status_code == 201, resp.text
    item = resp.json()["item"]
    assert str(item["project_id"]) == str(proj["_id"])
    # workspace_id auto-derived from the project.
    assert str(item["workspace_id"]) == str(ws["_id"])


def test_create_project_scoped_item_access_denied_403(client, plain_headers,
                                                     flask_core, test_user):
    # Project lives in test_user's workspace; plain_user is NOT a member.
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    proj = _seed_project(flask_core, workspace_id=ws["_id"], created_by=test_user["_id"])
    resp = client.post("/api/knowledge", headers=plain_headers, json={
        "source_type": "chat", "source_id": _new_uuid(),
        "message_id": _new_uuid(), "content": "x", "title": "y",
        "project_id": str(proj["_id"]),
    })
    assert resp.status_code == 403
    assert resp.json()["error"] == "Project access denied"


# ===========================================================================
# /api/knowledge-folders.
# ===========================================================================
def test_create_knowledge_folder_happy(client, auth_headers, test_user):
    resp = client.post("/api/knowledge-folders", headers=auth_headers, json={
        "name": "Research", "color": "#abcdef",
    })
    assert resp.status_code == 201, resp.text
    folder = resp.json()["folder"]
    assert folder["_id"]
    assert folder["name"] == "Research"


def test_create_knowledge_folder_requires_name_400(client, auth_headers):
    resp = client.post("/api/knowledge-folders", headers=auth_headers, json={"name": ""})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Folder name is required"


def test_create_knowledge_folder_duplicate_400(client, auth_headers, flask_core,
                                              test_user):
    _seed_kfolder(flask_core, user_id=test_user["_id"], name="Dupe")
    resp = client.post("/api/knowledge-folders", headers=auth_headers, json={"name": "dupe"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "A folder with this name already exists"


def test_list_knowledge_folders(client, auth_headers, flask_core, test_user):
    _seed_kfolder(flask_core, user_id=test_user["_id"], name="A")
    _seed_kfolder(flask_core, user_id=test_user["_id"], name="B")
    resp = client.get("/api/knowledge-folders", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["folders"]) == 2
    assert all("item_count" in f for f in body["folders"])
    assert "unfiled_count" in body


def test_get_knowledge_folder_happy(client, auth_headers, flask_core, test_user):
    folder = _seed_kfolder(flask_core, user_id=test_user["_id"], name="One")
    resp = client.get(f"/api/knowledge-folders/{folder['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()["folder"]
    assert body["_id"] == str(folder["_id"])
    assert "item_count" in body


def test_get_knowledge_folder_not_found_404(client, auth_headers):
    resp = client.get(f"/api/knowledge-folders/{_new_uuid()}", headers=auth_headers)
    assert resp.status_code == 404


def test_update_knowledge_folder_happy(client, auth_headers, flask_core, test_user):
    folder = _seed_kfolder(flask_core, user_id=test_user["_id"], name="Old")
    resp = client.put(f"/api/knowledge-folders/{folder['_id']}", headers=auth_headers,
                      json={"name": "New", "color": "#123456"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["folder"]["name"] == "New"


def test_update_knowledge_folder_reassign_project_blocked(client, auth_headers,
                                                        flask_core, test_user):
    folder = _seed_kfolder(flask_core, user_id=test_user["_id"], name="X")
    resp = client.put(f"/api/knowledge-folders/{folder['_id']}", headers=auth_headers,
                      json={"project_id": _new_uuid()})
    assert resp.status_code == 400
    assert resp.json()["code"] == "cannot_reassign_project"


def test_delete_knowledge_folder_happy(client, auth_headers, flask_core, test_user):
    folder = _seed_kfolder(flask_core, user_id=test_user["_id"], name="Trash")
    resp = client.delete(f"/api/knowledge-folders/{folder['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Folder deleted"


def test_delete_knowledge_folder_not_found_404(client, auth_headers):
    resp = client.delete(f"/api/knowledge-folders/{_new_uuid()}", headers=auth_headers)
    assert resp.status_code == 404


def test_reorder_knowledge_folders_happy(client, auth_headers, flask_core, test_user):
    f1 = _seed_kfolder(flask_core, user_id=test_user["_id"], name="One")
    f2 = _seed_kfolder(flask_core, user_id=test_user["_id"], name="Two")
    resp = client.put("/api/knowledge-folders/reorder", headers=auth_headers, json={
        "orders": [
            {"folder_id": str(f1["_id"]), "order": 1},
            {"folder_id": str(f2["_id"]), "order": 0},
        ],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Folders reordered"


def test_reorder_knowledge_folders_requires_orders_400(client, auth_headers):
    resp = client.put("/api/knowledge-folders/reorder", headers=auth_headers,
                      json={"orders": []})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Orders array is required"


def test_reorder_knowledge_folders_bad_order_type_400(client, auth_headers, flask_core,
                                                    test_user):
    f1 = _seed_kfolder(flask_core, user_id=test_user["_id"], name="One")
    resp = client.put("/api/knowledge-folders/reorder", headers=auth_headers, json={
        "orders": [{"folder_id": str(f1["_id"]), "order": "nope"}],
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Order must be an integer"


# ===========================================================================
# /api/folders — conversation folders.
# ===========================================================================
def test_create_conv_folder_happy(client, auth_headers, test_user):
    resp = client.post("/api/folders", headers=auth_headers, json={"name": "Chats"})
    assert resp.status_code == 201, resp.text
    folder = resp.json()["folder"]
    assert folder["_id"]
    assert folder["name"] == "Chats"


def test_create_conv_folder_requires_name_400(client, auth_headers):
    resp = client.post("/api/folders", headers=auth_headers, json={"name": ""})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Folder name is required"


def test_create_conv_folder_invalid_project_400(client, auth_headers):
    resp = client.post("/api/folders", headers=auth_headers, json={
        "name": "x", "project_id": "not-a-uuid",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid project_id"


def test_create_conv_folder_project_denied_403(client, plain_headers, flask_core,
                                             test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    proj = _seed_project(flask_core, workspace_id=ws["_id"], created_by=test_user["_id"])
    resp = client.post("/api/folders", headers=plain_headers, json={
        "name": "x", "project_id": str(proj["_id"]),
    })
    assert resp.status_code == 403
    assert resp.json()["error"] == "Project access denied"


def test_get_conv_folders(client, auth_headers, flask_core, test_user):
    _seed_conv_folder(flask_core, user_id=test_user["_id"], name="A")
    _seed_conv_folder(flask_core, user_id=test_user["_id"], name="B")
    resp = client.get("/api/folders", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    folders = resp.json()["folders"]
    assert len(folders) == 2
    assert all(f["_id"] for f in folders)


def test_get_conv_folder_tree(client, auth_headers, flask_core, test_user):
    _seed_conv_folder(flask_core, user_id=test_user["_id"], name="Root")
    resp = client.get("/api/folders/tree", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    tree = resp.json()["tree"]
    assert isinstance(tree, list)
    assert any(node["name"] == "Root" for node in tree)
    assert all("children" in node for node in tree)


def test_get_conv_folder_happy(client, auth_headers, flask_core, test_user):
    folder = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="One")
    resp = client.get(f"/api/folders/{folder['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["folder"]["_id"] == str(folder["_id"])
    assert "conversations" in body


def test_get_conv_folder_not_found_404(client, auth_headers):
    resp = client.get(f"/api/folders/{_new_uuid()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Folder not found"


def test_update_conv_folder_happy(client, auth_headers, flask_core, test_user):
    folder = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="Old")
    resp = client.put(f"/api/folders/{folder['_id']}", headers=auth_headers,
                      json={"name": "New"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["folder"]["name"] == "New"


def test_update_conv_folder_self_parent_400(client, auth_headers, flask_core, test_user):
    folder = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="Self")
    resp = client.put(f"/api/folders/{folder['_id']}", headers=auth_headers,
                      json={"parent_id": str(folder["_id"])})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Cannot set folder as its own parent"


def test_update_conv_folder_not_found_404(client, auth_headers):
    resp = client.put(f"/api/folders/{_new_uuid()}", headers=auth_headers,
                      json={"name": "x"})
    assert resp.status_code == 404


def test_delete_conv_folder_happy(client, auth_headers, flask_core, test_user):
    folder = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="Bye")
    resp = client.delete(f"/api/folders/{folder['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Folder deleted"
    assert client.get(f"/api/folders/{folder['_id']}", headers=auth_headers).status_code == 404


def test_delete_conv_folder_not_found_404(client, auth_headers):
    resp = client.delete(f"/api/folders/{_new_uuid()}", headers=auth_headers)
    assert resp.status_code == 404


def test_reorder_conv_folders_happy(client, auth_headers, flask_core, test_user):
    f1 = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="One")
    f2 = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="Two")
    resp = client.put("/api/folders/reorder", headers=auth_headers, json={
        "orders": [
            {"folder_id": str(f1["_id"]), "order": 1},
            {"folder_id": str(f2["_id"]), "order": 0},
        ],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Folders reordered"


def test_reorder_conv_folders_no_data_400(client, auth_headers):
    resp = client.put("/api/folders/reorder", headers=auth_headers, json={"orders": []})
    assert resp.status_code == 400
    assert resp.json()["error"] == "No order data provided"


# ===========================================================================
# Routing-order regression: literal /move and /reorder must NOT bind to the
# dynamic /{item_id} / /{folder_id} routes (FastAPI matches by reg order).
# ===========================================================================
def test_put_move_not_shadowed_by_dynamic(client, auth_headers):
    # If /move had been shadowed by PUT /{item_id}, this would 400 "Invalid
    # item ID" instead of the move handler's "item_ids array is required".
    resp = client.put("/api/knowledge/move", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "item_ids array is required"


def test_put_reorder_not_shadowed_by_dynamic(client, auth_headers):
    resp = client.put("/api/knowledge-folders/reorder", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Orders array is required"
    resp2 = client.put("/api/folders/reorder", headers=auth_headers, json={})
    assert resp2.status_code == 400
    assert resp2.json()["error"] == "No order data provided"


# ===========================================================================
# Heavy-``content`` projection — list/search ship a truncated
# ``content_preview`` (not the full Text column); single-item reads stay
# full-fidelity. (perf: list rows no longer carry up-to-50k-char content.)
# ===========================================================================
_LONG_CONTENT = "X" * 1000  # exceeds the 280-char preview cap


def test_list_emits_content_preview_not_full_content(client, auth_headers,
                                                      flask_core, test_user):
    _seed_item(flask_core, user_id=test_user["_id"], title="Long",
               content=_LONG_CONTENT)
    resp = client.get("/api/knowledge/list", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    row = resp.json()["items"][0]
    # Full content column is projected OUT of list rows.
    assert "content" not in row
    # ...replaced by a truncated preview (<= 280 chars, prefix of the original).
    assert "content_preview" in row
    assert row["content_preview"] == _LONG_CONTENT[:280]
    assert len(row["content_preview"]) == 280
    # Every other key the frontend reads survives unchanged.
    assert row["_id"] and row["title"] == "Long"
    assert "tags" in row and "source_type" in row and "created_at" in row


def test_search_emits_content_preview_not_full_content(client, auth_headers,
                                                        flask_core, test_user):
    _seed_item(flask_core, user_id=test_user["_id"], title="Preview Search",
               content=_LONG_CONTENT)
    resp = client.get("/api/knowledge/search?q=preview", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    row = next(it for it in resp.json()["items"] if it["title"] == "Preview Search")
    assert "content" not in row
    assert row["content_preview"] == _LONG_CONTENT[:280]


def test_get_single_item_returns_full_content(client, auth_headers, flask_core,
                                               test_user):
    item = _seed_item(flask_core, user_id=test_user["_id"], title="Full",
                      content=_LONG_CONTENT)
    resp = client.get(f"/api/knowledge/{item['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()["item"]
    # Single-item read keeps the FULL, untruncated content.
    assert body["content"] == _LONG_CONTENT
    assert len(body["content"]) == 1000
    assert "content_preview" not in body


def test_search_still_matches_on_content_terms(client, auth_headers, flask_core,
                                               test_user):
    # The search WHERE clause (ILIKE on full content) is unchanged by the
    # projection: a term that appears ONLY in the body (not the title) must
    # still match, even though the response ships only a preview.
    _seed_item(flask_core, user_id=test_user["_id"], title="Opaque Title",
               content="the secret word is photosynthesis somewhere in the body")
    _seed_item(flask_core, user_id=test_user["_id"], title="Unrelated",
               content="nothing relevant here")
    resp = client.get("/api/knowledge/search?q=photosynthesis", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    titles = {it["title"] for it in body["items"]}
    assert "Opaque Title" in titles
    assert "Unrelated" not in titles
