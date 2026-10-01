"""Sandbox artifact helpers shared by chat data-analyzer + agent.

Summarize / persist / prune file artifacts and format tool results for the model.
Moved out of the fat chat router so agent does not import routers.
"""
from __future__ import annotations

import logging
import os
import shutil
import uuid

from app.models.upload import UploadModel
from app.settings import settings

logger = logging.getLogger(__name__)

STDOUT_FEEDBACK_CAP = 4000  # chars of stdout fed back to the model per round
STDERR_FEEDBACK_CAP = 1800  # chars of stderr (tail) fed back per round (traceback + loader/output notes)

def summarize_artifacts(artifacts: list) -> str:
    """One-line human note of what a run_python call emitted (for the model).

    The model does NOT receive the artifact payloads (those go to the
    frontend) — only a shape note so it knows the render succeeded.
    """
    charts: list[str] = []
    tables: list[str] = []
    files: list[str] = []
    metrics: list[str] = []
    insights = 0
    for art in artifacts or []:
        if not isinstance(art, dict):
            continue
        atype = art.get('type')
        if atype == 'chart':
            kind = str(art.get('kind') or 'chart')
            # Flag an empty render so the model knows the chart has no data (it
            # commonly believes a render "succeeded" when it emitted 0 rows).
            empty = not (art.get('data') or [])
            charts.append(kind + (", EMPTY — 0 rows" if empty else ""))
        elif atype == 'table':
            n = art.get('total_rows')
            if n is None:
                n = len(art.get('rows') or [])
            tables.append(f"{n} rows")
        elif atype == 'file':
            files.append(str(art.get('name') or 'file'))
        elif atype == 'metric':
            # Echo label=value(+unit) so the model can cross-check the number it is
            # about to narrate against what it actually rendered (closes the
            # deterministic-compute->narrate loop without spending another round).
            label = str(art.get('label') or 'metric')
            value = art.get('value')
            unit = art.get('unit')
            vtxt = '' if value is None else str(value)
            metrics.append(f"{label}={vtxt}" + (f" {unit}" if unit else ""))
        elif atype == 'insight':
            insights += 1
    parts: list[str] = []
    if metrics:
        parts.append(f"{len(metrics)} metric" + ("s" if len(metrics) != 1 else "")
                     + f" ({'; '.join(metrics)})")
    if insights:
        parts.append(f"{insights} insight" + ("s" if insights != 1 else ""))
    if charts:
        parts.append(f"{len(charts)} chart" + ("s" if len(charts) != 1 else "")
                     + f" ({', '.join(charts)})")
    if tables:
        parts.append(f"{len(tables)} table" + ("s" if len(tables) != 1 else "")
                     + f" ({'; '.join(tables)})")
    # Downloadable files are the ONLY delivery signal the model gets, so it can
    # tell the user "report.xlsx is ready" — name each one explicitly.
    if files:
        parts.append(f"{len(files)} file" + ("s" if len(files) != 1 else "")
                     + f" ({', '.join(files)})")
    return "Emitted " + ", ".join(parts) + "." if parts else ""


