"""AI presentation generator routes — outline SSE, CRUD, render SSE.

Endpoints under ``/api/presentations`` (mounted in ``routers/__init__.py``):

  * ``POST /presentations/outline``        — SSE. Assembles owner-scoped source
    text, gates (DLP + spend) in the HANDLER, then streams an ``outlining``
    status and the generated outline; persists a ``presentations`` row.
  * ``GET  /presentations``                — list the caller's decks (owner-scoped).
  * ``GET  /presentations/{pid}``          — one deck (owner-scoped, 404 else).
  * ``PATCH /presentations/{pid}``         — patch outline/title/theme.
  * ``DELETE /presentations/{pid}``        — delete (owner-scoped).
  * ``POST /presentations/{pid}/render``   — SSE. Fans out per-slide AI images,
    renders the .pptx, persists it as a downloadable upload, emits a ``file``
    artifact then ``done``.

Conventions (CLAUDE.md + payroll.py / misc_a.py):
  * The router carries ``Depends(flask_ctx)`` so every request runs inside one
    Flask app_context (every model/service below is reused verbatim). Auth + the
    feature gate are applied per-route.
  * ``current_user`` resolves to a USER DICT — the id is ``str(user['_id'])``.
  * Errors are the legacy flat ``{"error", "status"}`` shape via ``JSONResponse``
    (never Pydantic / ``response_model``).
  * DLP + spend gates run in the HANDLER, BEFORE the SSE response — never inside
    the producer. Blocking gate calls are offloaded via
    ``anyio.to_thread.run_sync``. ``DLPBlockedError`` (-> global 403) and
    ``BudgetExceededError`` (-> global 402) propagate UNCAUGHT past the handler.
  * Background worker threads touching ``db.session`` open their OWN
    ``db.session_scope()`` (the SSE runner thread is a fresh contextvar context).
    Request values are pre-fetched into handler locals BEFORE the thread handoff.
  * ``OpenRouterService`` is the SOLE usage writer — ``generate_image`` /
    ``generate_outline`` are passed ``workspace_id``/``project_id``/``origin``/
    ``feature`` so every round-trip is attributed; we NEVER call
    ``UsageLogModel.create``.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import queue
import threading
import time
import uuid as _uuid

import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.core import db
from app.api.deps import current_user, feature_dep, flask_ctx
from app.api.sse import sse_stream_sync
from app.models.presentation import PresentationModel
from app.models.upload import UploadModel
from app.services import dlp_gate, spend_gate, stream_concurrency
from app.services import presentation_service as psvc
from app.services.openrouter_service import OpenRouterService
from app.services.pptx_renderer import PptxRenderer

logger = logging.getLogger(__name__)

# Router-level Flask app_context (mirrors payroll.py / every feature router).
router = APIRouter(dependencies=[Depends(flask_ctx)])

# Default image model for per-slide art = the Image Studio auto-default.
_IMAGE_MODEL = OpenRouterService.IMAGE_STUDIO_MODEL_IDS[0]

# Mime type for the rendered .pptx download.
_PPTX_MIME = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)

# Cost-amplification guards. A client can POST an inline ``outline`` to /render
# (or a huge ``slide_count`` to /outline) with arbitrarily many image_prompt
# slides -> hundreds of billed ``generate_image`` calls. The spend gate no-ops
# while ``billing_enforcement`` is OFF (the default), so these hard caps are the
# only throttle today. Slides beyond ``_MAX_SLIDE_IMAGES`` still render (text);
# only the number of GENERATED images is capped (graceful, like image-failure).
_MAX_SLIDES = 40
_MAX_SLIDE_IMAGES = 20
_MAX_CONCURRENT_STREAMS = 3
# Multi-agent outline stages can sit silent 30–90s on OpenRouter; without
# keepalives CDN / browser abort → FE "network error". Match chat/arena.
_KEEPALIVE_INTERVAL = 12
_OUTLINE_WALLCLOCK = 900  # hard cap for whole multi-agent outline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _json_body(request: Request) -> dict:
    """Read the JSON body, tolerating empty/garbage like get_json(silent=True).

    A non-JSON / empty body yields ``{}`` so per-route validation (e.g.
    topic-required -> 400) runs cleanly instead of raising a 500 (mirrors
    payroll.py)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _sse(event_type: str, data: dict) -> str:
    """Format an SSE frame. ``ensure_ascii=False`` keeps Persian outline text
    readable on the wire (the frontend decodes UTF-8)."""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _uid(user) -> str:
    """Read the user id from ``current_user`` — a dict keyed ``_id`` here."""
    return str(user["_id"]) if isinstance(user, dict) else str(user.id)


