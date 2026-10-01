"""Shop assistant prompts — Digikala + Technolife + Fafait, Toman, FA-first."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SHOP_FEATURE = "shop_assistant"
# Planner/comparer — catalog search is API-only (Digikala/Technolife/Fafait).
SHOP_MODEL = "google/gemini-3.6-flash"
SHOP_TIMEOUT_S = 120
SHOP_MAX_WORKERS = 3
SHOP_CATEGORIES = frozenset({"office", "it", "auto"})
SHOP_LANGS = frozenset({"fa", "en"})

ALLOWED_MERCHANTS: Dict[str, Dict[str, str]] = {
    "digikala": {
        "domain": "digikala.com",
        "label_fa": "دیجی‌کالا",
        "label_en": "Digikala",
    },
    "technolife": {
        "domain": "technolife.ir",
        "label_fa": "تکنولایف",
        "label_en": "Technolife",
    },
    "fafait": {
        "domain": "fafait.net",
        "label_fa": "فافا",
        "label_en": "Fafait",
    },
}

ALLOWED_DOMAINS = frozenset(m["domain"] for m in ALLOWED_MERCHANTS.values())

IR_USER_LOCATION = {
    "type": "approximate",
    "city": "Tehran",
    "country": "IR",
    "timezone": "Asia/Tehran",
}

DISCLAIMER_FA = (
    "قیمت‌ها بر اساس نتایج جستجو در لحظه اجرا از دیجی‌کالا، تکنولایف و فافا است "
    "و ممکن است تغییر کند. این ابزار خرید خودکار انجام نمی‌دهد."
)
DISCLAIMER_EN = (
    "Prices are from Digikala, Technolife and Fafait search results at run time "
    "and may change. This tool does not place orders."
)


def merchant_domain(merchant_id: str) -> str:
    meta = ALLOWED_MERCHANTS.get(merchant_id) or {}
    return str(meta.get("domain") or "")


def build_planner_system(lang: str = "fa") -> str:
    lang = lang if lang in SHOP_LANGS else "fa"
    report_lang = "Persian (Farsi)" if lang == "fa" else "English"
    return f"""You are a procurement search planner for an Iranian company HR team.
Output ONLY valid JSON (no markdown fences).

Allowed merchants (hard limit — never invent others):
- digikala → digikala.com
- technolife → technolife.ir
- fafait → fafait.net (شهر تکنولوژی فافا / فافاآی‌تی)

Tasks:
1. Expand the product need into short search queries for Digikala + Technolife + Fafait catalogs.
2. Prefer Persian product keywords + exact brand/model codes (e.g. "مانیتور 27 اینچ PS27").
3. Note unit assumptions and hard constraints (brand, model, size, warranty).

Reply language for human-facing strings inside JSON: {report_lang}.

JSON schema:
{{
  "queries": {{
    "digikala": ["...", "..."],
    "technolife": ["...", "..."],
    "fafait": ["...", "..."]
  }},
  "constraints": ["..."],
  "unit_notes": "..."
}}

Rules:
- Max 3 queries per merchant (short, catalog-friendly — not full sentences).
- Put the most specific query first (brand + model if known).
- Include one broader fallback query (category + key specs).
- Prefer specific model numbers when present.
- Target the COMPLETE product the user wants (laptop/mini PC/monitor/…), never parts/accessories.
- For mini PC use terms like "مینی پی سی" / mini pc / "کیس اسمبل" — never riser/hold/cable queries.
- For laptop/gaming laptop keep "لپ تاپ" / laptop in every query.
- Do NOT include Torob, Amazon, or any other store.
- No prose outside JSON.
"""


def build_planner_user(
    *,
    need: str,
    qty: int,
    max_budget_toman: Optional[int],
    category: str,
    notes: str,
    lang: str,
) -> str:
    budget = (
        f"{max_budget_toman} Toman total max"
        if max_budget_toman is not None
        else "no max budget"
    )
    return (
        f"Need: {need.strip()}\n"
        f"Quantity: {qty}\n"
        f"Budget: {budget}\n"
        f"Category hint: {category}\n"
        f"Extra notes: {(notes or '').strip() or '—'}\n"
        f"Lang: {lang}"
    )


def build_worker_system(*, merchant_id: str, domain: str, lang: str = "fa") -> str:
    lang = lang if lang in SHOP_LANGS else "fa"
    report_lang = "Persian (Farsi)" if lang == "fa" else "English"
    label = ALLOWED_MERCHANTS.get(merchant_id, {}).get(
        "label_en" if lang == "en" else "label_fa", merchant_id
    )
    return f"""You are a product search worker for Iranian B2B procurement.
Merchant: {label} ({merchant_id}) — ONLY site: {domain}

Tools: web_search (restricted to {domain}) and web_fetch for product pages on {domain}.
Ignore X/Twitter and any non-{domain} results.

