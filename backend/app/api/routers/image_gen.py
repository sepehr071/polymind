"""Image generation router — generate, history, threads, favorites.

Mounted at ``/api/image-gen``. Disk helpers live in uploads.py.
"""
from __future__ import annotations

import base64
import logging
import os
import time
import uuid as _uuid

import anyio
import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from app.api.deps import current_user, flask_ctx
from app.api.routers.uploads import _get_upload_folder, _safe_serve_name
from app.models.generated_image import (
    GeneratedImageModel,
    ImageConversationModel,
    decode_image_payload,
)
from app.models.llm_config import LLMConfigModel
from app.models.upload import UploadModel
from app.models.user import UserModel
from app.services import dlp_gate, spend_gate
from app.services.openrouter_service import OpenRouterService
from app.utils.helpers import serialize_doc
from app.utils.ids import is_valid_id
from app.utils.permissions import check_project_access, mask_image_money
from app.utils.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)

image_router = APIRouter(dependencies=[Depends(flask_ctx)])

def _upload_to_data_uri(upload: dict) -> str | None:
    """Read an owned image upload off disk and return a ``data:`` base64 URI.

    Returns ``None`` (caller skips silently) when the file is missing/unreadable.
    The mime is taken from the row, else guessed from the extension, default
    ``image/png``.
    """
    safe_name = _safe_serve_name(upload.get('filename') or '')
    if safe_name is None:
        return None
    file_path = os.path.join(_get_upload_folder(), safe_name)
    if not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, 'rb') as fh:
            raw = fh.read()
    except OSError as exc:  # noqa: BLE001 - best-effort; skip on read failure
        logger.warning("image assistant: failed to read base image: %s", exc)
        return None
    mime = upload.get('mime_type')
    if not mime:
        ext = safe_name.rsplit('.', 1)[1].lower() if '.' in safe_name else 'png'
        mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"
    encoded = base64.b64encode(raw).decode('ascii')
    return f"data:{mime};base64,{encoded}"


def _resolve_image_assistant(config_id: str, user_id: str):
    """Resolve + access-check an IMAGE assistant (LLMConfig with kind='image').

    Visibility mirrors ``configs.get_config``: owner OR public/template OR a
    project-scoped config the user can read (viewer). Returns ``(config, error)``
    where ``error`` is a ``JSONResponse`` to return, or ``(config, None)`` on
    success. ``config`` is ``None`` when an error is produced.
    """
    config = LLMConfigModel.find_by_id(config_id)
    if not config:
        return None, JSONResponse({'error': 'Assistant not found'}, status_code=404)

    if str(config.get('owner_id')) != user_id:
        visibility = config.get('visibility')
        if visibility in ('private', None):
            return None, JSONResponse({'error': 'Assistant not found'}, status_code=404)
        if visibility == 'project':
            cfg_pid = config.get('project_id')
            if not cfg_pid or not check_project_access(user_id, str(cfg_pid), 'viewer'):
                return None, JSONResponse({'error': 'Assistant not found'}, status_code=404)
        elif visibility not in ('public', 'template'):
            return None, JSONResponse({'error': 'Assistant not found'}, status_code=404)

    params = config.get('parameters') or {}
    if (params.get('kind') if isinstance(params, dict) else None) != 'image':
        return None, JSONResponse({'error': 'Not an image assistant'}, status_code=400)

    return config, None

# ===========================================================================
# /api/image-gen  (image_gen_bp) — PLAIN sync JSON (no SSE).
# ===========================================================================
@image_router.get("/models")
def get_image_models(user: dict = Depends(current_user)):
    """Get available image generation models."""
    models = OpenRouterService.get_image_capable_models()
    return JSONResponse({'models': models}, status_code=200)


