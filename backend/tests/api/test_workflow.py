"""Integration tests for the FastAPI workflow routers (tests/api/test_workflow.py).

Covers both translated blueprints:
  * /api/workflow      (save/list/get/delete/templates/duplicate/execute*/runs)
  * /api/workflow-ai   (generate)

Mirrors tests/api/test_auth.py — uses the shared conftest fixtures (client,
auth_headers, plain_headers, mint_token, user factories, truncate_all) and seeds
entities via the real model facades inside ``with flask_core.app_context():``.

External HTTP (OpenRouter) is mocked via monkeypatch on
``OpenRouterService.chat_completion``; the execute happy-path uses a personal-
scope ``textInput`` workflow which makes ZERO provider calls (DLP short-circuits
on workspace_id=None, textInput just echoes its static text).

NOTE: the router-wiring step (routers/__init__.py) runs AFTER this agent, so the
``_mount_workflow_routers`` autouse fixture mounts the two routers onto the live
FastAPI app idempotently — making these tests self-contained.
"""
import pytest


# ---------------------------------------------------------------------------
# Mount the workflow routers onto the live app (idempotent) — the central
# wiring step has not run yet at this agent's stage.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _mount_workflow_routers(app):
    from app.api.routers.workflow import router, workflow_ai_router

    existing = {getattr(r, "path", None) for r in app.routes}
    if "/api/workflow/list" not in existing:
        app.include_router(router, prefix="/api/workflow")
    if "/api/workflow-ai/generate" not in existing:
        app.include_router(workflow_ai_router, prefix="/api/workflow-ai")
    yield


# ---------------------------------------------------------------------------
# Seeding helpers.
# ---------------------------------------------------------------------------
def _seed_personal_workflow(flask_core, user_id, *, name="My Flow", nodes=None, edges=None):
    from app.models.workflow import WorkflowModel

    with flask_core.app_context():
        wid = WorkflowModel.create(
            user_id=user_id,
            name=name,
            description="d",
            nodes=nodes or [],
            edges=edges or [],
        )
    return wid


def _seed_project(flask_core, owner_id):
    """Create a workspace + an active 'owner' member + a project under it.

    WorkspaceModel.create only sets owner_user_id; check_project_access's
    workspace fallback resolves the role via a workspace_members row, so the
    owner is explicitly added as an active 'owner' member here. That grants
    the owner implicit project-owner access.
    """
    from app.models.project import ProjectModel
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Team WS", owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, role="owner", status="active")
        proj = ProjectModel.create(
            workspace_id=ws["_id"], name="Proj A", created_by=owner_id
        )
    return str(ws["_id"]), str(proj["_id"])


def _seed_project_workflow(flask_core, owner_id, project_id, workspace_id, *, name="Proj Flow"):
    from app.models.workflow import WorkflowModel

    with flask_core.app_context():
        wid = WorkflowModel.create(
            user_id=owner_id,
            name=name,
            description="",
            nodes=[],
            edges=[],
            project_id=project_id,
            workspace_id=workspace_id,
        )
    return wid


# ---------------------------------------------------------------------------
# Route-registration smoke.
# ---------------------------------------------------------------------------
def test_workflow_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/workflow/save" in paths
    assert "/api/workflow/list" in paths
    assert "/api/workflow/templates" in paths
    assert "/api/workflow/execute" in paths
    assert "/api/workflow/execute-from" in paths
    assert "/api/workflow/execute-node" in paths
    assert "/api/workflow/runs/{workflow_id}" in paths
    assert "/api/workflow/{workflow_id}" in paths
    assert "/api/workflow/{workflow_id}/duplicate" in paths
    assert "/api/workflow-ai/generate" in paths


