"""Coverage-focused tests for app/api/routers/presentations.py.

Targets the router contract:
  * the ``presentations`` feature gate (OFF -> 404 ``feature_disabled``);
  * owner-scoped IDOR — a missing/foreign deck id is a 404, the list is empty
    for a fresh user;
  * the happy-path outline SSE round-trip (persists a ``presentations`` row);
  * the happy-path render SSE round-trip (persists a .pptx ``uploads`` row and
    emits a ``file`` artifact, deck status -> ``ready`` + ``pptx_upload_id``).

NO network: ``presentation_service.generate_outline`` is monkeypatched. The
happy outline carries ``image_prompt=None`` on every slide, so the render fans
out ZERO ``OpenRouterService.generate_image`` calls — the .pptx is built purely
by ``PptxRenderer`` (python-pptx, offline). DLP no-ops on a falsy workspace_id
(personal scope) and the spend gate no-ops while ``billing_enforcement`` is OFF
(both defaults), so the gates pass without setup.

Mirrors tests/api/conftest.py fixtures (real model facades on Postgres via the
flask_ctx bridge) + the meetings cov file's feature-enable + SSE-drain patterns.
SSE streams are FULLY drained (``iter_text``) so the per-test TRUNCATE isn't
blocked by an 'idle in transaction' backend (CLAUDE.md SSE gotcha).
"""
import json
import uuid

import pytest

import app.api.routers.presentations as pres_router


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------
@pytest.fixture
def enable_presentations(flask_core):
    """Flip the platform ``presentations`` flag ON (default is OFF)."""
    from app.models.platform_settings import PlatformSettingsModel

    with flask_core.app_context():
        PlatformSettingsModel.set_feature("presentations", True, None)
    yield


@pytest.fixture
def upload_tmpdir(flask_core, tmp_path):
    """Point UPLOAD_FOLDER at a tmp dir so the rendered .pptx lands there."""
    cfg = flask_core.config
    saved = cfg.get("UPLOAD_FOLDER")
    cfg["UPLOAD_FOLDER"] = str(tmp_path)
    yield cfg
    cfg["UPLOAD_FOLDER"] = saved


# Single-slide outline with NO image_prompt -> render generates ZERO images.
def _no_image_outline(title="Test Deck", language="fa"):
    return {
        "title": title,
        "language": language,
        "slides": [
            {
                "layout": "content",
                "title": "Slide A",
                "bullets": ["point one", "point two"],
                "speaker_notes": "",
                "image_prompt": None,
            }
        ],
    }


def _sse_events(body: str):
    """Parse an SSE body into ``[(event_type, data_dict), ...]``."""
    events = []
    for frame in body.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        etype = None
        data = None
        for line in frame.splitlines():
            if line.startswith("event:"):
                etype = line[len("event:"):].strip()
            elif line.startswith("data:"):
                raw = line[len("data:"):].strip()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = raw
        if etype is not None:
            events.append((etype, data))
    return events


def _first(events, etype):
    for et, data in events:
        if et == etype:
            return data
    return None


# ===========================================================================
# Feature gate OFF -> 404 (feature looks absent). feature_dep raises 404 with
# {"error":"feature_disabled","feature":"presentations","status":404}.
# ===========================================================================
def test_outline_feature_off_404(client, auth_headers):
    resp = client.post("/api/presentations/outline", headers=auth_headers,
                       json={"topic": "anything"})
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"] == "feature_disabled"
    assert body["feature"] == "presentations"


