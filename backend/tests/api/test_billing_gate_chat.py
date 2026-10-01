"""Spend-gate (billing enforcement) wiring tests for the chat chokepoints.

Asserts the pre-flight budget gate fires at the FastAPI chat endpoints:
  - POST /api/chat/send   -> HTTP 402 when the user budget is exhausted.
  - POST /api/chat/stream -> HTTP 402 BEFORE any SSE frame.
  - POST /api/chat/send   -> proceeds (NOT 402) when the flag is OFF, even with
    an exhausted budget (the route may then fail later for unrelated reasons —
    we only assert it got PAST the gate).

The cheapest forced block is a zero user budget (``set_budget('user', uid, 0)``):
spent 0 >= limit 0 -> immediate breach, no rollups needed.

``truncate_all`` wipes ``platform_settings`` after EVERY test, so an autouse
fixture flips ``billing_enforcement`` ON per-test; the flag-off test disables it
explicitly. The smart-scan DLP classifier + the OpenRouter round-trips are
stubbed so the flag-off route runs end-to-end without ever hitting the network.
"""
import pytest


@pytest.fixture(autouse=True)
def _enable_enforcement(flask_core):
    """Flip ``billing_enforcement`` ON before each test (truncate_all wiped it)."""
    from app.models.platform_settings import PlatformSettingsModel
    with flask_core.app_context():
        PlatformSettingsModel.set_feature('billing_enforcement', True, None)


@pytest.fixture(autouse=True)
def _no_openrouter(monkeypatch):
    """Stub the DLP classifier + completions so flag-off routes never hit the net."""
    monkeypatch.setattr(
        "app.services.dlp_service.DLPDetector.llm_classify",
        lambda self, text, user_lang="en", *, user_id=None: None,
    )

    def _fake_completion(*args, **kwargs):
        return {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(
        "app.services.openrouter_service.OpenRouterService.chat_completion",
        staticmethod(_fake_completion),
    )
    monkeypatch.setattr(
        "app.services.openrouter_service.OpenRouterService.generate_title",
        staticmethod(lambda *a, **k: "Title"),
    )
    yield


def _disable_enforcement(flask_core):
    from app.models.platform_settings import PlatformSettingsModel
    with flask_core.app_context():
        PlatformSettingsModel.set_feature('billing_enforcement', False, None)


def _set_user_budget(flask_core, uid, amount):
    from app.models.budget_allocation import BudgetAllocationModel
    with flask_core.app_context():
        BudgetAllocationModel.set_budget('user', uid, amount, by=None)


def _auth(mint_token, user, role="manager"):
    return {
        "Authorization": f"Bearer {mint_token(user['_id'], role=role)}",
        "Content-Type": "application/json",
    }


def _quick_config_id():
    """A usable quick-model config id (resolves without a DB row)."""
    from app.utils.quick_models import QUICK_MODELS
    model_id = next(iter(QUICK_MODELS.keys()))
    return f"quick:{model_id}"


# ---------------------------------------------------------------------------
# POST /api/chat/send — 402 on exhausted user budget.
# ---------------------------------------------------------------------------
def test_send_blocked_402_on_zero_user_budget(client, flask_core, test_user, mint_token):
    # Zero user budget -> spent 0 >= limit 0 -> immediate breach.
    _set_user_budget(flask_core, test_user["_id"], 0)
    config_id = _quick_config_id()

    resp = client.post(
        "/api/chat/send",
        headers=_auth(mint_token, test_user),
        json={"message": "hello there", "config_id": config_id},
    )
    assert resp.status_code == 402, resp.text
    body = resp.json()
    assert body["code"] == "budget_exceeded"
    assert body["scope"] == "user"


# ---------------------------------------------------------------------------
# POST /api/chat/stream — 402 BEFORE any SSE frame.
# ---------------------------------------------------------------------------
def test_stream_blocked_402_before_any_frame(client, flask_core, test_user, mint_token):
    _set_user_budget(flask_core, test_user["_id"], 0)
    config_id = _quick_config_id()

    with client.stream(
        "POST",
        "/api/chat/stream",
        headers=_auth(mint_token, test_user),
        json={"message": "hello there", "config_id": config_id},
    ) as resp:
        # The breach must surface as a clean 402, never an in-stream SSE error.
        assert resp.status_code == 402, resp.read()
        body = resp.read()
        # Drain fully inside the with-block (no suspended generator left behind).
    import json as _json
    parsed = _json.loads(body)
    assert parsed["code"] == "budget_exceeded"
    assert parsed["scope"] == "user"


# ---------------------------------------------------------------------------
# Flag OFF — the route proceeds past the gate (NOT 402) even when exhausted.
# ---------------------------------------------------------------------------
def test_send_proceeds_when_flag_off(client, flask_core, test_user, mint_token):
    # Budget is exhausted, but enforcement is OFF -> gate short-circuits.
    _set_user_budget(flask_core, test_user["_id"], 0)
    _disable_enforcement(flask_core)
    config_id = _quick_config_id()

    resp = client.post(
        "/api/chat/send",
        headers=_auth(mint_token, test_user),
        json={"message": "hello there", "config_id": config_id},
    )
    # Only assert it got PAST the gate — the stubbed completion makes 200 likely,
    # but any non-402 proves the gate did not block.
    assert resp.status_code != 402, resp.text
    assert resp.status_code == 200, resp.text
