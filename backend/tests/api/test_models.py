"""Integration tests for the translated models + model-catalog router
(app.api.routers.models), mirroring tests/api/test_auth.py.

Two Flask blueprints (models_bp + model_catalog_bp) collapse into ONE FastAPI
router mounted at /api/models. These tests cover, per route:
  - happy path (status + shape, incl. the _id string alias on catalog docs)
  - auth gating (no token -> 401 token_missing; admin-only -> 403 exact body)
  - the key error codes the Flask routes return (404, 502)

External HTTP is ALWAYS mocked:
  - models_bp routes call OpenRouterService.get_available_models() -> monkeypatched
  - model_catalog refresh calls ModelRegistryService.refresh() -> monkeypatched
  - get_catalog_model calls ModelRegistryService.get_endpoints() -> monkeypatched
The in-process _models_cache is reset before each cache-backed assertion.
"""
import pytest

import app.api.routers.models as models_router
from app.services.openrouter_service import OpenRouterService
from app.services.model_registry_service import ModelRegistryService


# ---------------------------------------------------------------------------
# Fixtures: fake upstream model list + DB-seeded catalog rows.
# ---------------------------------------------------------------------------
_FAKE_MODELS = [
    {
        "id": "openai/gpt-4o",
        "name": "GPT-4o",
        "description": "OpenAI flagship",
        "context_length": 128000,
        "pricing": {"prompt": "0.000005", "completion": "0.000015"},
        "top_provider": {"is_moderated": True},
        "architecture": {"output_modalities": ["text"]},
        "per_request_limits": {"prompt_tokens": "100000"},
    },
    {
        "id": "anthropic/claude-sonnet-4.5",
        "name": "Claude Sonnet 4.5",
        "description": "Anthropic mid",
        "context_length": 200000,
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        "top_provider": {},
        "architecture": {"output_modalities": ["text"]},
        "per_request_limits": {},
    },
]


@pytest.fixture(autouse=True)
def _reset_models_cache():
    """The router-level OpenRouter cache is module-global; reset around each test."""
    models_router._models_cache = {"data": None, "timestamp": 0}
    yield
    models_router._models_cache = {"data": None, "timestamp": 0}


@pytest.fixture
def fake_models(monkeypatch):
    """Stub OpenRouterService.get_available_models so no real HTTP happens."""
    monkeypatch.setattr(
        OpenRouterService, "get_available_models", staticmethod(lambda: list(_FAKE_MODELS))
    )
    return _FAKE_MODELS


