"""Contract risk review via Gemini Flash Lite."""
from __future__ import annotations

import json
import logging
import mimetypes
import re
from typing import Any, Dict, List, Optional

from app.models.upload import UploadModel
from app.prompts.contract_review import (
    CONTRACT_FEATURE,
    CONTRACT_MAX_FILES,
    CONTRACT_MODEL,
    DISCLAIMER_EN,
    DISCLAIMER_FA,
    build_system_prompt,
    build_user_message,
)
from app.services.openrouter_service import OpenRouterService, _read_upload_bytes
from app.services.ocr_service import _content_text, _ext_of, _image_part, _pdf_part

logger = logging.getLogger(__name__)

_ALLOWED = frozenset({"pdf", "png", "jpg", "jpeg", "webp"})


def _parse_json(raw: str) -> dict:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start : end + 1]
    return json.loads(raw)


def run_review(
    *,
    upload_ids: List[str],
    notes: str = "",
    lang: str = "fa",
    workspace_id: Optional[str] = None,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    ids = [str(u).strip() for u in upload_ids if u][:CONTRACT_MAX_FILES]
    if not ids:
        raise ValueError("upload_ids required")

    media: list = []
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
        if ext == "pdf":
            media.append(_pdf_part(raw, name if name.lower().endswith(".pdf") else f"{name}.pdf"))
            plugins = [{"id": "file-parser", "pdf": {"engine": "native"}}]
        else:
            mime = row.get("mime_type") or mimetypes.guess_type(name)[0] or f"image/{ext}"
            media.append(_image_part(raw, mime))

    if not media:
        raise ValueError("no readable owned contract files")

    user_text = build_user_message(notes=notes)
    content = [{"type": "text", "text": user_text}, *media]
    result = OpenRouterService.chat_completion(
        messages=[{"role": "user", "content": content}],
        model=CONTRACT_MODEL,
        system_prompt=build_system_prompt(lang=lang),
        temperature=0.2,
        max_tokens=8000,
        stream=False,
        user_id=user_id,
        feature=CONTRACT_FEATURE,
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
        logger.warning("contract json parse failed: %s", exc)
        parsed = {
            "summary": raw[:3000] if raw else "Review failed to parse.",
            "risk_matrix": [],
            "key_clauses": [],
            "open_questions": [],
            "red_flags": [],
        }

    return {
        "disclaimer": {"fa": DISCLAIMER_FA, "en": DISCLAIMER_EN},
        "summary": parsed.get("summary") or "",
        "risk_matrix": parsed.get("risk_matrix") or [],
        "key_clauses": parsed.get("key_clauses") or [],
        "open_questions": parsed.get("open_questions") or [],
        "red_flags": parsed.get("red_flags") or [],
        "lang": lang if lang in ("fa", "en") else "fa",
        "model": CONTRACT_MODEL,
    }
