"""Coverage tests for app/api/routers/dlp.py + app/services/holding_analytics.py.

Mirrors tests/api/test_dlp.py (dedicated dlp_app mounting just the DLP router at
/api + the autouse smart-scan no-op) and tests/api/test_admin.py / test_platform.py
(real model facades on Postgres inside flask_core.app_context()).

This file targets the SPECIFIC uncovered line ranges reported in .cov_missing.json
that the existing test_dlp.py / test_platform.py do NOT exercise:

  dlp.py:
    - _json_body garbage/non-dict body (62-63)
    - _verify_dlp_token every failure branch (145, 150-151, 154, 159, 164, 166, 168-170)
    - _sweep_inactive_buckets (195-201)
    - _validate_custom_pattern branches (290-315)
    - _validate_llm_classifier branches (324-352)
    - _build_policy_payload branches (379-463): mode, rule_overrides type/value,
      custom_patterns list-type/empty-skip/text-normalise/regex, hostname suffixes,
      llm_classifier merge, notify_owners
    - dlp/test workspace validation (612, 614)
    - get/update policy not-found + invalid id (644, 663, 667)
    - list events skip/limit non-int (716-717)
    - admin list days param + skip/limit non-int (855-859, 864-865)
    - admin patch event validation + not-found (914-940)

  holding_analytics.py: drive the FULL aggregation paths (NOT the empty early
  returns the platform tests hit) by seeding workspaces + members + projects +
  conversations + usage_logs + credit_ledger + holding audit_logs, then calling
  list_companies / company_detail / users_overview / holding_overview /
  holding_ledger directly inside an app_context.

No external HTTP is ever hit (smart-scan is monkeypatched + DLP policies leave
the LLM classifier disabled; analytics are pure DB).
"""
import uuid as _uuid

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from app.api.errors import install_exception_handlers
from app.api.routers.dlp import router as dlp_router


# ---------------------------------------------------------------------------
# Dedicated app/client for the DLP router (same as test_dlp.py).
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


@pytest.fixture(autouse=True)
def _no_openrouter(monkeypatch):
    monkeypatch.setattr(
        "app.services.dlp_service.DLPDetector.llm_classify",
        lambda self, text, user_lang="en", *, user_id=None: None,
    )
    yield


# ---------------------------------------------------------------------------
# Seed helpers (mirror test_dlp.py).
# ---------------------------------------------------------------------------
def _seed_workspace(flask_core, owner_id, *, role="owner", dlp=None, name="Acme Co"):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, role, status="active")
        if dlp is not None:
            WorkspaceModel.update_settings_subkey(ws["_id"], "dlp", dlp)
        return WorkspaceModel.find_by_id(ws["_id"])


_DLP_ENABLED = {"enabled": True, "sensitivity": "balanced"}
_SSN_TEXT = "my national id is 0076229645 please keep it safe"


# ===========================================================================
# _json_body — garbage / non-dict bodies (lines 62-63, also 64 fallthrough).
# ===========================================================================
def test_scan_garbage_body_treated_as_empty(dlp_client, auth_headers):
    # Invalid JSON -> request.json() raises -> _json_body returns {} -> 400 on
    # missing text (exercises the except branch at 62-63).
    headers = dict(auth_headers)
    resp = dlp_client.post("/api/dlp/scan", headers=headers, content=b"not-json-at-all")
    assert resp.status_code == 400
    assert resp.json()["error"] == "text is required"


def test_scan_json_array_body_treated_as_empty(dlp_client, auth_headers):
    # A JSON array is valid JSON but not a dict -> _json_body returns {} (line 64).
    resp = dlp_client.post("/api/dlp/scan", headers=auth_headers, json=[1, 2, 3])
    assert resp.status_code == 400
    assert resp.json()["error"] == "text is required"