def persist_one_file_artifact(art: dict, *, workdir: str, outputs_root: str,
                               upload_folder: str, user_id, dedupe: dict) -> bool:
    """Persist a single ``type=='file'`` artifact. Returns True iff it survived.

    Copies the sandbox bytes into ``UPLOAD_FOLDER``, creates the owner-scoped
    :class:`UploadModel` row, and enriches ``art`` in place with ``upload_id`` +
    ``url`` (dropping the internal ``rel_path``). Returns False (and the caller
    drops the artifact) on a traversal/missing source or any copy/DB failure —
    a file artifact with no ``url`` is useless to the frontend.
    """
    rel_path = art.get('rel_path') or ''
    src = os.path.realpath(os.path.join(workdir, rel_path))
    # rel_path is model-influenced (the runner echoes the name the code chose),
    # so confine the resolved source to <workdir>/outputs and require a regular
    # file — a crafted ``../`` rel_path is rejected here.
    if not (src == outputs_root or src.startswith(outputs_root + os.sep)):
        logger.warning("data artifact rel_path escaped outputs: %r", rel_path)
        return False
    if not os.path.isfile(src):
        return False

    original_name = str(art.get('name') or 'output')
    ext = str(art.get('ext') or '').lstrip('.').lower()
    disk_filename = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    dst = os.path.join(upload_folder, disk_filename)
    shutil.copyfile(src, dst)
    size = int(art.get('size') or os.path.getsize(dst))

    # Dedupe across rounds: same output name → delete the prior row + disk file.
    prev = dedupe.get(original_name)
    if prev is not None:
        prev_upload_id, prev_disk = prev
        try:
            UploadModel.delete(prev_upload_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("data artifact dedupe row delete failed: %s", exc)
        try:
            os.remove(os.path.join(upload_folder, prev_disk))
        except OSError:
            pass

    row = UploadModel.create(
        user_id=user_id,
        filename=disk_filename,
        original_name=original_name,
        mime_type=art.get('mime') or 'application/octet-stream',
        size=size,
        type='file',
        force_attachment=True,
        extraction_status='na',
    )
    upload_id = row['_id']
    dedupe[original_name] = (upload_id, disk_filename)
    art['upload_id'] = str(upload_id)
    art['url'] = f"/api/uploads/{upload_id}"
    art.pop('rel_path', None)
    return True


def persist_file_artifacts(artifacts: list, *, workdir: str, user_id,
                            dedupe: dict) -> list:
    """Persist every sandbox ``type=='file'`` artifact in ``artifacts`` in place.

    Returns the (possibly filtered) artifact list: NON-file artifacts pass
    through untouched; file artifacts that copy successfully are enriched with
    ``upload_id`` + ``url``; file artifacts that fail (traversal, missing source,
    copy/DB error, or over the per-round cap) are DROPPED — so a file artifact
    that reaches the frontend / the model's recap always has a real download URL
    (the only delivery signal). Mutates the surviving dicts in place; the caller
    reassigns its list to the return value.

    MUST be called inside an active ``db.session_scope()`` — it writes rows.
    ``dedupe`` is a caller-owned ``{original_name: (upload_id, disk_filename)}``
    map carried across rounds (later same-name output deletes the prior row+file,
    so the model regenerating ``report.xlsx`` leaves no orphans). Capped at
    ``DATA_OUTPUT_MAX_FILES`` persisted files per round (runner also caps).
    """
    if not artifacts:
        return artifacts
    upload_folder = settings.get('UPLOAD_FOLDER', 'uploads')
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder, exist_ok=True)
    outputs_root = os.path.realpath(os.path.join(workdir, 'outputs'))
    max_files = int(settings.get('DATA_OUTPUT_MAX_FILES', 5))
    kept: list = []
    persisted = 0
    for art in artifacts:
        if not isinstance(art, dict) or art.get('type') != 'file':
            kept.append(art)
            continue
        if persisted >= max_files:
            continue  # over the cap — drop (don't surface a path-only artifact)
        try:
            if persist_one_file_artifact(
                art, workdir=workdir, outputs_root=outputs_root,
                upload_folder=upload_folder, user_id=user_id, dedupe=dedupe,
            ):
                kept.append(art)
                persisted += 1
        except Exception as exc:  # noqa: BLE001 — one bad file never kills the round
            logger.warning("data file-artifact persistence failed: %s", exc, exc_info=True)
    return kept


def prune_dead_file_artifacts(all_artifacts: list, file_dedupe: dict) -> list:
    """Drop file artifacts whose upload row was superseded by a same-name re-emit.

    Cross-round dedupe (``persist_one_file_artifact``) HARD-deletes the prior
    round's :class:`UploadModel` row + disk file when the model re-emits the same
    output name in a later round, but the prior round's artifact dict — now a DEAD
    ``upload_id``/``url`` — was already appended to ``all_artifacts``. Persisting it
    into ``metadata.data_artifacts`` would render a download card that 404s (and
    survives reload). Keep only file artifacts whose ``upload_id`` is still a current
    survivor in ``file_dedupe``; non-file artifacts pass through untouched.
    """
    if not all_artifacts:
        return all_artifacts
    live_ids = {str(v[0]) for v in file_dedupe.values()}
    pruned: list = []
    for art in all_artifacts:
        if isinstance(art, dict) and art.get('type') == 'file':
            if str(art.get('upload_id') or '') not in live_ids:
                continue
        pruned.append(art)
    return pruned