@image_router.post("/generate")
async def generate_image(request: Request, user: dict = Depends(current_user)):
    """Generate an image."""
    user_id = str(user['_id'])
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        data = {}
    data = data if isinstance(data, dict) else {}

    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        return JSONResponse({'error': 'Prompt is required'}, status_code=400)

    # Per-user rate limit (cost/DoS speed-bump on the paid provider call) —
    # independent of billing_enforcement. Shared in-process limiter.
    retry = check_rate_limit("image_gen", user_id, max_calls=15, window=60)
    if retry is not None:
        return JSONResponse(
            {"error": "rate_limited", "retry_after": retry},
            status_code=429,
            headers={"Retry-After": str(int(retry))},
        )

    model = data.get('model')

    negative_prompt = data.get('negative_prompt', '')
    input_images = data.get('input_images', [])

    # Optional capability-gated generation params (Image API). Each is validated
    # below against the resolved model's live capabilities — provided-but-
    # unsupported / out-of-range -> 400. NONE of these are part of the DLP scan
    # (only the prompt + negative-prompt text is scanned).
    aspect_ratio = data.get('aspect_ratio')
    resolution = data.get('resolution')
    quality = data.get('quality')
    output_format = data.get('output_format')
    background = data.get('background')
    seed = data.get('seed')
    output_compression = data.get('output_compression')
    n_requested = data.get('n')

    # Validate user-supplied input_images FORMAT. The final image list is
    # assembled below (assistant base + parent edit base + these) and capped to
    # the model's limit, so we no longer 400 on count — overflow is dropped.
    if input_images:
        if not isinstance(input_images, list):
            return JSONResponse({'error': 'input_images must be a list'}, status_code=400)

        from app.utils.network import validate_external_https
        for img in input_images:
            if not isinstance(img, str):
                return JSONResponse(
                    {'error': 'Invalid image format. Must be base64 data URI or URL'},
                    status_code=400,
                )
            if img.startswith('data:image/'):
                continue
            if img.startswith('http://') or img.startswith('https://'):
                # SSRF guard — same helper as videoGenNode (HTTPS + public host).
                ok, reason = validate_external_https(img)
                if not ok:
                    return JSONResponse(
                        {'error': f'Invalid image URL ({reason})'},
                        status_code=400,
                    )
                continue
            return JSONResponse(
                {'error': 'Invalid image format. Must be base64 data URI or HTTPS URL'},
                status_code=400,
            )
    elif input_images is None:
        input_images = []

    start_time = time.time()

    user_doc = UserModel.find_by_id(user_id) or {}
    project_id_raw = data.get('project_id')
    workspace_id = (
        str(user_doc['active_workspace_id']) if user_doc.get('active_workspace_id') else None
    )
    project_id = str(project_id_raw) if project_id_raw else None
    dlp_confirmed = bool(data.get('dlp_confirmed'))

    # --- Conversational image-edit threads + image-assistant resolution ------
    # ``config_id``: an IMAGE assistant (LLMConfig, parameters.kind == 'image')
    #   overrides ``model``, prepends its system_prompt as a style preamble
    #   (the preamble is DLP-gated under the gen workspace before the provider
    #   call — see the separate enforce-mode pass below the user-prompt gate),
    #   and contributes its saved ``base_images`` to the input list.
    # ``parent_image_id``: the prior generated image being edited (its payload
    #   becomes an input/edit base).
    # ``conversation_id``: groups a series of edits; auto-created when absent.
    config_id = data.get('config_id')
    parent_image_id = data.get('parent_image_id')
    conversation_id = data.get('conversation_id')

    assistant_system_prompt = ''
    assistant_base_images: list[str] = []
    if config_id:
        config, err = _resolve_image_assistant(config_id, user_id)
        if err is not None:
            return err
        assistant_model = config.get('model') or config.get('model_id')
        if assistant_model:
            model = assistant_model
        assistant_system_prompt = (config.get('system_prompt') or '').strip()
        params = config.get('parameters') or {}
        for base in (params.get('base_images') or []):
            if not isinstance(base, dict):
                continue
            up_id = base.get('upload_id')
            if not up_id:
                continue
            up = UploadModel.find_by_id(up_id)
            if not up or str(up.get('user_id')) != user_id:
                continue
            data_uri = _upload_to_data_uri(up)
            if data_uri:
                assistant_base_images.append(data_uri)

    # ``model`` is required unless an image assistant supplied one.
    if not model:
        return JSONResponse({'error': 'Model is required'}, status_code=400)

    # --- Capability gating ---------------------------------------------------
    # Resolve the model's live capabilities (per-endpoint > roster > static
    # fallback; fail-open) and validate every provided optional param against it.
    # Provided-but-unsupported / out-of-enum / out-of-range -> 400 (legacy error
    # shape). Defense-in-depth clamps applied after the membership checks.
    caps = OpenRouterService.get_image_capabilities(model)

    def _unsupported(param: str):
        return JSONResponse(
            {'error': f'Model {model} does not support {param}'}, status_code=400
        )

    # Enum params: reject when provided + (unsupported OR not in the model's set).
    for _param, _val in (
        ('aspect_ratio', aspect_ratio),
        ('resolution', resolution),
        ('quality', quality),
        ('output_format', output_format),
        ('background', background),
    ):
        if _val is None:
            continue
        _cap = caps.get(_param) or {}
        if not _cap.get('supported'):
            return _unsupported(_param)
        if _val not in (_cap.get('values') or []):
            return JSONResponse(
                {'error': f'Invalid {_param}'}, status_code=400
            )

    # seed: boolean-supported integer.
    if seed is not None:
        if not (caps.get('seed') or {}).get('supported'):
            return _unsupported('seed')
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            return JSONResponse({'error': 'Invalid seed'}, status_code=400)

    # output_compression: 0-100 range, only on supporting models.
    if output_compression is not None:
        if not (caps.get('output_compression') or {}).get('supported'):
            return _unsupported('output_compression')
        try:
            output_compression = int(output_compression)
        except (TypeError, ValueError):
            return JSONResponse({'error': 'Invalid output_compression'}, status_code=400)
        output_compression = max(0, min(100, output_compression))

    # transparent background only on png/webp output (else 400, defense-in-depth).
    if background == 'transparent' and output_format not in {'png', 'webp'}:
        return JSONResponse(
            {'error': 'Transparent background requires png or webp output_format'},
            status_code=400,
        )

    # n: clamp to the model's max (and a hard 10 ceiling). Default 1.
    n_cap = caps.get('n') or {}
    n_max = min(int(n_cap.get('max', 1) or 1), 10)
    n = 1
    if n_requested is not None:
        try:
            n = int(n_requested)
        except (TypeError, ValueError):
            return JSONResponse({'error': 'Invalid n'}, status_code=400)
        n = max(1, min(n, n_max))

    # Parent (edit base) image — owner-verified; its payload is the edit base.
    parent_data_uri = None
    if parent_image_id:
        parent_img = GeneratedImageModel.find_by_id(parent_image_id)
        if not parent_img:
            return JSONResponse({'error': 'Parent image not found'}, status_code=404)
        if str(parent_img.get('user_id')) != user_id:
            return JSONResponse({'error': 'Unauthorized'}, status_code=403)
        parent_data_uri = parent_img.get('image_data') or parent_img.get('b64_payload')

    # Owner-verify an existing thread, else create one titled from the prompt.
    if conversation_id:
        thread = ImageConversationModel.find_by_id(conversation_id)
        if not thread or str(thread.get('user_id')) != user_id:
            return JSONResponse({'error': 'Thread not found'}, status_code=404)
        conversation_id = str(thread['_id'])
    else:
        thread_title = ' '.join(prompt.split()[:6]) or None
        thread = ImageConversationModel.create(
            user_id=user_id,
            title=thread_title,
            config_id=config_id or None,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        conversation_id = str(thread['_id'])

    # Final input-image list, capped to the model's limit. The parent (edit base)
    # is the SUBJECT of the edit — reserve its slot FIRST so switching to a
    # low-cap model (or an assistant contributing many base_images) can never
    # silently drop it and degrade the "edit" into a fresh generate. Remaining
    # slots fill by priority: assistant style/identity bases, then user refs.
    max_images = (caps.get('input_references') or {}).get('max', 0)
    combined_images: list[str] = []
    if parent_data_uri and max_images > 0:
        combined_images.append(parent_data_uri)
    for img in (*assistant_base_images, *input_images):
        if len(combined_images) >= max_images:
            break
        combined_images.append(img)

    # DLP gate — scan prompt (and negative prompt if present) before sending to
    # the provider. ``gate_redactable`` is a drop-in superset of ``gate``: in
    # enforce mode it block/confirm/warns unchanged (DLPBlockedError -> global
    # 403); in redact mode (workspace ``mode=redact`` OR client ``dlp_redact``)
    # it scrubs sensitive spans out of the prompt, which we then send to image
    # generation instead of the raw text.
    image_dlp_redact = bool(data.get('dlp_redact'))
    image_user_lang = (user_doc.get('ai_preferences') or {}).get('lang', 'en') if user_doc else 'en'
    scan_text = prompt if not negative_prompt else f"{prompt}\n\n[negative]\n{negative_prompt}"

    # DLP smart-scan can be a multi-second LLM round-trip — offload the blocking
    # call (and the conditional re-redact) to a worker thread so it never stalls
    # the event loop. ``anyio.to_thread.run_sync`` copies contextvars, so the
    # request-scoped ``db.session`` works in the worker (same as ``_spend``).
    # ``DLPBlockedError`` raised inside the gate propagates back out of the
    # closure and is handled GLOBALLY (403) — the route never catches it locally.
    def _dlp() -> dict:
        gate_res = dlp_gate.gate_redactable(
            text=scan_text,
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            source='image_prompt',
            source_ref={'feature': 'image', 'model': model},
            force_redact=image_dlp_redact,
            confirmed=dlp_confirmed,
            dlp_confirm_token=data.get('dlp_confirm_token'),
            user_lang=image_user_lang,
        )
        # When redaction fired, re-redact the bare prompt alone so its placeholders
        # are numbered independently of the appended negative-prompt scan text. The
        # negative prompt is part of the SAME scan (it was appended for the gate), so
        # it MUST be scrubbed too — otherwise the raw negative_prompt would be sent to
        # the provider AND persisted un-redacted while the dlp_event claims redaction.
        red_prompt = prompt
        red_negative = negative_prompt
        if gate_res.get('redacted'):
            from app.services.dlp_service import DLPDetector
            _detector = DLPDetector.from_workspace(str(workspace_id))
            red_prompt, _, _ = _detector.redact(red_prompt, user_lang=image_user_lang, user_id=user_id)
            if red_negative:
                red_negative, _, _ = _detector.redact(
                    red_negative, user_lang=image_user_lang, user_id=user_id
                )
        return {'prompt': red_prompt, 'negative_prompt': red_negative}

    _dlp_res = await anyio.to_thread.run_sync(_dlp)
    prompt = _dlp_res['prompt']
    negative_prompt = _dlp_res['negative_prompt']

    # Gate the image-assistant preamble under the GEN workspace too. The saved
    # ``system_prompt`` is prepended to ``gen_prompt`` below and shipped to the
    # provider, but it was DLP-scanned only once at authoring time — under
    # whatever workspace was then active (``_resolve_image_assistant`` authorizes
    # on owner_id alone, so a private assistant travels across workspaces). Left
    # ungated here, a preamble carrying a banned codename — authored under a
    # DLP-off personal workspace — would evade a strict company's block-tier rule
    # at gen time. We scan the preamble VERBATIM (exactly the bytes prepended) in
    # ENFORCE posture: it's fixed server-side content the user cannot see, edit,
    # or "send anyway", so block/require_confirm both hard-block the generation
    # (no client confirm token applies). This is a SEPARATE gate from the user
    # prompt above so the user-prompt ``scan_text``/confirm-token sha stays
    # byte-for-byte identical (the client mints its token over the user text only
    # — folding the preamble into that scan would break the "Send anyway" replay).
    if assistant_system_prompt:
        def _dlp_preamble() -> None:
            dlp_gate.gate(
                text=assistant_system_prompt,
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                source='image_prompt',
                source_ref={'feature': 'image', 'model': model, 'preamble': True},
                confirmed=False,
                user_lang=image_user_lang,
            )

        await anyio.to_thread.run_sync(_dlp_preamble)

    # Spend gate — pre-flight budget/credit enforcement (same scope the route
    # resolved for DLP/usage). Offloaded to a worker thread: the blocking DB
    # point-reads must not stall the event loop in this async handler. A breach
    # raises BudgetExceededError -> global 402 BEFORE the provider call.
    def _spend() -> None:
        spend_gate.gate(
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            origin='web',
            feature='image',
        )

    await anyio.to_thread.run_sync(_spend)

    # Build the prompt actually sent to the provider: prepend the image
    # assistant's system_prompt as a style preamble. The preamble was gated under
    # the gen workspace just above (separate enforce-mode pass); the user's
    # prompt/negative was gated + possibly redacted by ``_dlp`` before that.
    gen_prompt = (
        f"{assistant_system_prompt}\n\n{prompt}" if assistant_system_prompt else prompt
    )

    # Provider round-trip is multi-second-to-minute of blocking I/O — offload it
    # so the async event loop isn't pinned for the whole generation.
    def _generate() -> dict:
        return OpenRouterService.generate_image(
            prompt=gen_prompt,
            model=model,
            negative_prompt=negative_prompt,
            input_images=combined_images if combined_images else None,
            aspect_ratio=aspect_ratio,
            n=n,
            resolution=resolution,
            seed=seed,
            quality=quality,
            output_format=output_format,
            background=background,
            output_compression=output_compression,
            user_id=user_id,
            conversation_id=None,
            feature='image',
            workspace_id=workspace_id,
            project_id=project_id,
            origin='web',
        )

    result = await anyio.to_thread.run_sync(_generate)

    generation_time = int((time.time() - start_time) * 1000)

    if not result.get('success'):
        body = {'error': result.get('error', 'Generation failed')}
        if result.get('code'):
            body['code'] = result['code']
        return JSONResponse(body, status_code=500)

    # One generation turn can yield N images (capability-gated batch). Persist
    # ONE GeneratedImage row per returned image, all tagged with a shared
    # ``batch_id`` so the FE can group them. The Image API books a SINGLE usage
    # block for the whole batch (one ``_record_usage`` call inside generate_image),
    # so divide the authoritative total cost/tokens evenly across the rows for the
    # per-image figure while preserving the batch total in metadata.
    images = result.get('images') or []
    actual_n = len(images)
    batch_id = str(_uuid.uuid4())
    total_cost = result.get('cost_usd_total')
    total_tokens = result.get('tokens_total')
    per_cost = (total_cost / actual_n) if (total_cost is not None and actual_n) else None
    per_tokens = (total_tokens / actual_n) if (total_tokens is not None and actual_n) else None

    common_settings = {
        'input_images_count': len(combined_images),
        'has_input_images': bool(combined_images),
        'batch_id': batch_id,
        'batch_n': actual_n,
        **({'aspect_ratio': aspect_ratio} if aspect_ratio else {}),
        **({'resolution': resolution} if resolution else {}),
        **({'seed': seed} if seed is not None else {}),
        **({'output_format': output_format} if output_format else {}),
        **({'background': background} if background else {}),
        **({'config_id': config_id} if config_id else {}),
    }

    created_rows = []
    for i, img_data in enumerate(images):
        row = GeneratedImageModel.create(
            user_id=user_id,
            prompt=prompt,
            model_id=model,
            image_data=img_data,
            negative_prompt=negative_prompt,
            conversation_id=conversation_id,
            parent_image_id=parent_image_id,
            settings={**common_settings, 'batch_index': i},
            metadata={
                'generation_time_ms': generation_time,
                'usage': result.get('usage', {}),
                # Per-image price + tokens (batch total split evenly). Surfaced to
                # the UI via _image_to_dict; null on providers/rows that report no
                # usage (old images render an em-dash).
                'cost_usd': per_cost,
                'tokens': {'total': per_tokens, 'image': None},
                'batch': {
                    'batch_id': batch_id,
                    'n': actual_n,
                    'total_cost_usd': total_cost,
                    'total_tokens': total_tokens,
                },
            },
        )
        created_rows.append(row)

    ImageConversationModel.touch(conversation_id)

    first = created_rows[0]
    return JSONResponse({
        'images': [mask_image_money(serialize_doc(r), user) for r in created_rows],
        'batch_id': batch_id,
        'conversation_id': str(conversation_id),
        # Back-compat: single-image callers read ``image``/``image_data``.
        'image': mask_image_money(serialize_doc(first), user),
        'image_data': first.get('image_data') or images[0],
    }, status_code=200)


@image_router.get("/history")
def get_history(
    page: int = 1,
    limit: int = 20,
    favorites: str = 'false',
    include_payload: str = 'false',
    search: str = '',
    user: dict = Depends(current_user),
):
    """Get the user's image generation history.

    ``include_payload`` (default ``'false'``) controls whether each row carries
    the heavy base64 ``image_data``. The grids never want the full payload in a
    list — they render the small ``thumb`` and lazy-fetch each image's payload
    by id, so a page isn't tens of MB of JSON. A caller that genuinely needs the
    payload inline must opt in explicitly with ``include_payload=true``.
    """
    user_id = str(user['_id'])
    favorites_only = favorites.lower() == 'true'
    want_payload = include_payload.lower() == 'true'

    skip = (page - 1) * limit
    images = GeneratedImageModel.find_by_user(
        user_id, skip=skip, limit=limit, favorites_only=favorites_only,
        include_payload=want_payload, search=search or None,
    )
    total = GeneratedImageModel.count_by_user(
        user_id, favorites_only=favorites_only, search=search or None
    )

    return JSONResponse({
        'images': [mask_image_money(serialize_doc(img), user) for img in images],
        'total': total,
        'page': page,
        'pages': (total + limit - 1) // limit,
    }, status_code=200)


# ---------------------------------------------------------------------------
# Image edit threads. DECLARED BEFORE the dynamic ``/{image_id}`` routes so the
# static ``/threads`` prefix is matched first (Starlette matches in declaration
# order). All owner-scoped: 404 when missing, 404 (not 403) when not the owner
# of a thread — mirrors the ``/{image_id}`` ownership pattern.
# ---------------------------------------------------------------------------
@image_router.get("/threads")
def list_threads(
    page: int = 1,
    limit: int = 20,
    user: dict = Depends(current_user),
):
    """List the caller's image-edit threads (newest activity first)."""
    user_id = str(user['_id'])
    skip = (page - 1) * limit
    threads = ImageConversationModel.find_by_user(user_id, skip=skip, limit=limit)
    total = ImageConversationModel.count_by_user(user_id)
    return JSONResponse({
        'threads': [serialize_doc(t) for t in threads],
        'total': total,
        'page': page,
        'pages': (total + limit - 1) // limit,
    }, status_code=200)


@image_router.get("/threads/{cid}")
def get_thread(cid: str, user: dict = Depends(current_user)):
    """Return one thread + its ordered images (thumbs only; no full base64)."""
    user_id = str(user['_id'])
    conv = ImageConversationModel.find_by_id(cid)
    if not conv:
        return JSONResponse({'error': 'Thread not found'}, status_code=404)
    if str(conv.get('user_id')) != user_id:
        return JSONResponse({'error': 'Thread not found'}, status_code=404)

    images = GeneratedImageModel.find_by_conversation(cid, user_id, include_payload=False)
    return JSONResponse({
        'conversation': serialize_doc(conv),
        'images': [mask_image_money(serialize_doc(img), user) for img in images],
    }, status_code=200)


@image_router.patch("/threads/{cid}")
async def rename_thread(cid: str, request: Request, user: dict = Depends(current_user)):
    """Rename a thread (owner-only)."""
    user_id = str(user['_id'])
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        data = {}
    data = data if isinstance(data, dict) else {}

    conv = ImageConversationModel.find_by_id(cid)
    if not conv:
        return JSONResponse({'error': 'Thread not found'}, status_code=404)
    if str(conv.get('user_id')) != user_id:
        return JSONResponse({'error': 'Thread not found'}, status_code=404)

    title = (data.get('title') or '').strip() or None
    updated = ImageConversationModel.rename(cid, user_id, title)
    if updated is None:
        return JSONResponse({'error': 'Thread not found'}, status_code=404)
    return JSONResponse({'conversation': serialize_doc(updated)}, status_code=200)


@image_router.delete("/threads/{cid}")
def delete_thread(cid: str, user: dict = Depends(current_user)):
    """Delete a thread AND its images (owner-only)."""
    user_id = str(user['_id'])
    deleted = ImageConversationModel.delete(cid, user_id)
    if not deleted:
        return JSONResponse({'error': 'Thread not found'}, status_code=404)
    return JSONResponse({'message': 'Thread deleted'}, status_code=200)


@image_router.get("/{image_id}/file")
def get_image_file(image_id: str, user: dict = Depends(current_user)):
    """Serve raw image bytes for ``<img src>`` / open-in-tab — owner-only.

    JSON detail at ``GET /{id}`` stays for Studio clients. Agent markdown and
    artifact links use this path so the browser gets ``image/*`` not a base64
    JSON envelope (which previously caused load-failed + base64-in-new-tab).
    """
    user_id = str(user['_id'])

    image = GeneratedImageModel.find_by_id(image_id)
    if not image:
        return JSONResponse({'error': 'Image not found'}, status_code=404)

    if str(image['user_id']) != user_id:
        return JSONResponse({'error': 'Unauthorized'}, status_code=403)

    full = image.get('image_data') or image.get('b64_payload')
    raw, mime = decode_image_payload(full)
    if not raw:
        return JSONResponse({'error': 'Image payload missing'}, status_code=404)

    return Response(
        content=raw,
        media_type=mime,
        headers={
            'Cache-Control': 'private, max-age=86400',
            'Content-Disposition': f'inline; filename="image-{image_id[:8]}"',
        },
    )


@image_router.get("/{image_id}")
def get_image(image_id: str, user: dict = Depends(current_user)):
    """Return a single image WITH its full base64 payload — owner-only.

    Declared AFTER ``/history`` so the static path isn't swallowed by this
    dynamic id param (Starlette matches in declaration order).
    """
    user_id = str(user['_id'])

    image = GeneratedImageModel.find_by_id(image_id)
    if not image:
        return JSONResponse({'error': 'Image not found'}, status_code=404)

    if str(image['user_id']) != user_id:
        return JSONResponse({'error': 'Unauthorized'}, status_code=403)

    return JSONResponse({
        'image': mask_image_money(serialize_doc(image), user),
    }, status_code=200)


@image_router.get("/{image_id}/preview")
def get_image_preview(image_id: str, user: dict = Depends(current_user)):
    """Medium (~1024px) WebP preview of an image — owner-only.

    The studio canvas renders THIS rather than the multi-MB full base64 (keeps
    the page light) and rather than the 256px list thumb (too small → blurry).
    Generated on demand from the full payload via the shared thumb helper; the
    rendition is immutable per image, so it's cacheable.
    """
    user_id = str(user['_id'])

    image = GeneratedImageModel.find_by_id(image_id)
    if not image:
        return JSONResponse({'error': 'Image not found'}, status_code=404)
    if str(image['user_id']) != user_id:
        return JSONResponse({'error': 'Unauthorized'}, status_code=403)

    from app.models.generated_image import _make_thumb_data_uri
    full = image.get('image_data') or image.get('b64_payload')
    preview = _make_thumb_data_uri(full, max_px=1024, quality=80) if full else None
    # Fall back to the small thumb so the canvas still shows something.
    if not preview:
        preview = image.get('thumb')
    return JSONResponse(
        {'preview': preview},
        status_code=200,
        headers={'Cache-Control': 'private, max-age=86400'},
    )


@image_router.delete("/{image_id}")
def delete_image(image_id: str, user: dict = Depends(current_user)):
    """Delete an image."""
    user_id = str(user['_id'])

    image = GeneratedImageModel.find_by_id(image_id)
    if not image:
        return JSONResponse({'error': 'Image not found'}, status_code=404)

    if str(image['user_id']) != user_id:
        return JSONResponse({'error': 'Unauthorized'}, status_code=403)

    GeneratedImageModel.delete(image_id)
    return JSONResponse({'message': 'Image deleted'}, status_code=200)


@image_router.post("/bulk-delete")
async def bulk_delete_images(request: Request, user: dict = Depends(current_user)):
    """Delete multiple images at once."""
    user_id = str(user['_id'])
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        data = {}
    data = data if isinstance(data, dict) else {}

    image_ids = data.get('image_ids', [])
    if not image_ids:
        return JSONResponse({'error': 'No images specified'}, status_code=400)

    if len(image_ids) > 50:
        return JSONResponse({'error': 'Maximum 50 images per request'}, status_code=400)

    for img_id in image_ids:
        if not is_valid_id(img_id):
            return JSONResponse({'error': f'Invalid image ID: {img_id}'}, status_code=400)

    deleted_count = GeneratedImageModel.delete_many(image_ids, user_id)
    return JSONResponse({
        'message': f'Deleted {deleted_count} images',
        'deleted_count': deleted_count,
    }, status_code=200)


@image_router.post("/{image_id}/favorite")
def toggle_favorite(image_id: str, user: dict = Depends(current_user)):
    """Toggle favorite status."""
    user_id = str(user['_id'])

    image = GeneratedImageModel.find_by_id(image_id)
    if not image:
        return JSONResponse({'error': 'Image not found'}, status_code=404)

    if str(image['user_id']) != user_id:
        return JSONResponse({'error': 'Unauthorized'}, status_code=403)

    new_status = GeneratedImageModel.toggle_favorite(image_id)
    return JSONResponse({'is_favorite': new_status}, status_code=200)




__all__ = ["image_router"]