# ===========================================================================
# _verify_dlp_token — every failure branch (pure function, app_context).
# ===========================================================================
def test_verify_dlp_token_all_failure_branches(flask_core):
    from app.api.routers.dlp import _sign_dlp_token
    from app.services.dlp_tokens import _verify_dlp_token
    import time as _t

    with flask_core.app_context():
        # 144-145: empty / non-string / no-dot token.
        assert _verify_dlp_token("", text_sha256="x", user_id="u", workspace_id="w") is False
        assert _verify_dlp_token("nodothere", text_sha256="x", user_id="u", workspace_id="w") is False

        # 150-151: undecodable base64 halves (still has a dot).
        assert _verify_dlp_token("!!!.@@@", text_sha256="x", user_id="u", workspace_id="w") is False

        # 154: HMAC mismatch — valid b64 structure, wrong signature.
        bad = "aaaa.bbbb"
        assert _verify_dlp_token(bad, text_sha256="x", user_id="u", workspace_id="w") is False

        sha = "a" * 64
        exp = int(_t.time()) + 300
        good = _sign_dlp_token(f"{sha}|user1|ws1|{exp}")

        # 159: payload has wrong number of '|' parts -> bad signed payload.
        wrong_parts = _sign_dlp_token("only|three|parts")
        assert _verify_dlp_token(wrong_parts, text_sha256="x", user_id="user1",
                                 workspace_id="ws1") is False

        # 161-162 (t_sha mismatch).
        assert _verify_dlp_token(good, text_sha256="DIFFERENT", user_id="user1",
                                 workspace_id="ws1") is False
        # 163-164 (uid mismatch).
        assert _verify_dlp_token(good, text_sha256=sha, user_id="other",
                                 workspace_id="ws1") is False
        # 165-166 (wid mismatch).
        assert _verify_dlp_token(good, text_sha256=sha, user_id="user1",
                                 workspace_id="otherws") is False

        # 167-168 (expired token).
        expired = _sign_dlp_token(f"{sha}|user1|ws1|{int(_t.time()) - 10}")
        assert _verify_dlp_token(expired, text_sha256=sha, user_id="user1",
                                 workspace_id="ws1") is False

        # 169-170 (non-integer exp -> int() raises -> caught).
        nonint = _sign_dlp_token(f"{sha}|user1|ws1|notanint")
        assert _verify_dlp_token(nonint, text_sha256=sha, user_id="user1",
                                 workspace_id="ws1") is False

        # Happy path proves the helper is otherwise sound + wid='' (falsy) branch.
        ok = _sign_dlp_token(f"{sha}|user1||{exp}")
        assert _verify_dlp_token(ok, text_sha256=sha, user_id="user1",
                                 workspace_id=None) is True


# ===========================================================================
# _sweep_inactive_buckets + rate-limit drop branch (195-201, 217-218, 223).
# ===========================================================================
def test_sweep_inactive_buckets_drops_stale(flask_core):
    from collections import deque
    import time as _t
    from app.api.routers import dlp as dlp_mod

    with flask_core.app_context():
        dlp_mod._scan_rate.clear()
        now = _t.monotonic()
        # An empty deque -> stale.
        dlp_mod._scan_rate["empty"] = deque()
        # A deque whose newest entry is older than 2*window -> stale.
        old = deque()
        old.append(now - (3 * dlp_mod._RATE_LIMIT_WINDOW))
        dlp_mod._scan_rate["old"] = old
        # A fresh deque -> kept.
        fresh = deque()
        fresh.append(now)
        dlp_mod._scan_rate["fresh"] = fresh

        dlp_mod._sweep_inactive_buckets(now)

        assert "empty" not in dlp_mod._scan_rate
        assert "old" not in dlp_mod._scan_rate
        assert "fresh" in dlp_mod._scan_rate
        dlp_mod._scan_rate.clear()


