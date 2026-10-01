"""POST /api/dlp/scan with attachment upload_ids — file text joins the scan.

Covers:
  * owned upload with a builtin secret → match even when message is clean
  * foreign upload_id is ignored (no IDOR text leak into scan)
  * empty message + attachment text is allowed
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setattr(
        "app.services.dlp_service.DLPDetector.llm_classify",
        lambda self, text, user_lang="en", *, user_id=None: None,
    )
    yield


_ENFORCE = {"enabled": True, "sensitivity": "balanced", "mode": "enforce"}
_CARD = "4111 1111 1111 1111"


def _seed_workspace(flask_core, owner_id, *, dlp):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Attach DLP Co", owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, "owner", status="active")
        WorkspaceModel.update_settings_subkey(ws["_id"], "dlp", dlp)
        return WorkspaceModel.find_by_id(ws["_id"])


def _auth(mint_token, user, role="manager"):
    return {
        "Authorization": f"Bearer {mint_token(user['_id'], role=role)}",
        "Content-Type": "application/json",
    }


def _make_upload(flask_core, user_id, *, text, name="secret.txt"):
    from app.models.upload import UploadModel

    with flask_core.app_context():
        return UploadModel.create(
            user_id=user_id,
            filename=f"f-{name}",
            original_name=name,
            mime_type="text/plain",
            size=len(text.encode("utf-8")),
            type="document",
            extracted_text=text,
            extracted_chars=len(text),
            extraction_status="ok",
        )


def test_scan_joins_owned_attachment_text(
    client, flask_core, test_user, mint_token,
):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_ENFORCE)
    up = _make_upload(
        flask_core, test_user["_id"],
        text=f"please charge {_CARD} from the sheet",
        name="secret.txt",
    )

    resp = client.post(
        "/api/dlp/scan",
        headers=_auth(mint_token, test_user),
        json={
            "text": "please summarize this file",
            "workspace_id": ws["_id"],
            "source": "chat",
            "attachments": [{"upload_id": up["_id"]}],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    result = body["result"]
    assert result["matches"], "expected card match from attachment text"
    assert result["highest_action"] in ("block", "warn")
    assert body["redactable"] is True


def test_scan_empty_message_with_attachment_ok(
    client, flask_core, test_user, mint_token,
):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_ENFORCE)
    up = _make_upload(
        flask_core, test_user["_id"],
        text=f"invoice {_CARD}",
        name="inv.csv",
    )

    resp = client.post(
        "/api/dlp/scan",
        headers=_auth(mint_token, test_user),
        json={
            "text": "",
            "workspace_id": ws["_id"],
            "source": "chat",
            "attachments": [{"upload_id": up["_id"]}],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["matches"]


def test_scan_foreign_upload_id_ignored(
    client, flask_core, test_user, plain_user, mint_token,
):
    """Victim's secret upload must not be readable via attacker's scan body."""
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_ENFORCE)
    victim_up = _make_upload(
        flask_core, plain_user["_id"],
        text=f"secret card {_CARD}",
        name="victim.txt",
    )

    resp = client.post(
        "/api/dlp/scan",
        headers=_auth(mint_token, test_user),
        json={
            "text": "please summarize",  # clean message
            "workspace_id": ws["_id"],
            "source": "chat",
            "attachments": [{"upload_id": victim_up["_id"]}],
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    # Foreign extracted_text must not enter the scan → no card match.
    assert not result.get("matches") or result.get("highest_action") in (None, "allow")


def test_scan_rejects_empty_without_attachments(
    client, flask_core, test_user, mint_token,
):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_ENFORCE)
    resp = client.post(
        "/api/dlp/scan",
        headers=_auth(mint_token, test_user),
        json={"text": "   ", "workspace_id": ws["_id"], "source": "chat"},
    )
    assert resp.status_code == 400
