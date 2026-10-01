"""Workflow routes, translated from app/routes/workflow.py and
app/routes/workflow_ai.py.

Two routers mirror the two Flask blueprints / url_prefixes:
  * ``router``             -> ``/api/workflow``     (workflow_bp)
  * ``workflow_ai_router`` -> ``/api/workflow-ai``  (workflow_ai_bp)

Each carries the router-level ``Depends(flask_ctx)`` so every request runs
inside ONE Flask app_context — the existing ``WorkflowModel`` / ``WorkflowRunModel``
facades + ``WorkflowService`` (with its thread fan-out) are reused VERBATIM.

WorkflowService.execute_* spawn/join threads internally and capture their own
app_context — the service layer is untouched; the route only needs the
request-bound app_context (the bridge) for the synchronous bookkeeping it does
before returning.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading

import anyio
import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import current_user, flask_ctx
from app.extensions import db
from app.models.project import ProjectModel
from app.models.workflow import WorkflowModel
from app.models.workflow_run import WorkflowRunModel
from app.services.dlp_gate import DLPBlockedError, format_blocked_response
from app.services.spend_gate import BudgetExceededError, format_budget_blocked_response
from app.services.workflow_service import WorkflowService, _LAYER_FAN_OUT_CAP
from app.utils.helpers import serialize_doc
from app.utils.ids import is_valid_id
from app.utils.permissions import check_project_access

logger = logging.getLogger(__name__)

# Per-worker admission cap for full/partial WORKFLOW RUNS (DB pool-DoS ceiling).
#
# Each multi-node run offloads ``execute_workflow`` to a worker thread, and every
# DAG layer fans out up to ``_LAYER_FAN_OUT_CAP`` node tasks that each open their
# own ``db.session_scope()`` pinning a pooled connection across a multi-second
# provider call (see workflow_service). The pre-existing
# ``find_running_for_workflow`` guard only blocks a second run of the SAME
# workflow_id — N distinct workflow_ids dodge it — and these routes are NOT
# counted against ``MAX_CONCURRENT_STREAMS_PER_WORKER`` (the stream ceiling sized
# to keep SSE pinning below the 50-conn pool). Without a cap, ~9 concurrent wide
# runs drain ``DB_POOL_SIZE + DB_MAX_OVERFLOW`` (=50) and every other request on
# the worker ``pool_timeout``-fails.
#
# Modeled on ``services/stream_concurrency.py``: a module-level per-worker/
# per-process ``BoundedSemaphore`` acquired NON-BLOCKING in the route before the
# run launches (-> 503 at ceiling), released in a ``finally`` that wraps the WHOLE
# offloaded run so the permit returns on success, exception, AND early return.
#
# Sizing: the worst-case connection draw of one in-flight run is bounded by
# ``_LAYER_FAN_OUT_CAP + 1`` (a wide layer's node tasks + the run's top-level
# session). With the default cap of 3 that is 3 × 7 = 21 connections — comfortably
# below the 50-conn pool even with the stream ceiling (14) fully reserved
# (21 + 14 = 35 < 50), leaving headroom for ordinary non-stream requests.
# Env-overridable for load tuning / tests.
_WORKFLOW_RUN_CEILING = int(os.environ.get("WORKFLOW_MAX_CONCURRENT_RUNS", "3"))

_workflow_run_semaphore = threading.BoundedSemaphore(_WORKFLOW_RUN_CEILING)


def _workflow_busy_response() -> JSONResponse:
    """Fresh 503 (legacy error shape) when the worker is at its run ceiling.

    Built per call rather than shared so response-mutating middleware
    (SecurityHeaders / CSRF in asgi.py) can't accumulate headers on a reused
    instance across requests.
    """
    return JSONResponse(
        {
            "error": "The server is busy running other workflows. Please try again shortly.",
            "code": "workflow_runs_at_capacity",
        },
        status_code=503,
    )

# Router-level dependency: every request runs inside the Flask app_context.
router = APIRouter(dependencies=[Depends(flask_ctx)])
workflow_ai_router = APIRouter(dependencies=[Depends(flask_ctx)])


async def _json_body(request: Request) -> dict:
    """Read the request JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _gate_execute(workflow_id, user_id):
    """Resolve a workflow for execution and check access.

    Returns ``(workflow_doc, error_response_or_None)`` where the error is a
    ready-to-return ``JSONResponse`` (mirrors the Flask tuple shape exactly).

    Project-scoped workflows require ``editor`` on the project; personal
    workflows fall back to owner/template access via ``get_by_id``.
    """
    if not is_valid_id(workflow_id):
        return None, JSONResponse({"error": "Invalid workflow ID"}, status_code=400)

    raw = WorkflowModel.find_by_id(workflow_id)
    if not raw:
        return None, JSONResponse({"error": "Workflow not found"}, status_code=404)

    project_id = raw.get("project_id")
    if project_id:
        if not check_project_access(user_id, project_id, "editor"):
            return None, JSONResponse(
                {"error": "Project access denied", "code": "project_access_denied"},
                status_code=403,
            )
        return raw, None

    # Personal workflow — fall back to owner/template check.
    accessible = WorkflowModel.get_by_id(workflow_id, user_id)
    if not accessible:
        return None, JSONResponse({"error": "Workflow not found"}, status_code=404)
    return accessible, None


