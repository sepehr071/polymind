"""Shop assistant — multi-agent Digikala + Technolife + Fafait price compare."""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, urlencode, urlparse

import requests

from app.prompts.shop import (
    ALLOWED_DOMAINS,
    ALLOWED_MERCHANTS,
    DISCLAIMER_EN,
    DISCLAIMER_FA,
    IR_USER_LOCATION,
    SHOP_FEATURE,
    SHOP_MODEL,
    SHOP_TIMEOUT_S,
    build_comparer_system,
    build_comparer_user,
    build_planner_system,
    build_planner_user,
    build_worker_system,
    build_worker_user,
    merchant_domain,
)
from app.services.openrouter_service import OpenRouterService

logger = logging.getLogger(__name__)

StatusCb = Optional[Callable[[str, Dict[str, Any]], None]]

# Digikala public APIs — prices always Rial.
_DIGIKALA_PRODUCT_API = "https://api.digikala.com/v2/product/{pid}/"
_DIGIKALA_SEARCH_API = "https://api.digikala.com/v1/search/"
_DIGIKALA_ID_RE = re.compile(r"(?:dkp[-/])(\d+)", re.I)
# Technolife GraphQL services (discovered 2026-07 via browser Network).
_TECHNOLIFE_SEARCH_GQL = "https://www.technolife.com/searchapi"
_TECHNOLIFE_PRODUCT_GQL = "https://www.technolife.com/shop_product"
_TECHNOLIFE_CODE_RE = re.compile(r"(?:TLP-|product-)(\d+)", re.I)
# Fafait Apollo persisted GraphQL (discovered 2026-07 via Chrome Network).
_FAFAIT_GQL = "https://web-api.fafait.net/api/graphql"
_FAFAIT_SEARCH_SHA = (
    "038a63c9466d9e4cf988d1fa4549526eca5bc0bf3c20bb7f1e8c5f8a180d0357"
)
_FAFAIT_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.S,
)
_HTTP_UA = (
    "Mozilla/5.0 (compatible; PolymindShopBot/1.0; +https://unichat.example.com)"
)
_DIGIKALA_SEARCH_PER_QUERY = 10
_DIGIKALA_SEARCH_MAX_TOTAL = 14
_TECHNOLIFE_SEARCH_MAX = 12
_FAFAIT_SEARCH_MAX = 12
# Full product detail (specs) for top candidates before LLM compare.
_DIGIKALA_DETAIL_MAX = 8
_TECHNOLIFE_DETAIL_MAX = 6
_FAFAIT_DETAIL_MAX = 6
_DIGIKALA_SPEC_MAX = 36
_API_PRICE_SOURCES = frozenset({"digikala_api", "technolife_api", "fafait_api"})

# Product-family hard filters: drop accessories / wrong category before LLM rank.
# need_re → detect family from user need; title_ok → must look like that product;
# reject → accessory/part patterns for that family.
_PRODUCT_FAMILIES: Dict[str, Dict[str, re.Pattern[str]]] = {
    "mini_pc": {
        "need": re.compile(
            r"مینی\s*پی[\s‌]*سی|mini\s*pc|minipc|مینی\s*کامپیوتر|مینی\s*کیس|"
            r"کامپیوتر\s*کوچک|barebone|mac\s*mini|مک\s*مینی",
            re.I,
        ),
        # Digikala catalog term = «کامپیوتر کوچک»; also NUC / Mac Mini / brand mini boxes.
        "ok": re.compile(
            r"مینی\s*پی[\s‌]*سی|mini\s*pc|minipc|مینی\s*کامپیوتر|مینی\s*کیس|"
            r"کامپیوتر\s*کوچک|کامپیوتر\s*مینی|mac\s*mini|مک\s*مینی|"
            r"barebone|intel\s*nuc|\bnuc\b|deskmini|deskmeet|beelink|minisforum|"
            r"genmachine|blackview|cubi|mini\s*desktop|مینی\s*دسکتاپ|"
            r"تین\s*کلاینت|thin\s*client|net\s*computer|نت\s*کامپیوتر",
            re.I,
        ),
        "reject": re.compile(
            r"رایزر|riser|پایه|hold|براکت|bracket|کابل|cable|آداپتور|adapter|"
            r"داکینگ|dock(?:ing)?|کیف|bag|شارژر|charger|فن\b|fan\b|خنک.?کننده|"
            r"cooler|رم\b|\bram\b|\bssd\b|هارد|hard\s*disk|کارت\s*گرافیک|"
            r"gpu\s*riser|نگهدارنده|mount|لیبل|label|کش\s*مینی|کمپرسور",
            re.I,
        ),
    },
    "laptop": {
        "need": re.compile(
            r"لپ[\s‌]*تاپ|laptop|notebook|نوت[\s‌]*بوک|گیمینگ\s*لپ",
            re.I,
        ),
        "ok": re.compile(
            r"لپ[\s‌]*تاپ|laptop|notebook|نوت[\s‌]*بوک",
            re.I,
        ),
        "reject": re.compile(
            r"کیف|bag|کوله|ماوس|mouse|پد\s*خنک|cooler\s*pad|شارژر|charger|"
            r"پایه\s*لپ|laptop\s*stand|اسکین|skin|استیکر|کابل|cable|"
            r"باتری\s*لپ|laptop\s*battery|رم\s*لپ|ssd\s*لپ",
            re.I,
        ),
    },
    "monitor": {
        "need": re.compile(r"مانیتور|monitor|نمایشگر", re.I),
        "ok": re.compile(r"مانیتور|monitor|نمایشگر", re.I),
        "reject": re.compile(
            r"پایه\s*مانیتور|monitor\s*stand|بازوی|monitor\s*arm|wall\s*mount|"
            r"کابل|cable|hdmi\s*کابل|حفاظ|screen\s*protector|کاور\s*مانیتور",
            re.I,
        ),
    },
}


def _content_text(result: dict) -> str:
    choices = result.get("choices") or []
    if not choices:
        return ""
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = ""
    if isinstance(message, dict):
        content = message.get("content") or ""
    if isinstance(content, list):
        content = "\n".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("text")
        )
    return (content or "").strip()


def _parse_json(raw: str) -> dict:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start : end + 1]
    return json.loads(raw)


def host_allowed(url: str, domain: Optional[str] = None) -> bool:
    """True if URL host is allowed merchant (or specific domain)."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    if domain:
        d = domain.lower().lstrip(".")
        return host == d or host.endswith("." + d)
    for d in ALLOWED_DOMAINS:
        if host == d or host.endswith("." + d):
            return True
    return False


def merchant_from_url(url: str) -> Optional[str]:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return None
    for mid, meta in ALLOWED_MERCHANTS.items():
        d = meta["domain"]
        if host == d or host.endswith("." + d):
            return mid
    return None


def normalize_price_toman(
    value: Any,
    *,
    label: str = "",
) -> Optional[int]:
    """Parse a price-ish value into integer Toman.

    Heuristic: if label/text mentions ریال or rial, divide by 10.
    Very large bare numbers (>= 1e9) without toman context also treated as Rial.
    """
    if value is None:
        return None
    text = ""
    if isinstance(value, str):
        text = value
        digits = re.sub(r"[^\d]", "", value.replace("٬", "").replace(",", ""))
        if not digits:
            return None
        try:
            n = int(digits)
        except ValueError:
            return None
    elif isinstance(value, (int, float)):
        n = int(value)
    else:
        return None

    blob = (label or text or "").lower()
    is_rial = ("ریال" in blob) or ("rial" in blob)
    is_toman = ("تومان" in blob) or ("toman" in blob)
    if is_rial and not is_toman:
        n = n // 10
    elif not is_toman and not is_rial and n >= 1_000_000_000:
        # Likely Rial for high-ticket items when unit is ambiguous
        n = n // 10
    if n <= 0:
        return None
    return n


def filter_candidates(
    raw_list: Any,
    *,
    merchant_id: str,
    domain: str,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(raw_list, list):
        return out
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url or not host_allowed(url, domain):
            continue
        raw_price = item.get("unit_price_toman") or item.get("price") or item.get("price_toman")
        price = normalize_price_toman(
            raw_price,
            label=str(item.get("notes") or item.get("title") or ""),
        )
        # Digikala: allow missing/0 model price — live API refresh fills it.
        if price is None or price <= 0:
            if merchant_id == "digikala" and digikala_product_id(url):
                price = 0
            else:
                continue
        title = str(item.get("title") or "").strip()
        if not title:
            title = "product"
        conf = str(item.get("confidence") or "medium").lower()
        if conf not in ("high", "medium", "low"):
            conf = "medium"
        out.append({
            "title": title[:300],
            "unit_price_toman": price,
            "merchant": merchant_id,
            "url": url,
            "in_stock": bool(item.get("in_stock", True)),
            "confidence": conf,
            "notes": str(item.get("notes") or "")[:400],
            "price_source": "model",
        })
    return out[:6]


def dedupe_candidates(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for c in items:
        key = f"{c.get('merchant')}|{re.sub(r'\s+', ' ', (c.get('title') or '').lower()).strip()[:80]}"
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def digikala_product_id(url: str) -> Optional[str]:
    """Extract numeric product id from digikala product URL (dkp-123 / dkp/123)."""
    if not url:
        return None
    m = _DIGIKALA_ID_RE.search(url)
    return m.group(1) if m else None


def digikala_product_url(pid: str | int) -> str:
    return f"https://www.digikala.com/product/dkp-{pid}/"


def _rial_to_toman(rial: Any) -> Optional[int]:
    """Digikala catalog prices are Rial → integer Toman (/10)."""
    try:
        n = int(rial)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return n // 10


def _as_toman_int(value: Any) -> Optional[int]:
    """Technolife GraphQL prices are already Toman (not Rial)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return n


