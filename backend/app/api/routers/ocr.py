"""OCR assistant routes — multi-file extract SSE.

``POST /api/ocr/extract`` — SSE. DLP + spend in the HANDLER before stream.
Sequential per-file OpenRouter calls (native PDF / vision image).
"""
from __future__ import annotations

import json
import logging
from typing import List

import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.core import db
from app.api.deps import current_user, feature_dep, flask_ctx
from app.api.sse import sse_stream_sync
from app.models.ocr_job import OcrJobModel
from app.models.upload import UploadModel
from app.prompts.ocr import OCR_MAX_FILES
from app.services import dlp_gate, ocr_service, spend_gate, stream_concurrency

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(flask_ctx)])

_MAX_CONCURRENT_STREAMS = 3


async def _json_body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _uid(user) -> str:
    return str(user["_id"]) if isinstance(user, dict) else str(user.id)


def _scan_text(prompt: str, user_id: str, upload_ids: List[str]) -> str:
    """Prompt + owner-scoped extracted_text for DLP (never trust client text)."""
    parts = [(prompt or "").strip()]
    for uid in upload_ids:
        try:
            meta = UploadModel.get_extracted_text_for_user(uid, user_id)
            text = (meta or {}).get("extracted_text") or ""
        except Exception:  # noqa: BLE001
            text = ""
        if text:
            parts.append(text)
    return "\n\n".join(p for p in parts if p)


