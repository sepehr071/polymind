"""POST /api/dlp/scan redactability signalling tests (FastAPI bridge).

Regression for the bug where ``redactable`` / ``redacted_preview`` were gated on
``detector.redaction_enabled``: in ENFORCE mode the per-send "Redact & send"
affordance never appeared, and the client had no signal that a workspace was in
REDACT mode.

The endpoint must now return, REGARDLESS of mode:
  - ``redactable``: bool — any match has a spliceable (regex/custom) span.
  - ``redacted_preview``: str — the spliced preview (only when redactable).
  - ``auto_redact``: bool — True iff the workspace policy is in redact mode
    (server will auto-scrub on send, so the client should NOT show a block modal).

A Luhn-valid test card trips the high-severity ``credit_card`` builtin rule,
which yields a spliceable regex span -> ``redactable=True`` in BOTH modes.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_openrouter(monkeypatch):
    # Smart-scan classifier must never reach the network in tests.
    monkeypatch.setattr(
        "app.services.dlp_service.DLPDetector.llm_classify",
        lambda self, text, user_lang="en", *, user_id=None: None,
    )
    yield


# balanced (default) sensitivity admits the high-severity credit_card rule.
_ENFORCE_POLICY = {"enabled": True, "sensitivity": "balanced", "mode": "enforce"}
_REDACT_POLICY = {"enabled": True, "sensitivity": "balanced", "mode": "redact"}

_CARD = "4111 1111 1111 1111"
_MSG = f"please charge {_CARD} now"


def _seed_workspace(flask_core, owner_id, *, dlp):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Scan Co", owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, "owner", status="active")
        WorkspaceModel.update_settings_subkey(ws["_id"], "dlp", dlp)
        return WorkspaceModel.find_by_id(ws["_id"])


def _auth(mint_token, user, role="manager"):
    return {
        "Authorization": f"Bearer {mint_token(user['_id'], role=role)}",
        "Content-Type": "application/json",
    }


def _scan(client, mint_token, user, workspace_id):
    return client.post(
        "/api/dlp/scan",
        headers=_auth(mint_token, user),
        json={"text": _MSG, "workspace_id": workspace_id, "source": "chat"},
    )


def test_scan_enforce_mode_card_is_redactable_without_auto_redact(
    client, flask_core, test_user, mint_token,
):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_ENFORCE_POLICY)

    resp = _scan(client, mint_token, test_user, ws["_id"])
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # A spliceable card span is present even though the workspace is in enforce mode.
    assert body["redactable"] is True
    assert "[CARD_1]" in body["redacted_preview"]
    assert _CARD not in body["redacted_preview"]
    # Enforce mode: the server will NOT auto-scrub on send.
    assert body["auto_redact"] is False
    # The legacy result envelope is untouched.
    assert "result" in body
    assert body["result"]["highest_action"] in ("warn", "block")


def test_scan_redact_mode_card_is_redactable_with_auto_redact(
    client, flask_core, test_user, mint_token,
):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_REDACT_POLICY)

    resp = _scan(client, mint_token, test_user, ws["_id"])
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["redactable"] is True
    assert "[CARD_1]" in body["redacted_preview"]
    assert _CARD not in body["redacted_preview"]
    # Redact mode: the server WILL auto-scrub on send (client skips block modal).
    assert body["auto_redact"] is True
    assert "result" in body