def _product_from_digikala_row(row: dict, *, query: str = "") -> Optional[Dict[str, Any]]:
    """Map Digikala search/product API row → shop candidate (Toman, live)."""
    if not isinstance(row, dict):
        return None
    pid = row.get("id")
    if pid is None:
        return None
    title = str(row.get("title_fa") or row.get("title_en") or "").strip()
    if not title:
        return None
    variant = row.get("default_variant") or {}
    if not isinstance(variant, dict):
        variant = {}
    price_obj = variant.get("price") if isinstance(variant.get("price"), dict) else {}
    toman = _rial_to_toman(price_obj.get("selling_price"))
    if toman is None:
        return None
    status = str(row.get("status") or variant.get("status") or "").lower()
    in_stock = status in ("marketable", "in_stock", "available", "")
    url = digikala_product_url(pid)
    # relevance: crude token overlap (need words in title)
    score = _relevance_score(query, title)
    return {
        "title": title[:300],
        "unit_price_toman": toman,
        "merchant": "digikala",
        "url": url,
        "in_stock": in_stock,
        "confidence": "high",
        "notes": f"live search · q={query[:60]}" if query else "live search",
        "price_source": "digikala_api",
        "product_id": str(pid),
        "relevance": score,
    }


def _relevance_score(query: str, title: str) -> float:
    """0–1 token overlap (Latin+Persian alnum tokens) + product-family boost/penalty."""
    def toks(s: str) -> set[str]:
        s = (s or "").lower()
        parts = re.findall(r"[a-z0-9\u0600-\u06ff]{2,}", s)
        return {p for p in parts if p not in {"the", "and", "for", "با", "از", "در", "به"}}

    qt, tt = toks(query), toks(title)
    if not qt or not tt:
        return 0.0
    score = len(qt & tt) / max(1, len(qt))
    family = detect_product_family(query)
    if family:
        cfg = _PRODUCT_FAMILIES[family]
        blob = title or ""
        if cfg["reject"].search(blob):
            return min(score, 0.05)
        if cfg["ok"].search(blob):
            score = min(1.0, score + 0.35)
        else:
            score *= 0.25
    return score


def detect_product_family(need: str) -> Optional[str]:
    """Map need text → product family key (mini_pc/laptop/monitor) or None."""
    text = (need or "").strip()
    if not text:
        return None
    # Order matters: mini_pc before generic PC-ish laptop checks.
    for name, cfg in _PRODUCT_FAMILIES.items():
        if cfg["need"].search(text):
            return name
    return None


def is_relevant_product(
    need: str,
    title: str,
    *,
    category: str = "",
) -> bool:
    """Hard gate: drop accessories / wrong product type for known families."""
    family = detect_product_family(need)
    if not family:
        return True
    cfg = _PRODUCT_FAMILIES[family]
    blob = f"{title or ''} {category or ''}"
    if cfg["reject"].search(blob):
        return False
    return bool(cfg["ok"].search(blob))


def filter_relevant_candidates(
    need: str,
    candidates: List[Dict[str, Any]],
    *,
    min_relevance: float = 0.12,
) -> List[Dict[str, Any]]:
    """Keep only products that match the need family; drop pure accessories."""
    if not candidates:
        return []
    family = detect_product_family(need)
    kept: List[Dict[str, Any]] = []
    for c in candidates:
        title = str(c.get("title") or "")
        cat = str(c.get("category") or "")
        if family and not is_relevant_product(need, title, category=cat):
            continue
        if not family and float(c.get("relevance") or 0) < min_relevance:
            continue
        kept.append(c)
    # Fail closed when family known (better empty than GPU riser as mini PC).
    # Fail open only when no family detected and filter wiped everything.
    if kept:
        return kept
    if family:
        return []
    return list(candidates)


def apply_soft_budget(
    candidates: List[Dict[str, Any]],
    *,
    qty: int,
    max_budget_toman: Optional[int],
    slack: float = 1.12,
) -> List[Dict[str, Any]]:
    """Prefer under-budget; if none under, keep all (flag later in LLM)."""
    if not candidates or max_budget_toman is None:
        return candidates
    try:
        cap = int(max_budget_toman) * max(1, int(qty)) * float(slack)
    except (TypeError, ValueError):
        return candidates
    if cap <= 0:
        return candidates
    within = [
        c for c in candidates
        if int(c.get("unit_price_toman") or 0) * max(1, int(qty)) <= cap
    ]
    return within if within else candidates


def search_digikala_api(
    query: str,
    *,
    max_results: int = _DIGIKALA_SEARCH_PER_QUERY,
    timeout: float = 15.0,
) -> List[Dict[str, Any]]:
    """Live Digikala catalog search — accurate products + selling prices."""
    q = (query or "").strip()
    if not q:
        return []
    try:
        r = requests.get(
            _DIGIKALA_SEARCH_API,
            params={"q": q, "page": 1},
            headers={"User-Agent": _HTTP_UA, "Accept": "application/json"},
            timeout=timeout,
            proxies={"http": None, "https": None},
        )
        if r.status_code != 200:
            logger.info("digikala search status=%s q=%r", r.status_code, q[:80])
            return []
        data = r.json()
    except Exception as exc:
        logger.info("digikala search failed q=%r: %s", q[:80], exc)
        return []

    products = (data or {}).get("data", {}).get("products") or []
    if not isinstance(products, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in products[: max(1, max_results)]:
        c = _product_from_digikala_row(row, query=q)
        if c:
            out.append(c)
    return out


def search_digikala_multi(queries: List[str]) -> List[Dict[str, Any]]:
    """Run several Digikala search queries; merge by product_id, keep best relevance."""
    qs = [str(q).strip() for q in (queries or []) if str(q).strip()][:4]
    if not qs:
        return []
    by_id: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(qs))) as pool:
        futs = {pool.submit(search_digikala_api, q): q for q in qs}
        for fut in as_completed(futs):
            q = futs[fut]
            try:
                rows = fut.result() or []
            except Exception as exc:
                logger.info("digikala multi q=%r: %s", q[:60], exc)
                rows = []
            for c in rows:
                pid = str(c.get("product_id") or "")
                if not pid:
                    continue
                prev = by_id.get(pid)
                if prev is None or float(c.get("relevance") or 0) > float(prev.get("relevance") or 0):
                    by_id[pid] = c
    merged = list(by_id.values())
    # Rank: relevance desc, then price asc
    merged.sort(
        key=lambda c: (
            -float(c.get("relevance") or 0),
            int(c.get("unit_price_toman") or 10**18),
        )
    )
    return merged[:_DIGIKALA_SEARCH_MAX_TOTAL]