# ---------------------------------------------------------------------------
# /api/workflow  (workflow_bp)
# ---------------------------------------------------------------------------
@router.post("/save")
async def save_workflow(request: Request, user: dict = Depends(current_user)):
    """Save or create a workflow."""
    try:
        user_id = user["_id"]
        data = await _json_body(request)

        if not data.get("name"):
            return JSONResponse({"error": "Workflow name is required"}, status_code=400)

        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        workflow_id = data.get("_id") or data.get("id")

        if workflow_id:
            # Update existing workflow — refuse project reassignment.
            if "project_id" in data:
                existing = WorkflowModel.find_by_id(workflow_id)
                if existing is not None:
                    existing_pid = existing.get("project_id")
                    incoming_pid = data.get("project_id") or None
                    if (str(existing_pid) if existing_pid else None) != (
                        str(incoming_pid) if incoming_pid else None
                    ):
                        return JSONResponse(
                            {
                                "error": "Cannot reassign workflow to a different project",
                                "code": "cannot_reassign_project",
                            },
                            status_code=400,
                        )

            # Optimistic concurrency — require an If-Match (or body version)
            # carrying the version the client last saw; 409 on stale writes.
            current_version = WorkflowModel.get_version(workflow_id) or 0
            client_version_str = request.headers.get("If-Match") or (
                str(data.get("version")) if data.get("version") is not None else None
            )
            if client_version_str is not None and str(client_version_str).strip() != "":
                try:
                    client_version = int(str(client_version_str).strip().strip('"'))
                except (TypeError, ValueError):
                    return JSONResponse(
                        {
                            "error": "If-Match header must be an integer version",
                            "code": "invalid_if_match",
                        },
                        status_code=400,
                    )
                if client_version != current_version:
                    return JSONResponse(
                        {
                            "error": "Workflow has been modified by another writer; refresh and retry",
                            "code": "version_conflict",
                            "current_version": current_version,
                        },
                        status_code=409,
                    )

            updates = {
                "name": data["name"],
                "description": data.get("description", ""),
                "nodes": nodes,
                "edges": edges,
                "version": current_version + 1,
            }

            success = WorkflowModel.update(workflow_id, user_id, updates)
            if not success:
                return JSONResponse(
                    {"error": "Workflow not found or unauthorized"}, status_code=404
                )

            workflow = WorkflowModel.get_by_id(workflow_id, user_id)
            return JSONResponse(
                {
                    "message": "Workflow updated successfully",
                    "workflow": serialize_doc(workflow),
                },
                status_code=200,
            )

        # Create new workflow.
        project_id = data.get("project_id") or None
        workspace_id = data.get("workspace_id") or None

        if project_id:
            if not is_valid_id(project_id):
                return JSONResponse({"error": "Invalid project_id"}, status_code=400)
            if not check_project_access(user_id, project_id, "editor"):
                return JSONResponse(
                    {"error": "Project access denied", "code": "project_access_denied"},
                    status_code=403,
                )
            # Auto-derive workspace_id from the project.
            project = ProjectModel.find_by_id(project_id)
            if not project:
                return JSONResponse({"error": "Project not found"}, status_code=404)
            workspace_id = project.get("workspace_id")

        workflow_id = WorkflowModel.create(
            user_id=user_id,
            name=data["name"],
            description=data.get("description", ""),
            nodes=nodes,
            edges=edges,
            project_id=project_id,
            workspace_id=workspace_id,
        )

        workflow = WorkflowModel.get_by_id(workflow_id, user_id)
        return JSONResponse(
            {
                "message": "Workflow created successfully",
                "workflow": serialize_doc(workflow),
            },
            status_code=201,
        )

    except Exception as e:  # noqa: BLE001
        logger.exception("Error saving workflow: %s", e)
        return JSONResponse({"error": "Failed to save workflow"}, status_code=500)


