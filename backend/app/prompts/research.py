"""Deep research prompts — FA report skeleton, no chat identity block."""

RESEARCH_FEATURE = "research"

# Live OpenRouter catalog (2026-08-03 probe):
#   GONE from OR: openai/o4-mini-deep-research, openai/o3-deep-research
#     (OpenAI deep-research was a *separate product* with multi-step browse;
#      o3 is only a reasoning chat model — NOT a substitute.)
#   Real deep-research on OR today: perplexity/sonar-deep-research
#     (native multi-step search + synthesis; text modality; don't add web_search)
#   Quick: gemini-3.5-flash-lite + openrouter:web_search
# Premium mode = same sonar-deep engine with larger output budget + deeper prompt
# (no o3 — expensive normal LLM with one-shot web_search, not research agent).
RESEARCH_MODELS = {
    "perplexity/sonar-deep-research": {
        "tier": "deep",
        "supports_files": False,  # text extracts injected when user attaches files
        "native_search": True,
        "cost_band": "medium",
        "max_tokens": 32000,
        "temperature": 0.2,
    },
    # Same model id, higher cap when mode=premium (resolve picks by mode default)
    "google/gemini-3.5-flash-lite": {
        "tier": "quick",
        "supports_files": False,
        "native_search": False,  # needs openrouter:web_search
        "cost_band": "low",
        "max_tokens": 16000,
        "temperature": 0.3,
    },
}

RESEARCH_MODEL_IDS = frozenset(RESEARCH_MODELS.keys())

MODE_DEFAULT_MODEL = {
    "quick": "google/gemini-3.5-flash-lite",
    "deep": "perplexity/sonar-deep-research",
    "deep_files": "perplexity/sonar-deep-research",  # same; files → text extract
    # Premium still sonar-deep-research — real multi-step research, not o3 chat
    "premium": "perplexity/sonar-deep-research",
}

RESEARCH_MODES = frozenset(MODE_DEFAULT_MODEL.keys())
RESEARCH_TIMEOUT_S = 600
RESEARCH_MAX_UPLOADS = 5


def build_system_prompt(*, lang: str, mode: str = "deep") -> str:
    lang = "en" if lang == "en" else "fa"
    mode = (mode or "deep").strip()
    if mode not in RESEARCH_MODES:
        mode = "deep"

    if lang == "fa":
        # Real ## headings — NOT "1. **عنوان**" lists (those render as a dense wall).
        sections = """
ساختار گزارش (markdown واقعی، هر بخش با تیتر سطح ۲):

## عنوان
(یک خط تیتر توصیفی)

## خلاصه اجرایی
(۲–۴ پاراگراف برای مدیر)

## زمینه و سؤال
(بافت مسئله و سؤال تحقیق)

## یافته‌های کلیدی
- هر یافته جدا، با نشانگر ارجاع [n] وقتی منبع دارید

## تحلیل
(چند زیربخش با ### در صورت نیاز)

## ریسک‌ها و عدم‌قطعیت
(بولت‌لیست)

## پیشنهاد اقدام
(اقدام‌های مشخص و اولویت‌دار)

## منابع
فهرست شماره‌دار؛ هر مورد: عنوان — URL واقعی (https://...)
"""
        lang_line = "کل گزارش را به فارسی بنویس. نام‌های خاص و URL را دست‌نخورده نگه دار."
    else:
        sections = """
Report structure (real markdown — use level-2 headings, NOT numbered bold labels):

## Title
(one descriptive title line)

## Executive summary
(2–4 paragraphs for a manager)

## Context & question
(problem framing)

## Key findings
- Each finding on its own bullet, with [n] markers when you have a source

## Analysis
(use ### subheads if helpful)

## Risks & uncertainties
(bullet list)

## Recommended actions
(concrete, prioritized)

## Sources
Numbered list; each item: title — real URL (https://...)
"""
        lang_line = "Write the full report in English. Keep proper nouns and URLs intact."

    if mode == "quick":
        if lang == "fa":
            depth = """
عمق (حالت سریع):
- گزارش کوتاه ولی کامل — نه چند جمله. حداقل حدود ۱۲۰۰–۱۸۰۰ کلمهٔ فارسی.
- حداقل ۵ یافته کلیدی مشخص با توضیح کوتاه.
- حداقل یک پاراگراف تحلیل و ۳ پیشنهاد اقدام.
- اگر وب‌سرچ فعال است، حداقل ۵ منبع با URL واقعی در بخش منابع.
- از تیترهای ## استفاده کن؛ هرگز «۱. **عنوان**» به شکل لیست شماره‌دار ننویس.
"""
        else:
            depth = """
Depth (quick mode):
- Short but complete — not a stub. Target ~900–1400 English words.
- At least 5 concrete key findings with brief explanation.
- At least one analysis paragraph and 3 recommended actions.
- If web search is available, at least 5 Sources entries with real https URLs.
- Use ## headings; never write "1. **Title**" as a numbered list of section labels.
"""
    elif mode == "premium":
        if lang == "fa":
            depth = """
عمق (حالت ویژه):
- گزارش جامع تحلیل‌گر (چند صفحه‌ای). زیرجزئیات، مقایسه، و ارجاع گسترده.
- یافته‌ها را با شواهد و [n] غنی کن؛ منابع متعدد و معتبر.
"""
        else:
            depth = """
Depth (premium mode):
- Comprehensive analyst report (multi-page). Detail, comparison, dense citations.
- Ground findings with evidence and [n]; many reputable sources.
"""
    else:
        if lang == "fa":
            depth = """
عمق (حالت عمیق):
- گزارش کامل مدیرعامل/تحلیل‌گر: چند صفحه، یافته‌های مستند، تحلیل متوازن.
- حداقل ۸–۱۲ یافته/نقطهٔ تحلیلی؛ منابع واقعی با URL در بخش منابع.
- از تیترهای ## استفاده کن؛ هرگز «۱. **عنوان**» به شکل لیست شماره‌دار ننویس.
"""
        else:
            depth = """
Depth (deep mode):
- Full manager/analyst report: multi-section, evidenced findings, balanced analysis.
- Aim for many concrete findings; real URLs in Sources.
- Use ## headings; never "1. **Title**" numbered section labels.
"""

    return f"""You are Polymind AI's deep research analyst for Iranian companies and managers.
{lang_line}
{sections}
{depth}

Formatting rules (critical for UI):
- Section titles MUST be markdown ATX headings: lines starting with "## " (and "### " for subheads).
- Do NOT format sections as ordered lists like "1. **Title**" — that collapses in the reader.
- Separate sections with a blank line before each ## heading.
- Body paragraphs under each heading; use bullets for lists of findings/actions.

Research rules:
- Ground claims in sources; use [n] markers that match the Sources list.
- Never invent URLs. If you lack a real URL, omit the link rather than fabricate one.
- Prefer recent, reputable sources; note uncertainty explicitly.
- Not legal, medical, or financial advice — decision support only.
- When relevant, consider Iranian market/regulatory context.
- Do not prepend product identity fluff; produce the report only.
"""


def build_user_message(*, query: str, focus: str = "", context: str = "") -> str:
    parts = [f"Research query:\n{(query or '').strip()}"]
    if (focus or "").strip():
        parts.append(f"Focus / constraints:\n{focus.strip()}")
    if (context or "").strip():
        parts.append(f"Additional source material:\n{context.strip()[:80000]}")
    return "\n\n".join(parts)
