"""Unit tests for ``app/services/openrouter_service.py`` (coverage push).

These exercise the OpenRouterService pure/near-pure methods directly inside a
``flask_core.app_context()`` (no HTTP routes). All outbound OpenRouter traffic is
mocked at the ``app.services.openrouter_service._session`` boundary — we replace
``_session.request`` with a fake returning a stub response object exposing
``.status_code`` / ``.json()`` / ``.content`` / ``.headers`` / ``.iter_lines()`` /
``.iter_content()`` / ``.raise_for_status()`` — so nothing hits a real upstream.

``_record_usage`` is verified against real rows written to ``usage_logs`` via the
``UsageLogModel`` facade on the isolated Postgres ``_test`` DB.

Mirrors the style/imports/seeding of tests/api/test_chat.py.
"""
import json

import pytest
import requests

import app.services.openrouter_service as ors_mod
from app.services.openrouter_service import OpenRouterService


# ---------------------------------------------------------------------------
# Fake requests.Response — only the surface the service touches.
# ---------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, *, status_code=200, json_data=None, content=b"",
                 headers=None, lines=None, raise_http=False):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.headers = headers or {}
        self._lines = lines or []
        self._raise_http = raise_http

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if self._raise_http or self.status_code >= 400:
            err = requests.exceptions.HTTPError(f"HTTP {self.status_code}")
            err.response = self
            raise err

    def iter_lines(self):
        for ln in self._lines:
            yield ln

    def iter_content(self, chunk_size=1):
        # Treat .content as a single chunk for download paths.
        if self.content:
            yield self.content

    # Context-manager support (used by stream=True download in generate_video).
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_request(monkeypatch, fn):
    """Replace _session.request so OpenRouterService._request calls our fake.

    ``_request`` calls ``_session.request(method, eff_url, headers=..., **kw)``.
    """
    monkeypatch.setattr(ors_mod._session, "request", fn)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    """Ensure get_api_key returns something deterministic (no real key needed)."""
    from app.settings import settings
    monkeypatch.setitem(settings, "OPENROUTER_API_KEY", "test-key")
    yield


@pytest.fixture(autouse=True)
def _no_deprecation_db(monkeypatch):
    """Keep the deprecation memo from touching the DB / registry on hot calls."""
    monkeypatch.setattr(ors_mod, "_expiration_for", lambda model: None)
    yield


# ---------------------------------------------------------------------------
# build_enhanced_system_prompt
# ---------------------------------------------------------------------------
def test_enhanced_prompt_disabled_returns_base():
    out = OpenRouterService.build_enhanced_system_prompt("base", {"enabled": False})
    assert out == "base"


def test_enhanced_prompt_none_prefs_returns_empty_string():
    assert OpenRouterService.build_enhanced_system_prompt(None, None) == ""


def test_enhanced_prompt_enabled_no_parts_returns_base():
    out = OpenRouterService.build_enhanced_system_prompt("base", {"enabled": True})
    assert out == "base"


def test_enhanced_prompt_full_preamble():
    prefs = {
        "enabled": True,
        "user_info": {"name": "Ada", "language": "fa", "expertise_level": "expert"},
        "behavior": {"tone": "formal", "response_style": "concise"},
        "custom_instructions": "Be terse.",
    }
    out = OpenRouterService.build_enhanced_system_prompt("BASE", prefs)
    assert out.startswith("[User Preferences]")
    assert "User's name: Ada" in out
    assert "Respond in: fa" in out
    assert "User expertise: expert" in out
    assert "Tone: formal" in out
    assert "Response style: concise" in out
    assert "Instructions: Be terse." in out
    assert out.endswith("BASE")


# ---------------------------------------------------------------------------
# get_headers / get_api_key
# ---------------------------------------------------------------------------
def test_get_headers_shape(flask_core):
    with flask_core.app_context():
        h = OpenRouterService.get_headers()
    assert h["Authorization"] == "Bearer test-key"
    assert h["Content-Type"] == "application/json"
    assert "X-Title" in h
    assert "HTTP-Referer" in h


# ---------------------------------------------------------------------------
# get_available_models / get_model_info / get_models_by_modality
# ---------------------------------------------------------------------------
def test_get_available_models_happy(flask_core, monkeypatch):
    def fake(method, url, **kw):
        assert method == "GET"
        return _FakeResp(json_data={"data": [{"id": "openai/gpt-4o"}]})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        models = OpenRouterService.get_available_models()
    assert models == [{"id": "openai/gpt-4o"}]


def test_get_available_models_error_returns_empty(flask_core, monkeypatch):
    def fake(method, url, **kw):
        raise requests.exceptions.ConnectionError("boom")

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        assert OpenRouterService.get_available_models() == []


