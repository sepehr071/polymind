"""Integration tests for the uploads + image-generation FastAPI routers.

Mirrors tests/api/test_auth.py: real model facades on Postgres via the
flask_ctx bridge, legacy-shaped JSON assertions (``_id``/``id`` alias). The
upload disk writer + thumbnailing + content-sniffing run for real against an
isolated tmp UPLOAD_FOLDER; external upstreams (OpenRouter image generation,
the DLP gate) are monkeypatched so nothing hits a real provider.

Routers are mounted here defensively (``_mount_misc_a_routers``): the ALL_ROUTERS
wiring is a later serialized migration step, so the autouse fixture include_router's
the two routers onto the live FastAPI app iff their paths aren't already present.
"""
import io

import pytest

import app.api.routers.misc_a as misc_a


# ---------------------------------------------------------------------------
# Mount fixture — make the tests self-sufficient regardless of ALL_ROUTERS
# wiring order (the wiring step runs after this router agent).
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _mount_misc_a_routers(app):
    existing = {getattr(r, "path", None) for r in app.routes}
    if "/api/uploads/my" not in existing:
        app.include_router(misc_a.router, prefix="/api/uploads")
    if "/api/image-gen/generate" not in existing:
        app.include_router(misc_a.image_router, prefix="/api/image-gen")
    yield


@pytest.fixture
def upload_tmpdir(flask_core, tmp_path):
    """Point the upload writer at an isolated tmp dir + restore after."""
    cfg = flask_core.config
    saved = cfg.get("UPLOAD_FOLDER")
    cfg["UPLOAD_FOLDER"] = str(tmp_path)
    yield tmp_path
    cfg["UPLOAD_FOLDER"] = saved