def extract_digikala_specs(product: dict) -> Dict[str, str]:
    """Flatten Digikala ``specifications`` blocks → {attr_title: values}."""
    out: Dict[str, str] = {}
    if not isinstance(product, dict):
        return out
    specs = product.get("specifications") or []
    if not isinstance(specs, list):
        return out
    for block in specs:
        if not isinstance(block, dict):
            continue
        attrs = block.get("attributes") or block.get("attributes_list") or []
        if not isinstance(attrs, list):
            continue
        for attr in attrs:
            if not isinstance(attr, dict):
                continue
            title = str(attr.get("title") or attr.get("name") or "").strip()
            if not title:
                continue
            values = attr.get("values")
            if values is None:
                values = attr.get("value")
            if isinstance(values, list):
                val = "، ".join(str(v).strip() for v in values if v is not None and str(v).strip())
            else:
                val = str(values or "").strip()
            if not val:
                continue
            out[title[:100]] = val[:240]
            if len(out) >= _DIGIKALA_SPEC_MAX:
                return out
    return out


def _digikala_get_json(url: str, *, timeout: float = 12.0) -> Optional[dict]:
    try:
        r = requests.get(
            url,
            headers={"User-Agent": _HTTP_UA, "Accept": "application/json"},
            timeout=timeout,
            proxies={"http": None, "https": None},
        )
        if r.status_code != 200:
            return None
        data = r.json()
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.info("digikala GET %s failed: %s", url[:80], exc)
        return None


def fetch_digikala_detail(pid: str, *, timeout: float = 12.0) -> Optional[Dict[str, Any]]:
    """Full Digikala product detail: live price + brand + specs + warranty.

    Used so LLM comparer ranks on real catalog facts, not search snippets.
    """
    pid = str(pid or "").strip()
    if not pid.isdigit():
        return None
    data = _digikala_get_json(_DIGIKALA_PRODUCT_API.format(pid=pid), timeout=timeout)
    if not data:
        return None
    product = (data.get("data") or {}).get("product") or {}
    if not isinstance(product, dict) or not product:
        return None

    variant = product.get("default_variant") or {}
    if not isinstance(variant, dict):
        variant = {}
    price_obj = variant.get("price") if isinstance(variant.get("price"), dict) else {}
    toman = _rial_to_toman(price_obj.get("selling_price"))
    rrp = _rial_to_toman(price_obj.get("rrp_price"))
    if toman is None:
        return None

    status = str(product.get("status") or variant.get("status") or "").lower()
    in_stock = status in ("marketable", "in_stock", "available", "")
    title = str(product.get("title_fa") or product.get("title_en") or "").strip()

    brand = product.get("brand") if isinstance(product.get("brand"), dict) else {}
    category = product.get("category") if isinstance(product.get("category"), dict) else {}
    warranty = variant.get("warranty") if isinstance(variant.get("warranty"), dict) else {}
    seller = variant.get("seller") if isinstance(variant.get("seller"), dict) else {}
    rating = product.get("rating") if isinstance(product.get("rating"), dict) else {}
    review = product.get("review") if isinstance(product.get("review"), dict) else {}
    expert = product.get("expert_reviews") if isinstance(product.get("expert_reviews"), dict) else {}
    desc = str(
        review.get("description")
        or expert.get("description")
        or ""
    ).strip()

    color = variant.get("color") if isinstance(variant.get("color"), dict) else {}
    specs = extract_digikala_specs(product)

    return {
        "product_id": pid,
        "unit_price_toman": toman,
        "rrp_toman": rrp,
        "discount_percent": price_obj.get("discount_percent"),
        "title": title or None,
        "in_stock": in_stock,
        "price_source": "digikala_api",
        "confidence": "high",
        "brand": str(brand.get("title_fa") or brand.get("title_en") or "").strip() or None,
        "category": str(category.get("title_fa") or category.get("title_en") or "").strip() or None,
        "warranty": str(warranty.get("title_fa") or warranty.get("title") or "").strip() or None,
        "seller": str(seller.get("title") or seller.get("name") or "").strip() or None,
        "color": str(color.get("title") or color.get("hex_code") or "").strip() or None,
        "rating": rating.get("rate"),
        "rating_count": rating.get("count"),
        "specs": specs,
        "description": (desc[:600] if desc else None),
        "url": digikala_product_url(pid),
    }


def fetch_digikala_live(url: str, *, timeout: float = 12.0) -> Optional[Dict[str, Any]]:
    """Live price (+detail if available) from Digikala product API."""
    pid = digikala_product_id(url)
    if not pid:
        return None
    return fetch_digikala_detail(pid, timeout=timeout)


def enrich_candidates_with_details(
    candidates: List[Dict[str, Any]],
    *,
    max_detail: int = _DIGIKALA_DETAIL_MAX,
) -> List[Dict[str, Any]]:
    """Attach full Digikala/Technolife/Fafait API specs to top candidates for LLM ranking."""
    if not candidates:
        return candidates

    digi_idxs = [
        i for i, c in enumerate(candidates)
        if c.get("merchant") == "digikala" and (
            c.get("product_id") or digikala_product_id(str(c.get("url") or ""))
        )
    ][: max(0, max_detail)]
    tl_idxs = [
        i for i, c in enumerate(candidates)
        if c.get("merchant") == "technolife" and (
            c.get("product_id") or technolife_product_code(str(c.get("url") or ""))
        )
    ][:_TECHNOLIFE_DETAIL_MAX]
    fa_idxs = [
        i for i, c in enumerate(candidates)
        if c.get("merchant") == "fafait" and str(c.get("url") or "").strip()
    ][:_FAFAIT_DETAIL_MAX]

    def _fetch(i: int) -> tuple[int, Optional[dict], str]:
        c = candidates[i]
        mid = c.get("merchant")
        if mid == "digikala":
            pid = str(c.get("product_id") or digikala_product_id(str(c.get("url") or "")) or "")
            return i, (fetch_digikala_detail(pid) if pid else None), "digikala_api"
        if mid == "fafait":
            return i, fetch_fafait_detail(str(c.get("url") or "")), "fafait_api"
        code = technolife_product_code(str(c.get("product_id") or c.get("url") or ""))
        return i, (fetch_technolife_detail(code) if code else None), "technolife_api"

    details: Dict[int, tuple[dict, str]] = {}
    idxs = digi_idxs + tl_idxs + fa_idxs
    if idxs:
        with ThreadPoolExecutor(max_workers=min(6, len(idxs))) as pool:
            for i, det, src in pool.map(_fetch, idxs):
                if det:
                    details[i] = (det, src)

    out: List[Dict[str, Any]] = []
    for i, c in enumerate(candidates):
        row = dict(c)
        packed = details.get(i)
        if packed:
            det, src = packed
            row["unit_price_toman"] = det["unit_price_toman"]
            row["price_source"] = src
            row["confidence"] = "high"
            row["in_stock"] = bool(det.get("in_stock", True))
            row["product_id"] = det.get("product_id") or row.get("product_id")
            if det.get("title"):
                row["title"] = det["title"][:300]
            for k in (
                "brand", "category", "warranty", "seller", "color",
                "rating", "rating_count", "rrp_toman", "discount_percent",
                "specs", "description",
            ):
                if det.get(k) is not None:
                    row[k] = det[k]
            row["details_source"] = src
            bits = [str(x) for x in (row.get("brand"), row.get("warranty")) if x]
            if bits:
                note = (row.get("notes") or "").strip()
                row["notes"] = f"{note}; {' · '.join(bits)}".strip("; ")[:400]
        out.append(row)
    return out


def _gql_post(url: str, payload: dict, *, timeout: float = 20.0) -> Optional[dict]:
    """POST GraphQL JSON; direct (no proxy). Returns parsed dict or None."""
    try:
        r = requests.post(
            url,
            json=payload,
            headers={
                "User-Agent": _HTTP_UA,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://www.technolife.com",
                "Referer": "https://www.technolife.com/",
            },
            timeout=timeout,
            proxies={"http": None, "https": None},
        )
        if r.status_code != 200:
            logger.info("gql %s status=%s", url, r.status_code)
            return None
        data = r.json()
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.info("gql %s failed: %s", url, exc)
        return None


