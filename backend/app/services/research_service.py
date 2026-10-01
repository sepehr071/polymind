"""Deep research via allowlisted OpenRouter models."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.models.upload import UploadModel
from app.prompts.research import (
    MODE_DEFAULT_MODEL,
    RESEARCH_FEATURE,
    RESEARCH_MAX_UPLOADS,
    RESEARCH_MODEL_IDS,
    RESEARCH_MODELS,
    RESEARCH_TIMEOUT_S,
    build_system_prompt,
    build_user_message,
)
from app.services.document_extraction_service import extract_text
from app.services.openrouter_service import OpenRouterService, _read_upload_bytes
from app.services.ocr_service import _content_text, _ext_of, _image_part, _pdf_part
from app.services.presentation_service import assemble_source_text
from app.settings import settings

logger = logging.getLogger(__name__)

# "1. **عنوان**" / "2. **Executive summary**" → "## عنوان" (UI was a dense wall of text)
_NUMBERED_BOLD_HEADING = re.compile(
    r"(?m)^[ \t]*(?:\d+[\.\)]|[۰-۹]+[\.\)])\s*\*\*(.+?)\*\*\s*$"
)
_URL_RE = re.compile(r"https?://[^\s\)\]\>\"'<>]+", re.I)
# Sources section heading (FA + EN)
_SOURCES_HEAD = re.compile(
    r"(?im)^##\s*(?:منابع|sources|references)\s*$"
)


def resolve_model(*, mode: str, model_id: Optional[str]) -> str:
    if model_id:
        mid = str(model_id).strip()
        if mid not in RESEARCH_MODEL_IDS:
            raise ValueError(f"model not allowlisted: {mid}")
        return mid
    default = MODE_DEFAULT_MODEL.get(mode)
    if not default:
        raise ValueError(f"invalid mode: {mode}")
    return default


def model_catalog() -> List[dict]:
    out = []
    for mid, meta in RESEARCH_MODELS.items():
        out.append({
            "id": mid,
            "tier": meta["tier"],
            "supports_files": meta["supports_files"],
            "cost_band": meta["cost_band"],
            "native_search": meta["native_search"],
        })
    return out


def _strip_url_trail(url: str) -> str:
    return (url or "").rstrip(".,;:)]}»\"'")


_DOMAIN_ONLY = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$", re.I)


def _is_grounding_redirect(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return (
        "vertexaisearch.cloud.google.com" in host
        or host.endswith("googleusercontent.com")
    )


def _canonicalize_citation_url(url: str, title: str = "") -> tuple[str, str]:
    """Prefer real domain/URL over Vertex grounding redirect wrappers.

    Gemini web_search often returns ``vertexaisearch.cloud.google.com/grounding-api-redirect/...``
    with the real domain only in ``title``. Never store the redirect host as the
    human title.
    """
    url = _strip_url_trail((url or "").strip())
    title = (title or "").strip()
    if not url:
        return url, title

    if _is_grounding_redirect(url):
        # Real https in title?
        m = _URL_RE.search(title)
        if m and not _is_grounding_redirect(m.group(0)):
            return _strip_url_trail(m.group(0)), title
        # Bare domain in title → link site root (article path lost; displayable)
        if _DOMAIN_ONLY.match(title):
            return f"https://{title.lower()}", title.lower()
        # Keep redirect for click-through but blank title if it would show vertex host
        if not title or _is_grounding_redirect(title) or "grounding-api-redirect" in title:
            try:
                host = urlparse(url).hostname or ""
            except Exception:
                host = ""
            if host and _is_grounding_redirect(url):
                title = ""  # FE shows generic "Source" rather than vertex host
        return url, title

    if not title or _is_grounding_redirect(title):
        try:
            title = (urlparse(url).hostname or "").replace("www.", "") or title
        except Exception:
            pass
    return url, title


def normalize_report_md(text: str) -> str:
    """Turn numbered-bold section labels into real ## headings for the reader."""
    if not (text or "").strip():
        return text or ""
    return _NUMBERED_BOLD_HEADING.sub(r"## \1", text)


