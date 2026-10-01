"""Payroll Payslip routes — preview + bulk payslip-ZIP generation.

Two endpoints under ``/api/payroll`` (mounted in ``routers/__init__.py``):

  * ``POST /payroll/preview``  — normal JSON. Parses an uploaded payroll XLSX and
    returns lightweight per-employee preview rows (no full earnings arrays).
  * ``POST /payroll/generate`` — SSE. Renders one PDF payslip per employee,
    emitting incremental ``status`` progress frames, zips them, persists the ZIP
    as an owner-scoped :class:`UploadModel` row, and emits a final ``file`` event
    pointing at ``/api/uploads/<id>``.

Both gate on ``Depends(current_user)`` + ``Depends(feature_dep('payroll'))`` (the
feature is default-ON; admins toggle it at ``/admin/features``). The router
carries ``Depends(flask_ctx)`` so every request runs inside one Flask
app_context (mirrors every other feature router).

Conventions followed (see CLAUDE.md + chat.py):
  * Bodies are read via the local ``_json_body`` raw-dict helper — never Pydantic
    / ``response_model`` (legacy dict shape).
  * Errors are the legacy flat ``{"error", "status"}`` shape, never ``{"detail"}``.
  * Upload bytes are resolved OWNER-SCOPED via ``_read_upload_bytes`` (which goes
    through ``UploadModel.find_by_id_for_user`` + ``UPLOAD_FOLDER``) — never a
    client-supplied path (cross-tenant upload IDOR guard).
  * Blocking work (openpyxl parse, PDF render) is offloaded: the preview parse
    runs via ``anyio.to_thread.run_sync``; the SSE producer runs end-to-end on
    the ``sse_stream_sync`` runner thread.
  * The SSE producer pre-fetches every request value into handler locals BEFORE
    the stream is built (the ``flask_ctx`` context is gone once the handler
    returns) and opens its OWN ``db.session_scope()`` for the ZIP-persist write
    (the runner thread is a fresh contextvar context).
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import uuid

import anyio
import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.core import db
from app.api.deps import current_user, feature_dep, flask_ctx
from app.api.sse import sse_stream_sync
from app.models.upload import UploadModel
from app.services import stream_concurrency
from app.services.openrouter_service import _read_upload_bytes
from app.services.payroll_service import build_payslip_zip, parse_payroll
from app.settings import settings

logger = logging.getLogger(__name__)

# Router-level dependency: every request runs inside the Flask app_context (every
# model/service below is reused verbatim). Auth + the feature gate are applied
# per-route so ``current_user`` resolves to the user dict.
router = APIRouter(dependencies=[Depends(flask_ctx)])

# Sentinel pushed onto the render bridge queue when build_payslip_zip finishes
# (success or failure) so the draining producer stops waiting for progress frames.
_BUILD_DONE = object()
_MAX_CONCURRENT_STREAMS = 3


async def _json_body(request: Request) -> dict:
    """Read the JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _sse_event(event_type: str, data: dict) -> str:
    """Format data as an SSE event frame (mirrors chat.py's helper)."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _clean_str(val) -> "str | None":
    """Coerce an optional body field to a trimmed non-empty str (else None)."""
    if not isinstance(val, str):
        return None
    val = val.strip()
    return val or None


def _preview_rows(records: list) -> list:
    """Lightweight per-employee preview rows — NOT the full earnings arrays.

    The preview endpoint ships only the headline figures so the client can render
    a confirmation table without the heavy ``earnings``/``deductions`` breakdown
    dicts each record carries.
    """
    rows: list = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        rows.append({
            "code": rec.get("code"),
            "name": rec.get("name"),
            "net": rec.get("net"),
            "earnings_total": rec.get("earnings_total"),
            "deductions_total": rec.get("deductions_total"),
        })
    return rows


# ---------------------------------------------------------------------------
# POST /payroll/preview — normal JSON
# ---------------------------------------------------------------------------
@router.post("/preview")
async def preview_payroll(
    request: Request,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("payroll")),
):
    """Parse an uploaded payroll XLSX and return lightweight preview rows.

    Body: ``{upload_id, employer?, month?}``. Resolves the upload OWNER-SCOPED,
    reads its bytes off disk, then parses (blocking openpyxl work offloaded to a
    worker thread). Returns FLAT JSON with headline per-employee rows only.
    """
    user_id = str(user["_id"])
    data = await _json_body(request)

    upload_id = _clean_str(data.get("upload_id"))
    employer = _clean_str(data.get("employer"))
    month = _clean_str(data.get("month"))

    if not upload_id:
        return JSONResponse({"error": "upload_id is required", "status": 400}, status_code=400)

    # Owner-scoped resolve + disk read in one call (find_by_id_for_user under the
    # hood). None == missing / not-owned / unreadable -> 404 (looks absent).
    xlsx_bytes = _read_upload_bytes(upload_id, user_id=user_id)
    if xlsx_bytes is None:
        return JSONResponse({"error": "Upload not found", "status": 404}, status_code=404)

    # openpyxl parse is blocking -> offload off the event loop.
    try:
        parsed = await anyio.to_thread.run_sync(
            lambda: parse_payroll(xlsx_bytes, employer=employer, month_override=month)
        )
    except Exception as exc:  # noqa: BLE001 — surface a clean 400 on a bad workbook
        logger.warning("payroll preview parse failed for upload %s: %s", upload_id, exc)
        return JSONResponse(
            {"error": "Could not parse the payroll file.", "status": 400}, status_code=400
        )

    records = parsed.get("records") or []
    return JSONResponse({
        "month": parsed.get("month"),
        "employer": parsed.get("employer"),
        "count": len(records),
        "columns_ok": bool(parsed.get("columns_ok")),
        "warnings": parsed.get("warnings") or [],
        "records": _preview_rows(records),
    })


# ---------------------------------------------------------------------------
# POST /payroll/generate — SSE
# ---------------------------------------------------------------------------
@router.post("/generate")
async def generate_payslips(
    request: Request,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("payroll")),
):
    """Render one PDF payslip per employee, zip them, and stream progress via SSE.

    Body: ``{upload_id, employer?, month?}``. Every request value (user_id, the
    resolved upload bytes, employer/month overrides) is pre-fetched into locals
    HERE — before the producer is built — because the ``flask_ctx`` context is
    torn down once this handler returns and the SSE runner thread runs in a fresh
    contextvar context (it opens its own ``db.session_scope()`` for the persist).

    Frames: ``status`` ({phase: parsing | rendering(+done/total) | zipping}),
    a final ``file`` event ({type:'file', url, name, ext, size}), then ``done``.
    Any failure emits an ``error`` event ({error, status}) and stops.
    """
    user_id = str(user["_id"])
    data = await _json_body(request)

    upload_id = _clean_str(data.get("upload_id"))
    employer_override = _clean_str(data.get("employer"))
    month_override = _clean_str(data.get("month"))

    if not upload_id:
        return JSONResponse({"error": "upload_id is required", "status": 400}, status_code=400)

    # Owner-scoped resolve + disk read in the HANDLER (before the stream). None ==
    # missing / not-owned / unreadable -> 404 now, not an in-stream error.
    xlsx_bytes = _read_upload_bytes(upload_id, user_id=user_id)
    if xlsx_bytes is None:
        return JSONResponse({"error": "Upload not found", "status": 404}, status_code=404)

    preflight = stream_concurrency.StreamPreflight(user_id, _MAX_CONCURRENT_STREAMS)
    if not preflight.reserve():
        return JSONResponse(
            {"error": "too_many_streams", "status": 429},
            status_code=429,
            headers={"Retry-After": "5"},
        )
    if not preflight.acquire_global():
        with preflight:
            return JSONResponse(
                {"error": "server_busy", "status": 503},
                status_code=503,
                headers={"Retry-After": "5"},
            )

    def _produce(stop_event):
        """SSE producer — runs end-to-end on the sse_stream_sync runner thread.

        The whole body (incl. the DB persist's ``db.session_scope()``) is confined
        to this one thread, so a Flask app_context / DB session never spans a
        Starlette yield.

        ``build_payslip_zip`` is a single blocking call, so to surface a real
        per-record progress bar we run it on a HELPER thread and have its
        ``progress_cb(done, total)`` push ``status`` frames onto a thread-safe
        queue; this generator drains + yields them in real time (same bridge-queue
        idiom chat.py's data-analysis producer uses for its sandbox loop). A
        sentinel marks render completion. ``stop_event`` (set on client disconnect)
        is checked while draining so an abandoned job stops before the persist.
        """
        # --- parse (blocking openpyxl) -----------------------------------------
        yield _sse_event("status", {"phase": "parsing"})
        try:
            parsed = parse_payroll(
                xlsx_bytes, employer=employer_override, month_override=month_override
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("payroll generate parse failed for upload %s: %s", upload_id, exc)
            yield _sse_event("error", {"error": "Could not parse the payroll file.", "status": 400})
            return

        records = [r for r in (parsed.get("records") or []) if isinstance(r, dict)]
        month = parsed.get("month") or month_override or "payroll"
        employer = parsed.get("employer") or employer_override or ""
        total = len(records)

        if total == 0:
            yield _sse_event("error", {"error": "No employee records found in the file.", "status": 400})
            return

        # --- render + zip on a helper thread, draining progress frames here -----
        yield _sse_event("status", {"phase": "rendering", "done": 0, "total": total})

        frame_q: "queue.Queue" = queue.Queue()
        result_box: dict = {}

        def _progress_cb(done: int, total_: int) -> None:
            # Fires synchronously inside build_payslip_zip on the helper thread —
            # hand the frame to the producer via the queue (a generator can't yield
            # from inside a callback).
            frame_q.put(_sse_event("status", {
                "phase": "rendering", "done": int(done), "total": int(total_),
            }))

        def _run_build() -> None:
            try:
                result_box["zip"] = build_payslip_zip(
                    records, employer=employer, month=month, progress_cb=_progress_cb,
                )
            except Exception as exc:  # noqa: BLE001
                result_box["error"] = exc
            finally:
                frame_q.put(_BUILD_DONE)

        build_thread = threading.Thread(
            target=_run_build, name="payroll-render", daemon=True
        )
        build_thread.start()

        try:
            while True:
                if stop_event.is_set():
                    # Client disconnected — stop draining; the daemon build thread
                    # is abandoned (CPU-bound, bounded by the record count) and
                    # nothing is persisted.
                    return
                try:
                    frame = frame_q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if frame is _BUILD_DONE:
                    break
                yield frame
        finally:
            build_thread.join(timeout=5)
            if build_thread.is_alive():
                logger.warning(
                    "payroll render worker still alive after join "
                    "(upload=%s stop=%s)",
                    upload_id,
                    stop_event.is_set(),
                )

        if stop_event.is_set():
            return
        if result_box.get("error") is not None:
            logger.warning(
                "payroll payslip build failed for upload %s: %s",
                upload_id, result_box["error"],
            )
            yield _sse_event("error", {"error": "Failed to render payslips.", "status": 500})
            return

        zip_bytes = result_box.get("zip")
        if not zip_bytes:
            yield _sse_event("error", {"error": "Failed to render payslips.", "status": 500})
            return

        # --- persist the ZIP as an owner-scoped UploadModel row ----------------
        # Mirrors chat.py's _persist_one_file_artifact: write bytes into
        # UPLOAD_FOLDER under a fresh uuid disk name, create the owner-scoped row,
        # then url = /api/uploads/<id>. MUST run inside an explicit session scope:
        # the runner thread is a fresh contextvar context, so db.session has no
        # bound session until one is opened here.
        yield _sse_event("status", {"phase": "zipping"})
        out_name = f"payslips-{month}.zip"
        try:
            with db.session_scope():
                file_artifact = _persist_zip(zip_bytes, original_name=out_name, user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("payroll zip persistence failed for upload %s: %s", upload_id, exc)
            yield _sse_event("error", {"error": "Failed to save the payslip archive.", "status": 500})
            return

        yield _sse_event("file", file_artifact)
        yield _sse_event("done", {"count": total})

    with preflight:
        preflight.hand_off()
        return sse_stream_sync(
            _produce, runner_name="payroll-generate-runner", on_close=preflight.on_close,
        )


def _persist_zip(zip_bytes: bytes, *, original_name: str, user_id) -> dict:
    """Persist the payslip ZIP into UPLOAD_FOLDER + an owner-scoped UploadModel row.

    Mirrors ``chat.py:_persist_one_file_artifact``: a fresh uuid disk filename, the
    bytes written under ``UPLOAD_FOLDER``, then the row created with
    ``force_attachment=True`` (so ``GET /api/uploads/<id>`` serves it as a
    download) and ``extraction_status='na'``. ``original_name`` is preserved
    verbatim (Unicode) — the serve route returns it as an RFC 5987 Persian-safe
    Content-Disposition filename. Returns the ``{type:'file', ...}`` artifact dict
    the SSE ``file`` event ships.

    MUST be called inside an active ``db.session_scope()`` (it writes a row).
    """
    upload_folder = settings.get("UPLOAD_FOLDER", "uploads")
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder, exist_ok=True)

    disk_filename = f"{uuid.uuid4().hex}.zip"
    dst = os.path.join(upload_folder, disk_filename)
    with open(dst, "wb") as fh:
        fh.write(zip_bytes)
    size = os.path.getsize(dst)

    row = UploadModel.create(
        user_id=user_id,
        filename=disk_filename,
        original_name=original_name,
        mime_type="application/zip",
        size=size,
        type="file",
        force_attachment=True,
        extraction_status="na",
    )
    upload_id = row["_id"]
    return {
        "type": "file",
        "url": f"/api/uploads/{upload_id}",
        "name": original_name,
        "ext": "zip",
        "size": size,
    }


__all__ = ["router"]