def append_artifact_recaps(context_messages: list) -> None:
    """Recap each prior assistant turn's emitted artifacts into its content.

    On a follow-up the model only sees prose ``content`` — the artifacts it
    emitted earlier live in ``metadata.data_artifacts`` and never reach the LLM,
    so it loses track of what it already produced. For each prior ASSISTANT turn
    that carries artifacts we append a one-line recap to a SHALLOW COPY of that
    message (persisted rows untouched — same copy-on-write idiom as the
    attachment strip). Mutates ``context_messages`` in place.
    """
    for idx in range(len(context_messages)):
        cm = context_messages[idx]
        if cm.get("role") != "assistant":
            continue
        arts = ((cm.get("metadata") or {}).get("data_artifacts") or {}).get("artifacts")
        if not arts:
            continue
        note = summarize_artifacts(arts)
        if not note:
            continue
        cm = dict(cm)
        # note already reads "Emitted ...." — phrase it as a recall hint.
        recap = note.replace("Emitted ", "", 1).rstrip(".")
        cm["content"] = (cm.get("content") or "") + (
            f"\n\n[Earlier in this analysis you emitted: {recap}.]"
        )
        context_messages[idx] = cm

def truncation_caveat(manifest: list) -> str:
    """Standing per-round reminder that some loaded tables are a HEAD sample.

    The ingest-cap truncation flag + the SAMPLE warning live only in the one-time
    system-prompt preview; after a round or two the model forgets and may narrate a
    sample total as the full-file total. Re-state it every round from the manifest's
    ``truncated`` flag so the caveat stays in the model's working context.
    """
    if not manifest:
        return ""
    sampled = [str(m.get('var') or m.get('name'))
               for m in manifest
               if isinstance(m, dict) and m.get('truncated')]
    if not sampled:
        return ""
    return ("[reminder: " + ", ".join(sampled) +
            " loaded only the FIRST rows of a larger file — any totals/aggregates "
            "are over a SAMPLE; disclose that or recompute over the full file.]")


def format_tool_result_for_model(sandbox_result: dict,
                                  manifest: "list | None" = None) -> str:
    """Build the SHORT tool-result string fed back to the model.

    Truncated stdout + the runner's stderr TAIL (loader warnings, output-rejection
    reasons, the real traceback) + the one-line error + an artifact note + a
    standing truncation caveat. Never the full artifact data — the model only needs
    to know they were produced + shape.
    """
    if not isinstance(sandbox_result, dict):
        return "[run_python] no result"
    parts: list[str] = []
    stdout = sandbox_result.get('stdout') or ''
    if stdout:
        if len(stdout) > STDOUT_FEEDBACK_CAP:
            stdout = stdout[:STDOUT_FEEDBACK_CAP] + "\n[...stdout truncated...]"
        parts.append(f"stdout:\n{stdout}")
    if sandbox_result.get('timed_out'):
        parts.append("[execution timed out]")
    err = sandbox_result.get('error')
    if err:
        parts.append(f"error:\n{err}")
    # Forward the runner's stderr TAIL: it carries the full traceback (so SELF-FIX-
    # ON-ERROR in the system prompt can actually be followed), every DATA LOADING
    # WARNING (skipped rows / unparseable files, re-emitted each round), and the
    # save_output rejection reasons (unsupported/over-size/over-count) that never
    # surface in ``error``. Tail-biased so the traceback's final frames + the most
    # recent notes survive the cap.
    stderr = sandbox_result.get('stderr') or ''
    if stderr.strip():
        if len(stderr) > STDERR_FEEDBACK_CAP:
            stderr = "[...stderr truncated...]\n" + stderr[-STDERR_FEEDBACK_CAP:]
        parts.append(f"stderr:\n{stderr}")
    # Plotting libs are intentionally absent — nudge the model to show_chart.
    blob = f"{err or ''}\n{stderr}"
    if 'ModuleNotFoundError' in blob and any(
        name in blob for name in ('matplotlib', 'seaborn', 'plotly')
    ):
        parts.append(
            "[hint] matplotlib/seaborn/plotly are NOT installed. "
            "Do not import them. Build a small DataFrame and call "
            "show_chart(kind, data, x=..., y=..., title=...) instead "
            "(kinds: bar|line|area|pie|scatter|histogram|box|heatmap|combo)."
        )
    note = summarize_artifacts(sandbox_result.get('artifacts') or [])
    if note:
        parts.append(note)
    caveat = truncation_caveat(manifest or [])
    if caveat:
        parts.append(caveat)
    if not parts:
        parts.append("(no output)")
    return "\n\n".join(parts)


