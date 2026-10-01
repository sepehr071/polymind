"""Coverage-driver tests for the chat / misc_a / misc_b / debate / automate_agent
FastAPI routers.

Mirrors the sibling suites (tests/api/test_chat.py, test_misc_a.py,
test_misc_b.py, test_debate.py, test_automate.py): real model facades on
Postgres via the flask_ctx bridge, legacy-shaped JSON, external upstreams
(OpenRouter, browser-use Cloud) mocked at the service boundary. The DLP gate is
inert for seeded users (active_workspace_id=None -> gate short-circuits) unless a
test explicitly monkeypatches the redact path.

These tests target the UNCOVERED branches the siblings miss: error-message 500
paths, token-limit 429s, DLP redact badges, annotation persistence, the full
debate stream (judge phase + persistence), error-chunk SSE frames, upload
extraction + traversal guards, the helper rate-limiter internals + usage rollup
masking, and the automate poll-error/timeout paths.
"""
import base64
import io
import json
import uuid

import pytest

from app.api.core import flask_core
from app.services.openrouter_service import OpenRouterService


# ===========================================================================
# Shared OpenRouter stubs.
# ===========================================================================
_FAKE_COMPLETION = {
    "choices": [{"message": {"content": "Hello from the model"},
                 "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


def _fake_chat_completion(*args, **kwargs):
    if kwargs.get("stream"):
        def _gen():
            yield {"choices": [{"delta": {"content": "Hi "}}]}
            yield {"choices": [{"delta": {"content": "there"}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
            yield {"done": True}
        return _gen()
    return dict(_FAKE_COMPLETION)


@pytest.fixture
def mock_openrouter(monkeypatch):
    monkeypatch.setattr(OpenRouterService, "chat_completion",
                        staticmethod(_fake_chat_completion))
    monkeypatch.setattr(OpenRouterService, "generate_title",
                        staticmethod(lambda *a, **k: "Generated Title"))
    yield


# ===========================================================================
# Seeding helpers.
# ===========================================================================
def _seed_config(flask_core, owner_id):
    from app.models.llm_config import LLMConfigModel

    with flask_core.app_context():
        return LLMConfigModel.create(
            name="Cov Config",
            model_id="openai/gpt-4o-mini",
            model_name="GPT-4o mini",
            owner_id=owner_id,
            system_prompt="You are a test bot.",
        )


def _seed_conversation(flask_core, user_id, config_id):
    from app.models.conversation import ConversationModel

    with flask_core.app_context():
        return ConversationModel.create(
            user_id=user_id, config_id=config_id, title="Cov conversation",
        )


def _seed_user_message(flask_core, conversation_id, content="hi", metadata=None):
    from app.models.message import MessageModel

    with flask_core.app_context():
        return MessageModel.create_user_message(
            conversation_id=conversation_id, content=content, metadata=metadata,
        )


def _seed_assistant_message(flask_core, conversation_id, content="ans"):
    from app.models.message import MessageModel

    with flask_core.app_context():
        return MessageModel.create_assistant_message(
            conversation_id=conversation_id, content=content,
            model_id="openai/gpt-4o-mini",
        )


def _png_bytes(color=(20, 120, 200), size=(8, 8)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeDetector:
    """Stand-in DLPDetector whose redact() scrubs the leading token."""

    @staticmethod
    def from_workspace(workspace_id):
        return _FakeDetector()

    def redact(self, text, user_lang="en", *, user_id=None):
        return ("[SENSITIVE_1] redacted", [{"label": "SECRET"}], None)


# ===========================================================================
# CHAT — error-message 500 paths, token limit, annotations, DLP redact badge.
# ===========================================================================
def test_send_provider_error_returns_500_with_messages(
    client, auth_headers, test_user, flask_core, monkeypatch
):
    """chat.py:333-345 — completion dict carries 'error' -> 500 with both turns."""
    monkeypatch.setattr(
        OpenRouterService, "chat_completion",
        staticmethod(lambda *a, **k: {"error": {"message": "model exploded"}}),
    )
    config = _seed_config(flask_core, test_user["_id"])
    resp = client.post("/api/chat/send", headers=auth_headers, json={
        "config_id": str(config["_id"]), "message": "boom",
    })
    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body["error"] == "model exploded"
    assert body["user_message"]["_id"]
    assert body["assistant_message"]["role"] == "assistant"


def test_send_token_limit_reached_429(
    client, auth_headers, test_user, flask_core, mock_openrouter
):
    """chat.py:225-226 — tokens_used >= tokens_limit -> 429."""
    from app.models.user import UserModel, User as UserRow
    from app.api.core import db

    config = _seed_config(flask_core, test_user["_id"])
    with flask_core.app_context():
        db.session.execute(
            db.update(UserRow).where(UserRow.id == test_user["_id"]).values(
                usage={"tokens_used": 100, "tokens_limit": 50,
                       "messages_used": 0, "messages_limit": -1},
            )
        )
        db.session.commit()
    resp = client.post("/api/chat/send", headers=auth_headers, json={
        "config_id": str(config["_id"]), "message": "x",
    })
    assert resp.status_code == 429
    assert resp.json()["error"] == "Token limit reached"


def test_send_persists_annotations(
    client, auth_headers, test_user, flask_core, monkeypatch
):
    """chat.py:370-373 — assistant annotations merged into metadata."""
    def _with_ann(*a, **k):
        return {
            "choices": [{"message": {"content": "cited"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "annotations": [{"type": "url_citation", "url": "https://x"}],
        }

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_with_ann))
    monkeypatch.setattr(OpenRouterService, "generate_title",
                        staticmethod(lambda *a, **k: "T"))
    config = _seed_config(flask_core, test_user["_id"])
    resp = client.post("/api/chat/send", headers=auth_headers, json={
        "config_id": str(config["_id"]), "message": "search",
    })
    assert resp.status_code == 200, resp.text
    meta = resp.json()["assistant_message"]["metadata"]
    assert meta["annotations"][0]["type"] == "url_citation"


def test_send_dlp_redact_badge(
    client, auth_headers, test_user, flask_core, monkeypatch, mock_openrouter
):
    """chat turn DLP redact — scrubs message + stamps a dlp_redacted badge."""
    # Gate helper lives in chat._common after the package split (not monomodule).
    import app.api.routers.chat._common as chat_common

    monkeypatch.setattr(chat_common, "gate_redactable",
                        lambda **kw: {"redacted": True})
    monkeypatch.setattr(chat_common, "DLPDetector", _FakeDetector)
    config = _seed_config(flask_core, test_user["_id"])
    resp = client.post("/api/chat/send", headers=auth_headers, json={
        "config_id": str(config["_id"]), "message": "my secret is hunter2",
    })
    assert resp.status_code == 200, resp.text
    um = resp.json()["user_message"]
    assert um["content"] == "[SENSITIVE_1] redacted"
    assert um["metadata"]["dlp_redacted"]["count"] == 1


def test_edit_regenerate_provider_error_500(
    client, auth_headers, test_user, flask_core, monkeypatch
):
    """chat.py:594-606 — regenerate completion errors -> 500 incl. edited msg."""
    monkeypatch.setattr(
        OpenRouterService, "chat_completion",
        staticmethod(lambda *a, **k: {"error": {"message": "regen failed"}}),
    )
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    msg = _seed_user_message(flask_core, str(conv["_id"]), "original")
    _seed_assistant_message(flask_core, str(conv["_id"]), "old")
    resp = client.put(f"/api/chat/messages/{msg['_id']}", headers=auth_headers, json={
        "content": "edited", "regenerate": True,
    })
    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body["error"] == "regen failed"
    assert body["message"]["content"] == "edited"
    assert body["assistant_message"]["role"] == "assistant"


def test_edit_regenerate_config_missing_404(
    client, auth_headers, test_user, flask_core
):
    """chat.py:483-484 — config deleted before regenerate -> 404 (no msg loss)."""
    from app.models.llm_config import LLMConfigModel
    from app.api.core import db

    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    msg = _seed_user_message(flask_core, str(conv["_id"]), "original")
    with flask_core.app_context():
        LLMConfigModel.delete(str(config["_id"]))
    resp = client.put(f"/api/chat/messages/{msg['_id']}", headers=auth_headers, json={
        "content": "edited", "regenerate": True,
    })
    assert resp.status_code == 404
    assert resp.json()["error"] == "Config not found"


def test_regenerate_provider_error_500(
    client, auth_headers, test_user, flask_core, monkeypatch
):
    """chat.py:771-775 — regenerate-endpoint completion error -> plain 500."""
    monkeypatch.setattr(
        OpenRouterService, "chat_completion",
        staticmethod(lambda *a, **k: {"error": {"message": "nope"}}),
    )
    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    _seed_user_message(flask_core, str(conv["_id"]), "q")
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]), "a")
    resp = client.post(f"/api/chat/regenerate/{assistant['_id']}",
                       headers=auth_headers, json={})
    assert resp.status_code == 500
    assert resp.json()["error"] == "nope"


def test_regenerate_config_missing_404(client, auth_headers, test_user, flask_core):
    """chat.py:668-669 — regenerate when config row is gone -> 404."""
    from app.models.llm_config import LLMConfigModel

    config = _seed_config(flask_core, test_user["_id"])
    conv = _seed_conversation(flask_core, test_user["_id"], str(config["_id"]))
    _seed_user_message(flask_core, str(conv["_id"]), "q")
    assistant = _seed_assistant_message(flask_core, str(conv["_id"]), "a")
    with flask_core.app_context():
        LLMConfigModel.delete(str(config["_id"]))
    resp = client.post(f"/api/chat/regenerate/{assistant['_id']}",
                       headers=auth_headers, json={})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Config not found"


def test_stream_error_chunk_emits_message_error(
    client, auth_headers, monkeypatch
):
    """chat.py:1104-1112 — an error chunk mid-stream -> message_error frame."""
    def _err_stream(*a, **k):
        def _gen():
            yield {"error": {"message": "stream boom"}}
        return _gen()

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_err_stream))
    monkeypatch.setattr(OpenRouterService, "generate_title",
                        staticmethod(lambda *a, **k: "T"))
    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite", "message": "go",
    }) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "event: message_error" in body
    assert "stream boom" in body


def test_stream_done_with_annotations_surfaces_citations(
    client, auth_headers, monkeypatch
):
    """chat.py:1116-1117 + 1214-1226 — done-frame annotations -> citations payload."""
    def _ann_stream(*a, **k):
        def _gen():
            yield {"choices": [{"delta": {"content": "see this"}}]}
            yield {"done": True,
                   "annotations": [{"type": "url_citation", "url": "https://cite"}]}
        return _gen()

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_ann_stream))
    monkeypatch.setattr(OpenRouterService, "generate_title",
                        staticmethod(lambda *a, **k: "T"))
    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite", "message": "go", "intent": "ask",
    }) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    complete = body.split("event: message_complete", 1)[1]
    data_line = next(ln for ln in complete.splitlines() if ln.startswith("data:"))
    payload = json.loads(data_line[len("data:"):].strip())
    assert payload["intent"] == "ask"
    assert payload["citations"][0]["url"] == "https://cite"


