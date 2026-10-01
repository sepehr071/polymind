"""Integration tests for the spend-gate (HTTP 402) wiring at the automate and
workflow chokepoints.

The spend gate is spliced in IMMEDIATELY after the existing DLP gate at each
chokepoint, BEFORE any StreamingResponse / sse_stream_sync is constructed — so a
budget breach is a clean HTTP 402, never an in-stream SSE error.

  * automate  POST /api/automate-agent/tasks/run  — async handler, gate offloaded
    via anyio.to_thread.run_sync, runs after the DLP block + before sse_stream_sync.
  * workflow  POST /api/workflow/execute          — service-layer gate inside
    WorkflowService.execute_workflow, right before _dlp_scan_nodes; the router
    maps BudgetExceededError -> 402.
  * workflow  POST /api/workflow/execute-node      — same gate inside
    WorkflowService.execute_single_node.

Cheap block: BudgetAllocationModel.set_budget('user', uid, 0) — a zero budget
blocks immediately (spent 0 >= limit 0). The DLP gate is neutralized everywhere
so the always-run LLM classifier never fires.

truncate_all wipes platform_settings after EVERY test, so an autouse fixture
re-flips billing_enforcement ON per-test; the flag-off tests prove the route
proceeds PAST the gate (only asserting NOT-402 — a personal textInput workflow /
mocked browser-use run then succeeds for unrelated reasons).
"""
import json

import pytest


# ---------------------------------------------------------------------------
# Enforcement flag — ON by default (truncate_all wiped platform_settings).
# Depends on the conftest ``flask_core`` fixture so the session engine is bound
# (it pulls in ``_pg_engine``) before any DB write fires.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _enable_enforcement(flask_core):
    from app.models.platform_settings import PlatformSettingsModel

    with flask_core.app_context():
        PlatformSettingsModel.set_feature("billing_enforcement", True, None)
    yield


def _disable_enforcement(flask_core):
    from app.models.platform_settings import PlatformSettingsModel

    with flask_core.app_context():
        PlatformSettingsModel.set_feature("billing_enforcement", False, None)


def _zero_user_budget(flask_core, user_id):
    """A zero user-budget blocks immediately (spent 0 >= limit 0)."""
    from app.models.budget_allocation import BudgetAllocationModel

    with flask_core.app_context():
        BudgetAllocationModel.set_budget("user", str(user_id), 0, by=None)


# ---------------------------------------------------------------------------
# Neutralize the DLP gate so the always-run LLM classifier never fires.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_dlp(monkeypatch):
    import app.api.routers.automate_agent as automate_mod
    import app.services.workflow_service as wf_mod

    monkeypatch.setattr(automate_mod, "dlp_gate", lambda **kwargs: None)
    # WorkflowService._dlp_scan_nodes calls the imported dlp_gate; stub the
    # whole scan method so no classifier fires (the spend gate runs BEFORE it).
    monkeypatch.setattr(
        wf_mod.WorkflowService, "_dlp_scan_nodes",
        classmethod(lambda cls, **kwargs: None),
    )
    yield


# ---------------------------------------------------------------------------
# Mount the workflow routers onto the live app (idempotent).
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
# Seeding helpers (mirror tests/api/test_workflow.py).
# ---------------------------------------------------------------------------
_TEXT_NODE = {
    "id": "t1",
    "type": "textInput",
    "position": {"x": 0, "y": 0},
    "data": {"text": "static output"},
}


def _seed_personal_workflow(flask_core, user_id, *, name="My Flow", nodes=None, edges=None):
    from app.models.workflow import WorkflowModel

    with flask_core.app_context():
        return WorkflowModel.create(
            user_id=user_id,
            name=name,
            description="d",
            nodes=nodes or [],
            edges=edges or [],
        )


# ---------------------------------------------------------------------------
# automate  POST /api/automate-agent/tasks/run — 402 BEFORE any SSE frame.
# ---------------------------------------------------------------------------
def test_automate_run_budget_exceeded_402(client, auth_headers, test_user, flask_core):
    # The spend gate raises BEFORE sse_stream_sync is constructed, so the 402 is
    # a plain JSONResponse (no SSE body) — a regular POST captures it fully.
    _zero_user_budget(flask_core, test_user["_id"])

    resp = client.post(
        "/api/automate-agent/tasks/run",
        headers=auth_headers,
        json={"task": "summarize https://example.com"},
    )
    assert resp.status_code == 402, resp.text
    # Plain JSON error body — no text/event-stream frames leaked.
    assert "event:" not in resp.text
    body = resp.json()
    assert body["code"] == "budget_exceeded"
    assert body["scope"] == "user"
    assert body["limit"] == 0


