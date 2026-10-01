"""Internal cost-allocation markup at the SOLE usage_logs writer.

Profit redesign 2026-06-29. ``OpenRouterService._record_usage`` applies a flat
platform markup so the persisted ``usage_logs`` row carries:

  - ``cost_usd``          = marked-up PRICE  (upstream × (1 + markup_pct))
  - ``upstream_cost_usd`` = TRUE OpenRouter cost (always, every row)
  - margin                = cost_usd − upstream_cost_usd

Default markup is 0.0 → no behavior change (report-only rollout): ``cost_usd``
equals ``upstream_cost_usd``. These tests drive ``_record_usage`` directly (it is
the SOLE writer) across all three cost-resolution paths and read the persisted
row back from the DB.

The markup knob is set via ``PlatformSettingsModel.set_markup_pct(v, by=None)``
(which auto-invalidates the TTL cache via ``_write_scalar``); an autouse fixture
also resets the cache between cases for hygiene. The OpenRouter stubbing mirrors
``test_billing_gate_chat.py`` — no network is ever touched.
"""
import uuid

import pytest

# A small, exactly-representable upstream cost. 0.001 × 1.3 = 0.0013, both round
# cleanly at 8 dp so float equality holds without an epsilon dance.
_UPSTREAM = 0.001
_MARKUP = 0.3
_EXPECTED_PRICE = round(_UPSTREAM * (1.0 + _MARKUP), 8)  # 0.0013


@pytest.fixture(autouse=True)
def _reset_billing_cache():
    """Drop the process-local markup/credits TTL cache before AND after each
    case so a stale cached markup can never leak across tests."""
    from app.models.platform_settings import _invalidate_billing_cache
    _invalidate_billing_cache()
    yield
    _invalidate_billing_cache()


def _set_markup(flask_core, value):
    from app.models.platform_settings import PlatformSettingsModel
    with flask_core.app_context():
        PlatformSettingsModel.set_markup_pct(value, by=None)


def _record(flask_core, user_id, response_usage, *, model_id="openai/gpt-4o",
            generation_id=None):
    """Invoke the SOLE usage_logs writer inside an app_context."""
    from app.services.openrouter_service import OpenRouterService
    with flask_core.app_context():
        return OpenRouterService._record_usage(
            user_id=user_id,
            conversation_id=None,
            model_id=model_id,
            response_usage=response_usage,
            feature="chat",
            generation_id=generation_id,
            origin="web",
        )


def _latest_row(flask_core, user_id):
    """Read back the most recent persisted usage_logs row for ``user_id``."""
    from app.extensions import db
    from app.models.usage_log import UsageLog
    with flask_core.app_context():
        row = db.session.execute(
            db.select(UsageLog)
            .where(UsageLog.user_id == uuid.UUID(str(user_id)))
            .order_by(UsageLog.created_at.desc())
        ).scalars().first()
        assert row is not None, "expected a usage_logs row to be written"
        # Numeric(14,8) -> Decimal; normalize to float for comparison.
        return {
            "cost_usd": float(row.cost_usd) if row.cost_usd is not None else None,
            "upstream_cost_usd": (
                float(row.upstream_cost_usd)
                if row.upstream_cost_usd is not None else None
            ),
        }


# ---------------------------------------------------------------------------
# markup = 0 (default rollout) -> price == upstream, margin 0.
# ---------------------------------------------------------------------------
def test_markup_zero_price_equals_upstream(flask_core, test_user):
    _set_markup(flask_core, 0.0)

    ret = _record(flask_core, test_user["_id"], {"cost": _UPSTREAM})

    row = _latest_row(flask_core, test_user["_id"])
    assert row["cost_usd"] == _UPSTREAM
    assert row["upstream_cost_usd"] == _UPSTREAM
    # margin = price − upstream == 0
    assert row["cost_usd"] - row["upstream_cost_usd"] == 0.0
    # The return dict reports the (price) cost_usd.
    assert ret is not None
    assert ret["cost_usd"] == _UPSTREAM


# ---------------------------------------------------------------------------
# markup = 0.3 -> price == round(upstream*1.3, 8); upstream stored verbatim.
# ---------------------------------------------------------------------------
def test_markup_thirty_marks_up_price_keeps_upstream(flask_core, test_user):
    _set_markup(flask_core, _MARKUP)

    ret = _record(flask_core, test_user["_id"], {"cost": _UPSTREAM})

    row = _latest_row(flask_core, test_user["_id"])
    assert row["upstream_cost_usd"] == _UPSTREAM          # TRUE cost preserved
    assert row["cost_usd"] == _EXPECTED_PRICE             # marked-up price
    # margin = price − upstream is the platform's cut.
    assert row["cost_usd"] - row["upstream_cost_usd"] == pytest.approx(
        _UPSTREAM * _MARKUP, abs=1e-9
    )
    # Return dict carries the PRICE (rollups/wallets operate in price terms).
    assert ret["cost_usd"] == _EXPECTED_PRICE


# ---------------------------------------------------------------------------
# Local-pricing FALLBACK path (no provider cost, no generation_id) is ALSO
# marked up, and stores the true (locally-computed) upstream cost.
# ---------------------------------------------------------------------------
def test_local_pricing_fallback_is_marked_up(flask_core, test_user, monkeypatch):
    # Force the ModelRegistryService local-pricing branch: prompt 1000 tok @
    # $0.0000005 + completion 1000 tok @ $0.0000005 = 0.001 upstream.
    class _FakeRegistry:
        def get_pricing(self, model_id):
            return {"prompt": 5e-7, "completion": 5e-7, "cached": 0.0}

    monkeypatch.setattr(
        "app.services.model_registry_service.ModelRegistryService",
        _FakeRegistry,
    )
    _set_markup(flask_core, _MARKUP)

    # No 'cost', no generation_id -> drops straight into local pricing.
    ret = _record(
        flask_core,
        test_user["_id"],
        {"prompt_tokens": 1000, "completion_tokens": 1000},
        generation_id=None,
    )

    row = _latest_row(flask_core, test_user["_id"])
    assert row["upstream_cost_usd"] == pytest.approx(_UPSTREAM, abs=1e-12)
    assert row["cost_usd"] == pytest.approx(_EXPECTED_PRICE, abs=1e-12)
    # margin correct on the fallback path too.
    assert row["cost_usd"] - row["upstream_cost_usd"] == pytest.approx(
        _UPSTREAM * _MARKUP, abs=1e-9
    )
    assert ret["cost_usd"] == pytest.approx(_EXPECTED_PRICE, abs=1e-12)