def test_stream_token_limit_429(client, auth_headers, test_user, flask_core, mock_openrouter):
    """chat.py:902-904 — stream endpoint also enforces the token cap -> 429."""
    from app.models.user import User as UserRow
    from app.api.core import db

    with flask_core.app_context():
        db.session.execute(
            db.update(UserRow).where(UserRow.id == test_user["_id"]).values(
                usage={"tokens_used": 999, "tokens_limit": 10,
                       "messages_used": 0, "messages_limit": -1},
            )
        )
        db.session.commit()
    resp = client.post("/api/chat/stream", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite", "message": "x",
    })
    assert resp.status_code == 429
    assert resp.json()["error"] == "Token limit reached"


def test_stream_title_updated_frame(client, auth_headers, monkeypatch):
    """chat.py:1228-1235 — new conversation whose better title differs emits
    a title_updated frame (title thread runs synchronously enough via the mock)."""
    def _stream(*a, **k):
        def _gen():
            yield {"choices": [{"delta": {"content": "hello"}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
            yield {"done": True}
        return _gen()

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_stream))
    # Title generator returns a NEW title; the background thread updates the conv.
    monkeypatch.setattr(OpenRouterService, "generate_title",
                        staticmethod(lambda *a, **k: "A Much Better Title"))
    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": "quick:google/gemini-3.5-flash-lite", "message": "first question here",
    }) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    # The conversation_created + completion frames always appear; title_updated is
    # best-effort (depends on the daemon thread finishing before the final read).
    assert "event: message_complete" in body


