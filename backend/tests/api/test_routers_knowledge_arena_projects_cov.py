"""Extra line-coverage tests for the knowledge / arena / projects routers.

Complements the existing tests/api/test_knowledge.py, tests/api/test_arena.py,
and tests/api/test_projects.py — targeting branches those files left uncovered
(error/edge paths, project-scoped ACL flows, list?search=, workflow source_type,
arena stream redaction + config-not-found frames).

Same harness as the siblings: real model facades on Postgres via the flask_ctx
bridge, legacy-shaped JSON, conftest fixtures. OpenRouter + the DLP gate are
monkeypatched so nothing hits a real upstream.
"""
import uuid

import pytest


# ---------------------------------------------------------------------------
# Seeding helpers (mirror the siblings).
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


def _seed_workspace(flask_core, *, owner_id, name="Acme", role="owner"):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(
            ws["_id"], owner_id, role, invited_by=owner_id, status="active"
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


def _seed_conv_folder(flask_core, *, user_id, name="Chats", project_id=None,
                      parent_id=None):
    from app.models.folder import FolderModel

    with flask_core.app_context():
        return FolderModel.create(
            user_id=user_id, name=name, project_id=project_id, parent_id=parent_id
        )


def _seed_project_via_api(client, headers, workspace_id, name="Alpha"):
    resp = client.post("/api/projects/create", headers=headers,
                       json={"workspace_id": str(workspace_id), "name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _other_user(flask_core, *, email):
    from app.models.user import UserModel

    with flask_core.app_context():
        return UserModel.create(email=email, password="TestPassword123!",
                                display_name="Other", role="user")


# ===========================================================================
# KNOWLEDGE — /api/knowledge create branches.
# ===========================================================================
def test_create_knowledge_workflow_missing_workflow_id_400(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "workflow", "content": "x", "title": "y",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid or missing workflow_id"


def test_create_knowledge_workflow_invalid_workflow_id_400(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "workflow", "workflow_id": "not-a-uuid",
        "content": "x", "title": "y",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid or missing workflow_id"


def test_create_knowledge_workflow_missing_node_id_400(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "workflow", "workflow_id": _new_uuid(),
        "node_id": "", "content": "x", "title": "y",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Missing node_id"


def test_create_knowledge_workflow_happy(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "workflow", "workflow_id": _new_uuid(),
        "node_id": "node-1", "content": "from a workflow", "title": "WF Note",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["item"]["title"] == "WF Note"


def test_create_knowledge_missing_message_id_400(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "chat", "source_id": _new_uuid(),
        "message_id": "", "content": "x", "title": "y",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid or missing message_id"


def test_create_knowledge_content_too_long_400(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "chat", "source_id": _new_uuid(),
        "message_id": _new_uuid(), "content": "a" * 50001, "title": "y",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Content too long (max 50000 characters)"


def test_create_knowledge_title_required_400(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "chat", "source_id": _new_uuid(),
        "message_id": _new_uuid(), "content": "x", "title": "  ",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Title is required"


def test_create_knowledge_title_too_long_400(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "chat", "source_id": _new_uuid(),
        "message_id": _new_uuid(), "content": "x", "title": "a" * 201,
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Title too long (max 200 characters)"


def test_create_knowledge_tags_not_array_400(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "chat", "source_id": _new_uuid(),
        "message_id": _new_uuid(), "content": "x", "title": "y",
        "tags": "nope",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Tags must be an array"


def test_create_knowledge_invalid_project_id_400(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "chat", "source_id": _new_uuid(),
        "message_id": _new_uuid(), "content": "x", "title": "y",
        "project_id": "not-a-uuid",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid project_id"


def test_create_knowledge_invalid_workspace_id_400(client, auth_headers):
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "chat", "source_id": _new_uuid(),
        "message_id": _new_uuid(), "content": "x", "title": "y",
        "workspace_id": "not-a-uuid",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace_id"


def test_create_knowledge_with_valid_workspace_id(client, auth_headers, flask_core,
                                                  test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    resp = client.post("/api/knowledge", headers=auth_headers, json={
        "source_type": "chat", "source_id": _new_uuid(),
        "message_id": _new_uuid(), "content": "x", "title": "WS scoped",
        "workspace_id": str(ws["_id"]),
    })
    assert resp.status_code == 201, resp.text
    assert str(resp.json()["item"]["workspace_id"]) == str(ws["_id"])


# ---------------------------------------------------------------------------
# /api/knowledge/list with ?project_id=null and ?search=.
# ---------------------------------------------------------------------------
def test_list_knowledge_null_project_filter(client, auth_headers, flask_core,
                                            test_user):
    _seed_item(flask_core, user_id=test_user["_id"], title="Personal")
    resp = client.get("/api/knowledge/list?project_id=null", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert any(it["title"] == "Personal" for it in body["items"])


def test_list_knowledge_with_search_param(client, auth_headers, flask_core,
                                          test_user):
    _seed_item(flask_core, user_id=test_user["_id"], title="Photosynthesis",
               content="chlorophyll")
    _seed_item(flask_core, user_id=test_user["_id"], title="Other")
    resp = client.get("/api/knowledge/list?search=photosynthesis", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert any("Photosynthesis" in it["title"] for it in body["items"])


def test_search_uses_workspace_accessible_projects(client, auth_headers, flask_core,
                                                   test_user):
    # Exercise _accessible_project_ids: workspace membership -> implied project
    # ids, plus an explicit project membership.
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    proj = _seed_project(flask_core, workspace_id=ws["_id"], created_by=test_user["_id"])
    from app.models.project_member import ProjectMemberModel

    with flask_core.app_context():
        ProjectMemberModel.add(proj["_id"], test_user["_id"], "editor",
                               added_by=test_user["_id"])
    _seed_item(flask_core, user_id=test_user["_id"], title="Relativity",
               content="spacetime", project_id=proj["_id"], workspace_id=ws["_id"])
    resp = client.get("/api/knowledge/search?q=relativity", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] >= 1


# ---------------------------------------------------------------------------
# /api/knowledge/move branches.
# ---------------------------------------------------------------------------
def test_move_invalid_folder_id_400(client, auth_headers, flask_core, test_user):
    item = _seed_item(flask_core, user_id=test_user["_id"])
    resp = client.put("/api/knowledge/move", headers=auth_headers, json={
        "item_ids": [str(item["_id"])], "folder_id": "not-a-uuid",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid folder ID"


def test_move_target_folder_not_found_404(client, auth_headers, flask_core, test_user):
    item = _seed_item(flask_core, user_id=test_user["_id"])
    resp = client.put("/api/knowledge/move", headers=auth_headers, json={
        "item_ids": [str(item["_id"])], "folder_id": _new_uuid(),
    })
    assert resp.status_code == 404
    assert resp.json()["error"] == "Target folder not found"


def test_move_to_root_no_sync(client, auth_headers, flask_core, test_user):
    # No folder_id => target_project_id None; items are already personal-scope =>
    # needs_project_sync stays False (exercises the else branch of move).
    item = _seed_item(flask_core, user_id=test_user["_id"])
    resp = client.put("/api/knowledge/move", headers=auth_headers, json={
        "item_ids": [str(item["_id"])],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["moved_count"] == 1


# ---------------------------------------------------------------------------
# Project-scoped knowledge item: get / delete access-denied (item has project_id
# the *requesting* user can no longer access).
# ---------------------------------------------------------------------------
def test_get_project_scoped_item_access_denied_403(client, plain_headers, flask_core,
                                                   test_user, plain_user):
    # Item belongs to plain_user but is scoped to test_user's project, which
    # plain_user cannot access -> 403 (item is theirs, project denies).
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    proj = _seed_project(flask_core, workspace_id=ws["_id"], created_by=test_user["_id"])
    item = _seed_item(flask_core, user_id=plain_user["_id"], project_id=proj["_id"],
                      workspace_id=ws["_id"])
    resp = client.get(f"/api/knowledge/{item['_id']}", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Project access denied"


def test_delete_project_scoped_item_access_denied_403(client, plain_headers, flask_core,
                                                      test_user, plain_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    proj = _seed_project(flask_core, workspace_id=ws["_id"], created_by=test_user["_id"])
    item = _seed_item(flask_core, user_id=plain_user["_id"], project_id=proj["_id"],
                      workspace_id=ws["_id"])
    resp = client.delete(f"/api/knowledge/{item['_id']}", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Project access denied"


# ---------------------------------------------------------------------------
# /api/knowledge/<id> update branches.
# ---------------------------------------------------------------------------
def test_update_knowledge_invalid_id_400(client, auth_headers):
    resp = client.put("/api/knowledge/not-a-uuid", headers=auth_headers,
                      json={"title": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid item ID"


def test_update_knowledge_empty_title_400(client, auth_headers, flask_core, test_user):
    item = _seed_item(flask_core, user_id=test_user["_id"])
    resp = client.put(f"/api/knowledge/{item['_id']}", headers=auth_headers,
                      json={"title": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Title cannot be empty"


def test_update_knowledge_title_too_long_400(client, auth_headers, flask_core, test_user):
    item = _seed_item(flask_core, user_id=test_user["_id"])
    resp = client.put(f"/api/knowledge/{item['_id']}", headers=auth_headers,
                      json={"title": "a" * 201})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Title too long (max 200 characters)"


def test_update_knowledge_tags_not_array_400(client, auth_headers, flask_core, test_user):
    item = _seed_item(flask_core, user_id=test_user["_id"])
    resp = client.put(f"/api/knowledge/{item['_id']}", headers=auth_headers,
                      json={"tags": "nope"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Tags must be an array"


def test_update_knowledge_notes_too_long_400(client, auth_headers, flask_core, test_user):
    item = _seed_item(flask_core, user_id=test_user["_id"])
    resp = client.put(f"/api/knowledge/{item['_id']}", headers=auth_headers,
                      json={"notes": "a" * 5001})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Notes too long (max 5000 characters)"


def test_update_knowledge_invalid_folder_id_400(client, auth_headers, flask_core,
                                                test_user):
    item = _seed_item(flask_core, user_id=test_user["_id"])
    resp = client.put(f"/api/knowledge/{item['_id']}", headers=auth_headers,
                      json={"folder_id": "not-a-uuid"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid folder ID"


def test_update_knowledge_tags_and_folder_to_root(client, auth_headers, flask_core,
                                                  test_user):
    folder = _seed_kfolder(flask_core, user_id=test_user["_id"], name="Bucket")
    item = _seed_item(flask_core, user_id=test_user["_id"])
    resp = client.put(f"/api/knowledge/{item['_id']}", headers=auth_headers, json={
        "tags": ["X", "x", " "], "folder_id": str(folder["_id"]),
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["item"]["tags"] == ["x"]
    # Now move it to root (folder_id None).
    resp2 = client.put(f"/api/knowledge/{item['_id']}", headers=auth_headers,
                       json={"folder_id": None})
    assert resp2.status_code == 200, resp2.text


def test_delete_knowledge_invalid_id_400(client, auth_headers):
    resp = client.delete("/api/knowledge/not-a-uuid", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid item ID"


# ===========================================================================
# KNOWLEDGE FOLDERS — branches.
# ===========================================================================
def test_list_kfolders_invalid_project_400(client, auth_headers):
    resp = client.get("/api/knowledge-folders?project_id=not-a-uuid", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid project_id"


def test_list_kfolders_project_denied_403(client, auth_headers):
    resp = client.get(f"/api/knowledge-folders?project_id={_new_uuid()}",
                      headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Project access denied"


def test_create_kfolder_name_too_long_400(client, auth_headers):
    resp = client.post("/api/knowledge-folders", headers=auth_headers,
                       json={"name": "a" * 101})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Folder name too long (max 100 characters)"


def test_create_kfolder_invalid_project_400(client, auth_headers):
    resp = client.post("/api/knowledge-folders", headers=auth_headers,
                       json={"name": "x", "project_id": "not-a-uuid"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid project_id"


def test_create_kfolder_project_denied_403(client, auth_headers):
    resp = client.post("/api/knowledge-folders", headers=auth_headers,
                       json={"name": "x", "project_id": _new_uuid()})
    assert resp.status_code == 403
    assert resp.json()["error"] == "Project access denied"


def test_create_kfolder_invalid_workspace_400(client, auth_headers):
    resp = client.post("/api/knowledge-folders", headers=auth_headers,
                       json={"name": "x", "workspace_id": "not-a-uuid"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace_id"


def test_create_kfolder_project_scoped_and_bad_color(client, auth_headers, flask_core,
                                                    test_user):
    # Project-scoped folder (derives workspace_id) + a bad color (falls back to
    # the default #5c9aed).
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    proj = _seed_project(flask_core, workspace_id=ws["_id"], created_by=test_user["_id"])
    resp = client.post("/api/knowledge-folders", headers=auth_headers, json={
        "name": "Scoped Folder", "project_id": str(proj["_id"]),
        "color": "blue",
    })
    assert resp.status_code == 201, resp.text
    folder = resp.json()["folder"]
    assert folder["color"] == "#5c9aed"
    assert str(folder["project_id"]) == str(proj["_id"])


def test_create_kfolder_with_workspace_id(client, auth_headers, flask_core, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    resp = client.post("/api/knowledge-folders", headers=auth_headers, json={
        "name": "WS Folder", "workspace_id": str(ws["_id"]),
    })
    assert resp.status_code == 201, resp.text


def test_reorder_kfolders_invalid_folder_id_400(client, auth_headers):
    resp = client.put("/api/knowledge-folders/reorder", headers=auth_headers, json={
        "orders": [{"folder_id": "not-a-uuid", "order": 0}],
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid folder ID in orders"


def test_get_kfolder_invalid_id_400(client, auth_headers):
    resp = client.get("/api/knowledge-folders/not-a-uuid", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid folder ID"


def test_update_kfolder_invalid_id_400(client, auth_headers):
    resp = client.put("/api/knowledge-folders/not-a-uuid", headers=auth_headers,
                      json={"name": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid folder ID"


def test_update_kfolder_empty_name_400(client, auth_headers, flask_core, test_user):
    folder = _seed_kfolder(flask_core, user_id=test_user["_id"], name="Keep")
    resp = client.put(f"/api/knowledge-folders/{folder['_id']}", headers=auth_headers,
                      json={"name": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Folder name cannot be empty"


def test_update_kfolder_name_too_long_400(client, auth_headers, flask_core, test_user):
    folder = _seed_kfolder(flask_core, user_id=test_user["_id"], name="Keep2")
    resp = client.put(f"/api/knowledge-folders/{folder['_id']}", headers=auth_headers,
                      json={"name": "a" * 101})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Folder name too long (max 100 characters)"


def test_update_kfolder_color_only_returns_404(client, auth_headers, flask_core,
                                              test_user):
    # The route validates + stages a `color` update, but KnowledgeFolderModel.update
    # only permits the `name` field (allowed = {'name'}); a color-only payload
    # yields an empty `clean` dict -> update() returns False -> the route reports
    # 404 "Folder not found" even though the folder exists.
    # NOTE: possible bug — a color-only knowledge-folder update 404s on an
    # existing folder (the color is silently unsupported at the model layer while
    # the route accepts it).
    folder = _seed_kfolder(flask_core, user_id=test_user["_id"], name="Colorful")
    resp = client.put(f"/api/knowledge-folders/{folder['_id']}", headers=auth_headers,
                      json={"color": "#0a0b0c"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Folder not found"


def test_update_kfolder_no_valid_fields_400(client, auth_headers, flask_core, test_user):
    folder = _seed_kfolder(flask_core, user_id=test_user["_id"], name="Empty")
    # Only a bad color (rejected silently) => no updates => 400.
    resp = client.put(f"/api/knowledge-folders/{folder['_id']}", headers=auth_headers,
                      json={"color": "blue"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "No valid fields to update"


def test_update_kfolder_duplicate_name_400(client, auth_headers, flask_core, test_user):
    _seed_kfolder(flask_core, user_id=test_user["_id"], name="Existing")
    folder = _seed_kfolder(flask_core, user_id=test_user["_id"], name="Renamer")
    resp = client.put(f"/api/knowledge-folders/{folder['_id']}", headers=auth_headers,
                      json={"name": "Existing"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "duplicate_name"


def test_update_kfolder_not_found_404(client, auth_headers):
    resp = client.put(f"/api/knowledge-folders/{_new_uuid()}", headers=auth_headers,
                      json={"name": "ghost"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Folder not found"


def test_delete_kfolder_invalid_id_400(client, auth_headers):
    resp = client.delete("/api/knowledge-folders/not-a-uuid", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid folder ID"


# ===========================================================================
# CONVERSATION FOLDERS — branches.
# ===========================================================================
def test_list_conv_folders_invalid_project_400(client, auth_headers):
    resp = client.get("/api/folders?project_id=not-a-uuid", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid project_id"


def test_list_conv_folders_project_denied_403(client, auth_headers):
    resp = client.get(f"/api/folders?project_id={_new_uuid()}", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Project access denied"


def test_create_conv_folder_name_too_long_400(client, auth_headers):
    resp = client.post("/api/folders", headers=auth_headers, json={"name": "a" * 101})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Folder name too long"


def test_create_conv_folder_project_scoped(client, auth_headers, flask_core, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    proj = _seed_project(flask_core, workspace_id=ws["_id"], created_by=test_user["_id"])
    resp = client.post("/api/folders", headers=auth_headers, json={
        "name": "Scoped Convs", "project_id": str(proj["_id"]), "icon": "star",
    })
    assert resp.status_code == 201, resp.text


def test_update_conv_folder_empty_name_400(client, auth_headers, flask_core, test_user):
    folder = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="Keep")
    resp = client.put(f"/api/folders/{folder['_id']}", headers=auth_headers,
                      json={"name": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Folder name is required"


def test_update_conv_folder_name_too_long_400(client, auth_headers, flask_core, test_user):
    folder = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="Keep2")
    resp = client.put(f"/api/folders/{folder['_id']}", headers=auth_headers,
                      json={"name": "a" * 101})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Folder name too long"


def test_update_conv_folder_color_icon(client, auth_headers, flask_core, test_user):
    # The route stages color + icon updates, but FolderModel.update deliberately
    # IGNORES color/icon ("Not modelled in ORM") — the update succeeds (200) yet
    # the persisted color stays at its seeded default. We assert the real shape.
    folder = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="Styler")
    resp = client.put(f"/api/folders/{folder['_id']}", headers=auth_headers,
                      json={"color": "#aabbcc", "icon": "folder"})
    assert resp.status_code == 200, resp.text
    body = resp.json()["folder"]
    # color/icon are dropped at the ORM layer -> seeded default unchanged.
    assert body["color"] == "#5c9aed"


def test_update_conv_folder_reparent_happy(client, auth_headers, flask_core, test_user):
    parent = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="Parent")
    child = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="Child")
    resp = client.put(f"/api/folders/{child['_id']}", headers=auth_headers,
                      json={"parent_id": str(parent["_id"])})
    assert resp.status_code == 200, resp.text


def test_update_conv_folder_parent_not_found_404(client, auth_headers, flask_core,
                                                test_user):
    folder = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="Orphan")
    resp = client.put(f"/api/folders/{folder['_id']}", headers=auth_headers,
                      json={"parent_id": _new_uuid()})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Parent folder not found"


def test_update_conv_folder_clear_parent(client, auth_headers, flask_core, test_user):
    parent = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="P")
    child = _seed_conv_folder(flask_core, user_id=test_user["_id"], name="C",
                              parent_id=None)
    # Set parent then clear it (parent_id falsy branch).
    client.put(f"/api/folders/{child['_id']}", headers=auth_headers,
               json={"parent_id": str(parent["_id"])})
    resp = client.put(f"/api/folders/{child['_id']}", headers=auth_headers,
                      json={"parent_id": None})
    assert resp.status_code == 200, resp.text


# ===========================================================================
# ARENA — create_session project access denied + stream redaction / config-404.
# ===========================================================================
QUICK_A = "quick:google/gemini-3.5-flash-lite"
QUICK_B = "quick:x-ai/grok-4.5"


def test_create_session_project_access_denied_403(client, auth_headers):
    # Valid 24-hex ObjectId-shaped project_id, but check_project_access denies
    # (no real project matches it on the UUID datastore).
    resp = client.post("/api/arena/sessions", headers=auth_headers, json={
        "config_ids": [QUICK_A, QUICK_B], "project_id": "a" * 24,
    })
    assert resp.status_code == 403
    assert resp.json()["code"] == "project_access_denied"


def _fake_stream(content):
    def _gen(*args, **kwargs):
        yield {"choices": [{"delta": {"content": content}}],
               "usage": {"prompt_tokens": 3, "completion_tokens": 5}}
        yield {"done": True}
    return _gen


@pytest.fixture
def patch_openrouter(monkeypatch):
    from app.services.openrouter_service import OpenRouterService

    monkeypatch.setattr(
        OpenRouterService, "chat_completion", staticmethod(_fake_stream("pong")),
    )
    return monkeypatch


@pytest.fixture
def real_config_ids(flask_core, test_user):
    from app.models.llm_config import LLMConfigModel

    with flask_core.app_context():
        a = LLMConfigModel.create(
            name="Config A", model_id="openai/gpt-4o-mini", model_name="GPT-4o mini",
            owner_id=test_user["_id"],
        )
        b = LLMConfigModel.create(
            name="Config B", model_id="anthropic/claude-3.5-haiku",
            model_name="Claude Haiku", owner_id=test_user["_id"],
        )
    return [a["_id"], b["_id"]]


def _read_sse(resp):
    return b"".join(resp.iter_bytes()).decode("utf-8")


def test_stream_quick_configs_emit_events(client, auth_headers,
                                          patch_openrouter):
    # quick:* ids resolve via resolve_arena_config (same as debate) and fan out.
    with client.stream(
        "POST", "/api/arena/stream", headers=auth_headers,
        json={"config_ids": [QUICK_A, QUICK_B], "message": "hi there"},
    ) as resp:
        assert resp.status_code == 200
        text = _read_sse(resp)
    assert "event: arena_session_created" in text
    assert "event: arena_user_message" in text
    assert "event: arena_message_complete" in text
    assert "Config not found" not in text


def test_stream_redaction_scrubs_message(client, auth_headers, monkeypatch,
                                         patch_openrouter, real_config_ids):
    # Force the DLP gate to report a redaction so the handler swaps in the
    # scrubbed text (line: message_content = arena_gate_res["redacted_text"]).
    import app.api.routers.arena as arena_mod

    def _fake_gate(**kwargs):
        return {"redacted": True, "redacted_text": "[REDACTED] message"}

    monkeypatch.setattr(arena_mod, "gate_redactable", _fake_gate)

    with client.stream(
        "POST", "/api/arena/stream", headers=auth_headers,
        json={"config_ids": real_config_ids, "message": "secret 1234",
              "dlp_redact": True},
    ) as resp:
        assert resp.status_code == 200
        text = _read_sse(resp)
    assert "event: arena_user_message" in text
    # The persisted user message holds the scrubbed text.
    assert "[REDACTED] message" in text
    assert "event: arena_message_complete" in text


def test_stream_multi_turn_history_filtering(client, auth_headers, patch_openrouter,
                                            real_config_ids):
    # First turn persists user + assistant messages; a second turn exercises the
    # history-formatting branch that keeps assistant turns matching each config.
    for _ in range(2):
        with client.stream(
            "POST", "/api/arena/stream", headers=auth_headers,
            json={"config_ids": real_config_ids, "message": "round"},
        ) as resp:
            assert resp.status_code == 200
            _read_sse(resp)
    # Both turns landed (2 user + 4 assistant across the shared session is not
    # guaranteed since each call creates a new session; just assert the second
    # call still completed). The real win is executing the formatting branch.


def test_stream_into_existing_session_history(client, auth_headers, patch_openrouter,
                                             real_config_ids):
    # Create a session with quick:* ids (real UUID config ids fail the
    # session-CREATE ObjectId.is_valid guard), stream once, then stream again
    # INTO the same session with REAL config ids so the history now contains an
    # assistant message with a matching config_id (exercises the assistant
    # history-append branch in _produce).
    first = client.post("/api/arena/sessions", headers=auth_headers,
                        json={"config_ids": [QUICK_A, QUICK_B], "title": "Hist"})
    sid = first.json()["session"]["_id"]
    for _ in range(2):
        with client.stream(
            "POST", "/api/arena/stream", headers=auth_headers,
            json={"session_id": sid, "config_ids": real_config_ids,
                  "message": "turn"},
        ) as resp:
            assert resp.status_code == 200
            _read_sse(resp)

    detail = client.get(f"/api/arena/sessions/{sid}", headers=auth_headers).json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles.count("user") == 2
    assert roles.count("assistant") == 4


# ===========================================================================
# PROJECTS — update field branches + members + access + webhooks.
# ===========================================================================
def test_update_project_empty_name_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.patch(f"/api/projects/{project['_id']}", headers=auth_headers,
                       json={"name": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"] == "name cannot be empty"


def test_update_project_name_too_long_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.patch(f"/api/projects/{project['_id']}", headers=auth_headers,
                       json={"name": "a" * 101})
    assert resp.status_code == 400
    assert resp.json()["error"] == "name must be at most 100 characters"


def test_update_project_all_optional_fields(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.patch(f"/api/projects/{project['_id']}", headers=auth_headers, json={
        "color": "#123123", "icon": "rocket", "description": "desc",
        "default_model": "openai/gpt-4o-mini", "default_temperature": 0.5,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["color"] == "#123123"
    assert body["icon"] == "rocket"
    assert body["description"] == "desc"


# ---------------------------------------------------------------------------
# Members.
# ---------------------------------------------------------------------------
def test_add_member_invalid_user_id_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.post(f"/api/projects/{project['_id']}/members", headers=auth_headers,
                      json={"user_id": "not-a-uuid", "role": "editor"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Valid user_id is required"


def test_update_member_bad_role_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    target = _other_user(flask_core, email="badrole@gmail.com")
    from app.models.workspace_member import WorkspaceMemberModel
    from app.models.project_member import ProjectMemberModel

    with flask_core.app_context():
        WorkspaceMemberModel.add(ws["_id"], target["_id"], "viewer", status="active")
        ProjectMemberModel.add(project["_id"], target["_id"], "viewer",
                               added_by=test_user["_id"])
    resp = client.patch(f"/api/projects/{project['_id']}/members/{target['_id']}",
                       headers=auth_headers, json={"role": "owner"})
    assert resp.status_code == 400
    assert "role must be one of" in resp.json()["error"]


def test_update_member_demote_last_owner_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    # The creator is the lone explicit owner; demoting to editor is refused.
    resp = client.patch(f"/api/projects/{project['_id']}/members/{test_user['_id']}",
                       headers=auth_headers, json={"role": "editor"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "last_owner_protected"


def test_remove_member_not_found_404(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.delete(f"/api/projects/{project['_id']}/members/{uuid.uuid4()}",
                        headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Member not found"


# ---------------------------------------------------------------------------
# pin / tags additional branches.
# ---------------------------------------------------------------------------
def test_patch_tags_non_string_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.patch(f"/api/projects/{project['_id']}/tags", headers=auth_headers,
                       json={"tags": ["ok", 5]})
    assert resp.status_code == 400
    assert resp.json()["error"] == "tags must be strings"


# ---------------------------------------------------------------------------
# Access page with a group grant hydrated.
# ---------------------------------------------------------------------------
def test_get_access_with_group_grant(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    from app.models.group import GroupModel
    from app.models.group_member import GroupMemberModel

    member = _other_user(flask_core, email="ingroup@gmail.com")
    with flask_core.app_context():
        group = GroupModel.create(workspace_id=ws["_id"], name="Squad",
                                  created_by=test_user["_id"])
        GroupMemberModel.add(group["_id"], member["_id"], added_by=test_user["_id"])
    # Grant the group access on the project so the grant-hydration loop runs.
    granted = client.post(f"/api/projects/{project['_id']}/access/groups",
                         headers=auth_headers,
                         json={"group_id": str(group["_id"]), "role": "viewer"})
    assert granted.status_code == 201, granted.text
    resp = client.get(f"/api/projects/{project['_id']}/access", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(g["name"] == "Squad" for g in body["groups"])


def test_upsert_group_access_invalid_group_id_400(client, flask_core, auth_headers,
                                                 test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.post(f"/api/projects/{project['_id']}/access/groups",
                      headers=auth_headers, json={"group_id": "nope", "role": "viewer"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Valid group_id is required"


def test_upsert_group_access_group_not_found_404(client, flask_core, auth_headers,
                                                test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.post(f"/api/projects/{project['_id']}/access/groups",
                      headers=auth_headers,
                      json={"group_id": _new_uuid(), "role": "viewer"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Group not found"


def test_upsert_group_access_workspace_mismatch_400(client, flask_core, auth_headers,
                                                   test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"], name="WS1")
    other_ws = _seed_workspace(flask_core, owner_id=test_user["_id"], name="WS2")
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    from app.models.group import GroupModel

    with flask_core.app_context():
        # Group belongs to a DIFFERENT workspace than the project.
        group = GroupModel.create(workspace_id=other_ws["_id"], name="Foreign",
                                  created_by=test_user["_id"])
    resp = client.post(f"/api/projects/{project['_id']}/access/groups",
                      headers=auth_headers,
                      json={"group_id": str(group["_id"]), "role": "viewer"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "group_workspace_mismatch"


def test_upsert_group_access_bad_expires_at_400(client, flask_core, auth_headers,
                                               test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    from app.models.group import GroupModel

    with flask_core.app_context():
        group = GroupModel.create(workspace_id=ws["_id"], name="Timed",
                                  created_by=test_user["_id"])
    resp = client.post(f"/api/projects/{project['_id']}/access/groups",
                      headers=auth_headers,
                      json={"group_id": str(group["_id"]), "role": "editor",
                            "expires_at": "not-a-date"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "expires_at must be ISO 8601"


def test_upsert_group_access_with_expires_at(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    from app.models.group import GroupModel

    with flask_core.app_context():
        group = GroupModel.create(workspace_id=ws["_id"], name="Expiring",
                                  created_by=test_user["_id"])
    resp = client.post(f"/api/projects/{project['_id']}/access/groups",
                      headers=auth_headers,
                      json={"group_id": str(group["_id"]), "role": "editor",
                            "expires_at": "2099-01-01T00:00:00Z"})
    assert resp.status_code == 201, resp.text


def test_remove_group_access_happy(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    from app.models.group import GroupModel

    with flask_core.app_context():
        group = GroupModel.create(workspace_id=ws["_id"], name="Removable",
                                  created_by=test_user["_id"])
    client.post(f"/api/projects/{project['_id']}/access/groups", headers=auth_headers,
               json={"group_id": str(group["_id"]), "role": "viewer"})
    resp = client.delete(
        f"/api/projects/{project['_id']}/access/groups/{group['_id']}",
        headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Group access removed"


# ---------------------------------------------------------------------------
# Webhooks additional branches.
# ---------------------------------------------------------------------------
def test_create_webhook_missing_url_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.post(f"/api/projects/{project['_id']}/webhooks", headers=auth_headers,
                      json={"name": "hook"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "url is required"


def test_create_webhook_events_not_list_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    resp = client.post(f"/api/projects/{project['_id']}/webhooks", headers=auth_headers,
                      json={"name": "hook", "url": "https://e.com", "events": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "events must be a list of strings"


def test_update_webhook_no_fields_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    created = client.post(f"/api/projects/{project['_id']}/webhooks",
                         headers=auth_headers,
                         json={"name": "hook", "url": "https://e.com"}).json()
    resp = client.put(f"/api/projects/{project['_id']}/webhooks/{created['_id']}",
                     headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "No valid fields to update"


def test_update_webhook_bad_events_400(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    created = client.post(f"/api/projects/{project['_id']}/webhooks",
                         headers=auth_headers,
                         json={"name": "hook", "url": "https://e.com"}).json()
    # events as a non-list reaches ProjectWebhookModel.update -> ValueError -> 400.
    resp = client.put(f"/api/projects/{project['_id']}/webhooks/{created['_id']}",
                     headers=auth_headers, json={"events": "nope"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "events must be a list of strings"


def test_update_webhook_wrong_project_404(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    p1 = _seed_project_via_api(client, auth_headers, ws["_id"], name="P1")
    p2 = _seed_project_via_api(client, auth_headers, ws["_id"], name="P2")
    created = client.post(f"/api/projects/{p1['_id']}/webhooks", headers=auth_headers,
                         json={"name": "hook", "url": "https://e.com"}).json()
    # Webhook belongs to p1, not p2 -> 404.
    resp = client.put(f"/api/projects/{p2['_id']}/webhooks/{created['_id']}",
                     headers=auth_headers, json={"url": "https://x.com"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Webhook not found"


def test_delete_webhook_happy(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    created = client.post(f"/api/projects/{project['_id']}/webhooks",
                         headers=auth_headers,
                         json={"name": "hook", "url": "https://e.com"}).json()
    resp = client.delete(f"/api/projects/{project['_id']}/webhooks/{created['_id']}",
                        headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Webhook deleted"


def test_rotate_secret_wrong_project_404(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    p1 = _seed_project_via_api(client, auth_headers, ws["_id"], name="RP1")
    p2 = _seed_project_via_api(client, auth_headers, ws["_id"], name="RP2")
    created = client.post(f"/api/projects/{p1['_id']}/webhooks", headers=auth_headers,
                         json={"name": "hook", "url": "https://e.com"}).json()
    resp = client.post(
        f"/api/projects/{p2['_id']}/webhooks/{created['_id']}/rotate-secret",
        headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Webhook not found"


def test_delete_webhook_wrong_project_404(client, flask_core, auth_headers, test_user):
    ws = _seed_workspace(flask_core, owner_id=test_user["_id"])
    p1 = _seed_project_via_api(client, auth_headers, ws["_id"], name="DP1")
    p2 = _seed_project_via_api(client, auth_headers, ws["_id"], name="DP2")
    created = client.post(f"/api/projects/{p1['_id']}/webhooks", headers=auth_headers,
                         json={"name": "hook", "url": "https://e.com"}).json()
    resp = client.delete(f"/api/projects/{p2['_id']}/webhooks/{created['_id']}",
                        headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Webhook not found"


# ---------------------------------------------------------------------------
# _json_body exception path (malformed body) on a project route.
# ---------------------------------------------------------------------------
def test_create_project_malformed_body_400(client, auth_headers):
    # Sending a non-JSON body trips _json_body's except -> {} -> "workspace_id
    # is required".
    resp = client.post("/api/projects/create", headers=auth_headers,
                       content=b"not json", )
    assert resp.status_code == 400
    assert resp.json()["error"] == "workspace_id is required"
