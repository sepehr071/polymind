"""One-shot: print eval report summary + custom guidance rows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

p = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path(__file__).resolve().parent
    / "reports"
    / "run-20260711-semantic-guidance.json"
)
r = json.loads(p.read_text(encoding="utf-8"))
m = r["metrics"]

print("=== SUMMARY ===")
print(f"model: {r.get('model')}")
print(f"generated_at: {r.get('generated_at')}")
print(
    f"accuracy: {m['accuracy_pct']}%  N={m['n']}  correct={m['correct']}  "
    f"misses={len(r['misses'])}  fail_open={m['fail_open']}"
)
print()
print("per-class:")
for cat, pc in m["per_class"].items():
    print(
        f"  {cat:14s} P={pc['precision']:.3f} R={pc['recall']:.3f} "
        f"F1={pc['f1']:.3f} support={pc['support']}"
    )
print()
print("slices:")
for k, v in m["slices"].items():
    acc = v["accuracy"]
    acc_s = f"{100 * acc:.1f}%" if acc is not None else "n/a"
    print(f"  {k:22s} n={v['n']:<4} acc={acc_s}")
print()
print("confusion gold\\pred:")
print("               public  confid  restri  fail")
for g in ("public", "confidential", "restricted"):
    row = m["confusion"][g]
    print(
        f"  {g:12s}  {row['public']:5d}  {row['confidential']:5d}  "
        f"{row['restricted']:5d}  {row['fail_open']:4d}"
    )

print()
print("=== CUSTOM GUIDANCE ROWS ===")
g_rows = [x for x in r["rows"] if x.get("guidance_prompt")]
print(f"count={len(g_rows)}  correct={sum(1 for x in g_rows if x['correct'])}")
print()
for x in g_rows:
    status = "OK" if x["correct"] else "MISS"
    print(f"--- [{status}] {x['id']}")
    print(
        f"  gold={x['gold_category']}  pred={x['predicted']}  "
        f"lang={x['lang']}  {x['latency_ms']}ms"
    )
    print(f"  GUIDANCE: {x['guidance_prompt']}")
    print(f"  TEXT: {x['text_preview']}")
    print(f"  reason: {x.get('reason')}")
    print(f"  spans: {x.get('spans')}")
    print()

print("=== ALL MISSES ===")
for x in r["misses"]:
    print(f"- {x['id']}: gold={x['gold_category']} pred={x['predicted']}")
    print(f"  text: {x['text_preview']}")
    if x.get("guidance_prompt"):
        print(f"  guidance: {x['guidance_prompt']}")
    print(f"  reason: {x.get('reason')}")
    print(f"  spans: {x.get('spans')}")
    print()
