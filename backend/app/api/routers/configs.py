"""LLM-config + prompt-template routes, translated from app/routes/configs.py
and app/routes/prompt_templates.py.

Two Flask blueprints -> two FastAPI routers (one per url_prefix):
  * ``router``                 -> mounted at ``/api/configs``           (configs_bp)
  * ``prompt_templates_router`` -> mounted at ``/api/prompt-templates`` (prompt_templates_bp)

Both carry ``Depends(flask_ctx)`` so every request runs inside one Flask
app_context — the legacy model facades + OpenRouterService are reused verbatim.

The Flask ``configs.py`` validated ``project_id`` with ``bson.ObjectId(...)``;
the canonical PK is now a UUID, so we validate with ``uuid.UUID(str(...))``
instead (no bson). Response shapes (``serialize_doc`` -> legacy ``_id`` alias)
are preserved byte-for-byte.
"""
from __future__ import annotations

import logging
import uuid
from functools import partial

import anyio.to_thread

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import current_user, flask_ctx, require_active, require_admin
from app.models.llm_config import LLMConfigModel
from app.models.project import ProjectModel
from app.models.prompt_template import PromptTemplateModel
from app.models.upload import UploadModel
from app.services import spend_gate
from app.services.dlp_gate import gate_redactable
from app.services.openrouter_service import OpenRouterService
from app.utils.helpers import serialize_doc
from app.utils.permissions import check_project_access
from app.utils.validators import (
    validate_config_name,
    validate_system_prompt,
)

logger = logging.getLogger(__name__)

ALLOWED_VISIBILITIES = {"private", "public", "template", "project"}

_ARABIC_START, _ARABIC_END = 0x0600, 0x06FF


def _has_arabic_script(text: str) -> bool:
    return any(_ARABIC_START <= ord(c) <= _ARABIC_END for c in text or "")


# Router-level dependency: every request runs inside the Flask app_context.
router = APIRouter(dependencies=[Depends(flask_ctx)])
prompt_templates_router = APIRouter(dependencies=[Depends(flask_ctx)])


