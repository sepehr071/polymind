"""Multi-agent presentation outline pipeline (always-on).

Stages: Analyst(+web_search) → Strategist → Outline writer → Layout director
→ Critic (≤N patch loops). Yields ``('phase', name)``, optional ``('warning', msg)``,
then ``('outline', outline_dict)``.

Blocking OpenRouter calls — run only from SSE worker thread / offloaded context.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Iterator, Optional, Tuple

from app.prompts import presentation_agents as prompts
from app.prompts.presentation import VALID_LAYOUTS
from app.services.openrouter_service import OpenRouterService
from app.services.presentation_service import _norm_slide, _parse_outline_json

logger = logging.getLogger(__name__)

_FEATURE = "presentation"
_VALID_LAYOUTS = frozenset(VALID_LAYOUTS)

_ANALYST_MODEL = os.environ.get(
    "PRESENTATION_ANALYST_MODEL", "google/gemini-3.1-flash-lite"
)
_STRATEGIST_MODEL = os.environ.get(
    "PRESENTATION_STRATEGIST_MODEL", "anthropic/claude-sonnet-5"
)
_OUTLINE_MODEL = os.environ.get(
    "PRESENTATION_OUTLINE_MODEL", "anthropic/claude-sonnet-5"
)
_LAYOUT_MODEL = os.environ.get(
    "PRESENTATION_LAYOUT_MODEL", "google/gemini-3.1-flash-lite"
)
_CRITIC_MODEL = os.environ.get(
    "PRESENTATION_CRITIC_MODEL", "google/gemini-3.1-flash-lite"
)
try:
    _CRITIC_MAX_LOOPS = max(0, min(3, int(os.environ.get("PRESENTATION_CRITIC_MAX_LOOPS", "2"))))
except (TypeError, ValueError):
    _CRITIC_MAX_LOOPS = 2

_COMPOSITIONS = frozenset({"default", "hero_split", "cards_row", "big_number", "full_bleed"})
_ACCENTS = frozenset({"edge", "band", "card", "none"})
_IMAGE_ROLES = frozenset({"none", "support", "hero"})
_DECK_TYPES = frozenset({"executive", "pitch", "marketing", "training", "general"})
_DENSITIES = frozenset({"exec_dense", "pitch_airy", "marketing_bold"})


# ── JSON helpers ────────────────────────────────────────────────────────────

def _strip_json(raw: str) -> str:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1]
    return raw


def _parse_json_obj(raw: str) -> dict:
    data = json.loads(_strip_json(raw))
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def _message_content(resp: Any) -> str:
    if isinstance(resp, dict) and "error" in resp:
        err = resp.get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise RuntimeError(msg or "OpenRouter error")
    try:
        content = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("model returned no content") from exc
    if isinstance(content, list):
        # some providers return content parts
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(p.get("text") or "")
            elif isinstance(p, str):
                parts.append(p)
        content = "".join(parts)
    return content or ""


def _llm_json(
    *,
    model: str,
    system: str,
    user: str,
    user_id,
    workspace_id,
    project_id,
    origin: str,
    temperature: float = 0.3,
    max_tokens: int = 8000,
    web_search: bool = False,
    timeout: Optional[int] = None,
) -> dict:
    kw: Dict[str, Any] = dict(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        user_id=user_id,
        workspace_id=workspace_id,
        project_id=project_id,
        origin=origin,
        feature=_FEATURE,
        web_search=web_search,
    )
    if timeout is not None:
        kw["timeout"] = timeout
    if web_search:
        kw["web_search_params"] = {"max_results": 5}
    resp = OpenRouterService.chat_completion(**kw)
    return _parse_json_obj(_message_content(resp))


# ── Normalizers ─────────────────────────────────────────────────────────────

def _norm_fact_sheet(raw: dict) -> dict:
    facts = []
    for f in (raw.get("facts") or [])[:12]:
        if not isinstance(f, dict):
            continue
        claim = (f.get("claim") or "").strip()
        if not claim and not f.get("value"):
            continue
        src = (f.get("source") or "web").strip().lower()
        if src not in ("upload", "web", "topic"):
            src = "web"
        facts.append({
            "claim": claim,
            "value": (str(f["value"]).strip() if f.get("value") is not None else None),
            "unit": (str(f["unit"]).strip() if f.get("unit") else None),
            "source": src,
            "url": (str(f["url"]).strip() if f.get("url") else None),
        })
    quotes = []
    for q in (raw.get("quotes") or [])[:4]:
        if not isinstance(q, dict):
            continue
        text = (q.get("text") or "").strip()
        if not text:
            continue
        quotes.append({
            "text": text,
            "attribution": (q.get("attribution") or "").strip(),
            "url": (str(q["url"]).strip() if q.get("url") else None),
        })
    web_sources = []
    for s in (raw.get("web_sources") or [])[:5]:
        if not isinstance(s, dict):
            continue
        web_sources.append({
            "title": (s.get("title") or "").strip()[:200],
            "url": (s.get("url") or "").strip()[:500],
            "snippet": (s.get("snippet") or "").strip()[:400],
        })
    angles = [str(a).strip() for a in (raw.get("angles") or []) if str(a).strip()][:8]
    risks = [str(a).strip() for a in (raw.get("risks_unknowns") or []) if str(a).strip()][:8]
    return {
        "topic_summary": (raw.get("topic_summary") or "").strip(),
        "audience_notes": (raw.get("audience_notes") or "").strip(),
        "facts": facts,
        "quotes": quotes,
        "angles": angles,
        "risks_unknowns": risks,
        "web_sources": web_sources,
    }


def _norm_deck_plan(raw: dict, *, slide_count: int, topic: str) -> dict:
    deck_type = (raw.get("deck_type") or "general").strip().lower()
    if deck_type not in _DECK_TYPES:
        deck_type = "general"
    density = (raw.get("density") or "pitch_airy").strip().lower()
    if density not in _DENSITIES:
        density = "pitch_airy"
    theme_hint = (raw.get("theme_hint") or "polymind").strip().lower()
    beats = []
    for b in (raw.get("narrative_beats") or [])[:12]:
        if not isinstance(b, dict):
            continue
        try:
            budget = int(b.get("slide_budget") or 1)
        except (TypeError, ValueError):
            budget = 1
        beats.append({
            "id": (b.get("id") or b.get("purpose") or "beat").strip()[:40],
            "purpose": (b.get("purpose") or "context").strip()[:40],
            "slide_budget": max(1, min(budget, 6)),
            "notes": (b.get("notes") or "").strip()[:300],
        })
    try:
        target = int(raw.get("slide_count_target") or slide_count)
    except (TypeError, ValueError):
        target = slide_count
    target = max(3, min(target, 40))
    return {
        "title": (raw.get("title") or topic).strip()[:200],
        "deck_type": deck_type,
        "density": density,
        "theme_hint": theme_hint,
        "image_style": (raw.get("image_style") or (
            "clean modern professional illustration, soft gradients, no text in image"
        )).strip()[:300],
        "narrative_beats": beats,
        "slide_count_target": target,
        "visual_direction": (raw.get("visual_direction") or "").strip()[:500],
    }


def _norm_visual_recipe(raw) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    comp = (raw.get("composition") or "default").strip().lower()
    if comp not in _COMPOSITIONS:
        comp = "default"
    accent = (raw.get("accent") or "edge").strip().lower()
    if accent not in _ACCENTS:
        accent = "edge"
    role = (raw.get("image_role") or "none").strip().lower()
    if role not in _IMAGE_ROLES:
        role = "none"
    return {"composition": comp, "accent": accent, "image_role": role}


def _enrich_outline_slide(s: dict) -> dict:
    """Normalize slide then attach purpose + visual_recipe."""
    base = _norm_slide(s)
    purpose = (s.get("purpose") or "").strip().lower() or None
    base["purpose"] = purpose
    base["visual_recipe"] = _norm_visual_recipe(s.get("visual_recipe"))
    # sync image_role into recipe if top-level present
    if s.get("image_role"):
        role = str(s.get("image_role")).strip().lower()
        if role in _IMAGE_ROLES:
            base["visual_recipe"]["image_role"] = role
    return base


def _parse_outline_enriched(raw_text: str, *, language: str) -> dict:
    """Parse outline JSON with purpose/visual_recipe (re-parse slides from raw)."""
    data = _parse_json_obj(raw_text)
    slides = []
    for s in (data.get("slides") or []):
        if isinstance(s, dict):
            slides.append(_enrich_outline_slide(s))
    return {
        "title": (data.get("title") or "").strip(),
        "language": data.get("language") or language or "fa",
        "slides": slides,
    }


def _prefix_image_prompts(outline: dict, image_style: str) -> None:
    style = (image_style or "").strip()
    if not style:
        return
    for s in outline.get("slides") or []:
        recipe = s.get("visual_recipe") or {}
        role = recipe.get("image_role") or "none"
        ip = s.get("image_prompt")
        if role in ("support", "hero"):
            if not ip:
                title = s.get("title") or "abstract concept"
                s["image_prompt"] = f"{style}. Visual for: {title}"
            elif not ip.lower().startswith(style[:20].lower()):
                s["image_prompt"] = f"{style}. {ip}"
        elif role == "none":
            # keep existing image_prompt for content_image layouts
            pass


def _apply_layout_directives(outline: dict, directives: dict, image_style: str) -> None:
    slides = outline.get("slides") or []
    for item in (directives.get("slides") or []):
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(slides):
            continue
        s = slides[idx]
        layout = (item.get("layout") or "").strip().lower()
        if layout in _VALID_LAYOUTS:
            s["layout"] = layout
        if item.get("visual_recipe") is not None:
            s["visual_recipe"] = _norm_visual_recipe(item.get("visual_recipe"))
        if item.get("image_role") is not None:
            role = str(item.get("image_role")).strip().lower()
            if role in _IMAGE_ROLES:
                s.setdefault("visual_recipe", _norm_visual_recipe({}))
                s["visual_recipe"]["image_role"] = role
        if "image_prompt" in item:
            ip = item.get("image_prompt")
            s["image_prompt"] = (str(ip).strip() if ip else None)
    _prefix_image_prompts(outline, image_style)


def apply_critic_patches(outline: dict, patches: list, *, image_style: str = "") -> int:
    """Apply allowed critic patches in-place. Returns number applied."""
    slides = outline.get("slides") or []
    applied = 0
    for p in (patches or [])[:12]:
        if not isinstance(p, dict):
            continue
        op = (p.get("op") or "").strip()
        try:
            idx = int(p.get("slide"))
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(slides):
            continue
        s = slides[idx]
        if op == "set_layout":
            layout = (p.get("layout") or "").strip().lower()
            if layout in _VALID_LAYOUTS:
                s["layout"] = layout
                applied += 1
        elif op == "set_visual_recipe":
            s["visual_recipe"] = _norm_visual_recipe(p.get("visual_recipe"))
            applied += 1
        elif op == "trim_bullets":
            try:
                mx = int(p.get("max") or 4)
            except (TypeError, ValueError):
                mx = 4
            bullets = s.get("bullets") or []
            if len(bullets) > mx:
                s["bullets"] = bullets[: max(1, mx)]
                applied += 1
        elif op == "clear_chart":
            if s.get("chart"):
                s["chart"] = None
                if s.get("layout") == "chart":
                    s["layout"] = "content"
                applied += 1
        elif op == "set_image_role":
            role = (p.get("image_role") or "none").strip().lower()
            if role in _IMAGE_ROLES:
                s.setdefault("visual_recipe", _norm_visual_recipe({}))
                s["visual_recipe"]["image_role"] = role
                if role == "none":
                    pass
                applied += 1
        elif op == "set_image_prompt":
            ip = p.get("image_prompt")
            s["image_prompt"] = (str(ip).strip() if ip else None)
            applied += 1
    if image_style:
        _prefix_image_prompts(outline, image_style)
    return applied


def _empty_fact_sheet(topic: str) -> dict:
    return {
        "topic_summary": topic,
        "audience_notes": "",
        "facts": [],
        "quotes": [],
        "angles": [],
        "risks_unknowns": ["web research unavailable"],
        "web_sources": [],
    }


# ── Pipeline ────────────────────────────────────────────────────────────────

def run_outline_pipeline(
    *,
    topic: str,
    source_text: str,
    slide_count: int,
    tone: str,
    audience: str,
    language: str,
    user_id,
    workspace_id,
    project_id,
    origin: str = "web",
    stop_event=None,
) -> Iterator[Tuple[str, Any]]:
    """Yield ``('phase', str)``, ``('warning', str)``, finally ``('outline', dict)``.

    Raises RuntimeError on hard failure after soft-degrades exhausted.
    """
    def _stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    lang = language or "fa"
    aud = audience or "general"
    ton = tone or "professional"

    # ── 1 Analyst ──────────────────────────────────────────────────────────
    yield ("phase", "researching")
    if _stopped():
        return
    try:
        raw_facts = _llm_json(
            model=_ANALYST_MODEL,
            system=prompts.analyst_system(language=lang, audience=aud),
            user=prompts.analyst_user(
                topic=topic, source_text=source_text or "", slide_count=slide_count
            ),
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            origin=origin,
            temperature=0.2,
            max_tokens=6000,
            web_search=True,
            timeout=120,
        )
        fact_sheet = _norm_fact_sheet(raw_facts)
    except Exception as exc:
        logger.warning("presentation analyst failed, source-only: %s", exc)
        yield ("warning", f"research degraded: {exc}")
        fact_sheet = _empty_fact_sheet(topic)
        # seed crude facts from source length signal only — no invented numbers

    if _stopped():
        return

    # ── 2 Strategist ───────────────────────────────────────────────────────
    yield ("phase", "planning")
    if _stopped():
        return
    try:
        raw_plan = _llm_json(
            model=_STRATEGIST_MODEL,
            system=prompts.strategist_system(language=lang, tone=ton, audience=aud),
            user=prompts.strategist_user(
                topic=topic, slide_count=slide_count, fact_sheet=fact_sheet
            ),
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            origin=origin,
            temperature=0.3,
            max_tokens=4000,
            timeout=90,
        )
        deck_plan = _norm_deck_plan(raw_plan, slide_count=slide_count, topic=topic)
    except Exception as exc:
        logger.warning("presentation strategist failed, defaults: %s", exc)
        yield ("warning", f"planning degraded: {exc}")
        deck_plan = _norm_deck_plan({}, slide_count=slide_count, topic=topic)

    target_slides = deck_plan.get("slide_count_target") or slide_count
    if _stopped():
        return

    # ── 3 Outline writer ───────────────────────────────────────────────────
    yield ("phase", "drafting")
    if _stopped():
        return
    try:
        # Use raw text path for full outline shape (richer than intermediate parsers)
        resp = OpenRouterService.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": prompts.outline_writer_system(
                        language=lang, tone=ton, audience=aud, slide_count=target_slides
                    ),
                },
                {
                    "role": "user",
                    "content": prompts.outline_writer_user(
                        topic=topic, fact_sheet=fact_sheet, deck_plan=deck_plan
                    ),
                },
            ],
            model=_OUTLINE_MODEL,
            temperature=0.3,
            max_tokens=16000,
            stream=False,
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            origin=origin,
            feature=_FEATURE,
            timeout=180,
        )
        outline = _parse_outline_enriched(_message_content(resp), language=lang)
    except Exception as exc:
        logger.exception("presentation outline writer failed")
        raise RuntimeError(f"outline drafting failed: {exc}") from exc

    if not outline.get("title"):
        outline["title"] = deck_plan.get("title") or topic
    if not outline.get("slides"):
        raise RuntimeError("outline generation produced no slides")

    _prefix_image_prompts(outline, deck_plan.get("image_style") or "")
    # stash plan metadata lightly on outline for FE/debug (non-breaking)
    outline["_meta"] = {
        "deck_type": deck_plan.get("deck_type"),
        "density": deck_plan.get("density"),
        "theme_hint": deck_plan.get("theme_hint"),
        "fact_count": len(fact_sheet.get("facts") or []),
        "web_sources": fact_sheet.get("web_sources") or [],
    }

    if _stopped():
        return

    # ── 4 Layout director ──────────────────────────────────────────────────
    yield ("phase", "designing")
    if _stopped():
        return
    try:
        directives = _llm_json(
            model=_LAYOUT_MODEL,
            system=prompts.layout_director_system(
                density=deck_plan.get("density"),
                deck_type=deck_plan.get("deck_type"),
            ),
            user=prompts.layout_director_user(outline=outline, deck_plan=deck_plan),
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            origin=origin,
            temperature=0.2,
            max_tokens=4000,
            timeout=90,
        )
        _apply_layout_directives(
            outline, directives, deck_plan.get("image_style") or ""
        )
    except Exception as exc:
        logger.warning("presentation layout director failed: %s", exc)
        yield ("warning", f"layout polish degraded: {exc}")

    if _stopped():
        return

    # ── 5 Critic loops ─────────────────────────────────────────────────────
    yield ("phase", "reviewing")
    for loop in range(_CRITIC_MAX_LOOPS):
        if _stopped():
            return
        try:
            critique = _llm_json(
                model=_CRITIC_MODEL,
                system=prompts.critic_system(),
                user=prompts.critic_user(
                    outline=outline, fact_sheet=fact_sheet, deck_plan=deck_plan
                ),
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                origin=origin,
                temperature=0.1,
                max_tokens=3000,
                timeout=60,
            )
        except Exception as exc:
            logger.warning("presentation critic failed loop %s: %s", loop, exc)
            yield ("warning", f"review degraded: {exc}")
            break

        passed = bool(critique.get("pass"))
        try:
            score = float(critique.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        if passed or score >= 72:
            break
        patches = critique.get("patches") or []
        if not patches:
            break
        n = apply_critic_patches(
            outline, patches, image_style=deck_plan.get("image_style") or ""
        )
        if n == 0:
            break

    # Final normalize pass — re-enrich slides to enforce schema
    outline["slides"] = [
        _enrich_outline_slide(s) if "visual_recipe" in s else _enrich_outline_slide(s)
        for s in (outline.get("slides") or [])
    ]
    # strip private meta before client? Keep for FE sources optional — FE ignores unknown.
    yield ("outline", outline)


def generate_outline_via_pipeline(**kwargs) -> dict:
    """Convenience: run pipeline, return final outline only (tests / sync callers)."""
    outline = None
    for kind, payload in run_outline_pipeline(**kwargs):
        if kind == "outline":
            outline = payload
    if not outline:
        raise RuntimeError("pipeline produced no outline")
    return outline