def _decode_data_uri(uri):
    """Decode a ``data:image/...;base64,<b64>`` URI (or bare b64) to bytes; None
    on falsy/garbage."""
    if not uri:
        return None
    try:
        b64 = uri.split(",", 1)[1] if "," in uri else uri
        return base64.b64decode(b64)
    except Exception:  # noqa: BLE001
        return None


def _persist_pptx(*, user_id, data: bytes, name: str) -> dict:
    """Write the rendered .pptx into UPLOAD_FOLDER + an owner-scoped UploadModel
    row (mirrors payroll ``_persist_zip``). Returns the ``{type:'file', ...}``
    artifact dict the SSE ``file`` event ships. MUST run inside an active
    ``db.session_scope()`` (it writes a row)."""
    # Reuse the canonical upload-folder resolver (mkdir-on-miss) from uploads.
    from app.api.routers.uploads import _get_upload_folder

    folder = _get_upload_folder()
    disk_filename = f"{_uuid.uuid4().hex}.pptx"
    dst = os.path.join(folder, disk_filename)
    with open(dst, "wb") as fh:
        fh.write(data)
    size = os.path.getsize(dst)

    row = UploadModel.create(
        user_id=user_id,
        filename=disk_filename,
        original_name=name,
        mime_type=_PPTX_MIME,
        size=size,
        type="file",
        force_attachment=True,
        extraction_status="na",
    )
    upload_id = row["_id"]
    return {
        "type": "file",
        "url": f"/api/uploads/{upload_id}",
        "name": name,
        "ext": "pptx",
        "size": size,
        "upload_id": upload_id,
    }


