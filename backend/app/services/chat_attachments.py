"""Chat attachment helpers shared by chat + agent routers.

Ownership filter, data-file detection, and DLP attachment text extraction.
Moved out of the fat chat router so agent (and tests) do not import routers.
"""
from __future__ import annotations

import logging

from app.models.upload import UploadModel

logger = logging.getLogger(__name__)

# Data-mode attachments the sandbox reads off disk — their extracted text/bytes
# must NOT be injected into the chat payload (the model gets a compact preview +
# the sandbox has the real data). Tabular files would leak their giant TSV;
# documents (PDF/office/images) would re-pay native OCR/vision EVERY round (the
# data flow extracts them ONCE into the workdir instead).
#
# MUST stay a SUPERSET of what ``data_analysis_service`` ingests — cross-ref both
# its tabular set AND ``data_analysis_service.DOC_EXTS``: anything prepare_dataset
# pulls into the workdir has to be stripped here too, else its full text/bytes
# leak into the prompt (TSV bloat) or double-bill OCR. These strips run ONLY on
# the data-mode paths (producer + regen) — never on normal chat.
DATA_FILE_EXTS = {
    # tabular (mirror data_analysis_service tabular set)
    'csv', 'tsv', 'xlsx', 'xls', 'xlsm', 'parquet', 'json', 'jsonl',
    'txt', 'text',
    # documents the data flow extracts off disk (mirror DOC_EXTS) — strip so the
    # native PDF / office / image payload never reaches the model per round.
    'pdf', 'docx', 'pptx', 'html', 'htm', 'md', 'xml',
    'png', 'jpg', 'jpeg', 'webp',
}


def is_data_attachment(att: dict) -> bool:
    """True when an attachment is a data-mode file the sandbox ingests off disk."""
    if not isinstance(att, dict):
        return False
    if att.get('is_data'):
        return True
    name = (att.get('name') or att.get('filename') or '').lower()
    ext = name.rsplit('.', 1)[-1] if '.' in name else ''
    if ext in DATA_FILE_EXTS:
        return True
    mime = (att.get('mime_type') or '').lower()
    return (
        'csv' in mime or 'spreadsheet' in mime or 'excel' in mime
        or mime in ('application/json', 'text/tab-separated-values')
        or 'parquet' in mime
        or mime == 'application/pdf'
        or mime.startswith('image/')
    )


def filter_owned_attachments(attachments, user_id):
    """Drop any attachment carrying a foreign / unknown ``upload_id``.

    The attachments array is taken VERBATIM from the request body, so a caller
    can put a victim's ``upload_id`` in it to exfil their file (the formatter /
    data-analyzer would otherwise read its bytes/text). This rejects, at the
    send boundary, any non-empty ``upload_id`` not owned by the sender — a
    foreign id is hostile, so dropping it is safe. Attachments with no
    ``upload_id`` (pure inline data: payloads) pass through; the formatter still
    owner-scopes any byte reads downstream.
    """
    if not attachments:
        return attachments
    kept = []
    for att in attachments:
        if not isinstance(att, dict):
            continue
        upload_id = att.get('upload_id')
        if upload_id and UploadModel.find_by_id_for_user(upload_id, user_id) is None:
            logger.warning(
                'dropping attachment with foreign/unknown upload_id %s from user %s',
                upload_id, user_id,
            )
            continue
        kept.append(att)
    return kept

def attachment_text_for_dlp(attachments: list, user_id=None) -> str:
    """Collect extractable attachment text for a combined DLP scan.

    NEVER trusts client-supplied ``extracted_text`` (spoof / IDOR). Only
    owner-scoped ``UploadModel.get_extracted_text_for_user`` is used — same
    source as ``POST /dlp/scan`` and OpenRouter formatting.

    ``user_id`` is required for any upload-backed text; without it returns ''.
    """
    parts: list[str] = []
    if user_id is None:
        return ""
    for att in attachments or []:
        if not isinstance(att, dict):
            continue
        # Prefer turn-local server redaction (set by chat gate); never client text.
        server_txt = att.get("_dlp_extracted_text")
        if server_txt:
            parts.append(str(server_txt))
            continue
        upload_id = att.get("upload_id") or att.get("id")
        if not upload_id:
            continue
        try:
            rec = UploadModel.get_extracted_text_for_user(upload_id, user_id)
        except Exception:  # noqa: BLE001 — never let lookup kill the gate
            rec = None
        if rec and rec.get("extracted_text"):
            parts.append(str(rec["extracted_text"]))
    return "\n\n".join(parts)


def load_attachment_extracted_text(att: dict, user_id) -> str:
    """Owner-scoped extract for one attachment dict (empty if none / not owned)."""
    if not isinstance(att, dict) or user_id is None:
        return ""
    if att.get("_dlp_extracted_text"):
        return str(att["_dlp_extracted_text"])
    upload_id = att.get("upload_id") or att.get("id")
    if not upload_id:
        return ""
    try:
        rec = UploadModel.get_extracted_text_for_user(upload_id, user_id)
    except Exception:  # noqa: BLE001
        return ""
    if rec and rec.get("extracted_text"):
        return str(rec["extracted_text"])
    return ""


