"""Prompt builders for the AI presentation outline generator.

The outline LLM is asked for STRICT JSON (no markdown / code fences) shaped per
``OUTLINE_JSON_SHAPE``; ``presentation_service._parse_outline_json`` parses and
normalizes that JSON. Keep the shape string and the parser in sync.
"""

VALID_LAYOUTS = (
    'title', 'section', 'agenda', 'content', 'content_image',
    'two_column', 'comparison', 'metrics', 'process', 'timeline',
    'quote', 'feature_grid', 'image_hero', 'chart', 'closing',
)

OUTLINE_JSON_SHAPE = (
    '{"title": string, "language": string, "slides": [{'
    '"layout": "title"|"section"|"agenda"|"content"|"content_image"|'
    '"two_column"|"comparison"|"metrics"|"process"|"timeline"|'
    '"quote"|"feature_grid"|"image_hero"|"chart"|"closing", '
    '"title": string, '
    '"subtitle": string|null, '
    '"kicker": string|null, '
    '"bullets": [string], '
    '"items": [string]|null, '
    '"speaker_notes": string, '
    '"image_prompt": string|null, '
    '"caption": string|null, '
    '"quote": string|null, '
    '"attribution": string|null, '
    '"columns": {"left":{"title":string,"bullets":[string]},'
    '"right":{"title":string,"bullets":[string]}}|null, '
    '"metrics": [{"value":string,"label":string,"delta":string|null}]|null, '
    '"steps": [{"title":string,"body":string,"icon":string|null}]|null, '
    '"events": [{"label":string,"detail":string,"when":string|null}]|null, '
    '"features": [{"title":string,"body":string,"icon":string|null}]|null, '
    '"chart": {"type":"bar"|"line"|"pie","categories":[string],'
    '"series":[{"name":string,"values":[number]}],"unit":string|null}|null'
    '}]}'
)

_LAYOUT_RUBRIC = """
Layout selection rubric (pick the BEST layout per slide purpose):
- title: opening hero only (first slide). Optional subtitle + image_prompt.
- section: major part divider. Optional kicker above title.
- agenda: table of contents. Put entries in items[] (not bullets).
- content: classic bullet points when no richer layout fits.
- content_image: bullets + visual. Set image_prompt (English, no text-in-image).
- two_column: two related topics side by side. Use columns.left/right.
- comparison: A vs B (pros/cons, before/after). columns.left/right with titles as labels.
- metrics: 3–4 executive KPIs. metrics[{value,label,delta?}]. Prefer real numbers from source.
- process: 3–5 sequential steps. steps[{title,body,icon?}].
- timeline: roadmap / chronology. events[{label,detail,when?}].
- quote: one powerful pull-quote. quote + attribution.
- feature_grid: 4 or 6 marketing features. features[{title,body,icon?}].
- image_hero: visual beat with short title + image_prompt + optional caption.
- chart: ONLY when source provides real numbers. chart{type,categories,series}. Never invent data.
- closing: final CTA (last slide). Optional bullets as next steps.
""".strip()


def build_outline_system_prompt(*, slide_count, tone, audience, language):
    lang = language or 'fa'
    if lang == 'fa':
        lang_line = (
            "Write ALL slide text in Persian (Farsi). Keep bullets short and dense "
            "(≤12 words). Prefer sharp executive phrasing over long sentences. "
            "Metric values may keep Latin digits and units (e.g. 42%, $1.2M). "
        )
    else:
        lang_line = (
            f"Write ALL slide text in language code '{lang}'. "
            "Keep bullets short (≤12 words), dense and scannable. "
        )
    return (
        "You are a senior presentation designer and strategist. Produce a slide deck "
        "outline as STRICT JSON and nothing else — no markdown, no code fences, no commentary.\n"
        f"Shape: {OUTLINE_JSON_SHAPE}\n"
        f"Produce about {slide_count} slides. First slide layout='title', last layout='closing'. "
        "Use 'section' to break major parts. Vary layouts deliberately — avoid making every "
        "slide 'content'. A strong multipurpose deck mixes metrics, process, comparison, "
        "two_column, feature_grid, and content as the narrative needs.\n"
        f"{_LAYOUT_RUBRIC}\n"
        "Icon keys (optional on steps/features): growth, shield, users, bolt, target, "
        "chart, globe, check, star, rocket, clock, lightbulb — or null.\n"
        "For image_prompt: concise English visual description, no text-in-image, no logos.\n"
        "Null out unused structured fields. Empty arrays only when the layout needs them.\n"
        f"{lang_line}"
        f"Tone: {tone or 'professional'}. Audience: {audience or 'general'}.\n"
        "If source material is provided, ground the outline strictly in it. "
        "Do not invent statistics or chart values not present in the source or topic."
    )


def build_outline_user_prompt(*, topic, source_text):
    parts = [f"Topic: {topic}".strip()]
    if source_text:
        parts.append("\n\n## Source material (ground the deck in this)\n" + source_text)
    return "\n".join(parts)