def test_automate_run_flag_off_not_402(client, auth_headers, test_user, flask_core, monkeypatch):
    # Even with a zero budget, enforcement OFF means the gate short-circuits —
    # the run proceeds past the gate (mocked browser-use Cloud lets it complete).
    _zero_user_budget(flask_core, test_user["_id"])
    _disable_enforcement(flask_core)

    from app.services.browser_use_service import BrowserUseService

    monkeypatch.setattr(
        BrowserUseService, "create_session",
        staticmethod(lambda task, model="claude-sonnet-4.6": {
            "id": "sess-1", "status": "completed",
            "live_url": "https://live.example/sess-1",
        }),
    )
    monkeypatch.setattr(
        BrowserUseService, "list_messages",
        staticmethod(lambda session_id, after=None, limit=100: {"messages": []}),
    )
    monkeypatch.setattr(
        BrowserUseService, "get_session",
        staticmethod(lambda session_id: {
            "id": session_id, "status": "completed", "output": "done",
            "live_url": "https://live.example/sess-1",
        }),
    )

    with client.stream(
        "POST",
        "/api/automate-agent/tasks/run",
        headers=auth_headers,
        json={"task": "summarize https://example.com"},
    ) as resp:
        assert resp.status_code != 402, resp.read()
        assert resp.status_code == 200
        # Drain the stream fully inside the with-block.
        raw = "".join(chunk for chunk in resp.iter_text())

    assert "event: task_started" in raw


# ---------------------------------------------------------------------------
# workflow  POST /api/workflow/execute — service gate -> router 402.
# ---------------------------------------------------------------------------
def test_workflow_execute_budget_exceeded_402(client, auth_headers, test_user, flask_core):
    _zero_user_budget(flask_core, test_user["_id"])
    wid = _seed_personal_workflow(
        flask_core, test_user["_id"], name="EchoFlow", nodes=[_TEXT_NODE], edges=[]
    )

    resp = client.post(
        "/api/workflow/execute", headers=auth_headers, json={"workflow_id": wid}
    )
    assert resp.status_code == 402, resp.text
    body = resp.json()
    assert body["code"] == "budget_exceeded"
    assert body["scope"] == "user"
    assert body["limit"] == 0


def test_workflow_execute_node_budget_exceeded_402(client, auth_headers, test_user, flask_core):
    _zero_user_budget(flask_core, test_user["_id"])
    wid = _seed_personal_workflow(
        flask_core, test_user["_id"], name="EchoFlow", nodes=[_TEXT_NODE], edges=[]
    )

    resp = client.post(
        "/api/workflow/execute-node",
        headers=auth_headers,
        json={"workflow_id": wid, "node_id": "t1"},
    )
    assert resp.status_code == 402, resp.text
    body = resp.json()
    assert body["code"] == "budget_exceeded"
    assert body["scope"] == "user"


def test_workflow_execute_from_budget_exceeded_402(client, auth_headers, test_user, flask_core):
    # execute-from routes through WorkflowService.execute_workflow -> same gate.
    _zero_user_budget(flask_core, test_user["_id"])
    wid = _seed_personal_workflow(
        flask_core, test_user["_id"], name="EchoFlow", nodes=[_TEXT_NODE], edges=[]
    )

    resp = client.post(
        "/api/workflow/execute-from",
        headers=auth_headers,
        json={"workflow_id": wid, "node_id": "t1"},
    )
    assert resp.status_code == 402, resp.text
    assert resp.json()["code"] == "budget_exceeded"


def test_workflow_execute_flag_off_not_402(client, auth_headers, test_user, flask_core):
    # Zero budget but enforcement OFF -> gate short-circuits; the personal
    # textInput workflow then executes (zero provider calls) and returns 200.
    _zero_user_budget(flask_core, test_user["_id"])
    _disable_enforcement(flask_core)
    wid = _seed_personal_workflow(
        flask_core, test_user["_id"], name="EchoFlow", nodes=[_TEXT_NODE], edges=[]
    )

    resp = client.post(
        "/api/workflow/execute", headers=auth_headers, json={"workflow_id": wid}
    )
    assert resp.status_code != 402, resp.text
    assert resp.status_code == 200
    assert resp.json()["message"] == "Workflow executed successfully"
