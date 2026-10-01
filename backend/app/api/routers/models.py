"""Models + model-catalog routes, translated from app/routes/models.py and
app/routes/model_catalog.py.

Both Flask blueprints (``models_bp`` and ``model_catalog_bp``) mounted under the
SAME url_prefix ``/api/models`` — so they collapse into ONE FastAPI router here.

ROUTE ORDER IS LOAD-BEARING: Starlette matches path operations in registration
order. The legacy ``models_bp`` declares a greedy ``GET /<path:model_id>``; in
Flask that lives in a separate URL map from the catalog routes, so specificity
sorts it correctly. Under one FastAPI router the catch-all would shadow every
``/quick-models`` / ``/catalog*`` / ``/categories`` / ``/refresh`` route, so the
catch-all ``GET /{model_id:path}`` is declared LAST.

The in-process models cache (``_models_cache``) is copied verbatim from the Flask
blueprint — it is a self-contained module-level cache, identical semantics.
"""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import current_user, flask_ctx, require_active, require_admin
from app.models.openrouter_model import OpenRouterModelDoc
from app.services.model_registry_service import ModelRegistryService
from app.services.openrouter_service import OpenRouterService
from app.utils.quick_models import QUICK_MODELS

# Router-level dependency: every request runs inside the Flask app_context.
router = APIRouter(dependencies=[Depends(flask_ctx)])


# ---------------------------------------------------------------------------
# In-process models cache (verbatim from app/routes/models.py:10-29).
# ---------------------------------------------------------------------------
_models_cache = {
    "data": None,
    "timestamp": 0,
}
CACHE_DURATION = 3600  # 1 hour
# Guards the cache refresh so concurrent requests on boot/expiry don't all
# refetch the full model list through the outbound proxy (thundering herd).
_models_cache_lock = threading.Lock()


def get_cached_models():
    """Get models with caching (mirrors models_bp.get_cached_models)."""

    def _stale():
        return (
            _models_cache["data"] is None
            or time.time() - _models_cache["timestamp"] > CACHE_DURATION
        )

    # Fast path: serve the warm cache without locking.
    if not _stale():
        return _models_cache["data"]

    # Cold/expired: refresh under a lock (double-checked) so only one thread
    # fetches while the rest wait, then all read the fresh value.
    with _models_cache_lock:
        if _stale():
            models = OpenRouterService.get_available_models()
            _models_cache["data"] = models
            _models_cache["timestamp"] = time.time()

    return _models_cache["data"]


def _iso(value):
    """Coerce a datetime (or already-stringified datetime) to an ISO string.

    The ``OpenRouterModelDoc`` facade's ``to_dict()`` already stringifies
    ``last_synced_at`` (SerializableMixin emits ISO strings for datetimes), so
    callers must tolerate a ``str`` here — calling ``.isoformat()`` on it blindly
    raises ``AttributeError``. Real datetimes are still handled for safety.
    """
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else value


def _serialize_doc(doc: dict) -> dict:
    """Convert any datetime fields for JSON output (mirrors model_catalog._serialize_doc)."""
    if not doc:
        return doc
    result = dict(doc)
    # _id is a plain string for this collection — no ObjectId conversion needed.
    if "last_synced_at" in result and result["last_synced_at"]:
        result["last_synced_at"] = _iso(result["last_synced_at"])
    # Strip raw field from list responses to keep payload small
    result.pop("raw", None)
    return result


# ===========================================================================
# model_catalog_bp routes (declared FIRST — more specific than the catch-all).
# ===========================================================================
@router.get("/quick-models")
def list_quick_models(user: dict = Depends(current_user)):
    """Return the canonical quick-models registry (id + display name) for frontend boot."""
    return {
        "models": [
            {"id": model_id, "name": display_name}
            for model_id, display_name in QUICK_MODELS.items()
        ]
    }


@router.get("/local-status")
def local_ai_status(user: dict = Depends(current_user)):
    """Whether the free local (Ollama) model is configured/reachable.

    Drives the "Local AI" tag on studio assistants (email writer). When false,
    the ``polymind/local-ai`` model still works via a silent cloud fallback.
    """
    from app.services.local_llm_service import local_llm_available

    return {"available": local_llm_available()}


@router.get("/catalog/refresh-status")
def refresh_status(user: dict = Depends(current_user)):
    """Return registry metadata: last sync time, count, staleness flag."""
    last_synced_at = OpenRouterModelDoc.get_last_sync_at()
    count = OpenRouterModelDoc.count()
    registry = ModelRegistryService()
    return {
        "last_synced_at": last_synced_at.isoformat() if last_synced_at else None,
        "count": count,
        "is_stale": registry.is_stale(),
        "has_models": count > 0,
    }


@router.post("/catalog/refresh")
def refresh_catalog(user: dict = Depends(require_admin)):
    """Trigger a synchronous model registry refresh from OpenRouter. Admin only."""
    registry = ModelRegistryService()
    result = registry.refresh()
    if "error" in result:
        return JSONResponse({"error": result["error"]}, status_code=502)
    return result


