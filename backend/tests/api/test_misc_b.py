"""Integration tests for the misc_b routers (helper SSE, usage, health, docs).

Mirrors tests/api/test_auth.py: full path TestClient -> security/CORS
middleware -> flask_ctx app_context -> real model facades on Postgres ->
legacy-shaped JSON. External HTTP (OpenRouter) is monkeypatched — tests never
hit a real upstream.

The wiring step (routers/__init__.py) is serialized AFTER this agent, so these
tests mount the three misc_b routers onto a dedicated FastAPI app + TestClient
built here (reusing conftest's flask_core / user factories / mint_token).
"""
import json

import pytest
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Dedicated app/client mounting the misc_b routers at their Flask prefixes.
# (asgi.app's ALL_ROUTERS won't include misc_b until the later wiring step.)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def misc_app(_pg_engine):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from app.api.errors import install_exception_handlers
    from app.api.routers.health import health_router
    from app.api.routers.helper import helper_router
    from app.api.routers.usage import api_router

    app = FastAPI(default_response_class=JSONResponse)
    install_exception_handlers(app)
    app.include_router(helper_router, prefix="/api/helper")
    app.include_router(api_router, prefix="/api")
    app.include_router(health_router, prefix="/api/v1")
    return app


@pytest.fixture(scope="function")
def mclient(misc_app):
    with TestClient(misc_app) as c:
        yield c


# ===========================================================================
# Route registration smoke.
# ===========================================================================
def test_misc_b_routes_registered(misc_app):
    paths = {getattr(r, "path", None) for r in misc_app.routes}
    assert "/api/helper/stream" in paths
    assert "/api/helper/cancel/{message_id}" in paths
    assert "/api/helper/clear" in paths
    assert "/api/helper/history" in paths
    assert "/api/usage/me" in paths
    assert "/api/admin/usage" in paths
    assert "/api/openapi.yaml" in paths
    assert "/api/openapi.json" in paths
    assert "/api/v1/health/check" in paths
    assert "/api/v1/health/status" in paths


# ===========================================================================
# Health (/api/v1) — no auth, no deps for /check; deep ping for /status.
# ===========================================================================
def test_health_check_always_200_no_deps(mclient):
    resp = mclient.get("/api/v1/health/check")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    # version/commit are env-driven and may be None in tests — keys must exist.
    assert "version" in body
    assert "commit" in body


