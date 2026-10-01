"""Data Analyzer dataset preparation — the bridge between chat attachments and
the hardened sandbox.

``prepare_dataset`` resolves the tabular attachments on a Data Analyzer turn,
copies their RAW bytes into a conversation-scoped workdir (reused across turns),
then runs a sandboxed PROFILE pass so untrusted bytes are parsed ONLY inside the
sandbox. It returns a ``DatasetContext`` the chat layer feeds to the model.

This module is pandas-FREE on purpose: all parsing happens in runner.py on the
sandbox venv. The backend only copies bytes + reads JSON.

Called from a background SSE producer thread; ``UploadModel`` access is wrapped
in ``db.session_scope()`` (mirrors app/api/sse.py) so the scoped session is bound
on the worker thread.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import time
from typing import Callable, Optional, TypedDict

from app.extensions import db
from app.services.openrouter_service import _read_upload_bytes
from app.services.sandbox_service import SandboxService
from app.settings import settings

logger = logging.getLogger(__name__)

# Attachment kinds we can analyze, mapped to a canonical file extension.
_KIND_BY_EXT = {
    'csv': 'csv', 'tsv': 'csv',
    'xlsx': 'xlsx', 'xls': 'xls', 'xlsm': 'xlsm',
    'txt': 'txt', 'text': 'txt',
    'json': 'json', 'jsonl': 'jsonl',
    'parquet': 'parquet',
}
TABULAR_EXTS = frozenset(_KIND_BY_EXT)

# Document attachments — extracted to a ``.extracted.txt`` text file in data/ so
# the (text-reading) sandbox runner ingests them with zero runner changes.
# Office/html formats reuse document_extraction_service; PDFs + images go through
# a one-shot OpenRouter transcription call.
#   * .doc is intentionally EXCLUDED — document_extraction_service can't parse the
#     legacy binary format (only .docx).
_DOC_EXTS_BACKEND = frozenset({'docx', 'pptx', 'html', 'htm', 'md', 'xml'})
_DOC_EXTS_PDF = frozenset({'pdf'})
_DOC_EXTS_IMAGE = frozenset({'png', 'jpg', 'jpeg', 'webp'})
DOC_EXTS = _DOC_EXTS_BACKEND | _DOC_EXTS_PDF | _DOC_EXTS_IMAGE

MAX_FILES = 5

# Below this many non-whitespace chars a transcription is treated as a failure
# (scanned-but-illegible PDF / blank image) rather than a real document.
_MIN_DOC_CHARS = 20

# MIME prefix for an image extension (data-URI for the vision transcription call).
_IMAGE_MIME = {
    'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
    'webp': 'image/webp',
}


class DatasetContext(TypedDict):
    workdir: str
    files: list[dict]            # [{name, path, kind}]
    preview_markdown: str
    manifest: list[dict]         # [{var, name, shape, columns, dtypes}]
    documents: list[dict]        # [{name, status, reason, target}] — empty when no docs


def _ext_of(name: str) -> str:
    return name.rsplit('.', 1)[-1].lower() if '.' in (name or '') else ''


def _safe_component(name: str) -> str:
    """A single traversal-free, filesystem-safe filename component.

    Strips any directory parts plus control/reserved chars so a crafted
    attachment ``name`` can never escape the workdir's ``data`` dir. Unicode
    (Persian filenames) is PRESERVED — the old ASCII-only charset collapsed
    every Persian name to ``file``, making distinct docs share one
    ``file.extracted.txt`` cache target (second doc silently reused the first
    doc's extracted text).
    """
    base = os.path.basename(name or '').strip()
    base = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', '_', base).strip('._ ') or 'file'
    return base[:120]


def _sandbox_root() -> str:
    root = settings.get('DATA_SANDBOX_ROOT') or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data_sandbox')
    return os.path.abspath(root)


def _workdir_for(conversation_id: str) -> str:
    # Conversation id is a UUID from our own DB; sanitize anyway (defence-in-depth).
    safe_conv = _safe_component(str(conversation_id)) or 'conv'
    return os.path.abspath(os.path.join(_sandbox_root(), safe_conv))


def prune_workdirs(ttl_hours: Optional[float] = None) -> int:
    """Delete conversation workdirs older than ``ttl_hours`` (by mtime).

    Per-conversation dirs under ``DATA_SANDBOX_ROOT`` are never otherwise
    removed, so without this the disk fills and the box outages. ``ttl_hours``
    defaults to ``DATA_WORKDIR_TTL_HOURS`` (env, default 24). Best-effort:
    swallows per-dir errors and never raises. Returns the count removed.

    Also run hourly from ``app/asgi.py`` startup task; still invoked
    opportunistically at the top of ``prepare_dataset`` so it self-heals
    without waiting for the next tick.
    """
    if ttl_hours is None:
        try:
            ttl_hours = float(settings.get('DATA_WORKDIR_TTL_HOURS', 24) or 24)
        except (TypeError, ValueError):
            ttl_hours = 24.0
    cutoff = time.time() - (ttl_hours * 3600.0)
    root = _sandbox_root()
    removed = 0
    try:
        entries = os.listdir(root)
    except OSError:
        return 0
    for name in entries:
        path = os.path.join(root, name)
        try:
            if not os.path.isdir(path):
                continue
            if os.path.getmtime(path) >= cutoff:
                continue
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except OSError as exc:
            logger.warning('prune_workdirs: failed removing %s: %s', path, exc)
    if removed:
        logger.info('prune_workdirs: removed %d stale data workdir(s)', removed)
    return removed


def _tabular_attachments(attachments: list[dict]) -> list[dict]:
    """Pick the tabular attachments, newest-last wins on duplicate names."""
    picked: list[dict] = []
    for att in attachments or []:
        if not isinstance(att, dict):
            continue
        name = att.get('name') or att.get('filename') or ''
        ext = _ext_of(name)
        if ext not in TABULAR_EXTS:
            # Fall back to mime sniffing for extension-less names.
            mime = (att.get('mime_type') or att.get('type') or '').lower()
            if 'csv' in mime:
                ext = 'csv'
            elif 'spreadsheet' in mime or 'excel' in mime:
                ext = 'xlsx'
            elif 'json' in mime:
                ext = 'json'
            elif mime.startswith('text/'):
                ext = 'txt'
            else:
                continue
        if att.get('upload_id'):
            picked.append({**att, '_ext': ext})
    return picked[:MAX_FILES]


def _document_attachments(attachments: list[dict]) -> list[dict]:
    """Pick the document attachments (PDF / image / office-doc) carrying an upload.

    Mirrors :func:`_tabular_attachments` but for the ``DOC_EXTS`` set. NO cap is
    applied here — :func:`prepare_dataset` enforces the shared ``MAX_FILES`` cap
    across tabular+docs (tabular first, docs fill the remainder) and records the
    overflow as ``status='skipped'`` so the model can still see what was dropped.
    """
    picked: list[dict] = []
    for att in attachments or []:
        if not isinstance(att, dict):
            continue
        name = att.get('name') or att.get('filename') or ''
        ext = _ext_of(name)
        if ext not in DOC_EXTS:
            continue
        if att.get('upload_id'):
            picked.append({**att, '_ext': ext})
    return picked


def _doc_target_name(att: dict) -> str:
    """Sandbox filename a document's extracted text lands in: ``<stem>.<short>.extracted.txt``.

    Stem is the safe component of the original name with its extension stripped,
    so ``Q3 report.pdf`` → ``Q3_report.<short>.extracted.txt``. The ``<short>``
    8-char suffix is derived from the upload_id (a UUID) so two distinct uploads
    whose sanitized stems collide (``گزارش.pdf`` + ``گزارش.docx``, or names sharing
    their first 120 chars) never write the same file — without it the second
    upload silently reused the first's extracted text. ``.txt`` is an already
    runner-readable kind, so no runner change is needed to ingest it.
    """
    raw = att.get('name') or att.get('filename') or 'document'
    safe = _safe_component(raw)
    stem = safe.rsplit('.', 1)[0] if '.' in safe else safe
    stem = stem or 'document'
    uid = str(att.get('upload_id') or '')
    short = re.sub(r'[^0-9a-fA-F]', '', uid)[:8] or 'doc'
    return f'{stem}.{short}.extracted.txt'


def _llm_transcribe(content_part: dict, instruction: str, *, user_id: str,
                    workspace_id, project_id) -> tuple[str, Optional[str]]:
    """One-shot OpenRouter transcription of a single document content part.

    Used for PDFs (``file`` part + file-parser plugin) and images (``image_url``
    part). Returns ``(text, error_reason)`` — ``error_reason`` is None on success,
    else a short human reason. NO DB session may be held by the caller across this
    call (it does the blocking OpenRouter HTTP round-trip). Never raises.
    """
    from app.services.openrouter_service import OpenRouterService

    model = settings.get('DATA_PDF_EXTRACT_MODEL', 'google/gemini-3.5-flash-lite')
    is_pdf = content_part.get('type') == 'file'
    plugins = None
    if is_pdf:
        engine = settings.get('DATA_PDF_ENGINE') or settings.get('PDF_OCR_ENGINE', 'mistral-ocr')
        plugins = [{'id': 'file-parser', 'pdf': {'engine': engine}}]

    try:
        result = OpenRouterService.chat_completion(
            messages=[{'role': 'user', 'content': [
                content_part,
                {'type': 'text', 'text': instruction},
            ]}],
            model=model,
            temperature=0.0,  # verbatim transcription — any sampling is noise
            max_tokens=int(settings.get('DOC_EXTRACT_MAX_CHARS', 200000) // 3),
            stream=False,
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            origin='web',
            feature='data_pdf_extract',
            plugins=plugins,
        )
    except Exception as exc:  # noqa: BLE001 - a paid-call failure must not crash ingestion
        logger.warning('data-analyzer: transcription call failed: %s', exc)
        return '', 'extraction error'

    if not isinstance(result, dict) or result.get('error'):
        reason = ''
        err = (result or {}).get('error') if isinstance(result, dict) else None
        if isinstance(err, dict):
            reason = str(err.get('message') or err.get('code') or '')[:80]
        return '', reason or 'extraction error'

    return _content_text_from_completion(result), None


def _content_text_from_completion(result: dict) -> str:
    """Pull the transcribed text out of a non-stream chat_completion result.

    Reads ``choices[0].message.content`` (dict OR attr access, per the rest of the
    codebase). Falls back to concatenating any ``file`` annotation text blocks when
    the message content is empty (some file-parser responses stash the parsed text
    in annotations rather than the message body).
    """
    choices = result.get('choices') or []
    if not choices:
        return ''
    first = choices[0]
    message = first.get('message') if isinstance(first, dict) else getattr(first, 'message', None)
    content = ''
    if isinstance(message, dict):
        content = message.get('content') or ''
    elif message is not None:
        content = getattr(message, 'content', '') or ''
    # content may itself be a list of parts on some providers.
    if isinstance(content, list):
        content = '\n'.join(
            p.get('text', '') for p in content if isinstance(p, dict) and p.get('text')
        )
    text = (content or '').strip()
    if text:
        return text

    # Fallback: file-parser annotations carry the parsed document text.
    annotations = result.get('annotations')
    if not annotations and isinstance(message, dict):
        annotations = message.get('annotations')
    parts: list[str] = []
    for ann in annotations or []:
        if not isinstance(ann, dict):
            continue
        file_ann = ann.get('file') if ann.get('type') == 'file' else None
        if isinstance(file_ann, dict):
            blocks = file_ann.get('content') or []
            for blk in blocks if isinstance(blocks, list) else []:
                if isinstance(blk, dict) and blk.get('text'):
                    parts.append(str(blk['text']))
    return '\n'.join(parts).strip()


def _existing_dataset_files(data_dir: str) -> list[dict]:
    """Tabular files already copied into the conversation workdir on a prior turn.

    Lets follow-up turns in a sticky Data Analyzer conversation reuse the dataset
    without re-attaching the file (the workdir persists across turns).
    """
    out: list[dict] = []
    try:
        for fn in sorted(os.listdir(data_dir)):
            p = os.path.join(data_dir, fn)
            if os.path.isfile(p):
                ext = _ext_of(fn)
                out.append({'name': fn, 'path': p,
                            'kind': _KIND_BY_EXT.get(ext, ext)})
    except OSError:
        pass
    return out[:MAX_FILES]


def prepare_dataset(user_id, conversation_id, attachments, *,
                    workspace_id=None, project_id=None,
                    status_cb: Optional[Callable[[dict], None]] = None,
                    stop_event=None
                    ) -> Optional[DatasetContext]:
    """Materialize the conversation's dataset workdir and profile it.

    Copies each NEW tabular attachment's raw bytes into ``<workdir>/data`` (adds
    or replaces by filename), and extracts each NEW document attachment (PDF /
    image / office-doc) to a ``<stem>.extracted.txt`` file in the same dir so the
    text-reading sandbox runner ingests it. When the turn brings no new file,
    REUSES the files already in the workdir from a prior turn — so follow-ups in a
    sticky Data Analyzer conversation don't need to re-attach. Returns ``None``
    only when there's neither a new tabular/doc file nor an existing one.

    ``user_id`` is the authed sender; every upload byte read is OWNER-SCOPED
    through it so a foreign ``upload_id`` smuggled in the attachments array
    resolves to nothing (cross-tenant IDOR guard). ``workspace_id``/``project_id``
    attribute the paid PDF/image transcription calls for usage + budget gating.

    ``status_cb`` (optional) is called ``{'phase': 'extracting', 'file': <name>}``
    right before each FRESH transcription/extraction (NOT cache hits) so the SSE
    layer can surface progress; it is best-effort (exceptions swallowed) and is
    never called with any other phase.
    """
    # Self-healing GC: prune stale conversation workdirs opportunistically so a
    # missing scheduler can't let DATA_SANDBOX_ROOT fill the disk. Best-effort.
    prune_workdirs()

    attachments = attachments or []
    tabular = _tabular_attachments(attachments)
    # Shared MAX_FILES cap across tabular + docs: tabular first, docs fill the
    # remainder. Docs over the cap are recorded as 'skipped' (not extracted).
    doc_atts = _document_attachments(attachments)
    doc_budget = max(0, MAX_FILES - len(tabular))
    docs_to_extract = doc_atts[:doc_budget]
    docs_over_cap = doc_atts[doc_budget:]

    workdir = _workdir_for(conversation_id)
    data_dir = os.path.join(workdir, 'data')

    files: list[dict] = []
    documents: list[dict] = []

    if tabular:
        os.makedirs(data_dir, exist_ok=True)
        seen_names: set[str] = set()
        # UploadModel.find_by_id (inside _read_upload_bytes) needs a bound session;
        # this runs on a background thread, so scope one for the byte reads.
        with db.session_scope():
            for att in tabular:
                upload_id = att.get('upload_id')
                raw = _read_upload_bytes(upload_id, user_id=user_id)
                if not raw:
                    logger.warning('data-analyzer: upload %s unreadable; skipping', upload_id)
                    continue
                ext = att.get('_ext') or _ext_of(att.get('name') or '')
                base = _safe_component(att.get('name') or f'data.{ext}')
                if '.' not in base:
                    base = f'{base}.{ext}'
                # De-dupe within this turn so two attachments named the same don't clobber.
                candidate, n = base, 2
                while candidate in seen_names:
                    stem, dot, suffix = base.rpartition('.')
                    candidate = f'{stem}_{n}.{suffix}' if dot else f'{base}_{n}'
                    n += 1
                seen_names.add(candidate)
                path = os.path.join(data_dir, candidate)
                with open(path, 'wb') as fh:
                    fh.write(raw)
                files.append({
                    'name': candidate,
                    'path': path,
                    'kind': _KIND_BY_EXT.get(ext, ext),
                })

    if docs_to_extract:
        os.makedirs(data_dir, exist_ok=True)
        for att in docs_to_extract:
            documents.append(_ingest_document(
                att, data_dir, user_id=user_id,
                workspace_id=workspace_id, project_id=project_id,
                status_cb=status_cb, stop_event=stop_event,
            ))

    for att in docs_over_cap:
        documents.append({
            'name': att.get('name') or att.get('filename') or 'document',
            'status': 'skipped',
            'reason': 'file limit',
        })

    # No new file this turn (or none readable) → reuse the conversation's dataset.
    if not files:
        files = _existing_dataset_files(data_dir)
    # Return a context when there's any data file OR any doc attachment this turn
    # (a lone PDF must still profile — its .extracted.txt lands in data/).
    if not files and not documents:
        return None

    profile = SandboxService.profile(
        workdir=workdir,
        timeout_s=int(settings.get('DATA_SANDBOX_TIMEOUT_S', 20) or 20) + 10,
        mem_mb=int(settings.get('DATA_SANDBOX_MEM_MB', 1024) or 1024),
        stop_event=stop_event,
    )

    preview_markdown = profile.get('preview_markdown', '')
    if documents:
        preview_markdown = preview_markdown + _documents_preview_section(documents)

    return DatasetContext(
        workdir=workdir,
        files=files,
        preview_markdown=preview_markdown,
        manifest=profile.get('manifest', []),
        documents=documents,
    )


def _dlp_block_extracted_text(
    text: str,
    *,
    user_id,
    workspace_id,
    project_id,
    feature: str = 'data_pdf_extract',
) -> Optional[str]:
    """Post-extract DLP fail-closed. Returns a safe reason string if blocked, else None.

    Mid-pipeline has no interactive confirm — ``require_confirm`` and ``block``
    both refuse the file. Empty text / missing workspace = allow.
    """
    if not text or not workspace_id:
        return None
    try:
        from app.services.dlp_gate import DLPBlockedError, gate
        with db.session_scope():
            gate(
                text=text,
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                source='chat',
                source_ref={'feature': feature},
                confirmed=False,
            )
    except DLPBlockedError:
        return 'content blocked by content safety policy'
    except Exception as exc:  # noqa: BLE001 — never crash ingestion on DLP infra
        logger.warning('data-analyzer: DLP gate error on extract: %s', exc)
        return None
    return None


def _ingest_document(att: dict, data_dir: str, *, user_id, workspace_id,
                     project_id, status_cb: Optional[Callable[[dict], None]],
                     stop_event=None
                     ) -> dict:
    """Extract ONE document attachment to ``<stem>.extracted.txt`` in ``data_dir``.

    Returns the report entry ``{'name', 'status', 'reason', 'target'}`` with status
    in ``ok | truncated | failed | budget_blocked | skipped``; ``target`` is the
    ACTUAL extracted filename on disk (``None`` on paths that wrote no file) so the
    preview reports the real hashed path. Never raises — every
    failure mode (unreadable bytes, oversized source, budget block, OCR error,
    empty transcription) maps to a status so the model can tell the user exactly
    which file couldn't be read.

    Session discipline (mirrors openrouter_service._record_usage's burst-and-
    remove): the byte read + cache lookups happen inside a short ``session_scope``
    that is LEFT before the blocking OpenRouter transcription HTTP call, so no
    pooled DB connection is pinned across the (multi-second) egress round-trip; a
    FRESH scope is opened afterwards only to write the transcription back.
    """
    original_name = att.get('name') or att.get('filename') or 'document'
    upload_id = att.get('upload_id')
    ext = att.get('_ext') or _ext_of(original_name)
    target_name = _doc_target_name(att)
    target_path = os.path.join(data_dir, target_name)

    # (2a) Already extracted into the workdir on a prior turn → reuse, but only if
    # the file is non-empty and meets the same minimum-char floor the fresh path
    # enforces. _write_text_file truncates-then-writes (non-atomic), so a crashed
    # prior turn can leave a 0-byte / sub-minimum file that still "exists" — treat
    # that as stale and re-extract rather than trusting it.
    if os.path.exists(target_path):
        try:
            if os.path.getsize(target_path) > 0:
                with open(target_path, 'r', encoding='utf-8', errors='replace') as fh:
                    _existing = fh.read()
                if len(_existing.strip()) >= _MIN_DOC_CHARS:
                    return {'name': original_name, 'status': 'ok', 'reason': None,
                            'target': target_name}
        except OSError:
            pass
        # stale/partial/empty → fall through and re-extract

    upload_max_bytes = int(settings.get('CHAT_UPLOAD_MAX_BYTES', 32 * 1024 * 1024))
    max_chars = int(settings.get('DOC_EXTRACT_MAX_CHARS', 200000))

    # Phase 1: read bytes + cached extraction inside ONE scope, then drop it
    # before any paid call. raw stays in memory; the pooled connection does not.
    raw: Optional[bytes] = None
    cached_text: Optional[str] = None
    cached_status: Optional[str] = None
    with db.session_scope():
        raw = _read_upload_bytes(upload_id, user_id=user_id)
        rec = None
        try:
            from app.models.upload import UploadModel
            rec = UploadModel.get_extracted_text_for_user(upload_id, user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning('data-analyzer: extracted-text lookup failed for %s: %s', upload_id, exc)
        if rec and rec.get('extracted_text'):
            cached_text = rec['extracted_text']
            cached_status = rec.get('extraction_status')

    if raw is None:
        logger.warning('data-analyzer: upload %s unreadable; skipping', upload_id)
        return {'name': original_name, 'status': 'failed', 'reason': 'file unreadable',
                'target': None}

    # (2b) Cache hit (office formats are populated at upload; PDFs/images after our
    # first pass). Write the data file straight from cache — no paid call.
    if cached_text:
        text, truncated = _cap_text(cached_text, max_chars)
        dlp_block = _dlp_block_extracted_text(
            text, user_id=user_id, workspace_id=workspace_id, project_id=project_id,
            feature='data_extract_cache',
        )
        if dlp_block:
            return {'name': original_name, 'status': 'failed', 'reason': dlp_block,
                    'target': None}
        _write_text_file(target_path, text)
        status = 'truncated' if (truncated or cached_status == 'truncated') else 'ok'
        return {'name': original_name, 'status': status, 'reason': None,
                'target': target_name}

    if len(raw) > upload_max_bytes:
        return {'name': original_name, 'status': 'failed', 'reason': 'file too large',
                'target': None}

    # Turn cancelled (client disconnect) before fresh extraction — skip the
    # (possibly PAID OCR) work entirely rather than billing for a discarded turn.
    # The SSE producer ends the turn as cancelled.
    if stop_event is not None and stop_event.is_set():
        return {'name': original_name, 'status': 'skipped', 'reason': 'cancelled',
                'target': None}

    # (2c) Fresh extraction.
    if status_cb is not None:
        try:
            status_cb({'phase': 'extracting', 'file': original_name})
        except Exception:  # noqa: BLE001 - progress callback must never break ingestion
            pass

    if ext in _DOC_EXTS_BACKEND:
        return _extract_backend_doc(
            raw, original_name, ext, target_path,
            upload_id=upload_id, user_id=user_id, max_chars=max_chars,
            workspace_id=workspace_id, project_id=project_id,
        )

    # PDF / image → paid OpenRouter transcription. Spend-gate BEFORE the call.
    # A budget breach blocks THIS file only — never propagate (we're mid-stream).
    # The Phase-1 scope is already closed; gate() does point-read DB lookups, so it
    # needs its OWN scope or it pins an unscoped pooled connection on this raw daemon
    # thread that never gets remove()d (idle-in-transaction leak, esp. on the early
    # BudgetExceededError return path).
    from app.services.spend_gate import BudgetExceededError, gate
    try:
        with db.session_scope():
            gate(user_id=user_id, workspace_id=workspace_id, project_id=project_id,
                 origin='web', feature='data_pdf_extract')
    except BudgetExceededError:
        return {'name': original_name, 'status': 'budget_blocked', 'reason': 'budget exceeded',
                'target': None}
    except Exception as exc:  # noqa: BLE001 - a gate fault must not crash ingestion
        logger.warning('data-analyzer: spend gate raised non-budget error: %s', exc)
        return {'name': original_name, 'status': 'failed', 'reason': 'gate error', 'target': None}

    if ext in _DOC_EXTS_PDF:
        from app.services.document_extraction_service import pdf_data_url
        content_part = {'type': 'file', 'file': {
            'filename': _safe_component(original_name),
            'file_data': pdf_data_url(raw),
        }}
        instruction = (
            'Return the complete text content of this document as markdown. '
            'Output ONLY the document text, no commentary.'
        )
    else:  # image
        mime = _IMAGE_MIME.get(ext, 'image/png')
        b64 = base64.b64encode(raw).decode('ascii')
        content_part = {'type': 'image_url', 'image_url': {
            'url': f'data:{mime};base64,{b64}',
        }}
        instruction = (
            'Transcribe all visible text and tables in this image as markdown. '
            'Tables as markdown tables. Output ONLY the transcription.'
        )

    text, reason = _llm_transcribe(
        content_part, instruction, user_id=user_id,
        workspace_id=workspace_id, project_id=project_id,
    )
    if reason:
        return {'name': original_name, 'status': 'failed', 'reason': reason, 'target': None}

    if len(text.strip()) < _MIN_DOC_CHARS:
        return {'name': original_name, 'status': 'failed',
                'reason': 'no readable text (scanned or illegible?)', 'target': None}

    capped, truncated = _cap_text(text, max_chars)

    # Post-extract DLP (fail-closed mid-pipeline — no interactive confirm).
    # Scans extracted text before cache/write so secrets aren't stored for reuse.
    dlp_block = _dlp_block_extracted_text(
        capped, user_id=user_id, workspace_id=workspace_id, project_id=project_id,
        feature='data_pdf_extract',
    )
    if dlp_block:
        return {'name': original_name, 'status': 'failed', 'reason': dlp_block, 'target': None}

    status = 'truncated' if truncated else 'ok'
    _write_text_file(target_path, capped)

    # Phase 2: cache the transcription back on the upload row in a FRESH scope so a
    # follow-up turn / re-attach skips the paid call. Best-effort.
    with db.session_scope():
        try:
            from app.models.upload import UploadModel
            UploadModel.set_extracted_text(upload_id, user_id, capped, len(capped), status)
        except Exception as exc:  # noqa: BLE001
            logger.warning('data-analyzer: extraction cache write failed for %s: %s', upload_id, exc)

    return {'name': original_name, 'status': status, 'reason': None, 'target': target_name}


def _extract_backend_doc(raw: bytes, original_name: str, ext: str,
                         target_path: str, *, upload_id, user_id,
                         max_chars: int, workspace_id=None, project_id=None) -> dict:
    """Extract an office/html document via document_extraction_service (no paid call).

    Writes the data file + caches the text on the upload row (FRESH scope) so a
    follow-up reuses it. document_extraction_service.extract_text returns the
    contract dict ``{'status','markdown','chars','truncated'}`` and never raises.
    """
    from app.services import document_extraction_service as des
    result = des.extract_text(
        raw,
        filename=_safe_component(original_name),
        mime_type='',
        extension=ext,
        max_chars=max_chars,
    )
    target_name = os.path.basename(target_path)
    text = result.get('markdown') or ''
    des_status = result.get('status')
    if des_status in ('unavailable', 'error') or len(text.strip()) < _MIN_DOC_CHARS:
        return {'name': original_name, 'status': 'failed',
                'reason': 'no readable text (scanned or illegible?)', 'target': None}

    dlp_block = _dlp_block_extracted_text(
        text, user_id=user_id, workspace_id=workspace_id, project_id=project_id,
        feature='data_doc_extract',
    )
    if dlp_block:
        return {'name': original_name, 'status': 'failed', 'reason': dlp_block,
                'target': None}

    status = 'truncated' if result.get('truncated') else 'ok'
    _write_text_file(target_path, text)
    with db.session_scope():
        try:
            from app.models.upload import UploadModel
            UploadModel.set_extracted_text(upload_id, user_id, text, len(text), status)
        except Exception as exc:  # noqa: BLE001
            logger.warning('data-analyzer: extraction cache write failed for %s: %s', upload_id, exc)
    return {'name': original_name, 'status': status, 'reason': None, 'target': target_name}


def _cap_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Clip ``text`` to ``max_chars`` with a trailing marker. Returns (text, truncated)."""
    if len(text) <= max_chars:
        return text, False
    dropped = len(text) - max_chars
    original_len = len(text)
    clipped = text[:max_chars] + f"\n\n[...truncated {dropped} of {original_len} characters...]"
    return clipped, True


