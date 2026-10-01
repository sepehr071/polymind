"""Pick Data Analyzer LLM: heavy (Sonnet) vs fast (Flash) from the user question.

Dual-model path keeps simple describe/schema asks cheap while complex stats,
joins, and modeling stay on the strong tool-calling model.

Env (via settings / Config):
  DATA_ANALYSIS_MODEL       — heavy default (anthropic/claude-sonnet-5)
  DATA_ANALYSIS_MODEL_FAST  — light default (google/gemini-3.5-flash-lite)
  DATA_ANALYSIS_DUAL_MODEL  — '1' (default) enables routing; '0' always heavy
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from app.settings import settings

# Strong tool-loop model — must emit show_chart/show_table helpers reliably.
_DEFAULT_HEAVY = "anthropic/claude-sonnet-5"
# Cheaper model for simple inspect/aggregate turns.
_DEFAULT_FAST = "google/gemini-3.5-flash-lite"

# Signals that need careful multi-step code / stats (always heavy).
_COMPLEX_RE = re.compile(
    r"(?i)\b("
    r"regress|regression|forecast|arima|ets|holt|cluster|k-?means|segment|"
    r"anova|t-?test|chi-?square|hypothesis|correlat|p-?value|significant|"
    r"join|merge|union|pivot|unpivot|reshape|"
    r"predict|classif|model|train|feature engineering|"
    r"causal|cohort|funnel|attribution|ab\s*test|a/b|"
    r"clean\s+and|export\s+and|then\s+export|multi-?step"
    r")\b"
)

# Simple inspect / summary asks (eligible for fast when short + no complex hits).
_SIMPLE_RE = re.compile(
    r"(?i)\b("
    r"describe|summary|summarize|overview|"
    r"columns?|dtypes?|schema|shape|head|preview|"
    r"missing|nulls?|nan|empty|"
    r"how many (rows?|columns?)|row count|count rows?|"
    r"what('s| is) in|list columns?|show columns?|"
    r"unique values?|value counts?|min|max|mean|median|average|"
    r"top\s+\d+|bottom\s+\d+|bar chart|line chart|pie chart|histogram|"
    r"خلاصه|ستون|سطر|ردیف|نمودار|میانگین|خالی"
    r")\b"
)


def data_analysis_models() -> Tuple[str, str]:
    """Return ``(heavy_model_id, fast_model_id)`` from config."""
    heavy = (
        str(settings.get("DATA_ANALYSIS_MODEL") or _DEFAULT_HEAVY).strip()
        or _DEFAULT_HEAVY
    )
    fast = (
        str(settings.get("DATA_ANALYSIS_MODEL_FAST") or _DEFAULT_FAST).strip()
        or _DEFAULT_FAST
    )
    return heavy, fast


def dual_model_enabled() -> bool:
    raw = str(settings.get("DATA_ANALYSIS_DUAL_MODEL", "1") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no", "disabled"}


def pick_data_analysis_model(user_text: Optional[str]) -> str:
    """Choose model id for this Data Analyzer turn.

    - Dual off → always heavy
    - Complex keywords → heavy
    - Short simple inspect/summary → fast
    - Default → heavy (prefer correctness on ambiguous asks)
    """
    heavy, fast = data_analysis_models()
    if not dual_model_enabled():
        return heavy
    text = (user_text or "").strip()
    if not text:
        return heavy
    if _COMPLEX_RE.search(text):
        return heavy
    if len(text) <= 320 and _SIMPLE_RE.search(text):
        return fast
    return heavy


def reasoning_effort_for_model(model_id: str) -> Optional[str]:
    """High reasoning only on heavy/capable models; skip on flash for latency/cost."""
    heavy, _fast = data_analysis_models()
    mid = (model_id or "").lower()
    if model_id == heavy:
        return "high"
    if any(tok in mid for tok in ("sonnet", "opus", "o1", "o3", "o4", "reasoning")):
        return "high"
    return None