def test_health_status_200_with_status_field(mclient, monkeypatch):
    """Postgres ok + OpenRouter ok -> status 'ok'. Mock the upstream ping."""
    class _Resp:
        status_code = 200

    monkeypatch.setattr(
        "requests.get", lambda *a, **k: _Resp(), raising=True
    )
    resp = mclient.get("/api/v1/health/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["postgres"]["ok"] is True
    assert body["dependencies"]["openrouter"]["ok"] is True


def test_health_status_degraded_when_openrouter_down(mclient, monkeypatch):
    """OpenRouter ping failure -> still HTTP 200 but status 'degraded'."""
    def _boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("requests.get", _boom, raising=True)
    resp = mclient.get("/api/v1/health/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["postgres"]["ok"] is True
    assert body["dependencies"]["openrouter"]["ok"] is False


# ===========================================================================
# Docs (/api) — FileResponse(openapi.yaml) + converted JSON.
# ===========================================================================
def test_serve_openapi_yaml(mclient):
    resp = mclient.get("/api/openapi.yaml")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/yaml")
    assert resp.content  # non-empty spec


def test_serve_openapi_json(mclient):
    resp = mclient.get("/api/openapi.json")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert isinstance(body, dict)
    assert "openapi" in body or "swagger" in body


# ===========================================================================
# Usage (/api/usage/me) — masking for non-owners, admin bypass.
# ===========================================================================
def test_usage_me_requires_auth(mclient):
    resp = mclient.get("/api/usage/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_usage_me_non_owner_masks_total_cost(mclient, plain_headers, plain_user):
    """A plain user with no owned workspaces -> total_cost masked to None."""
    resp = mclient.get("/api/usage/me", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "data" in body
    assert "total_tokens" in body
    # No usage rows + no owned workspace -> no visible cost.
    assert body["total_cost"] is None


def test_usage_me_super_admin_sees_cost(mclient, admin_headers):
    """Super-admin (role=admin) bypasses masking -> total_cost is a number."""
    resp = mclient.get("/api/usage/me", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "data" in body
    assert body["total_cost"] == 0  # no rows seeded -> 0, not None (admin bypass)
    assert body["total_tokens"] == 0


def test_admin_usage_requires_admin_role(mclient, plain_headers):
    resp = mclient.get("/api/admin/usage", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Admin access required"


def test_admin_usage_no_token_401(mclient):
    resp = mclient.get("/api/admin/usage")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_admin_usage_happy(mclient, admin_headers):
    resp = mclient.get("/api/admin/usage", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "data" in body
    assert body["total_cost"] == 0
    assert body["total_tokens"] == 0


# ===========================================================================
# Helper — non-SSE endpoints.
# ===========================================================================
def test_helper_history_empty_for_new_user(mclient, plain_headers):
    resp = mclient.get("/api/helper/history", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"messages": []}


def test_helper_history_requires_auth(mclient):
    resp = mclient.get("/api/helper/history")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_helper_clear_ok(mclient, plain_headers):
    resp = mclient.post("/api/helper/clear", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}


def test_helper_stream_empty_message_400(mclient, plain_headers):
    resp = mclient.post("/api/helper/stream", headers=plain_headers, json={"message": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Message content is required"


def test_helper_stream_no_body_400(mclient, plain_headers):
    resp = mclient.post("/api/helper/stream", headers=plain_headers)
    assert resp.status_code == 400


def test_helper_stream_requires_auth(mclient):
    resp = mclient.post("/api/helper/stream", json={"message": "hi"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_helper_cancel_not_found_404(mclient, plain_headers):
    resp = mclient.post("/api/helper/cancel/helper_msg:does-not-exist", headers=plain_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Generation not found"


def test_helper_cancel_wrong_owner_403(mclient, plain_headers, plain_user, flask_core):
    """A stream registered by another user -> 403 Not authorized."""
    from app.models.user import UserModel
    from app.services import stream_state

    # stream_generation_state.user_id is a FK -> users.id, so the owner MUST be a
    # real user (a synthetic UUID silently fails the insert and owner_of() -> None,
    # which would mis-report 404 instead of the 403 this test asserts).
    msg_id = "helper_msg:owned-by-other"
    with flask_core.app_context():
        other = UserModel.create(
            email="other-owner@gmail.com", password="TestPassword123!",
            display_name="Other Owner", role="user",
        )
        other_id = str(other["_id"])
        stream_state.register(msg_id, user_id=other_id)
    try:
        resp = mclient.post(f"/api/helper/cancel/{msg_id}", headers=plain_headers)
        assert resp.status_code == 403
        assert resp.json()["error"] == "Not authorized"
    finally:
        with flask_core.app_context():
            stream_state.clear(msg_id)


# ===========================================================================
# Helper SSE stream — mock OpenRouter, assert event frames.
# ===========================================================================
def test_helper_stream_sse_happy(mclient, plain_headers, plain_user, monkeypatch):
    """Mock OpenRouter chat_completion -> assert SSE headers + frame sequence.

    No workspace is seeded so the DLP gate short-circuits (gate returns None
    when workspace_id is falsy) — no external classifier call.
    """
    def _fake_stream(*args, **kwargs):
        # Mirror the OpenRouter streaming chunk shape the route consumes.
        yield {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]}
        yield {"choices": [{"delta": {"content": " world"}, "finish_reason": "stop"}]}
        yield {"done": True}

    monkeypatch.setattr(
        "app.services.openrouter_service.OpenRouterService.chat_completion",
        staticmethod(_fake_stream),
        raising=True,
    )

    with mclient.stream(
        "POST", "/api/helper/stream", headers=plain_headers,
        json={"message": "How do I create a chat?"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers.get("x-accel-buffering") == "no"

        raw = "".join(resp.iter_text())

    # Parse the SSE frames.
    events = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        etype = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                etype = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        events.append((etype, data))

    types = [e[0] for e in events]
    assert types[0] == "message_start"
    assert "message_chunk" in types
    assert types[-1] == "message_complete"

    complete = next(d for t, d in events if t == "message_complete")
    assert complete["content"] == "Hello world"
    assert complete["finish_reason"] == "stop"

    # The user turn + assistant turn were persisted -> history now non-empty.
    hist = mclient.get("/api/helper/history", headers=plain_headers)
    assert hist.status_code == 200
    msgs = hist.json()["messages"]
    roles = [m.get("role") for m in msgs]
    assert "user" in roles
    assert "assistant" in roles


def test_helper_stream_rate_limit_429(mclient, plain_headers, plain_user, monkeypatch):
    """Exhaust the in-process 30/60s window -> 429 with Retry-After."""
    import app.api.routers.helper as misc

    # Reset the shared limiter so prior tests don't bleed in.
    misc._helper_rate.clear()

    def _fake_stream(*args, **kwargs):
        yield {"choices": [{"delta": {"content": "x"}, "finish_reason": "stop"}]}
        yield {"done": True}

    monkeypatch.setattr(
        "app.services.openrouter_service.OpenRouterService.chat_completion",
        staticmethod(_fake_stream),
        raising=True,
    )

    # 30 allowed requests, then the 31st is throttled.
    last = None
    for _ in range(31):
        last = mclient.post(
            "/api/helper/stream", headers=plain_headers, json={"message": "hi"}
        )
        # Drain streaming bodies so the generator runs to completion.
        if last.status_code == 200:
            _ = last.content

    assert last.status_code == 429, last.text
    assert last.json()["error"] == "rate_limited"
    assert "retry_after" in last.json()
    assert last.headers.get("retry-after") is not None

    misc._helper_rate.clear()