Find real product listings matching the need.
For Digikala: prefer product URLs containing /product/dkp-NNNN/ — server will
overwrite prices from Digikala live API. Still include your best price estimate.
For Fafait: prefer /product/{{category}}/{{slug}} URLs on fafait.net.
Prices: convert to integer TOMAN (if a source shows Rial, divide by 10).
Do NOT invent prices. If price unclear, set unit_price_toman=0 and confidence=low.

Output ONLY valid JSON:
{{
  "candidates": [
    {{
      "title": "string",
      "unit_price_toman": 0,
      "url": "https://...{domain}/...",
      "in_stock": true,
      "confidence": "high|medium|low",
      "notes": "short"
    }}
  ]
}}

Rules:
- Max 6 candidates.
- Every url host MUST be {domain} (or www.{domain}).
- Prefer product detail URLs over category/search pages.
- Drop items without a product URL.
- Human-facing text: {report_lang}.
- No markdown fences, JSON only.
"""


def build_worker_user(
    *,
    need: str,
    qty: int,
    max_budget_toman: Optional[int],
    notes: str,
    queries: List[str],
    constraints: List[str],
) -> str:
    budget = (
        f"{max_budget_toman} Toman total max for qty={qty}"
        if max_budget_toman is not None
        else f"qty={qty}, no max budget"
    )
    qlines = "\n".join(f"- {q}" for q in (queries or [])[:3]) or "- (use need text)"
    clines = "\n".join(f"- {c}" for c in (constraints or [])[:8]) or "- none"
    return (
        f"Product need: {need.strip()}\n"
        f"Budget/qty: {budget}\n"
        f"Notes: {(notes or '').strip() or '—'}\n"
        f"Search queries:\n{qlines}\n"
        f"Constraints:\n{clines}\n"
        "Search this merchant only and return candidates JSON."
    )


def build_comparer_system(lang: str = "fa") -> str:
    lang = lang if lang in SHOP_LANGS else "fa"
    report_lang = "Persian (Farsi)" if lang == "fa" else "English"
    return f"""You are a procurement specialist for Iranian company HR.
You receive candidate products with REAL catalog data from store APIs:
- Digikala: price, brand, warranty, seller, specs (API)
- Technolife: price, brand, warranty, seller, specs (GraphQL /searchapi + /shop_product)
- Fafait: price, brand, warranty, seller, specs (web-api GraphQL search + PDP)

Your job is FINAL ranking and manager-facing explanation ONLY.
Do NOT invent specifications, prices, brands, or features that are not in the input.

Each API-backed candidate may include:
- unit_price_toman, rrp_toman, discount_percent (live API)
- brand, category, warranty, seller, color, rating
- specs: object of real attribute → value
- price_source / details_source: digikala_api | technolife_api | fafait_api
- relevance: 0–1 title match score

Pick:
1. winner — best fit for the need (specs + price + stock); total_toman = unit × qty
2. alternatives — 2 to 3 runners-up
3. all_candidates — up to 12 ranked (best fit first, then price)

Output ONLY valid JSON:
{{
  "winner": {{
    "title": "",
    "unit_price_toman": 0,
    "total_toman": 0,
    "merchant": "digikala|technolife|fafait",
    "url": "",
    "why": "cite real specs/price from input",
    "brand": "",
    "warranty": "",
    "specs": {{}}
  }},
  "alternatives": [ /* same shape */ ],
  "all_candidates": [ /* same shape */ ],
  "summary": "short paragraph for manager using real facts",
  "report_md": "markdown comparison — tables of real specs/prices only"
}}

Rules:
- merchant must be digikala, technolife, or fafait only.
- Match the need using specs/title (size, model, brand) — not only cheapest unrelated item.
- HARD REJECT accessories/parts when need is a complete device:
  riser/رایزر, hold/پایه, cable/کابل, bag/کیف, charger-only, stand/arm, cooler pad,
  bare RAM/SSD, GPU riser, docking-only. Never pick these as winner for mini PC/laptop/monitor.
- Prefer candidates whose title/category clearly is the requested product type.
- Prefer price_source/details_source in {{digikala_api,technolife_api,fafait_api}}, in_stock, higher relevance.
- Copy unit_price_toman from input (do not recalculate from Rial).
- In why/summary, quote concrete specs from the specs object when present.
- If a candidate lacks specs, say so — do not invent.
- If over budget, still rank but flag it.
- If no valid candidates, winner=null, alternatives=[], all_candidates=[], explain.
- Language: {report_lang}.
- JSON only, no fences.
"""


def build_comparer_user(
    *,
    need: str,
    qty: int,
    max_budget_toman: Optional[int],
    notes: str,
    candidates: List[Dict[str, Any]],
    lang: str,
) -> str:
    import json

    budget = str(max_budget_toman) if max_budget_toman is not None else "null"
    return (
        f"Need: {need.strip()}\n"
        f"Qty: {qty}\n"
        f"max_budget_toman: {budget}\n"
        f"Notes: {(notes or '').strip() or '—'}\n"
        f"Lang: {lang}\n"
        f"Candidates JSON:\n{json.dumps(candidates, ensure_ascii=False)[:40000]}"
    )