def test_list_feature_off_404(client, auth_headers):
    resp = client.get("/api/presentations", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "feature_disabled"


def test_get_feature_off_404(client, auth_headers):
    resp = client.get(f"/api/presentations/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "feature_disabled"


# ===========================================================================
# Feature gate ON -> reachable. IDOR / list-empty.
# ===========================================================================
def test_get_missing_id_404(client, auth_headers, enable_presentations):
    resp = client.get(
        "/api/presentations/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "Presentation not found"


def test_get_foreign_deck_404(client, flask_core, test_user, plain_user,
                              plain_headers, enable_presentations):
    # A deck owned by test_user, fetched by plain_user -> owner-scope 404.
    from app.models.presentation import PresentationModel

    with flask_core.app_context():
        rec = PresentationModel.create(
            user_id=str(test_user["_id"]),
            title="Owner Only",
            outline=_no_image_outline(),
            status="outline_ready",
        )
    resp = client.get(f"/api/presentations/{rec['_id']}", headers=plain_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Presentation not found"


def test_list_empty_for_fresh_user(client, auth_headers, enable_presentations):
    resp = client.get("/api/presentations", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"presentations": []}


def test_list_returns_owned_only(client, flask_core, test_user, plain_user,
                                 auth_headers, enable_presentations):
    from app.models.presentation import PresentationModel

    with flask_core.app_context():
        PresentationModel.create(user_id=str(test_user["_id"]), title="Mine",
                                 outline=_no_image_outline(), status="outline_ready")
        PresentationModel.create(user_id=str(plain_user["_id"]), title="Theirs",
                                 outline=_no_image_outline(), status="outline_ready")
    resp = client.get("/api/presentations", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()["presentations"]
    assert len(rows) == 1
    assert rows[0]["title"] == "Mine"


# ===========================================================================
# Outline SSE — validation + happy path (generate_outline monkeypatched).
# ===========================================================================
def test_outline_requires_topic_400(client, auth_headers, enable_presentations):
    resp = client.post("/api/presentations/outline", headers=auth_headers,
                       json={"topic": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"] == "topic is required"


def test_outline_happy_path_persists_row(client, auth_headers, test_user,
                                         flask_core, enable_presentations, monkeypatch):
    # Patch the service symbol the router looks up (psvc.generate_outline) so NO
    # OpenRouter call happens. Personal scope (no workspace_id) -> DLP no-ops;
    # billing_enforcement OFF -> spend gate no-ops.
    captured = {}

    def fake_outline(**kwargs):
        captured.update(kwargs)
        return _no_image_outline(title="Generated Title", language="fa")

    monkeypatch.setattr(pres_router.psvc, "generate_outline", fake_outline)

    with client.stream("POST", "/api/presentations/outline", headers=auth_headers,
                       json={"topic": "quarterly results", "slide_count": 1}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    events = _sse_events(body)
    types = [et for et, _ in events]
    assert "status" in types
    outline_evt = _first(events, "outline")
    assert outline_evt is not None, body
    new_id = outline_evt["id"]
    assert outline_evt["outline"]["title"] == "Generated Title"
    assert _first(events, "done")["id"] == new_id
    # The service was called with the request topic.
    assert captured["topic"] == "quarterly results"

    # Row persisted, owner-scoped, status outline_ready.
    got = client.get(f"/api/presentations/{new_id}", headers=auth_headers)
    assert got.status_code == 200
    rec = got.json()
    assert rec["status"] == "outline_ready"
    assert rec["title"] == "Generated Title"
    assert rec["outline"]["slides"][0]["title"] == "Slide A"


def test_outline_empty_slides_no_row(client, auth_headers, flask_core,
                                     enable_presentations, monkeypatch):
    # An outline with no slides surfaces an error frame and persists NO row.
    monkeypatch.setattr(
        pres_router.psvc, "generate_outline",
        lambda **kw: {"title": "x", "language": "fa", "slides": []},
    )
    with client.stream("POST", "/api/presentations/outline", headers=auth_headers,
                       json={"topic": "empty"}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    events = _sse_events(body)
    assert _first(events, "error") is not None
    assert _first(events, "outline") is None
    # No deck was created.
    listed = client.get("/api/presentations", headers=auth_headers)
    assert listed.json()["presentations"] == []


# ===========================================================================
# Render SSE — happy path (no images -> no network), persistence + IDOR.
# ===========================================================================
def test_render_missing_id_404(client, auth_headers, enable_presentations):
    resp = client.post(f"/api/presentations/{uuid.uuid4()}/render",
                       headers=auth_headers, json={})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Presentation not found"


def test_render_foreign_deck_404(client, flask_core, test_user, plain_headers,
                                 enable_presentations):
    from app.models.presentation import PresentationModel

    with flask_core.app_context():
        rec = PresentationModel.create(
            user_id=str(test_user["_id"]),
            title="Owner Only",
            outline=_no_image_outline(),
            status="outline_ready",
            options={"generate_images": False},
        )
    resp = client.post(f"/api/presentations/{rec['_id']}/render",
                       headers=plain_headers, json={})
    assert resp.status_code == 404


def test_render_happy_path_persists_upload(client, auth_headers, test_user,
                                           flask_core, enable_presentations,
                                           upload_tmpdir, monkeypatch):
    # A no-image deck renders text-only -> ZERO generate_image calls. Guard that
    # invariant: if the router ever tries an image call, the test fails loudly.
    from app.models.presentation import PresentationModel
    from app.services.openrouter_service import OpenRouterService

    def _no_network(*_a, **_k):
        raise AssertionError("generate_image must not be called for a no-image deck")

    monkeypatch.setattr(OpenRouterService, "generate_image", staticmethod(_no_network))

    with flask_core.app_context():
        rec = PresentationModel.create(
            user_id=str(test_user["_id"]),
            title="Renderable",
            outline=_no_image_outline(title="Renderable"),
            status="outline_ready",
            options={"generate_images": True},  # gen on, but no image_prompt slides
        )
    pid = rec["_id"]

    with client.stream("POST", f"/api/presentations/{pid}/render",
                       headers=auth_headers, json={}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    events = _sse_events(body)
    file_evt = _first(events, "file")
    assert file_evt is not None, body
    assert file_evt["ext"] == "pptx"
    assert file_evt["url"].startswith("/api/uploads/")
    assert file_evt["size"] > 0
    assert _first(events, "done")["id"] == pid
    # No 'rendering'/'imaging' status frame is required, but a 'rendering' phase
    # is always emitted before the render.
    assert any(
        et == "status" and isinstance(d, dict) and d.get("phase") == "rendering"
        for et, d in events
    ), body

    upload_id = file_evt["upload_id"]

    # Deck flipped to ready + carries the pptx upload id.
    got = client.get(f"/api/presentations/{pid}", headers=auth_headers)
    assert got.status_code == 200
    deck = got.json()
    assert deck["status"] == "ready"
    assert deck["pptx_upload_id"] == upload_id

    # The upload row exists, owner-scoped, and is a .pptx.
    with flask_core.app_context():
        from app.models.upload import UploadModel

        up = UploadModel.find_by_id_for_user(upload_id, str(test_user["_id"]))
    assert up is not None
    assert up["mime_type"] == pres_router._PPTX_MIME


def test_render_inline_outline_overrides_persisted(client, auth_headers, test_user,
                                                   flask_core, enable_presentations,
                                                   upload_tmpdir, monkeypatch):
    # A body-supplied outline (post-edit) overrides the stored one and is what
    # gets persisted back on the deck.
    from app.models.presentation import PresentationModel
    from app.services.openrouter_service import OpenRouterService

    monkeypatch.setattr(
        OpenRouterService, "generate_image",
        staticmethod(lambda *a, **k: (_ for _ in ()).throw(AssertionError("no images"))),
    )

    with flask_core.app_context():
        rec = PresentationModel.create(
            user_id=str(test_user["_id"]),
            title="Original",
            outline=_no_image_outline(title="Original"),
            status="outline_ready",
            options={"generate_images": False},
        )
    pid = rec["_id"]

    edited = _no_image_outline(title="Edited Title")
    edited["slides"][0]["title"] = "Edited Slide"

    with client.stream("POST", f"/api/presentations/{pid}/render",
                       headers=auth_headers, json={"outline": edited}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    events = _sse_events(body)
    assert _first(events, "file") is not None, body

    got = client.get(f"/api/presentations/{pid}", headers=auth_headers).json()
    assert got["status"] == "ready"
    assert got["outline"]["slides"][0]["title"] == "Edited Slide"