def _png_bytes(color=(200, 30, 30), size=(8, 8)) -> bytes:
    """A real, sniffable PNG so filetype.guess() classifies it as image/png."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _make_image(flask_core, owner_id, *, prompt="a cat", model="google/x",
                favorite=False):
    from app.models.generated_image import GeneratedImageModel

    with flask_core.app_context():
        img = GeneratedImageModel.create(
            user_id=str(owner_id),
            prompt=prompt,
            model_id=model,
            image_data="data:image/png;base64,AAAA",
            metadata={"is_favorite": favorite} if favorite else None,
        )
    return img


# ===========================================================================
# UPLOADS — POST /file (happy path + validation).
# ===========================================================================
def test_upload_file_happy_path(client, auth_headers, upload_tmpdir, test_user):
    files = {"file": ("photo.png", _png_bytes(), "image/png")}
    headers = {"Authorization": auth_headers["Authorization"]}
    resp = client.post("/api/uploads/file", headers=headers, files=files)
    assert resp.status_code == 201, resp.text
    body = resp.json()["upload"]
    assert body["id"]
    assert body["type"] == "image"
    assert body["original_name"] == "photo.png"
    assert body["size"] > 0
    assert body["url"].endswith(f"/api/uploads/{body['id']}")
    # An image gets a thumbnail URL.
    assert body["thumbnail_url"] is not None
    # File actually landed on disk.
    assert (upload_tmpdir / body["filename"]).is_file()


def test_upload_file_no_part_400(client, auth_headers, upload_tmpdir):
    headers = {"Authorization": auth_headers["Authorization"]}
    resp = client.post("/api/uploads/file", headers=headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "No file provided"


def test_upload_file_disallowed_extension_400(client, auth_headers, upload_tmpdir):
    files = {"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")}
    headers = {"Authorization": auth_headers["Authorization"]}
    resp = client.post("/api/uploads/file", headers=headers, files=files)
    assert resp.status_code == 400
    assert resp.json()["error"] == "File type not allowed"


def test_upload_file_mime_mismatch_400(client, auth_headers, upload_tmpdir):
    # Declared .png but the bytes sniff as a PDF -> the image extension
    # contradicts the sniffed (non-image) content -> 400 mime_mismatch.
    pdf_bytes = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n"
    files = {"file": ("fake.png", pdf_bytes, "image/png")}
    headers = {"Authorization": auth_headers["Authorization"]}
    resp = client.post("/api/uploads/file", headers=headers, files=files)
    assert resp.status_code == 400
    assert resp.json()["error"] == "mime_mismatch"


def test_upload_file_requires_auth_401(client, upload_tmpdir):
    files = {"file": ("photo.png", _png_bytes(), "image/png")}
    resp = client.post("/api/uploads/file", files=files)
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# UPLOADS — POST /image (image-extension gate).
# ===========================================================================
def test_upload_image_happy_path(client, auth_headers, upload_tmpdir):
    files = {"file": ("pic.png", _png_bytes(), "image/png")}
    headers = {"Authorization": auth_headers["Authorization"]}
    resp = client.post("/api/uploads/image", headers=headers, files=files)
    assert resp.status_code == 201, resp.text
    assert resp.json()["upload"]["type"] == "image"


def test_upload_image_rejects_non_image_extension_400(client, auth_headers, upload_tmpdir):
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    headers = {"Authorization": auth_headers["Authorization"]}
    resp = client.post("/api/uploads/image", headers=headers, files=files)
    assert resp.status_code == 400
    assert resp.json()["error"] == "File must be an image"


# ===========================================================================
# UPLOADS — GET /{upload_id} (owner-only serving, 404 oracle guard).
# ===========================================================================
def test_get_upload_owner_serves_file(client, auth_headers, upload_tmpdir):
    files = {"file": ("photo.png", _png_bytes(), "image/png")}
    headers = {"Authorization": auth_headers["Authorization"]}
    up = client.post("/api/uploads/file", headers=headers, files=files).json()["upload"]

    resp = client.get(f"/api/uploads/{up['id']}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("image/")
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_get_upload_non_owner_404_not_403(client, auth_headers, plain_headers, upload_tmpdir):
    files = {"file": ("photo.png", _png_bytes(), "image/png")}
    owner = {"Authorization": auth_headers["Authorization"]}
    up = client.post("/api/uploads/file", headers=owner, files=files).json()["upload"]

    # Different user -> 404 (existence oracle guard), never 403.
    resp = client.get(f"/api/uploads/{up['id']}", headers=plain_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Upload not found"


def test_get_upload_missing_404(client, auth_headers, upload_tmpdir):
    import uuid

    headers = {"Authorization": auth_headers["Authorization"]}
    resp = client.get(f"/api/uploads/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Upload not found"


def test_get_upload_requires_auth_401(client, upload_tmpdir):
    import uuid

    resp = client.get(f"/api/uploads/{uuid.uuid4()}")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# UPLOADS — GET /{upload_id}/thumbnail.
# ===========================================================================
def test_get_thumbnail_owner(client, auth_headers, upload_tmpdir):
    files = {"file": ("photo.png", _png_bytes(), "image/png")}
    headers = {"Authorization": auth_headers["Authorization"]}
    up = client.post("/api/uploads/file", headers=headers, files=files).json()["upload"]
    assert up["thumbnail_url"] is not None

    resp = client.get(f"/api/uploads/{up['id']}/thumbnail", headers=headers)
    assert resp.status_code == 200
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_get_thumbnail_non_owner_404(client, auth_headers, plain_headers, upload_tmpdir):
    files = {"file": ("photo.png", _png_bytes(), "image/png")}
    owner = {"Authorization": auth_headers["Authorization"]}
    up = client.post("/api/uploads/file", headers=owner, files=files).json()["upload"]

    resp = client.get(f"/api/uploads/{up['id']}/thumbnail", headers=plain_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Upload not found"


# ===========================================================================
# UPLOADS — GET /video/{filename} (public, traversal-guarded).
# ===========================================================================
def test_get_video_invalid_filename_400(client, upload_tmpdir):
    # Not an .mp4 -> 400.
    resp = client.get("/api/uploads/video/notavideo.txt")
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid filename"


def test_get_video_traversal_rejected_400(client, upload_tmpdir):
    # A path component is present (basename != filename) -> 400 traversal guard.
    resp = client.get("/api/uploads/video/sub/dir/clip.mp4")
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid filename"


def test_get_video_missing_404(client, upload_tmpdir):
    resp = client.get("/api/uploads/video/video_x_y.mp4")
    assert resp.status_code == 404
    assert resp.json()["error"] == "Video not found"


def test_get_video_serves_existing(client, upload_tmpdir):
    # Place a real mp4-named file in the upload dir; served public (no JWT).
    (upload_tmpdir / "video_u_g.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    resp = client.get("/api/uploads/video/video_u_g.mp4")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"


# ===========================================================================
# UPLOADS — DELETE /{upload_id}.
# ===========================================================================
def test_delete_upload_owner(client, auth_headers, upload_tmpdir):
    files = {"file": ("photo.png", _png_bytes(), "image/png")}
    headers = {"Authorization": auth_headers["Authorization"]}
    up = client.post("/api/uploads/file", headers=headers, files=files).json()["upload"]

    resp = client.delete(f"/api/uploads/{up['id']}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Upload deleted"
    # On-disk file gone.
    assert not (upload_tmpdir / up["filename"]).exists()
    # And the row is gone.
    assert client.get(f"/api/uploads/{up['id']}", headers=headers).status_code == 404


def test_delete_upload_non_owner_404(client, auth_headers, plain_headers, upload_tmpdir):
    files = {"file": ("photo.png", _png_bytes(), "image/png")}
    owner = {"Authorization": auth_headers["Authorization"]}
    up = client.post("/api/uploads/file", headers=owner, files=files).json()["upload"]

    resp = client.delete(f"/api/uploads/{up['id']}", headers=plain_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Upload not found"


def test_delete_upload_missing_404(client, auth_headers, upload_tmpdir):
    import uuid

    headers = {"Authorization": auth_headers["Authorization"]}
    resp = client.delete(f"/api/uploads/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


# ===========================================================================
# UPLOADS — GET /my (must NOT be shadowed by /{upload_id}).
# ===========================================================================
def test_my_uploads_lists_owned_with_id_alias(client, auth_headers, upload_tmpdir):
    headers = {"Authorization": auth_headers["Authorization"]}
    for _ in range(2):
        client.post("/api/uploads/file", headers=headers,
                    files={"file": ("p.png", _png_bytes(), "image/png")})

    resp = client.get("/api/uploads/my", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert len(body["uploads"]) == 2
    # Legacy _id alias survives serialize_doc; URLs appended.
    for u in body["uploads"]:
        assert "_id" in u
        assert u["url"].endswith(f"/api/uploads/{u['_id']}")


def test_my_uploads_requires_auth_401(client):
    resp = client.get("/api/uploads/my")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# IMAGE-GEN — GET /models.
# ===========================================================================
def test_image_models(client, auth_headers, monkeypatch):
    from app.services.openrouter_service import OpenRouterService

    monkeypatch.setattr(
        OpenRouterService, "get_image_capable_models",
        staticmethod(lambda: [{"id": "google/x", "name": "X"}]),
    )
    resp = client.get("/api/image-gen/models", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["models"][0]["id"] == "google/x"


def test_image_models_requires_auth_401(client):
    resp = client.get("/api/image-gen/models")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# IMAGE-GEN — POST /generate (happy path + validation + DLP + provider error).
# ===========================================================================
# Permissive capability map for the test model. The route resolves caps via
# OpenRouterService.get_image_capabilities(model) before gating; for the dummy
# "google/x" id we patch it to a wide-open set so non-capability tests proceed.
_WIDE_CAPS = {
    "resolution": {"supported": True, "values": ["512", "1K", "2K", "4K"]},
    "aspect_ratio": {"supported": True, "values": ["1:1", "16:9", "9:16", "4:5", "3:2"]},
    "n": {"supported": True, "min": 1, "max": 10},
    "seed": {"supported": True},
    "quality": {"supported": True, "values": ["auto", "low", "medium", "high"]},
    "output_format": {"supported": True, "values": ["png", "jpeg", "webp"]},
    "background": {"supported": True, "values": ["auto", "opaque", "transparent"]},
    "output_compression": {"supported": True, "min": 0, "max": 100},
    "input_references": {"supported": True, "max": 14},
}


def _stub_caps(monkeypatch, caps=None):
    """Patch the model's resolved capabilities (route gating reads this)."""
    from app.services.openrouter_service import OpenRouterService

    resolved = caps if caps is not None else _WIDE_CAPS
    monkeypatch.setattr(
        OpenRouterService, "get_image_capabilities",
        staticmethod(lambda model_id: resolved),
    )