def technolife_product_code(url_or_code: str) -> Optional[str]:
    """Normalize TLP-123 / product-123 / bare digits → TLP-123."""
    if not url_or_code:
        return None
    s = str(url_or_code).strip()
    m = _TECHNOLIFE_CODE_RE.search(s)
    if m:
        return f"TLP-{m.group(1)}"
    if re.fullmatch(r"\d{4,}", s):
        return f"TLP-{s}"
    return None


def technolife_product_url(code: str) -> str:
    """Canonical product URL from TLP code (slug omitted — TL redirects OK)."""
    c = technolife_product_code(code) or code
    num = c.replace("TLP-", "").replace("tlp-", "")
    return f"https://www.technolife.com/product-{num}/"


def _technolife_specs_from_configs(configs: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not isinstance(configs, list):
        return out
    for block in configs:
        if not isinstance(block, dict):
            continue
        for row in block.get("info") or []:
            if not isinstance(row, dict):
                continue
            k = str(row.get("item") or "").strip()
            v = str(row.get("value") or "").strip()
            if k and v:
                out[k[:100]] = v[:240]
            if len(out) >= _DIGIKALA_SPEC_MAX:
                return out
    return out


def search_technolife_api(
    query: str,
    *,
    limit: int = 10,
    timeout: float = 20.0,
) -> List[Dict[str, Any]]:
    """Live Technolife catalog search via GraphQL ``/searchapi``."""
    q = (query or "").strip()
    if not q:
        return []
    payload = {
        "operationName": "search_page_results",
        "variables": {"text": q, "filter": {"limit": int(limit)}},
        "query": (
            "query search_page_results($text: String, $filter: filter_obj) {\n"
            "  search_page_results(text: $text, filter: $filter) {\n"
            "    results {\n"
            "      name code normal_price discounted_price available image\n"
            "      score_avg score_count model\n"
            "      brand_info { name code }\n"
            "      category_info { name code }\n"
            "    }\n"
            "    count\n"
            "  }\n"
            "}"
        ),
    }
    data = _gql_post(_TECHNOLIFE_SEARCH_GQL, payload, timeout=timeout)
    if not data or data.get("errors"):
        logger.info("technolife search errors: %s", (data or {}).get("errors"))
        return []
    results = (
        ((data.get("data") or {}).get("search_page_results") or {}).get("results")
        or []
    )
    if not isinstance(results, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        title = str(row.get("name") or "").strip()
        if not code or not title:
            continue
        # Technolife prices are Toman already (verified vs PDP UI).
        price = row.get("discounted_price")
        if price is None:
            price = row.get("normal_price")
        toman = _as_toman_int(price)
        if toman is None:
            continue
        brand = row.get("brand_info") if isinstance(row.get("brand_info"), dict) else {}
        cat = row.get("category_info") if isinstance(row.get("category_info"), dict) else {}
        avail = row.get("available")
        try:
            in_stock = int(avail or 0) > 0
        except (TypeError, ValueError):
            in_stock = bool(avail)
        out.append({
            "title": title[:300],
            "unit_price_toman": toman,
            "merchant": "technolife",
            "url": technolife_product_url(code),
            "in_stock": in_stock,
            "confidence": "high",
            "notes": f"live search · q={q[:60]}",
            "price_source": "technolife_api",
            "product_id": code,
            "brand": str(brand.get("name") or "").strip() or None,
            "category": str(cat.get("name") or "").strip() or None,
            "rating": row.get("score_avg"),
            "rating_count": row.get("score_count"),
            "relevance": _relevance_score(q, title),
        })
    return out


def search_technolife_multi(queries: List[str]) -> List[Dict[str, Any]]:
    qs = [str(q).strip() for q in (queries or []) if str(q).strip()][:4]
    if not qs:
        return []
    by_id: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(qs))) as pool:
        futs = {pool.submit(search_technolife_api, q, limit=10): q for q in qs}
        for fut in as_completed(futs):
            try:
                rows = fut.result() or []
            except Exception as exc:
                logger.info("technolife multi failed: %s", exc)
                rows = []
            for c in rows:
                pid = str(c.get("product_id") or "")
                if not pid:
                    continue
                prev = by_id.get(pid)
                if prev is None or float(c.get("relevance") or 0) > float(prev.get("relevance") or 0):
                    by_id[pid] = c
    merged = list(by_id.values())
    merged.sort(
        key=lambda c: (
            -float(c.get("relevance") or 0),
            int(c.get("unit_price_toman") or 10**18),
        )
    )
    return merged[:_TECHNOLIFE_SEARCH_MAX]


def fetch_technolife_detail(code: str, *, timeout: float = 20.0) -> Optional[Dict[str, Any]]:
    """Full product via GraphQL ``/shop_product`` get_product_page."""
    code = technolife_product_code(code)
    if not code:
        return None
    payload = {
        "operationName": "get_product_page",
        "variables": {"code": code, "adItemId": None},
        "query": (
            "query get_product_page($code: String, $adItemId: String) {\n"
            "  get_product_page(code: $code, adItemId: $adItemId) {\n"
            "    product_info {\n"
            "      code title is_available model technical_code\n"
            "      score_avg score_count sample_configurations\n"
            "      brand { name enName }\n"
            "      category { name code }\n"
            "    }\n"
            "    seller_items_component {\n"
            "      seller_items {\n"
            "        seller price discounted_price guarantee available\n"
            "        stock_text delivery_text\n"
            "      }\n"
            "    }\n"
            "    configurations_component { title info { item value } }\n"
            "  }\n"
            "}"
        ),
    }
    data = _gql_post(_TECHNOLIFE_PRODUCT_GQL, payload, timeout=timeout)
    if not data or data.get("errors"):
        logger.info("technolife detail errors %s: %s", code, (data or {}).get("errors"))
        return None
    page = (data.get("data") or {}).get("get_product_page") or {}
    if not isinstance(page, dict):
        return None
    info = page.get("product_info") if isinstance(page.get("product_info"), dict) else {}
    title = str(info.get("title") or "").strip()
    if not title:
        return None

    # Best (lowest) seller price — already Toman on Technolife.
    sellers_wrap = page.get("seller_items_component") or []
    prices: List[int] = []
    warranty = None
    seller_name = None
    if isinstance(sellers_wrap, list):
        for wrap in sellers_wrap:
            if not isinstance(wrap, dict):
                continue
            for s in wrap.get("seller_items") or []:
                if not isinstance(s, dict):
                    continue
                pr = s.get("discounted_price")
                if pr is None:
                    pr = s.get("price")
                t = _as_toman_int(pr)
                if t is not None:
                    prices.append(t)
                    if warranty is None and s.get("guarantee"):
                        warranty = str(s.get("guarantee")).strip()
                    if seller_name is None and s.get("seller"):
                        seller_name = str(s.get("seller")).strip()
    if not prices:
        return None
    toman = min(prices)
    brand = info.get("brand") if isinstance(info.get("brand"), dict) else {}
    cat = info.get("category") if isinstance(info.get("category"), dict) else {}
    specs = _technolife_specs_from_configs(page.get("configurations_component"))
    # sample_configurations as extra free-text lines
    samples = info.get("sample_configurations") or []
    if isinstance(samples, list):
        for line in samples:
            s = str(line or "").strip().replace("\n", " ")
            if ":" in s:
                k, _, v = s.partition(":")
                k, v = k.strip(), v.strip()
                if k and v and k not in specs:
                    specs[k[:100]] = v[:240]

    return {
        "product_id": code,
        "unit_price_toman": toman,
        "title": title,
        "in_stock": bool(info.get("is_available")),
        "price_source": "technolife_api",
        "confidence": "high",
        "brand": str(brand.get("name") or brand.get("enName") or "").strip() or None,
        "category": str(cat.get("name") or "").strip() or None,
        "warranty": warranty,
        "seller": seller_name,
        "rating": info.get("score_avg"),
        "rating_count": info.get("score_count"),
        "specs": specs,
        "url": technolife_product_url(code),
        "details_source": "technolife_api",
    }


# ---------------------------------------------------------------------------
# Fafait (fafait.net) — Apollo persisted GraphQL search + SSR PDP enrich
# ---------------------------------------------------------------------------