@router.post("/extract")
async def extract(
    request: Request,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("ocr_assistant")),
):
    """SSE extract: status / file_result / file_error / error / done."""
    body = await _json_body(request)
    raw_ids = body.get("upload_ids") or []
    if not isinstance(raw_ids, list) or not raw_ids:
        return JSONResponse(
            {"error": "upload_ids is required (1–5 files)", "status": 400},
            status_code=400,
        )
    upload_ids = [str(u).strip() for u in raw_ids if u]
    if not upload_ids:
        return JSONResponse(
            {"error": "upload_ids is required (1–5 files)", "status": 400},
            status_code=400,
        )
    if len(upload_ids) > OCR_MAX_FILES:
        return JSONResponse(
            {
                "error": f"at most {OCR_MAX_FILES} files per run",
                "status": 400,
            },
            status_code=400,
        )

    prompt = body.get("prompt") or ""
    if not isinstance(prompt, str):
        prompt = str(prompt)
    workspace_id = body.get("workspace_id")
    project_id = body.get("project_id")
    dlp_confirmed = bool(body.get("dlp_confirmed"))
    dlp_confirm_token = body.get("dlp_confirm_token")
    user_lang = (body.get("lang") or "en")[:2]
    user_id = _uid(user)

    def _dlp() -> None:
        with db.session_scope():
            text = _scan_text(prompt, user_id, upload_ids)
            # Gate needs non-empty text when only images (no extract cache).
            # Fall back to a short sentinel so policy still runs on confirm path;
            # pure empty + no extract → still call with prompt-or-sentinel.
            if not text.strip():
                text = prompt.strip() or "[ocr attachments]"
            dlp_gate.gate(
                text=text,
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                source="ocr",
                source_ref={"feature": "ocr", "upload_ids": upload_ids[:OCR_MAX_FILES]},
                confirmed=dlp_confirmed,
                dlp_confirm_token=dlp_confirm_token,
                user_lang=user_lang,
            )

    await anyio.to_thread.run_sync(_dlp)

    def _spend() -> None:
        spend_gate.gate(
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            origin="web",
            feature="ocr",
        )

    await anyio.to_thread.run_sync(_spend)

    # Capture for producer closure (no request object on worker thread).
    ids = list(upload_ids)
    ptext = prompt
    wid = workspace_id
    pid = project_id
    uid = user_id

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

    def _file_stubs() -> list:
        stubs = []
        for upload_id in ids:
            name = None
            try:
                rec = UploadModel.find_by_id_for_user(upload_id, uid)
                name = (rec or {}).get("original_name")
            except Exception:  # noqa: BLE001
                name = None
            stubs.append({
                "upload_id": upload_id,
                "original_name": name,
                "status": "pending",
                "content": None,
                "error": None,
            })
        return stubs

    def _produce(stop_event):
        with db.session_scope():
            job = OcrJobModel.create(
                user_id=uid,
                workspace_id=wid,
                prompt=ptext,
                files=_file_stubs(),
                status="running",
            )
            job_id = job["_id"]
            try:
                total = len(ids)
                yield _sse(
                    "status",
                    {
                        "phase": "extracting",
                        "done": 0,
                        "total": total,
                        "job_id": job_id,
                    },
                )

                results = []
                ok = 0
                failed = 0
                cancelled = False

                for i, upload_id in enumerate(ids):
                    if stop_event.is_set():
                        cancelled = True
                        break
                    yield _sse(
                        "status",
                        {
                            "phase": "extracting",
                            "done": i,
                            "total": total,
                            "upload_id": upload_id,
                            "job_id": job_id,
                        },
                    )
                    row = ocr_service.extract_one(
                        upload_id=upload_id,
                        user_id=uid,
                        prompt=ptext,
                        workspace_id=wid,
                        project_id=pid,
                    )
                    results.append(row)
                    if row.get("ok"):
                        ok += 1
                        OcrJobModel.patch_file(
                            job_id,
                            upload_id,
                            status="ok",
                            original_name=row.get("original_name"),
                            content=row.get("content") or "",
                            error=None,
                        )
                        yield _sse(
                            "file_result",
                            {
                                "upload_id": row["upload_id"],
                                "original_name": row.get("original_name"),
                                "content": row.get("content") or "",
                                "index": i,
                                "total": total,
                                "job_id": job_id,
                            },
                        )
                    else:
                        failed += 1
                        OcrJobModel.patch_file(
                            job_id,
                            upload_id,
                            status="error",
                            original_name=row.get("original_name"),
                            content=None,
                            error=row.get("error") or "extraction failed",
                        )
                        yield _sse(
                            "file_error",
                            {
                                "upload_id": row["upload_id"],
                                "original_name": row.get("original_name"),
                                "error": row.get("error") or "extraction failed",
                                "index": i,
                                "total": total,
                                "job_id": job_id,
                            },
                        )

                if cancelled:
                    final_status = "cancelled"
                elif failed and not ok:
                    final_status = "failed"
                else:
                    final_status = "done"
                OcrJobModel.update(job_id, status=final_status)

                yield _sse(
                    "done",
                    {
                        "job_id": job_id,
                        "results": results,
                        "totals": {"ok": ok, "failed": failed, "total": len(results)},
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ocr extract stream failed: %s", exc)
                try:
                    OcrJobModel.update(job_id, status="failed")
                except Exception:  # noqa: BLE001
                    pass
                yield _sse("error", {"error": str(exc), "status": 500, "job_id": job_id})

    with preflight:
        preflight.hand_off()
        return sse_stream_sync(
            _produce, runner_name="ocr-extract-runner", on_close=preflight.on_close,
        )


@router.get("/jobs")
async def list_jobs(
    request: Request,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("ocr_assistant")),
):
    """Owner-scoped history. List rows omit file content."""
    user_id = _uid(user)
    try:
        limit = min(int(request.query_params.get("limit", 50)), 100)
    except (TypeError, ValueError):
        limit = 50

    def _q():
        with db.session_scope():
            return OcrJobModel.list_for_user(user_id, limit=limit)

    rows = await anyio.to_thread.run_sync(_q)
    return JSONResponse({"jobs": rows})


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("ocr_assistant")),
):
    user_id = _uid(user)

    def _q():
        with db.session_scope():
            return OcrJobModel.find_by_id_for_user(job_id, user_id)

    rec = await anyio.to_thread.run_sync(_q)
    if not rec:
        return JSONResponse({"error": "Job not found", "status": 404}, status_code=404)
    return JSONResponse(rec)


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("ocr_assistant")),
):
    user_id = _uid(user)

    def _d():
        with db.session_scope():
            return OcrJobModel.delete_for_user(job_id, user_id)

    ok = await anyio.to_thread.run_sync(_d)
    if not ok:
        return JSONResponse({"error": "Job not found", "status": 404}, status_code=404)
    return JSONResponse({"message": "Job deleted"})