def test_get_model_info_found(flask_core, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(json_data={"data": [{"id": "a"}, {"id": "b"}]})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        assert OpenRouterService.get_model_info("b") == {"id": "b"}
        assert OpenRouterService.get_model_info("missing") is None


def test_get_models_by_modality_builds_query(flask_core, monkeypatch):
    captured = {}

    def fake(method, url, **kw):
        captured["url"] = url
        return _FakeResp(json_data={"data": [{"id": "img-model"}]})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.get_models_by_modality(
            input_modality="image", output_modality="image")
    assert out == [{"id": "img-model"}]
    assert "input_modalities=image" in captured["url"]
    assert "output_modalities=image" in captured["url"]


def test_get_models_by_modality_error_returns_empty(flask_core, monkeypatch):
    def fake(method, url, **kw):
        raise RuntimeError("nope")

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        assert OpenRouterService.get_models_by_modality() == []


# ---------------------------------------------------------------------------
# check_model_supports_vision / is_vision_model / is_image_generation_model
# ---------------------------------------------------------------------------
def test_check_vision_via_static_fallback(flask_core, monkeypatch):
    # Registry raises -> falls through; OR API also raises -> static list.
    import app.services.model_registry_service as mrs

    def boom(self, model_id):
        raise RuntimeError("no registry")

    monkeypatch.setattr(mrs.ModelRegistryService, "is_vision_capable", boom)

    # Force the OR-API refresh itself to raise (not be swallowed into an empty
    # cache) so check_model_supports_vision falls through to the static list.
    def raise_modality(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(OpenRouterService, "get_models_by_modality",
                        staticmethod(raise_modality))
    # Reset the module-level cache to force the cold path.
    OpenRouterService._vision_models_cache = None
    OpenRouterService._cache_timestamp = 0
    with flask_core.app_context():
        assert OpenRouterService.check_model_supports_vision("openai/gpt-4o") is True
        assert OpenRouterService.check_model_supports_vision("nope/nope") is False


def test_check_vision_registry_hit(flask_core, monkeypatch):
    import app.services.model_registry_service as mrs
    monkeypatch.setattr(mrs.ModelRegistryService, "is_vision_capable",
                        lambda self, mid: True)
    with flask_core.app_context():
        assert OpenRouterService.check_model_supports_vision("whatever") is True


def test_check_vision_refresh_populates_cache(flask_core, monkeypatch):
    import app.services.model_registry_service as mrs
    monkeypatch.setattr(mrs.ModelRegistryService, "is_vision_capable",
                        lambda self, mid: None)  # unknown -> fall through

    def fake(method, url, **kw):
        return _FakeResp(json_data={"data": [{"id": "cool/model"}]})

    _patch_request(monkeypatch, fake)
    OpenRouterService._vision_models_cache = None
    OpenRouterService._cache_timestamp = 0
    with flask_core.app_context():
        assert OpenRouterService.check_model_supports_vision("cool/model") is True
        # Warm cache path (no further HTTP).
        assert OpenRouterService.check_model_supports_vision("cool/model") is True
        assert OpenRouterService.check_model_supports_vision("absent") is False


def test_is_vision_model_static_true(flask_core):
    with flask_core.app_context():
        assert OpenRouterService.is_vision_model("openai/gpt-4o") is True


def test_is_vision_model_dynamic_exception_false(flask_core, monkeypatch):
    monkeypatch.setattr(OpenRouterService, "check_model_supports_vision",
                        staticmethod(lambda mid: (_ for _ in ()).throw(RuntimeError())))
    with flask_core.app_context():
        assert OpenRouterService.is_vision_model("brand/new-unknown") is False


def test_is_image_generation_model_fallback(flask_core, monkeypatch):
    import app.services.model_registry_service as mrs
    monkeypatch.setattr(mrs.ModelRegistryService, "is_image_capable",
                        lambda self, mid: (_ for _ in ()).throw(RuntimeError()))
    with flask_core.app_context():
        assert OpenRouterService.is_image_generation_model(
            "google/gemini-3.1-flash-image") is True
        assert OpenRouterService.is_image_generation_model("plain/text-model") is False


def test_is_image_generation_model_registry_hit(flask_core, monkeypatch):
    import app.services.model_registry_service as mrs
    monkeypatch.setattr(mrs.ModelRegistryService, "is_image_capable",
                        lambda self, mid: True)
    with flask_core.app_context():
        assert OpenRouterService.is_image_generation_model("x") is True


def test_get_model_capabilities(flask_core, monkeypatch):
    import app.services.model_registry_service as mrs
    monkeypatch.setattr(mrs.ModelRegistryService, "is_image_capable",
                        lambda self, mid: False)
    with flask_core.app_context():
        caps = OpenRouterService.get_model_capabilities("openai/gpt-4o")
    assert caps["supports_vision"] is True
    assert caps["supports_image_generation"] is False


def test_get_image_capable_models_curated_rich_contract(flask_core, monkeypatch):
    """The Image Studio picker is CURATED: the method returns exactly
    ``IMAGE_STUDIO_MODEL_IDS`` in order, each carrying the rich capability
    contract (id/name/description/is_default/max_input_images/pricing/
    capabilities). Capabilities derive from the live Image API descriptor; when
    the live fetch misses entirely it fails open to the static caps map. It never
    returns the raw roster nor a registry list."""
    allow = OpenRouterService.IMAGE_STUDIO_MODEL_IDS
    assert len(allow) >= 1

    # Roster carries the first allowlisted id (with a typed descriptor + name)
    # plus a non-allowlisted id that MUST be dropped. Remaining ids resolve from
    # the static caps fallback (no roster entry).
    monkeypatch.setattr(
        OpenRouterService, "_image_roster",
        staticmethod(lambda: [
            {"id": allow[0], "name": "FROM-ROSTER",
             "supported_parameters": {
                 "aspect_ratio": {"type": "enum", "values": ["1:1", "16:9"]},
                 "n": {"type": "range", "min": 1, "max": 1},
                 "input_references": {"type": "range", "min": 0, "max": 7},
             }},
            {"id": "roster/not-in-allowlist", "name": "should be filtered out"},
        ]),
    )
    # No per-endpoint descriptor (so the roster-listing descriptor is used).
    import app.services.model_registry_service as mrs
    monkeypatch.setattr(mrs.ModelRegistryService, "get_image_endpoints",
                        lambda self, mid: None)

    with flask_core.app_context():
        out = OpenRouterService.get_image_capable_models()

    # Exactly the allowlist, in allowlist order; non-allowlisted id never surfaces.
    assert [m["id"] for m in out] == list(allow)
    assert all(m["id"] != "roster/not-in-allowlist" for m in out)

    # Rich contract on every entry.
    first = out[0]
    assert first["id"] == allow[0]
    assert first["name"] == "FROM-ROSTER"
    assert first["is_default"] is True
    assert all(m["is_default"] is (m["id"] == allow[0]) for m in out)
    caps = first["capabilities"]
    # Derived from the roster descriptor.
    assert caps["aspect_ratio"] == {"supported": True, "values": ["1:1", "16:9"]}
    assert caps["n"] == {"supported": True, "min": 1, "max": 1}
    assert caps["input_references"] == {"supported": True, "max": 7}
    # max_input_images aliases input_references.max.
    assert first["max_input_images"] == 7
    # Unsupported params still present with supported:False.
    assert caps["seed"] == {"supported": False}
    assert caps["quality"]["supported"] is False
    # Every entry carries the full uniform capability key set.
    for m in out:
        for k in OpenRouterService._IMAGE_CAP_DEFAULTS:
            assert k in m["capabilities"]


def test_get_image_capabilities_static_fallback(flask_core, monkeypatch):
    """When neither the per-endpoint nor roster descriptor is available, caps
    fall back to the static map (never raises, never empty)."""
    monkeypatch.setattr(OpenRouterService, "_image_roster", staticmethod(lambda: []))
    import app.services.model_registry_service as mrs
    monkeypatch.setattr(mrs.ModelRegistryService, "get_image_endpoints",
                        lambda self, mid: None)
    with flask_core.app_context():
        caps = OpenRouterService.get_image_capabilities("openai/gpt-image-2")
    # gpt-image-2 static caps: quality enum, background enum, n range, no resolution.
    assert caps["quality"] == {"supported": True,
                               "values": ["auto", "low", "medium", "high"]}
    assert caps["background"]["supported"] is True
    assert caps["n"] == {"supported": True, "min": 1, "max": 10}
    assert caps["resolution"]["supported"] is False
    assert caps["input_references"]["max"] == 16


def test_get_image_capabilities_unknown_model_defaults(flask_core, monkeypatch):
    """An unknown slug with no descriptor anywhere yields the all-unsupported
    defaults (fail-open, never raises)."""
    monkeypatch.setattr(OpenRouterService, "_image_roster", staticmethod(lambda: []))
    import app.services.model_registry_service as mrs
    monkeypatch.setattr(mrs.ModelRegistryService, "get_image_endpoints",
                        lambda self, mid: None)
    with flask_core.app_context():
        caps = OpenRouterService.get_image_capabilities("totally/unknown-model")
    assert all(not v.get("supported") for v in caps.values())
    assert caps["input_references"]["max"] == 0


def test_caps_prefer_endpoint_over_roster_descriptor(flask_core, monkeypatch):
    """The per-endpoint descriptor (most authoritative) wins over the roster
    listing descriptor when both are present."""
    monkeypatch.setattr(
        OpenRouterService, "_image_roster",
        staticmethod(lambda: [{"id": "m/x", "supported_parameters": {
            "n": {"type": "range", "min": 1, "max": 1},  # roster says max 1
        }}]),
    )
    import app.services.model_registry_service as mrs
    monkeypatch.setattr(
        mrs.ModelRegistryService, "get_image_endpoints",
        lambda self, mid: {"id": mid, "endpoints": [{"supported_parameters": {
            "n": {"type": "range", "min": 1, "max": 8},  # endpoint says max 8
        }}]},
    )
    with flask_core.app_context():
        caps = OpenRouterService.get_image_capabilities("m/x")
    # Endpoint descriptor (max 8) wins.
    assert caps["n"] == {"supported": True, "min": 1, "max": 8}


def test_n_override_caps_seedream_to_one(flask_core, monkeypatch):
    """Provider-quirk override: seedream advertises n up to 10 in its descriptor
    but OpenRouter delivers a single image, so caps clamp n to 1 (control hidden)
    regardless of what the live/roster descriptor reports."""
    monkeypatch.setattr(OpenRouterService, "_image_roster", staticmethod(lambda: []))
    import app.services.model_registry_service as mrs
    monkeypatch.setattr(
        mrs.ModelRegistryService, "get_image_endpoints",
        lambda self, mid: {"id": mid, "endpoints": [{"supported_parameters": {
            "n": {"type": "range", "min": 1, "max": 10},  # descriptor lies
            "seed": {"type": "boolean"},
        }}]},
    )
    with flask_core.app_context():
        caps = OpenRouterService.get_image_capabilities("bytedance-seed/seedream-4.5")
    assert caps["n"] == {"supported": False, "min": 1, "max": 1}
    # Other caps from the descriptor are untouched by the override.
    assert caps["seed"]["supported"] is True
    # A model NOT in the override map keeps its descriptor n range.
    monkeypatch.setattr(
        mrs.ModelRegistryService, "get_image_endpoints",
        lambda self, mid: {"id": mid, "endpoints": [{"supported_parameters": {
            "n": {"type": "range", "min": 1, "max": 10},
        }}]},
    )
    with flask_core.app_context():
        other = OpenRouterService.get_image_capabilities("openai/gpt-image-2")
    assert other["n"] == {"supported": True, "min": 1, "max": 10}


def test_get_image_endpoints_caches_and_fails_open(flask_core, monkeypatch):
    """ModelRegistryService.get_image_endpoints fetches once (1h cache) and
    returns None on a transport error without raising."""
    from app.services.model_registry_service import ModelRegistryService

    # Reset the class-level cache so this test is order-independent.
    ModelRegistryService._image_endpoints_cache.clear()
    calls = {"n": 0}

    def fake(method, url, **kw):
        calls["n"] += 1
        assert "/images/models/" in url and url.endswith("/endpoints")
        return _FakeResp(json_data={"id": "m/x", "endpoints": [{"pricing": []}]})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out1 = ModelRegistryService().get_image_endpoints("m/x")
        out2 = ModelRegistryService().get_image_endpoints("m/x")
    assert out1 == out2 == {"id": "m/x", "endpoints": [{"pricing": []}]}
    assert calls["n"] == 1  # second call served from cache

    # Fail-open: a transport error on a cold key -> None (no raise).
    ModelRegistryService._image_endpoints_cache.clear()

    def boom(method, url, **kw):
        raise RuntimeError("net down")

    _patch_request(monkeypatch, boom)
    with flask_core.app_context():
        assert ModelRegistryService().get_image_endpoints("m/cold") is None


# ---------------------------------------------------------------------------
# estimate_tokens / calculate_cost / detect_images_in_content
# ---------------------------------------------------------------------------
def test_estimate_tokens():
    assert OpenRouterService.estimate_tokens("") == 0
    assert OpenRouterService.estimate_tokens("a" * 8) == 2


def test_calculate_cost_known_and_default():
    known = OpenRouterService.calculate_cost("openai/gpt-4", 1000, 1000)
    assert known == pytest.approx(0.03 + 0.06)
    default = OpenRouterService.calculate_cost("unknown/model", 1000, 1000)
    assert default == pytest.approx(0.001 + 0.002)


def test_detect_images_empty():
    assert OpenRouterService.detect_images_in_content("") == []


def test_detect_images_markdown_url_base64():
    content = (
        "Look ![cat](http://x.com/cat.png) and https://y.com/dog.jpg "
        "and data:image/png;base64,QUJD here"
    )
    out = OpenRouterService.detect_images_in_content(content)
    types = {img["type"] for img in out}
    assert "markdown" in types
    assert "url" in types
    assert "base64" in types
    # Sorted by position ascending.
    positions = [img["position"] for img in out]
    assert positions == sorted(positions)


# ---------------------------------------------------------------------------
# format_messages_for_api / format_messages_for_api_ex
# ---------------------------------------------------------------------------
def test_format_plain_text_messages(flask_core):
    with flask_core.app_context():
        out = OpenRouterService.format_messages_for_api([
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ])
    assert out == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_format_skips_error_messages(flask_core):
    with flask_core.app_context():
        res = OpenRouterService.format_messages_for_api_ex([
            {"role": "user", "content": "ok"},
            {"role": "assistant", "content": "bad", "is_error": True},
        ])
    assert res["messages"] == [{"role": "user", "content": "ok"}]
    assert res["plugins"] == []
    assert res["has_native_pdf"] is False


def test_format_assistant_file_annotations_kept(flask_core):
    with flask_core.app_context():
        res = OpenRouterService.format_messages_for_api_ex([
            {
                "role": "assistant",
                "content": "answer",
                "metadata": {"annotations": [
                    {"type": "file", "hash": "abc"},
                    {"type": "url_citation", "url": "http://x"},
                ]},
            },
        ])
    msg = res["messages"][0]
    assert msg["annotations"] == [{"type": "file", "hash": "abc"}]


def _seed_owned_upload(flask_core, owner_id, tmp_path, *, name, mime, raw,
                       extracted_text=None):
    """Create an uploads row owned by ``owner_id`` and write its bytes to
    ``UPLOAD_FOLDER`` (the caller points ``UPLOAD_FOLDER`` at ``tmp_path``).

    Mirrors tests/api/test_upload_idor_cov.py — the post-security-fix formatter
    ALWAYS reloads attachment text / bytes from the OWNER-SCOPED upload row, so
    inline ``extracted_text`` / arbitrary ``url`` on the attachment dict are
    ignored; the test must persist a real owned row.
    """
    import os
    import uuid

    filename = f"{uuid.uuid4().hex}_{name}"
    with open(os.path.join(str(tmp_path), filename), "wb") as fh:
        fh.write(raw)
    with flask_core.app_context():
        from app.models.upload import UploadModel
        return UploadModel.create(
            user_id=str(owner_id), filename=filename, original_name=name,
            mime_type=mime, size=len(raw), type="file",
            extracted_text=extracted_text,
            extracted_chars=len(extracted_text or ""),
            extraction_status="ok" if extracted_text else None,
        )


def test_format_image_attachment_becomes_image_url(flask_core, test_user, tmp_path):
    """SECURITY (post-fix): a client-supplied arbitrary http(s) image url is NO
    LONGER forwarded (SSRF/beacon). An image now resolves bytes from the
    OWNER-SCOPED upload and inlines as a ``data:`` URI; a foreign/arbitrary url
    with no owned upload is dropped."""
    from app.settings import settings

    settings["UPLOAD_FOLDER"] = str(tmp_path)
    up = _seed_owned_upload(
        flask_core, test_user["_id"], tmp_path,
        name="x.png", mime="image/png", raw=b"\x89PNG\r\n\x1a\nIMGBYTES",
    )
    with flask_core.app_context():
        res = OpenRouterService.format_messages_for_api_ex([
            {
                "role": "user",
                "content": "describe",
                "attachments": [
                    # Owned upload -> inlined as data:; the arbitrary http url is ignored.
                    {"type": "image", "name": "x.png", "mime_type": "image/png",
                     "upload_id": up["_id"], "url": "http://img/x.png"},
                ],
            },
        ], user_id=str(test_user["_id"]))
    content = res["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "describe"}
    img = content[1]
    assert img["type"] == "image_url"
    # The arbitrary http url is NEVER forwarded; bytes inlined as a data: URI.
    assert img["image_url"]["url"].startswith("data:image/png;base64,")
    assert "http://img/x.png" not in img["image_url"]["url"]


def test_format_foreign_image_url_dropped(flask_core, test_user):
    """An image attachment with ONLY an arbitrary http url (no owned upload) is
    dropped — never echoed to the provider."""
    with flask_core.app_context():
        res = OpenRouterService.format_messages_for_api_ex([
            {
                "role": "user",
                "content": "describe",
                "attachments": [
                    {"type": "image", "url": "http://img/x.png", "name": "x.png"},
                ],
            },
        ], user_id=str(test_user["_id"]))
    content = res["messages"][0]["content"]
    image_parts = (
        [p for p in content if isinstance(p, dict) and p.get("type") == "image_url"]
        if isinstance(content, list) else []
    )
    assert image_parts == []
    assert "http://img/x.png" not in str(content)


def test_format_extracted_text_appended(flask_core, test_user, tmp_path):
    """SECURITY (post-fix): inline ``extracted_text`` is ignored; the formatter
    reloads from the OWNER-SCOPED upload row. The owner gets their own text."""
    from app.settings import settings

    settings["UPLOAD_FOLDER"] = str(tmp_path)
    up = _seed_owned_upload(
        flask_core, test_user["_id"], tmp_path,
        name="notes.txt", mime="text/plain", raw=b"raw",
        extracted_text="INLINE-DOC-TEXT",
    )
    with flask_core.app_context():
        res = OpenRouterService.format_messages_for_api_ex([
            {
                "role": "user",
                "content": "summarize",
                "attachments": [
                    {"type": "document", "name": "notes.txt",
                     "upload_id": up["_id"], "mime_type": "text/plain"},
                ],
            },
        ], user_id=str(test_user["_id"]))
    content = res["messages"][0]["content"]
    # Single text part collapses back to a string.
    assert isinstance(content, str)
    assert content.startswith("summarize")
    assert "[Attached file: notes.txt]" in content
    assert "INLINE-DOC-TEXT" in content


def test_format_pdf_fresh_data_url_no_bytes(flask_core, monkeypatch):
    # No upload bytes on disk -> degrade to data: URL file part if url is data:.
    monkeypatch.setattr(ors_mod, "_read_upload_bytes", lambda uid, user_id=None: None)
    with flask_core.app_context():
        res = OpenRouterService.format_messages_for_api_ex([
            {
                "role": "user",
                "content": "read pdf",
                "attachments": [
                    {"is_pdf": True, "name": "doc.pdf",
                     "url": "data:application/pdf;base64,QUJD", "upload_id": "u1"},
                ],
            },
        ], user_id="caller")
    assert res["has_native_pdf"] is True
    content = res["messages"][0]["content"]
    file_parts = [p for p in content if p.get("type") == "file"]
    assert file_parts
    assert file_parts[0]["file"]["file_data"].startswith("data:application/pdf")


def test_format_pdf_no_bytes_no_dataurl_marker(flask_core, monkeypatch):
    monkeypatch.setattr(ors_mod, "_read_upload_bytes", lambda uid, user_id=None: None)
    with flask_core.app_context():
        res = OpenRouterService.format_messages_for_api_ex([
            {
                "role": "user",
                "content": "read pdf",
                "attachments": [
                    {"is_pdf": True, "name": "doc.pdf", "url": "", "upload_id": "u1"},
                ],
            },
        ], user_id="caller")
    assert res["has_native_pdf"] is False
    content = res["messages"][0]["content"]
    texts = [p["text"] for p in content if p.get("type") == "text"]
    assert any("[PDF: doc.pdf]" in t for t in texts)


def test_format_pdf_fresh_with_bytes(flask_core, monkeypatch):
    monkeypatch.setattr(ors_mod, "_read_upload_bytes", lambda uid, user_id=None: b"%PDF-1.4 data")
    with flask_core.app_context():
        res = OpenRouterService.format_messages_for_api_ex([
            {
                "role": "user",
                "content": "read",
                "attachments": [
                    {"mime_type": "application/pdf", "name": "r.pdf", "upload_id": "u2"},
                ],
            },
        ], user_id="caller")
    assert res["has_native_pdf"] is True
    content = res["messages"][0]["content"]
    file_parts = [p for p in content if p.get("type") == "file"]
    assert file_parts[0]["file"]["filename"] == "r.pdf"
    assert file_parts[0]["file"]["file_data"].startswith("data:application/pdf;base64,")


def test_format_pdf_replay_marker(flask_core, monkeypatch):
    # Following assistant message carries file annotations -> REPLAY (no bytes).
    monkeypatch.setattr(ors_mod, "_read_upload_bytes",
                        lambda uid, user_id=None: (_ for _ in ()).throw(AssertionError("should not read")))
    with flask_core.app_context():
        res = OpenRouterService.format_messages_for_api_ex([
            {
                "role": "user",
                "content": "q",
                "attachments": [{"is_pdf": True, "name": "spec.pdf", "upload_id": "u3"}],
            },
            {
                "role": "assistant",
                "content": "a",
                "metadata": {"annotations": [{"type": "file", "hash": "h"}]},
            },
        ], user_id="caller")
    user_content = res["messages"][0]["content"]
    texts = [p["text"] for p in user_content if p.get("type") == "text"]
    assert any("[PDF: spec.pdf]" in t for t in texts)
    assert res["has_native_pdf"] is False


def test_format_extracted_text_budget_truncation(flask_core, test_user, tmp_path, monkeypatch):
    """SECURITY (post-fix): text reloaded from the OWNER-SCOPED upload row, then
    truncated to the per-message budget."""
    from app.settings import settings

    settings["UPLOAD_FOLDER"] = str(tmp_path)
    monkeypatch.setitem(settings, "DOC_EXTRACT_TOTAL_MAX_CHARS", 20)
    up = _seed_owned_upload(
        flask_core, test_user["_id"], tmp_path,
        name="big.txt", mime="text/plain", raw=b"raw",
        extracted_text="Y" * 5000,
    )
    with flask_core.app_context():
        res = OpenRouterService.format_messages_for_api_ex([
            {
                "role": "user",
                "content": "x",
                "attachments": [
                    {"type": "doc", "name": "big.txt",
                     "upload_id": up["_id"], "mime_type": "text/plain"},
                ],
            },
        ], user_id=str(test_user["_id"]))
    content = res["messages"][0]["content"]
    assert "[...attachment text truncated...]" in content


# ---------------------------------------------------------------------------
# _record_usage — writes real rows to usage_logs.
# ---------------------------------------------------------------------------
def _count_usage_rows(flask_core):
    from app.api.core import db
    from app.models.usage_log import UsageLog
    with flask_core.app_context():
        return db.session.query(UsageLog).count()


def _latest_usage_row(flask_core):
    from app.api.core import db
    from app.models.usage_log import UsageLog
    with flask_core.app_context():
        return (db.session.query(UsageLog)
                .order_by(UsageLog.created_at.desc()).first())


def _all_usage_rows(flask_core):
    from app.api.core import db
    from app.models.usage_log import UsageLog
    with flask_core.app_context():
        return (db.session.query(UsageLog)
                .order_by(UsageLog.created_at.desc()).all())


def test_record_usage_noop_without_user(flask_core):
    with flask_core.app_context():
        OpenRouterService._record_usage(
            None, None, "openai/gpt-4o", {"prompt_tokens": 5}, "chat")
    assert _count_usage_rows(flask_core) == 0


def test_record_usage_noop_without_usage(flask_core, test_user):
    with flask_core.app_context():
        OpenRouterService._record_usage(
            test_user["_id"], None, "openai/gpt-4o", None, "chat")
    assert _count_usage_rows(flask_core) == 0


def test_record_usage_writes_row_with_cost_and_provider(flask_core, test_user):
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 40,
        "prompt_tokens_details": {"cached_tokens": 30, "cache_write_tokens": 10},
        "completion_tokens_details": {"reasoning_tokens": 7},
        "cost": 0.0123,
        "upstream_cost_usd": 0.02,
    }
    with flask_core.app_context():
        OpenRouterService._record_usage(
            test_user["_id"], None, "anthropic/claude-opus-4.5", usage, "chat",
            generation_id="gen-1", origin="helper", is_streaming=True,
            finish_reason="stop",
        )
    row = _latest_usage_row(flask_core)
    assert row is not None
    assert row.model == "anthropic/claude-opus-4.5"
    assert row.provider == "anthropic"
    assert row.input_tokens == 100
    assert row.output_tokens == 40
    assert row.cached_tokens == 30  # subset of prompt, not additive
    assert row.reasoning_tokens == 7
    assert float(row.cost_usd) == pytest.approx(0.0123)
    assert row.origin == "helper"
    assert row.generation_id == "gen-1"


def test_record_usage_cost_none_fetches_generation(flask_core, test_user, monkeypatch):
    # cost is None + generation_id present -> GET /generation, total_cost used.
    def fake(method, url, **kw):
        assert method == "GET"
        assert "generation?id=gen-9" in url
        return _FakeResp(json_data={"data": {"total_cost": 0.55}})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        OpenRouterService._record_usage(
            test_user["_id"], None, "openai/gpt-4o",
            {"prompt_tokens": 1, "completion_tokens": 1}, "chat",
            generation_id="gen-9",
        )
    row = _latest_usage_row(flask_core)
    assert float(row.cost_usd) == pytest.approx(0.55)


def test_record_usage_cost_none_pricing_fallback(flask_core, test_user, monkeypatch):
    # No generation_id, no cost -> registry pricing path.
    import app.services.model_registry_service as mrs
    monkeypatch.setattr(mrs.ModelRegistryService, "get_pricing",
                        lambda self, mid: {"prompt": 0.001, "completion": 0.002,
                                           "cached": 0.0005})
    with flask_core.app_context():
        OpenRouterService._record_usage(
            test_user["_id"], None, "openai/gpt-4o",
            {"prompt_tokens": 1000, "completion_tokens": 1000,
             "prompt_tokens_details": {"cached_tokens": 100}},
            "chat",
        )
    row = _latest_usage_row(flask_core)
    expected = 0.001 * 1000 + 0.002 * 1000 + 0.0005 * 100
    assert float(row.cost_usd) == pytest.approx(expected)


def test_record_usage_cost_none_all_lookups_fail(flask_core, test_user, monkeypatch):
    import app.services.model_registry_service as mrs
    monkeypatch.setattr(mrs.ModelRegistryService, "get_pricing",
                        lambda self, mid: (_ for _ in ()).throw(RuntimeError()))
    with flask_core.app_context():
        OpenRouterService._record_usage(
            test_user["_id"], None, "noslash",
            {"prompt_tokens": 1, "completion_tokens": 1}, "chat",
        )
    row = _latest_usage_row(flask_core)
    assert float(row.cost_usd) == 0.0
    assert row.provider is None  # no '/' in model id


# ---------------------------------------------------------------------------
# _sync_completion / chat_completion (non-stream)
# ---------------------------------------------------------------------------
def test_chat_completion_nonstream_records_usage(flask_core, test_user, monkeypatch):
    def fake(method, url, **kw):
        assert method == "POST"
        return _FakeResp(json_data={
            "id": "gen-x",
            "model": "openai/gpt-4o",
            "choices": [{
                "message": {"content": "hi",
                            "annotations": [{"type": "file", "hash": "z"}]},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "cost": 0.001},
        })

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        data = OpenRouterService.chat_completion(
            [{"role": "user", "content": "x"}], "openai/gpt-4o",
            system_prompt="You are a bot.", user_id=test_user["_id"],
            stream=False, feature="chat",
        )
    assert data["choices"][0]["message"]["content"] == "hi"
    # Annotations surfaced top-level.
    assert data["annotations"] == [{"type": "file", "hash": "z"}]
    row = _latest_usage_row(flask_core)
    assert row is not None and float(row.cost_usd) == pytest.approx(0.001)


def test_chat_completion_web_search_tool_added(flask_core, monkeypatch):
    captured = {}

    def fake(method, url, **kw):
        captured["payload"] = kw.get("json")
        return _FakeResp(json_data={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        OpenRouterService.chat_completion(
            [{"role": "user", "content": "search"}], "openai/gpt-4o",
            web_search=True, plugins=[{"id": "file-parser"}],
        )
    payload = captured["payload"]
    assert payload["plugins"] == [{"id": "file-parser"}]
    tools = payload["tools"]
    assert any(t.get("type") == "openrouter:web_search" for t in tools)


def test_chat_completion_web_search_dedup(flask_core, monkeypatch):
    captured = {}

    def fake(method, url, **kw):
        captured["payload"] = kw.get("json")
        return _FakeResp(json_data={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })

    _patch_request(monkeypatch, fake)
    pre = [{"type": "openrouter:web_search", "parameters": {"max_results": 2}}]
    with flask_core.app_context():
        OpenRouterService.chat_completion(
            [{"role": "user", "content": "search"}], "openai/gpt-4o",
            web_search=True, tools=pre,
        )
    web_tools = [t for t in captured["payload"]["tools"]
                 if t.get("type") == "openrouter:web_search"]
    assert len(web_tools) == 1


def test_sync_completion_http_error_returns_error_dict(flask_core, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(status_code=429,
                         json_data={"error": {"message": "rate limited"}})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.chat_completion(
            [{"role": "user", "content": "x"}], "openai/gpt-4o", stream=False)
    assert out["error"]["message"] == "rate limited"
    assert out["error"]["code"] == 429


def test_sync_completion_generic_exception_returns_error_dict(flask_core, monkeypatch):
    def fake(method, url, **kw):
        raise RuntimeError("kaboom")

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.chat_completion(
            [{"role": "user", "content": "x"}], "openai/gpt-4o", stream=False)
    assert out["error"]["code"] == 500
    assert "kaboom" in out["error"]["message"]


# ---------------------------------------------------------------------------
# _stream_completion / chat_completion (stream)
# ---------------------------------------------------------------------------
def test_stream_completion_yields_chunks_and_done(flask_core, test_user, monkeypatch):
    lines = [
        b": keep-alive comment",
        b"",
        b'data: {"id":"g1","model":"openai/gpt-4o","choices":[{"delta":{"content":"Hello "}}]}',
        b'data: {"choices":[{"delta":{"content":"world"},"finish_reason":"stop","message":{"annotations":[{"type":"url_citation","url":"http://x"}]}}],"usage":{"prompt_tokens":4,"completion_tokens":2,"cost":0.003}}',
        b"data: [DONE]",
    ]

    def fake(method, url, **kw):
        assert kw.get("stream") is True
        return _FakeResp(lines=lines)

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        gen = OpenRouterService.chat_completion(
            [{"role": "user", "content": "hi"}], "openai/gpt-4o",
            stream=True, user_id=test_user["_id"], feature="chat",
        )
        chunks = list(gen)
    contents = [c["choices"][0]["delta"]["content"]
                for c in chunks if c.get("choices")]
    assert "".join(contents) == "Hello world"
    done = chunks[-1]
    assert done["done"] is True
    assert done["annotations"] == [{"type": "url_citation", "url": "http://x"}]
    # Usage recorded once from the terminal chunk.
    row = _latest_usage_row(flask_core)
    assert row is not None and float(row.cost_usd) == pytest.approx(0.003)


def test_stream_completion_bad_json_skipped(flask_core, monkeypatch):
    lines = [
        b"data: not-json",
        b'data: {"choices":[{"delta":{"content":"ok"}}]}',
        b"data: [DONE]",
    ]

    def fake(method, url, **kw):
        return _FakeResp(lines=lines)

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        chunks = list(OpenRouterService.chat_completion(
            [{"role": "user", "content": "hi"}], "openai/gpt-4o", stream=True))
    contents = [c["choices"][0]["delta"]["content"]
                for c in chunks if c.get("choices")]
    assert contents == ["ok"]


def test_stream_completion_http_error_yields_error(flask_core, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(status_code=500,
                         json_data={"error": {"message": "server boom"}})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        chunks = list(OpenRouterService.chat_completion(
            [{"role": "user", "content": "hi"}], "openai/gpt-4o", stream=True))
    assert chunks[0]["error"]["code"] == 500
    assert chunks[0]["error"]["message"] == "server boom"


def test_stream_completion_generic_error_yields_error(flask_core, monkeypatch):
    def fake(method, url, **kw):
        raise RuntimeError("conn died")

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        chunks = list(OpenRouterService.chat_completion(
            [{"role": "user", "content": "hi"}], "openai/gpt-4o", stream=True))
    assert chunks[0]["error"]["code"] == 500
    assert "conn died" in chunks[0]["error"]["message"]


def test_stream_completion_no_done_records_at_end(flask_core, test_user, monkeypatch):
    # Stream ends without [DONE] -> safety-net _record_now fires.
    lines = [
        b'data: {"id":"g2","choices":[{"delta":{"content":"partial"}}],"usage":{"prompt_tokens":2,"completion_tokens":1,"cost":0.009}}',
    ]

    def fake(method, url, **kw):
        return _FakeResp(lines=lines)

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        list(OpenRouterService.chat_completion(
            [{"role": "user", "content": "hi"}], "openai/gpt-4o",
            stream=True, user_id=test_user["_id"]))
    row = _latest_usage_row(flask_core)
    assert row is not None and float(row.cost_usd) == pytest.approx(0.009)


# ---------------------------------------------------------------------------
# generate_image — Image API (POST /images) param passthrough
# ---------------------------------------------------------------------------
def test_generate_image_posts_to_images_endpoint(monkeypatch):
    captured = {"url": None, "body": None}

    def fake(method, url, **kw):
        captured["url"] = url
        captured["body"] = kw.get("json") or {}
        return _FakeResp(json_data={"data": []})  # no image -> no usage write

    _patch_request(monkeypatch, fake)
    OpenRouterService.generate_image(prompt="a fox", model="google/x",
                                     aspect_ratio="9:16")
    assert captured["url"].endswith("/images")
    body = captured["body"]
    # New Image API body shape: top-level prompt + params, NO messages/modalities.
    assert body["prompt"] == "a fox"
    assert body["model"] == "google/x"
    assert body["aspect_ratio"] == "9:16"
    assert "messages" not in body
    assert "modalities" not in body
    assert "image_config" not in body


def test_generate_image_only_provided_params_forwarded(monkeypatch):
    captured = {}

    def fake(method, url, **kw):
        captured.update(kw.get("json") or {})
        return _FakeResp(json_data={"data": []})

    _patch_request(monkeypatch, fake)
    OpenRouterService.generate_image(prompt="a fox", model="google/x")
    # n defaults to 1 (always sent); the rest are omitted when None.
    assert captured["n"] == 1
    for k in ("aspect_ratio", "resolution", "seed", "quality",
              "output_format", "background", "output_compression"):
        assert k not in captured


def test_generate_image_all_params_forwarded(monkeypatch):
    captured = {}

    def fake(method, url, **kw):
        captured.update(kw.get("json") or {})
        return _FakeResp(json_data={"data": []})

    _patch_request(monkeypatch, fake)
    OpenRouterService.generate_image(
        prompt="a fox", model="openai/gpt-image-2", n=3, quality="high",
        background="opaque", output_compression=80, seed=42,
        output_format="jpeg", resolution="2K", aspect_ratio="1:1",
        input_images=["data:image/png;base64,REF"],
    )
    assert captured["n"] == 3
    assert captured["quality"] == "high"
    assert captured["background"] == "opaque"
    assert captured["output_compression"] == 80
    assert captured["seed"] == 42
    assert captured["output_format"] == "jpeg"
    assert captured["resolution"] == "2K"
    assert captured["aspect_ratio"] == "1:1"
    # input_images map to the Image API input_references shape.
    assert captured["input_references"] == [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,REF"}}
    ]


def test_generate_image_negative_prompt_folded_into_prompt(monkeypatch):
    captured = {}

    def fake(method, url, **kw):
        captured.update(kw.get("json") or {})
        return _FakeResp(json_data={"data": []})

    _patch_request(monkeypatch, fake)
    OpenRouterService.generate_image(prompt="a fox", model="google/x",
                                     negative_prompt="blurry")
    # Negative prompt is text-folded (no structured negative field on Image API).
    assert captured["prompt"] == "a fox\n\nNegative prompt: blurry"


# ---------------------------------------------------------------------------
# chat_completion — reasoning effort payload
# ---------------------------------------------------------------------------
def test_chat_completion_reasoning_effort_payload(flask_core, monkeypatch):
    captured = {}

    def fake(method, url, **kw):
        captured.update(kw.get("json") or {})
        return _FakeResp(json_data={
            "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        OpenRouterService.chat_completion(
            messages=[{"role": "user", "content": "q"}], model="openai/gpt-4o-mini",
            reasoning_effort="high",
        )
    assert captured["reasoning"] == {"effort": "high"}


def test_chat_completion_no_reasoning_effort_omits_field(flask_core, monkeypatch):
    captured = {}

    def fake(method, url, **kw):
        captured.update(kw.get("json") or {})
        return _FakeResp(json_data={
            "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        OpenRouterService.chat_completion(
            messages=[{"role": "user", "content": "q"}], model="openai/gpt-4o-mini",
        )
    assert "reasoning" not in captured


# ---------------------------------------------------------------------------
# generate_title
# ---------------------------------------------------------------------------
def test_generate_title_happy(flask_core, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(json_data={
            "choices": [{"message": {"content": '"My Title"'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        })

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        title = OpenRouterService.generate_title("Hello world question")
    assert title == "My Title"


def test_generate_title_error_falls_back_to_message(flask_core, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(status_code=500, json_data={"error": {"message": "boom"}})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        title = OpenRouterService.generate_title("A" * 80)
    assert title == "A" * 50


def test_generate_title_malformed_response_falls_back(flask_core, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(json_data={"choices": []})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        title = OpenRouterService.generate_title("fallback message here")
    assert title == "fallback message here"[:50]


# ---------------------------------------------------------------------------
# generate_image — Image API response parsing
# ---------------------------------------------------------------------------
def test_generate_image_invalid_image_format(flask_core):
    with flask_core.app_context():
        out = OpenRouterService.generate_image(
            "draw", "google/x", input_images=["notavalidimage"])
    assert out["success"] is False
    assert "Invalid image format" in out["error"]


def test_generate_image_happy_single(flask_core, test_user, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(json_data={
            "model": "google/x",
            "data": [{"b64_json": "RESULT"}],
            "usage": {"total_tokens": 1200, "cost": 0.004},
        })

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_image(
            "draw a cat", "google/x",
            negative_prompt="blurry", user_id=test_user["_id"])
    assert out["success"] is True
    # data: URI assembled from b64_json + default png format.
    assert out["images"] == ["data:image/png;base64,RESULT"]
    assert out["image_data"] == "data:image/png;base64,RESULT"  # back-compat
    assert out["n"] == 1
    assert out["cost_usd_total"] == pytest.approx(0.004)
    assert out["tokens_total"] == 1200
    row = _latest_usage_row(flask_core)
    assert row is not None and float(row.cost_usd) == pytest.approx(0.004)


def test_generate_image_multi_uses_output_format(flask_core, test_user, monkeypatch):
    """N entries -> N data URIs (one usage row for the batch). output_format
    drives the data: URI mime."""
    def fake(method, url, **kw):
        return _FakeResp(json_data={
            "model": "openai/gpt-image-2",
            "data": [{"b64_json": "A"}, {"b64_json": "B"}, {"b64_json": "C"}],
            "usage": {"total_tokens": 9, "cost": 0.06},
        })

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_image(
            "draw", "openai/gpt-image-2", n=3, output_format="jpeg",
            user_id=test_user["_id"])
    assert out["success"] is True
    assert out["n"] == 3
    assert out["images"] == [
        "data:image/jpeg;base64,A",
        "data:image/jpeg;base64,B",
        "data:image/jpeg;base64,C",
    ]
    # Single usage row for the whole batch (no per-image double-count).
    rows = _all_usage_rows(flask_core)
    assert len(rows) == 1
    assert float(rows[0].cost_usd) == pytest.approx(0.06)


def test_generate_image_no_image_in_response(flask_core, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(json_data={"data": [], "usage": {}})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_image("x", "google/x")
    assert out["success"] is False
    assert out["error"] == "No image in response"


def test_generate_image_content_policy_code(flask_core, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(status_code=400, json_data={
            "error": {
                "message": "Provider returned error",
                "metadata": {"raw": "content policy violation"},
            },
        })

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_image("x", "google/x")
    assert out["success"] is False
    assert out["code"] == "content_policy"
    assert out["error"] == "Provider returned error"


def test_generate_image_http_error(flask_core, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(status_code=400,
                         json_data={"error": {"message": "bad model"}})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_image("x", "google/x")
    assert out["success"] is False
    assert out["error"] == "bad model"


def test_generate_image_generic_exception(flask_core, monkeypatch):
    def fake(method, url, **kw):
        raise RuntimeError("net down")

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_image("x", "google/x")
    assert out["success"] is False
    assert "net down" in out["error"]


# ---------------------------------------------------------------------------
# generate_speech
# ---------------------------------------------------------------------------
def test_generate_speech_empty_input(flask_core):
    with flask_core.app_context():
        out = OpenRouterService.generate_speech("  ", "openai/gpt-4o-mini-tts-2025-12-15", "alloy")
    assert out["success"] is False
    assert "empty" in out["error"]


def test_generate_speech_happy_with_usage(flask_core, test_user, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(
            content=b"AUDIOBYTES",
            headers={"X-Generation-Id": "tts-1",
                     "Content-Type": "application/json"},
            json_data={"usage": {"prompt_tokens": 1, "completion_tokens": 1,
                                 "cost": 0.002}},
        )

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_speech(
            "hello", "openai/gpt-4o-mini-tts-2025-12-15", "alloy",
            speed=99.0, user_id=test_user["_id"])
    assert out["success"] is True
    assert out["audio_bytes"] == b"AUDIOBYTES"
    assert out["mime"] == "audio/mpeg"
    assert out["generation_id"] == "tts-1"
    row = _latest_usage_row(flask_core)
    assert row is not None and float(row.cost_usd) == pytest.approx(0.002)


def test_generate_speech_empty_payload(flask_core, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(content=b"", headers={})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_speech(
            "hi", "openai/gpt-4o-mini-tts-2025-12-15", "alloy")
    assert out["success"] is False
    assert "empty audio" in out["error"]


def test_generate_speech_no_usage_skips_record(flask_core, test_user, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(content=b"AUD", headers={"Content-Type": "audio/mpeg"})

    _patch_request(monkeypatch, fake)
    before = _count_usage_rows(flask_core)
    with flask_core.app_context():
        out = OpenRouterService.generate_speech(
            "hi", "openai/gpt-4o-mini-tts-2025-12-15", "alloy",
            user_id=test_user["_id"])
    assert out["success"] is True
    assert _count_usage_rows(flask_core) == before


def test_generate_speech_http_error(flask_core, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(status_code=400,
                         json_data={"error": {"message": "bad voice"}})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_speech(
            "hi", "openai/gpt-4o-mini-tts-2025-12-15", "alloy")
    assert out["success"] is False
    assert out["error"] == "bad voice"


def test_generate_speech_timeout(flask_core, monkeypatch):
    def fake(method, url, **kw):
        raise requests.exceptions.Timeout()

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_speech(
            "hi", "openai/gpt-4o-mini-tts-2025-12-15", "alloy")
    assert out["success"] is False
    assert "timed out" in out["error"]


def test_generate_speech_generic_exception(flask_core, monkeypatch):
    def fake(method, url, **kw):
        raise RuntimeError("weird")

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_speech(
            "hi", "openai/gpt-4o-mini-tts-2025-12-15", "alloy")
    assert out["success"] is False
    assert "weird" in out["error"]


# ---------------------------------------------------------------------------
# generate_video
# ---------------------------------------------------------------------------
def test_generate_video_empty_prompt(flask_core):
    with flask_core.app_context():
        out = OpenRouterService.generate_video("google/veo-3.1", "   ")
    assert out["success"] is False
    assert "empty" in out["error"]


def test_generate_video_submit_http_error(flask_core, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(status_code=400,
                         json_data={"error": {"message": "no quota"}})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_video("google/veo-3.1", "a clip")
    assert out["success"] is False
    assert "Video submit failed" in out["error"]
    assert "no quota" in out["error"]


def test_generate_video_submit_missing_polling_url(flask_core, monkeypatch):
    def fake(method, url, **kw):
        return _FakeResp(json_data={"status": "pending"})  # no polling_url/id

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_video("google/veo-3.1", "a clip")
    assert out["success"] is False
    assert "missing polling_url" in out["error"]


def test_generate_video_full_success(flask_core, test_user, monkeypatch, tmp_path):
    from app.settings import settings
    monkeypatch.setitem(settings, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(ors_mod.time, "sleep", lambda *a, **k: None)

    calls = {"n": 0}

    def fake(method, url, **kw):
        if method == "POST" and url.endswith("/videos"):
            return _FakeResp(json_data={"id": "vid-1", "polling_url": "http://poll/1",
                                        "status": "pending"})
        if method == "GET" and url == "http://poll/1":
            calls["n"] += 1
            if calls["n"] < 2:
                return _FakeResp(json_data={"status": "processing"})
            return _FakeResp(json_data={
                "status": "completed",
                "unsigned_urls": ["http://cdn/video.mp4"],
                "duration": 5,
                "resolution": "1080p",
                "usage": {"completion_tokens": 1, "cost": 0.5},
            })
        if method == "GET" and url == "http://cdn/video.mp4":
            return _FakeResp(content=b"MP4BYTES")
        raise AssertionError(f"unexpected call {method} {url}")

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_video(
            "google/veo-3.1", "a clip", duration=5, seed=42,
            frame_images=[{"frame_type": "first", "url": "data:image/png;base64,A"}],
            user_id=test_user["_id"], poll_interval=0, timeout=600)
    assert out["success"] is True
    assert out["generation_id"] == "vid-1"
    assert out["duration_sec"] == 5
    assert out["resolution"] == "1080p"
    # video_url is now HMAC-signed: the path ends with the filename, followed by
    # an ?exp=&sig= query (services/signed_urls.py). Split the query off before
    # the filename check.
    expected_name = "video_" + str(test_user["_id"]) + "_vid-1.mp4"
    url_path, _, query = out["video_url"].partition("?")
    assert url_path.endswith(expected_name)
    assert query.startswith("exp=") and "&sig=" in query
    # File written.
    import os
    assert os.path.isfile(out["local_path"])
    with open(out["local_path"], "rb") as fh:
        assert fh.read() == b"MP4BYTES"
    # Usage recorded.
    row = _latest_usage_row(flask_core)
    assert row is not None and float(row.cost_usd) == pytest.approx(0.5)


def test_generate_video_terminal_failure_status(flask_core, monkeypatch, tmp_path):
    from app.settings import settings
    monkeypatch.setitem(settings, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(ors_mod.time, "sleep", lambda *a, **k: None)

    def fake(method, url, **kw):
        if method == "POST":
            return _FakeResp(json_data={"id": "v2", "polling_url": "http://poll/2",
                                        "status": "pending"})
        return _FakeResp(json_data={"status": "failed",
                                    "error": {"message": "render error"}})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_video(
            "google/veo-3.1", "clip", poll_interval=0, timeout=600)
    assert out["success"] is False
    assert "render error" in out["error"]


def test_generate_video_completed_no_unsigned_urls(flask_core, monkeypatch, tmp_path):
    from app.settings import settings
    monkeypatch.setitem(settings, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(ors_mod.time, "sleep", lambda *a, **k: None)

    def fake(method, url, **kw):
        if method == "POST":
            return _FakeResp(json_data={"id": "v3", "polling_url": "http://poll/3",
                                        "status": "pending"})
        return _FakeResp(json_data={"status": "completed", "unsigned_urls": []})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_video(
            "google/veo-3.1", "clip", poll_interval=0, timeout=600)
    assert out["success"] is False
    assert "no unsigned_urls" in out["error"]


def test_generate_video_poll_http_error(flask_core, monkeypatch, tmp_path):
    from app.settings import settings
    monkeypatch.setitem(settings, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(ors_mod.time, "sleep", lambda *a, **k: None)

    def fake(method, url, **kw):
        if method == "POST":
            return _FakeResp(json_data={"id": "v4", "polling_url": "http://poll/4",
                                        "status": "pending"})
        return _FakeResp(status_code=500, json_data={"error": {"message": "poll boom"}})

    _patch_request(monkeypatch, fake)
    with flask_core.app_context():
        out = OpenRouterService.generate_video(
            "google/veo-3.1", "clip", poll_interval=0, timeout=600)
    assert out["success"] is False
    assert "Video poll failed" in out["error"]
    assert "poll boom" in out["error"]