def _fafait_headers() -> Dict[str, str]:
    return {
        "User-Agent": _HTTP_UA,
        "Accept": "*/*",
        "content-type": "application/json",
        "lang": "fa",
        "device-type": "desktop",
        "site-url": "fafait.net",
        "Origin": "https://fafait.net",
        "Referer": "https://fafait.net/",
    }


def fafait_product_url(
    category_slug: str,
    product_slug: str,
    *,
    sku: Optional[str] = None,
) -> str:
    cat = quote(str(category_slug or "").strip().strip("/"), safe="-_.")
    prod = quote(str(product_slug or "").strip().strip("/"), safe="-_.")
    url = f"https://fafait.net/product/{cat}/{prod}"
    if sku:
        return f"{url}?sku={quote(str(sku))}"
    return url


def _fafait_pick_price_rial(price_obj: Any) -> Optional[int]:
    """Return best selling price in Rial from Fafait Price object."""
    if not isinstance(price_obj, dict):
        return None
    offer = price_obj.get("offer_price")
    has_offer = bool(price_obj.get("has_offer"))
    try:
        offer_n = int(offer) if offer is not None else 0
    except (TypeError, ValueError):
        offer_n = 0
    if has_offer and offer_n > 0:
        return offer_n
    try:
        n = int(price_obj.get("price") or 0)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _fafait_variant_meta(row: dict) -> Dict[str, Any]:
    """Seller / warranty / stock / SKU from first mix_variant."""
    out: Dict[str, Any] = {}
    variants = row.get("mix_variant") if isinstance(row.get("mix_variant"), list) else []
    if not variants:
        return out
    v0 = variants[0] if isinstance(variants[0], dict) else {}
    labels = v0.get("labels") if isinstance(v0.get("labels"), list) else []
    titles = [
        str(x.get("title") or "").strip()
        for x in labels
        if isinstance(x, dict) and str(x.get("title") or "").strip()
    ]
    # Typical order: warranty, color, shop — assign heuristically.
    for t in titles:
        low = t.lower()
        if not out.get("seller") and ("فافا" in t or "fafa" in low or "shop" in low):
            out["seller"] = t
            continue
        if not out.get("color") and any(
            c in t for c in ("مشکی", "سفید", "نقره", "خاکستری", "آبی", "قرمز", "طلایی")
        ):
            out["color"] = t
            continue
        if not out.get("warranty"):
            out["warranty"] = t
    if not out.get("seller") and titles:
        # last label is often shop name
        out.setdefault("seller", titles[-1])
    details = v0.get("details") if isinstance(v0.get("details"), dict) else {}
    code = str(details.get("product_code") or "").strip()
    if code:
        out["sku"] = code
    try:
        count = int(details.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    out["in_stock"] = count > 0
    # Prefer variant price when present
    vprice = _fafait_pick_price_rial(v0.get("price"))
    if vprice is not None:
        out["price_rial"] = vprice
    return out


def _product_from_fafait_row(row: dict, *, query: str = "") -> Optional[Dict[str, Any]]:
    if not isinstance(row, dict):
        return None
    title = str(row.get("title") or "").strip()
    pid = str(row.get("id") or "").strip()
    if not title or not pid:
        return None
    cat = row.get("category") if isinstance(row.get("category"), dict) else {}
    cat_seo = cat.get("seo") if isinstance(cat.get("seo"), dict) else {}
    cat_slug = str(cat_seo.get("url") or "").strip()
    prod_seo = row.get("seo") if isinstance(row.get("seo"), dict) else {}
    prod_slug = str(prod_seo.get("url") or "").strip()
    if not cat_slug or not prod_slug:
        return None
    meta = _fafait_variant_meta(row)
    rial = meta.get("price_rial")
    if rial is None:
        rial = _fafait_pick_price_rial(row.get("price"))
    toman = _rial_to_toman(rial)
    if toman is None:
        return None
    brand = row.get("brand") if isinstance(row.get("brand"), dict) else {}
    url = fafait_product_url(cat_slug, prod_slug, sku=meta.get("sku"))
    return {
        "title": title[:300],
        "unit_price_toman": toman,
        "merchant": "fafait",
        "url": url,
        "in_stock": bool(meta.get("in_stock", True)),
        "confidence": "high",
        "notes": f"live search · q={query[:60]}",
        "price_source": "fafait_api",
        "product_id": pid,
        "brand": str(brand.get("title") or "").strip() or None,
        "category": str(cat.get("title") or "").strip() or None,
        "warranty": meta.get("warranty"),
        "seller": meta.get("seller"),
        "color": meta.get("color"),
        "sku": meta.get("sku"),
        "rating": row.get("average_rate"),
        "relevance": _relevance_score(query, title),
    }


def _fafait_gql_get(
    variables: dict,
    *,
    sha: str = _FAFAIT_SEARCH_SHA,
    timeout: float = 20.0,
) -> Optional[dict]:
    """GET Apollo persisted query. Fail-soft on hash rotation / network."""
    qs = urlencode({
        "variables": json.dumps(variables, ensure_ascii=False, separators=(",", ":")),
        "extensions": json.dumps(
            {"persistedQuery": {"version": 1, "sha256Hash": sha}},
            separators=(",", ":"),
        ),
    })
    url = f"{_FAFAIT_GQL}?{qs}"
    try:
        r = requests.get(
            url,
            headers=_fafait_headers(),
            timeout=timeout,
            proxies={"http": None, "https": None},
        )
        if r.status_code != 200:
            logger.info("fafait gql status=%s body=%s", r.status_code, (r.text or "")[:200])
            return None
        data = r.json()
        if not isinstance(data, dict):
            return None
        if data.get("errors"):
            logger.info("fafait gql errors: %s", data.get("errors"))
        return data
    except Exception as exc:
        logger.info("fafait gql failed: %s", exc)
        return None


def search_fafait_api(
    query: str,
    *,
    limit: int = 12,
    timeout: float = 20.0,
    in_stock: bool = True,
) -> List[Dict[str, Any]]:
    """Live Fafait catalog search via persisted GraphQL ProductFilterWithSort."""
    q = (query or "").strip()
    if not q:
        return []
    qf: Dict[str, Any] = {"q": q}
    if in_stock:
        qf["in-stock"] = "true"
    variables = {
        "model_name": None,
        "model_type": None,
        "target_model_name": "ProductModel",
        "target_model_type": 1,
        "slug": None,
        "limit": int(limit),
        "query_filter": qf,
    }
    data = _fafait_gql_get(variables, timeout=timeout)
    if not data:
        return []
    products = (
        ((data.get("data") or {}).get("result") or {}).get("products") or {}
    )
    rows = products.get("data") if isinstance(products, dict) else None
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        c = _product_from_fafait_row(row, query=q)
        if c:
            out.append(c)
    return out


def search_fafait_multi(queries: List[str]) -> List[Dict[str, Any]]:
    qs = [str(q).strip() for q in (queries or []) if str(q).strip()][:4]
    if not qs:
        return []
    by_id: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(qs))) as pool:
        futs = {pool.submit(search_fafait_api, q, limit=10): q for q in qs}
        for fut in as_completed(futs):
            try:
                rows = fut.result() or []
            except Exception as exc:
                logger.info("fafait multi failed: %s", exc)
                rows = []
            for c in rows:
                pid = str(c.get("product_id") or "")
                if not pid:
                    continue
                prev = by_id.get(pid)
                if prev is None or float(c.get("relevance") or 0) > float(prev.get("relevance") or 0):
                    by_id[pid] = c
    merged = list(by_id.values())
    merged.sort(
        key=lambda c: (
            -float(c.get("relevance") or 0),
            int(c.get("unit_price_toman") or 10**18),
        )
    )
    return merged[:_FAFAIT_SEARCH_MAX]


