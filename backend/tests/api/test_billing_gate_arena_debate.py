"""Spend-gate (hierarchical billing) enforcement on the arena + debate routers.

Mirrors tests/api/test_arena.py / test_debate.py: real model facades on Postgres
via the flask_ctx bridge, conftest fixtures, OpenRouter monkeypatched so the SSE
fan-out never hits a real upstream.

The spend gate is spliced in at each chokepoint IMMEDIATELY after the existing
DLP gate and BEFORE any StreamingResponse / sse_stream_sync is constructed, so a
budget breach is a clean HTTP 402 (``BudgetExceededError`` -> global handler),
never an in-stream SSE error.

Block recipe (cheap + deterministic): ``BudgetAllocationModel.set_budget('user',
uid, 0)`` — a zero USER budget means spent (0.0) >= limit (0.0), so the gate
raises ``budget_exceeded`` scope=user on the very first call, independent of any
workspace/credit setup. The gate only enforces while the ``billing_enforcement``
platform feature flag is ON; an autouse fixture flips it on per-test, and
``truncate_all`` wipes ``platform_settings`` back to default (OFF) after each.
"""
import json

import pytest

# Two real quick-model ids (always visible) — pass session-CREATE validation.
QUICK_A = "quick:google/gemini-3.5-flash-lite"
QUICK_B = "quick:x-ai/grok-4.5"
QUICK_JUDGE = "quick:openai/gpt-5.6-sol"


# ---------------------------------------------------------------------------
# Enforcement flag — ON per-test (truncate_all resets platform_settings to the
# default-OFF state after every test).
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _billing_flag_on(flask_core):
    from app.models.platform_settings import PlatformSettingsModel

    with flask_core.app_context():
        PlatformSettingsModel.set_feature("billing_enforcement", True, None)
    yield


def _block_user(flask_core, user_id):
    """Set a zero MTD budget on the user -> the gate blocks on first call."""
    from app.models.budget_allocation import BudgetAllocationModel

    with flask_core.app_context():
        BudgetAllocationModel.set_budget("user", str(user_id), 0)


