"""Backend coverage for the ChatGPT-parity fixes (2026-06-09).

Three concerns, mirroring the existing tests/api/** patterns (real model
facades on the isolated Postgres ``_test`` DB, the flask_ctx bridge, legacy
JSON shapes):

  A1  ``OpenRouterService._record_usage`` now captures image/total tokens so
      Image Studio rows persist nonzero ``usage_logs.total_tokens`` (was 0).
  A2  ``GET /api/admin/users`` attaches lifetime usage from ``usage_logs``
      (``usage_cost_usd`` / ``usage_tokens`` / ``usage_calls``) — not the
      chat-only ``User.usage`` JSONB counter.
  B2  ``POST /api/configs`` + ``PUT /api/configs/{id}`` DLP-gate the persona
      ``system_prompt`` at save → a critical match yields the global 403.

The DLP smart-scan classifier is never hit: the workspace policy these tests
create leaves the LLM classifier disabled, so DLPDetector.scan stays regex-only.
"""
import uuid

import pytest

from app.services.openrouter_service import OpenRouterService


# Deterministic critical-rule trip (AWS access key -> critical / block), shared
# with tests/api/test_dlp.py.
_AWS_KEY_TEXT = "deploy creds AKIAIOSFODNN7EXAMPLE rotate soon"
_DLP_ENABLED = {"enabled": True, "sensitivity": "balanced"}


@pytest.fixture(autouse=True)
def _no_openrouter_smart_scan(monkeypatch):
    """Belt-and-braces: even if a workspace enabled smart-scan, never network."""
    monkeypatch.setattr(
        "app.services.dlp_service.DLPDetector.llm_classify",
        lambda self, text, user_lang="en", *, user_id=None: None,
    )
    yield


# ---------------------------------------------------------------------------
# Seeding helpers.
# ---------------------------------------------------------------------------
def _seed_workspace(flask_core, owner_id, *, dlp=None):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Acme Co", owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, "owner", status="active")
        if dlp is not None:
            WorkspaceModel.update_settings_subkey(ws["_id"], "dlp", dlp)
        return WorkspaceModel.find_by_id(ws["_id"])


