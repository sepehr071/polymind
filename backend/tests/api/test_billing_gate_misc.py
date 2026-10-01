"""Spend-gate wiring tests for the misc chokepoints (image-gen + helper).

Verifies the pre-flight budget gate fires at:
  * ``POST /api/image-gen/generate``  (plain JSON -> HTTP 402 on breach)
  * ``POST /api/helper/stream``       (SSE -> 402 BEFORE any frame on breach)

Strategy: the cheapest forced block is a ZERO user budget — ``spent (0) >= limit
(0)`` trips immediately, so no rollup seeding is needed and no workspace is
required (the user-level ceiling binds first). The ``billing_enforcement``
platform flag is OFF by default (``truncate_all`` wipes ``platform_settings``
after every test), so an autouse fixture flips it ON per-test; the flag-off case
explicitly leaves it off and asserts the route proceeds past the gate.

External providers are stubbed so a NON-blocked path can't reach the network and
a missed gate surfaces as a non-402 success/error rather than a hang.
"""
import json

import pytest


@pytest.fixture(autouse=True)
def _enable_billing_enforcement(flask_core):
    """Flip the billing_enforcement flag ON for every test in this module.

    truncate_all wipes platform_settings after each test, so this re-seeds it
    each run via an UPSERT (set_feature). The flag-off tests below override by
    clearing it first. Reads the value back so a non-durable write (e.g. a
    truncate-deadlock rollback in the prior test's teardown) surfaces as a clear
    setup error here rather than a confusing 200-not-402 later.
    """
    from app.models.platform_settings import PlatformSettingsModel

    with flask_core.app_context():
        PlatformSettingsModel.set_feature("billing_enforcement", True, None)
        assert PlatformSettingsModel.get_features().get("billing_enforcement") is True
    yield


def _zero_user_budget(flask_core, user_id):
    """Set a hard $0 monthly budget on the user scope -> instant block."""
    from app.models.budget_allocation import BudgetAllocationModel

    with flask_core.app_context():
        BudgetAllocationModel.set_budget("user", str(user_id), 0)


def _stub_generate_image(monkeypatch):
    """Stub the provider so a NON-blocked image request returns 200, not network."""
    from app.services.openrouter_service import OpenRouterService

    monkeypatch.setattr(
        OpenRouterService, "generate_image",
        staticmethod(lambda *a, **k: {
            "success": True,
            "images": ["data:image/png;base64,ZmFrZQ=="],
            "image_data": "data:image/png;base64,ZmFrZQ==",
            "usage": {"cost": 0.0},
            "cost_usd_total": 0.0,
            "tokens_total": 0,
            "n": 1,
        }),
    )


def _stub_helper_stream(monkeypatch):
    """Stub OpenRouter streaming so a NON-blocked helper request streams cleanly."""
    def _fake_stream(*a, **k):
        yield {"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]}
        yield {"done": True}

    monkeypatch.setattr(
        "app.services.openrouter_service.OpenRouterService.chat_completion",
        staticmethod(_fake_stream),
        raising=True,
    )


# ===========================================================================
# Image generation — POST /api/image-gen/generate.
# ===========================================================================
def test_image_generate_budget_block_402(client, auth_headers, test_user,
                                          flask_core, monkeypatch):
    """A $0 user budget -> 402 budget_exceeded BEFORE the provider call."""
    _stub_generate_image(monkeypatch)
    _zero_user_budget(flask_core, test_user["_id"])

    resp = client.post(
        "/api/image-gen/generate", headers=auth_headers,
        json={"prompt": "a fox in snow", "model": "google/x"},
    )
    assert resp.status_code == 402, resp.text
    body = resp.json()
    assert body["code"] == "budget_exceeded"
    assert body["scope"] == "user"
    assert body["limit"] == 0


def test_image_generate_flag_off_not_402(client, auth_headers, test_user,
                                         flask_core, monkeypatch):
    """Flag OFF -> the gate is a no-op even with a $0 budget; route proceeds."""
    _stub_generate_image(monkeypatch)
    # Disable enforcement (the autouse fixture turned it on) + still set $0 budget
    # to prove the gate genuinely short-circuits on the flag, not on the budget.
    from app.models.platform_settings import PlatformSettingsModel

    with flask_core.app_context():
        PlatformSettingsModel.set_feature("billing_enforcement", False, None)
    _zero_user_budget(flask_core, test_user["_id"])

    resp = client.post(
        "/api/image-gen/generate", headers=auth_headers,
        json={"prompt": "a fox in snow", "model": "google/x"},
    )
    # Must NOT be the budget 402 — it sailed past the gate (then succeeded, since
    # the provider is stubbed). Only the absence of 402 is load-bearing.
    assert resp.status_code != 402, resp.text
    assert resp.status_code == 200, resp.text


# ===========================================================================
# Helper SSE — POST /api/helper/stream.
# ===========================================================================
def test_helper_stream_budget_block_402(client, plain_headers, plain_user,
                                        flask_core, monkeypatch):
    """A $0 user budget -> 402 BEFORE any SSE frame (no workspace needed)."""
    _stub_helper_stream(monkeypatch)
    _zero_user_budget(flask_core, plain_user["_id"])

    with client.stream(
        "POST", "/api/helper/stream", headers=plain_headers,
        json={"message": "How do I create a chat?"},
    ) as resp:
        # The breach is a clean HTTP status, asserted before reading the body.
        assert resp.status_code == 402, resp.read().decode()
        body = json.loads(resp.read())

    assert body["code"] == "budget_exceeded"
    assert body["scope"] == "user"
    assert body["limit"] == 0


def test_helper_stream_flag_off_not_402(client, plain_headers, plain_user,
                                        flask_core, monkeypatch):
    """Flag OFF -> helper stream proceeds past the gate (200 SSE)."""
    _stub_helper_stream(monkeypatch)
    from app.models.platform_settings import PlatformSettingsModel

    with flask_core.app_context():
        PlatformSettingsModel.set_feature("billing_enforcement", False, None)
    _zero_user_budget(flask_core, plain_user["_id"])

    with client.stream(
        "POST", "/api/helper/stream", headers=plain_headers,
        json={"message": "How do I create a chat?"},
    ) as resp:
        assert resp.status_code != 402, resp.read().decode()
        assert resp.status_code == 200
        # Drain fully so truncate_all isn't blocked by a suspended generator.
        _ = resp.read()