def _fafait_specs_from_attribute_groups(groups: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not isinstance(groups, list):
        return out
    for g in groups:
        if not isinstance(g, dict):
            continue
        for a in g.get("attributes") or []:
            if not isinstance(a, dict):
                continue
            attr = a.get("attribute") if isinstance(a.get("attribute"), dict) else {}
            aval = a.get("attribute_value") if isinstance(a.get("attribute_value"), dict) else {}
            k = str(attr.get("title") or "").strip()
            v = aval.get("value")
            if isinstance(v, list):
                v = "، ".join(str(x) for x in v if x is not None)
            elif v is True:
                v = "بله"
            elif v is False:
                v = "خیر"
            else:
                v = str(v or "").strip()
            # Skip placeholder dynamic brand key
            if k and v and v.lower() != "brand" and k not in out:
                out[k[:100]] = v[:240]
            if len(out) >= _DIGIKALA_SPEC_MAX:
                return out
    return out


def parse_fafait_next_data(html: str) -> Optional[dict]:
    """Extract product object from Fafait Next.js __NEXT_DATA__ HTML."""
    if not html:
        return None
    m = _FAFAIT_NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        payload = json.loads(m.group(1))
    except Exception:
        return None
    product = (
        ((payload.get("props") or {}).get("pageProps") or {}).get("data") or {}
    ).get("product")
    return product if isinstance(product, dict) else None


def fetch_fafait_detail(url: str, *, timeout: float = 20.0) -> Optional[Dict[str, Any]]:
    """PDP enrich: GET product HTML → __NEXT_DATA__ product (specs + live price)."""
    url = (url or "").strip()
    if not url or not host_allowed(url, "fafait.net"):
        return None
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": _HTTP_UA,
                "Accept": "text/html,application/xhtml+xml",
                "Referer": "https://fafait.net/",
            },
            timeout=timeout,
            proxies={"http": None, "https": None},
        )
        if r.status_code != 200:
            logger.info("fafait pdp status=%s url=%s", r.status_code, url[:80])
            return None
        product = parse_fafait_next_data(r.text)
    except Exception as exc:
        logger.info("fafait pdp failed %s: %s", url[:80], exc)
        return None
    if not product:
        return None
    title = str(product.get("title") or "").strip()
    if not title:
        return None
    meta = _fafait_variant_meta(product)
    rial = meta.get("price_rial")
    if rial is None:
        rial = _fafait_pick_price_rial(product.get("price"))
    toman = _rial_to_toman(rial)
    if toman is None:
        return None
    brand = product.get("brand") if isinstance(product.get("brand"), dict) else {}
    cat = product.get("category") if isinstance(product.get("category"), dict) else {}
    cat_seo = cat.get("seo") if isinstance(cat.get("seo"), dict) else {}
    prod_seo = product.get("seo") if isinstance(product.get("seo"), dict) else {}
    cat_slug = str(cat_seo.get("url") or "").strip()
    prod_slug = str(prod_seo.get("url") or "").strip()
    out_url = (
        fafait_product_url(cat_slug, prod_slug, sku=meta.get("sku"))
        if cat_slug and prod_slug
        else url
    )
    return {
        "product_id": str(product.get("id") or "").strip() or None,
        "unit_price_toman": toman,
        "title": title,
        "in_stock": bool(meta.get("in_stock", True)),
        "price_source": "fafait_api",
        "confidence": "high",
        "brand": str(brand.get("title") or "").strip() or None,
        "category": str(cat.get("title") or "").strip() or None,
        "warranty": meta.get("warranty"),
        "seller": meta.get("seller"),
        "color": meta.get("color"),
        "sku": meta.get("sku"),
        "rating": product.get("average_rate"),
        "specs": _fafait_specs_from_attribute_groups(product.get("attribute_groups")),
        "url": out_url,
        "details_source": "fafait_api",
    }


