"""Integration tests for the FastAPI DLP router (app/api/routers/dlp.py).

Mirrors tests/api/test_auth.py — uses the shared conftest fixtures
(client/auth_headers/admin_headers/plain_headers/mint_token/user factories +
the autouse truncate_all). The router is not yet wired into asgi.app (a later
serialized step does that), so we build a dedicated test app that mounts just
the DLP router at /api with the same exception handlers as asgi.py.

External HTTP is never hit: the workspace DLP policies these tests create leave
the LLM smart-scan classifier disabled (default), so DLPDetector.scan never
calls OpenRouter. A belt-and-braces monkeypatch on the smart-scan entrypoint is
applied autouse so any accidental enablement still can't reach the network.
"""
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from app.api.errors import install_exception_handlers
from app.api.routers.dlp import router as dlp_router


# ---------------------------------------------------------------------------
# Dedicated app/client for the DLP router (asgi.app doesn't mount it yet).
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def dlp_app(_pg_engine):
    application = FastAPI(default_response_class=JSONResponse)
    install_exception_handlers(application)
    application.include_router(dlp_router, prefix="/api")
    return application


@pytest.fixture(scope="function")
def dlp_client(dlp_app):
    with TestClient(dlp_app) as c:
        yield c


# ---------------------------------------------------------------------------
# Never let the smart-scan classifier reach the network, even if a test enables
# it. DLPDetector.llm_classify already returns None when disabled; this guards
# accidental enablement.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_openrouter(monkeypatch):
    monkeypatch.setattr(
        "app.services.dlp_service.DLPDetector.llm_classify",
        lambda self, text, user_lang="en", *, user_id=None: None,
    )
    yield


# ---------------------------------------------------------------------------
# Seed helpers — build a workspace owned by `user` with an active owner
# membership and (optionally) an enabled DLP policy.
# ---------------------------------------------------------------------------
def _seed_workspace(flask_core, owner_id, *, role="owner", dlp=None):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Acme Co", owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, role, status="active")
        if dlp is not None:
            WorkspaceModel.update_settings_subkey(ws["_id"], "dlp", dlp)
        # Re-fetch to get the merged settings.
        return WorkspaceModel.find_by_id(ws["_id"])


# Text fixtures that deterministically trip builtin rules:
#   AWS access key    -> critical / block
#   Iran national ID  -> high / block
_AWS_KEY_TEXT = "deploy creds AKIAIOSFODNN7EXAMPLE rotate soon"
_SSN_TEXT = "my national id is 0076229645 please keep it safe"

_DLP_ENABLED = {"enabled": True, "sensitivity": "balanced"}