# ---------------------------------------------------------------------------
# OpenRouter stub — used only by the flag-OFF happy paths (so the stream runs
# past the gate without a real upstream).
# ---------------------------------------------------------------------------
def _fake_stream(*args, **kwargs):
    yield {
        "choices": [{"delta": {"content": "hi"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 5},
    }
    yield {"done": True}


@pytest.fixture
def patch_openrouter(monkeypatch):
    from app.services.openrouter_service import OpenRouterService

    monkeypatch.setattr(
        OpenRouterService, "chat_completion", staticmethod(_fake_stream)
    )
    return monkeypatch


@pytest.fixture
def real_config_ids(flask_core, test_user):
    """Two persisted LLMConfig rows so the arena fan-out resolves real configs."""
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


# ===========================================================================
# Arena — POST /api/arena/stream
# ===========================================================================
def test_arena_stream_blocked_402_before_frames(client, auth_headers, test_user, flask_core):
    """A zero user budget -> the spend gate returns 402 BEFORE any SSE frame."""
    _block_user(flask_core, test_user["_id"])

    # Stream context: the 402 is a plain JSONResponse emitted before the stream
    # body, so it surfaces as the response status with no event frames.
    with client.stream(
        "POST", "/api/arena/stream", headers=auth_headers,
        json={"config_ids": [QUICK_A, QUICK_B], "message": "hello there"},
    ) as resp:
        assert resp.status_code == 402, resp.read()
        body = resp.read().decode("utf-8")

    # The error body is JSON (NOT text/event-stream) — no SSE frames leaked.
    assert "event:" not in body
    payload = json.loads(body)
    assert payload["code"] == "budget_exceeded"
    assert payload["scope"] == "user"
    assert payload["limit"] == 0


def test_arena_stream_flag_off_not_402(client, auth_headers, test_user, flask_core,
                                       patch_openrouter, real_config_ids):
    """Flag OFF: even with a zero user budget the gate is inert -> never 402."""
    # Disable enforcement (autouse fixture turned it on); leave the zero budget in
    # place to prove it is the FLAG, not the absence of a budget, that gates.
    from app.models.platform_settings import PlatformSettingsModel

    _block_user(flask_core, test_user["_id"])
    with flask_core.app_context():
        PlatformSettingsModel.set_feature("billing_enforcement", False, None)

    with client.stream(
        "POST", "/api/arena/stream", headers=auth_headers,
        json={"config_ids": real_config_ids, "message": "hello there"},
    ) as resp:
        assert resp.status_code != 402, resp.read()
        assert resp.status_code == 200
        text = b"".join(resp.iter_bytes()).decode("utf-8")

    # The stream actually ran past the gate.
    assert "event:" in text


# ===========================================================================
# Debate — POST /api/debate/sessions (create chokepoint)
# ===========================================================================
def test_debate_create_blocked_402(client, auth_headers, test_user, flask_core):
    """A zero user budget -> create_session is blocked at the spend gate (402)."""
    _block_user(flask_core, test_user["_id"])

    resp = client.post("/api/debate/sessions", headers=auth_headers, json={
        "topic": "Are hot dogs sandwiches?",
        "config_ids": [QUICK_A, QUICK_B],
        "judge_config_id": QUICK_JUDGE,
        "rounds": 2,
    })
    assert resp.status_code == 402, resp.text
    payload = resp.json()
    assert payload["code"] == "budget_exceeded"
    assert payload["scope"] == "user"


def test_debate_create_flag_off_not_402(client, auth_headers, test_user, flask_core):
    """Flag OFF with a zero user budget: create still proceeds (NOT 402)."""
    from app.models.platform_settings import PlatformSettingsModel

    _block_user(flask_core, test_user["_id"])
    with flask_core.app_context():
        PlatformSettingsModel.set_feature("billing_enforcement", False, None)

    resp = client.post("/api/debate/sessions", headers=auth_headers, json={
        "topic": "Are hot dogs sandwiches?",
        "config_ids": [QUICK_A, QUICK_B],
        "judge_config_id": QUICK_JUDGE,
        "rounds": 2,
    })
    assert resp.status_code != 402, resp.text
    assert resp.status_code == 201, resp.text


# ===========================================================================
# Debate — POST /api/debate/stream (stream chokepoint)
# ===========================================================================
def test_debate_stream_blocked_402_before_frames(client, auth_headers, test_user, flask_core):
    """A zero user budget -> the stream gate returns 402 BEFORE any SSE frame.

    The session is created with the flag OFF (so create() isn't itself gated),
    then enforcement is turned on for the stream call.
    """
    from app.models.debate_session import DebateSessionModel
    from app.models.platform_settings import PlatformSettingsModel

    # Create the session WITHOUT enforcement so the create chokepoint passes.
    with flask_core.app_context():
        PlatformSettingsModel.set_feature("billing_enforcement", False, None)
        session = DebateSessionModel.create(
            user_id=str(test_user["_id"]),
            topic="Is cereal a soup?",
            config_ids=[QUICK_A, QUICK_B],
            judge_config_id=QUICK_JUDGE,
            rounds=1,
            max_tokens=512,
        )
    # Now arm enforcement + a zero user budget for the stream call.
    with flask_core.app_context():
        PlatformSettingsModel.set_feature("billing_enforcement", True, None)
    _block_user(flask_core, test_user["_id"])

    with client.stream(
        "POST", "/api/debate/stream", headers=auth_headers,
        json={"session_id": session["_id"]},
    ) as resp:
        assert resp.status_code == 402, resp.read()
        body = resp.read().decode("utf-8")

    assert "event:" not in body
    payload = json.loads(body)
    assert payload["code"] == "budget_exceeded"
    assert payload["scope"] == "user"
