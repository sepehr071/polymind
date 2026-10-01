#!/usr/bin/env python3
"""Evaluate DLP smart-scan category accuracy against the labeled JSONL corpus.

Intended for the **prod** host where ``DLP_LLM_BASE_URL`` points at the
self-hosted Ollama model. Calls ``DLPDetector.llm_classify`` only (no regex
merge, no chat HTTP).

Usage (on prod, with prod env loaded)::

    set -a && source /path/to/.env.prod && set +a
    export DLP_LLM_TIMEOUT=60
    python scripts/eval_dlp_smart_scan.py \\
      --corpus eval/dlp_smart_scan/corpus.jsonl \\
      --out ../reports/run.json

Local laptops without ``DLP_LLM_BASE_URL`` exit 2 (refuses silent OpenRouter).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

# Load .env before Config class attrs bind from os.environ.
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    # Prod-style env file if present (prod often uses .env.prod).
    load_dotenv(ROOT / ".env.prod", override=False)
except Exception:  # noqa: BLE001
    pass

CATEGORIES = ("public", "confidential", "restricted")
DEFAULT_CORPUS = ROOT / "eval" / "dlp_smart_scan" / "corpus.jsonl"
DEFAULT_OUT = REPO_ROOT / "reports" / "latest.json"


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DLP smart-scan category accuracy eval")
    p.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS,
        help=f"JSONL corpus path (default: {DEFAULT_CORPUS})",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Write JSON report here (default: {DEFAULT_OUT})",
    )
    p.add_argument("--limit", type=int, default=None, help="Max rows to evaluate")
    p.add_argument(
        "--ids",
        type=str,
        default=None,
        help="Only rows whose id starts with this prefix",
    )
    p.add_argument(
        "--lang",
        choices=("en", "fa"),
        default=None,
        help="Filter corpus language",
    )
    p.add_argument(
        "--tag",
        type=str,
        default=None,
        help="Only rows that include this tag",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Override DLP_LLM_TIMEOUT seconds (set BEFORE import if possible; "
        "also patched into settings after import)",
    )
    p.add_argument(
        "--smoke",
        action="store_true",
        help="Classify one clean public phrase and exit (connectivity check)",
    )
    return p.parse_args(argv)


def _load_corpus(
    path: Path,
    *,
    limit: Optional[int],
    id_prefix: Optional[str],
    lang: Optional[str],
    tag: Optional[str],
) -> list[dict[str, Any]]:
    if not path.is_file():
        raise SystemExit(f"corpus not found: {path}")
    rows: list[dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"corpus line {i}: {exc}") from exc
        if id_prefix and not str(obj.get("id", "")).startswith(id_prefix):
            continue
        if lang and obj.get("lang") != lang:
            continue
        if tag and tag not in (obj.get("tags") or []):
            continue
        rows.append(obj)
        if limit is not None and len(rows) >= limit:
            break
    if not rows:
        raise SystemExit("no corpus rows matched filters")
    return rows


def _safe_div(n: float, d: float) -> float:
    return n / d if d else 0.0


def _prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "support": tp + fn,
    }


def _metrics(rows_out: list[dict[str, Any]]) -> dict[str, Any]:
    """Fail-open (predicted=None) counts as a miss against gold."""
    n = len(rows_out)
    correct = sum(1 for r in rows_out if r["predicted"] == r["gold_category"])
    fail_open = sum(1 for r in rows_out if r["predicted"] is None)
    answered = n - fail_open
    answered_correct = sum(
        1
        for r in rows_out
        if r["predicted"] is not None and r["predicted"] == r["gold_category"]
    )

    # Confusion: gold -> predicted (None -> "fail_open")
    conf: dict[str, dict[str, int]] = {
        g: {p: 0 for p in (*CATEGORIES, "fail_open")} for g in CATEGORIES
    }
    for r in rows_out:
        pred_key = r["predicted"] if r["predicted"] in CATEGORIES else "fail_open"
        gold = r["gold_category"]
        if gold in conf:
            conf[gold][pred_key] += 1

    per_class: dict[str, dict[str, float]] = {}
    for cat in CATEGORIES:
        tp = sum(
            1
            for r in rows_out
            if r["gold_category"] == cat and r["predicted"] == cat
        )
        fp = sum(
            1
            for r in rows_out
            if r["predicted"] == cat and r["gold_category"] != cat
        )
        fn = sum(
            1
            for r in rows_out
            if r["gold_category"] == cat and r["predicted"] != cat
        )
        per_class[cat] = _prf(tp, fp, fn)

    def _slice_acc(predicate) -> dict[str, Any]:
        subset = [r for r in rows_out if predicate(r)]
        if not subset:
            return {"n": 0, "accuracy": None}
        c = sum(1 for r in subset if r["predicted"] == r["gold_category"])
        return {"n": len(subset), "accuracy": round(c / len(subset), 4)}

    slices = {
        "lang:en": _slice_acc(lambda r: r["lang"] == "en"),
        "lang:fa": _slice_acc(lambda r: r["lang"] == "fa"),
        "tag:topic_only": _slice_acc(lambda r: "topic_only" in r["tags"]),
        "tag:value_present": _slice_acc(lambda r: "value_present" in r["tags"]),
        "tag:clean": _slice_acc(lambda r: "clean" in r["tags"]),
        "tag:secret": _slice_acc(lambda r: "secret" in r["tags"]),
        "tag:pii": _slice_acc(lambda r: "pii" in r["tags"]),
        "tag:semantic": _slice_acc(lambda r: "semantic" in r["tags"]),
        "tag:guidance": _slice_acc(lambda r: "guidance" in r["tags"]),
    }

    return {
        "n": n,
        "correct": correct,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "accuracy_pct": round(100.0 * correct / n, 2) if n else 0.0,
        "fail_open": fail_open,
        "answered": answered,
        "accuracy_among_answered": (
            round(answered_correct / answered, 4) if answered else None
        ),
        "per_class": per_class,
        "confusion": conf,
        "slices": slices,
    }


def _build_detector(guidance_prompt: str = ""):
    from app.services.dlp_service import DLPDetector, effective_policy

    policy = effective_policy(
        {
            "enabled": True,
            "llm_classifier": {
                "enabled": True,
                "guidance_prompt": guidance_prompt or "",
            },
        }
    )
    return DLPDetector(policy, workspace_id=None)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    # Timeout override must hit os.environ before Config is imported when
    # possible; we also patch settings after import for late overrides.
    if args.timeout is not None:
        os.environ["DLP_LLM_TIMEOUT"] = str(args.timeout)

    from app.services import dlp_service as dlp_svc
    from app.services.dlp_service import dlp_locked_model
    from app.settings import settings

    if args.timeout is not None:
        settings["DLP_LLM_TIMEOUT"] = int(args.timeout)

    base = (settings.get("DLP_LLM_BASE_URL") or "").strip()
    if not base:
        print(
            "ERROR: DLP_LLM_BASE_URL is empty. This eval must run on prod "
            "with the Ollama backend configured (refusing OpenRouter path).",
            file=sys.stderr,
        )
        return 2

    model = dlp_locked_model()
    print(f"DLP_LLM_BASE_URL={base}")
    print(f"model={model}")
    print(f"timeout={settings.get('DLP_LLM_TIMEOUT')}s")

    # Fresh cache for independent runs.
    dlp_svc._LLM_CACHE.clear()

    if args.smoke:
        detector = _build_detector("")
        t0 = time.perf_counter()
        verdict = detector.llm_classify(
            "Hello, can you summarize this meeting for me?",
            user_lang="en",
        )
        ms = (time.perf_counter() - t0) * 1000
        print(f"smoke verdict={verdict!r} latency_ms={ms:.0f}")
        return 0 if verdict is not None else 1

    rows = _load_corpus(
        args.corpus,
        limit=args.limit,
        id_prefix=args.ids,
        lang=args.lang,
        tag=args.tag,
    )
    print(f"corpus={args.corpus.resolve()} rows={len(rows)}")

    results: list[dict[str, Any]] = []
    # Rebuild detector when guidance changes (policy is fixed at construct time).
    current_guidance: Optional[str] = None
    detector = None

    for idx, row in enumerate(rows, 1):
        rid = row["id"]
        text = row["text"]
        lang = row.get("lang") or "en"
        gold = row["gold_category"]
        tags = list(row.get("tags") or [])
        guidance = (row.get("guidance_prompt") or "").strip()

        if detector is None or guidance != current_guidance:
            current_guidance = guidance
            detector = _build_detector(guidance)
            # Guidance is part of the LLM cache key, but clear anyway so
            # consecutive policy flips never see a stale hit.
            dlp_svc._LLM_CACHE.clear()

        t0 = time.perf_counter()
        try:
            verdict = detector.llm_classify(text, user_lang=lang)
        except Exception as exc:  # noqa: BLE001 — fail-open parity
            verdict = None
            err = f"{type(exc).__name__}: {exc}"
        else:
            err = None
        ms = (time.perf_counter() - t0) * 1000

        if verdict is None:
            predicted = None
            reason = None
            spans: list[str] = []
        else:
            predicted = verdict.get("category")
            if predicted not in CATEGORIES:
                predicted = None
            reason = (verdict.get("reason") or "")[:200]
            spans = list(verdict.get("spans") or [])[:10]

        hit = predicted == gold
        g_tag = " +guidance" if guidance else ""
        print(
            f"[{idx}/{len(rows)}] {'OK' if hit else 'MISS'} {rid} "
            f"gold={gold} pred={predicted} {ms:.0f}ms{g_tag}"
            + (f" err={err}" if err else "")
        )
        results.append(
            {
                "id": rid,
                "lang": lang,
                "gold_category": gold,
                "predicted": predicted,
                "correct": hit,
                "tags": tags,
                "guidance_prompt": guidance or None,
                "latency_ms": round(ms, 1),
                "reason": reason,
                "spans": spans,
                "error": err,
                "text_preview": text[:120],
            }
        )

    metrics = _metrics(results)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "dlp_llm_base_url": base,
        "timeout_s": settings.get("DLP_LLM_TIMEOUT"),
        "corpus": str(args.corpus.resolve()),
        "filters": {
            "limit": args.limit,
            "ids": args.ids,
            "lang": args.lang,
            "tag": args.tag,
        },
        "metrics": metrics,
        "misses": [r for r in results if not r["correct"]],
        "rows": results,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Smart-scan category accuracy: {metrics['accuracy_pct']:.1f}% "
        f"(N={metrics['n']}, model={model})"
    )
    print(
        f"  correct={metrics['correct']}  fail_open={metrics['fail_open']}  "
        f"accuracy_among_answered={metrics['accuracy_among_answered']}"
    )
    print("  per-class F1:")
    for cat in CATEGORIES:
        pc = metrics["per_class"][cat]
        print(
            f"    {cat:14s}  P={pc['precision']:.3f}  R={pc['recall']:.3f}  "
            f"F1={pc['f1']:.3f}  support={pc['support']}"
        )
    print("  confusion (gold \\ pred):")
    header = " " * 14 + "  ".join(f"{c[:6]:>8}" for c in (*CATEGORIES, "fail_open"))
    print(header)
    for g in CATEGORIES:
        cells = "  ".join(
            f"{metrics['confusion'][g][p]:>8}" for p in (*CATEGORIES, "fail_open")
        )
        print(f"  {g:12s}  {cells}")
    print("  slices:")
    for name, sl in metrics["slices"].items():
        acc = sl["accuracy"]
        acc_s = f"{100 * acc:.1f}%" if acc is not None else "n/a"
        print(f"    {name:22s}  n={sl['n']:<4}  acc={acc_s}")
    print(f"report written: {args.out.resolve()}")

    # Gold histogram for the filtered run.
    gold_counts = Counter(r["gold_category"] for r in results)
    print("  gold distribution:", dict(gold_counts))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
