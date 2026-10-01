"""POST /api/workspaces/{wid}/dlp/enhance-guidance — OpenRouter rewrite (mocked)."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_openrouter(monkeypatch):
    def _fake(*args, **kwargs):
        return {
            "choices": [{
                "message": {
                    "content": (
                        "Flag AURORA-7 as restricted. "
                        "Generic launch talk without that codename is public."
                    )
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }

    monkeypatch.setattr(
        "app.services.openrouter_service.OpenRouterService.chat_completion",
        staticmethod(_fake),
    )
    monkeypatch.setattr(
        "app.services.spend_gate.gate",
        lambda **kwargs: None,
    )
    yield


def _seed_workspace(flask_core, owner_id):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Enhance Co", owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, "owner", status="active")
        return WorkspaceModel.find_by_id(ws["_id"])


def _auth(mint_token, user, role="manager"):
    return {
        "Authorization": f"Bearer {mint_token(user['_id'], role=role)}",
        "Content-Type": "application/json",
    }


def test_enhance_guidance_happy(client, flask_core, test_user, mint_token):
    ws = _seed_workspace(flask_core, test_user["_id"])
    resp = client.post(
        f"/api/workspaces/{ws['_id']}/dlp/enhance-guidance",
        headers=_auth(mint_token, test_user),
        json={"prompt": "dont share AURORA-7", "lang": "en"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "AURORA-7" in body["enhanced_prompt"]


def test_enhance_guidance_empty_400(client, flask_core, test_user, mint_token):
    ws = _seed_workspace(flask_core, test_user["_id"])
    resp = client.post(
        f"/api/workspaces/{ws['_id']}/dlp/enhance-guidance",
        headers=_auth(mint_token, test_user),
        json={"prompt": "   "},
    )
    assert resp.status_code == 400


def test_enhance_guidance_viewer_forbidden(
    client, flask_core, test_user, plain_user, mint_token,
):
    ws = _seed_workspace(flask_core, test_user["_id"])
    # Add plain_user as viewer only
    from app.models.workspace_member import WorkspaceMemberModel
    with flask_core.app_context():
        WorkspaceMemberModel.add(ws["_id"], plain_user["_id"], "viewer", status="active")

    resp = client.post(
        f"/api/workspaces/{ws['_id']}/dlp/enhance-guidance",
        headers=_auth(mint_token, plain_user, role="user"),
        json={"prompt": "flag payroll sheets"},
    )
    assert resp.status_code == 403