async def _json_body(request: Request) -> dict:
    """Read JSON body, tolerating empty/garbage like ``get_json(silent=True)``."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _valid_uuid(value: str) -> bool:
    """Replacement for the legacy ``bson.ObjectId(...)`` validity probe."""
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _gate_assistant_prompt(
    *,
    text: str,
    user: dict,
    workspace_id,
    project_id,
    data: dict,
) -> str:
    """Run the DLP chokepoint over a custom-assistant persona prompt.

    Mirrors the chat gate: a block raises ``DLPBlockedError`` (the
    global handler turns it into a 403). Confirmation does not unlock the send.
    In redact mode the scrubbed text is returned to persist instead of the raw
    value. Synchronous — call sites offload
    via ``anyio.to_thread.run_sync`` because ``gate_redactable`` does blocking work
    (DB read + smart-scan LLM round-trip).
    """
    gate_res = gate_redactable(
        text=text,
        user_id=user["_id"],
        workspace_id=workspace_id,
        project_id=project_id,
        source="assistant",
        source_ref={},
        force_redact=bool(data.get("dlp_redact")),
        confirmed=bool(data.get("dlp_confirmed")),
        dlp_confirm_token=data.get("dlp_confirm_token"),
    )
    if gate_res.get("redacted"):
        return gate_res.get("redacted_text", text)
    return text


# Max ``base_images`` an image assistant may persist; whitelisted keys kept per
# entry (everything else is dropped).
_MAX_BASE_IMAGES = 16
_BASE_IMAGE_KEYS = ("upload_id", "url", "thumb_url", "name")


def _validate_image_parameters(parameters: dict, user_id: str):
    """Light validation/sanitization for an image-assistant ``parameters`` blob.

    Only applies when ``parameters.kind == 'image'``. Returns
    ``(sanitized_parameters, error)`` where ``error`` is a ``JSONResponse`` to
    return on a bad ``kind``, else ``None``. ``base_images`` is coerced to a list
    of ``{upload_id, url, thumb_url, name}`` objects, capped at
    ``_MAX_BASE_IMAGES``, dropping entries whose upload isn't owned by the caller.
    The model id is passed through untouched (image-model ids drift; not gated
    server-side).
    """
    if not isinstance(parameters, dict):
        return parameters, None

    kind = parameters.get("kind")
    if kind is None:
        return parameters, None
    if kind not in ("text", "image"):
        return None, JSONResponse({"error": "Invalid parameters.kind"}, status_code=400)
    if kind != "image":
        return parameters, None

    sanitized = dict(parameters)
    raw_base = parameters.get("base_images")
    if raw_base is not None:
        clean: list[dict] = []
        if isinstance(raw_base, list):
            for entry in raw_base:
                if len(clean) >= _MAX_BASE_IMAGES:
                    break
                if not isinstance(entry, dict):
                    continue
                upload_id = entry.get("upload_id")
                if not isinstance(upload_id, str) or not upload_id:
                    continue
                upload = UploadModel.find_by_id(upload_id)
                if not upload or str(upload.get("user_id")) != user_id:
                    continue
                clean.append({k: entry[k] for k in _BASE_IMAGE_KEYS if k in entry})
        sanitized["base_images"] = clean
    return sanitized, None


# ===========================================================================
# /api/configs  (configs_bp)
# ===========================================================================
@router.get("")
def get_configs(
    request: Request,
    user: dict = Depends(require_active),
    page: int = 1,
    limit: int = 50,
    project_id: str | None = None,
):
    """Get LLM configurations.

    Without ``project_id``: caller's owned configs (legacy behavior).
    With ``?project_id=<pid>``: configs visible inside that project — caller's
    private + project-scoped + public + templates. Requires viewer role.
    """
    user_id = str(user["_id"])

    skip = (page - 1) * limit

    if project_id:
        if not _valid_uuid(project_id):
            return JSONResponse({"error": "Invalid project_id"}, status_code=400)

        if not check_project_access(user_id, project_id, "viewer"):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        configs = LLMConfigModel.find_visible_to(
            user_id, project_id=project_id, skip=skip, limit=limit
        )
        return {
            "configs": serialize_doc(configs),
            "total": len(configs),
            "page": page,
            "limit": limit,
        }

    configs = LLMConfigModel.find_by_owner(user_id, skip=skip, limit=limit)
    total = LLMConfigModel.count_by_owner(user_id)

    return {
        "configs": serialize_doc(configs),
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/{config_id}")
def get_config(config_id: str, user: dict = Depends(require_active)):
    """Get a specific configuration."""
    user_id = str(user["_id"])

    config = LLMConfigModel.find_by_id(config_id)
    if not config:
        return JSONResponse({"error": "Config not found"}, status_code=404)

    if str(config.get("owner_id")) != user_id:
        visibility = config.get("visibility")
        if visibility == "private":
            return JSONResponse({"error": "Config not found"}, status_code=404)
        if visibility == "project":
            cfg_pid = config.get("project_id")
            if not cfg_pid or not check_project_access(user_id, str(cfg_pid), "viewer"):
                return JSONResponse({"error": "Config not found"}, status_code=404)

    return {"config": serialize_doc(config)}


@router.post("")
async def create_config(request: Request, user: dict = Depends(require_active)):
    """Create a new LLM configuration.

    Optional body fields ``project_id`` / ``workspace_id`` scope the config to a
    project. When ``project_id`` is set we require editor role and auto-derive
    workspace_id from the project (any client-supplied workspace_id is ignored
    in that case). Visibility defaults to 'project' when project_id is present.
    """
    user_id = str(user["_id"])
    data = await _json_body(request)

    name = (data.get("name") or "").strip()
    model_id = data.get("model_id")
    model_name = data.get("model_name", model_id)

    # Validate
    is_valid, error = validate_config_name(name)
    if not is_valid:
        return JSONResponse({"error": error}, status_code=400)

    if not model_id:
        return JSONResponse({"error": "model_id is required"}, status_code=400)

    system_prompt = data.get("system_prompt", "")
    is_valid, error = validate_system_prompt(system_prompt)
    if not is_valid:
        return JSONResponse({"error": error}, status_code=400)

    project_id = data.get("project_id")
    workspace_id = data.get("workspace_id")

    if project_id:
        if not _valid_uuid(project_id):
            return JSONResponse({"error": "Invalid project_id"}, status_code=400)

        if not check_project_access(user_id, project_id, "editor"):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        project = ProjectModel.find_by_id(project_id)
        if not project:
            return JSONResponse({"error": "Project not found"}, status_code=404)
        # Authoritative workspace_id from project — ignore any client value.
        workspace_id = project["workspace_id"]

    visibility = data.get("visibility")
    if visibility is None:
        visibility = "project" if project_id else "private"
    elif visibility not in ALLOWED_VISIBILITIES:
        return JSONResponse({"error": "Invalid visibility"}, status_code=400)

    # DLP gate the persona system prompt before persisting. Resolve attribution
    # ws: project's workspace (set above when project_id present) → user's active
    # workspace. A block raises DLPBlockedError → global 403; redact mode
    # returns the scrubbed prompt to store.
    if system_prompt:
        gate_ws_id = workspace_id or user.get("active_workspace_id")
        system_prompt = await anyio.to_thread.run_sync(
            partial(
                _gate_assistant_prompt,
                text=system_prompt,
                user=user,
                workspace_id=gate_ws_id,
                project_id=project_id,
                data=data,
            )
        )

    parameters = data.get("parameters")
    if isinstance(parameters, dict):
        parameters, params_err = _validate_image_parameters(parameters, user_id)
        if params_err is not None:
            return params_err

    config = LLMConfigModel.create(
        name=name,
        model_id=model_id,
        model_name=model_name,
        owner_id=user_id,
        description=data.get("description", ""),
        system_prompt=system_prompt,
        visibility=visibility,
        avatar=data.get("avatar"),
        parameters=parameters,
        tags=data.get("tags", []),
        project_id=project_id,
        workspace_id=workspace_id,
    )

    return JSONResponse({"config": serialize_doc(config)}, status_code=201)


@router.put("/{config_id}")
async def update_config(config_id: str, request: Request, user: dict = Depends(require_active)):
    """Update a configuration."""
    user_id = str(user["_id"])

    config = LLMConfigModel.find_by_id(config_id)
    if not config or str(config.get("owner_id")) != user_id:
        return JSONResponse({"error": "Config not found"}, status_code=404)

    data = await _json_body(request)

    # Reassigning project_id post-creation is intentionally not supported —
    # it crosses permission/workspace boundaries. Caller should duplicate.
    if "project_id" in data:
        existing_pid = config.get("project_id")
        existing_pid_str = str(existing_pid) if existing_pid else None
        new_pid = data["project_id"]
        new_pid_str = str(new_pid) if new_pid else None
        if existing_pid_str != new_pid_str:
            return JSONResponse({"error": "cannot_reassign_project"}, status_code=400)

    update_fields: dict = {}

    if "name" in data:
        is_valid, error = validate_config_name(data["name"])
        if not is_valid:
            return JSONResponse({"error": error}, status_code=400)
        update_fields["name"] = data["name"].strip()

    if "description" in data:
        update_fields["description"] = data["description"]

    if "system_prompt" in data:
        is_valid, error = validate_system_prompt(data["system_prompt"])
        if not is_valid:
            return JSONResponse({"error": error}, status_code=400)
        new_prompt = data["system_prompt"]
        if new_prompt:
            # Attribution ws: config's existing workspace → user's active.
            upd_ws_id = config.get("workspace_id") or user.get("active_workspace_id")
            new_prompt = await anyio.to_thread.run_sync(
                partial(
                    _gate_assistant_prompt,
                    text=new_prompt,
                    user=user,
                    workspace_id=upd_ws_id,
                    project_id=config.get("project_id"),
                    data=data,
                )
            )
        update_fields["system_prompt"] = new_prompt

    if "model_id" in data:
        update_fields["model_id"] = data["model_id"]
        update_fields["model_name"] = data.get("model_name", data["model_id"])

    if "avatar" in data:
        update_fields["avatar"] = data["avatar"]

    if "parameters" in data:
        new_params = data["parameters"]
        if isinstance(new_params, dict):
            new_params, params_err = _validate_image_parameters(new_params, user_id)
            if params_err is not None:
                return params_err
        update_fields["parameters"] = new_params

    if "tags" in data:
        update_fields["tags"] = data["tags"]

    if "visibility" in data:
        if data["visibility"] not in ALLOWED_VISIBILITIES:
            return JSONResponse({"error": "Invalid visibility"}, status_code=400)
        update_fields["visibility"] = data["visibility"]

    if update_fields:
        LLMConfigModel.update(config_id, update_fields)

    updated = LLMConfigModel.find_by_id(config_id)
    return {"config": serialize_doc(updated)}


@router.delete("/{config_id}")
def delete_config(config_id: str, user: dict = Depends(require_active)):
    """Delete a configuration."""
    user_id = str(user["_id"])

    config = LLMConfigModel.find_by_id(config_id)
    if not config or str(config.get("owner_id")) != user_id:
        return JSONResponse({"error": "Config not found"}, status_code=404)

    LLMConfigModel.delete(config_id)

    return {"message": "Config deleted"}


@router.post("/{config_id}/publish")
def publish_config(config_id: str, user: dict = Depends(require_active)):
    """Make a configuration public."""
    user_id = str(user["_id"])

    config = LLMConfigModel.find_by_id(config_id)
    if not config or str(config.get("owner_id")) != user_id:
        return JSONResponse({"error": "Config not found"}, status_code=404)

    LLMConfigModel.set_visibility(config_id, "public")

    return {"message": "Config published", "visibility": "public"}


@router.post("/{config_id}/unpublish")
def unpublish_config(config_id: str, user: dict = Depends(require_active)):
    """Make a configuration private."""
    user_id = str(user["_id"])

    config = LLMConfigModel.find_by_id(config_id)
    if not config or str(config.get("owner_id")) != user_id:
        return JSONResponse({"error": "Config not found"}, status_code=404)

    LLMConfigModel.set_visibility(config_id, "private")

    return {"message": "Config unpublished", "visibility": "private"}


@router.post("/{config_id}/duplicate")
async def duplicate_config(config_id: str, request: Request, user: dict = Depends(require_active)):
    """Duplicate a configuration."""
    user_id = str(user["_id"])
    data = await _json_body(request)

    config = LLMConfigModel.find_by_id(config_id)
    if not config:
        return JSONResponse({"error": "Config not found"}, status_code=404)

    if str(config.get("owner_id")) != user_id:
        visibility = config.get("visibility")
        if visibility == "private":
            return JSONResponse({"error": "Config not found"}, status_code=404)
        if visibility == "project":
            cfg_pid = config.get("project_id")
            if not cfg_pid or not check_project_access(user_id, str(cfg_pid), "viewer"):
                return JSONResponse({"error": "Config not found"}, status_code=404)

    new_name = data.get("name")
    new_config = LLMConfigModel.duplicate(config_id, user_id, new_name)

    return JSONResponse({"config": serialize_doc(new_config)}, status_code=201)


@router.post("/enhance-prompt")
async def enhance_prompt(request: Request, user: dict = Depends(require_active)):
    """Enhance a system prompt using LLM."""
    user_id = str(user["_id"])
    data = await _json_body(request)
    prompt = (data.get("prompt") or "").strip()
    # 'assistant' (default) = persona system prompt; 'image' = image-gen prompt.
    mode = (data.get("mode") or "assistant").strip().lower()
    if mode not in ("assistant", "image"):
        mode = "assistant"

    if not prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    if len(prompt) > 10000:
        return JSONResponse(
            {"error": "Prompt too long (max 10000 characters)"}, status_code=400
        )

    # Resolve attribution from request body if provided, else user's active workspace.
    body_ws = data.get("workspace_id")
    body_proj = data.get("project_id")
    enh_ws_id = body_ws or user.get("active_workspace_id")
    enh_proj_id = body_proj

    # DLP gate the user's prompt BEFORE building/sending the enhancement request.
    # A block raises DLPBlockedError → global 403; redaction (if active)
    # scrubs the prompt actually forwarded to the model. Offloaded like the
    # completion below. Gating before the f-string ensures the scrubbed value is
    # what gets embedded.
    if enh_ws_id:
        prompt = await anyio.to_thread.run_sync(
            partial(
                _gate_assistant_prompt,
                text=prompt,
                user=user,
                workspace_id=enh_ws_id,
                project_id=enh_proj_id,
                data=data,
            )
        )

    # Spend gate (pre-flight budget/credit enforcement). Mirrors the DLP gate
    # above: runs AFTER it, BEFORE the billable completion, so a breach is a
    # clean HTTP 402 (BudgetExceededError -> global handler). Offloaded — a few
    # indexed point-reads. ``config_suggest`` is NOT an exempt feature, so an
    # exhausted budget correctly blocks the ✨Enhance round-trip.
    def _spend_gate() -> None:
        spend_gate.gate(
            user_id=user_id,
            workspace_id=str(enh_ws_id) if enh_ws_id else None,
            project_id=str(enh_proj_id) if enh_proj_id else None,
            origin="web",
            feature="config_suggest",
        )

    await anyio.to_thread.run_sync(_spend_gate)

    if mode == "image":
        system_prompt = (
            "You improve image-generation prompts.\n"
            "Rules:\n"
            "- Keep the user's subject, entities, and details. Never replace them "
            "with an unrelated demo scene (cars, stock landscapes, sample products).\n"
            "- Write in the SAME language as the user. Persian stays Persian; "
            "English stays English. Do not translate.\n"
            "- Add useful visual detail (composition, lighting, materials, mood) "
            "without changing who or what is depicted.\n"
            "- Compact descriptors are fine. No commentary, headings, or quotes.\n"
            "- Return ONLY the improved prompt."
        )
        user_content = prompt
        enhance_temp = 0.2
    else:
        system_prompt = None
        user_content = f"""You are an expert prompt engineer. Improve this system prompt to be clearer, more specific, and more effective.

