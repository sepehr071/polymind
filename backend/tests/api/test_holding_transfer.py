"""Integration tests for holding -> company credit transfers.

Covers the ``source`` extension of ``POST /api/admin/companies/{wid}/credits``:
  * ``source='external'`` (default) — legacy behavior, holding pool untouched.
  * ``source='holding'``  — credits TRANSFERRED out of the holding pool, with a
    pre-flight pool-remaining guard (402 on over-draw, atomic on success).

Plus the holding overview/ledger surfacing of the new ``transferred`` /
``pool_remaining`` accounting.

Idioms mirror tests/api/test_platform.py (real model facades on Postgres, the
``client``/``mint_token``/``admin_user`` fixtures, truncate_all autouse). The
router gate is now ``require_admin`` (super-admin), not the old platform claim.

NOTE on robustness: the truncate_all autouse fixture terminates idle-in-
transaction backends between tests, which races with the TestClient's async
session teardown when a test issues many requests. To keep these tests
deterministic, each one issues the MINIMUM number of requests and asserts on
the POST response body (which already carries ``holding_pool_remaining_usd`` +
``credits_balance_usd``) wherever possible, using at most a single verifying
GET. The pool is funded through the production route (``POST /holding/credits``)
rather than a raw ``flask_core.app_context()`` so every write stays on the
request-scoped session.
"""
import uuid


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------
def _admin_headers(mint_token, admin_user):
    token = mint_token(admin_user["_id"], role="admin")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _seed_company(flask_core, owner, *, name="Acme Co"):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        return WorkspaceModel.create(name=name, owner_id=owner["_id"], type="team")


