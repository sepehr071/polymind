"""Tender / RFQ analyze service."""
from __future__ import annotations

import json
import logging
import mimetypes
import re
from typing import Any, Dict, List, Optional

from app.models.upload import UploadModel
from app.prompts.tender import (
    DISCLAIMER_EN,
    DISCLAIMER_FA,
    TENDER_FEATURE,
    TENDER_MAX_FILES,
    TENDER_MODEL,
    TENDER_MODES,
    build_system_prompt,
    build_user_message,
)
from app.services.document_extraction_service import extract_text
from app.services.openrouter_service import OpenRouterService, _read_upload_bytes
from app.services.ocr_service import _content_text, _ext_of, _image_part, _pdf_part
from app.settings import settings

logger = logging.getLogger(__name__)

_ALLOWED = frozenset({"pdf", "png", "jpg", "jpeg", "webp", "docx", "doc", "txt"})


def _parse_json(raw: str) -> dict:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start : end + 1]
    return json.loads(raw)


def outline_seed_from_result(result: dict) -> dict:
    """FE sessionStorage handoff payload for presentations."""
    title = (result.get("title") or "Tender pack").strip()
    bullets = []
    for row in (result.get("compliance_matrix") or [])[:12]:
        if not isinstance(row, dict):
            continue
        req = (row.get("requirement") or "").strip()
        st = row.get("status") or ""
        if req:
            bullets.append(f"[{st}] {req}"[:200])
    summary = (result.get("summary") or "").strip()
    risks = result.get("risks") or []
    notes = summary
    if risks:
        notes += "\n\n## Risks\n" + "\n".join(f"- {r}" for r in risks[:10])
    return {
        "topic": title,
        "audience": "tender",
        "language": result.get("lang") or "fa",
        "notes_markdown": notes[:8000],
        "bullets": bullets,
    }


def run_analyze(
    *,
    upload_ids: List[str],
    notes: str = "",
    mode: str = "tender",
    lang: str = "fa",
    currency_unit: str = "toman",
    workspace_id: Optional[str] = None,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    mode = mode if mode in TENDER_MODES else "tender"
    currency_unit = "rial" if currency_unit == "rial" else "toman"
    lang = "en" if lang == "en" else "fa"
    ids = [str(u).strip() for u in upload_ids if u][:TENDER_MAX_FILES]
    if not ids:
        raise ValueError("upload_ids required")

    media: list = []
    text_chunks: list[str] = []
    plugins = None
    for uid in ids:
        row = UploadModel.find_by_id_for_user(uid, user_id)
        if not row:
            continue
        ext = _ext_of(row)
        if ext not in _ALLOWED:
            continue
        raw = _read_upload_bytes(uid, user_id=user_id)
        if not raw:
            continue
        name = row.get("original_name") or row.get("filename") or uid
        if ext in {"docx", "doc", "txt"}:
            meta = UploadModel.get_extracted_text_for_user(uid, user_id) or {}
            t = (meta.get("extracted_text") or "").strip()
            if not t:
                try:
                    out = extract_text(
                        raw,
                        filename=name,
                        mime_type=row.get("mime_type") or "",
                        extension=ext,
                        max_chars=int(settings.get("DOC_EXTRACT_MAX_CHARS", 200000)),
                    )
                    t = (out.get("markdown") or "").strip()
                except Exception:
                    t = ""
            if t:
                text_chunks.append(t)
            continue
        if ext == "pdf":
            media.append(_pdf_part(raw, name if name.lower().endswith(".pdf") else f"{name}.pdf"))
            plugins = [{"id": "file-parser", "pdf": {"engine": "native"}}]
        else:
            mime = row.get("mime_type") or mimetypes.guess_type(name)[0] or f"image/{ext}"
            media.append(_image_part(raw, mime))

    if not media and not text_chunks:
        raise ValueError("no readable owned tender files")

    user_text = build_user_message(notes=notes, mode=mode)
    if text_chunks:
        user_text += "\n\n=== Document text ===\n" + "\n\n---\n\n".join(text_chunks)[:80000]

    content: Any = user_text
    if media:
        content = [{"type": "text", "text": user_text}, *media]

    result = OpenRouterService.chat_completion(
        messages=[{"role": "user", "content": content}],
        model=TENDER_MODEL,
        system_prompt=build_system_prompt(lang=lang, mode=mode, currency_unit=currency_unit),
        temperature=0.2,
        max_tokens=10000,
        stream=False,
        user_id=user_id,
        feature=TENDER_FEATURE,
        workspace_id=workspace_id,
        project_id=project_id,
        origin="web",
        plugins=plugins,
        timeout=180,
    )
    raw = _content_text(result)
    try:
        parsed = _parse_json(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("tender json parse failed: %s", exc)
        parsed = {
            "title": "",
            "summary": raw[:3000] if raw else "Analyze failed to parse.",
            "deadlines": [],
            "compliance_matrix": [],
            "cover_letter_fa": "",
            "cover_letter": "",
            "questions": [],
            "risks": [],
        }

    pack = {
        "mode": mode,
        "title": parsed.get("title") or "",
        "summary": parsed.get("summary") or "",
        "deadlines": parsed.get("deadlines") or [],
        "compliance_matrix": parsed.get("compliance_matrix") or [],
        "cover_letter_fa": parsed.get("cover_letter_fa") or "",
        "cover_letter": parsed.get("cover_letter") or "",
        "questions": parsed.get("questions") or [],
        "risks": parsed.get("risks") or [],
        "currency_unit_pref": currency_unit,
        "model": TENDER_MODEL,
        "lang": lang,
        "disclaimer": {"fa": DISCLAIMER_FA, "en": DISCLAIMER_EN},
    }
    return pack