def refresh_live_prices(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Overwrite Digikala/Technolife/Fafait candidate prices from live product APIs."""
    if not candidates:
        return candidates

    def _one(c: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(c)
        mid = out.get("merchant")
        # API search rows already carry live prices — skip extra PDP fetch.
        if mid in ("digikala", "technolife", "fafait") and out.get("price_source") in _API_PRICE_SOURCES:
            return out
        if mid == "digikala":
            live = fetch_digikala_live(str(out.get("url") or ""))
            src = "digikala_api"
        elif mid == "technolife":
            code = technolife_product_code(
                str(out.get("product_id") or out.get("url") or "")
            )
            live = fetch_technolife_detail(code) if code else None
            src = "technolife_api"
        elif mid == "fafait":
            live = fetch_fafait_detail(str(out.get("url") or ""))
            src = "fafait_api"
        else:
            out.setdefault("price_source", "model")
            return out
        if not live:
            out["price_source"] = "model_unverified"
            if out.get("confidence") == "high":
                out["confidence"] = "medium"
            note = (out.get("notes") or "").strip()
            out["notes"] = f"{note}; price not verified live".strip("; ")[:400]
            return out
        old = out.get("unit_price_toman")
        out["unit_price_toman"] = live["unit_price_toman"]
        out["price_source"] = src
        out["confidence"] = "high"
        out["in_stock"] = bool(live.get("in_stock", True))
        if live.get("title") and (
            not out.get("title") or len(str(out.get("title") or "")) < 8
        ):
            out["title"] = live["title"][:300]
        for k in ("brand", "category", "warranty", "seller", "specs", "product_id"):
            if live.get(k) is not None:
                out[k] = live[k]
        if old and int(old) != int(live["unit_price_toman"]):
            note = (out.get("notes") or "").strip()
            out["notes"] = (
                f"{note}; live price {live['unit_price_toman']} Toman "
                f"(was model {old})"
            ).strip("; ")[:400]
        return out

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(candidates)))) as pool:
        return list(pool.map(_one, candidates))


def _llm_json(
    *,
    system: str,
    user: str,
    web_search: bool = False,
    web_fetch: bool = False,
    web_search_params: Optional[dict] = None,
    user_id: Optional[str],
    workspace_id: Optional[str],
    project_id: Optional[str],
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> dict:
    result = OpenRouterService.chat_completion(
        messages=[{"role": "user", "content": user}],
        model=SHOP_MODEL,
        system_prompt=system,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        user_id=user_id,
        feature=SHOP_FEATURE,
        workspace_id=workspace_id,
        project_id=project_id,
        origin="web",
        web_search=web_search,
        web_fetch=web_fetch,
        web_search_params=web_search_params,
        timeout=SHOP_TIMEOUT_S,
    )
    if not isinstance(result, dict):
        raise RuntimeError("empty shop model response")
    if result.get("error"):
        err = result["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise RuntimeError(msg or "openrouter error")
    raw = _content_text(result)
    if not raw:
        raise RuntimeError("empty model content")
    try:
        return _parse_json(raw)
    except Exception as exc:
        logger.warning("shop JSON parse failed: %s | head=%r", exc, raw[:200])
        raise RuntimeError(f"invalid model JSON: {exc}") from exc


def _family_query_boosts(need: str) -> List[str]:
    """Extra catalog-friendly synonyms when product family is known."""
    family = detect_product_family(need)
    if family == "mini_pc":
        return ["کامپیوتر کوچک", "مینی پی سی", "mini pc"]
    if family == "laptop":
        return ["لپ تاپ", "laptop"]
    if family == "monitor":
        return ["مانیتور", "monitor"]
    return []


def _merge_query_lists(primary: List[str], boosts: List[str], *, limit: int = 3) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for q in list(primary or []) + list(boosts or []):
        s = str(q or "").strip()
        if not s:
            continue
        key = re.sub(r"\s+", " ", s.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(s[:120])
        if len(out) >= limit:
            break
    return out or (primary[:1] if primary else [])


def _default_plan(need: str) -> dict:
    q = need.strip()[:120]
    boosts = _family_query_boosts(need)
    digi = _merge_query_lists([q], boosts, limit=3)
    tech = _merge_query_lists(boosts or [q], [q], limit=3)
    fafa = _merge_query_lists(boosts or [q], [q], limit=3)
    return {
        "queries": {
            "digikala": digi,
            "technolife": tech,
            "fafait": fafa,
        },
        "constraints": [],
        "unit_notes": "",
    }


def _run_digikala_worker(
    *,
    need: str,
    queries: List[str],
) -> List[Dict[str, Any]]:
    """Digikala via live catalog API (not LLM web search) — accurate + current prices."""
    qs = list(queries or [])
    if need and need.strip() not in qs:
        qs = [need.strip(), *qs]
    hits = search_digikala_multi(qs)
    # Boost relevance using full need text
    for h in hits:
        h["relevance"] = max(
            float(h.get("relevance") or 0),
            _relevance_score(need, str(h.get("title") or "")),
        )
    hits.sort(
        key=lambda c: (
            -float(c.get("relevance") or 0),
            int(c.get("unit_price_toman") or 10**18),
        )
    )
    return hits[:_DIGIKALA_SEARCH_MAX_TOTAL]


def _run_technolife_worker(
    *,
    need: str,
    queries: List[str],
) -> List[Dict[str, Any]]:
    """Technolife via GraphQL searchapi — live prices + catalog rows."""
    qs = list(queries or [])
    if need and need.strip() not in qs:
        qs = [need.strip(), *qs]
    hits = search_technolife_multi(qs)
    for h in hits:
        h["relevance"] = max(
            float(h.get("relevance") or 0),
            _relevance_score(need, str(h.get("title") or "")),
        )
    hits.sort(
        key=lambda c: (
            -float(c.get("relevance") or 0),
            int(c.get("unit_price_toman") or 10**18),
        )
    )
    return hits[:_TECHNOLIFE_SEARCH_MAX]


def _run_fafait_worker(
    *,
    need: str,
    queries: List[str],
) -> List[Dict[str, Any]]:
    """Fafait via web-api.fafait.net persisted GraphQL search."""
    qs = list(queries or [])
    if need and need.strip() not in qs:
        qs = [need.strip(), *qs]
    hits = search_fafait_multi(qs)
    for h in hits:
        h["relevance"] = max(
            float(h.get("relevance") or 0),
            _relevance_score(need, str(h.get("title") or "")),
        )
    hits.sort(
        key=lambda c: (
            -float(c.get("relevance") or 0),
            int(c.get("unit_price_toman") or 10**18),
        )
    )
    return hits[:_FAFAIT_SEARCH_MAX]


def _run_worker(
    *,
    merchant_id: str,
    need: str,
    qty: int,
    max_budget_toman: Optional[int],
    notes: str,
    queries: List[str],
    constraints: List[str],
    lang: str,
    user_id: Optional[str],
    workspace_id: Optional[str],
    project_id: Optional[str],
) -> List[Dict[str, Any]]:
    # Digikala + Technolife + Fafait: live catalog APIs. LLM web = last resort.
    if merchant_id == "digikala":
        try:
            return _run_digikala_worker(need=need, queries=queries)
        except Exception as exc:
            logger.warning("digikala API worker failed, falling back to LLM: %s", exc)
    if merchant_id == "technolife":
        try:
            hits = _run_technolife_worker(need=need, queries=queries)
            if hits:
                return hits
            logger.info("technolife API returned empty; falling back to LLM web")
        except Exception as exc:
            logger.warning("technolife API worker failed, falling back to LLM: %s", exc)
    if merchant_id == "fafait":
        try:
            hits = _run_fafait_worker(need=need, queries=queries)
            if hits:
                return hits
            logger.info("fafait API returned empty; falling back to LLM web")
        except Exception as exc:
            logger.warning("fafait API worker failed, falling back to LLM: %s", exc)

    domain = merchant_domain(merchant_id)
    if not domain:
        return []
    params = {
        "engine": "native",
        "max_results": 5,
        "allowed_domains": [domain],
        "user_location": IR_USER_LOCATION,
    }
    try:
        data = _llm_json(
            system=build_worker_system(merchant_id=merchant_id, domain=domain, lang=lang),
            user=build_worker_user(
                need=need,
                qty=qty,
                max_budget_toman=max_budget_toman,
                notes=notes,
                queries=queries,
                constraints=constraints,
            ),
            web_search=True,
            web_fetch=True,
            web_search_params=params,
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            max_tokens=4096,
        )
    except Exception as exc:
        logger.warning("shop worker %s failed: %s", merchant_id, exc)
        return []
    return filter_candidates(
        data.get("candidates"),
        merchant_id=merchant_id,
        domain=domain,
    )


def _sanitize_pick(item: Any, qty: int) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or "").strip()
    mid = str(item.get("merchant") or "").strip() or (merchant_from_url(url) or "")
    if mid not in ALLOWED_MERCHANTS:
        mid = merchant_from_url(url) or ""
    if mid not in ALLOWED_MERCHANTS or not host_allowed(url):
        return None
    unit = normalize_price_toman(item.get("unit_price_toman") or item.get("price"))
    if unit is None:
        return None
    title = str(item.get("title") or "").strip()
    if not title:
        return None
    total = normalize_price_toman(item.get("total_toman"))
    if total is None:
        total = unit * max(1, int(qty))
    pick: Dict[str, Any] = {
        "title": title[:300],
        "unit_price_toman": unit,
        "total_toman": total,
        "merchant": mid,
        "url": url,
        "why": str(item.get("why") or item.get("notes") or "")[:500],
    }
    # Pass through API-backed facts for UI (never invent).
    for k in (
        "brand", "category", "warranty", "seller", "color", "specs",
        "rating", "rating_count", "price_source", "product_id",
        "rrp_toman", "discount_percent", "in_stock",
    ):
        if item.get(k) is not None:
            pick[k] = item[k]
    return pick


def _rank_fallback(candidates: List[Dict[str, Any]], qty: int) -> dict:
    ranked = sorted(
        candidates,
        key=lambda c: (
            -float(c.get("relevance") or 0),
            int(c.get("unit_price_toman") or 10**18),
        ),
    )
    picks = []
    for c in ranked[:12]:
        unit = int(c["unit_price_toman"])
        picks.append({
            "title": c["title"],
            "unit_price_toman": unit,
            "total_toman": unit * max(1, qty),
            "merchant": c["merchant"],
            "url": c["url"],
            "why": c.get("notes") or "",
            "brand": c.get("brand") or "",
            "warranty": c.get("warranty") or "",
            "specs": c.get("specs") or {},
        })
    winner = picks[0] if picks else None
    alts = picks[1:4] if len(picks) > 1 else []
    return {
        "winner": winner,
        "alternatives": alts,
        "all_candidates": picks,
        "summary": "",
        "report_md": "",
    }


def run_pipeline(
    *,
    need: str,
    qty: int = 1,
    max_budget_toman: Optional[int] = None,
    category: str = "auto",
    lang: str = "fa",
    notes: str = "",
    workspace_id: Optional[str] = None,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    on_status: StatusCb = None,
) -> Dict[str, Any]:
    need = (need or "").strip()
    if not need:
        raise ValueError("need is required")
    qty = max(1, min(int(qty or 1), 9999))
    lang = lang if lang in ("fa", "en") else "fa"
    category = category if category in ("office", "it", "auto") else "auto"
    notes = (notes or "").strip()[:2000]
    if max_budget_toman is not None:
        try:
            max_budget_toman = int(max_budget_toman)
            if max_budget_toman <= 0:
                max_budget_toman = None
        except (TypeError, ValueError):
            max_budget_toman = None

    def _status(phase: str, **extra: Any) -> None:
        if on_status:
            on_status(phase, extra)

    # --- 1. Planner (no web) ---
    _status("planning")
    try:
        plan = _llm_json(
            system=build_planner_system(lang),
            user=build_planner_user(
                need=need,
                qty=qty,
                max_budget_toman=max_budget_toman,
                category=category,
                notes=notes,
                lang=lang,
            ),
            web_search=False,
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            temperature=0.1,
            max_tokens=2048,
        )
    except Exception as exc:
        logger.warning("shop planner failed, using default: %s", exc)
        plan = _default_plan(need)

    queries_map = plan.get("queries") if isinstance(plan.get("queries"), dict) else {}
    constraints = plan.get("constraints") if isinstance(plan.get("constraints"), list) else []
    constraints = [str(c) for c in constraints if c][:12]

    boosts = _family_query_boosts(need)
    digi_q = _merge_query_lists(
        [str(q) for q in (queries_map.get("digikala") or []) if q],
        boosts + [need],
        limit=3,
    ) or [need]
    tech_q = _merge_query_lists(
        [str(q) for q in (queries_map.get("technolife") or []) if q],
        boosts + [need],
        limit=3,
    ) or [need]
    fafa_q = _merge_query_lists(
        [str(q) for q in (queries_map.get("fafait") or []) if q],
        boosts + [need],
        limit=3,
    ) or [need]

    plan_out = {
        "queries": {
            "digikala": digi_q,
            "technolife": tech_q,
            "fafait": fafa_q,
        },
        "constraints": constraints,
        "unit_notes": str(plan.get("unit_notes") or ""),
        "merchants": ["digikala", "technolife", "fafait"],
    }
    _status("plan_ready", plan=plan_out)

    # --- 2. Parallel search workers ---
    _status("searching")
    worker_specs = (
        ("digikala", digi_q),
        ("technolife", tech_q),
        ("fafait", fafa_q),
    )
    all_cands: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {
            pool.submit(
                _run_worker,
                merchant_id=mid,
                need=need,
                qty=qty,
                max_budget_toman=max_budget_toman,
                notes=notes,
                queries=qs,
                constraints=constraints,
                lang=lang,
                user_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
            ): mid
            for mid, qs in worker_specs
        }
        for fut in as_completed(futs):
            mid = futs[fut]
            try:
                got = fut.result() or []
            except Exception as exc:
                logger.warning("shop worker future %s: %s", mid, exc)
                got = []
            all_cands.extend(got)
            _status("candidates", merchant=mid, items=got, count=len(got))

    all_cands = dedupe_candidates(all_cands)
    # Live Digikala prices for any leftover LLM digikala URLs (API search already live).
    _status("price_refresh", count=len(all_cands))
    all_cands = refresh_live_prices(all_cands)
    all_cands = [
        c for c in all_cands
        if int(c.get("unit_price_toman") or 0) > 0
    ]
    # Relevance vs original need (helps comparer + ranking).
    for c in all_cands:
        c["relevance"] = max(
            float(c.get("relevance") or 0),
            _relevance_score(need, str(c.get("title") or "")),
        )
    # Hard drop accessories / wrong product type (e.g. GPU riser for mini PC).
    before_fit = len(all_cands)
    all_cands = filter_relevant_candidates(need, all_cands)
    all_cands = apply_soft_budget(
        all_cands, qty=qty, max_budget_toman=max_budget_toman,
    )
    if before_fit and len(all_cands) < before_fit:
        logger.info(
            "shop product-fit filter: %s → %s (family=%s)",
            before_fit, len(all_cands), detect_product_family(need),
        )
    # Prefer: high relevance, live API price, then cheapest.
    all_cands.sort(
        key=lambda c: (
            -float(c.get("relevance") or 0),
            0 if c.get("price_source") in _API_PRICE_SOURCES else 1,
            int(c.get("unit_price_toman") or 10**18),
        )
    )
    # Full product detail (specs/brand/warranty) for top rows → LLM final.
    _status("enrich_details", count=min(_DIGIKALA_DETAIL_MAX, len(all_cands)))
    all_cands = enrich_candidates_with_details(all_cands, max_detail=_DIGIKALA_DETAIL_MAX)
    all_cands = [
        c for c in all_cands
        if int(c.get("unit_price_toman") or 0) > 0
    ]
    # Re-apply fit after detail (category may appear on enrich).
    all_cands = filter_relevant_candidates(need, all_cands)
    _status("search_done", count=len(all_cands))

    # --- 3. Comparer (LLM on real API facts) ---
    _status("comparing")
    disclaimer = DISCLAIMER_FA if lang == "fa" else DISCLAIMER_EN
    if not all_cands:
        return {
            "query": need,
            "qty": qty,
            "max_budget_toman": max_budget_toman,
            "currency": "IRT",
            "category": category,
            "plan": plan_out,
            "winner": None,
            "alternatives": [],
            "all_candidates": [],
            "citations": [],
            "summary": (
                "موردی در دیجی‌کالا، تکنولایف یا فافا پیدا نشد."
                if lang == "fa"
                else "No products found on Digikala, Technolife, or Fafait."
            ),
            "report_md": (
                f"# {(need)[:80]}\n\n{disclaimer}\n\n"
                + ("نتیجه‌ای یافت نشد.\n" if lang == "fa" else "No results.\n")
            ),
            "disclaimer": disclaimer,
            "model_id": SHOP_MODEL,
        }

    try:
        cmp_data = _llm_json(
            system=build_comparer_system(lang),
            user=build_comparer_user(
                need=need,
                qty=qty,
                max_budget_toman=max_budget_toman,
                notes=notes,
                candidates=all_cands,
                lang=lang,
            ),
            web_search=False,
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            temperature=0.1,
            max_tokens=6000,
        )
    except Exception as exc:
        logger.warning("shop comparer failed, ranking locally: %s", exc)
        cmp_data = _rank_fallback(all_cands, qty)

    # Index API-enriched candidates so we can re-attach facts the LLM may drop.
    by_url: Dict[str, Dict[str, Any]] = {}
    for c in all_cands:
        u = str(c.get("url") or "").strip()
        if u:
            by_url[u] = c

    def _merge_api(pick: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not pick:
            return None
        src = by_url.get(str(pick.get("url") or "").strip())
        if not src:
            return pick
        # Trust API price when present (LLM sometimes rewrites numbers).
        if src.get("unit_price_toman"):
            try:
                unit = int(src["unit_price_toman"])
                pick["unit_price_toman"] = unit
                pick["total_toman"] = unit * max(1, int(qty))
            except (TypeError, ValueError):
                pass
        for k in (
            "brand", "category", "warranty", "seller", "color", "specs",
            "rating", "rating_count", "price_source", "product_id",
            "rrp_toman", "discount_percent", "in_stock", "details_source",
        ):
            if src.get(k) is not None and (pick.get(k) is None or pick.get(k) == {} or pick.get(k) == ""):
                pick[k] = src[k]
        if src.get("title") and (
            not pick.get("title") or len(str(pick.get("title") or "")) < 8
        ):
            pick["title"] = src["title"]
        return pick

    winner = _merge_api(_sanitize_pick(cmp_data.get("winner"), qty))
    alternatives = []
    for a in (cmp_data.get("alternatives") or [])[:3]:
        p = _merge_api(_sanitize_pick(a, qty))
        if p and (not winner or p["url"] != winner["url"]):
            alternatives.append(p)
    all_picks = []
    for a in (cmp_data.get("all_candidates") or []):
        p = _merge_api(_sanitize_pick(a, qty))
        if p:
            all_picks.append(p)
    if not all_picks:
        fb = _rank_fallback(all_cands, qty)
        all_picks = [_merge_api(x) or x for x in (fb["all_candidates"] or [])]
        if not winner:
            winner = _merge_api(fb["winner"])
        if not alternatives:
            alternatives = [_merge_api(x) or x for x in (fb["alternatives"] or [])]

    # Ensure winner is cheapest-ish if model omitted it
    if not winner and all_picks:
        winner = all_picks[0]
        alternatives = all_picks[1:4]

    citations = []
    seen_u: set[str] = set()
    for row in ([winner] if winner else []) + alternatives + all_picks:
        if not row:
            continue
        u = row.get("url") or ""
        if u and u not in seen_u:
            seen_u.add(u)
            citations.append({
                "index": len(citations) + 1,
                "url": u,
                "title": row.get("title") or "",
            })

    summary = str(cmp_data.get("summary") or "").strip()
    report_md = str(cmp_data.get("report_md") or "").strip()
    if not report_md:
        lines = [f"# {need[:100]}", "", disclaimer, ""]
        if winner:
            lines.append(f"## Winner\n- {winner['title']}: {winner['total_toman']} Toman ×{qty}\n- {winner['url']}\n")
        for i, a in enumerate(alternatives, 1):
            lines.append(f"## Alt {i}\n- {a['title']}: {a['total_toman']} Toman\n- {a['url']}\n")
        report_md = "\n".join(lines)

    return {
        "query": need,
        "qty": qty,
        "max_budget_toman": max_budget_toman,
        "currency": "IRT",
        "category": category,
        "plan": plan_out,
        "winner": winner,
        "alternatives": alternatives,
        "all_candidates": all_picks[:12],
        "citations": citations,
        "summary": summary,
        "report_md": report_md,
        "disclaimer": disclaimer,
        "model_id": SHOP_MODEL,
    }