def _fund_pool(client, headers, amount, note="seed pool"):
    """Top up the holding pool via the production route (POST /holding/credits)."""
    resp = client.post(
        "/api/admin/holding/credits",
        json={"amount_usd": amount, "type": "top_up", "note": note},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _transfer(client, headers, wid, amount, **extra):
    body = {"amount_usd": amount, "source": "holding", **extra}
    return client.post(f"/api/admin/companies/{wid}/credits", json=body, headers=headers)


# ---------------------------------------------------------------------------
# source='external' — legacy behavior unchanged.
# ---------------------------------------------------------------------------
def test_external_source_default_unchanged(client, flask_core, mint_token, admin_user):
    """No source key -> external -> old response keys + pool untouched."""
    headers = _admin_headers(mint_token, admin_user)
    _fund_pool(client, headers, 500.0)
    ws = _seed_company(flask_core, admin_user, name="Umbrella")

    resp = client.post(
        f"/api/admin/companies/{ws['_id']}/credits",
        json={"amount_usd": 25.0, "type": "top_up", "note": "seed"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Legacy keys present + unchanged.
    assert "_id" in body["entry"]
    assert body["entry"]["amount_usd"] == 25.0
    assert body["credits_balance_usd"] == 25.0
    # Resolved source surfaced; transfer-only fields do NOT leak on external.
    assert body["source"] == "external"
    assert "holding_pool_remaining_usd" not in body

    # The holding pool was NOT touched by an external charge (single verify GET).
    overview = client.get("/api/admin/holding/overview", headers=headers).json()
    hc = overview["holding_credits"]
    assert hc["lifetime_topups_usd"] == 500.0
    assert hc["transferred_usd"] == 0.0
    assert hc["pool_remaining_usd"] == 500.0


def test_explicit_external_source(client, flask_core, mint_token, admin_user):
    headers = _admin_headers(mint_token, admin_user)
    _fund_pool(client, headers, 100.0)
    ws = _seed_company(flask_core, admin_user)
    resp = client.post(
        f"/api/admin/companies/{ws['_id']}/credits",
        json={"amount_usd": 10.0, "source": "external"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["source"] == "external"
    assert "holding_pool_remaining_usd" not in resp.json()


def test_bad_source_400(client, flask_core, mint_token, admin_user):
    ws = _seed_company(flask_core, admin_user)
    resp = client.post(
        f"/api/admin/companies/{ws['_id']}/credits",
        json={"amount_usd": 5.0, "source": "bogus"},
        headers=_admin_headers(mint_token, admin_user),
    )
    assert resp.status_code == 400
    assert "source must be one of" in resp.json()["error"]


# ---------------------------------------------------------------------------
# source='holding' — funded pool debits successfully.
# ---------------------------------------------------------------------------
def test_holding_transfer_happy(client, flask_core, mint_token, admin_user):
    headers = _admin_headers(mint_token, admin_user)
    _fund_pool(client, headers, 200.0)
    ws = _seed_company(flask_core, admin_user, name="Globex")

    resp = _transfer(client, headers, ws["_id"], 75.0, type="top_up", note="from pool")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Response body fully describes the result of the transfer.
    assert body["source"] == "holding"
    assert body["credits_balance_usd"] == 75.0
    assert body["holding_pool_remaining_usd"] == 125.0  # 200 - 75
    assert "_id" in body["entry"]
    assert body["entry"]["amount_usd"] == 75.0

    # Single verify GET: pool transferred bumped, remaining dropped, topups intact.
    hc = client.get("/api/admin/holding/overview", headers=headers).json()["holding_credits"]
    assert hc["lifetime_topups_usd"] == 200.0
    assert hc["transferred_usd"] == 75.0
    assert hc["pool_remaining_usd"] == 125.0


def test_holding_transfer_credits_company_wallet(client, flask_core, mint_token, admin_user):
    """The transfer writes a company ledger entry + bumps the wallet balance."""
    headers = _admin_headers(mint_token, admin_user)
    _fund_pool(client, headers, 150.0)
    ws = _seed_company(flask_core, admin_user, name="Wayne")
    resp = _transfer(client, headers, ws["_id"], 90.0)
    assert resp.status_code == 201, resp.text

    # Company-detail credits block: balance + lifetime topups reflect the move.
    credits = client.get(f"/api/admin/companies/{ws['_id']}", headers=headers).json()["credits"]
    assert credits["balance_field"] == 90.0
    assert credits["lifetime_topups_usd"] == 90.0


def test_holding_transfer_exact_pool(client, flask_core, mint_token, admin_user):
    """Transferring the entire remaining pool is allowed (amount == remaining)."""
    headers = _admin_headers(mint_token, admin_user)
    _fund_pool(client, headers, 50.0)
    ws = _seed_company(flask_core, admin_user)
    resp = _transfer(client, headers, ws["_id"], 50.0)
    assert resp.status_code == 201, resp.text
    assert resp.json()["holding_pool_remaining_usd"] == 0.0


def test_holding_transfer_sequential_debits(client, flask_core, mint_token, admin_user):
    """Two transfers accumulate on the transferred counter (response-body only)."""
    headers = _admin_headers(mint_token, admin_user)
    _fund_pool(client, headers, 300.0)
    ws = _seed_company(flask_core, admin_user)
    r1 = _transfer(client, headers, ws["_id"], 100.0)
    r2 = _transfer(client, headers, ws["_id"], 50.0)
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text
    assert r1.json()["holding_pool_remaining_usd"] == 200.0
    assert r2.json()["holding_pool_remaining_usd"] == 150.0
    # Wallet balance accumulated across both transfers.
    assert r2.json()["credits_balance_usd"] == 150.0


# ---------------------------------------------------------------------------
# source='holding' — short pool -> 402 + atomicity (no mutation).
# ---------------------------------------------------------------------------
def test_holding_transfer_short_pool_402_atomic(client, flask_core, mint_token, admin_user):
    headers = _admin_headers(mint_token, admin_user)
    _fund_pool(client, headers, 40.0)
    ws = _seed_company(flask_core, admin_user)

    resp = _transfer(client, headers, ws["_id"], 100.0)
    assert resp.status_code == 402, resp.text
    body = resp.json()
    assert body["code"] == "insufficient_credits"
    assert body["scope"] == "holding"
    assert body["remaining"] == 40.0
    assert body["limit"] == 40.0

    # ATOMICITY (single verify GET): nothing moved — pool intact, wallet empty.
    overview = client.get("/api/admin/holding/overview", headers=headers).json()
    hc = overview["holding_credits"]
    assert hc["transferred_usd"] == 0.0
    assert hc["pool_remaining_usd"] == 40.0
    credits = client.get(f"/api/admin/companies/{ws['_id']}", headers=headers).json()["credits"]
    assert credits["balance_field"] == 0.0
    assert credits["lifetime_topups_usd"] == 0.0


def test_holding_transfer_negative_amount_400_no_mutation(client, flask_core, mint_token, admin_user):
    """A negative holding transfer is rejected (400) BEFORE any mutation — it must
    not bypass the pool guard (-50 > 0 is False), drive the never-decrementing
    `transferred` counter negative, or push the company wallet below zero."""
    headers = _admin_headers(mint_token, admin_user)
    _fund_pool(client, headers, 200.0)
    ws = _seed_company(flask_core, admin_user, name="Soylent")

    resp = _transfer(client, headers, ws["_id"], -50.0)
    assert resp.status_code == 400, resp.text
    assert "positive" in resp.json()["error"]

    # Nothing moved: pool intact, transferred still 0, wallet untouched.
    hc = client.get("/api/admin/holding/overview", headers=headers).json()["holding_credits"]
    assert hc["transferred_usd"] == 0.0
    assert hc["pool_remaining_usd"] == 200.0
    credits = client.get(f"/api/admin/companies/{ws['_id']}", headers=headers).json()["credits"]
    assert credits["balance_field"] == 0.0


def test_holding_transfer_empty_pool_402(client, flask_core, mint_token, admin_user):
    """No pool funding at all -> any holding transfer 402s, scope=holding."""
    ws = _seed_company(flask_core, admin_user)
    resp = _transfer(client, headers=_admin_headers(mint_token, admin_user), wid=ws["_id"], amount=1.0)
    assert resp.status_code == 402
    body = resp.json()
    assert body["scope"] == "holding"
    assert body["code"] == "insufficient_credits"
    assert body["remaining"] == 0.0


def test_holding_transfer_workspace_not_found_404(client, flask_core, mint_token, admin_user):
    headers = _admin_headers(mint_token, admin_user)
    _fund_pool(client, headers, 100.0)
    resp = _transfer(client, headers, str(uuid.uuid4()), 10.0)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Workspace not found"


# ---------------------------------------------------------------------------
# Holding overview + ledger reflect transfers.
# ---------------------------------------------------------------------------
def test_overview_reflects_transferred_pool_remaining(client, flask_core, mint_token, admin_user):
    headers = _admin_headers(mint_token, admin_user)
    _fund_pool(client, headers, 500.0)
    ws = _seed_company(flask_core, admin_user)
    assert _transfer(client, headers, ws["_id"], 120.0).status_code == 201

    hc = client.get("/api/admin/holding/overview", headers=headers).json()["holding_credits"]
    assert hc["lifetime_topups_usd"] == 500.0
    assert hc["transferred_usd"] == 120.0
    assert hc["pool_remaining_usd"] == 380.0  # 500 - 120
    # Legacy advisory remaining (topups - usage) still present + untouched.
    assert "remaining_usd" in hc


def test_ledger_includes_transfer_rows(client, flask_core, mint_token, admin_user):
    headers = _admin_headers(mint_token, admin_user)
    # Route-driven top-up so the ledger (audit-sourced) sees the 'in' movement.
    _fund_pool(client, headers, 200.0, note="pool")
    ws = _seed_company(flask_core, admin_user, name="Initech")
    assert _transfer(client, headers, ws["_id"], 60.0, note="moved").status_code == 201

    body = client.get("/api/admin/holding/ledger", headers=headers).json()
    # Both the top-up (in) and the transfer (out) appear.
    assert body["total"] == 2
    by_dir = {e["direction"]: e for e in body["entries"]}
    assert "in" in by_dir and "out" in by_dir

    topup = by_dir["in"]
    assert topup["amount_usd"] == 200.0
    assert topup["action"] == "holding_credits_added"

    transfer = by_dir["out"]
    assert transfer["action"] == "company_credits_transferred"
    assert transfer["amount_usd"] == -60.0  # signed negative (leaves the pool)
    assert transfer["workspace_id"] == str(ws["_id"])
    assert transfer["workspace_name"] == "Initech"


def test_ledger_empty_when_no_movements(client, mint_token, admin_user):
    """No top-ups and no transfers -> the holding ledger is empty."""
    body = client.get("/api/admin/holding/ledger", headers=_admin_headers(mint_token, admin_user)).json()
    assert body["entries"] == []
    assert body["total"] == 0


def test_ledger_transfer_leads_topup_by_recency(client, flask_core, mint_token, admin_user):
    """Rows are time-desc: the later transfer (out) leads the earlier top-up (in)."""
    headers = _admin_headers(mint_token, admin_user)
    _fund_pool(client, headers, 300.0, note="pool")
    ws = _seed_company(flask_core, admin_user)
    assert _transfer(client, headers, ws["_id"], 100.0).status_code == 201

    body = client.get("/api/admin/holding/ledger", headers=headers).json()
    assert body["total"] == 2
    assert body["entries"][0]["direction"] == "out"  # most recent first
    assert body["entries"][1]["direction"] == "in"


# ---------------------------------------------------------------------------
# Transfer audit row.
# ---------------------------------------------------------------------------
def test_transfer_writes_audit_row(client, flask_core, mint_token, admin_user):
    headers = _admin_headers(mint_token, admin_user)
    _fund_pool(client, headers, 200.0)
    ws = _seed_company(flask_core, admin_user, name="Stark")
    assert _transfer(client, headers, ws["_id"], 75.0).status_code == 201

    # No admin audit endpoint in this router — verify the row directly via the
    # model. The transfer writes a category='holding' company_credits_transferred row.
    with flask_core.app_context():
        from app.models.audit_log import AuditLogModel
        rows = AuditLogModel.find_all(action="company_credits_transferred")
    matching = [r for r in rows if r.get("target_id") == str(ws["_id"])]
    assert len(matching) == 1
    event = matching[0]
    assert event["category"] == "holding"
    assert event["details"]["amount_usd"] == 75.0
    assert event["details"]["pool_remaining_after"] == 125.0
    assert event["details"]["workspace_name"] == "Stark"
