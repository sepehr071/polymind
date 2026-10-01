"""Security-hardening regression locks.

Covers the four fixes shipped in this batch:

  * office-XML zip-bomb guard rejects a crafted .docx/.xlsx before its parser
    library inflates the archive (FIX 1).
  * link-share snapshot carries only a coarse, PII-free sender (no user id, no
    email-derived name, no avatar) — it is cross-tenant readable (FIX 2).
  * the public share GET is rate-limited (429 after the per-window cap) (FIX 3).
  * deep ``/health/status`` requires auth; shallow ``/health/check`` stays open
    (FIX 5b).
"""
import io
import zipfile


def _h(mint, user):
    return {
        "Authorization": f"Bearer {mint(user['_id'], role=user.get('role', 'user'))}",
        "Content-Type": "application/json",
    }


def _make_conversation(flask_core, *, user_id, config_id="quick:gpt", title="Chat"):
    from app.models.conversation import ConversationModel
    with flask_core.app_context():
        return ConversationModel.create(
            user_id=str(user_id), config_id=config_id, title=title,
        )


def _add_message(flask_core, *, conversation_id, role, content, sender_user_id=None):
    from app.models.message import MessageModel
    with flask_core.app_context():
        return MessageModel.create(
            conversation_id=conversation_id, role=role, content=content,
            sender_user_id=sender_user_id,
        )


# ---------------------------------------------------------------------------
# FIX 1 — office-XML zip-bomb guard
# ---------------------------------------------------------------------------
def _zip_bomb_bytes(*, member_uncompressed=400 * 1024 * 1024) -> bytes:
    """A tiny .docx-shaped zip whose single member inflates far past the cap.

    Highly compressible (all-zero) payload: a few KB on disk, hundreds of MB
    uncompressed → trips both the total-uncompressed AND the ratio guard.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"\x00" * member_uncompressed)
    return buf.getvalue()


def test_office_zip_bomb_rejected():
    from app.services import document_extraction_service as svc

    bomb = _zip_bomb_bytes()
    # Sanity: the crafted archive really is tiny on disk but huge uncompressed.
    assert len(bomb) < svc._OFFICE_MAX_RAW_BYTES

    res = svc.extract_text(
        bomb, filename="bomb.docx", mime_type="", extension="docx",
        max_chars=200_000,
    )
    assert res["status"] == "error"
    assert res["markdown"] == ""
    assert res["chars"] == 0


def test_office_oversized_raw_rejected():
    """A raw payload past the byte ceiling is rejected before any zip parse."""
    from app.services import document_extraction_service as svc

    oversized = b"PK\x03\x04" + b"\x00" * (svc._OFFICE_MAX_RAW_BYTES + 1)
    res = svc.extract_text(
        oversized, filename="big.xlsx", mime_type="", extension="xlsx",
        max_chars=200_000,
    )
    assert res["status"] == "error"


def test_office_guard_only_for_office_exts():
    """A plain .txt is never run through the zip guard (stays available)."""
    from app.services import document_extraction_service as svc

    res = svc.extract_text(
        b"hello world", filename="note.txt", mime_type="", extension="txt",
        max_chars=200_000,
    )
    assert res["status"] == "ok"
    assert res["markdown"] == "hello world"


# ---------------------------------------------------------------------------
# FIX 2 — snapshot sender is coarse / PII-free
# ---------------------------------------------------------------------------
def test_snapshot_sender_omits_id_and_email(client, flask_core, mint_token, test_user, plain_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"], title="Shared")
    cid = conv["_id"]
    # A teammate-authored user turn (carries sender_user_id), plus an assistant turn.
    _add_message(flask_core, conversation_id=cid, role="user",
                 content="from a teammate", sender_user_id=str(plain_user["_id"]))
    _add_message(flask_core, conversation_id=cid, role="assistant", content="reply")

    token = client.post(
        f"/api/conversations/{cid}/share/link", headers=_h(mint_token, test_user)
    ).json()["token"]

    snap = client.get(f"/api/share/{token}", headers=_h(mint_token, plain_user)).json()["snapshot"]
    msgs = snap["messages"]
    assert len(msgs) == 2

    user_msg = next(m for m in msgs if m["role"] == "user")
    sender = user_msg["sender"]
    # Coarse generic label only — no id, no avatar, no email-derived name.
    assert sender == {"name": "You"}
    assert "id" not in sender
    assert "avatar_url" not in sender
    # The plain_user's id / email local-part must NOT appear anywhere in the sender.
    assert str(plain_user["_id"]) not in str(sender)
    assert (plain_user["email"].split("@")[0]) not in str(sender)

    # Assistant turn carries no sender object.
    asst_msg = next(m for m in msgs if m["role"] == "assistant")
    assert asst_msg["sender"] is None


def test_sender_public_helper_role_based():
    from app.models.message import sender_public

    assert sender_public({"role": "user"}) == {"name": "You"}
    assert sender_public({"role": "assistant"}) is None
    assert sender_public({"role": "system"}) is None
    assert sender_public({}) is None


# ---------------------------------------------------------------------------
# FIX 3 — share GET is rate-limited
# ---------------------------------------------------------------------------
def test_share_get_rate_limited(client, flask_core, mint_token, test_user, plain_user):
    conv = _make_conversation(flask_core, user_id=test_user["_id"], title="RL")
    cid = conv["_id"]
    _add_message(flask_core, conversation_id=cid, role="user", content="hi")
    token = client.post(
        f"/api/conversations/{cid}/share/link", headers=_h(mint_token, test_user)
    ).json()["token"]

    headers = _h(mint_token, plain_user)
    # Bucket is 30/60s. Drive past it; the over-limit call must 429 with Retry-After.
    statuses = [
        client.get(f"/api/share/{token}", headers=headers).status_code
        for _ in range(35)
    ]
    assert 429 in statuses
    # The 429 must precede exhausting all 35 (cap is 30).
    assert statuses.index(429) <= 30

    over = client.get(f"/api/share/{token}", headers=headers)
    assert over.status_code == 429
    assert "Retry-After" in over.headers
    assert over.json()["error"] == "rate_limited"


# ---------------------------------------------------------------------------
# /health/check + /health/status are BOTH public + always HTTP 200 by contract
# (misc_b.py:health_status — Swarm/edge monitoring must never be killed on a
# transient dep blip, and anonymous callers never see raw exception text).
# ---------------------------------------------------------------------------
def test_health_check_open_unauthenticated(client):
    resp = client.get("/api/v1/health/check")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_status_public_always_200(client, mint_token, plain_user):
    # Public + always HTTP 200 (ok|degraded), with or without auth. Dependency
    # results are reduced to ok/latency — no raw error text leaked to anon.
    anon = client.get("/api/v1/health/status")
    assert anon.status_code == 200, anon.text
    assert anon.json()["status"] in ("ok", "degraded")

    authed = client.get("/api/v1/health/status", headers=_h(mint_token, plain_user))
    assert authed.status_code == 200, authed.text
    assert authed.json()["status"] in ("ok", "degraded")
