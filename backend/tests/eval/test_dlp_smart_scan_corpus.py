"""Offline validation of the DLP smart-scan eval corpus.

Does NOT call Ollama / OpenRouter. Safe for CI and laptop runs.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

CORPUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "eval"
    / "dlp_smart_scan"
    / "corpus.jsonl"
)

REQUIRED = {"id", "lang", "gold_category", "tags", "text"}
VALID_LANG = {"en", "fa"}
VALID_CATEGORY = {"public", "confidential", "restricted"}
MIN_TEXT_LEN = 6
MIN_PER_CATEGORY = 15
MIN_PER_LANG = 30


def _load_rows() -> list[dict]:
    assert CORPUS_PATH.is_file(), f"missing corpus: {CORPUS_PATH}"
    rows: list[dict] = []
    for i, line in enumerate(CORPUS_PATH.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            pytest.fail(f"line {i}: invalid JSON: {exc}")
        if not isinstance(obj, dict):
            pytest.fail(f"line {i}: expected object, got {type(obj).__name__}")
        rows.append(obj)
    assert rows, "corpus is empty"
    return rows


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return _load_rows()


def test_corpus_schema_and_uniqueness(rows: list[dict]) -> None:
    seen: set[str] = set()
    for i, row in enumerate(rows, 1):
        missing = REQUIRED - set(row)
        assert not missing, f"row {i} id={row.get('id')!r}: missing {missing}"
        rid = row["id"]
        assert isinstance(rid, str) and rid.strip(), f"row {i}: empty id"
        assert rid not in seen, f"duplicate id: {rid}"
        seen.add(rid)

        assert row["lang"] in VALID_LANG, f"{rid}: bad lang {row['lang']!r}"
        assert row["gold_category"] in VALID_CATEGORY, (
            f"{rid}: bad gold_category {row['gold_category']!r}"
        )
        assert isinstance(row["tags"], list) and all(
            isinstance(t, str) and t for t in row["tags"]
        ), f"{rid}: tags must be non-empty strings"
        text = row["text"]
        assert isinstance(text, str), f"{rid}: text must be str"
        assert len(text.strip()) >= MIN_TEXT_LEN, (
            f"{rid}: text shorter than smart-scan min ({MIN_TEXT_LEN})"
        )
        if "notes" in row and row["notes"] is not None:
            assert isinstance(row["notes"], str), f"{rid}: notes must be str"
        if "guidance_prompt" in row and row["guidance_prompt"] is not None:
            assert isinstance(row["guidance_prompt"], str), (
                f"{rid}: guidance_prompt must be str"
            )
            assert row["guidance_prompt"].strip(), (
                f"{rid}: guidance_prompt must be non-empty when present"
            )
            assert "guidance" in row["tags"], (
                f"{rid}: rows with guidance_prompt should tag 'guidance'"
            )


def test_corpus_balance(rows: list[dict]) -> None:
    by_cat = Counter(r["gold_category"] for r in rows)
    by_lang = Counter(r["lang"] for r in rows)
    for cat in VALID_CATEGORY:
        assert by_cat[cat] >= MIN_PER_CATEGORY, (
            f"category {cat} has {by_cat[cat]} rows, need ≥{MIN_PER_CATEGORY}"
        )
    for lang in VALID_LANG:
        assert by_lang[lang] >= MIN_PER_LANG, (
            f"lang {lang} has {by_lang[lang]} rows, need ≥{MIN_PER_LANG}"
        )


def test_topic_only_rows_are_public(rows: list[dict]) -> None:
    """Hard cases tagged topic_only must be gold=public (presence detection)."""
    for row in rows:
        if "topic_only" in row["tags"]:
            assert row["gold_category"] == "public", (
                f"{row['id']}: topic_only must be gold public, got "
                f"{row['gold_category']}"
            )


def test_value_present_not_public_unless_edge_clean(rows: list[dict]) -> None:
    """value_present should not be labeled public."""
    for row in rows:
        if "value_present" in row["tags"]:
            assert row["gold_category"] != "public", (
                f"{row['id']}: value_present tagged but gold is public"
            )
