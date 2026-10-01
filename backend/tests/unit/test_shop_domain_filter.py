"""Pure unit tests for shop URL allowlist + price normalizer."""
from app.services.shop_service import (
    _as_toman_int,
    _product_from_digikala_row,
    _product_from_fafait_row,
    _relevance_score,
    _rial_to_toman,
    _technolife_specs_from_configs,
    apply_soft_budget,
    dedupe_candidates,
    detect_product_family,
    digikala_product_id,
    digikala_product_url,
    extract_digikala_specs,
    fafait_product_url,
    filter_candidates,
    filter_relevant_candidates,
    host_allowed,
    is_relevant_product,
    merchant_from_url,
    normalize_price_toman,
    parse_fafait_next_data,
    technolife_product_code,
    technolife_product_url,
)
from app.prompts.shop import ALLOWED_MERCHANTS, SHOP_MODEL


def test_host_allowed_digikala_and_subdomain():
    assert host_allowed("https://www.digikala.com/product/dkp-1")
    assert host_allowed("https://digikala.com/product/dkp-1", "digikala.com")
    assert not host_allowed("https://torob.com/p/1")
    assert not host_allowed("https://amazon.com/x")


def test_host_allowed_technolife():
    assert host_allowed("https://www.technolife.ir/product-1")
    assert host_allowed("https://technolife.ir/x", "technolife.ir")
    assert not host_allowed("https://evil.com/?q=technolife.ir")


def test_host_allowed_fafait():
    assert host_allowed("https://fafait.net/product/monitor/innovers-ps27-")
    assert host_allowed("https://www.fafait.net/x", "fafait.net")
    assert not host_allowed("https://evil.com/?q=fafait.net")


def test_merchant_from_url():
    assert merchant_from_url("https://www.digikala.com/a") == "digikala"
    assert merchant_from_url("https://technolife.ir/b") == "technolife"
    assert merchant_from_url("https://fafait.net/product/laptop/x") == "fafait"
    assert merchant_from_url("https://torob.com/c") is None
    assert "fafait" in ALLOWED_MERCHANTS


def test_normalize_price_toman_rial_label():
    assert normalize_price_toman(120_000_000, label="قیمت به ریال") == 12_000_000
    assert normalize_price_toman("12,000,000 تومان", label="تومان") == 12_000_000


def test_filter_candidates_drops_off_domain_and_no_price():
    raw = [
        {"title": "OK", "unit_price_toman": 1000, "url": "https://www.digikala.com/p/1"},
        {"title": "Bad host", "unit_price_toman": 1000, "url": "https://torob.com/p/1"},
        {"title": "No price", "url": "https://digikala.com/p/2"},
        {"title": "TL", "unit_price_toman": 2000, "url": "https://technolife.ir/p/9"},
    ]
    digi = filter_candidates(raw, merchant_id="digikala", domain="digikala.com")
    assert len(digi) == 1
    assert digi[0]["merchant"] == "digikala"
    assert digi[0]["url"].endswith("/p/1")

    tl = filter_candidates(raw, merchant_id="technolife", domain="technolife.ir")
    assert len(tl) == 1
    assert tl[0]["merchant"] == "technolife"


def test_dedupe_candidates():
    items = [
        {"merchant": "digikala", "title": "Laptop X 16GB", "unit_price_toman": 1, "url": "u1"},
        {"merchant": "digikala", "title": "Laptop X  16GB", "unit_price_toman": 2, "url": "u2"},
        {"merchant": "technolife", "title": "Laptop X 16GB", "unit_price_toman": 3, "url": "u3"},
    ]
    out = dedupe_candidates(items)
    assert len(out) == 2


def test_digikala_product_id():
    assert digikala_product_id(
        "https://www.digikala.com/product/dkp-20666787/"
    ) == "20666787"
    assert digikala_product_id(
        "https://www.digikala.com/product/dkp-20666787/monitor-ps27"
    ) == "20666787"
    assert digikala_product_id("https://technolife.ir/product-1") is None


def test_digikala_product_url():
    assert digikala_product_url(20666787).endswith("/product/dkp-20666787/")


def test_product_from_digikala_row_rial_to_toman():
    row = {
        "id": 20666787,
        "title_fa": "مانیتور 27 اینچ اینوورس مدل PS27",
        "status": "marketable",
        "default_variant": {
            "price": {"selling_price": 160_590_000},
        },
    }
    c = _product_from_digikala_row(row, query="مانیتور PS27")
    assert c is not None
    assert c["unit_price_toman"] == 16_059_000
    assert c["price_source"] == "digikala_api"
    assert "20666787" in c["url"]
    assert c["relevance"] > 0


def test_relevance_score_prefers_model_match():
    need = "مانیتور 27 اینچ PS27"
    a = _relevance_score(need, "مانیتور 27 اینچ اینوورس مدل PS27")
    b = _relevance_score(need, "هدفون بی سیم ارزان")
    assert a > b


def test_extract_digikala_specs():
    product = {
        "specifications": [
            {
                "title": "مشخصات",
                "attributes": [
                    {"title": "اندازه صفحه نمایش", "values": ["27 اینچ"]},
                    {"title": "نوع پنل", "values": ["IPS"]},
                ],
            }
        ]
    }
    specs = extract_digikala_specs(product)
    assert specs["اندازه صفحه نمایش"] == "27 اینچ"
    assert specs["نوع پنل"] == "IPS"