@router.get("/list")
def list_workflows(request: Request, user: dict = Depends(current_user)):
    """Get workflows for the current user, optionally scoped to a project."""
    try:
        user_id = user["_id"]
        project_id = request.query_params.get("project_id")

        if project_id:
            if not is_valid_id(project_id):
                return JSONResponse({"error": "Invalid project_id"}, status_code=400)
            if not check_project_access(user_id, project_id, "viewer"):
                return JSONResponse(
                    {"error": "Project access denied", "code": "project_access_denied"},
                    status_code=403,
                )
            workflows = WorkflowModel.find_visible_to(user_id, project_id=project_id)
        else:
            workflows = WorkflowModel.get_by_user(user_id)

        return {"workflows": [serialize_doc(w) for w in workflows]}

    except Exception as e:  # noqa: BLE001
        logger.exception("Error listing workflows: %s", e)
        return JSONResponse({"error": "Failed to list workflows"}, status_code=500)


@router.get("/templates")
def get_templates(user: dict = Depends(current_user)):
    """Get all workflow templates."""
    try:
        templates = WorkflowModel.get_templates()
        return {"templates": [serialize_doc(t) for t in templates]}

    except Exception as e:  # noqa: BLE001
        logger.exception("Error getting templates: %s", e)
        return JSONResponse({"error": "Failed to get templates"}, status_code=500)


@router.post("/execute")
async def execute_workflow(request: Request, user: dict = Depends(current_user)):
    """Execute a workflow completely."""
    try:
        user_id = user["_id"]
        data = await _json_body(request)

        workflow_id = data.get("workflow_id")
        if not workflow_id:
            return JSONResponse({"error": "workflow_id is required"}, status_code=400)

        _, err = _gate_execute(workflow_id, user_id)
        if err:
            return err

        # Refuse a second concurrent run for the same workflow.
        existing_run_id = WorkflowRunModel.find_running_for_workflow(workflow_id)
        if existing_run_id:
            return JSONResponse(
                {
                    "error": "A run is already in progress for this workflow",
                    "code": "workflow_run_in_progress",
                    "run_id": existing_run_id,
                },
                status_code=409,
            )

        # Per-worker run-admission cap (DB pool-DoS ceiling). Acquire one permit
        # NON-BLOCKING before launching the fan-out; at ceiling return 503 rather
        # than queueing (the run pins pooled connections, so a backlog is exactly
        # what drains the pool). The permit covers the WHOLE offloaded run and is
        # released in a finally below — success, exception, and early return.
        if not _workflow_run_semaphore.acquire(blocking=False):
            return _workflow_busy_response()

        try:
            # Offload the multi-node DLP + spend + LLM fan-out (joins worker
            # threads, blocks seconds-to-minutes) off the uvicorn event loop.
            # anyio copies the contextvars Context into the worker; the closure
            # opens its OWN db.session_scope() so the service's top-level
            # bookkeeping (run records, gates) runs against a fresh session rather
            # than the request-thread one (SQLAlchemy sessions are not
            # thread-safe). The service's internal per-node child threads still
            # open their own scopes, unaffected. DLPBlockedError /
            # BudgetExceededError / ValueError propagate through run_sync
            # unchanged, so the handlers below still fire.
            def _run():
                with db.session_scope():
                    return WorkflowService.execute_workflow(
                        workflow_id=workflow_id,
                        user_id=user_id,
                        execution_mode="full",
                        dlp_confirmed=bool(data.get("dlp_confirmed")),
                        dlp_confirm_token=data.get("dlp_confirm_token"),
                    )

            result = await anyio.to_thread.run_sync(_run)
        finally:
            # The offloaded run is fully complete (returned or raised) by the time
            # the awaited run_sync unwinds, so releasing here returns the permit on
            # every path — including the DLP/Budget/ValueError re-raises caught by
            # the handlers below. BoundedSemaphore raises ValueError on
            # over-release; a single acquire paired with this single release keeps
            # the count exact.
            _workflow_run_semaphore.release()

        return {
            "message": "Workflow executed successfully",
            "run_id": result["run_id"],
            "status": result["status"],
            "node_results": result["node_results"],
            "run": serialize_doc(result["run"]) if result.get("run") else None,
        }

    except DLPBlockedError as dlp_exc:
        return JSONResponse(format_blocked_response(dlp_exc), status_code=403)
    except BudgetExceededError as exc:
        return JSONResponse(format_budget_blocked_response(exc), status_code=402)
    except ValueError as e:
        logger.warning("[execute_workflow] ValueError: %s", e)
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        logger.exception("[execute_workflow] Exception: %s", e)
        return JSONResponse(
            {"error": "Failed to execute workflow"}, status_code=500
        )