def _gen_result(images=None, **extra):
    imgs = images if images is not None else ["data:image/png;base64,ZmFrZQ=="]
    out = {
        "success": True,
        "images": imgs,
        "image_data": imgs[0],
        "usage": {"cost": 0.01},
        "cost_usd_total": 0.01,
        "tokens_total": 100,
        "n": len(imgs),
    }
    out.update(extra)
    return out


def _stub_generate_ok(monkeypatch):
    from app.services.openrouter_service import OpenRouterService

    _stub_caps(monkeypatch)

    def _fake(*args, **kwargs):
        return _gen_result()

    monkeypatch.setattr(OpenRouterService, "generate_image", staticmethod(_fake))


def test_generate_happy_path(client, auth_headers, monkeypatch):
    _stub_generate_ok(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "a fox", "model": "google/x"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["image_data"].startswith("data:image/png")
    # The persisted entity carries the legacy _id alias.
    assert "_id" in body["image"]
    assert body["image"]["prompt"] == "a fox"
    assert body["image"]["model_id"] == "google/x"


def test_generate_missing_prompt_400(client, auth_headers, monkeypatch):
    _stub_generate_ok(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"model": "google/x"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Prompt is required"


def test_generate_missing_model_400(client, auth_headers, monkeypatch):
    _stub_generate_ok(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "a fox"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Model is required"


def test_generate_input_images_not_list_400(client, auth_headers, monkeypatch):
    _stub_generate_ok(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "x", "model": "google/x",
                             "input_images": "nope"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "input_images must be a list"


def test_generate_input_images_bad_format_400(client, auth_headers, monkeypatch):
    _stub_generate_ok(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "x", "model": "google/x",
                             "input_images": ["ftp://bad"]})
    assert resp.status_code == 400
    assert "Invalid image format" in resp.json()["error"]


def test_generate_input_images_capped_to_limit(client, auth_headers, monkeypatch):
    """Over-limit input_images are silently capped (overflow dropped from the
    end) rather than 400'd — the combined assistant/parent/user list is trimmed
    to the model's input_references.max capability before generation."""
    from app.services.openrouter_service import OpenRouterService

    # Cap the model to a single reference slot via its capabilities.
    caps = {**_WIDE_CAPS, "input_references": {"supported": True, "max": 1}}
    _stub_caps(monkeypatch, caps)
    captured = {}

    def _fake(*args, **kwargs):
        captured["input_images"] = kwargs.get("input_images")
        return _gen_result()

    monkeypatch.setattr(OpenRouterService, "generate_image", staticmethod(_fake))
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "x", "model": "google/x",
                             "input_images": ["http://a", "http://b"]})
    assert resp.status_code == 200, resp.text
    # Capped to the single allowed slot, keeping the first (priority) entry.
    assert captured["input_images"] == ["http://a"]


def test_generate_provider_failure_500(client, auth_headers, monkeypatch):
    from app.services.openrouter_service import OpenRouterService

    monkeypatch.setattr(
        OpenRouterService, "generate_image",
        staticmethod(lambda *a, **k: {"success": False, "error": "upstream boom"}),
    )
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "x", "model": "google/x"})
    assert resp.status_code == 500
    assert resp.json()["error"] == "upstream boom"