def _write_text_file(path: str, text: str) -> None:
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)


_DOC_STATUS_LABEL = {
    'failed': 'EXTRACTION FAILED',
    'budget_blocked': 'SKIPPED (budget exceeded)',
    'skipped': 'SKIPPED',
    'truncated': 'truncated',
}


def _documents_preview_section(documents: list[dict]) -> str:
    """A '## Documents' markdown block listing every doc attachment + its status.

    Successes are one line each (``report.pdf → report.extracted.txt``); failures
    are explicit (``scan.pdf: EXTRACTION FAILED — no readable text...``) so the
    model can tell the user precisely which file couldn't be read.
    """
    lines = ['', '## Documents', '']
    for doc in documents:
        name = doc.get('name') or 'document'
        status = doc.get('status')
        reason = doc.get('reason')
        if status in ('ok', 'truncated'):
            stem = name.rsplit('.', 1)[0] if '.' in name else name
            suffix = ' (truncated)' if status == 'truncated' else ''
            # Use the REAL hashed on-disk filename (doc['target']); recomputing it
            # from the stem would mismatch the upload-id-hashed name written to disk.
            target = doc.get('target') or (_safe_component(stem) + '.extracted.txt')
            lines.append(f'- {name} → {target}{suffix}')
        else:
            label = _DOC_STATUS_LABEL.get(status, 'SKIPPED')
            tail = f' — {reason}' if reason else ''
            lines.append(f'- {name}: {label}{tail}')
    return '\n'.join(lines) + '\n'


def build_chart_payload(artifact: dict) -> dict:
    """Normalize a runner chart artifact to the frontend chart shape.

    Output: ``{type:'chart', kind, encoding:{x,y,series}, data:[...], title}``.
    Table artifacts (and anything already shaped) pass through unchanged.
    """
    if not isinstance(artifact, dict):
        return artifact
    if artifact.get('type') != 'chart':
        return artifact

    kind = str(artifact.get('kind') or 'bar').lower()
    enc = artifact.get('encoding') or {}
    if not isinstance(enc, dict):
        enc = {}
    data = artifact.get('data')
    if not isinstance(data, list):
        data = []

    return {
        'type': 'chart',
        'kind': kind,
        'encoding': {
            'x': enc.get('x'),
            'y': enc.get('y'),
            'series': enc.get('series'),
        },
        'data': data,
        'title': artifact.get('title'),
    }
