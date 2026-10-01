"""Data-analyzer path helpers still owned by the chat router.

Streaming data producer lives nested inside ``stream._stream_chat_impl``;
this module holds the shared tool schema, constants, prefs trimmer, and the
non-streaming ``_run_data_analysis_sync`` used by regenerate.
"""
from __future__ import annotations

from app.api.core import db
from app.services import spend_gate
from app.services.openrouter_service import OpenRouterService
from app.settings import settings

from ._common import (
    _format_tool_result_for_model,
    _logger,
    _persist_file_artifacts,
    _prune_dead_file_artifacts,
)

# ---------------------------------------------------------------------------
# Data Analyzer (intent == 'data') — agentic run_python tool loop over the
# user's uploaded tabular data. The sandbox + dataset prep live in sibling
# services (sandbox_service / data_analysis_service) owned by another agent;
# they are imported LAZILY inside the producer so this module still imports
# cleanly before those files land, and so a missing sandbox fails CLOSED.
# ---------------------------------------------------------------------------

# JSON-schema function tool exposed to the model. One required string param.
_RUN_PYTHON_TOOL = {
    'type': 'function',
    'function': {
        'name': 'run_python',
        'description': (
            'Execute Python (pandas/numpy/scipy/sklearn/statsmodels) against the '
            'preloaded `df` (and `dfs`/`datafiles` for multiple files) in a '
            'stateless sandbox. Use print() to inspect. Render results to the '
            'user with the injected helpers show_metric / show_insight / '
            'show_table / show_chart (kinds: bar, line, area, pie, scatter, '
            'histogram, box, heatmap, combo) and query with sql(). See the '
            'system prompt for full helper signatures and the required emit order.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'code': {
                    'type': 'string',
                    'description': 'Self-contained Python source to execute.',
                },
            },
            'required': ['code'],
            'additionalProperties': False,
        },
    },
}

# Sentinel pushed onto the data-analysis frame bridge queue when the tool loop
# thread finishes, so the draining producer generator stops waiting for frames.
_DATA_LOOP_DONE = object()

# Data Analyzer forces a strong, tool-calling + reasoning-capable model. Weak
# models (e.g. gemini flash-lite, the chat default) ignore the show_chart/
# show_table helpers and improvise charts as raw SVG/HTML in the narration
# instead of emitting real artifacts — so the interactive chart/table never
# renders. Sonnet 4.6 reliably drives the code-interpreter loop at a fraction of
# Opus's cost. (v1: forced; a future picker may allow other strong tool-capable
# models.)
# Fallback heavy model id when settings/router unavailable (see data_model_router).
_DATA_ANALYSIS_MODEL = 'anthropic/claude-sonnet-5'
# Near-deterministic on purpose: the loop writes CODE and narrates NUMBERS —
# sampling noise produces wrong column guesses and re-rounded figures. The
# persona/chat temperature default (0.7) must never leak into the data path.
_DATA_ANALYSIS_TEMPERATURE = 0.1
# Usage/spend attribution tag — keeps data-analyzer spend out of plain chat rollups.
_DATA_FEATURE = 'data_analyzer'

# Injected as a final system turn before the narration round WHEN the tool loop hit
# its round cap with a tool call still pending. Without it the model narrates the
# truncated analysis as if finished (the history ends on an unanswered tool call and
# nothing signals the force-stop), stating conclusions for steps it never ran.
_DATA_CAPPED_NARRATION_NOTE = (
    "You have reached the maximum number of code-execution rounds for this turn. "
    "Do NOT request any more tools. Write your final answer NOW using ONLY the "
    "numbers you already computed and saw in output. If the analysis is incomplete, "
    "say so plainly and tell the user what still needs to be done."
)

def _data_analysis_prefs(ai_prefs: dict) -> dict:
    """Trim chat AI-preferences to ONLY the language preference for data mode.

    ``build_enhanced_system_prompt`` prepends the user's ``custom_instructions``
    plus tone/response_style/expertise (``behavior``/``user_info``). In the
    specialized data-analyst flow those generic chat instructions would override
    the data-analyst contract (PROSE-only narration, strict emit order, no-$
    currency rule, deterministic compute), so we drop everything except the
    language so "respond in Persian" still applies.
    """
    if not ai_prefs:
        return {}
    user_info = (ai_prefs or {}).get("user_info", {}) or {}
    return {
        "enabled": bool(ai_prefs.get("enabled")),
        "user_info": {"language": user_info.get("language")},
    }