def _stub_generate_capture(monkeypatch, caps=None):
    """Like _stub_generate_ok but records the kwargs the route passed."""
    from app.services.openrouter_service import OpenRouterService

    _stub_caps(monkeypatch, caps)
    captured = {}

    def _fake(*args, **kwargs):
        captured.update(kwargs)
        return _gen_result()

    monkeypatch.setattr(OpenRouterService, "generate_image", staticmethod(_fake))
    return captured


def test_generate_aspect_ratio_passthrough_and_persist(client, auth_headers, monkeypatch):
    captured = _stub_generate_capture(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "a fox", "model": "google/x",
                             "aspect_ratio": "16:9"})
    assert resp.status_code == 200, resp.text
    assert captured["aspect_ratio"] == "16:9"
    assert resp.json()["image"]["settings"]["aspect_ratio"] == "16:9"


def test_generate_aspect_ratio_invalid_400(client, auth_headers, monkeypatch):
    _stub_generate_ok(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "a fox", "model": "google/x",
                             "aspect_ratio": "2:7"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid aspect_ratio"


def test_generate_aspect_ratio_omitted_not_persisted(client, auth_headers, monkeypatch):
    captured = _stub_generate_capture(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "a fox", "model": "google/x"})
    assert resp.status_code == 200, resp.text
    assert captured["aspect_ratio"] is None
    assert "aspect_ratio" not in resp.json()["image"]["settings"]


# ===========================================================================
# IMAGE-GEN — capability gating (Image API params validated vs model caps).
# ===========================================================================
def test_generate_unsupported_param_400(client, auth_headers, monkeypatch):
    """A param the model doesn't support -> 400 {error:'Model X does not support P'}."""
    _stub_generate_ok(monkeypatch)
    # Narrow caps: quality unsupported.
    caps = {**_WIDE_CAPS, "quality": {"supported": False, "values": []}}
    _stub_caps(monkeypatch, caps)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "a fox", "model": "google/x", "quality": "high"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Model google/x does not support quality"


def test_generate_invalid_enum_value_400(client, auth_headers, monkeypatch):
    """A supported enum param with an out-of-set value -> 400 {error:'Invalid P'}."""
    _stub_generate_ok(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "a fox", "model": "google/x", "quality": "ultra"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid quality"


def test_generate_seed_unsupported_400(client, auth_headers, monkeypatch):
    _stub_generate_ok(monkeypatch)
    caps = {**_WIDE_CAPS, "seed": {"supported": False}}
    _stub_caps(monkeypatch, caps)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "x", "model": "google/x", "seed": 7})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Model google/x does not support seed"


def test_generate_transparent_background_requires_png_webp_400(
    client, auth_headers, monkeypatch
):
    """Transparent background only with png/webp output (defense-in-depth)."""
    _stub_generate_ok(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "x", "model": "google/x",
                             "background": "transparent", "output_format": "jpeg"})
    assert resp.status_code == 400
    assert "Transparent background" in resp.json()["error"]