# ---------------------------------------------------------------------------
# Auth gating (no token -> 401 token_missing).
# ---------------------------------------------------------------------------
def test_list_requires_auth(client):
    resp = client.get("/api/workflow/list")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_save_requires_auth(client):
    resp = client.post("/api/workflow/save", json={"name": "x"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_execute_requires_auth(client):
    resp = client.post("/api/workflow/execute", json={"workflow_id": "x"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_generate_requires_auth(client):
    resp = client.post("/api/workflow-ai/generate", json={"description": "x"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# /save — create + update + concurrency + reassignment.
# ---------------------------------------------------------------------------
def test_save_create_personal_workflow(client, auth_headers):
    resp = client.post("/api/workflow/save", headers=auth_headers, json={
        "name": "Pipeline 1",
        "nodes": [{"id": "n1", "type": "textInput", "position": {"x": 0, "y": 0},
                   "data": {"text": "hello"}}],
        "edges": [],
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["message"] == "Workflow created successfully"
    wf = body["workflow"]
    assert wf["_id"]  # legacy _id alias from to_dict()
    assert wf["name"] == "Pipeline 1"


def test_save_missing_name_400(client, auth_headers):
    resp = client.post("/api/workflow/save", headers=auth_headers, json={"nodes": []})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Workflow name is required"


def test_save_update_existing(client, auth_headers, test_user, flask_core):
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="Orig")
    resp = client.post("/api/workflow/save", headers=auth_headers, json={
        "_id": wid, "name": "Renamed", "nodes": [], "edges": [],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"] == "Workflow updated successfully"
    assert body["workflow"]["name"] == "Renamed"
    assert body["workflow"]["_id"] == wid


def test_save_update_version_conflict_409(client, auth_headers, test_user, flask_core):
    # Seeded workflow starts at version 0; sending If-Match: 5 is stale -> 409.
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="Orig")
    resp = client.post(
        "/api/workflow/save",
        headers={**auth_headers, "If-Match": "5"},
        json={"_id": wid, "name": "Renamed", "nodes": [], "edges": []},
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["code"] == "version_conflict"
    assert body["current_version"] == 0


def test_save_update_invalid_if_match_400(client, auth_headers, test_user, flask_core):
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="Orig")
    resp = client.post(
        "/api/workflow/save",
        headers={**auth_headers, "If-Match": "not-an-int"},
        json={"_id": wid, "name": "Renamed", "nodes": [], "edges": []},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_if_match"


def test_save_reassign_project_rejected_400(client, auth_headers, test_user, flask_core):
    # Personal workflow (project_id None); incoming project_id flips it -> 400.
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="Orig")
    _, proj_id = _seed_project(flask_core, test_user["_id"])
    resp = client.post("/api/workflow/save", headers=auth_headers, json={
        "_id": wid, "name": "Orig", "nodes": [], "edges": [], "project_id": proj_id,
    })
    assert resp.status_code == 400
    assert resp.json()["code"] == "cannot_reassign_project"


def test_save_create_project_workflow_access_denied_403(client, plain_headers, plain_user,
                                                        test_user, flask_core):
    # plain_user is NOT a member of test_user's workspace/project -> 403.
    _, proj_id = _seed_project(flask_core, test_user["_id"])
    resp = client.post("/api/workflow/save", headers=plain_headers, json={
        "name": "X", "nodes": [], "edges": [], "project_id": proj_id,
    })
    assert resp.status_code == 403
    assert resp.json()["code"] == "project_access_denied"


def test_save_create_invalid_project_400(client, auth_headers):
    resp = client.post("/api/workflow/save", headers=auth_headers, json={
        "name": "X", "nodes": [], "edges": [], "project_id": "not-a-uuid",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid project_id"


# ---------------------------------------------------------------------------
# /list.
# ---------------------------------------------------------------------------
def test_list_personal_workflows(client, auth_headers, test_user, flask_core):
    _seed_personal_workflow(flask_core, test_user["_id"], name="A")
    _seed_personal_workflow(flask_core, test_user["_id"], name="B")
    resp = client.get("/api/workflow/list", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    names = {w["name"] for w in body["workflows"]}
    assert names == {"A", "B"}
    assert all(w["_id"] for w in body["workflows"])


def test_list_invalid_project_400(client, auth_headers):
    resp = client.get("/api/workflow/list?project_id=not-a-uuid", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid project_id"


def test_list_project_scoped_access_denied_403(client, plain_headers, test_user, flask_core):
    _, proj_id = _seed_project(flask_core, test_user["_id"])
    resp = client.get(f"/api/workflow/list?project_id={proj_id}", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["code"] == "project_access_denied"


# ---------------------------------------------------------------------------
# /templates.
# ---------------------------------------------------------------------------
def test_templates_empty_ok(client, auth_headers):
    resp = client.get("/api/workflow/templates", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"templates": []}


# ---------------------------------------------------------------------------
# GET /{workflow_id}.
# ---------------------------------------------------------------------------
def test_get_workflow_ok(client, auth_headers, test_user, flask_core):
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="Solo")
    resp = client.get(f"/api/workflow/{wid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    wf = resp.json()["workflow"]
    assert wf["_id"] == wid
    assert wf["name"] == "Solo"


def test_get_workflow_invalid_id_400(client, auth_headers):
    resp = client.get("/api/workflow/not-a-uuid", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workflow ID"


def test_get_workflow_not_found_404(client, auth_headers):
    import uuid
    resp = client.get(f"/api/workflow/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Workflow not found"


def test_get_workflow_other_user_404(client, plain_headers, test_user, flask_core):
    # plain_user cannot read test_user's personal workflow.
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="Private")
    resp = client.get(f"/api/workflow/{wid}", headers=plain_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /{workflow_id}.
# ---------------------------------------------------------------------------
def test_delete_personal_workflow_ok(client, auth_headers, test_user, flask_core):
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="ToDelete")
    resp = client.delete(f"/api/workflow/{wid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Workflow deleted successfully"
    # Gone now.
    assert client.get(f"/api/workflow/{wid}", headers=auth_headers).status_code == 404


def test_delete_invalid_id_400(client, auth_headers):
    resp = client.delete("/api/workflow/not-a-uuid", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workflow ID"


def test_delete_not_found_404(client, auth_headers):
    import uuid
    resp = client.delete(f"/api/workflow/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Workflow not found or unauthorized"


def test_delete_project_workflow_requires_owner_403(client, plain_headers, plain_user,
                                                    test_user, flask_core):
    # plain_user has no project access -> 403 (project-scoped delete gate).
    ws_id, proj_id = _seed_project(flask_core, test_user["_id"])
    wid = _seed_project_workflow(flask_core, test_user["_id"], proj_id, ws_id)
    resp = client.delete(f"/api/workflow/{wid}", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["code"] == "project_access_denied"


def test_delete_project_workflow_owner_ok(client, auth_headers, test_user, flask_core):
    # test_user owns the workspace -> implicit project owner -> delete allowed.
    ws_id, proj_id = _seed_project(flask_core, test_user["_id"])
    wid = _seed_project_workflow(flask_core, test_user["_id"], proj_id, ws_id)
    resp = client.delete(f"/api/workflow/{wid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Workflow deleted successfully"


# ---------------------------------------------------------------------------
# POST /{workflow_id}/duplicate.
# ---------------------------------------------------------------------------
def test_duplicate_workflow_ok(client, auth_headers, test_user, flask_core):
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="Original")
    resp = client.post(f"/api/workflow/{wid}/duplicate", headers=auth_headers,
                       json={"name": "Copy X"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["message"] == "Workflow duplicated successfully"
    assert body["workflow"]["_id"] != wid
    assert body["workflow"]["name"] == "Copy X"


def test_duplicate_invalid_id_400(client, auth_headers):
    resp = client.post("/api/workflow/not-a-uuid/duplicate", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workflow ID"


def test_duplicate_not_found_404(client, auth_headers):
    import uuid
    resp = client.post(f"/api/workflow/{uuid.uuid4()}/duplicate", headers=auth_headers, json={})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Workflow not found"


# ---------------------------------------------------------------------------
# /execute, /execute-from, /execute-node — personal textInput workflow makes
# zero external calls (DLP short-circuits, textInput echoes static text).
# ---------------------------------------------------------------------------
_TEXT_NODE = {"id": "t1", "type": "textInput", "position": {"x": 0, "y": 0},
              "data": {"text": "static output"}}


def test_execute_missing_workflow_id_400(client, auth_headers):
    resp = client.post("/api/workflow/execute", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "workflow_id is required"


def test_execute_invalid_workflow_id_400(client, auth_headers):
    resp = client.post("/api/workflow/execute", headers=auth_headers,
                       json={"workflow_id": "not-a-uuid"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workflow ID"


def test_execute_not_found_404(client, auth_headers):
    import uuid
    resp = client.post("/api/workflow/execute", headers=auth_headers,
                       json={"workflow_id": str(uuid.uuid4())})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Workflow not found"


def test_execute_happy_path_text_node(client, auth_headers, test_user, flask_core):
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="EchoFlow",
                                  nodes=[_TEXT_NODE], edges=[])
    resp = client.post("/api/workflow/execute", headers=auth_headers,
                       json={"workflow_id": wid})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"] == "Workflow executed successfully"
    assert body["run_id"]
    assert body["status"] in ("completed", "failed")
    assert "node_results" in body


def test_execute_project_access_denied_403(client, plain_headers, test_user, flask_core):
    ws_id, proj_id = _seed_project(flask_core, test_user["_id"])
    wid = _seed_project_workflow(flask_core, test_user["_id"], proj_id, ws_id)
    resp = client.post("/api/workflow/execute", headers=plain_headers,
                       json={"workflow_id": wid})
    assert resp.status_code == 403
    assert resp.json()["code"] == "project_access_denied"


def test_execute_from_missing_node_id_400(client, auth_headers, test_user, flask_core):
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="F",
                                  nodes=[_TEXT_NODE])
    resp = client.post("/api/workflow/execute-from", headers=auth_headers,
                       json={"workflow_id": wid})
    assert resp.status_code == 400
    assert resp.json()["error"] == "node_id is required"


def test_execute_node_missing_node_id_400(client, auth_headers, test_user, flask_core):
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="F",
                                  nodes=[_TEXT_NODE])
    resp = client.post("/api/workflow/execute-node", headers=auth_headers,
                       json={"workflow_id": wid})
    assert resp.status_code == 400
    assert resp.json()["error"] == "node_id is required"


def test_execute_node_happy_path(client, auth_headers, test_user, flask_core):
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="EchoFlow",
                                  nodes=[_TEXT_NODE], edges=[])
    resp = client.post("/api/workflow/execute-node", headers=auth_headers,
                       json={"workflow_id": wid, "node_id": "t1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["node_id"] == "t1"
    assert body["status"] == "completed"
    assert body["text"] == "static output"


# ---------------------------------------------------------------------------
# /runs/{workflow_id}.
# ---------------------------------------------------------------------------
def test_runs_invalid_id_400(client, auth_headers):
    resp = client.get("/api/workflow/runs/not-a-uuid", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workflow ID"


def test_runs_empty_ok(client, auth_headers, test_user, flask_core):
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="NoRuns")
    resp = client.get(f"/api/workflow/runs/{wid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"runs": []}


def test_runs_not_found_400(client, auth_headers):
    # WorkflowService.get_workflow_runs raises ValueError("Workflow not found")
    # -> route maps ValueError to 400.
    import uuid
    resp = client.get(f"/api/workflow/runs/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Workflow not found"


def test_runs_after_execute(client, auth_headers, test_user, flask_core):
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="EchoFlow",
                                  nodes=[_TEXT_NODE], edges=[])
    client.post("/api/workflow/execute", headers=auth_headers, json={"workflow_id": wid})
    resp = client.get(f"/api/workflow/runs/{wid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    runs = resp.json()["runs"]
    assert len(runs) >= 1
    assert all(r["_id"] for r in runs)


def test_runs_other_user_unauthorized_400(client, plain_headers, test_user, flask_core):
    # Personal workflow owned by test_user -> get_workflow_runs raises
    # ValueError("Unauthorized access to workflow") -> 400.
    wid = _seed_personal_workflow(flask_core, test_user["_id"], name="Private")
    resp = client.get(f"/api/workflow/runs/{wid}", headers=plain_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Unauthorized access to workflow"


# ---------------------------------------------------------------------------
# /api/workflow-ai/generate — OpenRouter mocked.
# ---------------------------------------------------------------------------
def _ok_llm_response():
    import json
    workflow_json = {
        "name": "Generated",
        "description": "x",
        "nodes": [
            {"id": "node-1", "type": "imageUpload",
             "position": {"x": 100, "y": 300}, "data": {"label": "Input"}},
            {"id": "node-2", "type": "imageGen",
             "position": {"x": 450, "y": 300}, "data": {"prompt": "a cat"}},
        ],
        "edges": [
            {"id": "e1-2", "source": "node-1", "target": "node-2",
             "sourceHandle": "output", "targetHandle": "input-0"},
        ],
    }
    return {"choices": [{"message": {"content": json.dumps(workflow_json)}}]}


def test_generate_description_required_400(client, auth_headers):
    resp = client.post("/api/workflow-ai/generate", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Description is required"


def test_generate_description_too_long_400(client, auth_headers):
    resp = client.post("/api/workflow-ai/generate", headers=auth_headers,
                       json={"description": "x" * 2001})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Description too long (max 2000 characters)"


def test_generate_happy_path(client, auth_headers, monkeypatch):
    from app.services.openrouter_service import OpenRouterService

    monkeypatch.setattr(
        OpenRouterService, "chat_completion",
        staticmethod(lambda *a, **k: _ok_llm_response()),
    )
    resp = client.post("/api/workflow-ai/generate", headers=auth_headers,
                       json={"description": "make a cat image pipeline"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    wf = body["workflow"]
    assert wf["name"] == "Generated"
    # imageGen node defaults filled in by the route (model + negativePrompt).
    gen_node = next(n for n in wf["nodes"] if n["type"] == "imageGen")
    assert "model" in gen_node["data"]
    assert gen_node["data"]["negativePrompt"] == "blurry, low quality, distorted"


def test_generate_llm_error_500(client, auth_headers, monkeypatch):
    from app.services.openrouter_service import OpenRouterService

    monkeypatch.setattr(
        OpenRouterService, "chat_completion",
        staticmethod(lambda *a, **k: {"error": {"message": "upstream down"}}),
    )
    resp = client.post("/api/workflow-ai/generate", headers=auth_headers,
                       json={"description": "build me a flow"})
    assert resp.status_code == 500
    assert resp.json()["error"] == "upstream down"


def test_generate_unparseable_json_500(client, auth_headers, monkeypatch):
    from app.services.openrouter_service import OpenRouterService

    monkeypatch.setattr(
        OpenRouterService, "chat_completion",
        staticmethod(lambda *a, **k: {"choices": [{"message": {"content": "not json {{{"}}]}),
    )
    resp = client.post("/api/workflow-ai/generate", headers=auth_headers,
                       json={"description": "build me a flow"})
    assert resp.status_code == 500
    assert resp.json()["error"] == "Failed to parse workflow JSON from LLM response"