Key improvements to make:
- Add clear role definition if missing
- Add specific behavioral guidelines
- Add output format instructions if relevant
- Make instructions explicit and unambiguous
- Keep the original intent intact

Original prompt:
{prompt}

Return ONLY the improved prompt, no explanations or extra text."""
        enhance_temp = 0.7

    # Offload the blocking, non-streaming LLM round-trip (+ sync usage write) to a
    # worker thread — calling it directly in this async handler would park the
    # event loop for the full OpenRouter round-trip (up to the 120s timeout).
    response = await anyio.to_thread.run_sync(
        partial(
            OpenRouterService.chat_completion,
            messages=[{"role": "user", "content": user_content}],
            system_prompt=system_prompt,
            model="google/gemini-3.5-flash-lite",
            max_tokens=1024,
            temperature=enhance_temp,
            stream=False,
            user_id=user_id,
            conversation_id=None,
            feature="config_suggest",
            workspace_id=str(enh_ws_id) if enh_ws_id else None,
            project_id=str(enh_proj_id) if enh_proj_id else None,
            origin="web",
        )
    )

    if "error" in response:
        return JSONResponse(
            {"error": response["error"].get("message", "Enhancement failed")},
            status_code=500,
        )

    try:
        enhanced = response["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        return JSONResponse({"error": "Invalid response from LLM"}, status_code=500)

    if not enhanced:
        return JSONResponse({"error": "Enhancement failed"}, status_code=500)
    if mode == "image" and _has_arabic_script(prompt) and not _has_arabic_script(enhanced):
        # Model dropped Persian / swapped in an English demo scene (e.g. a red car).
        return JSONResponse({"error": "Enhancement failed"}, status_code=500)
    return {"enhanced_prompt": enhanced}


# ===========================================================================
# /api/prompt-templates  (prompt_templates_bp)
# ===========================================================================
@prompt_templates_router.get("/list")
def get_templates(user: dict = Depends(current_user), category: str | None = None):
    """Get all active prompt templates."""
    if category:
        templates = PromptTemplateModel.find_by_category(category)
    else:
        templates = PromptTemplateModel.find_all_active()

    return {"templates": [serialize_doc(t) for t in templates]}


@prompt_templates_router.get("/categories")
def get_categories(user: dict = Depends(current_user)):
    """Get list of all template categories."""
    categories = PromptTemplateModel.get_categories()
    return {"categories": categories}


@prompt_templates_router.post("/{template_id}/use")
def use_template(template_id: str, user: dict = Depends(current_user)):
    """Increment usage count when template is used."""
    template = PromptTemplateModel.find_by_id(template_id)
    if not template:
        return JSONResponse({"error": "Template not found"}, status_code=404)

    PromptTemplateModel.increment_usage(template_id)
    return {"message": "Usage recorded"}


@prompt_templates_router.post("/create")
async def create_template(request: Request, user: dict = Depends(require_admin)):
    """Create a new prompt template (admin only)."""
    user_id = str(user["_id"])
    data = await _json_body(request)

    name = (data.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "Name is required"}, status_code=400)

    category = (data.get("category") or "").strip()
    if not category:
        return JSONResponse({"error": "Category is required"}, status_code=400)

    template_text = (data.get("template_text") or "").strip()
    if not template_text:
        return JSONResponse({"error": "Template text is required"}, status_code=400)

    variables = data.get("variables", [])
    description = data.get("description", "")

    template = PromptTemplateModel.create(
        name=name,
        category=category,
        template_text=template_text,
        variables=variables,
        description=description,
        created_by=user_id,
    )

    return JSONResponse(
        {"message": "Template created", "template": serialize_doc(template)},
        status_code=201,
    )


@prompt_templates_router.put("/{template_id}")
async def update_template(template_id: str, request: Request, user: dict = Depends(require_admin)):
    """Update a prompt template (admin only)."""
    template = PromptTemplateModel.find_by_id(template_id)
    if not template:
        return JSONResponse({"error": "Template not found"}, status_code=404)

    data = await _json_body(request)
    updates: dict = {}

    if "name" in data:
        updates["name"] = data["name"].strip()
    if "category" in data:
        updates["category"] = data["category"].strip()
    if "template_text" in data:
        updates["template_text"] = data["template_text"].strip()
    if "variables" in data:
        updates["variables"] = data["variables"]
    if "description" in data:
        updates["description"] = data["description"]
    if "is_active" in data:
        updates["is_active"] = data["is_active"]

    PromptTemplateModel.update(template_id, updates)

    return {"message": "Template updated"}


@prompt_templates_router.delete("/{template_id}")
def delete_template(template_id: str, user: dict = Depends(require_admin)):
    """Delete a prompt template (admin only)."""
    template = PromptTemplateModel.find_by_id(template_id)
    if not template:
        return JSONResponse({"error": "Template not found"}, status_code=404)

    PromptTemplateModel.delete(template_id)

    return {"message": "Template deleted"}


__all__ = ["router", "prompt_templates_router"]