def test_check_rate_limit_window_drop_and_trip(flask_core):
    from collections import deque
    import time as _t
    from app.api.routers import dlp as dlp_mod

    with flask_core.app_context():
        dlp_mod._scan_rate.clear()
        uid = "ratelimit-unit"
        now = _t.monotonic()
        dq = deque()
        # One entry well outside the window -> popped on next check (222-223).
        dq.append(now - (dlp_mod._RATE_LIMIT_WINDOW + 100))
        # Fill the rest of the window to MAX so the next call trips (225-228).
        for _ in range(dlp_mod._RATE_LIMIT_MAX):
            dq.append(now)
        dlp_mod._scan_rate[uid] = dq

        retry = dlp_mod._check_rate_limit(uid)
        assert isinstance(retry, int) and retry >= 1
        dlp_mod._scan_rate.clear()


def test_sweep_triggered_by_counter(flask_core):
    from app.api.routers import dlp as dlp_mod

    with flask_core.app_context():
        dlp_mod._scan_rate.clear()
        # Push the sweep counter to the trigger threshold; the next _check_rate_limit
        # runs _sweep_inactive_buckets (215-218).
        dlp_mod._sweep_counter = dlp_mod._SWEEP_EVERY_N - 1
        dlp_mod._check_rate_limit("counter-unit")
        assert dlp_mod._sweep_counter == 0
        dlp_mod._scan_rate.clear()


# ===========================================================================
# _validate_custom_pattern — every error branch (290-315).
# ===========================================================================
def test_validate_custom_pattern_branches(flask_core):
    from app.api.routers.dlp import _validate_custom_pattern as v

    with flask_core.app_context():
        # 289-290: not a dict.
        assert "must be an object" in v("nope", 0)
        # 292-293: empty name.
        assert "name must be a non-empty" in v({"name": "   "}, 1)
        # 295-296: bad match_type.
        assert "match_type must be" in v({"name": "n", "match_type": "fuzzy"}, 2)
        # 297-300: text match_type with empty text.
        assert "text must be a non-empty" in v(
            {"name": "n", "match_type": "text", "text": "  "}, 3)
        # 303-304: regex match_type with empty regex.
        assert "regex must be a non-empty" in v(
            {"name": "n", "match_type": "regex", "regex": ""}, 4)
        # 306-308: invalid regex compile.
        assert "regex is invalid" in v(
            {"name": "n", "match_type": "regex", "regex": "("}, 5)
        # 309-311: bad severity.
        assert "severity must be one of" in v(
            {"name": "n", "match_type": "regex", "regex": "x", "severity": "nope"}, 6)
        # 312-314: bad action.
        assert "action must be one of" in v(
            {"name": "n", "match_type": "regex", "regex": "x", "severity": "high",
             "action": "nope"}, 7)
        # 315: valid -> None.
        assert v({"name": "n", "match_type": "text", "text": "secret",
                  "severity": "high", "action": "warn"}, 8) is None


# ===========================================================================
# _validate_llm_classifier — every branch (324-352).
# ===========================================================================
def test_validate_llm_classifier_branches(flask_core):
    from app.api.routers.dlp import _validate_llm_classifier as v
    from app.services.dlp_service import dlp_locked_model

    with flask_core.app_context():
        # 324-325: not a dict.
        clean, err = v("nope")
        assert clean is None and err == "llm_classifier must be an object"

        # 332-334: guidance_prompt too long.
        clean, err = v({"guidance_prompt": "x" * 4001})
        assert clean is None and "4000 characters" in err

        # 337-339: action_thresholds not a dict.
        clean, err = v({"action_thresholds": "nope"})
        assert clean is None and "action_thresholds must be an object" in err

        # confidential may tighten to block. allow is rejected.
        # require_confirm is coerced to block, not rejected.
        clean, err = v({"action_thresholds": {"confidential": "allow"}})
        assert clean is None and "confidential must be one of" in err
        clean, err = v({"action_thresholds": {"confidential": "require_confirm"}})
        assert err is None and clean["action_thresholds"]["confidential"] == "block"
        clean, err = v({"action_thresholds": {"restricted": "require_confirm"}})
        assert err is None and clean["action_thresholds"]["restricted"] == "block"

        # 347-349: bad restricted value.
        clean, err = v({"action_thresholds": {"restricted": "nonsense"}})
        assert clean is None and "restricted must be one of" in err

        # Full happy path: model is force-locked (329-330), enabled coerced (327-328),
        # guidance kept, both thresholds valid (341-352).
        clean, err = v({
            "enabled": "yes",
            "model": "client/tries/to/override",
            "guidance_prompt": "be careful",
            "action_thresholds": {"confidential": "warn", "restricted": "block"},
        })
        assert err is None
        assert clean["model"] == dlp_locked_model()
        assert clean["enabled"] is True
        assert clean["guidance_prompt"] == "be careful"
        assert clean["action_thresholds"] == {"confidential": "warn", "restricted": "block"}


