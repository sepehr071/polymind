"""DLP redact-mode wiring tests for the chat chokepoint (FastAPI bridge).

Asserts that when a workspace DLP policy is in ``mode='redact'``, a chat message
containing sensitive data (email / credit-card) is PERSISTED with typed
placeholders (``[EMAIL_1]`` / ``[CARD_1]``) — the raw value never lands in the
stored message content — and a ``dlp_events`` row with
``highest_action=='redact'`` is written.

External HTTP is never hit: the workspace policy leaves the smart-scan LLM
classifier disabled, an autouse monkeypatch hard-stops it anyway, and the
non-streaming ``chat_completion`` round-trip is stubbed so ``/send`` never calls
OpenRouter.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_openrouter(monkeypatch):
    # Smart-scan classifier never reaches the network.
    monkeypatch.setattr(
        "app.services.dlp_service.DLPDetector.llm_classify",
        lambda self, text, user_lang="en", *, user_id=None: None,
    )
    # Stub the non-streaming completion used by POST /api/chat/send so the
    # handler runs end-to-end (persist user msg -> LLM -> persist assistant msg)
    # without an HTTP call. Title generation also routes through a stub.
    def _fake_completion(*args, **kwargs):
        return {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(
        "app.services.openrouter_service.OpenRouterService.chat_completion",
        staticmethod(_fake_completion),
    )
    monkeypatch.setattr(
        "app.services.openrouter_service.OpenRouterService.generate_title",
        staticmethod(lambda *a, **k: "Title"),
    )
    yield


# ``strict`` admits low-severity builtin rules (email/phone) in addition to the
# high-severity ones (credit-card), so BOTH the email and the card are redacted.
# (``balanced`` floors at medium and would skip the low-severity email rule.)
_REDACT_POLICY = {"enabled": True, "sensitivity": "strict", "mode": "redact"}

# Deterministically trips builtin rules: a real email + a Luhn-valid test card.
_EMAIL = "john.doe@example.com"
_CARD = "4111 1111 1111 1111"
_MSG = f"contact me at {_EMAIL} and charge {_CARD} please"


def _seed_workspace(flask_core, owner_id, *, dlp):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Redact Co", owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, "owner", status="active")
        WorkspaceModel.update_settings_subkey(ws["_id"], "dlp", dlp)
        return WorkspaceModel.find_by_id(ws["_id"])


def _set_active_workspace(flask_core, user_id, workspace_id):
    from app.models.user import UserModel

    with flask_core.app_context():
        UserModel.update(user_id, {"active_workspace_id": workspace_id})


def _auth(mint_token, user, role="manager"):
    return {
        "Authorization": f"Bearer {mint_token(user['_id'], role=role)}",
        "Content-Type": "application/json",
    }


def _quick_config_id(flask_core):
    """Return a usable quick-model config id (resolves without a DB row)."""
    from app.utils.quick_models import QUICK_MODELS

    model_id = next(iter(QUICK_MODELS.keys()))
    return f"quick:{model_id}"


def test_send_redacts_email_and_card_in_workspace_redact_mode(
    client, flask_core, test_user, mint_token,
):
    ws = _seed_workspace(flask_core, test_user["_id"], dlp=_REDACT_POLICY)
    _set_active_workspace(flask_core, test_user["_id"], ws["_id"])
    config_id = _quick_config_id(flask_core)

    resp = client.post(
        "/api/chat/send",
        headers=_auth(mint_token, test_user),
        json={"message": _MSG, "config_id": config_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    conversation_id = body["conversation_id"]

    # The persisted user message must carry placeholders, NOT the raw values.
    from app.models.message import MessageModel

    with flask_core.app_context():
        messages = MessageModel.find_by_conversation(conversation_id)
    user_msgs = [m for m in messages if m.get("role") == "user"]
    assert len(user_msgs) == 1
    persisted = user_msgs[0]["content"]

    assert "[EMAIL_1]" in persisted
    assert "[CARD_1]" in persisted
    # Raw sensitive values must NOT be present in the stored content.
    assert _EMAIL not in persisted
    assert "4111" not in persisted

    # A redact-action DLP event was logged for the workspace.
    from app.models.dlp_event import DLPEventModel

    with flask_core.app_context():
        events, total = DLPEventModel.list_for_workspace(ws["_id"], source="chat")
    assert total >= 1
    assert any(e.get("highest_action") == "redact" for e in events)

    # A redaction badge is stamped on the message metadata for the UI.
    meta = user_msgs[0].get("metadata") or {}
    badge = meta.get("dlp_redacted")
    assert badge and badge.get("count", 0) >= 2