@router.post("/execute-from")
async def execute_from_node(request: Request, user: dict = Depends(current_user)):
    """Execute workflow starting from a specific node."""
    try:
        user_id = user["_id"]
        data = await _json_body(request)

        workflow_id = data.get("workflow_id")
        node_id = data.get("node_id")

        if not workflow_id:
            return JSONResponse({"error": "workflow_id is required"}, status_code=400)
        if not node_id:
            return JSONResponse({"error": "node_id is required"}, status_code=400)

        _, err = _gate_execute(workflow_id, user_id)
        if err:
            return err

        # Per-worker run-admission cap — same ceiling as /execute (a partial run
        # fans out the same way). Acquire NON-BLOCKING; 503 at capacity; release
        # in the finally wrapping the whole offloaded run.
        if not _workflow_run_semaphore.acquire(blocking=False):
            return _workflow_busy_response()

        try:
            # Offload the partial-run fan-out off the event loop (see /execute for
            # the full rationale). Own db.session_scope() per worker; exceptions
            # propagate through run_sync so the handlers below stay intact.
            def _run():
                with db.session_scope():
                    return WorkflowService.execute_workflow(
                        workflow_id=workflow_id,
                        user_id=user_id,
                        execution_mode="partial",
                        start_node_id=node_id,
                        dlp_confirmed=bool(data.get("dlp_confirmed")),
                        dlp_confirm_token=data.get("dlp_confirm_token"),
                    )

            result = await anyio.to_thread.run_sync(_run)
        finally:
            # Single acquire ↔ single release: returns the permit on success,
            # exception, and early return (see /execute for the lifecycle note).
            _workflow_run_semaphore.release()

        return {
            "message": "Workflow executed successfully",
            "run_id": result["run_id"],
            "status": result["status"],
            "node_results": result["node_results"],
            "run": serialize_doc(result["run"]) if result.get("run") else None,
        }

    except DLPBlockedError as dlp_exc:
        return JSONResponse(format_blocked_response(dlp_exc), status_code=403)
    except BudgetExceededError as exc:
        return JSONResponse(format_budget_blocked_response(exc), status_code=402)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        logger.exception("Error executing workflow from node: %s", e)
        return JSONResponse({"error": "Failed to execute workflow"}, status_code=500)


