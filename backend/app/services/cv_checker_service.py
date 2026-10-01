"""CV checker — extract text + structured OpenRouter analysis."""
from __future__ import annotations

import json
import logging
import mimetypes
import re
from typing import Any, Dict, Optional

from app.models.upload import UploadModel
from app.prompts.cv_checker import (
    BIAS_BLOCK,  # noqa: F401 — available for tests
    CHECKLIST_STATUSES,
    CV_CHECKER_FEATURE,
    CV_CHECKER_MODEL,
    DENYLIST_KEYS,
    DIMENSION_WHITELIST,
    DISCLAIMER_EN,
    DISCLAIMER_FA,
    build_system_prompt,
    build_user_message,
)
from app.services.document_extraction_service import extract_text
from app.services.openrouter_service import OpenRouterService, _read_upload_bytes
from app.services.ocr_service import _content_text, _ext_of, _image_part, _pdf_part
from app.settings import settings

logger = logging.getLogger(__name__)

_DOC_EXTS = frozenset({"pdf", "docx", "doc", "txt", "md"})
_IMAGE_EXTS = frozenset({"png", "jpg", "jpeg", "webp"})


def _parse_json(raw: str) -> dict:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start : end + 1]
    return json.loads(raw)


def _clamp_score(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        n = int(round(float(val)))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, n))


def _strip_bias(result: dict) -> dict:
    if not isinstance(result, dict):
        return {}
    clean = {k: v for k, v in result.items() if k not in DENYLIST_KEYS}
    dims = clean.get("dimensions")
    if isinstance(dims, list):
        clean["dimensions"] = [
            d for d in dims
            if isinstance(d, dict) and d.get("id") in DIMENSION_WHITELIST
        ]
    return clean


def _normalize_hr_fields(result: dict) -> dict:
    """Coerce HR checklist + interview Qs; clamp scores. Safe on partial dicts."""
    if not isinstance(result, dict):
        return {}
    out = dict(result)

    out["overall_score"] = _clamp_score(out.get("overall_score"))
    out["match_score"] = _clamp_score(out.get("match_score"))

    dims = out.get("dimensions")
    if isinstance(dims, list):
        norm_dims = []
        for d in dims:
            if not isinstance(d, dict) or d.get("id") not in DIMENSION_WHITELIST:
                continue
            row = dict(d)
            row["score"] = _clamp_score(row.get("score"))
            row["label"] = str(row.get("label") or row.get("id") or "")[:120]
            row["notes"] = str(row.get("notes") or "")[:800]
            norm_dims.append(row)
        out["dimensions"] = norm_dims
    else:
        out["dimensions"] = []

    checklist: list = []
    raw_cl = out.get("must_have_checklist")
    if isinstance(raw_cl, list):
        for item in raw_cl[:12]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("item") or item.get("label") or "").strip()
            if not label:
                continue
            status = str(item.get("status") or "").strip().lower()
            if status not in CHECKLIST_STATUSES:
                status = "partial"
            checklist.append({
                "item": label[:240],
                "status": status,
                "evidence": str(item.get("evidence") or "").strip()[:400],
            })
    out["must_have_checklist"] = checklist

    questions: list = []
    raw_q = out.get("interview_questions")
    if isinstance(raw_q, list):
        for item in raw_q[:10]:
            if isinstance(item, str):
                q = item.strip()
                if q:
                    questions.append({"question": q[:500], "rationale": ""})
                continue
            if not isinstance(item, dict):
                continue
            q = str(item.get("question") or item.get("q") or "").strip()
            if not q:
                continue
            questions.append({
                "question": q[:500],
                "rationale": str(item.get("rationale") or item.get("why") or "").strip()[:400],
            })
    out["interview_questions"] = questions

    kw = out.get("keywords")
    if not isinstance(kw, dict):
        out["keywords"] = {"present": [], "missing": []}
    else:
        present = kw.get("present") if isinstance(kw.get("present"), list) else []
        missing = kw.get("missing") if isinstance(kw.get("missing"), list) else []
        out["keywords"] = {
            "present": [str(x).strip() for x in present if str(x).strip()][:40],
            "missing": [str(x).strip() for x in missing if str(x).strip()][:40],
        }

    for key in ("strengths", "gaps", "risks_or_questions", "language_notes"):
        val = out.get(key)
        if not isinstance(val, list):
            out[key] = []
        else:
            out[key] = [str(x).strip() for x in val if str(x).strip()][:20]

    rec = str(out.get("recommendation") or "n_a").strip().lower()
    if rec not in {"advance", "maybe", "pass", "n_a"}:
        rec = "n_a"
    out["recommendation"] = rec

    return out


_EMPTY_RESULT: Dict[str, Any] = {
    "summary": "",
    "overall_score": None,
    "recommendation": "n_a",
    "match_score": None,
    "dimensions": [],
    "strengths": [],
    "gaps": [],
    "risks_or_questions": [],
    "must_have_checklist": [],
    "interview_questions": [],
    "keywords": {"present": [], "missing": []},
    "improvements": [],
    "rewritten_bullets": [],
    "language_notes": [],
    "bias_check": {"ignored_attributes_mentioned": False, "note": ""},
}


