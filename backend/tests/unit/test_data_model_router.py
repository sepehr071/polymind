"""Unit tests for Data Analyzer dual-model routing (no DB / no sandbox)."""
from __future__ import annotations

import os

os.environ.setdefault("DATA_SANDBOX_MODE", "dev")

from app.services.data_model_router import (  # noqa: E402
    dual_model_enabled,
    pick_data_analysis_model,
    reasoning_effort_for_model,
)


def test_dual_enabled_by_default():
    assert dual_model_enabled() is True


def test_simple_question_uses_fast():
    mid = pick_data_analysis_model("Summarize columns and missing values")
    assert "flash" in mid


def test_complex_question_uses_heavy():
    mid = pick_data_analysis_model(
        "Run a regression of revenue on marketing spend and forecast next quarter"
    )
    assert "sonnet" in mid


def test_ambiguous_defaults_heavy():
    mid = pick_data_analysis_model("What should we do about Q3?")
    assert "sonnet" in mid


def test_reasoning_only_on_heavy():
    assert reasoning_effort_for_model("anthropic/claude-sonnet-5") == "high"
    assert reasoning_effort_for_model("google/gemini-3.5-flash-lite") is None