@router.post("/execute-node")
async def execute_single_node(request: Request, user: dict = Depends(current_user)):
    """Execute only a single node using existing inputs from connected nodes."""
    try:
        user_id = user["_id"]
        data = await _json_body(request)

        workflow_id = data.get("workflow_id")
        node_id = data.get("node_id")

        if not workflow_id:
            return JSONResponse({"error": "workflow_id is required"}, status_code=400)
        if not node_id:
            return JSONResponse({"error": "node_id is required"}, status_code=400)

        _, err = _gate_execute(workflow_id, user_id)
        if err:
            return err

        # Offload the single-node execution (DLP + spend gate + one blocking
        # LLM/image/TTS/video call) off the event loop. Own db.session_scope()
        # per worker; ValueError/DLPBlockedError/BudgetExceededError propagate
        # through run_sync so the handlers below still fire. Note: a node-level
        # failure is returned as a {'status': 'failed'} dict (not raised), so the
        # branch below is preserved.
        def _run():
            with db.session_scope():
                return WorkflowService.execute_single_node(
                    workflow_id=workflow_id,
                    node_id=node_id,
                    user_id=user_id,
                    dlp_confirmed=bool(data.get("dlp_confirmed")),
                    dlp_confirm_token=data.get("dlp_confirm_token"),
                )

        result = await anyio.to_thread.run_sync(_run)

        if result["status"] == "failed":
            return JSONResponse(
                {
                    "error": result.get("error", "Node execution failed"),
                    "node_id": node_id,
                    "status": "failed",
                },
                status_code=400,
            )

        # Mirror every key the result dict carries (image/text/audio/video/...).
        return {
            "message": "Node executed successfully",
            "node_id": result["node_id"],
            "status": result["status"],
            "image_data": result.get("image_data"),
            "image_id": result.get("image_id"),
            "text": result.get("text"),
            "text_variants": result.get("text_variants"),
            "audio_data_uri": result.get("audio_data_uri"),
            "audio_id": result.get("audio_id"),
            "duration_ms": result.get("duration_ms"),
            "video_url": result.get("video_url"),
            "video_id": result.get("video_id"),
            "duration_sec": result.get("duration_sec"),
            "resolution": result.get("resolution"),
            "generation_time_ms": result.get("generation_time_ms"),
        }

    except DLPBlockedError as dlp_exc:
        return JSONResponse(format_blocked_response(dlp_exc), status_code=403)
    except BudgetExceededError as exc:
        return JSONResponse(format_budget_blocked_response(exc), status_code=402)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        logger.exception("Error executing single node: %s", e)
        return JSONResponse({"error": "Failed to execute node"}, status_code=500)


@router.get("/runs/{workflow_id}")
def get_workflow_runs(workflow_id: str, user: dict = Depends(current_user)):
    """Get execution history for a workflow."""
    try:
        user_id = user["_id"]

        if not is_valid_id(workflow_id):
            return JSONResponse({"error": "Invalid workflow ID"}, status_code=400)

        runs = WorkflowService.get_workflow_runs(
            workflow_id=workflow_id, user_id=user_id
        )

        return {"runs": [serialize_doc(r) for r in runs]}

    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        logger.exception("Error getting workflow runs: %s", e)
        return JSONResponse({"error": "Failed to get workflow runs"}, status_code=500)


@router.post("/{workflow_id}/duplicate")
async def duplicate_workflow(
    workflow_id: str, request: Request, user: dict = Depends(current_user)
):
    """Duplicate a workflow."""
    try:
        user_id = user["_id"]
        data = await _json_body(request)

        if not is_valid_id(workflow_id):
            return JSONResponse({"error": "Invalid workflow ID"}, status_code=400)

        workflow = WorkflowModel.get_by_id(workflow_id, user_id)
        if not workflow:
            return JSONResponse({"error": "Workflow not found"}, status_code=404)

        new_name = data.get("name")
        new_workflow_id = WorkflowModel.duplicate(workflow_id, user_id, new_name)

        if not new_workflow_id:
            return JSONResponse(
                {"error": "Failed to duplicate workflow"}, status_code=500
            )

        new_workflow = WorkflowModel.get_by_id(new_workflow_id, user_id)
        return JSONResponse(
            {
                "message": "Workflow duplicated successfully",
                "workflow": serialize_doc(new_workflow),
            },
            status_code=201,
        )

    except Exception as e:  # noqa: BLE001
        logger.exception("Error duplicating workflow: %s", e)
        return JSONResponse({"error": "Failed to duplicate workflow"}, status_code=500)