@pytest.fixture
def seed_catalog(flask_core):
    """Seed two openrouter_models rows via the real facade."""
    from app.models.openrouter_model import OpenRouterModelDoc

    items = [
        {
            "id": "openai/gpt-4o",
            "name": "GPT-4o",
            "context_length": 128000,
            "pricing": {"prompt": "0.000005", "completion": "0.000015"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            "supported_parameters": ["tools", "temperature"],
        },
        {
            "id": "google/gemini-2.5-flash-image",
            "name": "Gemini 2.5 Flash Image",
            "context_length": 1000000,
            "pricing": {"prompt": "0.000001", "completion": "0.000004"},
            "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["image"]},
            "supported_parameters": ["temperature"],
        },
    ]
    with flask_core.app_context():
        OpenRouterModelDoc.upsert_many(items)
    return items


# ===========================================================================
# models_bp: GET /api/models
# ===========================================================================
def test_get_models_happy(client, plain_headers, fake_models):
    resp = client.get("/api/models", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 2
    names = [m["name"] for m in body["models"]]
    # Sorted by name -> Claude before GPT.
    assert names == sorted(names)
    first = body["models"][0]
    assert set(first.keys()) == {
        "id", "name", "description", "context_length", "pricing",
        "top_provider", "architecture",
    }
    assert first["pricing"] == {"prompt": "0.000003", "completion": "0.000015"}


def test_get_models_no_token_401(client, fake_models):
    resp = client.get("/api/models")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_get_models_banned_403(client, banned_user, mint_token, fake_models):
    token = mint_token(banned_user["_id"], role="user")
    resp = client.get("/api/models", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["error"] == "Account has been suspended"


# ===========================================================================
# models_bp: GET /api/models/categories
# ===========================================================================
def test_get_categories_happy(client, plain_headers, fake_models):
    resp = client.get("/api/models/categories", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    cats = resp.json()["categories"]
    assert set(cats.keys()) == {"openai", "anthropic"}
    assert cats["openai"][0]["id"] == "openai/gpt-4o"
    assert cats["openai"][0]["context_length"] == 128000


def test_get_categories_no_token_401(client, fake_models):
    resp = client.get("/api/models/categories")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# models_bp: POST /api/models/refresh
# ===========================================================================
def test_refresh_models_happy(client, plain_headers, fake_models):
    resp = client.post("/api/models/refresh", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"] == "Models cache refreshed"
    assert body["count"] == 2


def test_refresh_models_no_token_401(client, fake_models):
    resp = client.post("/api/models/refresh")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# models_bp: GET /api/models/<path:model_id>  (greedy catch-all, declared LAST)
# ===========================================================================
def test_get_model_by_id_happy(client, plain_headers, fake_models):
    resp = client.get("/api/models/openai/gpt-4o", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    model = resp.json()["model"]
    assert model["id"] == "openai/gpt-4o"
    assert model["per_request_limits"] == {"prompt_tokens": "100000"}


def test_get_model_by_id_not_found_404(client, plain_headers, fake_models):
    resp = client.get("/api/models/does/not-exist", headers=plain_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Model not found"


def test_get_model_by_id_no_token_401(client, fake_models):
    resp = client.get("/api/models/openai/gpt-4o")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# model_catalog_bp: GET /api/models/quick-models
# ===========================================================================
def test_quick_models_happy(client, plain_headers):
    from app.utils.quick_models import QUICK_MODELS

    resp = client.get("/api/models/quick-models", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    models = resp.json()["models"]
    assert len(models) == len(QUICK_MODELS)
    first_id = next(iter(QUICK_MODELS))
    assert models[0]["id"] == first_id
    assert models[0]["name"] == QUICK_MODELS[first_id]


def test_quick_models_no_token_401(client):
    resp = client.get("/api/models/quick-models")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# model_catalog_bp: GET /api/models/catalog
#
# ``_serialize_doc`` is now string-tolerant on ``last_synced_at`` (the
# ``OpenRouterModelDoc`` facade already emits an ISO string via ``to_dict()``),
# so list / filtered / get-model paths return their 200 envelopes whether or not
# rows exist.
# ===========================================================================
def test_catalog_list_empty_happy(client, plain_headers):
    """Empty registry: the paginated envelope returns 200 with an empty page."""
    resp = client.get("/api/models/catalog", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert body["data"] == []


def test_catalog_list_with_rows_happy(client, plain_headers, seed_catalog):
    """With rows, the paginated envelope serializes each doc and returns 200."""
    resp = client.get("/api/models/catalog", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 50
    ids = {d["_id"] for d in body["data"]}
    assert ids == {"openai/gpt-4o", "google/gemini-2.5-flash-image"}
    # last_synced_at is serialized to an ISO string; the bulky `raw` blob is dropped.
    for d in body["data"]:
        assert isinstance(d["last_synced_at"], str)
        assert "raw" not in d


def test_catalog_list_filter_by_modality_happy(client, plain_headers, seed_catalog):
    resp = client.get(
        "/api/models/catalog", params={"modality": "image"}, headers=plain_headers
    )
    # The filtered path runs each matching doc through _serialize_doc -> 200.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {d["_id"] for d in body["data"]}
    assert ids == {"google/gemini-2.5-flash-image"}
    assert body["total"] == 1


def test_catalog_list_no_token_401(client):
    resp = client.get("/api/models/catalog")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# model_catalog_bp: GET /api/models/catalog/refresh-status
# ===========================================================================
def test_catalog_refresh_status_empty(client, plain_headers):
    resp = client.get("/api/models/catalog/refresh-status", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 0
    assert body["has_models"] is False
    assert body["last_synced_at"] is None
    # Empty registry is always stale.
    assert body["is_stale"] is True


def test_catalog_refresh_status_with_rows(client, plain_headers, seed_catalog):
    """With rows, refresh-status returns 200 with the populated registry metadata.

    ``ModelRegistryService.is_stale()`` now compares in UTC-aware space (treating
    a naive ``last_synced_at`` as UTC), so the freshly-upserted rows — written
    moments ago via ``upsert_many`` — are NOT stale, and the route returns its
    200 envelope rather than tripping the old naive/aware ``TypeError``.
    """
    resp = client.get("/api/models/catalog/refresh-status", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 2
    assert body["has_models"] is True
    # Rows were just synced, so the registry is fresh (not stale).
    assert body["is_stale"] is False
    assert isinstance(body["last_synced_at"], str)


def test_catalog_refresh_status_no_token_401(client):
    resp = client.get("/api/models/catalog/refresh-status")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# model_catalog_bp: GET /api/models/catalog/<path:model_id>
# ===========================================================================
def test_catalog_get_model_with_row_happy(
    client, plain_headers, seed_catalog, monkeypatch
):
    """Single-model lookup serializes the row (string-tolerant last_synced_at)
    and attaches lazily-loaded endpoints -> 200."""
    monkeypatch.setattr(
        ModelRegistryService, "get_endpoints", lambda self, mid: {"data": {"endpoints": []}}
    )
    resp = client.get("/api/models/catalog/openai/gpt-4o", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["_id"] == "openai/gpt-4o"
    assert isinstance(body["last_synced_at"], str)
    assert body["endpoints"] == {"data": {"endpoints": []}}


def test_catalog_get_model_not_found_404(client, plain_headers, monkeypatch):
    monkeypatch.setattr(ModelRegistryService, "get_endpoints", lambda self, mid: None)
    resp = client.get("/api/models/catalog/nope/missing", headers=plain_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "model not found"


def test_catalog_get_model_no_token_401(client):
    resp = client.get("/api/models/catalog/openai/gpt-4o")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# model_catalog_bp: POST /api/models/catalog/refresh  (admin only)
# ===========================================================================
def test_catalog_refresh_happy_admin(client, admin_headers, monkeypatch):
    monkeypatch.setattr(
        ModelRegistryService, "refresh", lambda self: {"synced": 7, "at": "2026-01-01T00:00:00"}
    )
    resp = client.post("/api/models/catalog/refresh", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["synced"] == 7
    assert body["at"] == "2026-01-01T00:00:00"


def test_catalog_refresh_upstream_error_502(client, admin_headers, monkeypatch):
    monkeypatch.setattr(
        ModelRegistryService, "refresh", lambda self: {"error": "upstream timeout"}
    )
    resp = client.post("/api/models/catalog/refresh", headers=admin_headers)
    assert resp.status_code == 502
    assert resp.json()["error"] == "upstream timeout"


def test_catalog_refresh_non_admin_403(client, plain_headers, monkeypatch):
    monkeypatch.setattr(ModelRegistryService, "refresh", lambda self: {"synced": 0})
    resp = client.post("/api/models/catalog/refresh", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Admin access required"


def test_catalog_refresh_no_token_401(client):
    resp = client.post("/api/models/catalog/refresh")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# Route-registration smoke + ordering proof.
# ===========================================================================
def test_models_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/models" in paths
    assert "/api/models/categories" in paths
    assert "/api/models/refresh" in paths
    assert "/api/models/quick-models" in paths
    assert "/api/models/catalog" in paths
    assert "/api/models/catalog/refresh-status" in paths
    assert "/api/models/catalog/refresh" in paths
    assert "/api/models/{model_id:path}" in paths
    assert "/api/models/catalog/{model_id:path}" in paths


def test_catalog_not_shadowed_by_catchall(client, plain_headers):
    """The greedy /{model_id:path} must NOT shadow /catalog (declared first).

    Uses the empty registry so /catalog returns its 200 envelope (no rows hit
    the legacy _serialize_doc bug) — the point is the path resolved to the
    catalog handler, not the single-model catch-all.
    """
    resp = client.get("/api/models/catalog", headers=plain_headers)
    assert resp.status_code == 200
    # /catalog returns the paginated envelope, NOT the single-model {"model": ...}.
    assert "data" in resp.json()
    assert "model" not in resp.json()


def test_quick_models_not_shadowed_by_catchall(client, plain_headers):
    """/quick-models resolves to the catalog handler, not /{model_id:path}."""
    resp = client.get("/api/models/quick-models", headers=plain_headers)
    assert resp.status_code == 200
    # quick-models returns a registry list, not a single-model {"model": ...}.
    assert "models" in resp.json()
    assert "model" not in resp.json()