@router.get("/catalog/{model_id:path}")
def get_catalog_model(model_id: str, user: dict = Depends(current_user)):
    """Return a single model doc plus lazy-loaded endpoint data.

    The ``{model_id:path}`` converter mirrors Flask's ``<path:model_id>`` so
    slashes in the model id (e.g. 'openai/gpt-4o') pass through correctly.
    """
    registry = ModelRegistryService()
    doc = registry.get(model_id)
    if not doc:
        return JSONResponse({"error": "model not found"}, status_code=404)

    result = dict(doc)
    if "last_synced_at" in result and result["last_synced_at"]:
        result["last_synced_at"] = _iso(result["last_synced_at"])

    # Attach endpoints lazily
    endpoints = registry.get_endpoints(model_id)
    result["endpoints"] = endpoints

    return result


@router.get("/catalog")
def list_catalog(
    request: Request,
    modality: str | None = None,
    capability: str | None = None,
    sort: str = "newest",
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(current_user),
):
    """List models from the local registry with optional filtering and pagination.

    Query params:
      modality    — filter by output modality: image | audio | text | video
      capability  — filter by a supported_parameter value
      sort        — newest | price | context  (default: newest)
      page        — 1-based page number (default: 1)
      page_size   — items per page (default: 50, max 200)
    """
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))

    sort_map = {
        "newest": ("created", -1),
        "price": ("pricing.prompt", 1),
        "context": ("context_length", -1),
    }
    sort_by, sort_dir = sort_map.get(sort, ("created", -1))

    # Filtered queries
    if modality:
        docs = OpenRouterModelDoc.find_by_modality(output_modalities=[modality])
    elif capability:
        docs = OpenRouterModelDoc.find_by_capability(capability)
    else:
        skip = (page - 1) * page_size
        docs = OpenRouterModelDoc.find_all(
            skip=skip, limit=page_size, sort_by=sort_by, sort_dir=sort_dir
        )
        total = OpenRouterModelDoc.count()
        return {
            "data": [_serialize_doc(d) for d in docs],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # For filtered queries, apply pagination in Python (result set is bounded)
    total = len(docs)
    skip = (page - 1) * page_size
    docs = docs[skip : skip + page_size]

    return {
        "data": [_serialize_doc(d) for d in docs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ===========================================================================
# models_bp routes.
# ===========================================================================
@router.post("/refresh")
def refresh_models(user: dict = Depends(require_active)):
    """Force refresh the models cache."""
    global _models_cache
    _models_cache = {
        "data": None,
        "timestamp": 0,
    }

    models = get_cached_models()

    return {
        "message": "Models cache refreshed",
        "count": len(models),
    }


@router.get("/categories")
def get_model_categories(user: dict = Depends(require_active)):
    """Get models grouped by provider/category."""
    models = get_cached_models()

    categories: dict = {}
    for model in models:
        model_id = model.get("id", "")
        # Extract provider from model ID (e.g., "openai/gpt-4" -> "openai")
        provider = model_id.split("/")[0] if "/" in model_id else "other"

        if provider not in categories:
            categories[provider] = []

        categories[provider].append({
            "id": model.get("id"),
            "name": model.get("name"),
            "context_length": model.get("context_length", 4096),
        })

    # Sort models within each category
    for provider in categories:
        categories[provider].sort(key=lambda x: x["name"])

    return {"categories": categories}


@router.get("")
def get_models(user: dict = Depends(require_active)):
    """Get list of available OpenRouter models."""
    models = get_cached_models()

    # Format for frontend
    formatted_models = []
    for model in models:
        formatted_models.append({
            "id": model.get("id"),
            "name": model.get("name"),
            "description": model.get("description", ""),
            "context_length": model.get("context_length", 4096),
            "pricing": {
                "prompt": model.get("pricing", {}).get("prompt", "0"),
                "completion": model.get("pricing", {}).get("completion", "0"),
            },
            "top_provider": model.get("top_provider", {}),
            "architecture": model.get("architecture", {}),
        })

    # Sort by name
    formatted_models.sort(key=lambda x: x["name"])

    return {
        "models": formatted_models,
        "count": len(formatted_models),
    }


# ---------------------------------------------------------------------------
# Greedy catch-all — MUST be the LAST route declared. Mirrors the legacy
# models_bp ``GET /<path:model_id>`` single-model lookup.
# ---------------------------------------------------------------------------
@router.get("/{model_id:path}")
def get_model(model_id: str, user: dict = Depends(require_active)):
    """Get details for a specific model."""
    models = get_cached_models()

    for model in models:
        if model.get("id") == model_id:
            return {
                "model": {
                    "id": model.get("id"),
                    "name": model.get("name"),
                    "description": model.get("description", ""),
                    "context_length": model.get("context_length", 4096),
                    "pricing": model.get("pricing", {}),
                    "top_provider": model.get("top_provider", {}),
                    "architecture": model.get("architecture", {}),
                    "per_request_limits": model.get("per_request_limits", {}),
                }
            }

    return JSONResponse({"error": "Model not found"}, status_code=404)


__all__ = ["router"]