# NOTE: the catch-all ``/{workflow_id}`` routes are registered LAST so the more
# specific literal paths above (``/list``, ``/templates``, ``/execute*``,
# ``/runs/{...}``, ``/{...}/duplicate``) win — Flask's url_map resolved these by
# specificity; FastAPI matches by registration order, so order is load-bearing.
@router.get("/{workflow_id}")
def get_workflow(workflow_id: str, user: dict = Depends(current_user)):
    """Get a specific workflow by ID."""
    try:
        user_id = user["_id"]

        if not is_valid_id(workflow_id):
            return JSONResponse({"error": "Invalid workflow ID"}, status_code=400)

        workflow = WorkflowModel.get_by_id(workflow_id, user_id)
        if not workflow:
            # Fall back: project-scoped workflow visible via project membership.
            raw = WorkflowModel.find_by_id(workflow_id)
            if (
                raw
                and raw.get("project_id")
                and check_project_access(user_id, raw["project_id"], "viewer")
            ):
                workflow = raw
            else:
                return JSONResponse({"error": "Workflow not found"}, status_code=404)

        return {"workflow": serialize_doc(workflow)}

    except Exception as e:  # noqa: BLE001
        logger.exception("Error getting workflow: %s", e)
        return JSONResponse({"error": "Failed to get workflow"}, status_code=500)


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: str, user: dict = Depends(current_user)):
    """Delete a workflow.

    Project-scoped workflows require ``owner`` on the project; personal
    workflows keep the creator-only delete semantics.
    """
    try:
        user_id = user["_id"]

        if not is_valid_id(workflow_id):
            return JSONResponse({"error": "Invalid workflow ID"}, status_code=400)

        raw = WorkflowModel.find_by_id(workflow_id)
        if not raw:
            return JSONResponse(
                {"error": "Workflow not found or unauthorized"}, status_code=404
            )

        # Templates are never user-deletable from this route.
        if raw.get("is_template"):
            return JSONResponse(
                {"error": "Workflow not found or unauthorized"}, status_code=404
            )

        project_id = raw.get("project_id")
        if project_id:
            if not check_project_access(user_id, project_id, "owner"):
                return JSONResponse(
                    {"error": "Project access denied", "code": "project_access_denied"},
                    status_code=403,
                )
            if not WorkflowModel.delete_unchecked(workflow_id):
                return JSONResponse(
                    {"error": "Workflow not found or unauthorized"}, status_code=404
                )
        else:
            success = WorkflowModel.delete(workflow_id, user_id)
            if not success:
                return JSONResponse(
                    {"error": "Workflow not found or unauthorized"}, status_code=404
                )

        return {"message": "Workflow deleted successfully"}

    except Exception as e:  # noqa: BLE001
        logger.exception("Error deleting workflow: %s", e)
        return JSONResponse({"error": "Failed to delete workflow"}, status_code=500)


