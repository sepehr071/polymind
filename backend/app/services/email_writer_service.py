"""Email / letter writer — stream draft via OpenRouter."""
from __future__ import annotations

import logging
from typing import Any, Dict, Generator, Optional

from app.prompts.email_writer import (
    EMAIL_WRITER_FEATURE,
    EMAIL_WRITER_MODEL,
    TEMPLATE_IDS,
    TONES,
    LANGS,
    build_system_prompt,
    build_user_message,
)
from app.services.openrouter_service import OpenRouterService

logger = logging.getLogger(__name__)


def _delta_text(chunk: dict) -> str:
    choices = chunk.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    content = delta.get("content") or ""
    if isinstance(content, list):
        return "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("text")
        )
    return content if isinstance(content, str) else ""


def stream_draft(
    *,
    template_id: str,
    fields: dict,
    lang: str = "fa",
    tone: str = "formal",
    workspace_id: Optional[str] = None,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Yield {type:'token', text} then {type:'done', content,...}."""
    if template_id not in TEMPLATE_IDS:
        raise ValueError(f"unknown template_id: {template_id}")
    lang = lang if lang in LANGS else "fa"
    tone = tone if tone in TONES else "formal"
    fields = fields if isinstance(fields, dict) else {}

    sys_p = build_system_prompt(lang=lang, tone=tone, template_id=template_id)
    user_p = build_user_message(template_id=template_id, lang=lang, tone=tone, fields=fields)

    gen = OpenRouterService.chat_completion(
        messages=[{"role": "user", "content": user_p}],
        model=EMAIL_WRITER_MODEL,
        system_prompt=sys_p,
        temperature=0.4,
        max_tokens=4096,
        stream=True,
        user_id=user_id,
        feature=EMAIL_WRITER_FEATURE,
        workspace_id=workspace_id,
        project_id=project_id,
        origin="web",
    )

    parts: list[str] = []
    for chunk in gen:
        if not isinstance(chunk, dict):
            continue
        if chunk.get("done"):
            break
        t = _delta_text(chunk)
        if t:
            parts.append(t)
            yield {"type": "token", "text": t}

    content = "".join(parts).strip()
    yield {
        "type": "done",
        "content": content,
        "template_id": template_id,
        "lang": lang,
        "tone": tone,
    }