# ---------------------------------------------------------------------------
# POST /presentations/outline — SSE
# ---------------------------------------------------------------------------
@router.post("/outline")
async def generate_outline(
    request: Request,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("presentations")),
):
    """Generate a deck outline and persist a ``presentations`` row, streaming
    progress via SSE.

    Body: ``{topic, slide_count?, tone?, audience?, language?, theme?,
    workspace_id?, project_id?, upload_ids?, knowledge_ids?, generate_images?,
    dlp_confirmed?, dlp_confirm_token?}``.

    Source assembly + the DLP/spend gates run HERE (offloaded), BEFORE the
    stream — a block is a real 403/402, never an in-stream error. The outline
    round-trip itself (blocking) runs on the SSE runner thread inside its own
    ``db.session_scope()``.
    """
    body = await _json_body(request)
    topic = (body.get("topic") or "").strip()
    if not topic:
        return JSONResponse({"error": "topic is required", "status": 400}, status_code=400)

    # Coerce + clamp defensively: a non-numeric value falls back to the default
    # (no 500), and the hard ``_MAX_SLIDES`` ceiling caps the outline-model ask.
    try:
        slide_count = int(body.get("slide_count") or 10)
    except (TypeError, ValueError):
        slide_count = 10
    slide_count = max(1, min(slide_count, _MAX_SLIDES))
    tone = body.get("tone")
    audience = body.get("audience")
    language = body.get("language") or "fa"
    theme = body.get("theme") or "polymind"
    workspace_id = body.get("workspace_id")
    project_id = body.get("project_id")
    upload_ids = body.get("upload_ids") or []
    knowledge_ids = body.get("knowledge_ids") or []
    generate_images = bool(body.get("generate_images", True))
    dlp_confirmed = bool(body.get("dlp_confirmed"))
    dlp_confirm_token = body.get("dlp_confirm_token")
    user_id = _uid(user)

    # Owner-scoped source assembly (foreign/missing ids silently dropped) — DB
    # read, offload off the event loop.
    source_text = await anyio.to_thread.run_sync(
        lambda: psvc.assemble_source_text(
            user_id=user_id, upload_ids=upload_ids, knowledge_ids=knowledge_ids
        )
    )

    # DLP gate over topic + assembled source (offloaded). DLPBlockedError -> 403.
    scan_text = topic + ("\n" + source_text if source_text else "")

    def _dlp() -> None:
        dlp_gate.gate(
            text=scan_text,
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            source="presentation",
            source_ref={"feature": "presentation"},
            confirmed=dlp_confirmed,
            dlp_confirm_token=dlp_confirm_token,
            user_lang=language,
        )

    await anyio.to_thread.run_sync(_dlp)

    # Spend gate (offloaded). BudgetExceededError -> 402.
    def _spend() -> None:
        spend_gate.gate(
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            origin="web",
            feature="presentation",
        )

    await anyio.to_thread.run_sync(_spend)

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
        # Pipeline runs on a helper thread so this generator can emit SSE
        # keepalives while OpenRouter stages block (else CDN idle-kills → FE
        # "network error"). Session scope stays on the helper (DB writes).
        from app.services.presentation_pipeline import run_outline_pipeline

        frame_q: queue.Queue = queue.Queue()
        _SENTINEL = object()

        def _worker() -> None:
            with db.session_scope():
                try:
                    outline = None
                    for kind, payload in run_outline_pipeline(
                        topic=topic,
                        source_text=source_text,
                        slide_count=slide_count,
                        tone=tone,
                        audience=audience,
                        language=language,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        stop_event=stop_event,
                    ):
                        if stop_event is not None and stop_event.is_set():
                            return
                        if kind == "phase":
                            frame_q.put(_sse("status", {"phase": payload}))
                        elif kind == "warning":
                            frame_q.put(_sse("warning", {"message": str(payload)}))
                        elif kind == "outline":
                            outline = payload
                    if stop_event is not None and stop_event.is_set():
                        return
                    if not outline or not outline.get("slides"):
                        frame_q.put(_sse(
                            "error",
                            {"error": "outline generation produced no slides", "status": 502},
                        ))
                        return
                    # Prefer strategist theme_hint only when client left default polymind.
                    eff_theme = theme
                    meta = outline.get("_meta") if isinstance(outline.get("_meta"), dict) else {}
                    hint = (meta.get("theme_hint") or "").strip().lower()
                    if theme == "polymind" and hint and hint != "polymind":
                        from app.services.presentation_themes import THEME_KEYS
                        if hint in THEME_KEYS:
                            eff_theme = hint
                    rec = PresentationModel.create(
                        user_id=user_id,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        title=outline.get("title") or topic,
                        language=language,
                        theme=eff_theme,
                        options={
                            "slide_count": slide_count,
                            "tone": tone,
                            "audience": audience,
                            "generate_images": generate_images,
                            "upload_ids": upload_ids,
                            "knowledge_ids": knowledge_ids,
                            "pipeline": "multi_agent_v1",
                            "deck_type": meta.get("deck_type"),
                            "density": meta.get("density"),
                        },
                        outline=outline,
                        status="outline_ready",
                    )
                    frame_q.put(_sse(
                        "outline",
                        {"id": rec["_id"], "outline": outline, "theme": eff_theme},
                    ))
                    frame_q.put(_sse("done", {"id": rec["_id"]}))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("presentation outline failed: %s", exc)
                    frame_q.put(_sse("error", {"error": str(exc), "status": 500}))
                finally:
                    frame_q.put(_SENTINEL)

        worker = threading.Thread(
            target=_worker, name="presentation-outline-pipeline", daemon=True,
        )
        worker.start()
        started = time.time()
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    return
                if time.time() - started > _OUTLINE_WALLCLOCK:
                    yield _sse("error", {
                        "error": "outline generation timed out",
                        "status": 504,
                    })
                    return
                try:
                    item = frame_q.get(timeout=_KEEPALIVE_INTERVAL)
                except queue.Empty:
                    # Raw SSE comment — FE idle watchdog + CDN stay alive
                    yield ": keepalive\n\n"
                    continue
                if item is _SENTINEL:
                    return
                yield item
        finally:
            if stop_event is not None:
                stop_event.set()
            worker.join(timeout=5)

    with preflight:
        preflight.hand_off()
        return sse_stream_sync(
            _produce,
            runner_name="presentation-outline-runner",
            on_close=preflight.on_close,
        )