# ---------------------------------------------------------------------------
# /api/workflow-ai  (workflow_ai_bp)
# ---------------------------------------------------------------------------
# Comprehensive context about the workflow system for the LLM.
WORKFLOW_CONTEXT = """
# Polymind AI Workflow System

You are generating workflows for an image generation pipeline system. Users describe what they want, and you create the workflow structure.

## Available Node Types

### 1. imageUpload
- **Purpose**: Starting point - user will upload a reference image here
- **Inputs**: None (this is always a source node)
- **Outputs**: 1 image output (handle name: "output")
- **Required data fields**:
  - label: string (descriptive name like "Product Photo", "Style Reference")
- **Use when**: User needs to provide an existing image as input

### 2. imageGen
- **Purpose**: Generate new images using AI models
- **Inputs**: 0-3 reference images (handle names: "input-0", "input-1", "input-2")
- **Outputs**: 1 generated image (handle name: "output")
- **Required data fields**:
  - label: string (descriptive name)
  - model: MUST be one of:
    - "google/gemini-2.5-flash-image" (Nano Banana, fast/cheap, up to 3 reference images, great default)
    - "google/gemini-3.1-flash-image" (Nano Banana 2, Pro-quality at Flash speed, up to 3 refs)
    - "google/gemini-3-pro-image-preview" (Nano Banana Pro, top quality + 1K/2K/4K, up to 14 refs)
    - "openai/gpt-5-image-mini" (efficient OpenAI model, strong text rendering, up to 16 refs)
    - "openai/gpt-5-image" (full GPT-5 reasoning + image gen, up to 16 refs)
    - "openai/gpt-5.4-image-2" (latest OpenAI flagship, high-fidelity edits, up to 16 refs)
  - prompt: string (detailed description of what to generate)
  - negativePrompt: string (what to avoid, e.g., "blurry, low quality, distorted")
- **Use when**: Creating new images or transforming existing ones

## Workflow Patterns

### Linear Chain (sequential processing)
```
imageUpload → imageGen → imageGen → imageGen
```
Use for: Multi-step refinement, progressive enhancement

### Fan-Out (one input, multiple outputs)
```
imageUpload → imageGen (variation 1)
            → imageGen (variation 2)
            → imageGen (variation 3)
```
Use for: Creating multiple variations, social media packs, A/B testing

### Fan-In (multiple inputs, one output)
```
imageUpload (product) ──┐
imageUpload (style)  ───┼→ imageGen (combined result)
imageUpload (scene)  ───┘
```
Use for: Style transfer, compositing, combining multiple references

### Complex (combination of patterns)
```
imageUpload ──┬→ imageGen (style A) ──┬→ imageGen (final blend)
              └→ imageGen (style B) ──┘
```

## Node Positioning Rules
- First column (imageUpload nodes): x = 100
- Each subsequent column: x += 350
- Vertical spacing between nodes: 200
- Center the workflow vertically, start around y = 200-300
- For fan-out: spread output nodes vertically
- For fan-in: align input nodes vertically, output centered

## Connection Rules
- Edge source is always the "output" handle
- Edge target is "input-0", "input-1", or "input-2"
- imageUpload can only be a SOURCE (no incoming edges)
- imageGen can have 0-3 incoming edges and 1 outgoing edge
- NO CYCLES - the workflow must be a DAG (directed acyclic graph)
- Use edge IDs like "e1-2" (edge from node-1 to node-2)

## Prompt Writing Guidelines
- Be specific and descriptive
- Include: subject, style, lighting, composition, quality modifiers
- Product photos: "professional product photography, studio lighting, white background, commercial quality"
- Social media: mention the format context (e.g., "Instagram square format", "Twitter banner wide format")
- Artistic: include art style references (e.g., "oil painting style", "digital art", "photorealistic")
- Always include quality terms: "high quality, detailed, sharp focus"
- Negative prompts should include: "blurry, low quality, distorted, artifacts, watermark"

## Output Format
Return ONLY a valid JSON object with this exact structure:
{
  "name": "Workflow Name",
  "description": "Brief description of what this workflow does",
  "nodes": [
    {
      "id": "node-1",
      "type": "imageUpload",
      "position": {"x": 100, "y": 300},
      "data": {"label": "Input Image"}
    },
    {
      "id": "node-2",
      "type": "imageGen",
      "position": {"x": 450, "y": 300},
      "data": {
        "label": "Generated Output",
        "model": "google/gemini-2.5-flash-image",
        "prompt": "detailed prompt here",
        "negativePrompt": "blurry, low quality, distorted"
      }
    }
  ],
  "edges": [
    {
      "id": "e1-2",
      "source": "node-1",
      "target": "node-2",
      "sourceHandle": "output",
      "targetHandle": "input-0"
    }
  ]
}
"""

SYSTEM_PROMPT = """You are a workflow generator for Polymind AI's image generation system.
Given a user's description, generate a complete and valid workflow JSON.

CRITICAL RULES:
1. Output ONLY valid JSON - no markdown, no explanation, no code blocks
2. Every imageGen node MUST have model, prompt, and negativePrompt in data
3. Model MUST be exactly one of: "google/gemini-2.5-flash-image", "google/gemini-3.1-flash-image", "google/gemini-3-pro-image-preview", "openai/gpt-5-image-mini", "openai/gpt-5-image", "openai/gpt-5.4-image-2"
4. All edges must use sourceHandle: "output" and targetHandle: "input-0" (or input-1, input-2)
5. Node IDs must be unique: node-1, node-2, node-3, etc.
6. Position nodes logically so they don't overlap
7. Write detailed, high-quality prompts for each imageGen node"""


