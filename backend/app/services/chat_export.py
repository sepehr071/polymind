"""polymind.chat.export/v1 — one document rendered as JSON, Markdown, or PDF/A.

The JSON object is the source of truth. Markdown and PDF read that same dict
so assistant, model, workspace, and timestamps cannot drift between formats.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

from app.models.project import ProjectModel
from app.models.workspace import WorkspaceModel
from app.utils.config_resolver import resolve_config
from app.utils.quick_models import QUICK_MODELS

SCHEMA = "polymind.chat.export/v1"
EMPTY_ERROR = "این مکالمه پیامی برای خروجی ندارد."
TEHRAN = ZoneInfo("Asia/Tehran")
_ROLES = {"system", "user", "assistant"}
_ROLE_FA = {"user": "کاربر", "assistant": "دستیار"}
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_URL_RE = re.compile(r"https?://[^\s<>\[\])\"']+", re.IGNORECASE)


def has_dialogue(messages) -> bool:
    return any((m or {}).get("role") in ("user", "assistant") for m in messages or [])


def _iso(dt) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return dt
        dt = parsed
    if not isinstance(dt, datetime):
        return str(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TEHRAN).isoformat(timespec="seconds")


def _now() -> datetime:
    return datetime.now(TEHRAN)


def _workspace(conversation) -> dict:
    ws = None
    wid = conversation.get("workspace_id")
    if not wid and conversation.get("project_id"):
        project = ProjectModel.find_by_id(conversation.get("project_id")) or {}
        wid = project.get("workspace_id")
    if wid:
        ws = WorkspaceModel.find_by_id(wid)
    if not ws:
        return {"type": "person", "id": "", "title": ""}
    personal = ws.get("type") == "personal" or bool(ws.get("is_personal"))
    return {
        "type": "person" if personal else "organization",
        "id": str(ws.get("_id") or ws.get("id") or ""),
        "title": ws.get("name") or ws.get("display_name") or "",
    }


def _assistant_and_model(conversation, messages, user_id):
    cfg = None
    config_id = conversation.get("config_id")
    if config_id:
        cfg = resolve_config(
            str(config_id),
            user_id=user_id,
            project_id=conversation.get("project_id"),
        )
    assistant = {
        "id": str((cfg or {}).get("_id") or config_id or ""),
        "name": (cfg or {}).get("name") or conversation.get("title") or "",
    }
    model_id = ""
    for msg in reversed(messages or []):
        if msg.get("role") != "assistant":
            continue
        mid = (msg.get("metadata") or {}).get("model_id")
        if mid:
            model_id = str(mid)
            break
    if not model_id and cfg:
        model_id = str(cfg.get("model_id") or "")
    label = QUICK_MODELS.get(model_id) or (model_id.split("/")[-1] if model_id else "")
    return assistant, {"id": model_id, "label": label}, cfg


def _part_kind(att: dict) -> str:
    mime = att.get("content_type") or att.get("mime") or ""
    if not isinstance(mime, str):
        mime = ""
    raw_type = att.get("type") if isinstance(att.get("type"), str) else ""
    if mime.startswith("image/") or raw_type in ("image", "image_url"):
        return "image"
    name = (att.get("filename") or att.get("name") or "").lower()
    if name.endswith(_IMAGE_EXT):
        return "image"
    return "file"


def message_content(msg) -> str | list:
    text = msg.get("content") or ""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    atts = [a for a in (msg.get("attachments") or []) if isinstance(a, dict)]
    if not atts:
        return text
    parts: list[dict] = []
    if text:
        parts.append({"type": "text", "text": text})
    for att in atts:
        parts.append({
            "type": _part_kind(att),
            "filename": att.get("filename") or att.get("name") or "",
            "upload_id": str(att.get("upload_id") or att.get("id") or ""),
        })
    return parts


def _trim_url(raw: str) -> tuple[str, str]:
    core = raw
    tail = ""
    while core and core[-1] in ".,;:)]":
        tail = core[-1] + tail
        core = core[:-1]
    return core, tail


def prettify_urls(text: str) -> str:
    """Decode percent-encoded URLs so a Persian path is readable text."""
    if not text or "%" not in text:
        return text

    def repl(match: re.Match) -> str:
        core, tail = _trim_url(match.group(0))
        try:
            shown = unquote(core)
        except Exception:
            shown = core
        return shown + tail

    return _URL_RE.sub(repl, text)


def iter_text_and_urls(text: str):
    """Yield ('text', str) and ('url', original_url) pieces of one line."""
    if not text:
        return
    pos = 0
    for match in _URL_RE.finditer(text):
        if match.start() > pos:
            yield "text", text[pos:match.start()]
        core, _tail = _trim_url(match.group(0))
        yield "url", core
        pos = match.end()
    if pos < len(text):
        yield "text", text[pos:]


def content_text(content) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    lines = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            lines.append(part.get("text") or "")
        elif part.get("type") in ("file", "image"):
            name = part.get("filename") or part.get("upload_id") or part["type"]
            lines.append(f"[{part['type']}] {name}")
    return "\n".join(lines)


def _tokens(conversation, messages) -> int:
    total = int((conversation.get("token_count") or {}).get("total") or 0)
    if total:
        return total
    acc = 0
    for msg in messages or []:
        tok = (msg.get("metadata") or {}).get("tokens") or {}
        if isinstance(tok, dict):
            acc += int(tok.get("total") or 0)
        elif isinstance(tok, int):
            acc += tok
    return acc


def build_export(conversation, messages, user_id) -> dict:
    assistant, model, cfg = _assistant_and_model(conversation, messages, user_id)
    out = []
    seen = set()
    prompt = ((cfg or {}).get("system_prompt") or "").strip()
    if prompt:
        out.append({
            "role": "system",
            "content": prompt,
            "created_at": _iso(conversation.get("created_at")),
        })
        seen.add(prompt)
    requests = 0
    for msg in messages or []:
        role = msg.get("role")
        if role not in _ROLES:
            continue
        if role == "assistant":
            requests += 1
        content = message_content(msg)
        if role == "system":
            key = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            if not (key or "").strip() or key in seen:
                continue
            seen.add(key)
        out.append({
            "role": role,
            "content": content,
            "created_at": _iso(msg.get("created_at")),
        })
    conv_id = str(conversation.get("_id") or conversation.get("id") or "")
    return {
        "schema": SCHEMA,
        "id": f"conv_{conv_id}",
        "exported_at": _iso(_now()),
        "assistant": assistant,
        "model": model,
        "workspace": _workspace(conversation),
        "usage": {"tokens": _tokens(conversation, messages), "requests": requests},
        "messages": out,
    }


def render_json(doc) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2)


def render_markdown(doc, title: str) -> str:
    lines = [
        f"**دستیار:** {doc['assistant']['name']}",
        f"**فضا:** {doc['workspace']['title']}",
        f"**تاریخ:** {doc['exported_at']}",
        f"**مدل:** {doc['model']['label'] or doc['model']['id']}",
        "",
        f"# {title}",
        "",
    ]
    systems = [m for m in doc["messages"] if m["role"] == "system"]
    if systems:
        lines.extend(["## تنظیمات دستیار", ""])
        for msg in systems:
            lines.extend([content_text(msg["content"]), ""])
    lines.extend(["## گفتگو", ""])
    for msg in doc["messages"]:
        label = _ROLE_FA.get(msg["role"])
        if not label:
            continue
        lines.extend([f"**{label}**", "", prettify_urls(content_text(msg["content"])), ""])
    return "\n".join(lines).rstrip() + "\n"


def ascii_filename(conversation, ext: str, when: datetime | None = None) -> str:
    raw = str(conversation.get("_id") or "chat").replace("-", "")
    short = re.sub(r"[^A-Za-z0-9]", "", raw)[:8] or "chat"
    stamp = (when or _now()).strftime("%Y%m%d%H%M%S")
    return f"polymind-{short}-{stamp}.{ext}"


def display_filename(title: str, ext: str) -> str:
    cleaned = _ILLEGAL.sub(" ", title or "chat")
    cleaned = re.sub(r"\s+", " ", cleaned).strip() or "chat"
    return f"{cleaned}.{ext}"


def content_disposition(ascii_name: str, display_name: str) -> str:
    star = quote(display_name, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{star}"
