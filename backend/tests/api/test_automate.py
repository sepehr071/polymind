"""Integration tests for the automate-agent FastAPI router (/api/automate-agent).

Mirrors tests/api/test_auth.py: real model facades on Postgres via the
flask_ctx bridge, legacy-shaped JSON, external HTTP (browser-use Cloud) and the
DLP LLM classifier are mocked — never hit real upstreams.
"""
import json

import pytest

from app.api.core import flask_core


# ---------------------------------------------------------------------------
# Helpers — seed automate tasks directly via the model facade.
# ---------------------------------------------------------------------------
def _make_task(user_id, *, task_text="do a thing", model="claude-sonnet-4.6",
               status=None, session_id=None):
    from app.models.automate_task import AutomateTaskModel

    with flask_core.app_context():
        task_id = AutomateTaskModel.create(str(user_id), task_text, model)
        updates = {}
        if session_id is not None:
            updates["session_id"] = session_id
        if updates:
            AutomateTaskModel.update(task_id, updates)
        if status is not None:
            AutomateTaskModel.set_status(task_id, status)
        return task_id


@pytest.fixture(autouse=True)
def _no_dlp(monkeypatch):
    """Neutralize the DLP gate so the always-run LLM classifier never fires."""
    import app.api.routers.automate_agent as mod

    monkeypatch.setattr(mod, "dlp_gate", lambda **kwargs: None)
    yield


# ---------------------------------------------------------------------------
# GET /tasks — list.
# ---------------------------------------------------------------------------
def test_list_tasks_empty(client, auth_headers):
    resp = client.get("/api/automate-agent/tasks", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"tasks": [], "total": 0}


def test_list_tasks_returns_owned_with_id_alias(client, auth_headers, test_user):
    tid = _make_task(test_user["_id"], task_text="search docs")
    resp = client.get("/api/automate-agent/tasks", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["tasks"]) == 1
    task = body["tasks"][0]
    # Legacy Mongo _id alias is preserved by the model to_dict().
    assert task["_id"] == tid
    assert task["task_text"] == "search docs"
    assert task["status"] == "pending"