# ===========================================================================
# _build_policy_payload — branches not covered by test_dlp.py (379-463).
# ===========================================================================
def test_build_policy_payload_mode_and_collections(flask_core):
    from app.api.routers.dlp import _build_policy_payload as b

    with flask_core.app_context():
        # 378-382: bad mode value.
        clean, err = b({"mode": "explode"})
        assert clean is None and "mode must be one of" in err
        # mode falsy -> defaults to enforce.
        clean, err = b({"mode": ""})
        assert err is None and clean["mode"] == "enforce"

        # 386-387: rule_overrides not a dict.
        clean, err = b({"rule_overrides": ["x"]})
        assert clean is None and "rule_overrides must be an object" in err
        # 389-391: bad override action value.
        clean, err = b({"rule_overrides": {"some_rule": "explode"}})
        assert clean is None and "must be one of" in err
        # 400/416: unknown (custom) rule_id bypasses the floor -> accepted.
        clean, err = b({"rule_overrides": {"my_custom_rule": "warn"}})
        assert err is None and clean["rule_overrides"] == {"my_custom_rule": "warn"}

        # 420-421: custom_patterns not a list.
        clean, err = b({"custom_patterns": {"nope": 1}})
        assert clean is None and "custom_patterns must be an array" in err

        # 429-430: an empty/abandoned row is SKIPPED (no text/regex value).
        clean, err = b({"custom_patterns": [
            {"name": "blank", "match_type": "text", "text": "   "},
        ]})
        assert err is None and clean["custom_patterns"] == []

        # 434-451: text pattern normalised (regex synthesised) + regex pattern kept.
        clean, err = b({"custom_patterns": [
            {"name": "  Phrase  ", "match_type": "text", "text": "  topsecret  ",
             "severity": "high", "action": "warn"},
            {"name": "Rx", "match_type": "regex", "regex": "foo[0-9]+",
             "severity": "medium", "action": "warn"},
        ]})
        assert err is None
        pats = clean["custom_patterns"]
        assert len(pats) == 2
        text_pat = next(p for p in pats if p["name"] == "Phrase")
        assert text_pat["text"] == "topsecret"
        assert text_pat["regex"].startswith("(?i)")
        assert "topsecret" in text_pat["regex"]
        rx_pat = next(p for p in pats if p["name"] == "Rx")
        assert rx_pat["regex"] == "foo[0-9]+"

        # 442-444: invalid (non-empty) custom pattern aborts the whole save.
        clean, err = b({"custom_patterns": [
            {"name": "bad", "match_type": "regex", "regex": "(",
             "severity": "high", "action": "warn"},
        ]})
        assert clean is None and "regex is invalid" in err

        # 453-457: internal_hostname_suffixes type-check + filter falsy.
        clean, err = b({"internal_hostname_suffixes": "nope"})
        assert clean is None and "internal_hostname_suffixes must be an array" in err
        clean, err = b({"internal_hostname_suffixes": ["  .corp  ", "", None, ".int"]})
        assert err is None
        assert clean["internal_hostname_suffixes"] == [".corp", ".int"]

        # 459-463: llm_classifier merge (error path + happy path).
        clean, err = b({"llm_classifier": "nope"})
        assert clean is None and "llm_classifier must be an object" in err
        clean, err = b({"llm_classifier": {"enabled": True}})
        assert err is None and clean["llm_classifier"]["enabled"] is True

        # 465-466: notify_owners coercion.
        clean, err = b({"notify_owners": 1})
        assert err is None and clean["notify_owners"] is True