def _seed_project_via_api(client, headers, workspace_id, name="Alpha"):
    resp = client.post("/api/projects/create", headers=headers,
                       json={"workspace_id": str(workspace_id), "name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _latest_usage_row(flask_core):
    from app.api.core import db
    from app.models.usage_log import UsageLog
    with flask_core.app_context():
        return (db.session.query(UsageLog)
                .order_by(UsageLog.created_at.desc()).first())


# ===========================================================================
# A1 — _record_usage persists image/total tokens.
# ===========================================================================
def test_record_usage_image_path_persists_total_tokens(flask_core, test_user):
    """An image-gen style usage payload (image_tokens + total_tokens, no
    completion_tokens) must land nonzero total_tokens on the row."""
    usage = {
        "prompt_tokens": 12,
        "completion_tokens": 0,
        "image_tokens": 1290,
        "total_tokens": 1302,
        "cost": 0.04,
    }
    with flask_core.app_context():
        OpenRouterService._record_usage(
            test_user["_id"], None, "google/gemini-2.5-flash-image", usage,
            "image_generation", origin="web",
        )
    row = _latest_usage_row(flask_core)
    assert row is not None
    assert row.image_tokens == 1290
    assert row.total_tokens == 1302
    assert float(row.cost_usd) == pytest.approx(0.04)


def test_record_usage_total_tokens_derived_when_absent(flask_core, test_user):
    """When the payload omits total_tokens, it's derived as prompt+completion+image."""
    usage = {
        "prompt_tokens": 5,
        "completion_tokens": 0,
        "completion_tokens_details": {"image_tokens": 100},
        "cost": 0.01,
    }
    with flask_core.app_context():
        OpenRouterService._record_usage(
            test_user["_id"], None, "google/gemini-2.5-flash-image", usage,
            "image_generation",
        )
    row = _latest_usage_row(flask_core)
    assert row.image_tokens == 100
    assert row.total_tokens == 105  # 5 + 0 + 100


# ===========================================================================
# A2 — /api/admin/users attaches lifetime usage from usage_logs.
# ===========================================================================
def _seed_usage_row(flask_core, user_id, *, cost, total_tokens, image_tokens=0):
    from app.models.usage_log import UsageLogModel
    with flask_core.app_context():
        UsageLogModel.create(
            user_id=user_id, model="google/gemini-2.5-flash-image",
            prompt_tokens=0, completion_tokens=0, image_tokens=image_tokens,
            total_tokens=total_tokens, cost_usd=cost, feature="image_generation",
            origin="web",
        )


def test_get_users_includes_usage_fields(client, admin_headers, admin_user, plain_user, flask_core):
    # plain_user used Image Studio twice: tokens live ONLY in usage_logs.
    _seed_usage_row(flask_core, plain_user["_id"], cost=0.04, total_tokens=1302, image_tokens=1290)
    _seed_usage_row(flask_core, plain_user["_id"], cost=0.02, total_tokens=650, image_tokens=640)

    resp = client.get("/api/admin/users", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    by_id = {u["_id"]: u for u in resp.json()["users"]}

    plain = by_id[str(plain_user["_id"])]
    # New contract fields present on every row.
    assert "usage_cost_usd" in plain
    assert "usage_tokens" in plain
    assert "usage_calls" in plain
    assert plain["usage_cost_usd"] == pytest.approx(0.06)
    assert plain["usage_tokens"] == 1952  # 1302 + 650
    assert plain["usage_calls"] == 2

    # A user with no usage_logs rows reports zeros (not missing keys).
    admin = by_id[str(admin_user["_id"])]
    assert admin["usage_cost_usd"] == 0.0
    assert admin["usage_tokens"] == 0
    assert admin["usage_calls"] == 0


def test_get_users_usage_jsonb_blob_preserved(client, admin_headers, admin_user, plain_user):
    """The legacy User.usage JSONB blob is still emitted alongside the new fields."""
    resp = client.get("/api/admin/users", headers=admin_headers)
    assert resp.status_code == 200
    rows = resp.json()["users"]
    assert all("usage" in u for u in rows)
    assert all("usage_tokens" in u for u in rows)


# ===========================================================================
# A4 — /api/admin/usage accepts an optional user_id filter.
# ===========================================================================
def test_admin_usage_user_id_filter_scopes_to_one_user(
    client, admin_headers, admin_user, plain_user, flask_core
):
    _seed_usage_row(flask_core, plain_user["_id"], cost=0.05, total_tokens=500)
    _seed_usage_row(flask_core, admin_user["_id"], cost=0.10, total_tokens=900)

    # Global (no user_id) sees both rows' cost.
    glob = client.get("/api/admin/usage?group_by=user", headers=admin_headers)
    assert glob.status_code == 200, glob.text
    assert glob.json()["total_cost"] == pytest.approx(0.15)

    # Scoped to plain_user sees only its spend.
    scoped = client.get(
        f"/api/admin/usage?group_by=feature&user_id={plain_user['_id']}",
        headers=admin_headers,
    )
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()["total_cost"] == pytest.approx(0.05)


# ===========================================================================
# B2 — persona system_prompt DLP gate at save (create + update -> 403).
# ===========================================================================
def test_create_config_critical_system_prompt_blocked_403(
    client, auth_headers, test_user, flask_core
):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_DLP_ENABLED)
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    pid = project["_id"] if "_id" in project else project.get("id")

    resp = client.post("/api/configs", headers=auth_headers, json={
        "name": "Leaky Persona", "model_id": "openai/gpt-5",
        "project_id": str(pid),
        "system_prompt": f"You are an assistant. {_AWS_KEY_TEXT}",
    })
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["code"] == "dlp_blocked"
    assert any(m["rule_id"] == "aws_access_key" for m in body["matches"])


def test_create_config_clean_system_prompt_ok(
    client, auth_headers, test_user, flask_core
):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_DLP_ENABLED)
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    pid = project["_id"] if "_id" in project else project.get("id")

    resp = client.post("/api/configs", headers=auth_headers, json={
        "name": "Clean Persona", "model_id": "openai/gpt-5",
        "project_id": str(pid),
        "system_prompt": "You are a friendly, concise assistant.",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["config"]["system_prompt"] == "You are a friendly, concise assistant."


def test_update_config_critical_system_prompt_blocked_403(
    client, auth_headers, test_user, flask_core
):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_DLP_ENABLED)
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    pid = project["_id"] if "_id" in project else project.get("id")

    created = client.post("/api/configs", headers=auth_headers, json={
        "name": "Persona", "model_id": "openai/gpt-5", "project_id": str(pid),
        "system_prompt": "You are a friendly assistant.",
    })
    assert created.status_code == 201, created.text
    cfg_id = created.json()["config"]["_id"]

    resp = client.put(f"/api/configs/{cfg_id}", headers=auth_headers, json={
        "system_prompt": f"Updated. {_AWS_KEY_TEXT}",
    })
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "dlp_blocked"


def test_create_config_no_workspace_no_gate(client, plain_headers):
    """Personal-scope config for a user with no active workspace: gate is a
    no-op (gate_redactable returns clean when workspace_id is None) — create
    still succeeds even with text that WOULD trip a rule under a policy."""
    resp = client.post("/api/configs", headers=plain_headers, json={
        "name": "Personal", "model_id": "openai/gpt-5",
        "system_prompt": f"Notes: {_AWS_KEY_TEXT}",
    })
    assert resp.status_code == 201, resp.text
