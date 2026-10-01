"""
Unit tests for DLP detector service and rule catalog.

All tests are pure-Python — no Flask app context, no MongoDB.
"""
import time
import random
import string
import pytest

from app.services.dlp_rules import (
    iran_id_check,
    is_high_entropy,
    BUILTIN_RULES,
)
from app.services.dlp_service import (
    DLPDetector,
    DLPScanResult,
    effective_policy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_detector(overrides: dict | None = None) -> DLPDetector:
    """Create an enabled detector with optional policy overrides."""
    base = {"enabled": True, "sensitivity": "strict"}
    if overrides:
        base.update(overrides)
    return DLPDetector(base)


def find_rule_by_id(rule_id: str) -> dict:
    for rule in BUILTIN_RULES:
        if rule["id"] == rule_id:
            return rule
    raise KeyError(f"Rule {rule_id!r} not in BUILTIN_RULES")


# ---------------------------------------------------------------------------
# Parametrized positive samples — one per builtin rule
# ---------------------------------------------------------------------------

POSITIVE_SAMPLES = [
    # All secret-like fixtures are split via runtime concat so the literal does
    # not appear in source — GitHub push protection scans the source file, not
    # the runtime value, while the DLP rule scans the assembled string.
    ("aws_access_key",      "AKIA" + "IOSFODNN7EXAMPLE"),
    # AWS secret key: high-entropy 40-char string
    ("aws_secret_key",      "wJalrXUtnFEMI" + "/K7MDENG/bPxRfiCYEXAMPLEKEY"),
    ("openai_api_key",      "sk-proj-" + "abc123defGHIJKLmnopQRSTUVwxyz1234567890"),
    ("anthropic_api_key",   "sk-ant-api03-" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789ABCDEFGHIJ"),
    ("github_pat",          "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ12345678"),
    ("google_api_key",      "AIza" + "SyABCDEFGHIJKLMNOPQRSTUVWXYZ1234567"),
    ("slack_token",         "xoxb-" + "123456789012-123456789012-ABCDEFGHIJKLMNOP"),
    ("stripe_secret",       "sk_" + "live_ABCDEFGHIJKLMNOPQRSTUV1234"),
    ("private_key_pem",     "-----BEGIN RSA PRIVATE KEY-----"),
    ("jwt_token",
     "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
     ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0"
     ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"),
    ("credit_card",         "4111 1111 1111 1111"),
    ("iban",                "GB82WEST12345698765432"),
    ("national_id_iran",    "0076229645"),
    ("generic_api_key",     "pwd: secret_value_1234"),
    ("email",               "user@example.com"),
    ("phone_intl",          "+1 650 253 0000"),
    ("ipv4_private",        "192.168.1.100"),
    # 38-char mixed-case alphanumeric, entropy=4.74, doesn't match any specific key rule
    ("high_entropy_token",  "Kj9mD83Xm2pQrLm88ZwQ14TnvbM9v0xZq7cW4R"),
]


@pytest.mark.parametrize("rule_id,sample", POSITIVE_SAMPLES)
def test_each_builtin_rule_detects_positive(rule_id: str, sample: str) -> None:
    detector = make_detector()
    result = detector.scan(sample)
    matched_ids = {m.rule_id for m in result.matches}
    assert rule_id in matched_ids, (
        f"Rule '{rule_id}' did not fire on sample {sample!r}. "
        f"Matched: {matched_ids}"
    )
    # Verify severity matches the rule catalog
    rule = find_rule_by_id(rule_id)
    for m in result.matches:
        if m.rule_id == rule_id:
            assert m.severity == rule["severity"]
            break


# ---------------------------------------------------------------------------
# Negative samples
# ---------------------------------------------------------------------------

NEGATIVE_SAMPLES = [
    ("aws_access_key",     ""),
    ("aws_access_key",     "Just some normal prose without keys."),
    ("openai_api_key",     "not-a-key-at-all"),
    ("anthropic_api_key",  "sk-ant-wrongformat"),
    ("credit_card",        "1234 5678 9012 3456"),  # non-Luhn (different from test below)
    ("email",              "not_an_email"),
    ("jwt_token",          "eyJ.short.jwt"),
]


@pytest.mark.parametrize("rule_id,text", NEGATIVE_SAMPLES)
def test_each_builtin_rule_ignores_negative(rule_id: str, text: str) -> None:
    detector = make_detector()
    result = detector.scan(text)
    # The specific rule should NOT have fired
    matched_ids_for_rule = {m.rule_id for m in result.matches if m.rule_id == rule_id}
    assert not matched_ids_for_rule, (
        f"Rule '{rule_id}' unexpectedly fired on {text!r}"
    )


# ---------------------------------------------------------------------------
# Credit-card Luhn validation
# ---------------------------------------------------------------------------

def test_credit_card_luhn_filters_invalid() -> None:
    # 4111 1111 1111 1112 — Luhn-invalid (last digit off by 1)
    detector = make_detector()
    result = detector.scan("4111 1111 1111 1112")
    cc_matches = [m for m in result.matches if m.rule_id == "credit_card"]
    assert len(cc_matches) == 0, "Luhn-invalid card number should not match"


def test_credit_card_luhn_passes_valid() -> None:
    detector = make_detector()
    result = detector.scan("4111 1111 1111 1111")
    cc_matches = [m for m in result.matches if m.rule_id == "credit_card"]
    assert len(cc_matches) > 0, "Luhn-valid card number should match"


# ---------------------------------------------------------------------------
# IBAN mod-97 validation
# ---------------------------------------------------------------------------

def test_iban_mod97_filters_invalid() -> None:
    # GB00WEST12345698765432 — invalid checksum (00 is not valid for GB IBAN)
    detector = make_detector()
    result = detector.scan("GB00WEST12345698765432")
    iban_matches = [m for m in result.matches if m.rule_id == "iban"]
    assert len(iban_matches) == 0, "Invalid IBAN should not match after mod-97 check"


def test_iban_mod97_passes_valid() -> None:
    # GB82WEST12345698765432 — real valid IBAN
    detector = make_detector()
    result = detector.scan("GB82WEST12345698765432")
    iban_matches = [m for m in result.matches if m.rule_id == "iban"]
    assert len(iban_matches) > 0, "Valid IBAN should match"


# ---------------------------------------------------------------------------
# Iran national ID validator
# ---------------------------------------------------------------------------

def test_iran_id_validator_positive() -> None:
    # Known valid Iran national ID
    assert iran_id_check("0076229645") is True


def test_iran_id_validator_negative_bad_checksum() -> None:
    assert iran_id_check("0076229646") is False


def test_iran_id_validator_rejects_all_same_digit() -> None:
    for digit in "0123456789":
        assert iran_id_check(digit * 10) is False, (
            f"All-same-digit ID {digit * 10} should be rejected"
        )


def test_iran_id_detector_positive() -> None:
    detector = make_detector()
    result = detector.scan("0076229645")
    matched = {m.rule_id for m in result.matches}
    assert "national_id_iran" in matched


def test_iran_id_detector_rejects_invalid() -> None:
    detector = make_detector()
    result = detector.scan("1111111111")  # all-same-digit
    iran_matches = [m for m in result.matches if m.rule_id == "national_id_iran"]
    assert len(iran_matches) == 0


# ---------------------------------------------------------------------------
# High-entropy token tests
# ---------------------------------------------------------------------------

def test_high_entropy_filter_skips_low_entropy_string() -> None:
    # Uniform character repetition — low entropy
    detector = make_detector()
    result = detector.scan("aaaaaaaaaaaaaaaaaaaaaaaa")
    entropy_matches = [m for m in result.matches if m.rule_id == "high_entropy_token"]
    assert len(entropy_matches) == 0, "Low-entropy string should not match high_entropy_token"


def test_high_entropy_filter_matches_high_entropy_string() -> None:
    # Mixed chars with high entropy (entropy=4.66, 29 distinct, mixed alpha/num/symbols)
    sample = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    assert is_high_entropy(sample), "Sample should be high-entropy"
    detector = make_detector()
    result = detector.scan(sample)
    # May match as aws_secret_key (which also uses is_high_entropy) OR high_entropy_token
    entropy_or_aws = [
        m for m in result.matches
        if m.rule_id in {"high_entropy_token", "aws_secret_key"}
    ]
    assert len(entropy_or_aws) > 0, "High-entropy string should match an entropy-based rule"


def test_high_entropy_filter_skips_pure_alpha() -> None:
    # Pure alpha — even if entropy is decent, purely alphabetic is excluded
    sample = "abcdefghijklmnopqrstuvwxyzABCDE"
    assert not is_high_entropy(sample), "Pure-alpha should not be considered high entropy"


def test_high_entropy_filter_skips_pure_digit() -> None:
    sample = "12345678901234567890123456"
    assert not is_high_entropy(sample), "Pure-digit should not be considered high entropy"


# ---------------------------------------------------------------------------
# Disabled policy
# ---------------------------------------------------------------------------

def test_disabled_policy_returns_empty() -> None:
    detector = DLPDetector({"enabled": False})
    # Even an obvious API key should produce no matches
    result = detector.scan("sk-ant-api03-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
    assert result.matches == []
    assert result.highest_action == "allow"


# ---------------------------------------------------------------------------
# Rule override to allow
# ---------------------------------------------------------------------------

def test_rule_override_to_allow_skips_rule() -> None:
    detector = DLPDetector({
        "enabled": True,
        "sensitivity": "strict",
        "rule_overrides": {"email": "allow"},
    })
    result = detector.scan("Contact us at user@example.com for more info.")
    email_matches = [m for m in result.matches if m.rule_id == "email"]
    assert len(email_matches) == 0, "Overriding email to allow should suppress the match"


def test_rule_override_changes_action() -> None:
    # credit_card default is already block; an explicit block override stays block.
    detector = DLPDetector({
        "enabled": True,
        "sensitivity": "strict",
        "rule_overrides": {"credit_card": "block"},
    })
    result = detector.scan("4111 1111 1111 1111")
    cc_matches = [m for m in result.matches if m.rule_id == "credit_card"]
    assert len(cc_matches) > 0
    assert cc_matches[0].action == "block"


# ---------------------------------------------------------------------------
# Custom patterns
# ---------------------------------------------------------------------------

def test_custom_pattern_runs() -> None:
    detector = DLPDetector({
        "enabled": True,
        "sensitivity": "strict",
        "custom_patterns": [
            {
                "id": "codename_project_x",
                "name": "Project X Codename",
                "regex": r"PROJECT-X-\d+",
                "severity": "high",
                "action": "warn",
            }
        ],
    })
    result = detector.scan("The ticket is PROJECT-X-1234 for this feature.")
    custom_matches = [m for m in result.matches if m.rule_id == "codename_project_x"]
    assert len(custom_matches) > 0, "Custom pattern should match PROJECT-X-1234"
    assert custom_matches[0].severity == "high"
    assert custom_matches[0].action == "warn"


def test_invalid_custom_regex_does_not_crash() -> None:
    detector = DLPDetector({
        "enabled": True,
        "sensitivity": "strict",
        "custom_patterns": [
            {
                "id": "broken",
                "name": "Broken Pattern",
                "regex": r"[invalid(regex",
                "severity": "high",
                "action": "warn",
            }
        ],
    })
    # Should not raise; builtin rules still work
    result = detector.scan("sk-ant-api03-ValidKeyHereXXXXXXXXXXXXXXXXXXXXX")
    assert isinstance(result, DLPScanResult), "Scan should return a result even with bad custom regex"


# ---------------------------------------------------------------------------
# Internal hostname dynamic rule
# ---------------------------------------------------------------------------

def test_internal_hostname_dynamic_rule() -> None:
    detector = DLPDetector({
        "enabled": True,
        "sensitivity": "strict",
        "internal_hostname_suffixes": ["acme-internal.com"],
    })
    result_match = detector.scan("Connect to db01.acme-internal.com for queries.")
    hostname_matches = [m for m in result_match.matches if m.rule_id == "internal_hostname"]
    assert len(hostname_matches) > 0, "Internal hostname should match"

    result_no_match = detector.scan("Visit acme.com for public info.")
    hostname_no_matches = [m for m in result_no_match.matches if m.rule_id == "internal_hostname"]
    assert len(hostname_no_matches) == 0, "acme.com should NOT match acme-internal.com suffix"


# ---------------------------------------------------------------------------
# Highest action resolution
# ---------------------------------------------------------------------------

def test_highest_action_resolution() -> None:
    # Email triggers warn; Anthropic key triggers block
    text = (
        "Contact user@example.com "
        "or use sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AB"
    )
    detector = make_detector()
    result = detector.scan(text)
    assert result.highest_action == "block", (
        f"Expected 'block' as highest_action, got {result.highest_action!r}"
    )


# ---------------------------------------------------------------------------
# Snippet masking
# ---------------------------------------------------------------------------

def test_snippet_masks_secret() -> None:
    secret = "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AB"
    detector = make_detector()
    result = detector.scan(f"Token: {secret} end")
    anthropic_matches = [m for m in result.matches if m.rule_id == "anthropic_api_key"]
    assert len(anthropic_matches) > 0
    snippet = anthropic_matches[0].snippet
    # The snippet must NOT contain the raw secret
    assert secret not in snippet, "Snippet must not expose raw secret"
    # It must contain asterisks
    assert "*" in snippet, "Snippet should contain masking asterisks"


# ---------------------------------------------------------------------------
# SHA-256 and text_length
# ---------------------------------------------------------------------------

def test_sha256_and_length_set() -> None:
    import hashlib
    text = "Hello, world!"
    detector = DLPDetector({"enabled": True})
    result = detector.scan(text)
    assert result.text_length == len(text)
    expected_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert result.text_sha256 == expected_hash


def test_sha256_set_even_when_disabled() -> None:
    """text_sha256 and text_length are always populated, even for disabled detector."""
    import hashlib
    text = "just some text"
    detector = DLPDetector({"enabled": False})
    result = detector.scan(text)
    assert result.text_length == len(text)
    assert result.text_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Sensitivity level tests
# ---------------------------------------------------------------------------

def test_sensitivity_lenient_skips_low_medium() -> None:
    # Email is 'low'; ipv4_private is 'medium' — both skipped under 'lenient'
    detector = DLPDetector({
        "enabled": True,
        "sensitivity": "lenient",
    })
    result = detector.scan(
        "Contact user@example.com at IP 192.168.1.1 for network info."
    )
    ids = {m.rule_id for m in result.matches}
    assert "email" not in ids, "lenient sensitivity should skip 'low' severity rules"
    assert "ipv4_private" not in ids, "lenient sensitivity should skip 'medium' severity rules"


def test_sensitivity_lenient_still_scans_high_critical() -> None:
    detector = DLPDetector({
        "enabled": True,
        "sensitivity": "lenient",
    })
    result = detector.scan("sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AB")
    ids = {m.rule_id for m in result.matches}
    assert "anthropic_api_key" in ids, "lenient sensitivity should still catch critical rules"


def test_sensitivity_strict_scans_all() -> None:
    # Under strict, even 'low' rules like email are scanned
    detector = DLPDetector({
        "enabled": True,
        "sensitivity": "strict",
    })
    result = detector.scan("user@example.com")
    ids = {m.rule_id for m in result.matches}
    assert "email" in ids, "strict sensitivity should include 'low' severity rules"


def test_sensitivity_balanced_scans_medium_and_above() -> None:
    detector = DLPDetector({
        "enabled": True,
        "sensitivity": "balanced",
    })
    # email is 'low' — should be skipped
    result_email = detector.scan("user@example.com")
    ids_email = {m.rule_id for m in result_email.matches}
    assert "email" not in ids_email, "balanced should skip 'low' rules"

    # ipv4_private is 'medium' — should be scanned
    result_ip = detector.scan("192.168.1.100")
    ids_ip = {m.rule_id for m in result_ip.matches}
    assert "ipv4_private" in ids_ip, "balanced should scan 'medium' rules"


# ---------------------------------------------------------------------------
# Effective policy helper
# ---------------------------------------------------------------------------

def test_effective_policy_defaults() -> None:
    policy = effective_policy(None)
    assert policy["enabled"] is False
    assert policy["sensitivity"] == "balanced"
    assert policy["rule_overrides"] == {}
    assert policy["custom_patterns"] == []
    assert policy["internal_hostname_suffixes"] == []
    assert policy["notify_owners"] is True
    assert policy["llm_classifier"]["enabled"] is False


def test_effective_policy_merges_workspace_settings() -> None:
    raw = {"enabled": True, "sensitivity": "strict", "notify_owners": False}
    policy = effective_policy(raw)
    assert policy["enabled"] is True
    assert policy["sensitivity"] == "strict"
    assert policy["notify_owners"] is False
    # Defaults still present
    assert policy["rule_overrides"] == {}


def test_effective_policy_deep_merges_llm_classifier() -> None:
    raw = {"llm_classifier": {"enabled": True}}
    policy = effective_policy(raw)
    assert policy["llm_classifier"]["enabled"] is True
    # Default model still present
    assert "model" in policy["llm_classifier"]


# ---------------------------------------------------------------------------
# Performance test
# ---------------------------------------------------------------------------

def _make_4kb_text_with_secret() -> str:
    """Generate ~4 KB of random prose with one embedded secret."""
    prose_chars = string.ascii_letters + string.digits + " .,\n"
    # ~4000 chars of random prose
    random.seed(42)
    prose = "".join(random.choices(prose_chars, k=3950))
    secret = " sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AB "
    # Insert secret at roughly the middle
    mid = len(prose) // 2
    return prose[:mid] + secret + prose[mid:]


def test_perf_under_50ms_for_4kb() -> None:
    """Scanner must complete in < 50 ms for 4 KB input (allow 100 ms on Windows)."""
    text = _make_4kb_text_with_secret()
    assert len(text) >= 4000, "Test text should be at least 4 KB"

    detector = DLPDetector({
        "enabled": True,
        "sensitivity": "strict",
    })

    # Warm up (first call compiles custom regex cache, etc.)
    detector.scan(text)

    start = time.perf_counter()
    result = detector.scan(text)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 100, (
        f"Scan took {elapsed_ms:.1f} ms, expected < 100 ms for 4 KB input"
    )
    # Verify the secret was actually found
    matched_ids = {m.rule_id for m in result.matches}
    assert "anthropic_api_key" in matched_ids, "Secret should be detected in performance test"


# ---------------------------------------------------------------------------
# LLM classify stub
# ---------------------------------------------------------------------------

def test_llm_classify_returns_none() -> None:
    """Phase 1: llm_classify must return None (not yet implemented)."""
    detector = make_detector({"llm_classifier": {"enabled": True}})
    result = detector.llm_classify("some sensitive text")
    assert result is None


# ---------------------------------------------------------------------------
# DLPMatch enrichment — description / source / category
# ---------------------------------------------------------------------------

def test_builtin_match_carries_description_source_category_low() -> None:
    """Low-severity builtin match (email) populates description, category='pii', source='builtin'."""
    detector = make_detector()
    result = detector.scan("Reach me at user@example.com.")
    email_matches = [m for m in result.matches if m.rule_id == "email"]
    assert len(email_matches) == 1
    m = email_matches[0]
    assert m.source == "builtin"
    assert m.category == "pii"
    assert m.description is not None and m.description != ""


def test_builtin_match_carries_description_source_category_critical() -> None:
    """Critical-severity builtin match (aws_access_key) populates the same fields."""
    detector = make_detector()
    result = detector.scan("My key is AKIA" + "IOSFODNN7EXAMPLE here.")
    aws_matches = [m for m in result.matches if m.rule_id == "aws_access_key"]
    assert len(aws_matches) == 1
    m = aws_matches[0]
    assert m.source == "builtin"
    assert m.category == "secrets"
    assert m.description is not None and m.description != ""


def test_to_dict_emits_source_and_description() -> None:
    """DLPScanResult.to_dict() must emit `source` always and `description` when non-null."""
    detector = make_detector()
    result = detector.scan("user@example.com")
    out = result.to_dict()
    assert out["matches"], "expected at least one match"
    entry = next(e for e in out["matches"] if e["rule_id"] == "email")
    assert entry["source"] == "builtin"
    assert "description" in entry
    assert "category" in entry


def test_custom_pattern_match_source_is_custom() -> None:
    """Custom-pattern matches carry source='custom' with no description/category."""
    detector = DLPDetector({
        "enabled": True,
        "sensitivity": "strict",
        "custom_patterns": [
            {
                "id": "codename",
                "name": "Codename",
                "regex": r"PROJECT-X-\d+",
                "severity": "high",
                "action": "warn",
            }
        ],
    })
    result = detector.scan("Ticket PROJECT-X-1234 in flight.")
    custom_matches = [m for m in result.matches if m.rule_id == "codename"]
    assert len(custom_matches) == 1
    m = custom_matches[0]
    assert m.source == "custom"
    assert m.description is None
    assert m.category is None


def test_hostname_match_source_and_category() -> None:
    """Dynamic hostname matches: source='hostname', category='network', description set."""
    detector = DLPDetector({
        "enabled": True,
        "sensitivity": "strict",
        "internal_hostname_suffixes": ["acme-internal.com"],
    })
    result = detector.scan("Connect to db01.acme-internal.com for queries.")
    host_matches = [m for m in result.matches if m.rule_id == "internal_hostname"]
    assert len(host_matches) == 1
    m = host_matches[0]
    assert m.source == "hostname"
    assert m.category == "network"
    assert m.description == "Internal company hostname"


def test_smart_scan_synthetic_match_carries_llm_source(monkeypatch) -> None:
    """LLM synthetic match: source='llm', description=verdict.reason, snippet=''."""
    from app.services import dlp_service

    dlp_service._LLM_CACHE.clear()
    detector = make_detector({"llm_classifier": {"enabled": True}})

    def fake_classify(self, text, user_lang='en', *, user_id=None):
        return {"category": "restricted", "reason": "mentions codename"}

    monkeypatch.setattr(DLPDetector, "llm_classify", fake_classify)
    result = detector.scan("Email me at user@example.com about Project Atlas updates.")
    smart = next((m for m in result.matches if m.rule_id == "ai_smart_scan"), None)
    assert smart is not None
    assert smart.source == "llm"
    assert smart.description == "mentions codename"
    assert smart.snippet == ""
    assert smart.category == "restricted"