def test_generate_output_compression_clamped(client, auth_headers, monkeypatch):
    """output_compression clamps to 0-100 (defense-in-depth)."""
    captured = _stub_generate_capture(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "x", "model": "google/x",
                             "output_compression": 250})
    assert resp.status_code == 200, resp.text
    assert captured["output_compression"] == 100


def test_generate_n_clamped_to_model_max(client, auth_headers, monkeypatch):
    """n is clamped to the model's capability max (and a hard 10 ceiling)."""
    caps = {**_WIDE_CAPS, "n": {"supported": True, "min": 1, "max": 2}}
    captured = _stub_generate_capture(monkeypatch, caps)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "x", "model": "google/x", "n": 9})
    assert resp.status_code == 200, resp.text
    assert captured["n"] == 2


def test_generate_supported_params_forwarded_and_persisted(
    client, auth_headers, monkeypatch
):
    """Supported params pass through to generate_image AND persist on settings."""
    captured = _stub_generate_capture(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers, json={
        "prompt": "x", "model": "google/x", "resolution": "2K", "seed": 42,
        "output_format": "png", "background": "opaque", "aspect_ratio": "16:9",
    })
    assert resp.status_code == 200, resp.text
    assert captured["resolution"] == "2K"
    assert captured["seed"] == 42
    assert captured["output_format"] == "png"
    assert captured["background"] == "opaque"
    settings = resp.json()["image"]["settings"]
    assert settings["resolution"] == "2K"
    assert settings["seed"] == 42
    assert settings["output_format"] == "png"
    assert settings["background"] == "opaque"
    assert settings["aspect_ratio"] == "16:9"


# ===========================================================================
# IMAGE-GEN — batch (n>1) persistence + response shape.
# ===========================================================================
def test_generate_batch_persists_n_rows_with_shared_batch_id(
    client, auth_headers, monkeypatch
):
    """n>1 -> N GeneratedImage rows, all sharing one batch_id, with batch_index
    0..N-1 and the batch total cost split across rows."""
    from app.services.openrouter_service import OpenRouterService

    _stub_caps(monkeypatch)
    three = [f"data:image/png;base64,IMG{i}" for i in range(3)]
    monkeypatch.setattr(
        OpenRouterService, "generate_image",
        staticmethod(lambda *a, **k: _gen_result(
            images=three, cost_usd_total=0.06, tokens_total=900)),
    )
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "a fox", "model": "google/x", "n": 3})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Response carries the images[] list + a shared batch_id + conversation_id.
    assert "batch_id" in body and body["batch_id"]
    assert "conversation_id" in body
    assert len(body["images"]) == 3
    batch_ids = {img["settings"]["batch_id"] for img in body["images"]}
    assert batch_ids == {body["batch_id"]}
    assert [img["settings"]["batch_index"] for img in body["images"]] == [0, 1, 2]
    assert all(img["settings"]["batch_n"] == 3 for img in body["images"])
    # Per-image cost = batch total / n.
    assert all(img["cost_usd"] == pytest.approx(0.02) for img in body["images"])
    # Batch metadata preserves the totals.
    assert body["images"][0]["metadata"]["batch"]["total_cost_usd"] == pytest.approx(0.06)
    assert body["images"][0]["metadata"]["batch"]["n"] == 3


def test_generate_batch_back_compat_single_keys(client, auth_headers, monkeypatch):
    """Even for a batch, the legacy `image`/`image_data` keys point at the first."""
    from app.services.openrouter_service import OpenRouterService

    _stub_caps(monkeypatch)
    two = ["data:image/png;base64,FIRST", "data:image/png;base64,SECOND"]
    monkeypatch.setattr(
        OpenRouterService, "generate_image",
        staticmethod(lambda *a, **k: _gen_result(images=two)),
    )
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "a fox", "model": "google/x", "n": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["image_data"] == "data:image/png;base64,FIRST"
    assert body["image"]["_id"] == body["images"][0]["_id"]


def test_generate_dlp_blocked_403(client, auth_headers, monkeypatch):
    """DLPBlockedError from the gate is handled globally -> 403 {code, matches}."""
    _stub_generate_ok(monkeypatch)
    from app.services import dlp_gate

    def _raise(**kwargs):
        raise dlp_gate.DLPBlockedError(
            "dlp_blocked",
            [{
                "rule_id": "r1", "rule_name": "Secrets", "severity": "critical",
                "action": "block", "offset_start": 0, "offset_end": 3, "snippet": "***",
            }],
        )

    monkeypatch.setattr(dlp_gate, "gate", _raise)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "leak this", "model": "google/x"})
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "dlp_blocked"
    assert body["matches"][0]["rule_name"] == "Secrets"