# ===========================================================================
# dlp/test — workspace validation branches (612, 614).
# ===========================================================================
def test_dlp_test_missing_workspace_400(dlp_client, auth_headers):
    resp = dlp_client.post("/api/dlp/test", headers=auth_headers, json={"text": "hi"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "workspace_id is required"


def test_dlp_test_invalid_workspace_400(dlp_client, auth_headers):
    resp = dlp_client.post("/api/dlp/test", headers=auth_headers, json={
        "text": "hi", "workspace_id": "not-a-uuid",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace_id"


# ===========================================================================
# get/update policy — workspace not found + invalid id (644, 663, 667).
# admin short-circuits the workspace_member gate so the handler body runs.
# ===========================================================================
def test_get_policy_workspace_not_found_404(dlp_client, admin_headers):
    resp = dlp_client.get(f"/api/workspaces/{_uuid.uuid4()}/dlp/policy",
                          headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Workspace not found"


def test_update_policy_invalid_wid_400(dlp_client, admin_headers):
    resp = dlp_client.put("/api/workspaces/not-a-uuid/dlp/policy",
                          headers=admin_headers, json={"enabled": True})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace ID"


def test_update_policy_workspace_not_found_404(dlp_client, admin_headers):
    resp = dlp_client.put(f"/api/workspaces/{_uuid.uuid4()}/dlp/policy",
                          headers=admin_headers, json={"enabled": True})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Workspace not found"


def test_update_policy_with_custom_patterns_and_mode_persists(dlp_client, flask_core, test_user, auth_headers):
    # Exercises the full _build_policy_payload happy path through the route +
    # merge-with-existing + persist (677-684) with rich fields.
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    resp = dlp_client.put(f"/api/workspaces/{ws['_id']}/dlp/policy", headers=auth_headers, json={
        "enabled": True,
        "mode": "redact",
        "custom_patterns": [
            {"name": "Codeword", "match_type": "text", "text": "bluefalcon",
             "severity": "high", "action": "warn"},
        ],
        "internal_hostname_suffixes": [".corp"],
        "llm_classifier": {"enabled": False},
        "notify_owners": True,
    })
    assert resp.status_code == 200, resp.text
    policy = resp.json()["policy"]
    assert policy["mode"] == "redact"
    assert policy["notify_owners"] is True


# ===========================================================================
# list events — skip/limit non-int (716-717).
# ===========================================================================
def test_list_events_bad_skip_limit_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    resp = dlp_client.get(
        f"/api/workspaces/{ws['_id']}/dlp/events?skip=abc&limit=def",
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "skip and limit must be integers"


def test_get_single_event_invalid_wid_400(dlp_client, admin_headers):
    # admin short-circuits gate; invalid wid hits 753-754.
    resp = dlp_client.get(f"/api/workspaces/not-a-uuid/dlp/events/{_uuid.uuid4()}",
                          headers=admin_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace ID"


def test_patch_event_invalid_wid_400(dlp_client, admin_headers):
    resp = dlp_client.patch(f"/api/workspaces/not-a-uuid/dlp/events/{_uuid.uuid4()}",
                            headers=admin_headers, json={"status": "reviewed"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace ID"


def test_patch_event_invalid_event_id_400(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    resp = dlp_client.patch(
        f"/api/workspaces/{ws['_id']}/dlp/events/not-a-uuid",
        headers=auth_headers, json={"status": "reviewed"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid event ID"


def test_patch_event_not_found_404(dlp_client, flask_core, test_user, auth_headers):
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    resp = dlp_client.patch(
        f"/api/workspaces/{ws['_id']}/dlp/events/{_uuid.uuid4()}",
        headers=auth_headers, json={"status": "reviewed"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_workspace_stats_invalid_wid_400(dlp_client, admin_headers):
    resp = dlp_client.get("/api/workspaces/not-a-uuid/dlp/stats", headers=admin_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid workspace ID"


# ===========================================================================
# admin list events — extra filter / pagination branches (844, 855-865).
# ===========================================================================
def test_admin_list_events_invalid_user_filter_400(dlp_client, admin_headers):
    resp = dlp_client.get("/api/admin/dlp/events?user_id=not-a-uuid", headers=admin_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid user_id filter"


def test_admin_list_events_days_param(dlp_client, admin_headers):
    # days param without `from` -> computes from_dt (854-859).
    resp = dlp_client.get("/api/admin/dlp/events?days=14", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert "rows" in resp.json()


def test_admin_list_events_bad_days_400(dlp_client, admin_headers):
    resp = dlp_client.get("/api/admin/dlp/events?days=notanint", headers=admin_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "days must be an integer"


def test_admin_list_events_bad_skip_limit_400(dlp_client, admin_headers):
    resp = dlp_client.get("/api/admin/dlp/events?skip=x&limit=y", headers=admin_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "skip and limit must be integers"


def test_admin_list_events_with_filters_ok(dlp_client, admin_headers):
    # All filter args present + valid -> 881 region (find_all called).
    resp = dlp_client.get(
        "/api/admin/dlp/events?severity=critical&source=chat&status=blocked"
        "&action=block&skip=0&limit=10",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text


# ===========================================================================
# admin PATCH event — validation + update + not-found (914-940).
# ===========================================================================
def test_admin_patch_event_invalid_id_400(dlp_client, admin_headers):
    resp = dlp_client.patch("/api/admin/dlp/events/not-a-uuid",
                            headers=admin_headers, json={"status": "reviewed"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid event ID"


def test_admin_patch_event_missing_status_400(dlp_client, admin_headers):
    resp = dlp_client.patch(f"/api/admin/dlp/events/{_uuid.uuid4()}",
                            headers=admin_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "status is required"


def test_admin_patch_event_bad_status_400(dlp_client, admin_headers):
    resp = dlp_client.patch(f"/api/admin/dlp/events/{_uuid.uuid4()}",
                            headers=admin_headers, json={"status": "nonsense"})
    assert resp.status_code == 400
    assert "status must be one of" in resp.json()["error"]


def test_admin_patch_event_not_found_404(dlp_client, admin_headers):
    # Valid UUID, but no such event -> update_review returns None -> 937-940.
    resp = dlp_client.patch(f"/api/admin/dlp/events/{_uuid.uuid4()}",
                            headers=admin_headers, json={"status": "reviewed"})
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_admin_patch_event_updates(dlp_client, flask_core, test_user, admin_user, admin_headers):
    from app.models.dlp_event import DLPEventModel
    ws = _seed_workspace(flask_core, test_user["_id"], role="owner")
    with flask_core.app_context():
        ev = DLPEventModel.create(
            user_id=test_user["_id"], workspace_id=ws["_id"], project_id=None,
            source="chat", source_ref={"preflight": True},
            matches=[{"rule_id": "aws_access_key", "rule_name": "AWS",
                      "severity": "critical", "action": "block", "snippet": "***",
                      "offset_start": 0, "offset_end": 3}],
            highest_action="block", was_sent=False, text_sha256="b" * 64, text_length=10,
        )
    resp = dlp_client.patch(f"/api/admin/dlp/events/{ev['_id']}",
                            headers=admin_headers,
                            json={"status": "dismissed", "note": "false positive"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["event"]["_id"] == str(ev["_id"])


# ===========================================================================
# holding_analytics — FULL aggregation paths.
# ===========================================================================
def _seed_full_company(flask_core, owner, *, name, member, with_conv=True, with_usage=True):
    """Seed a team workspace with: an active member, a project, a conversation,
    usage_logs, and a credit-ledger entry. Returns the workspace dict."""
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel
    from app.models.project import ProjectModel
    from app.models.conversation import ConversationModel
    from app.models.usage_log import UsageLogModel
    from app.models.credit_ledger import CreditLedgerModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner["_id"], type="team")
        wid = ws["_id"]
        # Two active members so member_counts aggregates a real value.
        WorkspaceMemberModel.add(wid, owner["_id"], "owner", status="active")
        WorkspaceMemberModel.add(wid, member["_id"], "editor", status="active")

        proj = ProjectModel.create(workspace_id=wid, name="Proj A", created_by=owner["_id"])
        pid = proj["_id"]

        if with_conv:
            ConversationModel.create(
                user_id=owner["_id"], config_id=None, title="conv",
                project_id=pid,
            )

        if with_usage:
            # Owner (admin/manager role) + member (user role) usage so by_role
            # aggregation has multiple buckets.
            UsageLogModel.create(
                user_id=owner["_id"], workspace_id=wid, project_id=pid,
                model="openai/gpt-5", prompt_tokens=100, completion_tokens=50,
                cost_usd=1.25, origin="web",
            )
            UsageLogModel.create(
                user_id=member["_id"], workspace_id=wid, project_id=pid,
                model="anthropic/claude", prompt_tokens=200, completion_tokens=80,
                cost_usd=0.50, origin="web",
            )

        # A holding/company credit ledger entry with a real added_by user, so the
        # recent_ledger user_map lookup executes (343-348).
        CreditLedgerModel.create(
            workspace_id=wid, delta_micro_usd=10_000_000, kind="topup",
            ref={"note": "seed top up"}, created_by_user_id=owner["_id"],
        )
        return WorkspaceModel.find_by_id(wid)


def test_list_companies_full_aggregation(flask_core, admin_user, plain_user):
    from app.services import holding_analytics as ha

    ws = _seed_full_company(flask_core, admin_user, name="Globex", member=plain_user)
    with flask_core.app_context():
        out = ha.list_companies(days=30)

    assert out["days"] == 30
    row = next(c for c in out["companies"] if c["_id"] == str(ws["_id"]))
    # Members (72/81), projects, conversations (91), usage rollup (107).
    assert row["member_count"] == 2
    assert row["project_count"] == 1
    assert row["conversation_count"] == 1
    assert row["usage_30d"]["calls"] == 2
    assert round(row["usage_30d"]["cost_usd"], 2) == 1.75
    # Totals are summed across companies.
    assert out["totals"]["companies"] >= 1
    assert out["totals"]["members"] >= 2
    assert round(out["totals"]["cost_30d"], 2) >= 1.75
    assert out["totals"]["credits_balance_usd"] >= 0.0


def test_company_detail_full_aggregation(flask_core, admin_user, plain_user):
    from app.services import holding_analytics as ha

    ws = _seed_full_company(flask_core, admin_user, name="Initech", member=plain_user)
    with flask_core.app_context():
        out = ha.company_detail(ws["_id"], days=14)

    assert out is not None
    assert out["workspace"]["_id"] == str(ws["_id"])
    assert out["days"] == 14
    assert out["member_count"] == 2
    assert out["project_count"] == 1
    # project_rows + usage (169/182/186-197).
    assert out["projects"] and out["projects"][0]["calls"] >= 1
    # top_users hydrated with email/role (213-237).
    assert out["top_users"] and any(u["email"] for u in out["top_users"])
    # top_models (252).
    assert out["top_models"] and out["top_models"][0]["calls"] >= 1
    # by_role buckets summed (287-290).
    assert "admin" in out["by_role"] and "user" in out["by_role"]
    # daily fill produces exactly `days` entries (312-322).
    assert len(out["daily"]) == 14
    # credits block + recent_ledger hydrated with added_by (325-365).
    assert out["credits"]["lifetime_topups_usd"] >= 10.0
    assert out["recent_ledger"] and out["recent_ledger"][0]["added_by"]["email"]


def test_company_detail_invalid_and_missing(flask_core):
    from app.services import holding_analytics as ha

    with flask_core.app_context():
        # 33/35: _maybe_uuid(None) -> None -> early return.
        assert ha.company_detail(None) is None
        # _maybe_uuid garbage string -> None -> early return.
        assert ha.company_detail("not-a-uuid") is None
        # Valid UUID, no workspace -> None (workspace lookup miss).
        assert ha.company_detail(str(_uuid.uuid4())) is None


def test_users_overview_full(flask_core, admin_user, plain_user):
    from app.services import holding_analytics as ha

    _seed_full_company(flask_core, admin_user, name="UO Co", member=plain_user)
    with flask_core.app_context():
        # No filters -> matched users + usage rollup + ws_counts (422/425/428/437/456).
        out = ha.users_overview(days=30)
        assert out["total"] >= 2
        assert out["totals"]["users"] >= 2
        top = out["users"][0]
        assert top["cost_usd"] >= 0.0
        assert top["workspaces_count"] >= 1

        # role filter path (419-422).
        out_admin = ha.users_overview(days=30, role="admin")
        assert all(u["role"] == "admin" for u in out_admin["users"])

        # search path matching the seeded admin email (423-432).
        out_search = ha.users_overview(days=30, search="admin@gmail.com")
        assert any(u["email"] == "admin@gmail.com" for u in out_search["users"])

        # search that matches nobody -> empty early return (436-440).
        out_none = ha.users_overview(days=30, search="zzz-no-such-user-zzz")
        assert out_none["total"] == 0 and out_none["users"] == []


def test_users_overview_invalid_role_raises(flask_core):
    from app.services import holding_analytics as ha

    with flask_core.app_context():
        with pytest.raises(ValueError):
            ha.users_overview(role="superhero")


def test_holding_overview_full(flask_core, admin_user, plain_user):
    from app.services import holding_analytics as ha

    _seed_full_company(flask_core, admin_user, name="HO Co", member=plain_user)
    with flask_core.app_context():
        out = ha.holding_overview(days=10)

    assert out["workspaces_count"] >= 1
    assert out["projects_count"] >= 1
    assert out["users_count"] >= 2
    assert out["conversations_count"] >= 1
    # CEO resolved (admin role exists) -> 531-536.
    assert out["ceo"] and out["ceo"]["email"] == "admin@gmail.com"
    assert out["totals"]["calls"] >= 2
    assert len(out["daily"]) == 10
    # top_companies hydrated with workspace name/domain (592-615).
    assert out["top_companies"] and out["top_companies"][0]["calls"] >= 1
    # top_models (629).
    assert out["top_models"] and out["top_models"][0]["calls"] >= 1
    # by_role buckets (664-672).
    assert "admin" in out["by_role"] and "user" in out["by_role"]
    assert "holding_credits" in out


def test_holding_ledger_full(flask_core, admin_user):
    from app.services import holding_analytics as ha
    from app.models.audit_log import AuditLogModel

    with flask_core.app_context():
        # Holding ledger now reads audit_logs WHERE category='holding'; the actor
        # is a super-admin's users.id (admin_user), hydrated from the users table.
        AuditLogModel.create(
            action="holding_credits_added",
            admin_id=admin_user["_id"],
            category="holding",
            details={"amount_usd": 500.0, "type": "top_up", "note": "Q1 budget"},
        )
        out = ha.holding_ledger(skip=0, limit=10)

    assert out["total"] >= 1
    entry = out["entries"][0]
    assert entry["amount_usd"] == 500.0
    assert entry["type"] == "top_up"
    assert entry["note"] == "Q1 budget"
    # Actor metadata hydrated from the super-admin's users row.
    assert entry["added_by"]["email"] == "admin@gmail.com"
