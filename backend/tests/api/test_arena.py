"""Integration tests for the translated arena router (app.api.routers.arena).

Mirrors tests/api/test_auth.py: real model facades on Postgres via the
flask_ctx bridge, legacy-shaped JSON, conftest fixtures. OpenRouter is
monkeypatched so the SSE fan-out never hits a real upstream.

Quirk under test (ported VERBATIM from the Flask routes): config_id /
project_id / session_id are validated with ``bson.ObjectId.is_valid`` — i.e.
the 24-hex-char shape. On the UUID datastore only ``quick:*`` config ids
resolve end-to-end, and a real UUID session id fails the PATCH guard with 400.
"""
import json

import pytest

# Two real quick-model ids from app/utils/quick_models.py (always visible).
QUICK_A = "quick:google/gemini-3.5-flash-lite"
QUICK_B = "quick:x-ai/grok-4.5"


def _create_session(client, headers, config_ids=None, title="Arena Session"):
    body = {"config_ids": config_ids or [QUICK_A, QUICK_B], "title": title}
    return client.post("/api/arena/sessions", headers=headers, json=body)


# ---------------------------------------------------------------------------
# POST /sessions — create.
# ---------------------------------------------------------------------------
def test_create_session_happy_path(client, auth_headers):
    resp = _create_session(client, auth_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    session = body["session"]
    # Legacy _id alias must be present + a serialized UUID string.
    assert session["_id"]
    assert session["title"] == "Arena Session"
    assert session["config_ids"] == [QUICK_A, QUICK_B]


def test_create_session_too_few_configs_400(client, auth_headers):
    resp = client.post("/api/arena/sessions", headers=auth_headers, json={"config_ids": [QUICK_A]})
    assert resp.status_code == 400
    assert resp.json()["error"] == "At least 2 configs required"


def test_create_session_too_many_configs_400(client, auth_headers):
    cfgs = [QUICK_A, QUICK_B, QUICK_A, QUICK_B, QUICK_A]
    resp = client.post("/api/arena/sessions", headers=auth_headers, json={"config_ids": cfgs})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Maximum 4 configs allowed"


def test_create_session_invalid_config_id_400(client, auth_headers):
    # A non-quick id that is not a 24-hex ObjectId -> "Invalid config id".
    resp = client.post(
        "/api/arena/sessions", headers=auth_headers,
        json={"config_ids": [QUICK_A, "not-a-valid-id"]},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid config id: not-a-valid-id"


def test_create_session_config_not_found_404(client, auth_headers):
    # Valid 24-hex ObjectId shape but no matching LLMConfig row -> 404.
    fake_oid = "a" * 24
    resp = client.post(
        "/api/arena/sessions", headers=auth_headers,
        json={"config_ids": [QUICK_A, fake_oid]},
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == f"Config {fake_oid} not found"


def test_create_session_invalid_project_id_400(client, auth_headers):
    resp = client.post(
        "/api/arena/sessions", headers=auth_headers,
        json={"config_ids": [QUICK_A, QUICK_B], "project_id": "bad-project"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "project_id must be a valid 24-char hex ObjectId"


def test_create_session_no_token_401(client):
    resp = client.post("/api/arena/sessions", json={"config_ids": [QUICK_A, QUICK_B]})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# GET /sessions — list.
# ---------------------------------------------------------------------------
def test_list_sessions_happy_path(client, auth_headers):
    _create_session(client, auth_headers, title="One")
    _create_session(client, auth_headers, title="Two")

    resp = client.get("/api/arena/sessions", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["limit"] == 20
    assert len(body["sessions"]) == 2
    for s in body["sessions"]:
        assert s["_id"]


def test_list_sessions_pagination_clamps_limit(client, auth_headers):
    resp = client.get("/api/arena/sessions?page=1&limit=999", headers=auth_headers)
    assert resp.status_code == 200
    # limit clamps to 50.
    assert resp.json()["limit"] == 50


def test_list_sessions_no_token_401(client):
    resp = client.get("/api/arena/sessions")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_list_sessions_scoped_to_user(client, auth_headers, plain_headers):
    _create_session(client, auth_headers, title="Owner session")
    # A different user sees none of the first user's sessions.
    resp = client.get("/api/arena/sessions", headers=plain_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ---------------------------------------------------------------------------
# GET /sessions/{id} — detail.
# ---------------------------------------------------------------------------
def test_get_session_happy_path(client, auth_headers):
    sid = _create_session(client, auth_headers).json()["session"]["_id"]
    resp = client.get(f"/api/arena/sessions/{sid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session"]["_id"] == sid
    assert body["messages"] == []
    ids = [c["_id"] for c in body["configs"]]
    assert QUICK_A in ids
    assert QUICK_B in ids


def test_get_session_not_found_404(client, auth_headers):
    import uuid
    resp = client.get(f"/api/arena/sessions/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Session not found"


def test_get_session_unauthorized_403(client, auth_headers, plain_headers):
    sid = _create_session(client, auth_headers).json()["session"]["_id"]
    resp = client.get(f"/api/arena/sessions/{sid}", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Unauthorized"


def test_get_session_no_token_401(client, auth_headers):
    sid = _create_session(client, auth_headers).json()["session"]["_id"]
    resp = client.get(f"/api/arena/sessions/{sid}")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# PATCH /sessions/{id} — update. The session_id guard uses ObjectId.is_valid,
# so a real UUID session id is rejected 400 (verbatim Flask behavior).
# ---------------------------------------------------------------------------
def test_update_session_uuid_id_rejected_400(client, auth_headers):
    sid = _create_session(client, auth_headers).json()["session"]["_id"]
    resp = client.patch(
        f"/api/arena/sessions/{sid}", headers=auth_headers, json={"title": "new"}
    )
    # UUID (36 chars) fails ObjectId.is_valid -> 400 Invalid session id.
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid session id"


def test_update_session_invalid_id_400(client, auth_headers):
    resp = client.patch(
        "/api/arena/sessions/not-an-oid", headers=auth_headers, json={"title": "x"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid session id"


def test_update_session_not_found_404(client, auth_headers):
    # 24-hex ObjectId shape passes the guard but matches no session.
    resp = client.patch(
        f"/api/arena/sessions/{'b' * 24}", headers=auth_headers, json={"title": "x"}
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Session not found"


def test_update_session_no_token_401(client):
    resp = client.patch(f"/api/arena/sessions/{'b' * 24}", json={"title": "x"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# DELETE /sessions/{id}.
# ---------------------------------------------------------------------------
def test_delete_session_happy_path(client, auth_headers):
    sid = _create_session(client, auth_headers).json()["session"]["_id"]
    resp = client.delete(f"/api/arena/sessions/{sid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Session deleted"
    # Now gone.
    assert client.get(f"/api/arena/sessions/{sid}", headers=auth_headers).status_code == 404


def test_delete_session_not_found_404(client, auth_headers):
    import uuid
    resp = client.delete(f"/api/arena/sessions/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Session not found"


def test_delete_session_unauthorized_403(client, auth_headers, plain_headers):
    sid = _create_session(client, auth_headers).json()["session"]["_id"]
    resp = client.delete(f"/api/arena/sessions/{sid}", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Unauthorized"


# ---------------------------------------------------------------------------
# POST /stream — SSE fan-out. OpenRouter monkeypatched.
# ---------------------------------------------------------------------------
def _fake_stream(content):
    """A fake chat_completion stream yielding one content chunk + usage."""
    def _gen(*args, **kwargs):
        yield {
            "choices": [{"delta": {"content": content}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5},
        }
        yield {"done": True}
    return _gen


@pytest.fixture
def patch_openrouter(monkeypatch):
    from app.services.openrouter_service import OpenRouterService

    monkeypatch.setattr(
        OpenRouterService, "chat_completion", staticmethod(_fake_stream("hello")),
    )
    # Keep build_enhanced_system_prompt as the real (pure) implementation — it
    # makes no network call.
    return monkeypatch


@pytest.fixture
def real_config_ids(flask_core, test_user):
    """Two persisted LLMConfig rows owned by the auth user.

    Stream fan-out now uses ``resolve_arena_config`` (UUID persona + ``quick:*``).
    These rows still cover the persona path; ``test_stream_quick_models_emits_events``
    covers the synthetic quick-model path.
    """
    from app.models.llm_config import LLMConfigModel

    with flask_core.app_context():
        a = LLMConfigModel.create(
            name="Config A", model_id="openai/gpt-4o-mini", model_name="GPT-4o mini",
            owner_id=test_user["_id"],
        )
        b = LLMConfigModel.create(
            name="Config B", model_id="anthropic/claude-3.5-haiku", model_name="Claude Haiku",
            owner_id=test_user["_id"],
        )
    return [a["_id"], b["_id"]]


def _read_sse_frames(resp):
    """Collect SSE frames from a streamed TestClient response into a list."""
    text = b"".join(resp.iter_bytes()).decode("utf-8")
    return text


def test_stream_message_required_400(client, auth_headers):
    resp = client.post(
        "/api/arena/stream", headers=auth_headers,
        json={"config_ids": [QUICK_A, QUICK_B], "message": "   "},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Message is required"


def test_stream_too_few_configs_400(client, auth_headers):
    resp = client.post(
        "/api/arena/stream", headers=auth_headers,
        json={"config_ids": [QUICK_A], "message": "hi"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "At least 2 configs required"


def test_stream_no_token_401(client):
    resp = client.post(
        "/api/arena/stream",
        json={"config_ids": [QUICK_A, QUICK_B], "message": "hi"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_stream_happy_path_emits_events(client, auth_headers, patch_openrouter, real_config_ids):
    with client.stream(
        "POST", "/api/arena/stream", headers=auth_headers,
        json={"config_ids": real_config_ids, "message": "hello there"},
    ) as resp:
        assert resp.status_code == 200, resp.read()
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["x-accel-buffering"] == "no"
        text = _read_sse_frames(resp)

    # First a session-created event (no session_id supplied).
    assert "event: arena_session_created" in text
    assert "event: arena_user_message" in text
    # Per-config lifecycle events from the fan-out threads.
    assert "event: arena_message_start" in text
    assert "event: arena_message_chunk" in text
    assert "event: arena_message_complete" in text
    # The monkeypatched content arrived.
    assert "hello" in text


def test_stream_quick_models_emits_events(client, auth_headers, patch_openrouter):
    """`quick:*` ids (what the Arena picker actually sends) must fan out."""
    with client.stream(
        "POST", "/api/arena/stream", headers=auth_headers,
        json={"config_ids": [QUICK_A, QUICK_B], "message": "hello there"},
    ) as resp:
        assert resp.status_code == 200, resp.read()
        text = _read_sse_frames(resp)

    assert "event: arena_session_created" in text
    assert "event: arena_user_message" in text
    assert "event: arena_message_start" in text
    assert "event: arena_message_chunk" in text
    assert "event: arena_message_complete" in text
    assert "hello" in text
    assert "Config not found" not in text


def test_stream_into_existing_session(client, auth_headers, patch_openrouter, real_config_ids):
    # Pre-create a session (quick:* ids pass session-CREATE validation), then
    # stream into it with REAL config ids so the fan-out actually resolves
    # configs and persists assistant messages. The stream reads config_ids from
    # the request body, not from the stored session, so the two need not match.
    sid = _create_session(client, auth_headers).json()["session"]["_id"]
    with client.stream(
        "POST", "/api/arena/stream", headers=auth_headers,
        json={"session_id": sid, "config_ids": real_config_ids, "message": "yo"},
    ) as resp:
        assert resp.status_code == 200
        text = _read_sse_frames(resp)

    # Existing session -> NO session-created event, but messages still flow.
    assert "event: arena_session_created" not in text
    assert "event: arena_user_message" in text
    assert "event: arena_message_complete" in text

    # The session now has persisted messages (user + 2 assistant).
    detail = client.get(f"/api/arena/sessions/{sid}", headers=auth_headers).json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles.count("user") == 1
    assert roles.count("assistant") == 2


def test_stream_foreign_session_emits_error(client, auth_headers, plain_headers, patch_openrouter):
    # Session owned by auth user; plain user streams into it -> "Session not found".
    sid = _create_session(client, auth_headers).json()["session"]["_id"]
    with client.stream(
        "POST", "/api/arena/stream", headers=plain_headers,
        json={"session_id": sid, "config_ids": [QUICK_A, QUICK_B], "message": "x"},
    ) as resp:
        assert resp.status_code == 200
        text = _read_sse_frames(resp)
    assert "event: error" in text
    assert "Session not found" in text


# ---------------------------------------------------------------------------
# POST /cancel/{session_id}.
# ---------------------------------------------------------------------------
def test_cancel_happy_path(client, auth_headers, flask_core):
    sid = _create_session(client, auth_headers).json()["session"]["_id"]
    # Register an active stream so the cancel POST finds it (mark_cancelled
    # returns True only when a stream_state row exists for the session).
    with flask_core.app_context():
        from app.services import stream_state
        stream_state.register(sid)

    resp = client.post(f"/api/arena/cancel/{sid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["message"] == "Arena generation cancelled"


def test_cancel_no_active_generation_404(client, auth_headers):
    # Session exists but no stream_state row registered -> 404.
    sid = _create_session(client, auth_headers).json()["session"]["_id"]
    resp = client.post(f"/api/arena/cancel/{sid}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "No active generation"


def test_cancel_session_not_found_404(client, auth_headers):
    import uuid
    resp = client.post(f"/api/arena/cancel/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Session not found"


def test_cancel_unauthorized_403(client, auth_headers, plain_headers):
    sid = _create_session(client, auth_headers).json()["session"]["_id"]
    resp = client.post(f"/api/arena/cancel/{sid}", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Not authorized"


def test_cancel_no_token_401(client, auth_headers):
    sid = _create_session(client, auth_headers).json()["session"]["_id"]
    resp = client.post(f"/api/arena/cancel/{sid}")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# Route-registration smoke.
# ---------------------------------------------------------------------------
def test_arena_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/arena/sessions" in paths
    assert "/api/arena/sessions/{session_id}" in paths
    assert "/api/arena/stream" in paths
    assert "/api/arena/cancel/{session_id}" in paths