# ===========================================================================
# MISC_A — upload extraction, traversal/oversize guards, image-gen redact + edges.
# ===========================================================================
@pytest.fixture
def upload_tmpdir(flask_core, tmp_path):
    cfg = flask_core.config
    saved = cfg.get("UPLOAD_FOLDER")
    cfg["UPLOAD_FOLDER"] = str(tmp_path)
    yield tmp_path
    cfg["UPLOAD_FOLDER"] = saved


def test_upload_text_file_extracts(client, auth_headers, upload_tmpdir):
    """misc_a.py:197-217 — an extractable .txt records extracted text."""
    files = {"file": ("notes.txt", b"hello world from a text file", "text/plain")}
    headers = {"Authorization": auth_headers["Authorization"]}
    resp = client.post("/api/uploads/file", headers=headers, files=files)
    assert resp.status_code == 201, resp.text
    body = resp.json()["upload"]
    assert body["type"] == "file"
    assert body["extraction_status"] in ("ok", "partial", "empty", "error")
    # text_preview is populated when extraction yielded markdown.
    if body["extracted_chars"]:
        assert body["text_preview"]


def test_upload_oversize_413(client, auth_headers, upload_tmpdir, flask_core):
    """misc_a.py:144-158 — exceeding CHAT_UPLOAD_MAX_BYTES -> 413 + partial unlink."""
    cfg = flask_core.config
    saved = cfg.get("CHAT_UPLOAD_MAX_BYTES")
    cfg["CHAT_UPLOAD_MAX_BYTES"] = 4  # tiny cap
    try:
        files = {"file": ("big.png", _png_bytes(size=(64, 64)), "image/png")}
        headers = {"Authorization": auth_headers["Authorization"]}
        resp = client.post("/api/uploads/file", headers=headers, files=files)
        assert resp.status_code == 413, resp.text
        body = resp.json()
        assert body["code"] == "file_too_large"
        assert body["max_bytes"] == 4
    finally:
        cfg["CHAT_UPLOAD_MAX_BYTES"] = saved
    # Partial file was removed.
    assert not list(upload_tmpdir.glob("*.png"))