# ---------------------------------------------------------------------------
# CRUD — list / detail / patch / delete (owner-scoped)
# ---------------------------------------------------------------------------
@router.get("")
async def list_presentations(
    request: Request,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("presentations")),
):
    """List the caller's decks (most-recent first), optional ``?project_id=``."""
    user_id = _uid(user)
    project_id = request.query_params.get("project_id") or None

    def _q():
        with db.session_scope():
            return PresentationModel.list_for_user(user_id, project_id=project_id)

    rows = await anyio.to_thread.run_sync(_q)
    return JSONResponse({"presentations": rows})


@router.get("/{pid}")
async def get_presentation(
    pid: str,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("presentations")),
):
    """One deck, owner-scoped (404 for missing / not-owned)."""
    user_id = _uid(user)

    def _q():
        with db.session_scope():
            return PresentationModel.find_by_id_for_user(pid, user_id)

    rec = await anyio.to_thread.run_sync(_q)
    if not rec:
        return JSONResponse({"error": "Presentation not found", "status": 404}, status_code=404)
    return JSONResponse(rec)


@router.patch("/{pid}")
async def update_presentation(
    pid: str,
    request: Request,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("presentations")),
):
    """Patch a deck's ``outline`` / ``title`` / ``theme`` (owner-scoped)."""
    body = await _json_body(request)
    user_id = _uid(user)
    fields = {k: body[k] for k in ("outline", "title", "theme") if k in body}

    def _u():
        with db.session_scope():
            if not PresentationModel.find_by_id_for_user(pid, user_id):
                return None
            return PresentationModel.update(pid, **fields)

    rec = await anyio.to_thread.run_sync(_u)
    if not rec:
        return JSONResponse({"error": "Presentation not found", "status": 404}, status_code=404)
    return JSONResponse(rec)


@router.delete("/{pid}")
async def delete_presentation(
    pid: str,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("presentations")),
):
    """Delete a deck (owner-scoped)."""
    user_id = _uid(user)

    def _d():
        with db.session_scope():
            if not PresentationModel.find_by_id_for_user(pid, user_id):
                return False
            return PresentationModel.delete(pid)

    deleted = await anyio.to_thread.run_sync(_d)
    if not deleted:
        return JSONResponse({"error": "Presentation not found", "status": 404}, status_code=404)
    return JSONResponse({"deleted": True})