@workflow_ai_router.post("/generate")
async def generate_workflow(request: Request, user: dict = Depends(current_user)):
    """Generate a workflow from natural language description."""
    try:
        from app.models.user import UserModel
        from app.services.model_registry_service import ModelRegistryService
        from app.services.openrouter_service import OpenRouterService

        user_id = user["_id"]
        data = await _json_body(request)
        description = (data.get("description") or "").strip()

        # Resolve attribution context: prefer body, then user's active workspace,
        # else personal-scope (None) — so generator usage rolls up per workspace.
        user_doc = UserModel.find_by_id(user_id) or {}
        body_project_id = data.get("project_id")
        body_workspace_id = data.get("workspace_id")
        gen_workspace_id = body_workspace_id or user_doc.get("active_workspace_id")
        gen_project_id = body_project_id

        if not description:
            return JSONResponse({"error": "Description is required"}, status_code=400)

        if len(description) > 2000:
            return JSONResponse(
                {"error": "Description too long (max 2000 characters)"}, status_code=400
            )

        # Resolve live image-gen models from the registry (falls back gracefully).
        registry = ModelRegistryService()
        image_models = registry.find_by_modality(output=["image"]) or []
        image_model_ids = [m["_id"] for m in image_models]
        default_image_model = (
            image_model_ids[0] if image_model_ids else "google/gemini-2.5-flash-image"
        )

        # Build system prompt with current image model allowlist.
        if image_model_ids:
            model_list_str = "\n    - ".join(f'"{m}"' for m in image_model_ids)
            dynamic_system_prompt = SYSTEM_PROMPT.replace(
                'Model MUST be exactly one of: "google/gemini-2.5-flash-image", "google/gemini-3.1-flash-image", "google/gemini-3-pro-image-preview", "openai/gpt-5-image-mini", "openai/gpt-5-image", "openai/gpt-5.4-image-2"',
                f"Model MUST be exactly one of:\n    - {model_list_str}",
            )
        else:
            dynamic_system_prompt = SYSTEM_PROMPT

        user_message = f"""{WORKFLOW_CONTEXT}

---

USER REQUEST: {description}

Generate a workflow that accomplishes this request. Remember:
- Start with imageUpload nodes for any images the user needs to provide
- Use imageGen nodes with detailed prompts
- Position nodes so they don't overlap
- Connect nodes appropriately

Output only the JSON, nothing else."""

        messages = [{"role": "user", "content": user_message}]

        # Offload the blocking (multi-second) LLM round-trip to a worker thread
        # so it never stalls the uvicorn event loop. Mirrors chat.py's
        # `_completion`: anyio copies the contextvars Context (incl. the
        # flask_ctx app_context / db.session) into the worker, so the usage-log
        # write inside `_record_usage` stays valid; the request thread is parked
        # awaiting and never touches the session concurrently.
        def _completion():
            return OpenRouterService.chat_completion(
                messages=messages,
                model="google/gemini-3.6-flash",
                system_prompt=dynamic_system_prompt,
                temperature=0.1,
                max_tokens=4096,
                stream=False,
                user_id=user_id,
                conversation_id=None,
                feature="workflow_ai",
                workspace_id=str(gen_workspace_id) if gen_workspace_id else None,
                project_id=str(gen_project_id) if gen_project_id else None,
                origin="web",
            )

        response = await anyio.to_thread.run_sync(_completion)

        if "error" in response:
            return JSONResponse(
                {"error": response["error"].get("message", "LLM request failed")},
                status_code=500,
            )

        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")

        if not content:
            return JSONResponse({"error": "No response from LLM"}, status_code=500)

        # Strip any markdown code-fence wrapping.
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
            content = content.strip()

        try:
            workflow = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("JSON parse error: %s | content=%s", e, content[:500])
            return JSONResponse(
                {"error": "Failed to parse workflow JSON from LLM response"},
                status_code=500,
            )

        if "nodes" not in workflow or "edges" not in workflow:
            return JSONResponse(
                {"error": "Invalid workflow structure: missing nodes or edges"},
                status_code=500,
            )

        for node in workflow.get("nodes", []):
            if "id" not in node or "type" not in node or "position" not in node:
                return JSONResponse(
                    {"error": f"Invalid node structure: {node}"}, status_code=500
                )

            if "data" not in node:
                node["data"] = {}

            if node["type"] == "imageGen":
                if "model" not in node["data"]:
                    node["data"]["model"] = default_image_model
                if "prompt" not in node["data"]:
                    node["data"]["prompt"] = ""
                if "negativePrompt" not in node["data"]:
                    node["data"]["negativePrompt"] = "blurry, low quality, distorted"

        return {"success": True, "workflow": workflow}

    except Exception as e:  # noqa: BLE001
        logger.exception("Error generating workflow: %s", e)
        return JSONResponse(
            {"error": "Failed to generate workflow"}, status_code=500
        )


__all__ = ["router", "workflow_ai_router"]
