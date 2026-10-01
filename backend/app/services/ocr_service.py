"""OCR assistant — per-file extract via OpenRouter Gemini Flash Lite.

Images → vision ``image_url`` data URI.
PDFs → ``file`` part + ``file-parser`` engine ``native`` (Gemini-native, no page fee).

Sequential, fail-soft per file. Owner-scoped bytes only.
"""
from __future__ import annotations

import base64
import logging
import mimetypes
from typing import Any, Callable, Dict, List, Optional

from app.settings import settings
from app.models.upload import UploadModel
from app.prompts.ocr import (
    OCR_DEFAULT_USER_PROMPT,
    OCR_MAX_FILES,
    OCR_MODEL,
    OCR_SYSTEM_PROMPT,
)
from app.services.document_extraction_service import pdf_data_url
from app.services.openrouter_service import OpenRouterService, _read_upload_bytes

logger = logging.getLogger(__name__)

_IMAGE_EXTS = frozenset({"png", "jpg", "jpeg", "webp", "gif"})
_PDF_EXTS = frozenset({"pdf"})
_ALLOWED_EXTS = _IMAGE_EXTS | _PDF_EXTS


def _ext_of(row: dict) -> str:
    name = (row.get("original_name") or row.get("filename") or "").lower()
    if "." in name:
        return name.rsplit(".", 1)[-1]
    mime = (row.get("mime_type") or "").lower()
    if "pdf" in mime:
        return "pdf"
    if "png" in mime:
        return "png"
    if "jpeg" in mime or "jpg" in mime:
        return "jpg"
    if "webp" in mime:
        return "webp"
    if "gif" in mime:
        return "gif"
    return ""


def _content_text(result: dict) -> str:
    choices = result.get("choices") or []
    if not choices:
        return ""
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
    content = ""
    if isinstance(message, dict):
        content = message.get("content") or ""
    elif message is not None:
        content = getattr(message, "content", "") or ""
    if isinstance(content, list):
        content = "\n".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("text")
        )
    return (content or "").strip()


def _image_part(raw: bytes, mime: str) -> dict:
    if not mime or not mime.startswith("image/"):
        mime = "image/png"
    b64 = base64.b64encode(raw).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{b64}"},
    }


def _pdf_part(raw: bytes, filename: str) -> dict:
    return {
        "type": "file",
        "file": {
            "filename": filename or "document.pdf",
            "file_data": pdf_data_url(raw),
        },
    }


def extract_one(
    *,
    upload_id: str,
    user_id: str,
    prompt: str,
    workspace_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract from one owner-scoped upload. Never raises — returns error dict."""
    row = UploadModel.find_by_id_for_user(upload_id, user_id)
    if not row:
        return {
            "upload_id": upload_id,
            "original_name": None,
            "ok": False,
            "error": "upload not found",
            "content": None,
        }

    name = row.get("original_name") or row.get("filename") or upload_id
    ext = _ext_of(row)
    if ext not in _ALLOWED_EXTS:
        return {
            "upload_id": upload_id,
            "original_name": name,
            "ok": False,
            "error": f"unsupported type .{ext or '?'}",
            "content": None,
        }

    raw = _read_upload_bytes(upload_id, user_id=user_id)
    if not raw:
        return {
            "upload_id": upload_id,
            "original_name": name,
            "ok": False,
            "error": "file unreadable",
            "content": None,
        }

    user_text = (prompt or "").strip() or OCR_DEFAULT_USER_PROMPT
    plugins = None
    if ext in _PDF_EXTS:
        content_part = _pdf_part(raw, name if name.lower().endswith(".pdf") else f"{name}.pdf")
        plugins = [{"id": "file-parser", "pdf": {"engine": "native"}}]
    else:
        mime = row.get("mime_type") or mimetypes.guess_type(name)[0] or f"image/{ext}"
        content_part = _image_part(raw, mime)

    max_tokens = int(settings.get("DOC_EXTRACT_MAX_CHARS", 200000) // 3)
    max_tokens = max(1024, min(max_tokens, 32000))

    try:
        result = OpenRouterService.chat_completion(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    content_part,
                ],
            }],
            model=OCR_MODEL,
            system_prompt=OCR_SYSTEM_PROMPT,
            temperature=0.0,
            max_tokens=max_tokens,
            stream=False,
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            origin="web",
            feature="ocr",
            plugins=plugins,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ocr extract failed for %s: %s", upload_id, exc)
        return {
            "upload_id": upload_id,
            "original_name": name,
            "ok": False,
            "error": str(exc)[:200],
            "content": None,
        }

    if not isinstance(result, dict) or result.get("error"):
        err = (result or {}).get("error") if isinstance(result, dict) else None
        reason = ""
        if isinstance(err, dict):
            reason = str(err.get("message") or err.get("code") or "")[:120]
        elif err:
            reason = str(err)[:120]
        return {
            "upload_id": upload_id,
            "original_name": name,
            "ok": False,
            "error": reason or "extraction error",
            "content": None,
        }

    text = _content_text(result)
    if not text:
        return {
            "upload_id": upload_id,
            "original_name": name,
            "ok": False,
            "error": "empty model response",
            "content": None,
        }

    return {
        "upload_id": upload_id,
        "original_name": name,
        "ok": True,
        "error": None,
        "content": text,
    }


def extract_files(
    *,
    user_id: str,
    upload_ids: List[str],
    prompt: str = "",
    workspace_id: Optional[str] = None,
    project_id: Optional[str] = None,
    on_file_start: Optional[Callable[[int, int, str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> List[Dict[str, Any]]:
    """Sequential extract for up to ``OCR_MAX_FILES`` uploads."""
    ids = [str(u).strip() for u in (upload_ids or []) if u]
    # Dedupe preserving order
    seen = set()
    ordered: List[str] = []
    for uid in ids:
        if uid in seen:
            continue
        seen.add(uid)
        ordered.append(uid)
    ordered = ordered[:OCR_MAX_FILES]

    results: List[Dict[str, Any]] = []
    total = len(ordered)
    for i, uid in enumerate(ordered):
        if should_stop and should_stop():
            break
        if on_file_start:
            on_file_start(i + 1, total, uid)
        results.append(
            extract_one(
                upload_id=uid,
                user_id=user_id,
                prompt=prompt,
                workspace_id=workspace_id,
                project_id=project_id,
            )
        )
    return results
