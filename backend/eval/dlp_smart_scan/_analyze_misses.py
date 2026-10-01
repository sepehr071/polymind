"""Print miss analysis for latest smart-scan report."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

REPORT = Path(__file__).resolve().parent / "reports" / "run-20260711-fa-policy-286.json"
r = json.loads(REPORT.read_text(encoding="utf-8"))
misses = r["misses"]
print("total_misses", len(misses))
print("gold->pred", Counter((m["gold_category"], m["predicted"]) for m in misses))
print()


def bucket(m: dict) -> str:
    tags = set(m.get("tags") or [])
    if "fa_policy" in tags:
        return "fa_policy"
    if "guidance" in tags:
        return "guidance"
    if "adversarial" in tags:
        return "adversarial"
    if "semantic" in tags:
        return "semantic"
    if "topic_only" in tags:
        return "topic_only"
    return "other"


by: dict[str, list] = defaultdict(list)
for m in misses:
    by[bucket(m)].append(m)

for k, items in sorted(by.items(), key=lambda x: -len(x[1])):
    print(f"=== {k} ({len(items)}) ===")
    for m in items:
        print(m["id"])
        print(
            f"  gold={m['gold_category']} pred={m['predicted']} "
            f"lang={m['lang']} tags={m.get('tags')}"
        )
        print(f"  text: {(m.get('text_preview') or '')[:160]}")
        if m.get("guidance_prompt"):
            g = m["guidance_prompt"]
            print(f"  guidance: {g[:160]}{'...' if len(g) > 160 else ''}")
        print(f"  reason: {m.get('reason')}")
        print(f"  spans: {m.get('spans')}")
        print()