# ---------------------------------------------------------------------------
# POST /presentations/{pid}/render — SSE
# ---------------------------------------------------------------------------
@router.post("/{pid}/render")
async def render_presentation(
    pid: str,
    request: Request,
    user: dict = Depends(current_user),
    _feat: dict = Depends(feature_dep("presentations")),
):
    """Render a deck to .pptx, streaming progress via SSE.

    Body (all optional): ``{outline?, dlp_confirmed?, dlp_confirm_token?}`` — a
    supplied ``outline`` (post-edit) overrides the persisted one. Per-slide AI
    images are generated for every slide carrying an ``image_prompt`` (when the
    deck's ``generate_images`` option is set). A failed image DEGRADES to a
    ``warning`` frame rather than aborting the render.

    Ownership resolve + the DLP (over the joined image prompts) + spend gates
    (one per imaged slide) run in the HANDLER BEFORE the stream. The image fan-
    out + pptx render + upload-persist run on a worker thread (its own
    ``db.session_scope()``); frames bridge back through a ``queue.Queue``.
    """
    body = await _json_body(request)
    user_id = _uid(user)

    def _load():
        with db.session_scope():
            return PresentationModel.find_by_id_for_user(pid, user_id)

    rec = await anyio.to_thread.run_sync(_load)
    if not rec:
        return JSONResponse({"error": "Presentation not found", "status": 404}, status_code=404)

    outline = body.get("outline") or rec.get("outline") or {}
    workspace_id = rec.get("workspace_id")
    project_id = rec.get("project_id")
    language = rec.get("language") or "fa"
    theme = rec.get("theme") or "polymind"
    gen_images = bool((rec.get("options") or {}).get("generate_images", True))
    dlp_confirmed = bool(body.get("dlp_confirmed"))
    dlp_confirm_token = body.get("dlp_confirm_token")

    slides = outline.get("slides") or []
    image_slides = (
        [(i, s.get("image_prompt")) for i, s in enumerate(slides) if s.get("image_prompt")]
        if gen_images
        else []
    )
    # Cost-amplification cap: bound the number of billed image calls BEFORE both
    # the per-image spend-gate loop and the worker fan-out. Slides past the cap
    # still render text-only (their idx never lands in ``images``).
    image_slides = image_slides[:_MAX_SLIDE_IMAGES]

    # Gate image prompts up-front: ONE DLP scan over the joined prompts, then one
    # spend check per imaged slide. Both offloaded, BEFORE the stream (block ==
    # real 403/402). No images -> no gates (renders text-only).
    if image_slides:
        prompts_text = "\n".join(p for _, p in image_slides)

        def _dlp() -> None:
            dlp_gate.gate(
                text=prompts_text,
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                source="presentation",
                source_ref={"feature": "presentation_image"},
                confirmed=dlp_confirmed,
                dlp_confirm_token=dlp_confirm_token,
                user_lang=language,
            )

        await anyio.to_thread.run_sync(_dlp)

        def _spend() -> None:
            spend_gate.gate(
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                origin="web",
                feature="presentation_image",
            )

        for _ in image_slides:
            await anyio.to_thread.run_sync(_spend)

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

    frame_q: "queue.Queue" = queue.Queue()

    def _worker(stop_event) -> None:
        # Fresh contextvar context on this thread -> own session scope for every
        # model write (status flips, the upload-persist row).
        with db.session_scope():
            try:
                PresentationModel.update(pid, status="rendering")

                images: dict = {}
                total = len(image_slides)
                for done, (idx, prompt) in enumerate(image_slides):
                    # Client disconnected -> stop burning paid image calls. The
                    # ``finally`` below still fires the EOF sentinel so the
                    # producer drains cleanly.
                    if stop_event is not None and stop_event.is_set():
                        return
                    frame_q.put(_sse("status", {"phase": "imaging", "done": done, "total": total}))
                    res = OpenRouterService.generate_image(
                        prompt,
                        _IMAGE_MODEL,
                        n=1,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        feature="presentation_image",
                        origin="web",
                    )
                    if res.get("success"):
                        img_bytes = _decode_data_uri(res.get("image_data"))
                        if img_bytes:
                            images[idx] = img_bytes
                        else:
                            frame_q.put(_sse("warning", {"slide": idx, "message": "image decode failed"}))
                    else:
                        frame_q.put(_sse("warning", {"slide": idx, "message": "image failed"}))
                if total:
                    frame_q.put(_sse("status", {"phase": "imaging", "done": total, "total": total}))

                frame_q.put(_sse("status", {"phase": "rendering"}))
                data = PptxRenderer().render(
                    outline, theme=theme, language=language, images=images
                )
                name = f"{(outline.get('title') or 'presentation')}.pptx"
                artifact = _persist_pptx(user_id=user_id, data=data, name=name)

                PresentationModel.update(
                    pid,
                    status="ready",
                    outline=outline,
                    pptx_upload_id=artifact["upload_id"],
                )
                frame_q.put(_sse("file", artifact))
                frame_q.put(_sse("done", {"id": pid}))
            except Exception as exc:  # noqa: BLE001
                logger.warning("presentation render failed for %s: %s", pid, exc)
                try:
                    PresentationModel.update(pid, status="failed", error=str(exc))
                except Exception:  # noqa: BLE001 — best-effort status flip
                    pass
                frame_q.put(_sse("error", {"error": str(exc), "status": 500}))
            finally:
                frame_q.put(None)  # EOF sentinel for the draining producer

    def _produce(stop_event):
        # The producer ONLY bridges frames + honors stop_event — no db.session
        # access here. All DB work happens on the worker thread (own scope). The
        # event is threaded into the worker so a disconnect halts paid image calls.
        worker = threading.Thread(
            target=_worker, args=(stop_event,), name="presentation-render", daemon=True
        )
        worker.start()
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    break
                try:
                    frame = frame_q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if frame is None:
                    break
                yield frame
        finally:
            worker.join(timeout=5)
            if worker.is_alive():
                logger.warning(
                    "presentation render worker still alive after join "
                    "(pid=%s stop=%s)",
                    pid,
                    stop_event.is_set() if stop_event is not None else None,
                )

    with preflight:
        preflight.hand_off()
        return sse_stream_sync(
            _produce,
            runner_name="presentation-render-runner",
            on_close=preflight.on_close,
        )


__all__ = ["router"]