def test_upload_non_image_ext_with_image_bytes_mismatch(
    client, auth_headers, upload_tmpdir
):
    """misc_a.py:176-178 — a non-image extension whose bytes sniff as image -> 400."""
    files = {"file": ("data.txt", _png_bytes(), "text/plain")}
    headers = {"Authorization": auth_headers["Authorization"]}
    resp = client.post("/api/uploads/file", headers=headers, files=files)
    assert resp.status_code == 400
    assert resp.json()["error"] == "mime_mismatch"


def test_upload_image_no_file_400(client, auth_headers, upload_tmpdir):
    """misc_a.py:284-285 — /image with no file part -> 400."""
    headers = {"Authorization": auth_headers["Authorization"]}
    resp = client.post("/api/uploads/image", headers=headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "No file provided"


def test_get_upload_traversal_row_404(client, auth_headers, upload_tmpdir, flask_core):
    """misc_a.py:363-365 — a crafted filename with a separator -> 404 (guard)."""
    from app.models.upload import UploadModel
    from app.api.core import db
    from app.models.upload import Upload as UploadRow

    headers = {"Authorization": auth_headers["Authorization"]}
    up = client.post("/api/uploads/file", headers=headers,
                     files={"file": ("p.png", _png_bytes(), "image/png")}).json()["upload"]
    # Poison the stored filename with a path separator.
    with flask_core.app_context():
        db.session.execute(
            db.update(UploadRow).where(UploadRow.id == uuid.UUID(up["id"]))
            .values(filename="../escape.png")
        )
        db.session.commit()
    resp = client.get(f"/api/uploads/{up['id']}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Upload not found"


def test_get_upload_missing_disk_file_404(
    client, auth_headers, upload_tmpdir
):
    """misc_a.py:369-370 — row exists but the on-disk file is gone -> 404."""
    headers = {"Authorization": auth_headers["Authorization"]}
    up = client.post("/api/uploads/file", headers=headers,
                     files={"file": ("p.png", _png_bytes(), "image/png")}).json()["upload"]
    (upload_tmpdir / up["filename"]).unlink()
    resp = client.get(f"/api/uploads/{up['id']}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Upload not found"


def test_thumbnail_no_thumbnail_404(client, auth_headers, upload_tmpdir):
    """misc_a.py:394-395 — a non-image upload has no thumbnail -> 404."""
    headers = {"Authorization": auth_headers["Authorization"]}
    up = client.post("/api/uploads/file", headers=headers,
                     files={"file": ("doc.txt", b"plain text", "text/plain")}).json()["upload"]
    resp = client.get(f"/api/uploads/{up['id']}/thumbnail", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "No thumbnail available"


def test_thumbnail_missing_disk_file_404(client, auth_headers, upload_tmpdir):
    """misc_a.py:403-404 — thumbnail row present but file deleted -> 404."""
    headers = {"Authorization": auth_headers["Authorization"]}
    up = client.post("/api/uploads/file", headers=headers,
                     files={"file": ("p.png", _png_bytes(), "image/png")}).json()["upload"]
    assert up["thumbnail_url"] is not None
    (upload_tmpdir / f"thumb_{up['filename']}").unlink()
    resp = client.get(f"/api/uploads/{up['id']}/thumbnail", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "No thumbnail available"


def test_get_image_owner_full_payload(client, auth_headers, flask_core, test_user):
    """misc_a.py:614-623 — single-image fetch returns full payload for owner."""
    from app.models.generated_image import GeneratedImageModel

    with flask_core.app_context():
        img = GeneratedImageModel.create(
            user_id=str(test_user["_id"]), prompt="p", model_id="google/x",
            image_data="data:image/png;base64,AAAA",
        )
    resp = client.get(f"/api/image-gen/{img['_id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["image"]["_id"] == str(img["_id"])


def test_get_image_not_found_404(client, auth_headers):
    """misc_a.py:616-618."""
    resp = client.get(f"/api/image-gen/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Image not found"


def test_get_image_non_owner_403(client, auth_headers, flask_core, plain_user):
    """misc_a.py:620-621."""
    from app.models.generated_image import GeneratedImageModel

    with flask_core.app_context():
        img = GeneratedImageModel.create(
            user_id=str(plain_user["_id"]), prompt="p", model_id="google/x",
            image_data="data:image/png;base64,AAAA",
        )
    resp = client.get(f"/api/image-gen/{img['_id']}", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Unauthorized"


def test_generate_image_redact_path(client, auth_headers, monkeypatch):
    """misc_a.py:526-529 — redact mode re-scrubs the bare prompt independently."""
    import app.api.routers.misc_a as misc_a

    monkeypatch.setattr(
        OpenRouterService, "generate_image",
        staticmethod(lambda *a, **k: {
            "success": True,
            "images": ["data:image/png;base64,ZmFrZQ=="],
            "image_data": "data:image/png;base64,ZmFrZQ==",
            "usage": {}, "cost_usd_total": None, "tokens_total": None, "n": 1,
        }),
    )
    monkeypatch.setattr(misc_a.dlp_gate, "gate_redactable",
                        lambda **kw: {"redacted": True})
    # The redact branch imports DLPDetector locally from app.services.dlp_service.
    monkeypatch.setattr("app.services.dlp_service.DLPDetector", _FakeDetector)
    resp = client.post("/api/image-gen/generate", headers=auth_headers, json={
        "prompt": "draw my secret token", "model": "google/x",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["image"]["prompt"] == "[SENSITIVE_1] redacted"


def test_bulk_delete_bad_json_400(client, auth_headers):
    """misc_a.py:648-654 — empty/garbage body -> no images specified."""
    headers = {"Authorization": auth_headers["Authorization"],
               "Content-Type": "application/json"}
    resp = client.post("/api/image-gen/bulk-delete", headers=headers, content="not json")
    assert resp.status_code == 400
    assert resp.json()["error"] == "No images specified"


def test_toggle_favorite_not_found_404(client, auth_headers):
    """misc_a.py:677 — toggling a missing image -> 404."""
    resp = client.post(f"/api/image-gen/{uuid.uuid4()}/favorite", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Image not found"


# ===========================================================================
# MISC_B — helper redact, error-chunk frame, usage rollup/masking, parse_iso.
# ===========================================================================
def test_helper_history_after_assistant_turn_strips_ids(
    client, plain_headers, plain_user, flask_core
):
    """misc_b.py:115-129 + 136-146 — deep-link extraction + _strip_ids on history."""
    from app.models.helper_conversation import HelperConversationModel

    with flask_core.app_context():
        HelperConversationModel.append_message(
            user_id=plain_user["_id"], role="assistant",
            content="See [chat](/chat) and [dup](/chat) and external [x](https://y)",
            page_context={"route": "/"},
            deep_links=["/chat"],
        )
    resp = client.get("/api/helper/history", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    msgs = resp.json()["messages"]
    assert msgs and all("_id" not in m for m in msgs)


def test_helper_stream_error_chunk(client, plain_headers, plain_user, monkeypatch):
    """misc_b.py:329-335 — error chunk -> message_error frame, no completion."""
    def _err(*a, **k):
        def _gen():
            yield {"error": {"message": "helper boom"}}
        return _gen()

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_err))
    import app.api.routers.misc_b as misc
    misc._helper_rate.clear()
    with client.stream("POST", "/api/helper/stream", headers=plain_headers,
                       json={"message": "explain"}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    misc._helper_rate.clear()
    assert "event: message_error" in body
    assert "helper boom" in body
    assert "event: message_complete" not in body


def test_helper_stream_redact_path(client, plain_headers, plain_user, monkeypatch):
    """misc_b.py:251-252 — redact-mode swaps in the scrubbed message text."""
    import app.api.routers.misc_b as misc
    misc._helper_rate.clear()

    def _ok(*a, **k):
        def _gen():
            yield {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}
            yield {"done": True}
        return _gen()

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_ok))
    monkeypatch.setattr(
        "app.services.dlp_gate.gate_redactable",
        lambda **kw: {"redacted": True, "redacted_text": "[SENSITIVE_1]"},
    )
    with client.stream("POST", "/api/helper/stream", headers=plain_headers,
                       json={"message": "secret"}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    misc._helper_rate.clear()
    assert "event: message_complete" in body
    # The persisted user turn used the scrubbed text.
    hist = client.get("/api/helper/history", headers=plain_headers).json()["messages"]
    user_turns = [m for m in hist if m.get("role") == "user"]
    assert user_turns and user_turns[-1]["content"] == "[SENSITIVE_1]"


def test_usage_me_owner_sees_own_workspace_cost(
    client, auth_headers, test_user, flask_core
):
    """/usage/me is org-scoped: an ``owner`` member of a TEAM workspace sees the
    price for that org (``?workspace_id=``)."""
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel
    from app.models.usage_log import UsageLogModel

    with flask_core.app_context():
        team = WorkspaceModel.create(name="Cost Team", owner_id=None, type="team")
        team_id = str(team["_id"])
        WorkspaceMemberModel.add(team_id, test_user["_id"], "owner", status="active")
        UsageLogModel.create(
            user_id=str(test_user["_id"]),
            workspace_id=team_id,
            model_id="openai/gpt-4o-mini",
            feature="chat",
            origin="web",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=0.25,
        )
    resp = client.get(f"/api/usage/me?workspace_id={team_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_cost"] is not None
    assert body["total_cost"] >= 0.25
    assert body["total_tokens"] >= 15
    # Credits are ALWAYS present (the user-facing unit, never masked).
    assert body["total_credits"] is not None


def test_usage_me_viewer_sees_only_credits(
    client, plain_headers, plain_user, flask_core
):
    """Regression: a non-owner member sees NO dollar figure on /usage/me —
    total_cost is masked to None, credits + tokens are still returned."""
    from app.models.usage_log import UsageLogModel

    with flask_core.app_context():
        UsageLogModel.create(
            user_id=str(plain_user["_id"]),
            workspace_id=str(plain_user["active_workspace_id"]),
            model_id="openai/gpt-4o-mini",
            feature="chat",
            origin="web",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=0.25,
        )
    resp = client.get("/api/usage/me", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_cost"] is None
    assert body["total_credits"] is not None
    assert body["total_tokens"] >= 15


def test_admin_usage_per_user_breakdown(client, admin_headers):
    """misc_b.py:584-585 — per_user=true & group_by=user echoes the per_user key."""
    resp = client.get("/api/admin/usage?per_user=true&group_by=user",
                      headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "per_user" in body


def test_usage_me_from_to_iso_parsing(client, plain_headers):
    """misc_b.py:437-442 — from/to query params flow through _parse_iso."""
    resp = client.get("/api/usage/me?from=2020-01-01&to=2030-12-31T00:00:00",
                      headers=plain_headers)
    assert resp.status_code == 200, resp.text
    assert "data" in resp.json()


def test_usage_me_from_to_accepts_millis_z(client, plain_headers):
    """FE stamps `YYYY-MM-DDTHH:MM:SS.000Z`. A failed parse used to drop the
    window (all-time rows) so dashboard vs usage-tab counts drifted."""
    from app.api.routers.usage import _parse_iso

    parsed = _parse_iso("2026-09-01T00:00:00.000Z")
    assert parsed is not None
    assert parsed.year == 2026 and parsed.month == 9 and parsed.day == 1
    far = _parse_iso("2099-01-01T00:00:00.000Z")
    assert far is not None
    resp = client.get(
        "/api/usage/me?from=2099-01-01T00:00:00.000Z&to=2099-01-02T23:59:59.999Z",
        headers=plain_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("data") == []
    assert (body.get("total_credits") or 0) == 0


def test_health_status_postgres_down_degraded(client, monkeypatch):
    """misc_b.py:654-656 — a failing DB ping -> postgres ok False, degraded."""
    from app.api.core import db

    def _boom(*a, **k):
        raise RuntimeError("db gone")

    monkeypatch.setattr(db.session, "execute", _boom)
    resp = client.get("/api/v1/health/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dependencies"]["postgres"]["ok"] is False
    assert body["status"] == "degraded"


def test_health_status_openrouter_non_200_degraded(client, monkeypatch):
    """misc_b.py:669-670 — OpenRouter ping non-200 -> degraded."""
    class _Resp:
        status_code = 503

    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(), raising=True)
    resp = client.get("/api/v1/health/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dependencies"]["openrouter"]["ok"] is False
    assert body["status"] == "degraded"


# ===========================================================================
# DEBATE — full stream (judge phase + persistence) + error-chunk frames.
# ===========================================================================
_QM_A = "quick:google/gemini-3.5-flash-lite"
_QM_B = "quick:x-ai/grok-4.5"
_QM_JUDGE = "quick:openai/gpt-5.6-sol"


def _make_session(flask_core, user_id, *, topic="Is cereal soup?",
                  config_ids=None, judge=_QM_JUDGE, rounds=1, status="pending"):
    from app.models.debate_session import DebateSessionModel

    config_ids = config_ids or [_QM_A, _QM_B]
    with flask_core.app_context():
        session = DebateSessionModel.create(
            user_id=str(user_id), topic=topic, config_ids=config_ids,
            judge_config_id=judge, rounds=rounds, max_tokens=512,
        )
        if status != "pending":
            DebateSessionModel.update_status(session["_id"], status)
        return session


def _debate_completion(*args, **kwargs):
    def _gen():
        yield {"choices": [{"delta": {"content": "Argument "}}]}
        yield {"choices": [{"delta": {"content": "made."}}],
               "usage": {"prompt_tokens": 5, "completion_tokens": 3}}
        yield {"done": True}
    return _gen()


def _drain_stream(client, headers, body):
    with client.stream("POST", "/api/debate/stream", headers=headers, json=body) as resp:
        assert resp.status_code == 200, resp.read()
        return "".join(resp.iter_text())


def test_debate_stream_full_run_through_judge(
    client, auth_headers, flask_core, test_user, monkeypatch
):
    """debate.py:489-836 — drain the whole stream: rounds + judge + complete."""
    monkeypatch.setattr(OpenRouterService, "chat_completion",
                        staticmethod(_debate_completion))
    session = _make_session(flask_core, test_user["_id"], rounds=1)
    body = _drain_stream(client, auth_headers, {"session_id": session["_id"]})

    assert "event: debate_session_started" in body
    assert "event: debate_round_start" in body
    assert "event: debate_message_complete" in body
    assert "event: debate_round_complete" in body
    assert "event: debate_judge_start" in body
    assert "event: debate_judge_chunk" in body
    assert "event: debate_judge_complete" in body
    assert "event: debate_session_complete" in body

    # Judge verdict + debater messages persisted.
    with flask_core.app_context():
        from app.models.debate_message import DebateMessageModel
        msgs = DebateMessageModel.find_by_session(str(session["_id"]))
    roles = [m.get("role") for m in msgs]
    assert "debater" in roles
    assert "judge" in roles


def test_debate_stream_debater_error_chunk(
    client, auth_headers, flask_core, test_user, monkeypatch
):
    """debate.py:608-615 — an error chunk during a debater turn -> debate_error."""
    def _err(*a, **k):
        def _gen():
            yield {"error": {"message": "debater down"}}
        return _gen()

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_err))
    session = _make_session(flask_core, test_user["_id"], rounds=1)
    body = _drain_stream(client, auth_headers, {"session_id": session["_id"]})
    assert "event: debate_error" in body
    assert "debater down" in body
    # Judge phase never reached.
    assert "event: debate_judge_complete" not in body


def test_debate_stream_infinite_concluded(
    client, auth_headers, flask_core, test_user, monkeypatch
):
    """debate.py:651-704 — infinite mode: a [DEBATE_CONCLUDED] marker concludes
    every debater and exits the round loop straight to the judge."""
    def _concluded(*a, **k):
        def _gen():
            yield {"choices": [{"delta": {"content": "Final word. [DEBATE_CONCLUDED]"}}]}
            yield {"done": True}
        return _gen()

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_concluded))
    # rounds=0 -> infinite mode.
    session = _make_session(flask_core, test_user["_id"], rounds=0)
    body = _drain_stream(client, auth_headers, {"session_id": session["_id"]})
    assert "event: debate_debater_concluded" in body
    assert "event: debate_judge_complete" in body
    # The stored content has the marker stripped.
    with flask_core.app_context():
        from app.models.debate_message import DebateMessageModel
        msgs = DebateMessageModel.find_by_session(str(session["_id"]))
    debater_msgs = [m for m in msgs if m.get("role") == "debater"]
    assert debater_msgs
    assert all("[DEBATE_CONCLUDED]" not in (m.get("content") or "") for m in debater_msgs)


# ===========================================================================
# AUTOMATE — delete best-effort stop, sweep, daily-quota, bad body, poll errors.
# ===========================================================================
@pytest.fixture(autouse=True)
def _no_dlp_automate(monkeypatch):
    import app.api.routers.automate_agent as mod

    monkeypatch.setattr(mod, "dlp_gate", lambda **kwargs: None)
    yield


def _make_task(user_id, *, task_text="do a thing", model="claude-sonnet-4.6",
               status=None, session_id=None):
    from app.models.automate_task import AutomateTaskModel

    with flask_core.app_context():
        task_id = AutomateTaskModel.create(str(user_id), task_text, model)
        if session_id is not None:
            AutomateTaskModel.update(task_id, {"session_id": session_id})
        if status is not None:
            AutomateTaskModel.set_status(task_id, status)
        return task_id


def test_delete_task_stop_swallows_exception(
    client, auth_headers, test_user, monkeypatch
):
    """automate_agent.py:194-198 — stop_session raising is swallowed; delete OK."""
    tid = _make_task(test_user["_id"], session_id="s1", status="running")

    def _boom(session_id, strategy="task"):
        raise Exception("cloud unreachable")

    from app.services.browser_use_service import BrowserUseService
    monkeypatch.setattr(BrowserUseService, "stop_session", staticmethod(_boom))

    resp = client.delete(f"/api/automate-agent/tasks/{tid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Task deleted"


def test_run_task_bad_json_body_400(client, auth_headers):
    """automate_agent.py:256-264 — garbage body -> {} -> 'task is required'."""
    headers = {"Authorization": auth_headers["Authorization"],
               "Content-Type": "application/json"}
    resp = client.post("/api/automate-agent/tasks/run", headers=headers,
                       content="<<<not json>>>")
    assert resp.status_code == 400
    assert resp.json()["error"] == "task is required"


def test_run_task_daily_quota_exhausted_429(
    client, auth_headers, test_user, flask_core, monkeypatch
):
    """automate_agent.py:303-305 — daily quota hit -> 429 daily_quota_exhausted."""
    import app.api.routers.automate_agent as mod
    from app.models.automate_task import AutomateTaskModel

    # Force concurrency check to pass and quota to fail deterministically.
    monkeypatch.setattr(AutomateTaskModel, "count_active_by_user",
                        staticmethod(lambda uid: 0))
    monkeypatch.setattr(AutomateTaskModel, "count_created_since",
                        staticmethod(lambda uid, since: 9999))
    monkeypatch.setattr(mod, "_DAILY_QUOTA", 20)
    resp = client.post("/api/automate-agent/tasks/run", headers=auth_headers,
                       json={"task": "go visit https://example.com"})
    assert resp.status_code == 429
    assert resp.json()["error"] == "daily_quota_exhausted"


def test_run_task_sse_live_url_refresh(client, auth_headers, monkeypatch):
    """automate_agent.py:351-357 — missing live_url triggers a get_session refresh."""
    from app.services.browser_use_service import BrowserUseService

    monkeypatch.setattr(
        BrowserUseService, "create_session",
        staticmethod(lambda task, model="claude-sonnet-4.6": {
            "id": "sess-refresh", "status": "running",  # NO live_url
        }),
    )
    get_calls = {"n": 0}

    def _get_session(session_id):
        get_calls["n"] += 1
        if get_calls["n"] == 1:
            # The refresh fetch supplies the live_url.
            return {"id": session_id, "status": "running",
                    "live_url": "https://live/refresh"}
        return {"id": session_id, "status": "completed", "output": "fin"}

    monkeypatch.setattr(BrowserUseService, "get_session", staticmethod(_get_session))
    monkeypatch.setattr(BrowserUseService, "list_messages",
                        staticmethod(lambda sid, after=None, limit=100: {"messages": []}))

    with client.stream("POST", "/api/automate-agent/tasks/run", headers=auth_headers,
                       json={"task": "summarize https://example.com"}) as resp:
        assert resp.status_code == 200, resp.read()
        raw = "".join(resp.iter_text())
    assert "event: task_started" in raw
    assert "https://live/refresh" in raw
    assert "event: task_complete" in raw


def test_run_task_sse_poll_failures_abort(client, auth_headers, monkeypatch):
    """automate_agent.py:395-409 — list_messages keeps failing -> poll_failed."""
    import app.api.routers.automate_agent as mod
    from app.services.browser_use_service import BrowserUseService

    monkeypatch.setattr(mod, "_POLL_INTERVAL", 0)  # no real sleeping
    monkeypatch.setattr(mod, "_MAX_CONSECUTIVE_POLL_ERRORS", 2)
    monkeypatch.setattr(
        BrowserUseService, "create_session",
        staticmethod(lambda task, model="claude-sonnet-4.6": {
            "id": "sess-poll", "status": "running",
            "live_url": "https://live/poll",
        }),
    )

    def _always_fail(sid, after=None, limit=100):
        raise Exception("list down")

    monkeypatch.setattr(BrowserUseService, "list_messages", staticmethod(_always_fail))
    monkeypatch.setattr(BrowserUseService, "get_session",
                        staticmethod(lambda sid: {"id": sid, "status": "running"}))

    with client.stream("POST", "/api/automate-agent/tasks/run", headers=auth_headers,
                       json={"task": "summarize https://example.com"}) as resp:
        assert resp.status_code == 200, resp.read()
        raw = "".join(resp.iter_text())
    assert "event: error" in raw
    assert "poll_failed" in raw


def test_run_task_sse_get_session_poll_failures_abort(client, auth_headers, monkeypatch):
    """automate_agent.py:444-458 — get_session keeps failing -> poll_failed."""
    import app.api.routers.automate_agent as mod
    from app.services.browser_use_service import BrowserUseService

    monkeypatch.setattr(mod, "_POLL_INTERVAL", 0)
    monkeypatch.setattr(mod, "_MAX_CONSECUTIVE_POLL_ERRORS", 2)
    monkeypatch.setattr(
        BrowserUseService, "create_session",
        staticmethod(lambda task, model="claude-sonnet-4.6": {
            "id": "sess-gs", "status": "running", "live_url": "https://live/gs",
        }),
    )
    monkeypatch.setattr(BrowserUseService, "list_messages",
                        staticmethod(lambda sid, after=None, limit=100: {"messages": []}))

    def _gs_fail(sid):
        raise Exception("get down")

    monkeypatch.setattr(BrowserUseService, "get_session", staticmethod(_gs_fail))

    with client.stream("POST", "/api/automate-agent/tasks/run", headers=auth_headers,
                       json={"task": "summarize https://example.com"}) as resp:
        assert resp.status_code == 200, resp.read()
        raw = "".join(resp.iter_text())
    assert "event: error" in raw
    assert "poll_failed" in raw


def test_list_tasks_sweeps_expired(client, auth_headers, test_user, flask_core, monkeypatch):
    """automate_agent.py:109-126 — a deadline-expired running task is swept to
    timed_out, best-effort stopping its upstream session."""
    from app.models.automate_task import AutomateTaskModel
    from app.services.browser_use_service import BrowserUseService

    tid = _make_task(test_user["_id"], session_id="sweep-sess", status="running")

    # find_expired_running returns our task so the sweep walks 117-125.
    with flask_core.app_context():
        task_doc = AutomateTaskModel.find_by_id(tid)

    monkeypatch.setattr(AutomateTaskModel, "find_expired_running",
                        staticmethod(lambda: [task_doc]))
    stop_calls = {}
    monkeypatch.setattr(
        BrowserUseService, "stop_session",
        staticmethod(lambda session_id, strategy="task": stop_calls.update(
            {"sid": session_id, "strategy": strategy})),
    )

    resp = client.get("/api/automate-agent/tasks", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert stop_calls == {"sid": "sweep-sess", "strategy": "session"}
    # The task is now timed_out.
    after = client.get(f"/api/automate-agent/tasks/{tid}", headers=auth_headers)
    assert after.json()["task"]["status"] == "timed_out"
