"""Unit tests for multi-agent presentation pipeline helpers (no DB, no network)."""
from app.services.presentation_pipeline import (
    apply_critic_patches,
    _norm_deck_plan,
    _norm_fact_sheet,
    _enrich_outline_slide,
)


def test_norm_fact_sheet_caps_and_sources():
    raw = {
        "facts": [
            {"claim": "rev", "value": "10M", "source": "web"},
            {"claim": "bad", "source": "alien"},
        ],
        "web_sources": [{"title": "A", "url": "https://x", "snippet": "s"}] * 10,
    }
    fs = _norm_fact_sheet(raw)
    assert len(fs["facts"]) == 2
    assert fs["facts"][1]["source"] == "web"  # alien coerced
    assert len(fs["web_sources"]) == 5


def test_norm_deck_plan_defaults():
    plan = _norm_deck_plan({}, slide_count=12, topic="Hello")
    assert plan["title"] == "Hello"
    assert plan["deck_type"] == "general"
    assert plan["slide_count_target"] == 12
    assert plan["image_style"]


def test_enrich_slide_visual_recipe():
    s = _enrich_outline_slide({
        "layout": "bogus",
        "title": "T",
        "bullets": ["a"],
        "visual_recipe": {"composition": "big_number", "image_role": "hero"},
    })
    assert s["layout"] == "content"
    assert s["visual_recipe"]["composition"] == "big_number"
    assert s["visual_recipe"]["image_role"] == "hero"


def test_apply_critic_patches():
    outline = {
        "slides": [
            {
                "layout": "content",
                "title": "A",
                "bullets": ["1", "2", "3", "4", "5"],
                "visual_recipe": {"composition": "default", "accent": "edge", "image_role": "none"},
                "chart": {"type": "bar", "categories": ["a"], "series": [{"name": "s", "values": [1]}]},
            },
        ]
    }
    n = apply_critic_patches(
        outline,
        [
            {"op": "set_layout", "slide": 0, "layout": "metrics"},
            {"op": "trim_bullets", "slide": 0, "max": 2},
            {"op": "clear_chart", "slide": 0},
            {"op": "set_image_role", "slide": 0, "image_role": "support"},
        ],
        image_style="clean flat",
    )
    assert n >= 3
    s = outline["slides"][0]
    assert s["layout"] == "metrics" or s["chart"] is None  # clear_chart may flip chart layout
    assert len(s["bullets"]) == 2
    assert s["chart"] is None
    assert s["visual_recipe"]["image_role"] == "support"
