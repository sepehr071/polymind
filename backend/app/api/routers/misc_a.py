"""Compat shim — prefer ``uploads`` / ``image_gen``.

Kept so tests and any stale imports keep working for one release.
"""
from app.api.routers.image_gen import image_router
from app.api.routers.uploads import _get_upload_folder, _safe_serve_name, router
from app.services import dlp_gate  # noqa: F401  — monkeypatch target for tests

__all__ = ["router", "image_router", "_get_upload_folder", "_safe_serve_name", "dlp_gate"]