def load_cv_text(*, upload_id: str, user_id: str) -> tuple[str, list]:
    """Return (text, multimodal content parts for vision/pdf fallback)."""
    row = UploadModel.find_by_id_for_user(upload_id, user_id)
    if not row:
        raise ValueError("cv upload not found")
    name = row.get("original_name") or row.get("filename") or upload_id
    ext = _ext_of(row)

    meta = UploadModel.get_extracted_text_for_user(upload_id, user_id) or {}
    cached = (meta.get("extracted_text") or "").strip()
    if cached:
        return cached, []

    raw = _read_upload_bytes(upload_id, user_id=user_id)
    if not raw:
        raise ValueError("cv file unreadable")

    # Local extract for office/text
    if ext in {"docx", "doc", "txt", "md", "csv"}:
        max_chars = int(settings.get("DOC_EXTRACT_MAX_CHARS", 200000))
        try:
            out = extract_text(
                raw,
                filename=name,
                mime_type=row.get("mime_type") or "",
                extension=ext,
                max_chars=max_chars,
            )
            text = (out.get("markdown") or "").strip()
            if text:
                return text, []
        except Exception as exc:  # noqa: BLE001
            logger.info("cv local extract failed: %s", exc)

    parts: list = []
    if ext in _IMAGE_EXTS:
        mime = row.get("mime_type") or mimetypes.guess_type(name)[0] or f"image/{ext}"
        parts.append(_image_part(raw, mime))
        return "", parts
    if ext == "pdf":
        parts.append(_pdf_part(raw, name if name.lower().endswith(".pdf") else f"{name}.pdf"))
        return "", parts

    raise ValueError(f"unsupported CV type .{ext or '?'}")


def load_jd_text(*, jd_text: str, jd_upload_id: Optional[str], user_id: str) -> str:
    parts = []
    if (jd_text or "").strip():
        parts.append(jd_text.strip()[:50000])
    if jd_upload_id:
        meta = UploadModel.get_extracted_text_for_user(jd_upload_id, user_id) or {}
        t = (meta.get("extracted_text") or "").strip()
        if t:
            parts.append(t[:50000])
        else:
            row = UploadModel.find_by_id_for_user(jd_upload_id, user_id)
            if row:
                raw = _read_upload_bytes(jd_upload_id, user_id=user_id)
                if raw:
                    try:
                        out = extract_text(
                            raw,
                            filename=row.get("original_name") or "jd",
                            mime_type=row.get("mime_type") or "",
                            extension=_ext_of(row),
                            max_chars=50000,
                        )
                        t2 = (out.get("markdown") or "").strip()
                        if t2:
                            parts.append(t2[:50000])
                    except Exception:  # noqa: BLE001
                        pass
    return "\n\n".join(parts)


def run_check(
    *,
    mode: str,
    lang: str,
    cv_upload_id: str,
    jd_text: str = "",
    jd_upload_id: Optional[str] = None,
    focus: str = "",
    workspace_id: Optional[str] = None,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    cv_text, media_parts = load_cv_text(upload_id=cv_upload_id, user_id=user_id)
    jd = load_jd_text(jd_text=jd_text, jd_upload_id=jd_upload_id, user_id=user_id)
    has_jd = bool(jd.strip())

    sys_p = build_system_prompt(mode=mode, lang=lang, has_jd=has_jd)
    user_text = build_user_message(mode=mode, cv_text=cv_text or "(see attached)", jd_text=jd, focus=focus)

    content: Any
    plugins = None
    if media_parts:
        content = [{"type": "text", "text": user_text}, *media_parts]
        if any(p.get("type") == "file" for p in media_parts):
            plugins = [{"id": "file-parser", "pdf": {"engine": "native"}}]
    else:
        content = user_text

    result = OpenRouterService.chat_completion(
        messages=[{"role": "user", "content": content}],
        model=CV_CHECKER_MODEL,
        system_prompt=sys_p,
        temperature=0.2,
        max_tokens=6000,
        stream=False,
        user_id=user_id,
        feature=CV_CHECKER_FEATURE,
        workspace_id=workspace_id,
        project_id=project_id,
        origin="web",
        plugins=plugins,
        timeout=120,
    )
    raw = _content_text(result)
    try:
        parsed = _normalize_hr_fields(_strip_bias(_parse_json(raw)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("cv_checker json parse failed: %s", exc)
        parsed = {
            **_EMPTY_RESULT,
            "summary": raw[:2000] if raw else "Analysis failed to parse.",
            "bias_check": {"ignored_attributes_mentioned": False, "note": "parse_error"},
        }

    if not has_jd:
        parsed["match_score"] = None

    disclaimer = DISCLAIMER_FA if lang != "en" else DISCLAIMER_EN
    return {
        "result": parsed,
        "mode": mode,
        "lang": lang,
        "disclaimer": disclaimer,
        "disclaimer_fa": DISCLAIMER_FA,
        "disclaimer_en": DISCLAIMER_EN,
        "meta": {"model": CV_CHECKER_MODEL, "has_jd": has_jd},
    }
