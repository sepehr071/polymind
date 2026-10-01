"""Exception handlers for the FastAPI bridge app.

Mirrors ``app/utils/errors.py`` (the Flask handlers) so response *bodies* are
byte-for-byte identical between the Flask and FastAPI stacks. The frontend was
built against the legacy flat-JSON error shape ``{"error": msg, "status": code}``
(plus DLP's ``{code, matches}``) — FastAPI's defaults (``{"detail": ...}`` /
422 on validation) would break it, so we override them here.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.utils.errors import APIError

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Auth/identity failure with a byte-exact legacy body + status.

    Raised from ``app.api.deps`` (token/role/feature gates). Carries the exact
    JSON body and HTTP status the Flask JWT callbacks would have produced.
    """

    def __init__(self, status: int, body: dict) -> None:
        super().__init__(body.get("error", "auth error"))
        self.status = status
        self.body = body


def install_exception_handlers(app: FastAPI) -> None:
    """Register all handlers on the FastAPI app."""

    @app.exception_handler(AuthError)
    async def _handle_auth_error(_request: Request, err: AuthError) -> JSONResponse:
        return JSONResponse(err.body, status_code=err.status)

    @app.exception_handler(APIError)
    async def _handle_api_error(_request: Request, err: APIError) -> JSONResponse:
        return JSONResponse(err.to_dict(), status_code=err.status_code)

    # DLP block / confirm-required. Import here to avoid pulling the DLP gate
    # (and its transitive service deps) at module import time.
    from app.services.dlp_gate import DLPBlockedError, format_blocked_response

    @app.exception_handler(DLPBlockedError)
    async def _handle_dlp_blocked(_request: Request, err: DLPBlockedError) -> JSONResponse:
        return JSONResponse(format_blocked_response(err), status_code=403)

    # Spend gate — budget cap / prepaid-credit exhaustion -> HTTP 402.
    from app.services.spend_gate import BudgetExceededError, format_budget_blocked_response

    @app.exception_handler(BudgetExceededError)
    async def _handle_budget_exceeded(_request: Request, err: BudgetExceededError) -> JSONResponse:
        return JSONResponse(format_budget_blocked_response(err), status_code=402)

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(_request: Request, err: StarletteHTTPException) -> JSONResponse:
        # Starlette default body is {"detail": ...}; remap to the legacy shape.
        detail = err.detail
        if isinstance(detail, dict):
            # A router that raised HTTPException(detail={...}) already supplied a
            # legacy-shaped body — pass it through untouched.
            return JSONResponse(detail, status_code=err.status_code)
        message = detail if isinstance(detail, str) else "error"
        return JSONResponse(
            {"error": message, "status": err.status_code},
            status_code=err.status_code,
            headers=getattr(err, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_request: Request, err: RequestValidationError) -> JSONResponse:
        # Malformed/missing body params: legacy stack returned 400, not 422.
        try:
            first = err.errors()[0]
            loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
            msg = first.get("msg", "Invalid request")
            message = f"{loc}: {msg}" if loc else msg
        except Exception:  # noqa: BLE001
            message = "Invalid request"
        return JSONResponse({"error": message, "status": 400}, status_code=400)

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, err: Exception) -> JSONResponse:
        logger.exception("unhandled exception in FastAPI bridge: %s", err)
        return JSONResponse(
            {"error": "Internal server error", "status": 500}, status_code=500
        )
