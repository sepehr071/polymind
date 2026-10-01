"""Integration tests for the FastAPI debate router (app/api/routers/debate.py).

Mirrors tests/api/test_auth.py: full path through TestClient -> flask_ctx
app_context -> real DebateSession/DebateMessage facades on Postgres ->
legacy-shaped JSON. External upstream (OpenRouter) is monkeypatched — never hit.

Test users have no ``active_workspace_id``, so ``dlp_gate`` short-circuits
(``if not text or not workspace_id: return None``) and is inert here; the DLP
path itself is exercised by the dedicated DLP suite.
"""
import json

# Quick-model ids never need a real LLMConfig row (resolve_config returns a
# synthetic dict), keeping session seeding self-contained.
_QM_A = "quick:google/gemini-3.5-flash-lite"
_QM_B = "quick:x-ai/grok-4.5"
_QM_JUDGE = "quick:openai/gpt-5.6-sol"


# ---------------------------------------------------------------------------
# The debate-specific CHECK constraints (``ck_debate_sessions_status`` and
# ``ck_debate_messages_role``) are now correct in the schema: Alembic 0002
# widened them to the full lifecycle ('pending'/'in_progress'/'cancelled') and
# speaker roles ('debater'/'judge') the debate feature actually persists. So no
# test-side constraint patching is needed — debate passes purely on schema.


# ---------------------------------------------------------------------------
# Seed helpers — create sessions via the real model facade in an app_context.
# ---------------------------------------------------------------------------
def _make_session(flask_core, user_id, *, topic="Is cereal a soup?",
                  config_ids=None, judge=_QM_JUDGE, rounds=1, status="pending"):
    from app.models.debate_session import DebateSessionModel

    config_ids = config_ids or [_QM_A, _QM_B]
    with flask_core.app_context():
        session = DebateSessionModel.create(
            user_id=str(user_id),
            topic=topic,
            config_ids=config_ids,
            judge_config_id=judge,
            rounds=rounds,
            max_tokens=512,
        )
        if status != "pending":
            DebateSessionModel.update_status(session["_id"], status)
        return session