def citations_from_report_md(report_md: str) -> List[dict]:
    """Fallback: pull https URLs from the ## منابع / ## Sources section."""
    if not (report_md or "").strip():
        return []
    m = _SOURCES_HEAD.search(report_md)
    body = report_md[m.end():] if m else report_md
    # If we found a sources head, stop at next ## section
    if m:
        nxt = re.search(r"(?m)^##\s+\S", body)
        if nxt:
            body = body[: nxt.start()]
    seen: set[str] = set()
    out: List[dict] = []
    for line in body.splitlines():
        urls = _URL_RE.findall(line)
        if not urls:
            continue
        url = _strip_url_trail(urls[0])
        if not url or url in seen:
            continue
        seen.add(url)
        # Title = line without the URL, cleaned
        title = _URL_RE.sub("", line).strip(" -\t*—–|")
        title = re.sub(r"^\d+[\.\)]\s*", "", title).strip()
        if not title:
            try:
                title = urlparse(url).netloc or url
            except Exception:
                title = url
        out.append({
            "index": len(out) + 1,
            "url": url,
            "title": title[:200],
            "snippet": None,
        })
    return out


def normalize_citations(result: dict, report_md: str = "") -> List[dict]:
    """Parse annotations + top-level citations; fall back to URLs in report Sources."""
    seen: set[str] = set()
    out: List[dict] = []

    def _add(url: str, title: str = "", snippet: str | None = None):
        url, title = _canonicalize_citation_url(url, title)
        if not url or url in seen:
            return
        if not url.startswith(("http://", "https://")):
            return
        # Prefer non-redirect when same domain already present
        if _is_grounding_redirect(url):
            # Skip if we already have a real URL for this title/domain
            for existing in out:
                et = (existing.get("title") or "").lower()
                if title and et == title.lower() and not _is_grounding_redirect(existing.get("url") or ""):
                    return
        seen.add(url)
        if not title:
            try:
                host = (urlparse(url).hostname or "").replace("www.", "")
                # Never fall back to vertex host as title
                title = "" if _is_grounding_redirect(url) else (host or url)
            except Exception:
                title = "" if _is_grounding_redirect(url) else url
        out.append({
            "index": len(out) + 1,
            "url": url,
            "title": title,
            "snippet": snippet,
        })

    def _ingest_ann(ann: dict):
        if not isinstance(ann, dict):
            return
        if ann.get("type") in ("url_citation", "url"):
            uc = ann.get("url_citation") or ann
            _add(
                uc.get("url") or ann.get("url") or "",
                uc.get("title") or "",
                uc.get("content") or uc.get("snippet"),
            )
        elif ann.get("url"):
            _add(ann.get("url"), ann.get("title") or "")

    choices = result.get("choices") or []
    if choices:
        msg = choices[0].get("message") or {}
        for ann in msg.get("annotations") or []:
            _ingest_ann(ann)

    # openrouter_service also hoists message annotations to top-level
    for ann in result.get("annotations") or []:
        _ingest_ann(ann)

    for c in result.get("citations") or []:
        if isinstance(c, str):
            _add(c)
        elif isinstance(c, dict):
            _add(c.get("url") or c.get("link") or "", c.get("title") or "", c.get("snippet"))

    for sr in result.get("search_results") or []:
        if isinstance(sr, dict):
            _add(sr.get("url") or "", sr.get("title") or "", sr.get("snippet") or sr.get("content"))

    if not out and report_md:
        for c in citations_from_report_md(report_md):
            _add(c.get("url") or "", c.get("title") or "", c.get("snippet"))

    return out


def _gather_context(
    *,
    user_id: str,
    upload_ids: List[str],
    knowledge_ids: List[str],
    supports_files: bool,
) -> tuple[str, list, list]:
    """Returns (text_context, media_parts, plugins)."""
    text = assemble_source_text(
        user_id=user_id,
        upload_ids=upload_ids if not supports_files else [],
        knowledge_ids=knowledge_ids,
    )
    media: list = []
    plugins = None
    if supports_files and upload_ids:
        for uid in upload_ids[:RESEARCH_MAX_UPLOADS]:
            row = UploadModel.find_by_id_for_user(uid, user_id)
            if not row:
                continue
            raw = _read_upload_bytes(uid, user_id=user_id)
            if not raw:
                continue
            name = row.get("original_name") or row.get("filename") or uid
            ext = _ext_of(row)
            if ext == "pdf":
                media.append(_pdf_part(raw, name if name.lower().endswith(".pdf") else f"{name}.pdf"))
                plugins = [{"id": "file-parser", "pdf": {"engine": "native"}}]
            elif ext in {"png", "jpg", "jpeg", "webp"}:
                mime = row.get("mime_type") or f"image/{ext}"
                media.append(_image_part(raw, mime))
            else:
                meta = UploadModel.get_extracted_text_for_user(uid, user_id) or {}
                t = (meta.get("extracted_text") or "").strip()
                if not t and raw:
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
                    text = (text + "\n\n" + t)[:80000]
    return text, media, plugins


