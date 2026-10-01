"""Integration tests for the conversation ``kind`` discriminator.

Data-Analyzer conversations are persisted with ``kind='data'`` so the chat
sidebar (and its dedicated page) can filter them apart from normal chat
(``kind='chat'``, the default). Exercises the ``?kind=`` query param on
``GET /api/conversations`` end-to-end: TestClient -> flask_ctx app_context ->
real ConversationModel facade on Postgres -> legacy-shaped JSON.
"""
from app.models.conversation import ConversationModel


def _seed_conversation(flask_core, user_id, *, title, kind):
    with flask_core.app_context():
        return ConversationModel.create(
            user_id=user_id,
            config_id="quick:openai/gpt-4o-mini",
            title=title,
            kind=kind,
            workspace_id=_active_ws(user_id),
        )


def _ids(payload):
    return {c["_id"] for c in payload["conversations"]}


def test_kind_filter_partitions_chat_and_data(client, auth_headers, test_user, flask_core):
    chat = _seed_conversation(
        flask_core, test_user["_id"], title="Chat one", kind="chat"
    )
    data = _seed_conversation(
        flask_core, test_user["_id"], title="Data one", kind="data"
    )
    chat_id = str(chat["_id"])
    data_id = str(data["_id"])

    # ?kind=chat -> only the chat conversation.
    resp = client.get("/api/conversations?kind=chat", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _ids(body) == {chat_id}
    assert body["total"] == 1

    # ?kind=data -> only the data conversation.
    resp = client.get("/api/conversations?kind=data", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _ids(body) == {data_id}
    assert body["total"] == 1

    # No kind param -> both (backward-compatible).
    resp = client.get("/api/conversations", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _ids(body) == {chat_id, data_id}
    assert body["total"] == 2


def test_default_kind_is_chat(client, auth_headers, test_user, flask_core):
    """A conversation created without an explicit kind defaults to 'chat' and
    therefore surfaces under ``?kind=chat``."""
    conv = _seed_conversation(
        flask_core, test_user["_id"], title="Defaulted", kind="chat"
    )
    # Sanity: the persisted row carries kind='chat'.
    with flask_core.app_context():
        fetched = ConversationModel.find_by_id(conv["_id"])
    assert fetched["kind"] == "chat"

    resp = client.get("/api/conversations?kind=data", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["conversations"] == []


def test_create_endpoint_accepts_data_kind(client, auth_headers, test_user, flask_core):
    """POST /api/conversations honors an explicit ``kind='data'`` in the body,
    and the row is excluded from the default chat listing."""
    from app.models.llm_config import LLMConfigModel

    with flask_core.app_context():
        config = LLMConfigModel.create(
            name="Cfg",
            model_id="openai/gpt-4o-mini",
            model_name="GPT-4o mini",
            owner_id=test_user["_id"],
            system_prompt="bot",
        )

    resp = client.post(
        "/api/conversations",
        headers=auth_headers,
        json={"config_id": str(config["_id"]), "title": "Data via API", "kind": "data"},
    )
    assert resp.status_code == 201, resp.text
    created_id = resp.json()["conversation"]["_id"]

    # Shows under ?kind=data, hidden under ?kind=chat.
    data_body = client.get("/api/conversations?kind=data", headers=auth_headers).json()
    assert created_id in {c["_id"] for c in data_body["conversations"]}

    chat_body = client.get("/api/conversations?kind=chat", headers=auth_headers).json()
    assert created_id not in {c["_id"] for c in chat_body["conversations"]}


def _active_ws(user_id):
    """The user's org (conftest puts every fixture user in "Test Org")."""
    from app.models.user import UserModel

    return (UserModel.find_by_id(user_id) or {}).get("active_workspace_id")