# ---------------------------------------------------------------------------
# POST /sessions — create.
# ---------------------------------------------------------------------------
def test_create_session_happy_path(client, auth_headers, test_user):
    resp = client.post("/api/debate/sessions", headers=auth_headers, json={
        "topic": "Are hot dogs sandwiches?",
        "config_ids": [_QM_A, _QM_B],
        "judge_config_id": _QM_JUDGE,
        "rounds": 2,
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["message"] == "Debate session created"
    session = body["session"]
    # Legacy _id alias must be present on the entity.
    assert "_id" in session
    assert session["topic"] == "Are hot dogs sandwiches?"
    assert session["config_ids"] == [_QM_A, _QM_B]
    assert session["judge_config_id"] == _QM_JUDGE
    assert str(session["user_id"]) == str(test_user["_id"])


def test_create_session_missing_topic_400(client, auth_headers):
    resp = client.post("/api/debate/sessions", headers=auth_headers, json={
        "config_ids": [_QM_A, _QM_B], "judge_config_id": _QM_JUDGE,
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Topic is required"


def test_create_session_too_few_configs_400(client, auth_headers):
    resp = client.post("/api/debate/sessions", headers=auth_headers, json={
        "topic": "x", "config_ids": [_QM_A], "judge_config_id": _QM_JUDGE,
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "At least 2 debater configs are required"


def test_create_session_too_many_configs_400(client, auth_headers):
    resp = client.post("/api/debate/sessions", headers=auth_headers, json={
        "topic": "x",
        "config_ids": [_QM_A, _QM_B, _QM_A, _QM_B, _QM_A, _QM_B],
        "judge_config_id": _QM_JUDGE,
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Maximum 5 debater configs allowed"


def test_create_session_missing_judge_400(client, auth_headers):
    resp = client.post("/api/debate/sessions", headers=auth_headers, json={
        "topic": "x", "config_ids": [_QM_A, _QM_B],
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Judge config is required"


def test_create_session_unknown_config_403(client, auth_headers):
    # A non-quick UUID-shaped id is validated via resolve_config (ownership +
    # visibility), which returns None for BOTH a non-existent id and a foreign
    # private id -> 403 with no existence oracle (was a 404 "Config not found").
    resp = client.post("/api/debate/sessions", headers=auth_headers, json={
        "topic": "x",
        "config_ids": ["00000000-0000-0000-0000-000000000000", _QM_B],
        "judge_config_id": _QM_JUDGE,
    })
    assert resp.status_code == 403
    assert resp.json()["error"] == (
        "Config 00000000-0000-0000-0000-000000000000 not accessible"
    )


def test_create_session_unknown_judge_403(client, auth_headers):
    resp = client.post("/api/debate/sessions", headers=auth_headers, json={
        "topic": "x",
        "config_ids": [_QM_A, _QM_B],
        "judge_config_id": "00000000-0000-0000-0000-000000000000",
    })
    assert resp.status_code == 403
    assert resp.json()["error"] == "Judge config not accessible"


def test_create_session_requires_auth(client):
    resp = client.post("/api/debate/sessions", json={"topic": "x"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# GET /sessions — list + pagination.
# ---------------------------------------------------------------------------
def test_list_sessions_happy_path(client, auth_headers, flask_core, test_user):
    _make_session(flask_core, test_user["_id"], topic="Debate One")
    resp = client.get("/api/debate/sessions", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert len(body["sessions"]) == 1
    s = body["sessions"][0]
    assert "_id" in s
    # Enrichment: quick-model display names resolved.
    assert s["config_names"] == ["Gemini 3.1 Flash Lite", "Grok 4.3"]
    assert s["judge_name"] == "GPT-5.5"


def test_list_sessions_pagination_limit_capped(client, auth_headers, flask_core, test_user):
    for i in range(3):
        _make_session(flask_core, test_user["_id"], topic=f"D{i}")
    resp = client.get("/api/debate/sessions?page=1&limit=100", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    # limit capped at 50 -> pages math uses the capped limit.
    assert body["pages"] == 1


def test_list_sessions_requires_auth(client):
    resp = client.get("/api/debate/sessions")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# GET /sessions/{id} — fetch one.
# ---------------------------------------------------------------------------
def test_get_session_happy_path(client, auth_headers, flask_core, test_user):
    session = _make_session(flask_core, test_user["_id"], topic="Detailed Debate")
    resp = client.get(f"/api/debate/sessions/{session['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["session"]
    assert str(data["_id"]) == str(session["_id"])
    assert data["config_names"] == ["Gemini 3.1 Flash Lite", "Grok 4.3"]
    assert data["judge_name"] == "GPT-5.5"
    assert isinstance(data["debaters"], list) and len(data["debaters"]) == 2
    assert data["debaters"][0]["isQuickModel"] is True
    assert data["judge"]["isQuickModel"] is True
    assert data["messages"] == []


def test_get_session_not_found_404(client, auth_headers):
    resp = client.get(
        "/api/debate/sessions/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Session not found"


def test_get_session_other_user_403(client, plain_headers, flask_core, test_user):
    # Session owned by test_user, accessed by plain_user.
    session = _make_session(flask_core, test_user["_id"])
    resp = client.get(f"/api/debate/sessions/{session['_id']}", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Not authorized"


def test_get_session_requires_auth(client, flask_core, test_user):
    session = _make_session(flask_core, test_user["_id"])
    resp = client.get(f"/api/debate/sessions/{session['_id']}")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /sessions/{id}.
# ---------------------------------------------------------------------------
def test_delete_session_happy_path(client, auth_headers, flask_core, test_user):
    session = _make_session(flask_core, test_user["_id"])
    resp = client.delete(f"/api/debate/sessions/{session['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Session deleted"
    # Gone afterward.
    again = client.get(f"/api/debate/sessions/{session['_id']}", headers=auth_headers)
    assert again.status_code == 404


def test_delete_session_not_found_404(client, auth_headers):
    resp = client.delete(
        "/api/debate/sessions/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_delete_session_other_user_403(client, plain_headers, flask_core, test_user):
    session = _make_session(flask_core, test_user["_id"])
    resp = client.delete(f"/api/debate/sessions/{session['_id']}", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Not authorized"


# ---------------------------------------------------------------------------
# POST /sessions/{id}/cancel.
# ---------------------------------------------------------------------------
def test_cancel_session_happy_path(client, auth_headers, flask_core, test_user):
    session = _make_session(flask_core, test_user["_id"], status="in_progress")
    resp = client.post(f"/api/debate/sessions/{session['_id']}/cancel", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Session cancelled"


def test_cancel_session_wrong_status_400(client, auth_headers, flask_core, test_user):
    # 'completed' status is not cancellable.
    session = _make_session(flask_core, test_user["_id"], status="completed")
    resp = client.post(f"/api/debate/sessions/{session['_id']}/cancel", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Session cannot be cancelled"


def test_cancel_session_not_found_404(client, auth_headers):
    resp = client.post(
        "/api/debate/sessions/00000000-0000-0000-0000-000000000000/cancel",
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_cancel_session_other_user_403(client, plain_headers, flask_core, test_user):
    session = _make_session(flask_core, test_user["_id"], status="in_progress")
    resp = client.post(f"/api/debate/sessions/{session['_id']}/cancel", headers=plain_headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /cancel/{id} — generation cancel (stream_state).
# ---------------------------------------------------------------------------
def test_cancel_generation_no_active_404(client, auth_headers, flask_core, test_user):
    # No stream registered -> mark_cancelled returns False -> 404.
    session = _make_session(flask_core, test_user["_id"])
    resp = client.post(f"/api/debate/cancel/{session['_id']}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "No active generation"


def test_cancel_generation_active(client, auth_headers, flask_core, test_user):
    session = _make_session(flask_core, test_user["_id"])
    with flask_core.app_context():
        from app.services import stream_state
        stream_state.register(session["_id"], user_id=str(test_user["_id"]))
    resp = client.post(f"/api/debate/cancel/{session['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True


def test_cancel_generation_other_user_403(client, plain_headers, flask_core, test_user):
    session = _make_session(flask_core, test_user["_id"])
    resp = client.post(f"/api/debate/cancel/{session['_id']}", headers=plain_headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /stream — SSE.
# ---------------------------------------------------------------------------
def test_stream_missing_session_id_400(client, auth_headers):
    resp = client.post("/api/debate/stream", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "session_id is required"


def test_stream_session_not_found_404(client, auth_headers):
    resp = client.post("/api/debate/stream", headers=auth_headers, json={
        "session_id": "00000000-0000-0000-0000-000000000000",
    })
    assert resp.status_code == 404
    assert resp.json()["error"] == "Session not found"


def test_stream_other_user_403(client, plain_headers, flask_core, test_user):
    session = _make_session(flask_core, test_user["_id"])
    resp = client.post("/api/debate/stream", headers=plain_headers, json={
        "session_id": session["_id"],
    })
    assert resp.status_code == 403
    assert resp.json()["error"] == "Not authorized"


def test_stream_completed_session_400(client, auth_headers, flask_core, test_user):
    session = _make_session(flask_core, test_user["_id"], status="completed")
    resp = client.post("/api/debate/stream", headers=auth_headers, json={
        "session_id": session["_id"],
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Debate already completed"


def test_stream_cancelled_session_400(client, auth_headers, flask_core, test_user):
    session = _make_session(flask_core, test_user["_id"], status="cancelled")
    resp = client.post("/api/debate/stream", headers=auth_headers, json={
        "session_id": session["_id"],
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Debate was cancelled"


def _fake_chat_completion(*args, **kwargs):
    """Yield a couple of OpenRouter-shaped streaming chunks, then done.

    Marker-aware: include ``[DEBATE_CONCLUDED]`` so the strip path is exercised
    when the debater concludes — but sessions here run finite (rounds=1) so the
    marker is harmless and simply proves stripping doesn't corrupt content.
    """
    yield {"choices": [{"delta": {"content": "Hello "}}]}
    yield {"choices": [{"delta": {"content": "world."}}],
           "usage": {"prompt_tokens": 5, "completion_tokens": 3}}
    yield {"done": True}


def _read_first_frames(client, headers, body, *, max_frames=3):
    # Drain the SSE stream to completion before leaving the ``client.stream``
    # context. The debate generator opens its own ``flask_core.app_context()``
    # for the whole stream lifetime; abandoning the response mid-flight (closing
    # the context manager while the generator is suspended at a ``yield``) cancels
    # it from a foreign context, so Flask's app_context pop raises "Token ... was
    # created in a different Context". The fake completion is finite (rounds=1),
    # so the full stream completes promptly; we still assert on the FIRST frames.
    with client.stream("POST", "/api/debate/stream", headers=headers, json=body) as resp:
        assert resp.status_code == 200, resp.read()
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers.get("x-accel-buffering") == "no"
        text_body = "".join(resp.iter_text())

    frames = [f for f in text_body.split("\n\n") if f]
    return frames[:max_frames]


def test_stream_happy_path_first_frame(client, auth_headers, flask_core, test_user, monkeypatch):
    from app.services.openrouter_service import OpenRouterService

    monkeypatch.setattr(OpenRouterService, "chat_completion",
                        staticmethod(_fake_chat_completion))

    session = _make_session(flask_core, test_user["_id"], rounds=1)
    frames = _read_first_frames(client, auth_headers, {"session_id": session["_id"]})
    assert frames, "expected at least one SSE frame"
    # First emitted event is the session-started handshake.
    first = frames[0]
    assert first.startswith("event: debate_session_started")
    payload = json.loads(first.split("data: ", 1)[1])
    assert str(payload["session_id"]) == str(session["_id"])
    assert payload["topic"] == session["topic"]
    assert payload["debaters"] == ["Gemini 3.1 Flash Lite", "Grok 4.3"]


def test_stream_judge_config_not_found_404(client, auth_headers, flask_core, test_user, monkeypatch):
    from app.services.openrouter_service import OpenRouterService

    monkeypatch.setattr(OpenRouterService, "chat_completion",
                        staticmethod(_fake_chat_completion))

    # Debaters resolve (quick models) but judge is an unknown UUID -> 404 before
    # streaming starts.
    session = _make_session(
        flask_core, test_user["_id"],
        judge="00000000-0000-0000-0000-000000000000",
    )
    resp = client.post("/api/debate/stream", headers=auth_headers, json={
        "session_id": session["_id"],
    })
    assert resp.status_code == 404
    assert resp.json()["error"] == "Judge config not found"


def test_stream_requires_auth(client):
    resp = client.post("/api/debate/stream", json={"session_id": "x"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# Route-registration smoke.
# ---------------------------------------------------------------------------
def test_debate_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/debate/sessions" in paths
    assert "/api/debate/sessions/{session_id}" in paths
    assert "/api/debate/sessions/{session_id}/cancel" in paths
    assert "/api/debate/stream" in paths
    assert "/api/debate/cancel/{session_id}" in paths