def run_research(
    *,
    query: str,
    mode: str,
    model_id: Optional[str] = None,
    lang: str = "fa",
    focus: str = "",
    upload_ids: Optional[List[str]] = None,
    knowledge_ids: Optional[List[str]] = None,
    workspace_id: Optional[str] = None,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    stop_event: Any = None,
) -> Dict[str, Any]:
    """Run a deep-research completion.

    ``stop_event`` is cooperative only: checked before context assembly and
    before the blocking OpenRouter call. An in-flight HTTP request cannot be
    aborted mid-flight (stream permit still releases on SSE close).
    """
    upload_ids = [str(u).strip() for u in (upload_ids or []) if u][:RESEARCH_MAX_UPLOADS]
    knowledge_ids = [str(k).strip() for k in (knowledge_ids or []) if k][:20]

    mid = resolve_model(mode=mode, model_id=model_id)
    meta = RESEARCH_MODELS[mid]
    supports_files = bool(meta["supports_files"])

    if upload_ids and not supports_files:
        # Prefer text extract when model has no file modality
        pass

    if upload_ids and mode == "deep_files" and not supports_files:
        raise ValueError("selected model does not support files")

    if stop_event is not None and stop_event.is_set():
        raise RuntimeError("research cancelled")

    ctx, media, plugins = _gather_context(
        user_id=user_id,
        upload_ids=upload_ids,
        knowledge_ids=knowledge_ids,
        supports_files=supports_files and bool(upload_ids),
    )

    # If files requested but model lacks support → inject extracts only
    if upload_ids and not supports_files:
        ctx2, _, _ = _gather_context(
            user_id=user_id, upload_ids=upload_ids, knowledge_ids=[], supports_files=False,
        )
        ctx = "\n\n".join(p for p in (ctx, ctx2) if p)

    if stop_event is not None and stop_event.is_set():
        raise RuntimeError("research cancelled")

    sys_p = build_system_prompt(lang=lang, mode=mode)
    user_p = build_user_message(query=query, focus=focus, context=ctx)

    content: Any = user_p
    if media:
        content = [{"type": "text", "text": user_p}, *media]

    # native_search models (Perplexity sonar-deep) already browse — don't double-bill
    web_search = not meta["native_search"]
    max_tokens = int(meta.get("max_tokens") or 16000)
    # Premium = same sonar-deep engine, larger write budget
    if mode == "premium" and mid == "perplexity/sonar-deep-research":
        max_tokens = max(max_tokens, 64000)
    temperature = float(meta["temperature"]) if "temperature" in meta else 0.3

    # Blocking call — cannot interrupt mid-HTTP; stop_event only gates entry.
    result = OpenRouterService.chat_completion(
        messages=[{"role": "user", "content": content}],
        model=mid,
        system_prompt=sys_p,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        user_id=user_id,
        feature=RESEARCH_FEATURE,
        workspace_id=workspace_id,
        project_id=project_id,
        origin="web",
        web_search=web_search,
        plugins=plugins,
        timeout=RESEARCH_TIMEOUT_S,
    )

    # _sync_completion returns {error:…} instead of raising — surface like OCR.
    if not isinstance(result, dict) or result.get("error"):
        err = (result or {}).get("error") if isinstance(result, dict) else None
        if isinstance(err, dict):
            reason = str(err.get("message") or err.get("code") or "model error")
        elif err:
            reason = str(err)
        else:
            reason = "model error"
        raise RuntimeError(reason[:500])

    report = _content_text(result)
    if not (report or "").strip():
        raise RuntimeError("empty model response")
    report = normalize_report_md(report)
    citations = normalize_citations(result, report_md=report)
    return {
        "report_md": report,
        "citations": citations,
        "model_id": mid,
        "mode": mode,
        "lang": lang if lang in ("fa", "en") else "fa",
    }