def test_technolife_product_code_and_url():
    assert technolife_product_code(
        "https://www.technolife.com/product-442894/macbook"
    ) == "TLP-442894"
    assert technolife_product_code("TLP-442894") == "TLP-442894"
    assert "product-442894" in technolife_product_url("TLP-442894")


def test_technolife_specs_from_configs():
    configs = [
        {"title": "کلی", "info": [{"item": "سری", "value": "Macbook Air"}]},
        {"title": "فیزیکی", "info": [{"item": "وزن", "value": "۱.۲۴ کیلوگرم"}]},
    ]
    specs = _technolife_specs_from_configs(configs)
    assert specs["سری"] == "Macbook Air"
    assert "وزن" in specs


def test_price_units_digikala_rial_vs_technolife_toman():
    # Digikala API: Rial → Toman /10
    assert _rial_to_toman(217_000_000) == 21_700_000
    # Technolife GraphQL: already Toman (PDP shows ۲۱,۷۰۰,۰۰۰)
    assert _as_toman_int(21_700_000) == 21_700_000
    assert _as_toman_int(21_700_000) != _rial_to_toman(21_700_000)


def test_shop_model_is_gemini_36_flash():
    assert SHOP_MODEL == "google/gemini-3.6-flash"


def test_detect_product_family():
    assert detect_product_family("مینی پی سی اداری") == "mini_pc"
    assert detect_product_family("لپ تاپ گیمینگ RTX") == "laptop"
    assert detect_product_family("مانیتور 27 اینچ") == "monitor"
    assert detect_product_family("چای ساز") is None


def test_reject_gpu_riser_for_mini_pc():
    need = "مینی پی سی اداری"
    assert not is_relevant_product(
        need, "رایزر گرافیک GPU Riser برای کیس",
    )
    assert is_relevant_product(
        need, "مینی پی سی Beelink SER5 Ryzen 5",
    )
    # Digikala catalog wording
    assert is_relevant_product(
        need, "کامپیوتر کوچک چووی Chuwi Mini Pc LarkBox X N100",
    )
    assert is_relevant_product(
        need, "کامپیوتر کوچک اینتل مدل NUC11ATKC2 8-256",
    )


def test_filter_relevant_drops_accessories():
    need = "مینی پی سی"
    cands = [
        {
            "title": "رایزر گرافیک GPU",
            "unit_price_toman": 500_000,
            "relevance": 0.9,
        },
        {
            "title": "مینی پی سی Beelink",
            "unit_price_toman": 25_000_000,
            "relevance": 0.5,
        },
    ]
    out = filter_relevant_candidates(need, cands)
    assert len(out) == 1
    assert "Beelink" in out[0]["title"]


def test_soft_budget_prefers_within():
    cands = [
        {"title": "a", "unit_price_toman": 10_000_000},
        {"title": "b", "unit_price_toman": 50_000_000},
    ]
    out = apply_soft_budget(cands, qty=1, max_budget_toman=12_000_000)
    assert len(out) == 1
    assert out[0]["title"] == "a"


def test_relevance_penalizes_accessory():
    need = "مینی پی سی"
    riser = _relevance_score(need, "رایزر گرافیک GPU Riser")
    mini = _relevance_score(need, "مینی پی سی Beelink SER5")
    assert mini > riser


def test_fafait_product_url():
    url = fafait_product_url("monitor", "innovers-ps27-", sku="15150131464")
    assert url.startswith("https://fafait.net/product/monitor/innovers-ps27-")
    assert "sku=15150131464" in url


def test_product_from_fafait_row_rial_to_toman():
    row = {
        "id": "6a410958fc6de4dc609ce983",
        "title": "مانیتور 27 اینچ Innovers مدل PS27",
        "average_rate": 0,
        "price": {
            "price": 176_000_000,
            "offer_price": 0,
            "has_offer": False,
        },
        "seo": {"url": "innovers-ps27-"},
        "brand": {"title": "اینوورس"},
        "category": {
            "title": "مانیتور",
            "seo": {"url": "monitor"},
        },
        "mix_variant": [
            {
                "labels": [
                    {"title": "مشکی"},
                    {"title": "ونوس سرویس"},
                    {"title": "فافاآی‌تی"},
                ],
                "details": {"product_code": "15150131464", "count": 3},
                "price": {
                    "price": 176_000_000,
                    "offer_price": 0,
                    "has_offer": False,
                },
            }
        ],
    }
    c = _product_from_fafait_row(row, query="مانیتور 27")
    assert c is not None
    assert c["unit_price_toman"] == 17_600_000
    assert c["price_source"] == "fafait_api"
    assert c["merchant"] == "fafait"
    assert "/product/monitor/innovers-ps27-" in c["url"]
    assert c["brand"] == "اینوورس"
    assert c["warranty"] == "ونوس سرویس"
    assert c["seller"] == "فافاآی‌تی"


def test_parse_fafait_next_data():
    html = (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"data":{"product":{'
        '"id":"abc","title":"Test Monitor","attribute_groups":[]'
        "}}}}}</script></html>"
    )
    product = parse_fafait_next_data(html)
    assert product is not None
    assert product["id"] == "abc"
    assert product["title"] == "Test Monitor"
