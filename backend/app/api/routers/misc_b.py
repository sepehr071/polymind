"""Compat shim — prefer ``helper`` / ``usage`` / ``health``.

Kept so tests and any stale imports keep working for one release.
"""
from app.api.routers.health import health_router
from app.api.routers.helper import _helper_rate, helper_router
from app.api.routers.usage import api_router

__all__ = ["helper_router", "api_router", "health_router", "_helper_rate"]