def _run_data_analysis_sync(
    *,
    formatted_messages: list,
    system_prompt: str,
    model: str,
    params: dict,
    max_rounds: int,
    workdir: str,
    sandbox_run,
    user_id,
    conversation_id,
    workspace_id,
    project_id,
    manifest: "list | None" = None,
    reasoning_effort: "str | None" = "high",
) -> dict:
    """Run the full data-analysis tool loop + final narration NON-streamed.

    Used by the regenerate path (a JSON handler — no SSE). Mirrors the streaming
    producer's loop but collects everything, then does one non-streamed narration
    round over the loop's message history. Returns
    ``{content, data_artifacts, finish_reason, error}``.
    """
    steps: list = []
    all_artifacts: list = []
    # {original_name: (upload_id, disk_filename)} carried across this run's rounds
    # so a re-emitted output name deletes its prior upload row (no orphans).
    file_dedupe: dict = {}

    def _exec(name: str, args: dict) -> str:
        step_no = len(steps) + 1
        code = (args or {}).get("code") or "" if name == "run_python" else ""
        if name != "run_python":
            steps.append({"step": step_no, "code": code, "stdout": "",
                          "error": f"unknown tool {name!r}"})
            return f"[tool error] unknown tool {name!r}"
        # Mid-loop spend re-check — multi-round Sonnet can exceed preflight budget.
        try:
            spend_gate.gate(
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                origin="web",
                feature=_DATA_FEATURE,
            )
        except spend_gate.BudgetExceededError as exc:
            err = f"budget exceeded ({exc.scope}): analysis stopped"
            steps.append({"step": step_no, "code": code, "stdout": "", "error": err})
            return f"[tool error] {err}"
        result = sandbox_run(
            workdir=workdir,
            code=code,
            # Prefer DATA_SANDBOX_* (Config); DATA_PY_* kept as legacy alias.
            timeout_s=int(
                settings.get("DATA_SANDBOX_TIMEOUT_S")
                or settings.get("DATA_PY_TIMEOUT_S", 20)
            ),
            mem_mb=int(
                settings.get("DATA_SANDBOX_MEM_MB")
                or settings.get("DATA_PY_MEM_MB", 1024)
            ),
        )
        result = result if isinstance(result, dict) else {}
        artifacts = [a for a in (result.get("artifacts") or []) if isinstance(a, dict)]
        # Persist file artifacts (enrich with upload_id/url, drop failures). This
        # runs on the anyio.to_thread worker; wrap in an explicit session scope so
        # the UploadModel writes have a bound session regardless of how the loop's
        # burst-and-remove left the contextvar.
        try:
            with db.session_scope():
                artifacts = _persist_file_artifacts(
                    artifacts, workdir=workdir, user_id=user_id, dedupe=file_dedupe,
                )
        except Exception as e:  # noqa: BLE001 — persistence must not kill the round
            _logger.warning("data regen file-artifact persistence failed: %s", e)
        all_artifacts.extend(artifacts)
        steps.append({
            "step": step_no,
            "code": code,
            "stdout": result.get("stdout") or "",
            "error": result.get("error"),
        })
        # Feed the model the post-persist list so its recap names only real files.
        result["artifacts"] = artifacts
        return _format_tool_result_for_model(result, manifest=manifest)

    loop_result = OpenRouterService.run_tool_loop(
        model=model,
        messages=formatted_messages,
        tools=[_RUN_PYTHON_TOOL],
        tool_executor=_exec,
        system_prompt=system_prompt,
        max_rounds=max_rounds,
        temperature=_DATA_ANALYSIS_TEMPERATURE,
        max_tokens=params.get("max_tokens", 32000),
        reasoning_effort=reasoning_effort,
        user_id=user_id,
        conversation_id=conversation_id,
        feature=_DATA_FEATURE,
        workspace_id=workspace_id,
        project_id=project_id,
        origin="web",
    )
    error = loop_result.get("error")
    content = (loop_result.get("content") or "").strip()
    finish_reason = loop_result.get("finish_reason") or "stop"

    # Narration round (non-streamed, no tools) when the loop ended on tools or
    # produced no text — gives a clean final answer over the tool history.
    if not error and (loop_result.get("capped") or not content):
        _nm = loop_result.get("messages")
        if loop_result.get("capped") and _nm:
            # Force-stopped at the round cap — signal it so the model narrates over
            # computed results instead of presenting a truncated analysis as done.
            _nm = _nm + [{"role": "system", "content": _DATA_CAPPED_NARRATION_NOTE}]
        narration = OpenRouterService.chat_completion(
            messages=_nm or formatted_messages,
            model=model,
            # ``_nm`` from run_tool_loop ALREADY leads with the system prompt; pass
            # it again ONLY when falling back to the bare context (else chat_completion
            # prepends a SECOND identical ~4k-token system block).
            system_prompt=(None if _nm else system_prompt),
            temperature=_DATA_ANALYSIS_TEMPERATURE,
            max_tokens=params.get("max_tokens", 32000),
            stream=False,
            reasoning_effort=reasoning_effort,
            user_id=user_id,
            conversation_id=conversation_id,
            feature=_DATA_FEATURE,
            workspace_id=workspace_id,
            project_id=project_id,
            origin="web",
        )
        if isinstance(narration, dict) and "error" not in narration:
            ch = narration.get("choices") or []
            if ch:
                content = (ch[0].get("message") or {}).get("content") or content
                finish_reason = ch[0].get("finish_reason") or finish_reason

    if not content:
        content = ("I ran into a problem completing the analysis."
                   if error else "Analysis complete.")
    # Drop file artifacts whose upload row was superseded by a same-name re-emit
    # (cross-round dedupe hard-deleted the prior row) so no dead download card is
    # persisted into metadata.data_artifacts.
    all_artifacts = _prune_dead_file_artifacts(all_artifacts, file_dedupe)
    return {
        "content": content,
        "data_artifacts": {"steps": steps, "artifacts": all_artifacts},
        "finish_reason": finish_reason,
        "error": error,
    }

