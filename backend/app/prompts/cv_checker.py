"""CV checker prompts — anti-bias, screen | improve modes."""

CV_CHECKER_MODEL = "google/gemini-3.5-flash-lite"
CV_CHECKER_FEATURE = "cv_checker"
CV_CHECKER_MODES = frozenset({"screen", "improve"})
CV_CHECKER_LANGS = frozenset({"fa", "en"})

DISCLAIMER_FA = (
    "این ابزار پیشنهاد کمکی است و جایگزین ارزیابی انسانی نیست. "
    "تصمیم استخدام فقط با انسان."
)
DISCLAIMER_EN = (
    "This is assistive only and not an automated hiring decision. "
    "A human makes the final hiring call."
)

BIAS_BLOCK = """
ANTI-BIAS (non-negotiable):
1. Do NOT infer or score: gender, religion, ethnicity, race, nationality, age,
   marital/family status, disability, sexual orientation, political affiliation,
   appearance, or photo attractiveness.
2. Do NOT use name, pronouns, or address as a gender/ethnicity proxy.
3. Military/service history: only skill-transfer relevance if JD/user mentions it —
   never as a quality or loyalty signal; no political judgment.
4. Career gaps: phrase as "clarify with candidate", never automatic reject demerit.
5. If CV contains protected attributes, ignore them for scoring; focus skills,
   experience, education, outcomes, and communication clarity.
6. If the user asks for biased criteria, refuse that dimension and continue neutrally.
7. must_have_checklist items MUST be skills/experience/education/outcomes only —
   never demographic or protected-class criteria.
"""

DENYLIST_KEYS = frozenset({
    "gender_score", "age", "religion", "ethnicity", "nationality_score",
    "photo_score", "photo_attractiveness", "marital_status", "marital_score",
    "disability_score", "appearance_score",
})

DIMENSION_WHITELIST = frozenset({
    "skills", "experience", "education", "impact", "clarity", "jd_alignment",
})

CHECKLIST_STATUSES = frozenset({"met", "partial", "missing"})


def build_system_prompt(*, mode: str, lang: str, has_jd: bool) -> str:
    lang = lang if lang in CV_CHECKER_LANGS else "fa"
    mode = mode if mode in CV_CHECKER_MODES else "screen"
    out_lang = "Persian (Farsi)" if lang == "fa" else "English"
    if mode == "screen":
        mode_block = (
            "Mode SCREEN (HR assist): skills/seniority fit vs JD if present, gaps, "
            "communication clarity. recommendation ∈ advance|maybe|pass framed as "
            "suggestion only (never an automated hire decision).\n"
            "interview_questions: 4–8 recruiter-ready questions (paste into calendar "
            "invite); each rationale one sentence on what gap/claim to verify.\n"
            "risks_or_questions: short legacy list (may overlap interview_questions)."
        )
    else:
        mode_block = (
            "Mode IMPROVE (candidate): rewrite bullets (STAR), quantify impact, "
            "structure, JD keywords, language polish. recommendation may be n_a.\n"
            "improvements + rewritten_bullets are primary. interview_questions may be "
            "empty or 1–2 self-audit prompts for the candidate."
        )
    jd_block = (
        "A job description is provided — compute match_score and keyword gaps."
        if has_jd
        else
        "No JD — overall_score is content quality only; match_score must be null; "
        "recommendation may be n_a for improve or quality-based for screen."
    )
    return f"""You are Polymind AI's CV analysis assistant for HR and candidates.
Write all human-readable strings in {out_lang}.
{mode_block}
{jd_block}

MUST-HAVE CHECKLIST:
- Prefer discrete criteria from FOCUS / NOTES first, then from the JD.
- If neither yields discrete must-haves, use an empty array [].
- status ∈ met|partial|missing; evidence = short cite from the CV only (no invention).
- Max ~10 items. Skills/experience/education/outcomes only.

{BIAS_BLOCK}

Return ONLY a single JSON object (no markdown fences) with this shape:
{{
  "summary": "2-4 sentences",
  "overall_score": 0-100,
  "recommendation": "advance|maybe|pass|n_a",
  "match_score": null or 0-100,
  "dimensions": [{{"id":"skills|experience|education|impact|clarity|jd_alignment","label":"...","score":0-100,"notes":"..."}}],
  "strengths": ["..."],
  "gaps": ["..."],
  "risks_or_questions": ["..."],
  "must_have_checklist": [{{"item":"...","status":"met|partial|missing","evidence":"..."}}],
  "interview_questions": [{{"question":"...","rationale":"..."}}],
  "keywords": {{"present":[],"missing":[]}},
  "improvements": [{{"priority":"high|med|low","section":"...","issue":"...","suggestion":"..."}}],
  "rewritten_bullets": [{{"original":"...","improved":"..."}}],
  "language_notes": ["..."],
  "bias_check": {{"ignored_attributes_mentioned": true/false, "note": "..."}}
}}
Never include demographic scores. Do not invent employment facts not in the CV.
"""


def build_user_message(*, mode: str, cv_text: str, jd_text: str, focus: str) -> str:
    parts = [f"mode: {mode}", "", "=== CV ===", (cv_text or "").strip() or "(empty)"]
    if (jd_text or "").strip():
        parts += ["", "=== JOB DESCRIPTION ===", jd_text.strip()]
    if (focus or "").strip():
        parts += ["", "=== FOCUS / NOTES ===", focus.strip()]
    return "\n".join(parts)