# ===========================================================================
# /api/dlp/scan
# ===========================================================================
def test_scan_no_matches_returns_result(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_DLP_ENABLED)
    resp = dlp_client.post("/api/dlp/scan", headers=auth_headers, json={
        "text": "hello world, nothing sensitive here",
        "workspace_id": str(ws["_id"]),
        "source": "chat",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["highest_action"] == "allow"
    assert body["result"]["matches"] == []
    assert body["event_id"] is None
    assert "confirm_token" not in body


def test_scan_block_persists_event_no_confirm_token(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_DLP_ENABLED)
    resp = dlp_client.post("/api/dlp/scan", headers=auth_headers, json={
        "text": _AWS_KEY_TEXT,
        "workspace_id": str(ws["_id"]),
        "source": "chat",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["highest_action"] == "block"
    assert any(m["rule_id"] == "aws_access_key" for m in body["result"]["matches"])
    # Block-level pre-flight persists an event so dashboards see the attempt.
    assert body["event_id"] is not None
    # Block is non-overridable — no confirm_token minted.
    assert "confirm_token" not in body


def test_scan_national_id_is_block_without_confirm_token(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_DLP_ENABLED)
    resp = dlp_client.post("/api/dlp/scan", headers=auth_headers, json={
        "text": _SSN_TEXT,
        "workspace_id": str(ws["_id"]),
        "source": "chat",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["highest_action"] == "block"
    assert body["event_id"] is not None
    assert "confirm_token" not in body
    assert "confirm_token_exp" not in body


def test_scan_missing_text_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_DLP_ENABLED)
    resp = dlp_client.post("/api/dlp/scan", headers=auth_headers, json={
        "workspace_id": str(ws["_id"]),
        "source": "chat",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "text is required"


def test_scan_missing_workspace_400(dlp_client, auth_headers):
    resp = dlp_client.post("/api/dlp/scan", headers=auth_headers, json={
        "text": "hi", "source": "chat",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "workspace_id is required"


def test_scan_invalid_workspace_id_400(dlp_client, auth_headers):
    resp = dlp_client.post("/api/dlp/scan", headers=auth_headers, json={
        "text": "hi", "workspace_id": "not-a-uuid", "source": "chat",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace_id"


def test_scan_missing_source_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_DLP_ENABLED)
    resp = dlp_client.post("/api/dlp/scan", headers=auth_headers, json={
        "text": "hi", "workspace_id": str(ws["_id"]),
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "source is required"


def test_scan_no_workspace_access_403(dlp_client, flask_core, test_user, plain_user, auth_headers):
    # Workspace owned by plain_user; test_user (auth_headers) is NOT a member.
    ws = _seed_workspace(flask_core, plain_user["_id"], dlp=_DLP_ENABLED)
    resp = dlp_client.post("/api/dlp/scan", headers=auth_headers, json={
        "text": "hi", "workspace_id": str(ws["_id"]), "source": "chat",
    })
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "Workspace access denied"
    assert body["code"] == "forbidden"


def test_scan_no_token_401(dlp_client, flask_core, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_DLP_ENABLED)
    resp = dlp_client.post("/api/dlp/scan", json={
        "text": "hi", "workspace_id": str(ws["_id"]), "source": "chat",
    })
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_scan_banned_user_403(dlp_client, flask_core, banned_user, mint_token):
    ws = _seed_workspace(flask_core, banned_user["_id"], dlp=_DLP_ENABLED)
    headers = {"Authorization": f"Bearer {mint_token(banned_user['_id'], role='user')}"}
    resp = dlp_client.post("/api/dlp/scan", headers=headers, json={
        "text": "hi", "workspace_id": str(ws["_id"]), "source": "chat",
    })
    assert resp.status_code == 403
    assert resp.json()["error"] == "Account has been suspended"


def test_scan_rate_limit_429_with_retry_after(dlp_client, flask_core, test_user, auth_headers):
    # The limiter is a module-level deque keyed by user_id; clear it first so a
    # prior test in the same worker didn't seed timestamps.
    from app.api.routers import dlp as dlp_mod
    dlp_mod._scan_rate.clear()

    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_DLP_ENABLED)
    payload = {"text": "hello there", "workspace_id": str(ws["_id"]), "source": "chat"}

    # 60 calls are allowed in the window; the 61st trips the limiter.
    last = None
    for _ in range(dlp_mod._RATE_LIMIT_MAX + 1):
        last = dlp_client.post("/api/dlp/scan", headers=auth_headers, json=payload)
    assert last.status_code == 429, last.text
    body = last.json()
    assert body["error"] == "rate_limited"
    assert body["retry_after"] >= 1
    assert int(last.headers["Retry-After"]) >= 1
    dlp_mod._scan_rate.clear()


# ===========================================================================
# /api/dlp/test (owner-only playground)
# ===========================================================================
def test_dlp_test_owner_runs_scan(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_DLP_ENABLED, role="owner")
    resp = dlp_client.post("/api/dlp/test", headers=auth_headers, json={
        "text": _AWS_KEY_TEXT,
        "workspace_id": str(ws["_id"]),
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["highest_action"] == "block"
    # No event persisted by /dlp/test — only the scan result is returned.
    assert "event_id" not in body


def test_dlp_test_non_owner_403(dlp_client, flask_core, test_user, auth_headers):
    # Viewer membership only — /dlp/test requires owner.
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_DLP_ENABLED, role="viewer")
    resp = dlp_client.post("/api/dlp/test", headers=auth_headers, json={
        "text": "hi", "workspace_id": str(ws["_id"]),
    })
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_dlp_test_missing_text_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    resp = dlp_client.post("/api/dlp/test", headers=auth_headers, json={
        "workspace_id": str(ws["_id"]),
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "text is required"


# ===========================================================================
# /api/workspaces/{wid}/dlp/policy
# ===========================================================================
def test_get_policy_returns_policy_and_catalog(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_DLP_ENABLED, role="viewer")
    resp = dlp_client.get(f"/api/workspaces/{ws['_id']}/dlp/policy", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["policy"]["enabled"] is True
    assert body["policy"]["sensitivity"] == "balanced"
    # Locked smart-scan model surfaces in the effective policy.
    assert body["policy"]["llm_classifier"]["model"] == "google/gemini-3.5-flash-lite"
    assert isinstance(body["rule_catalog"], list) and body["rule_catalog"]
    assert all({"id", "name", "severity", "default_action", "category"} <= set(r)
               for r in body["rule_catalog"])


def test_get_policy_invalid_wid_400(dlp_client, admin_headers):
    # admin role short-circuits the workspace_member gate, so the handler runs
    # and validates the (garbage) wid.
    resp = dlp_client.get("/api/workspaces/not-a-uuid/dlp/policy", headers=admin_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace ID"


def test_get_policy_no_membership_403(dlp_client, flask_core, plain_user, auth_headers):
    ws = _seed_workspace(flask_core, plain_user["_id"], dlp=_DLP_ENABLED)
    resp = dlp_client.get(f"/api/workspaces/{ws['_id']}/dlp/policy", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Workspace access denied"


def test_get_policy_no_token_401(dlp_client, flask_core, test_user):
    ws = _seed_workspace(flask_core, test_user["_id"])
    resp = dlp_client.get(f"/api/workspaces/{ws['_id']}/dlp/policy")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_update_policy_owner_persists(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    resp = dlp_client.put(f"/api/workspaces/{ws['_id']}/dlp/policy", headers=auth_headers, json={
        "enabled": True,
        "sensitivity": "strict",
        "notify_owners": False,
    })
    assert resp.status_code == 200, resp.text
    policy = resp.json()["policy"]
    assert policy["enabled"] is True
    assert policy["sensitivity"] == "strict"
    assert policy["notify_owners"] is False

    # Persisted — a follow-up GET reflects it.
    again = dlp_client.get(f"/api/workspaces/{ws['_id']}/dlp/policy", headers=auth_headers)
    assert again.json()["policy"]["sensitivity"] == "strict"


def test_update_policy_unknown_key_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    resp = dlp_client.put(f"/api/workspaces/{ws['_id']}/dlp/policy", headers=auth_headers, json={
        "enabled": True, "bogus_key": 1,
    })
    assert resp.status_code == 400
    assert "Unknown policy key" in resp.json()["error"]


def test_update_policy_bad_sensitivity_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    resp = dlp_client.put(f"/api/workspaces/{ws['_id']}/dlp/policy", headers=auth_headers, json={
        "sensitivity": "paranoid",
    })
    assert resp.status_code == 400
    assert "sensitivity must be one of" in resp.json()["error"]


def test_update_policy_rule_override_floor_violation_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    # aws_access_key is critical -> floor 'block'; loosening to 'warn' is rejected
    # with a structured violation payload.
    resp = dlp_client.put(f"/api/workspaces/{ws['_id']}/dlp/policy", headers=auth_headers, json={
        "rule_overrides": {"aws_access_key": "warn"},
    })
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "rule_override_below_floor"
    assert body["violations"][0]["rule_id"] == "aws_access_key"
    assert body["violations"][0]["min_action"] == "block"


def test_update_policy_invalid_custom_regex_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    resp = dlp_client.put(f"/api/workspaces/{ws['_id']}/dlp/policy", headers=auth_headers, json={
        "custom_patterns": [
            {"name": "bad", "match_type": "regex", "regex": "(", "severity": "high", "action": "warn"},
        ],
    })
    assert resp.status_code == 400
    assert "regex is invalid" in resp.json()["error"]


def test_update_policy_non_owner_403(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="viewer")
    resp = dlp_client.put(f"/api/workspaces/{ws['_id']}/dlp/policy", headers=auth_headers, json={
        "enabled": True,
    })
    assert resp.status_code == 403
    assert resp.json()["error"] == "Workspace access denied"


# ===========================================================================
# /api/workspaces/{wid}/dlp/events  (+ single GET/PATCH)
# ===========================================================================
def _seed_event(flask_core, *, user_id, workspace_id, action="block", source="chat"):
    from app.models.dlp_event import DLPEventModel

    with flask_core.app_context():
        return DLPEventModel.create(
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=None,
            source=source,
            source_ref={"preflight": True},
            matches=[{
                "rule_id": "aws_access_key", "rule_name": "AWS Access Key",
                "severity": "critical", "action": action,
                "snippet": "***", "offset_start": 0, "offset_end": 3,
            }],
            highest_action=action,
            was_sent=False,
            text_sha256="a" * 64,
            text_length=42,
        )


def test_list_events_owner(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    _seed_event(flask_core, user_id=test_user["_id"], workspace_id=ws["_id"])
    resp = dlp_client.get(f"/api/workspaces/{ws['_id']}/dlp/events", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["limit"] == 50 and body["skip"] == 0
    assert len(body["rows"]) == 1
    # Legacy _id alias is preserved on the serialized event.
    assert body["rows"][0]["_id"]
    assert body["rows"][0]["highest_action"] == "block"


def test_list_events_invalid_user_filter_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    resp = dlp_client.get(
        f"/api/workspaces/{ws['_id']}/dlp/events?user_id=not-a-uuid",
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid user_id filter"


def test_list_events_non_owner_403(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="viewer")
    resp = dlp_client.get(f"/api/workspaces/{ws['_id']}/dlp/events", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Workspace access denied"


def test_get_single_event_owner(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    event = _seed_event(flask_core, user_id=test_user["_id"], workspace_id=ws["_id"])
    resp = dlp_client.get(
        f"/api/workspaces/{ws['_id']}/dlp/events/{event['_id']}", headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["event"]["_id"] == str(event["_id"])


def test_get_single_event_wrong_workspace_404(dlp_client, flask_core, test_user, plain_user, auth_headers):
    ws_owned = _seed_workspace(flask_core, test_user["_id"], role="owner")
    ws_other = _seed_workspace(flask_core, plain_user["_id"])
    # Event belongs to ws_other, queried under ws_owned -> 404.
    event = _seed_event(flask_core, user_id=plain_user["_id"], workspace_id=ws_other["_id"])
    resp = dlp_client.get(
        f"/api/workspaces/{ws_owned['_id']}/dlp/events/{event['_id']}", headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_get_single_event_invalid_event_id_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    resp = dlp_client.get(
        f"/api/workspaces/{ws['_id']}/dlp/events/not-a-uuid", headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid event ID"


def test_patch_event_updates_status(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    event = _seed_event(flask_core, user_id=test_user["_id"], workspace_id=ws["_id"])
    resp = dlp_client.patch(
        f"/api/workspaces/{ws['_id']}/dlp/events/{event['_id']}",
        headers=auth_headers,
        json={"status": "reviewed", "review_note": "looks intentional"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["event"]["_id"] == str(event["_id"])
    assert body["event"]["review_note"] == "looks intentional"


def test_patch_event_missing_status_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    event = _seed_event(flask_core, user_id=test_user["_id"], workspace_id=ws["_id"])
    resp = dlp_client.patch(
        f"/api/workspaces/{ws['_id']}/dlp/events/{event['_id']}",
        headers=auth_headers, json={},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "status is required"


def test_patch_event_bad_status_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    event = _seed_event(flask_core, user_id=test_user["_id"], workspace_id=ws["_id"])
    resp = dlp_client.patch(
        f"/api/workspaces/{ws['_id']}/dlp/events/{event['_id']}",
        headers=auth_headers, json={"status": "nonsense"},
    )
    assert resp.status_code == 400
    assert "status must be one of" in resp.json()["error"]


# ===========================================================================
# /api/workspaces/{wid}/dlp/stats
# ===========================================================================
def test_workspace_stats_owner(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    _seed_event(flask_core, user_id=test_user["_id"], workspace_id=ws["_id"])
    resp = dlp_client.get(f"/api/workspaces/{ws['_id']}/dlp/stats", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert "by_severity" in body and "by_source" in body
    assert "daily" in body and "top_rules" in body


def test_workspace_stats_bad_days_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    resp = dlp_client.get(
        f"/api/workspaces/{ws['_id']}/dlp/stats?days=abc", headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "days must be an integer"


def test_workspace_stats_non_owner_403(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="viewer")
    resp = dlp_client.get(f"/api/workspaces/{ws['_id']}/dlp/stats", headers=auth_headers)
    assert resp.status_code == 403


# ===========================================================================
# /api/admin/dlp/*  (admin-required)
# ===========================================================================
def test_admin_list_events(dlp_client, flask_core, admin_user, test_user, admin_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    _seed_event(flask_core, user_id=test_user["_id"], workspace_id=ws["_id"])
    resp = dlp_client.get("/api/admin/dlp/events", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert body["rows"] and body["rows"][0]["_id"]


def test_admin_list_events_non_admin_403(dlp_client, plain_headers):
    resp = dlp_client.get("/api/admin/dlp/events", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Admin access required"


def test_admin_list_events_manager_403(dlp_client, auth_headers):
    # auth_headers = manager role; /admin requires admin specifically.
    resp = dlp_client.get("/api/admin/dlp/events", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Admin access required"


def test_admin_list_events_invalid_workspace_filter_400(dlp_client, admin_headers):
    resp = dlp_client.get(
        "/api/admin/dlp/events?workspace_id=not-a-uuid", headers=admin_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace_id filter"


def test_admin_get_event(dlp_client, flask_core, admin_user, test_user, admin_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    event = _seed_event(flask_core, user_id=test_user["_id"], workspace_id=ws["_id"])
    resp = dlp_client.get(f"/api/admin/dlp/events/{event['_id']}", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["event"]["_id"] == str(event["_id"])


def test_admin_get_event_missing_404(dlp_client, flask_core, admin_user, admin_headers):
    import uuid as _uuid
    resp = dlp_client.get(f"/api/admin/dlp/events/{_uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_admin_get_event_invalid_id_400(dlp_client, admin_headers):
    resp = dlp_client.get("/api/admin/dlp/events/not-a-uuid", headers=admin_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid event ID"


def test_admin_stats(dlp_client, flask_core, admin_user, test_user, admin_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    _seed_event(flask_core, user_id=test_user["_id"], workspace_id=ws["_id"])
    resp = dlp_client.get("/api/admin/dlp/stats", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert "by_action" in body and "top_workspaces" in body


def test_admin_stats_non_admin_403(dlp_client, plain_headers):
    resp = dlp_client.get("/api/admin/dlp/stats", headers=plain_headers)
    assert resp.status_code == 403


# ===========================================================================
# Route-registration smoke.
# ===========================================================================
def test_dlp_routes_registered(dlp_app):
    paths = {getattr(r, "path", None) for r in dlp_app.routes}
    assert "/api/dlp/scan" in paths
    assert "/api/dlp/test" in paths
    assert "/api/workspaces/{wid}/dlp/policy" in paths
    assert "/api/workspaces/{wid}/dlp/events" in paths
    assert "/api/workspaces/{wid}/dlp/events/{event_id}" in paths
    assert "/api/workspaces/{wid}/dlp/stats" in paths
    assert "/api/admin/dlp/events" in paths
    assert "/api/admin/dlp/events/{event_id}" in paths
    assert "/api/admin/dlp/stats" in paths