def test_list_tasks_no_token_401_token_missing(client):
    resp = client.get("/api/automate-agent/tasks")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_list_tasks_only_own_tasks(client, auth_headers, test_user, plain_user):
    # A task belonging to another user must NOT appear in this user's listing.
    _make_task(plain_user["_id"], task_text="other user task")
    mine = _make_task(test_user["_id"], task_text="my task")

    resp = client.get("/api/automate-agent/tasks", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["tasks"][0]["_id"] == mine


# ---------------------------------------------------------------------------
# GET /tasks/{id} — single task + messages.
# ---------------------------------------------------------------------------
def test_get_task_happy(client, auth_headers, test_user):
    tid = _make_task(test_user["_id"], task_text="single fetch")
    resp = client.get(f"/api/automate-agent/tasks/{tid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["task"]["_id"] == tid
    assert body["task"]["task_text"] == "single fetch"
    assert body["messages"] == []


def test_get_task_not_found_404(client, auth_headers):
    import uuid

    resp = client.get(f"/api/automate-agent/tasks/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Task not found"


def test_get_task_garbage_id_404(client, auth_headers):
    # _to_uuid coerces garbage -> None -> find_by_id returns None.
    resp = client.get("/api/automate-agent/tasks/not-a-uuid", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Task not found"


def test_get_task_not_owner_403(client, auth_headers, test_user, plain_user):
    tid = _make_task(plain_user["_id"], task_text="someone else's")
    resp = client.get(f"/api/automate-agent/tasks/{tid}", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Not authorized"


def test_get_task_no_token_401(client, test_user):
    tid = _make_task(test_user["_id"])
    resp = client.get(f"/api/automate-agent/tasks/{tid}")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# DELETE /tasks/{id}.
# ---------------------------------------------------------------------------
def test_delete_task_happy(client, auth_headers, test_user):
    tid = _make_task(test_user["_id"])
    resp = client.delete(f"/api/automate-agent/tasks/{tid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Task deleted"

    # Gone now.
    after = client.get(f"/api/automate-agent/tasks/{tid}", headers=auth_headers)
    assert after.status_code == 404


def test_delete_task_not_found_404(client, auth_headers):
    import uuid

    resp = client.delete(f"/api/automate-agent/tasks/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Task not found"


def test_delete_task_not_owner_403(client, auth_headers, plain_user):
    tid = _make_task(plain_user["_id"])
    resp = client.delete(f"/api/automate-agent/tasks/{tid}", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Not authorized"


def test_delete_task_calls_stop_when_active_session(client, auth_headers, test_user, monkeypatch):
    # A running task with a session_id must trigger a best-effort hard stop.
    tid = _make_task(test_user["_id"], session_id="sess-123", status="running")

    calls = {}

    def _fake_stop(session_id, strategy="task"):
        calls["session_id"] = session_id
        calls["strategy"] = strategy
        return {"ok": True}

    from app.services.browser_use_service import BrowserUseService

    monkeypatch.setattr(BrowserUseService, "stop_session", staticmethod(_fake_stop))

    resp = client.delete(f"/api/automate-agent/tasks/{tid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert calls == {"session_id": "sess-123", "strategy": "session"}


# ---------------------------------------------------------------------------
# POST /tasks/{id}/stop.
# ---------------------------------------------------------------------------
def test_stop_task_happy(client, auth_headers, test_user, monkeypatch):
    tid = _make_task(test_user["_id"], session_id="sess-xyz", status="running")

    def _fake_stop(session_id, strategy="task"):
        return {"ok": True}

    from app.services.browser_use_service import BrowserUseService

    monkeypatch.setattr(BrowserUseService, "stop_session", staticmethod(_fake_stop))

    resp = client.post(f"/api/automate-agent/tasks/{tid}/stop", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "status": "stopped"}

    # Status persisted as stopped.
    after = client.get(f"/api/automate-agent/tasks/{tid}", headers=auth_headers).json()
    assert after["task"]["status"] == "stopped"


def test_stop_task_not_found_404(client, auth_headers):
    import uuid

    resp = client.post(f"/api/automate-agent/tasks/{uuid.uuid4()}/stop", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Task not found"


def test_stop_task_not_owner_403(client, auth_headers, plain_user):
    tid = _make_task(plain_user["_id"], session_id="s", status="running")
    resp = client.post(f"/api/automate-agent/tasks/{tid}/stop", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Not authorized"


def test_stop_task_terminal_state_400(client, auth_headers, test_user):
    tid = _make_task(test_user["_id"], session_id="s", status="completed")
    resp = client.post(f"/api/automate-agent/tasks/{tid}/stop", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Task already in terminal state"


def test_stop_task_no_session_400(client, auth_headers, test_user):
    tid = _make_task(test_user["_id"], status="running")  # no session_id
    resp = client.post(f"/api/automate-agent/tasks/{tid}/stop", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "No active session for this task"


def test_stop_task_upstream_failure_502(client, auth_headers, test_user, monkeypatch):
    tid = _make_task(test_user["_id"], session_id="s", status="running")

    def _boom(session_id, strategy="task"):
        raise Exception("browser-use unreachable")

    from app.services.browser_use_service import BrowserUseService

    monkeypatch.setattr(BrowserUseService, "stop_session", staticmethod(_boom))

    resp = client.post(f"/api/automate-agent/tasks/{tid}/stop", headers=auth_headers)
    assert resp.status_code == 502
    assert resp.json()["error"] == "browser-use unreachable"


# ---------------------------------------------------------------------------
# POST /tasks/run — pre-stream validation (no SSE body produced on these).
# ---------------------------------------------------------------------------
def test_run_task_missing_task_400(client, auth_headers):
    resp = client.post("/api/automate-agent/tasks/run", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "task is required"


def test_run_task_no_token_401(client):
    resp = client.post("/api/automate-agent/tasks/run", json={"task": "go"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_run_task_ssrf_internal_host_400(client, auth_headers):
    resp = client.post(
        "/api/automate-agent/tasks/run",
        headers=auth_headers,
        json={"task": "open http://localhost:8080/admin and read it"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "task_url_blocked"
    assert "localhost" in body["host"]


def test_run_task_ssrf_dangerous_scheme_400(client, auth_headers):
    resp = client.post(
        "/api/automate-agent/tasks/run",
        headers=auth_headers,
        json={"task": "run file:///etc/passwd now"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "task_url_blocked"
    assert body["host"] == "file:"


def test_run_task_concurrent_limit_429(client, auth_headers, test_user):
    # AUTOMATE_MAX_CONCURRENT defaults to 1 — one running task already exhausts it.
    _make_task(test_user["_id"], status="running")
    resp = client.post(
        "/api/automate-agent/tasks/run",
        headers=auth_headers,
        json={"task": "go visit https://example.com"},
    )
    assert resp.status_code == 429
    assert resp.json()["error"] == "concurrent_limit"


# ---------------------------------------------------------------------------
# POST /tasks/run — full SSE happy path. Mock browser-use Cloud entirely.
# ---------------------------------------------------------------------------
def test_run_task_sse_stream_happy(client, auth_headers, monkeypatch):
    from app.services.browser_use_service import BrowserUseService

    monkeypatch.setattr(
        BrowserUseService, "create_session",
        staticmethod(lambda task, model="claude-sonnet-4.6": {
            "id": "sess-stream-1", "status": "running",
            "live_url": "https://live.example/sess-stream-1",
        }),
    )
    # First message batch then empty; session completes on first status poll.
    msg_batches = [
        {"messages": [{"id": "c1", "role": "assistant", "type": "thought",
                       "summary": "thinking", "screenshot_url": None}]},
    ]

    def _fake_list_messages(session_id, after=None, limit=100):
        return msg_batches.pop(0) if msg_batches else {"messages": []}

    monkeypatch.setattr(
        BrowserUseService, "list_messages", staticmethod(_fake_list_messages)
    )
    monkeypatch.setattr(
        BrowserUseService, "get_session",
        staticmethod(lambda session_id: {
            "id": session_id, "status": "completed", "output": "all done",
            "live_url": "https://live.example/sess-stream-1",
        }),
    )

    with client.stream(
        "POST", "/api/automate-agent/tasks/run",
        headers=auth_headers,
        json={"task": "summarize https://example.com"},
    ) as resp:
        assert resp.status_code == 200, resp.read()
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers.get("x-accel-buffering") == "no"

        raw = "".join(chunk for chunk in resp.iter_text())

    # First frame is the task_started named event.
    assert raw.startswith("event: task_started")
    # The named events all arrived, in order.
    assert "event: task_started" in raw
    assert "event: message" in raw
    assert "event: status_change" in raw
    assert "event: task_complete" in raw

    # The completion frame carries the upstream output.
    complete_chunk = raw.split("event: task_complete", 1)[1]
    data_line = next(
        ln for ln in complete_chunk.splitlines() if ln.startswith("data:")
    )
    payload = json.loads(data_line[len("data:"):].strip())
    assert payload["output"] == "all done"


def test_run_task_sse_session_create_failure_error_event(client, auth_headers, monkeypatch):
    from app.services.browser_use_service import BrowserUseService

    def _boom(task, model="claude-sonnet-4.6"):
        raise Exception("cloud down")

    monkeypatch.setattr(BrowserUseService, "create_session", staticmethod(_boom))

    with client.stream(
        "POST", "/api/automate-agent/tasks/run",
        headers=auth_headers,
        json={"task": "summarize https://example.com"},
    ) as resp:
        assert resp.status_code == 200, resp.read()
        assert resp.headers["content-type"].startswith("text/event-stream")
        raw = "".join(chunk for chunk in resp.iter_text())

    assert "event: error" in raw
    assert "session_create_failed" in raw


# ---------------------------------------------------------------------------
# Route-registration smoke.
# ---------------------------------------------------------------------------
def test_automate_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/automate-agent/tasks" in paths
    assert "/api/automate-agent/tasks/{task_id}" in paths
    assert "/api/automate-agent/tasks/{task_id}/stop" in paths
    assert "/api/automate-agent/tasks/run" in paths
