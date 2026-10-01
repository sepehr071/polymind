"""Integration tests for the FastAPI chat router (app/api/routers/chat.py).

Translated from app/routes/chat.py + app/routes/chat_stream.py. Exercises the
full bridge path: TestClient -> flask_ctx app_context (worker thread) -> real
ConversationModel / MessageModel / LLMConfigModel facades on Postgres ->
legacy-shaped JSON.

External HTTP (OpenRouter) is mocked at the service boundary
(``OpenRouterService.chat_completion`` / ``generate_title``) so no test hits a
real upstream. The DLP gate short-circuits in tests because the seeded users
have ``active_workspace_id=None`` (gate returns None when workspace_id is
falsy), so no DLP LLM call fires either.
"""
import json

import pytest

from app.services.openrouter_service import OpenRouterService

# A canned non-streaming OpenRouter response.
_FAKE_COMPLETION = {
    "choices": [{
        "message": {"content": "Hello from the model"},
        "finish_reason": "stop",
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


def _fake_chat_completion(*args, **kwargs):
    """Stand-in for OpenRouterService.chat_completion.

    Returns a generator of SSE-shaped chunk dicts when stream=True, else the
    canned completion dict.
    """
    if kwargs.get("stream"):
        def _gen():
            yield {"choices": [{"delta": {"content": "Hello "}}]}
            yield {"choices": [{"delta": {"content": "world"}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
            yield {"done": True}
        return _gen()
    return dict(_FAKE_COMPLETION)


@pytest.fixture(autouse=True)
def _mock_openrouter(monkeypatch):
    """Patch every OpenRouter network entrypoint the chat router can hit."""
    monkeypatch.setattr(OpenRouterService, "chat_completion",
                        staticmethod(_fake_chat_completion))
    monkeypatch.setattr(OpenRouterService, "generate_title",
                        staticmethod(lambda *a, **k: "Generated Title"))
    yield


# ---------------------------------------------------------------------------
# Seeding helpers (real facades inside an app_context).
# ---------------------------------------------------------------------------
def _seed_config(flask_core, owner_id):
    from app.models.llm_config import LLMConfigModel

    with flask_core.app_context():
        return LLMConfigModel.create(
            name="Test Config",
            model_id="openai/gpt-4o-mini",
            model_name="GPT-4o mini",
            owner_id=owner_id,
            system_prompt="You are a test bot.",
        )


def _seed_conversation(flask_core, user_id, config_id):
    from app.models.conversation import ConversationModel

    with flask_core.app_context():
        return ConversationModel.create(
            user_id=user_id,
            config_id=config_id,
            title="Seeded conversation",
        )


def _seed_user_message(flask_core, conversation_id, content="hi there"):
    from app.models.message import MessageModel

    with flask_core.app_context():
        return MessageModel.create_user_message(
            conversation_id=conversation_id,
            content=content,
        )


def _seed_assistant_message(flask_core, conversation_id, content="answer"):
    from app.models.message import MessageModel

    with flask_core.app_context():
        return MessageModel.create_assistant_message(
            conversation_id=conversation_id,
            content=content,
            model_id="openai/gpt-4o-mini",
        )


# ---------------------------------------------------------------------------
# POST /send — non-streaming.
# ---------------------------------------------------------------------------
def test_send_creates_conversation_and_returns_messages(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    resp = client.post("/api/chat/send", headers=auth_headers, json={
        "config_id": str(config["_id"]),
        "message": "Hello there",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["conversation_id"]
    assert body["is_new_conversation"] is True
    # Legacy _id alias on persisted entities.
    assert body["user_message"]["_id"]
    assert body["user_message"]["role"] == "user"
    assert body["assistant_message"]["_id"]
    assert body["assistant_message"]["role"] == "assistant"
    assert body["assistant_message"]["content"] == "Hello from the model"


def test_send_with_quick_model(client, auth_headers):
    resp = client.post("/api/chat/send", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite",
        "message": "Quick question",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["assistant_message"]["content"] == "Hello from the model"


def test_send_missing_message_400(client, auth_headers):
    resp = client.post("/api/chat/send", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Message content is required"


def test_send_missing_config_400(client, auth_headers):
    resp = client.post("/api/chat/send", headers=auth_headers, json={
        "message": "Hello",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "config_id is required"


def test_send_unknown_config_404(client, auth_headers):
    import uuid

    resp = client.post("/api/chat/send", headers=auth_headers, json={
        "config_id": str(uuid.uuid4()),
        "message": "Hello",
    })
    assert resp.status_code == 404
    assert resp.json()["error"] == "Config not found"


def test_send_no_token_401(client):
    resp = client.post("/api/chat/send", json={
        "config_id": "quick:google/gemini-3.5-flash-lite", "message": "x",
    })
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_send_banned_user_403(client, banned_user, mint_token):
    headers = {"Authorization": f"Bearer {mint_token(banned_user['_id'], role='user')}"}
    resp = client.post("/api/chat/send", headers=headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite", "message": "x",
    })
    assert resp.status_code == 403
    assert resp.json()["error"] == "Account has been suspended"


def test_send_other_users_conversation_404(client, auth_headers, plain_user, flask_core):
    # A conversation owned by a DIFFERENT user must be invisible.
    config = _seed_config(flask_core, plain_user["_id"])
    conv = _seed_conversation(flask_core, plain_user["_id"], str(config["_id"]))
    resp = client.post("/api/chat/send", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite",
        "conversation_id": str(conv["_id"]),
        "message": "intrusion",
    })
    assert resp.status_code == 404
    assert resp.json()["error"] == "Conversation not found"


# ---------------------------------------------------------------------------
# GET /{conversation_id}/messages.
# ---------------------------------------------------------------------------
def test_get_messages_happy(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    _seed_user_message(flask_core, str(conv["_id"]), "first message")

    resp = client.get(f"/api/chat/{conv['_id']}/messages", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["branch_id"] == "main"
    assert body["messages"][0]["_id"]
    assert body["messages"][0]["content"] == "first message"


def test_get_messages_other_user_404(client, auth_headers, plain_user, flask_core):
    config = _seed_config(flask_core, plain_user["_id"])
    conv = _seed_conversation(flask_core, plain_user["_id"], str(config["_id"]))
    resp = client.get(f"/api/chat/{conv['_id']}/messages", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Conversation not found"


def test_get_messages_no_token_401(client, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    resp = client.get(f"/api/chat/{conv['_id']}/messages")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# DELETE /messages/{message_id}.
# ---------------------------------------------------------------------------
def test_delete_message_happy(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    msg = _seed_user_message(flask_core, str(conv["_id"]))

    resp = client.delete(f"/api/chat/messages/{msg['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Message deleted"


def test_delete_message_unknown_404(client, auth_headers):
    import uuid

    resp = client.delete(f"/api/chat/messages/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Message not found"


def test_delete_message_other_user_404(client, auth_headers, plain_user, flask_core):
    config = _seed_config(flask_core, plain_user["_id"])
    conv = _seed_conversation(flask_core, plain_user["_id"], str(config["_id"]))
    msg = _seed_user_message(flask_core, str(conv["_id"]))
    resp = client.delete(f"/api/chat/messages/{msg['_id']}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Message not found"


# ---------------------------------------------------------------------------
# PUT /messages/{message_id} — edit (+ optional regenerate).
# ---------------------------------------------------------------------------
def test_edit_message_invalid_id_400(client, auth_headers):
    resp = client.put("/api/chat/messages/temp-123456", headers=auth_headers, json={
        "content": "new content",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid message ID format"


def test_edit_message_missing_content_400(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    msg = _seed_user_message(flask_core, str(conv["_id"]))
    resp = client.put(f"/api/chat/messages/{msg['_id']}", headers=auth_headers, json={
        "content": "   ",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Content is required"


def test_edit_message_unknown_404(client, auth_headers):
    import uuid

    resp = client.put(f"/api/chat/messages/{uuid.uuid4()}", headers=auth_headers, json={
        "content": "new content", "regenerate": False,
    })
    assert resp.status_code == 404
    assert resp.json()["error"] == "Message not found"


def test_edit_assistant_message_rejected_400(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    msg = _seed_assistant_message(flask_core, str(conv["_id"]))
    resp = client.put(f"/api/chat/messages/{msg['_id']}", headers=auth_headers, json={
        "content": "new content", "regenerate": False,
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Only user messages can be edited"


def test_edit_message_no_regenerate(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    msg = _seed_user_message(flask_core, str(conv["_id"]), "original")
    resp = client.put(f"/api/chat/messages/{msg['_id']}", headers=auth_headers, json={
        "content": "edited content", "regenerate": False,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"]["_id"] == str(msg["_id"])
    assert body["message"]["content"] == "edited content"
    assert body["deleted_count"] == 0
    assert "assistant_message" not in body


def test_edit_message_with_regenerate(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    msg = _seed_user_message(flask_core, str(conv["_id"]), "original")
    _seed_assistant_message(flask_core, str(conv["_id"]), "old answer")

    resp = client.put(f"/api/chat/messages/{msg['_id']}", headers=auth_headers, json={
        "content": "edited content", "regenerate": True,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"]["content"] == "edited content"
    assert body["assistant_message"]["_id"]
    assert body["assistant_message"]["content"] == "Hello from the model"


# ---------------------------------------------------------------------------
# POST /regenerate/{message_id}.
# ---------------------------------------------------------------------------
def test_regenerate_happy(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    _seed_user_message(flask_core, str(conv["_id"]), "the question")
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]), "the old answer")

    resp = client.post(f"/api/chat/regenerate/{assistant['_id']}", headers=auth_headers, json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"]["_id"]
    assert body["message"]["content"] == "Hello from the model"
    assert body["branch_id"] == "main"
    assert "new_branch_id" not in body


def test_regenerate_with_branch(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    _seed_user_message(flask_core, str(conv["_id"]), "the question")
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]), "the old answer")

    resp = client.post(f"/api/chat/regenerate/{assistant['_id']}", headers=auth_headers, json={
        "create_branch": True, "branch_name": "alt",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new_branch_id"]
    assert body["branch_id"] == body["new_branch_id"]
    assert "branches" in body


def test_regenerate_streams(client, auth_headers, test_user, flask_core):
    """stream=true deletes the old assistant reply and emits tokens over SSE."""
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    _seed_user_message(flask_core, str(conv["_id"]), "the question")
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]), "the old answer")

    with client.stream(
        "POST",
        f"/api/chat/regenerate/{assistant['_id']}",
        headers=auth_headers,
        json={"stream": True},
    ) as resp:
        assert resp.status_code == 200, resp.read()
        body = "".join(resp.iter_text())

    assert "event: message_start" in body
    assert "event: message_chunk" in body
    assert "Hello world" in body
    assert "the old answer" not in body


def test_regenerate_user_message_404(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    user_msg = _seed_user_message(flask_core, str(conv["_id"]))
    # Regenerate targets an assistant message; a user message is not regeneratable.
    resp = client.post(f"/api/chat/regenerate/{user_msg['_id']}", headers=auth_headers, json={})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Message not found or not regeneratable"


def test_regenerate_no_user_message_400(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    # An assistant message with NO preceding user message -> 400.
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]), "orphan answer")
    resp = client.post(f"/api/chat/regenerate/{assistant['_id']}", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "No user message found"


# ---------------------------------------------------------------------------
# POST /messages/{message_id}/feedback.
# ---------------------------------------------------------------------------
def _fetch_message(flask_core, message_id):
    from app.models.message import MessageModel

    with flask_core.app_context():
        return MessageModel.find_by_id(str(message_id))


@pytest.mark.parametrize("rating", ["up", "down"])
def test_feedback_set_rating(client, auth_headers, test_user, flask_core, rating):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]))

    resp = client.post(
        f"/api/chat/messages/{assistant['_id']}/feedback",
        headers=auth_headers,
        json={"rating": rating},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"success": True, "message_id": str(assistant["_id"]), "rating": rating}
    # Persisted into message_metadata.feedback (aliased to metadata on read).
    stored = _fetch_message(flask_core, assistant["_id"])
    assert stored["metadata"]["feedback"] == rating


def test_feedback_preserves_sibling_metadata(client, auth_headers, test_user, flask_core):
    """Rating write must not clobber existing metadata keys (model_id, etc.)."""
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]))

    resp = client.post(
        f"/api/chat/messages/{assistant['_id']}/feedback",
        headers=auth_headers,
        json={"rating": "up"},
    )
    assert resp.status_code == 200, resp.text
    stored = _fetch_message(flask_core, assistant["_id"])
    assert stored["metadata"]["feedback"] == "up"
    # model_id was stamped by create_assistant_message and must survive.
    assert stored["metadata"]["model_id"] == "openai/gpt-4o-mini"


def test_feedback_clear_null_removes_key(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]))

    # Set, then clear.
    client.post(f"/api/chat/messages/{assistant['_id']}/feedback",
                headers=auth_headers, json={"rating": "down"})
    resp = client.post(f"/api/chat/messages/{assistant['_id']}/feedback",
                       headers=auth_headers, json={"rating": None})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "success": True, "message_id": str(assistant["_id"]), "rating": None,
    }
    stored = _fetch_message(flask_core, assistant["_id"])
    assert "feedback" not in (stored["metadata"] or {})
    # model_id still intact after the wholesale-replace clear path.
    assert stored["metadata"]["model_id"] == "openai/gpt-4o-mini"


def test_feedback_invalid_rating_400(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]))

    resp = client.post(
        f"/api/chat/messages/{assistant['_id']}/feedback",
        headers=auth_headers,
        json={"rating": "sideways"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "rating must be one of 'up', 'down', or null"


def test_feedback_user_message_rejected_400(client, auth_headers, test_user, flask_core):
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    user_msg = _seed_user_message(flask_core, str(conv["_id"]))

    resp = client.post(
        f"/api/chat/messages/{user_msg['_id']}/feedback",
        headers=auth_headers,
        json={"rating": "up"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Only assistant messages can be rated"


def test_feedback_invalid_id_400(client, auth_headers):
    resp = client.post("/api/chat/messages/temp-123456/feedback",
                       headers=auth_headers, json={"rating": "up"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid message ID format"


def test_feedback_unknown_404(client, auth_headers):
    import uuid

    resp = client.post(f"/api/chat/messages/{uuid.uuid4()}/feedback",
                       headers=auth_headers, json={"rating": "up"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Message not found"


def test_feedback_foreign_conversation_404(client, auth_headers, plain_user, flask_core):
    config = _seed_config(flask_core, plain_user["_id"])
    conv = _seed_conversation(flask_core, plain_user["_id"], str(config["_id"]))
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]))

    # test_user (auth_headers) must not rate a message in plain_user's conversation.
    resp = client.post(
        f"/api/chat/messages/{assistant['_id']}/feedback",
        headers=auth_headers,
        json={"rating": "up"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Conversation not found"


def test_feedback_no_token_401(client):
    import uuid

    resp = client.post(f"/api/chat/messages/{uuid.uuid4()}/feedback",
                       json={"rating": "up"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# POST /regenerate/{message_id} — config_id override (model switch).
# ---------------------------------------------------------------------------
def test_regenerate_with_config_id_override(client, auth_headers, test_user, flask_core, monkeypatch):
    """A body config_id (quick:<model>) regenerates with that model, resolved
    via the same path as /send, and stamps the swapped model_id onto the new
    assistant message — without mutating the conversation's saved config."""
    captured = {}

    def _spy_completion(*args, **kwargs):
        captured["model"] = kwargs.get("model")
        captured["workspace_id"] = kwargs.get("workspace_id")
        captured["project_id"] = kwargs.get("project_id")
        captured["origin"] = kwargs.get("origin")
        return dict(_FAKE_COMPLETION)

    monkeypatch.setattr(OpenRouterService, "chat_completion",
                        staticmethod(_spy_completion))

    config = _seed_config(flask_core, test_user["_id"])  # model openai/gpt-4o-mini
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    _seed_user_message(flask_core, str(conv["_id"]), "the question")
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]), "old answer")

    resp = client.post(
        f"/api/chat/regenerate/{assistant['_id']}",
        headers=auth_headers,
        json={"config_id": "quick:anthropic/claude-opus-5"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"]["content"] == "Hello from the model"

    # The override model (NOT the conversation's saved openai/gpt-4o-mini) was used.
    assert captured["model"] == "anthropic/claude-opus-5"
    # Origin/attribution plumbing still flows (usage logging path intact).
    assert captured["origin"] == "web"

    # New assistant message stamped with the swapped model_id.
    new_msg = _fetch_message(flask_core, body["message"]["_id"])
    assert new_msg["metadata"]["model_id"] == "anthropic/claude-opus-5"

    # Conversation's saved config_id is UNCHANGED (override was for this gen only).
    from app.models.conversation import ConversationModel
    with flask_core.app_context():
        reloaded = ConversationModel.find_by_id(str(conv["_id"]))
    assert str(reloaded["config_id"]) == str(config["_id"])


def test_regenerate_unknown_config_id_override_404(client, auth_headers, test_user, flask_core):
    import uuid

    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    _seed_user_message(flask_core, str(conv["_id"]), "the question")
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]), "old answer")

    resp = client.post(
        f"/api/chat/regenerate/{assistant['_id']}",
        headers=auth_headers,
        json={"config_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Config not found"


# ---------------------------------------------------------------------------
# POST /stream — SSE.
# ---------------------------------------------------------------------------
def test_stream_missing_message_400(client, auth_headers):
    resp = client.post("/api/chat/stream", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Message content is required"


def test_stream_unknown_config_404(client, auth_headers):
    import uuid

    resp = client.post("/api/chat/stream", headers=auth_headers, json={
        "config_id": str(uuid.uuid4()), "message": "hello",
    })
    assert resp.status_code == 404
    assert resp.json()["error"] == "Config not found"


def test_stream_no_token_401(client):
    resp = client.post("/api/chat/stream", json={
        "config_id": "quick:google/gemini-3.5-flash-lite", "message": "x",
    })
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_stream_emits_sse_frames(client, auth_headers):
    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite",
        "message": "Stream please",
    }) as resp:
        assert resp.status_code == 200, resp.read()
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["x-accel-buffering"] == "no"

        body = "".join(resp.iter_text())

    # First frame is the new-conversation notice (quick model -> new conv).
    assert body.startswith("event: conversation_created")
    # The message lifecycle events all appear.
    assert "event: message_saved" in body
    assert "event: message_start" in body
    assert "event: message_chunk" in body
    assert "event: message_complete" in body

    # The streamed chunks reconstruct the full content.
    chunks = []
    for raw in body.split("\n\n"):
        if "event: message_chunk" in raw:
            data_line = [ln for ln in raw.splitlines() if ln.startswith("data:")][0]
            chunks.append(json.loads(data_line[len("data:"):].strip())["content"])
    assert "".join(chunks) == "Hello world"


def test_stream_existing_other_user_conversation_error_frame(client, auth_headers, plain_user, flask_core):
    config = _seed_config(flask_core, plain_user["_id"])
    conv = _seed_conversation(flask_core, plain_user["_id"], str(config["_id"]))
    # Non-members are rejected with a clean pre-stream 4xx (see the stream
    # handler's preflight access gate), not an in-stream error frame.
    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite",
        "conversation_id": str(conv["_id"]),
        "message": "intrusion",
    }) as resp:
        body = resp.read()
        assert resp.status_code == 404
    assert b"Conversation not found" in body


# ---------------------------------------------------------------------------
# POST /cancel/{message_id}.
# ---------------------------------------------------------------------------
def test_cancel_unknown_404(client, auth_headers):
    import uuid

    resp = client.post(f"/api/chat/cancel/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Generation not found"


def test_cancel_happy(client, auth_headers, test_user, flask_core):
    from app.services import stream_state

    message_id = "cancel-target-1"
    with flask_core.app_context():
        stream_state.register(message_id, user_id=str(test_user["_id"]))

    resp = client.post(f"/api/chat/cancel/{message_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    with flask_core.app_context():
        assert stream_state.is_cancelled(message_id) is True


def test_cancel_not_owner_403(client, auth_headers, plain_user, flask_core):
    from app.services import stream_state

    message_id = "cancel-target-2"
    # Registered by plain_user; test_user (auth_headers) must not be able to cancel it.
    with flask_core.app_context():
        stream_state.register(message_id, user_id=str(plain_user["_id"]))

    resp = client.post(f"/api/chat/cancel/{message_id}", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Not authorized"


def test_cancel_no_token_401(client):
    resp = client.post("/api/chat/cancel/anything")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# Route-registration smoke.
# ---------------------------------------------------------------------------
def test_chat_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/chat/send" in paths
    assert "/api/chat/{conversation_id}/messages" in paths
    assert "/api/chat/messages/{message_id}" in paths
    assert "/api/chat/regenerate/{message_id}" in paths
    assert "/api/chat/stream" in paths
    assert "/api/chat/cancel/{message_id}" in paths


# ---------------------------------------------------------------------------
# Canvas intent (picker-selected model + Canvas Coder prompt) + reasoning effort.
# ---------------------------------------------------------------------------
def _spy_stream_completion(captured):
    """chat_completion stand-in that records kwargs and streams one chunk."""
    def _spy(*args, **kwargs):
        captured.update(kwargs)

        def _gen():
            yield {"choices": [{"delta": {"content": "```html\n<h1>hi</h1>\n```"},
                                "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 5, "completion_tokens": 5}}
            yield {"done": True}
        return _gen()
    return _spy


def test_stream_canvas_intent_uses_selected_model_with_canvas_prompt(
    client, auth_headers, monkeypatch
):
    """intent='canvas' keeps the PICKER-selected model and swaps in the Canvas
    Coder system prompt (frontend no longer pins canvas to agent:canvas)."""
    captured = {}
    monkeypatch.setattr(OpenRouterService, "chat_completion",
                        staticmethod(_spy_stream_completion(captured)))

    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite",
        "message": "build a counter",
        "intent": "canvas",
    }) as resp:
        assert resp.status_code == 200, resp.read()
        "".join(resp.iter_text())  # drain (idle-in-transaction guard)

    assert captured["model"] == "google/gemini-3.5-flash-lite"
    assert "Canvas Coder" in (captured.get("system_prompt") or "")


def test_stream_without_canvas_intent_keeps_config_prompt(
    client, auth_headers, monkeypatch
):
    captured = {}
    monkeypatch.setattr(OpenRouterService, "chat_completion",
                        staticmethod(_spy_stream_completion(captured)))

    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite",
        "message": "hello",
    }) as resp:
        assert resp.status_code == 200, resp.read()
        "".join(resp.iter_text())

    assert "Canvas Coder" not in (captured.get("system_prompt") or "")


def test_stream_reasoning_effort_passthrough(client, auth_headers, monkeypatch):
    captured = {}
    monkeypatch.setattr(OpenRouterService, "chat_completion",
                        staticmethod(_spy_stream_completion(captured)))

    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite",
        "message": "think hard",
        "reasoning_effort": "high",
    }) as resp:
        assert resp.status_code == 200, resp.read()
        "".join(resp.iter_text())

    assert captured["reasoning_effort"] == "high"


def test_stream_reasoning_effort_invalid_dropped(client, auth_headers, monkeypatch):
    captured = {}
    monkeypatch.setattr(OpenRouterService, "chat_completion",
                        staticmethod(_spy_stream_completion(captured)))

    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite",
        "message": "go",
        "reasoning_effort": "turbo",
    }) as resp:
        assert resp.status_code == 200, resp.read()
        "".join(resp.iter_text())

    assert captured["reasoning_effort"] is None


def test_regenerate_canvas_intent_carries_canvas_prompt(
    client, auth_headers, test_user, flask_core, monkeypatch
):
    """Regenerating a canvas turn re-applies the Canvas Coder prompt and stamps
    intent='canvas' onto the regenerated message (future regens keep working)."""
    captured = {}

    def _spy(*args, **kwargs):
        captured.update(kwargs)
        return dict(_FAKE_COMPLETION)

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_spy))

    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    _seed_user_message(flask_core, str(conv["_id"]), "build a page")
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]), "```html\n<p>old</p>\n```")

    from app.models.message import MessageModel
    with flask_core.app_context():
        MessageModel.merge_metadata(str(assistant["_id"]), {"intent": "canvas"})

    resp = client.post(f"/api/chat/regenerate/{assistant['_id']}",
                       headers=auth_headers, json={})
    assert resp.status_code == 200, resp.text

    assert "Canvas Coder" in (captured.get("system_prompt") or "")
    new_msg = _fetch_message(flask_core, resp.json()["message"]["_id"])
    assert new_msg["metadata"]["intent"] == "canvas"


def test_format_messages_emits_audio_and_video_parts(monkeypatch):
    """Audio/video attachments inline their upload bytes as OpenRouter
    ``input_audio`` (raw base64 + format) and ``video_url`` (data-URI) parts.

    Pure unit test — patches the module-level byte reader so it never touches
    the DB or disk.
    """
    import app.services.openrouter_service as orm

    monkeypatch.setattr(orm, "_read_upload_bytes", lambda uid, user_id=None: b"ABCD")

    msgs = [{"role": "user", "content": "hi", "attachments": [
        {"name": "a.mp3", "mime_type": "audio/mpeg", "upload_id": "u1",
         "is_audio": True, "url": "/api/uploads/u1"},
        {"name": "v.mp4", "mime_type": "video/mp4", "upload_id": "u2",
         "is_video": True, "url": "/api/uploads/u2"},
    ]}]

    out = orm.OpenRouterService.format_messages_for_api_ex(msgs, user_id="caller")
    parts = out["messages"][0]["content"]

    audio = [p for p in parts if p.get("type") == "input_audio"]
    video = [p for p in parts if p.get("type") == "video_url"]

    assert audio and audio[0]["input_audio"]["format"] == "mp3"
    assert audio[0]["input_audio"]["data"]
    assert video and video[0]["video_url"]["url"].startswith("data:video/mp4;base64,")
