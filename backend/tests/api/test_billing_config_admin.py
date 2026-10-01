"""Integration tests for the admin billing-config routes.

``GET`` + ``PUT /api/admin/billing/config`` (app/api/routers/admin_holding.py)
expose the two profit knobs introduced by the 2026-06-29 profit redesign:

  * ``markup_pct``       — flat margin on upstream OpenRouter cost.
  * ``credits_per_usd``  — scales the user-facing Polymind-Credits display unit.

Both are gated by ``require_admin``. Idioms mirror tests/api/test_holding_transfer.py
(real model facades on Postgres, the ``client``/``mint_token``/``admin_user``
fixtures, truncate_all autouse). The process-local billing TTL cache is reset
around every case (mirrors test_markup_record_usage.py) so a stale cached knob
can never leak across tests, and so we can assert cache-invalidation-on-write.
"""
import pytest


@pytest.fixture(autouse=True)
def _reset_billing_cache():
    """Drop the process-local markup/credits TTL cache before AND after each
    case so a stale cached value can never leak across tests."""
    from app.models.platform_settings import _invalidate_billing_cache
    _invalidate_billing_cache()
    yield
    _invalidate_billing_cache()


def _admin_headers(mint_token, admin_user):
    token = mint_token(admin_user["_id"], role="admin")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Auth gating.
# ---------------------------------------------------------------------------
def test_get_no_token_401(client):
    resp = client.get("/api/admin/billing/config")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_get_non_admin_403(client, plain_headers):
    resp = client.get("/api/admin/billing/config", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Admin access required"


def test_put_non_admin_403(client, plain_headers):
    resp = client.put(
        "/api/admin/billing/config",
        json={"markup_pct": 0.2},
        headers=plain_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "Admin access required"


def test_put_manager_role_403(client, auth_headers):
    # auth_headers is the manager test_user — still not admin.
    resp = client.put(
        "/api/admin/billing/config",
        json={"markup_pct": 0.2},
        headers=auth_headers,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET — defaults on a fresh DB.
# ---------------------------------------------------------------------------
def test_get_defaults(client, mint_token, admin_user):
    resp = client.get("/api/admin/billing/config", headers=_admin_headers(mint_token, admin_user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"markup_pct": 0.0, "credits_per_usd": 1000.0}


# ---------------------------------------------------------------------------
# PUT — valid update is reflected by a subsequent GET.
# ---------------------------------------------------------------------------
def test_put_markup_and_credits_then_get_reflects(client, mint_token, admin_user):
    headers = _admin_headers(mint_token, admin_user)
    resp = client.put(
        "/api/admin/billing/config",
        json={"markup_pct": 0.35, "credits_per_usd": 500.0},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"markup_pct": 0.35, "credits_per_usd": 500.0}

    # A fresh GET reflects the persisted values.
    got = client.get("/api/admin/billing/config", headers=headers)
    assert got.status_code == 200
    assert got.json() == {"markup_pct": 0.35, "credits_per_usd": 500.0}


def test_put_partial_markup_only(client, mint_token, admin_user):
    """Updating only markup_pct leaves credits_per_usd at its default."""
    headers = _admin_headers(mint_token, admin_user)
    resp = client.put("/api/admin/billing/config", json={"markup_pct": 1.5}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"markup_pct": 1.5, "credits_per_usd": 1000.0}


def test_put_empty_body_400(client, mint_token, admin_user):
    """No recognized keys -> 400 with the legacy error shape."""
    resp = client.put(
        "/api/admin/billing/config",
        json={"nope": 1},
        headers=_admin_headers(mint_token, admin_user),
    )
    assert resp.status_code == 400
    assert resp.json()["status"] == 400
    assert "markup_pct" in resp.json()["error"]


# ---------------------------------------------------------------------------
# PUT — out-of-bounds values -> 400 (ValueError normalized).
# ---------------------------------------------------------------------------
def test_put_markup_out_of_bounds_400(client, mint_token, admin_user):
    """markup_pct max is 5.0 -> 99 is rejected, nothing persisted."""
    headers = _admin_headers(mint_token, admin_user)
    resp = client.put("/api/admin/billing/config", json={"markup_pct": 99}, headers=headers)
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["status"] == 400
    assert "markup_pct" in body["error"]

    # The rejected write left the default untouched.
    got = client.get("/api/admin/billing/config", headers=headers).json()
    assert got["markup_pct"] == 0.0


def test_put_credits_zero_400(client, mint_token, admin_user):
    """credits_per_usd must be > 0 -> 0 is rejected."""
    headers = _admin_headers(mint_token, admin_user)
    resp = client.put("/api/admin/billing/config", json={"credits_per_usd": 0}, headers=headers)
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["status"] == 400
    assert "credits_per_usd" in body["error"]

    got = client.get("/api/admin/billing/config", headers=headers).json()
    assert got["credits_per_usd"] == 1000.0


# ---------------------------------------------------------------------------
# Cache invalidation — after a PUT, the cached knob reader reflects the new value.
# ---------------------------------------------------------------------------
def test_put_invalidates_cache_for_get_markup_pct(client, flask_core, mint_token, admin_user):
    """A PUT through the route must invalidate the process-local billing cache so
    ``get_markup_pct`` (read on every billable LLM call) sees the new value."""
    from app.models.platform_settings import PlatformSettingsModel

    headers = _admin_headers(mint_token, admin_user)
    # Prime the cache with the default via the model reader.
    with flask_core.app_context():
        assert PlatformSettingsModel.get_markup_pct() == 0.0

    resp = client.put("/api/admin/billing/config", json={"markup_pct": 0.25}, headers=headers)
    assert resp.status_code == 200, resp.text

    # Without explicit cache reset here: the route's write path invalidated it,
    # so the very next read returns the new value (not the cached 0.0).
    with flask_core.app_context():
        assert PlatformSettingsModel.get_markup_pct() == 0.25


# ---------------------------------------------------------------------------
# Audit row — one category='holding' billing_config_set row per PUT.
# ---------------------------------------------------------------------------
def test_put_writes_audit_row(client, flask_core, mint_token, admin_user):
    headers = _admin_headers(mint_token, admin_user)
    resp = client.put(
        "/api/admin/billing/config",
        json={"markup_pct": 0.4, "credits_per_usd": 250.0},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    with flask_core.app_context():
        from app.models.audit_log import AuditLogModel
        rows = AuditLogModel.find_all(action="billing_config_set")
    assert len(rows) == 1
    event = rows[0]
    assert event["category"] == "holding"
    assert event["target_type"] == "platform_settings"
    assert event["target_id"] == "singleton"
    assert event["details"]["after"] == {"markup_pct": 0.4, "credits_per_usd": 250.0}