def test_generate_requires_auth_401(client):
    resp = client.post("/api/image-gen/generate", json={"prompt": "x", "model": "y"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# IMAGE-GEN — GET /history.
# ===========================================================================
def test_history_lists_with_pagination(client, auth_headers, flask_core, test_user):
    for i in range(3):
        _make_image(flask_core, test_user["_id"], prompt=f"p{i}")

    resp = client.get("/api/image-gen/history", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["pages"] == 1
    assert len(body["images"]) == 3
    assert all("_id" in img for img in body["images"])


def test_history_favorites_only(client, auth_headers, flask_core, test_user):
    _make_image(flask_core, test_user["_id"], prompt="plain")
    _make_image(flask_core, test_user["_id"], prompt="fav", favorite=True)

    resp = client.get("/api/image-gen/history?favorites=true", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["images"][0]["prompt"] == "fav"


def test_history_search_filter(client, auth_headers, flask_core, test_user):
    """``search`` filters prompts case-insensitively; total/pages reflect the
    filter; a miss yields total=0; search composes with ``favorites``."""
    _make_image(flask_core, test_user["_id"], prompt="a Sunset over water")
    _make_image(flask_core, test_user["_id"], prompt="a mountain trail")
    _make_image(flask_core, test_user["_id"], prompt="sunset on a beach", favorite=True)

    # Case-insensitive substring hit -> only the two "sunset" prompts, and the
    # total/pages reflect the filtered count (not the 3 total rows).
    resp = client.get("/api/image-gen/history?search=SUNSET", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert body["pages"] == 1
    assert len(body["images"]) == 2
    assert all("sunset" in img["prompt"].lower() for img in body["images"])

    # A miss -> empty result with total 0.
    resp = client.get("/api/image-gen/history?search=zzznope", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["images"] == []

    # search + favorites compose: only the favorited "sunset" row survives.
    resp = client.get(
        "/api/image-gen/history?search=sunset&favorites=true", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["images"][0]["prompt"] == "sunset on a beach"


# ===========================================================================
# IMAGE-GEN — thumbnail (thumb_b64) contract.
# ===========================================================================
def test_generate_populates_thumb(client, auth_headers, monkeypatch):
    """A real raster payload yields a small WebP thumb on the persisted entity."""
    from app.services.openrouter_service import OpenRouterService

    png_uri = "data:image/png;base64," + (
        __import__("base64").b64encode(_png_bytes(size=(64, 48))).decode()
    )
    _stub_caps(monkeypatch)
    monkeypatch.setattr(
        OpenRouterService, "generate_image",
        staticmethod(lambda *a, **k: _gen_result(images=[png_uri], usage={})),
    )
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "a fox", "model": "google/x"})
    assert resp.status_code == 200, resp.text
    thumb = resp.json()["image"]["thumb"]
    assert thumb and thumb.startswith("data:image/webp;base64,")
    # The raw column key is never leaked under its DB name.
    assert "thumb_b64" not in resp.json()["image"]


def test_history_list_carries_thumb_without_full_payload(
    client, auth_headers, flask_core, test_user
):
    """The payload-less list ships `thumb` (real WebP for a real image) but no
    full `image_data`; an undecodable payload yields `thumb: null` (frontend
    falls back to the lazy full-by-id fetch)."""
    import base64

    png_uri = "data:image/png;base64," + base64.b64encode(_png_bytes()).decode()
    with flask_core.app_context():
        from app.models.generated_image import GeneratedImageModel
        GeneratedImageModel.create(
            user_id=str(test_user["_id"]), prompt="real", model_id="google/x",
            image_data=png_uri,
        )
    # A row whose payload can't decode -> thumb stays null.
    _make_image(flask_core, test_user["_id"], prompt="garbage")

    resp = client.get(
        "/api/image-gen/history?include_payload=false", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    by_prompt = {img["prompt"]: img for img in resp.json()["images"]}
    # List omits the heavy full-res payload entirely.
    for img in resp.json()["images"]:
        assert "image_data" not in img
        assert "b64_payload" not in img
        assert "thumb" in img  # key always present (value may be null)
    assert by_prompt["real"]["thumb"].startswith("data:image/webp;base64,")
    assert by_prompt["garbage"]["thumb"] is None


# ===========================================================================
# IMAGE-GEN — DELETE /{image_id}, favorite toggle, bulk-delete.
# ===========================================================================
def test_delete_image_owner(client, auth_headers, flask_core, test_user):
    img = _make_image(flask_core, test_user["_id"])
    resp = client.delete(f"/api/image-gen/{img['_id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Image deleted"


def test_delete_image_non_owner_403(client, auth_headers, plain_headers, flask_core, plain_user):
    img = _make_image(flask_core, plain_user["_id"])
    # auth_headers (manager) is NOT the owner -> 403 Unauthorized (matches Flask).
    resp = client.delete(f"/api/image-gen/{img['_id']}", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Unauthorized"


def test_delete_image_missing_404(client, auth_headers):
    import uuid

    resp = client.delete(f"/api/image-gen/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Image not found"


def test_toggle_favorite(client, auth_headers, flask_core, test_user):
    img = _make_image(flask_core, test_user["_id"])
    resp = client.post(f"/api/image-gen/{img['_id']}/favorite", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_favorite"] is True
    # Toggling again flips it back.
    resp2 = client.post(f"/api/image-gen/{img['_id']}/favorite", headers=auth_headers)
    assert resp2.json()["is_favorite"] is False


def test_toggle_favorite_non_owner_403(client, auth_headers, flask_core, plain_user):
    img = _make_image(flask_core, plain_user["_id"])
    resp = client.post(f"/api/image-gen/{img['_id']}/favorite", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Unauthorized"


def test_bulk_delete_images(client, auth_headers, flask_core, test_user):
    ids = [_make_image(flask_core, test_user["_id"])["_id"] for _ in range(3)]
    resp = client.post("/api/image-gen/bulk-delete", headers=auth_headers,
                       json={"image_ids": ids})
    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 3


def test_bulk_delete_empty_400(client, auth_headers):
    resp = client.post("/api/image-gen/bulk-delete", headers=auth_headers,
                       json={"image_ids": []})
    assert resp.status_code == 400
    assert resp.json()["error"] == "No images specified"


def test_bulk_delete_too_many_400(client, auth_headers):
    resp = client.post("/api/image-gen/bulk-delete", headers=auth_headers,
                       json={"image_ids": [f"id{i}" for i in range(51)]})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Maximum 50 images per request"


def test_bulk_delete_invalid_id_400(client, auth_headers):
    resp = client.post("/api/image-gen/bulk-delete", headers=auth_headers,
                       json={"image_ids": ["not-a-uuid"]})
    assert resp.status_code == 400
    assert "Invalid image ID" in resp.json()["error"]


# ===========================================================================
# Route-registration smoke.
# ===========================================================================
def test_misc_a_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/uploads/file" in paths
    assert "/api/uploads/image" in paths
    assert "/api/uploads/my" in paths
    assert "/api/uploads/{upload_id}" in paths
    assert "/api/uploads/{upload_id}/thumbnail" in paths
    assert "/api/uploads/video/{filename:path}" in paths
    assert "/api/image-gen/models" in paths
    assert "/api/image-gen/generate" in paths
    assert "/api/image-gen/history" in paths
    assert "/api/image-gen/{image_id}" in paths
    assert "/api/image-gen/bulk-delete" in paths
    assert "/api/image-gen/{image_id}/favorite" in paths
    assert "/api/image-gen/threads" in paths
    assert "/api/image-gen/threads/{cid}" in paths


# ===========================================================================
# IMAGE-GEN — conversational threads + image-assistant resolution.
# ===========================================================================
def test_generate_creates_thread_and_returns_conversation_id(
    client, auth_headers, monkeypatch
):
    """A plain single-shot generation now also opens a 1-image thread and
    returns its conversation_id (additive)."""
    _stub_generate_ok(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "a quiet fox in snow", "model": "google/x"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    cid = body["conversation_id"]
    assert cid
    assert body["image"]["conversation_id"] == cid

    # The thread is listed, titled from the first ~6 prompt words.
    lst = client.get("/api/image-gen/threads", headers=auth_headers)
    assert lst.status_code == 200
    threads = lst.json()["threads"]
    assert any(t["_id"] == cid for t in threads)
    match = next(t for t in threads if t["_id"] == cid)
    assert match["title"] == "a quiet fox in snow"
    assert match["image_count"] == 1


def test_generate_into_existing_thread(client, auth_headers, monkeypatch):
    _stub_generate_ok(monkeypatch)
    first = client.post("/api/image-gen/generate", headers=auth_headers,
                        json={"prompt": "base image", "model": "google/x"}).json()
    cid = first["conversation_id"]

    second = client.post("/api/image-gen/generate", headers=auth_headers,
                         json={"prompt": "now bluer", "model": "google/x",
                               "conversation_id": cid})
    assert second.status_code == 200, second.text
    assert second.json()["conversation_id"] == cid

    detail = client.get(f"/api/image-gen/threads/{cid}", headers=auth_headers)
    assert detail.status_code == 200
    imgs = detail.json()["images"]
    assert len(imgs) == 2
    # Thumbs only — no full base64 payload in the thread detail list.
    assert all("image_data" not in img for img in imgs)


def test_generate_unknown_thread_404(client, auth_headers, monkeypatch):
    _stub_generate_ok(monkeypatch)
    import uuid as _uuid
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "x", "model": "google/x",
                             "conversation_id": str(_uuid.uuid4())})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Thread not found"


def test_generate_with_parent_image_as_edit_base(
    client, auth_headers, monkeypatch, flask_core, test_user
):
    """parent_image_id's payload is forwarded as an input/edit base image."""
    captured = _stub_generate_capture(monkeypatch)
    parent = _make_image(flask_core, test_user["_id"], prompt="parent")

    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "edit it", "model": "google/x",
                             "parent_image_id": parent["_id"]})
    assert resp.status_code == 200, resp.text
    # The parent's stored data URI was passed as the edit base.
    assert captured["input_images"] == ["data:image/png;base64,AAAA"]
    assert resp.json()["image"]["parent_image_id"] == parent["_id"]


def test_generate_parent_image_non_owner_403(
    client, auth_headers, monkeypatch, flask_core, plain_user
):
    _stub_generate_ok(monkeypatch)
    other = _make_image(flask_core, plain_user["_id"], prompt="not yours")
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "x", "model": "google/x",
                             "parent_image_id": other["_id"]})
    assert resp.status_code == 403
    assert resp.json()["error"] == "Unauthorized"


def _make_image_assistant(flask_core, owner_id, *, model="google/assistant-model",
                          system_prompt="watercolor, soft pastel", base_images=None):
    from app.models.llm_config import LLMConfigModel

    with flask_core.app_context():
        return LLMConfigModel.create(
            name="Painter",
            model_id=model,
            model_name=model,
            owner_id=str(owner_id),
            system_prompt=system_prompt,
            visibility="private",
            parameters={"kind": "image", "base_images": base_images or []},
        )


def test_generate_with_image_assistant_overrides_model_and_preamble(
    client, auth_headers, monkeypatch, flask_core, test_user
):
    captured = _stub_generate_capture(monkeypatch)
    assistant = _make_image_assistant(flask_core, test_user["_id"])

    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "a castle", "config_id": assistant["_id"]})
    assert resp.status_code == 200, resp.text
    # Model came from the assistant (none supplied in the body).
    assert captured["model"] == "google/assistant-model"
    # The assistant system_prompt is prepended to the prompt actually sent.
    assert captured["prompt"] == "watercolor, soft pastel\n\na castle"
    # But the PERSISTED prompt is the user's raw text (no preamble).
    assert resp.json()["image"]["prompt"] == "a castle"
    assert resp.json()["image"]["settings"]["config_id"] == assistant["_id"]


def test_generate_with_non_image_assistant_400(
    client, auth_headers, monkeypatch, flask_core, test_user
):
    _stub_generate_ok(monkeypatch)
    from app.models.llm_config import LLMConfigModel
    with flask_core.app_context():
        text_cfg = LLMConfigModel.create(
            name="Chatter", model_id="m", model_name="m",
            owner_id=str(test_user["_id"]), system_prompt="be terse",
            visibility="private", parameters={"kind": "text"},
        )
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "x", "config_id": text_cfg["_id"]})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Not an image assistant"


def test_generate_missing_model_without_assistant_400(client, auth_headers, monkeypatch):
    _stub_generate_ok(monkeypatch)
    resp = client.post("/api/image-gen/generate", headers=auth_headers,
                       json={"prompt": "a fox"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Model is required"


def test_thread_rename_and_delete(client, auth_headers, monkeypatch):
    _stub_generate_ok(monkeypatch)
    cid = client.post("/api/image-gen/generate", headers=auth_headers,
                      json={"prompt": "orig", "model": "google/x"}).json()["conversation_id"]

    renamed = client.patch(f"/api/image-gen/threads/{cid}", headers=auth_headers,
                           json={"title": "My edits"})
    assert renamed.status_code == 200
    assert renamed.json()["conversation"]["title"] == "My edits"

    deleted = client.delete(f"/api/image-gen/threads/{cid}", headers=auth_headers)
    assert deleted.status_code == 200
    assert deleted.json()["message"] == "Thread deleted"

    # Gone afterwards.
    assert client.get(f"/api/image-gen/threads/{cid}", headers=auth_headers).status_code == 404


def test_thread_get_non_owner_404(client, auth_headers, flask_core, plain_user):
    from app.models.generated_image import ImageConversationModel
    with flask_core.app_context():
        conv = ImageConversationModel.create(user_id=str(plain_user["_id"]), title="theirs")
    resp = client.get(f"/api/image-gen/threads/{conv['_id']}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Thread not found"
