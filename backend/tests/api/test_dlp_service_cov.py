"""Direct unit coverage for the DLP service layer (no HTTP for most tests).

Targets uncovered ranges in:
  - app/services/dlp_rules.py    (luhn / iban / iran-id / entropy validators)
  - app/services/dlp_service.py  (effective_policy, lang resolve, llm cache,
                                  DLPDetector.from_workspace/scan/redact/llm_classify,
                                  snippet + occurrence + dedup helpers)
  - app/services/dlp_gate.py     (gate / gate_redactable decision branches)

Mirrors tests/api/test_dlp.py + tests/api/test_models_meetings_cov.py:
  - DB-touching calls run inside ``flask_core.app_context()`` against the
    isolated ``unichat_*_test`` DB (per-test TRUNCATE via the autouse fixture).
  - The smart-scan LLM boundary is monkeypatched at
    ``OpenRouterService._sync_completion`` so the network is never hit.
  - Most of DLPDetector is exercised by constructing it directly with a policy
    dict (no DB needed) — the same effective_policy() the request path uses.
"""
import time

import pytest

import app.services.dlp_rules as rules
import app.services.dlp_service as svc
from app.services.dlp_service import (
    DLPDetector,
    DLPMatch,
    effective_policy,
    _resolve_lang_name,
    _redact_label,
    _llm_cache_get,
    _llm_cache_set,
    _POLICY_DEFAULTS,
)
import app.services.dlp_gate as gate_mod
from app.services.dlp_gate import (
    gate,
    gate_redactable,
    DLPBlockedError,
    format_blocked_response,
    _highest_severity,
)


# Deterministic text fixtures that trip builtin rules.
_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"            # aws_access_key -> critical/block
_NID = "0076229645"                           # national_id_iran -> high/block
_CARD = "4111 1111 1111 1111"                 # credit_card (Luhn ok) -> high/block
_EMAIL = "alice@example.com"                   # email -> low/warn
_PRIV_IP = "10.1.2.3"                          # ipv4_private -> medium/warn


def _policy(**over):
    p = {"enabled": True, "sensitivity": "balanced"}
    p.update(over)
    return effective_policy(p)


def _detector(**over):
    return DLPDetector(_policy(**over))


# ===========================================================================
# dlp_rules.py — validators (luhn / iban / iran-id / entropy)
# ===========================================================================
def test_luhn_valid_true_and_false():
    assert rules.luhn_valid("4111 1111 1111 1111") is True   # canonical Visa test
    assert rules.luhn_valid("4111-1111-1111-1112") is False  # bad checksum


def test_luhn_rejects_out_of_range_lengths():
    assert rules.luhn_valid("123456789012") is False   # 12 digits < 13
    assert rules.luhn_valid("1" * 20) is False          # 20 digits > 19


def test_luhn_doubling_carry_branch():
    # Forces the n>9 -> n-=9 branch; '0000000000000000' (16 zeros) sums to 0.
    assert rules.luhn_valid("0000000000000000") is True
    # A real Visa test number has odd-index digits that double past 9 (n-=9).
    assert rules.luhn_valid("4242424242424242") is True


def test_iban_mod97_valid_and_invalid():
    assert rules.iban_mod97("DE89 3704 0044 0532 0130 00") is True
    assert rules.iban_mod97("DE89 3704 0044 0532 0130 01") is False


def test_iban_mod97_too_short():
    assert rules.iban_mod97("DE1") is False


def test_iban_mod97_invalid_char_returns_false():
    # '@' is neither digit nor alpha -> the else branch returns False.
    assert rules.iban_mod97("DE89@7040044053201300") is False


def test_iran_id_check_valid():
    # 0084575948 is a well-known valid Iranian national ID.
    assert rules.iran_id_check("0084575948") is True


def test_iran_id_check_wrong_length():
    assert rules.iran_id_check("12345") is False


def test_iran_id_check_all_same_digit_rejected():
    assert rules.iran_id_check("1111111111") is False


def test_iran_id_check_remainder_ge_2_branch():
    # 0013542419 exercises the (remainder >= 2 -> 11-remainder) branch.
    assert rules.iran_id_check("0013542419") is True


def test_iran_id_check_remainder_lt_2_branch():
    # 5675164881 has checksum remainder == 1 -> the (last == remainder) branch.
    assert rules.iran_id_check("5675164881") is True


def test_iran_id_check_bad_checksum():
    assert rules.iran_id_check("0084575940") is False


def test_shannon_entropy_empty_and_uniform():
    assert rules.shannon_entropy("") == 0.0
    # 'ab' -> two equally-likely symbols -> 1 bit.
    assert rules.shannon_entropy("ab") == pytest.approx(1.0)


def test_is_high_entropy_rejects_short():
    assert rules.is_high_entropy("short") is False


def test_is_high_entropy_rejects_all_digits():
    assert rules.is_high_entropy("1234567890123456789012345") is False


def test_is_high_entropy_rejects_all_alpha():
    assert rules.is_high_entropy("abcdefghijklmnopqrstuvwxyz") is False


def test_is_high_entropy_rejects_low_distinct():
    # 24+ chars, mixed alnum but only a few distinct chars -> distinct < 12.
    assert rules.is_high_entropy("a1a1a1a1a1a1a1a1a1a1a1a1a1") is False


def test_is_high_entropy_true_for_secret_like():
    secret = "aZ9k_Q3pX7mB2vL8rT4wYc1dN6sH0"  # 29 chars, mixed, high entropy
    assert rules.is_high_entropy(secret) is True


def test_is_high_entropy_empty():
    assert rules.is_high_entropy("") is False


# ===========================================================================
# dlp_service.py — effective_policy
# ===========================================================================
def test_effective_policy_none_returns_defaults():
    p = effective_policy(None)
    assert p["enabled"] is False
    assert p["sensitivity"] == "balanced"
    # Smart-scan model is force-locked.
    assert p["llm_classifier"]["model"] == svc._LOCKED_LLM_MODEL


def test_effective_policy_deep_merges_llm_classifier():
    # Partial llm_classifier should merge with defaults (line 170).
    p = effective_policy({
        "enabled": True,
        "llm_classifier": {"enabled": True, "guidance_prompt": "be careful"},
    })
    lc = p["llm_classifier"]
    assert lc["enabled"] is True
    assert lc["guidance_prompt"] == "be careful"
    # Defaulted sub-keys survive the merge.
    assert "action_thresholds" in lc
    # Model is still force-overwritten to the locked value even if stale.
    assert lc["model"] == svc._LOCKED_LLM_MODEL


def test_effective_policy_force_locks_stale_model():
    p = effective_policy({"llm_classifier": {"model": "evil/model"}})
    assert p["llm_classifier"]["model"] == svc._LOCKED_LLM_MODEL


def test_effective_policy_non_dict_llm_classifier_passthrough():
    # A non-dict llm_classifier is taken verbatim (not deep-merged); the
    # force-lock block then skips because it's not a dict.
    p = effective_policy({"llm_classifier": "nope"})
    assert p["llm_classifier"] == "nope"


# ===========================================================================
# dlp_service.py — _resolve_lang_name
# ===========================================================================
def test_resolve_lang_name_known_and_unknown():
    assert _resolve_lang_name("fa") == "Persian"
    assert _resolve_lang_name("PE") == "Persian"      # 2-char prefix + lower
    assert _resolve_lang_name("german-ish") == "German"  # 'ge' prefix
    assert _resolve_lang_name("zz") == "English"      # unknown -> English
    assert _resolve_lang_name("") == "English"
    assert _resolve_lang_name(None) == "English"


# ===========================================================================
# dlp_service.py — _redact_label
# ===========================================================================
def test_redact_label_explicit_category_and_fallback():
    m_email = DLPMatch("email", "Email", "low", "warn", "*", 0, 1, category="pii")
    assert _redact_label(m_email) == "EMAIL"
    # Unknown rule_id -> uppercased category.
    m_custom = DLPMatch("custom:x", "X", "medium", "warn", "*", 0, 1, category="finance")
    assert _redact_label(m_custom) == "FINANCE"
    # Unknown rule_id, no category -> generic SENSITIVE.
    m_bare = DLPMatch("custom:y", "Y", "medium", "warn", "*", 0, 1, category=None)
    assert _redact_label(m_bare) == "SENSITIVE"


# ===========================================================================
# dlp_service.py — module-level LLM verdict cache
# ===========================================================================
def test_llm_cache_set_get_roundtrip():
    svc._LLM_CACHE.clear()
    verdict = {"category": "confidential", "reason": "x", "spans": []}
    _llm_cache_set("k1", verdict)
    assert _llm_cache_get("k1") == verdict
    svc._LLM_CACHE.clear()


def test_llm_cache_get_missing_returns_none():
    svc._LLM_CACHE.clear()
    assert _llm_cache_get("absent") is None


def test_llm_cache_get_expired_evicts(monkeypatch):
    svc._LLM_CACHE.clear()
    # Insert an already-expired entry by stubbing time during set.
    monkeypatch.setattr(svc.time, "time", lambda: 1000.0)
    _llm_cache_set("k", {"category": "public"})
    # Advance the clock past the TTL.
    monkeypatch.setattr(svc.time, "time", lambda: 1000.0 + svc._LLM_CACHE_TTL + 1)
    assert _llm_cache_get("k") is None
    # Expired entry was popped.
    assert "k" not in svc._LLM_CACHE
    svc._LLM_CACHE.clear()


def test_llm_cache_set_reinsert_moves_to_tail():
    svc._LLM_CACHE.clear()
    _llm_cache_set("dup", {"category": "public", "v": 1})
    _llm_cache_set("dup", {"category": "public", "v": 2})  # re-insert -> pop+append
    assert _llm_cache_get("dup")["v"] == 2
    assert len(svc._LLM_CACHE) == 1
    svc._LLM_CACHE.clear()


def test_llm_cache_evicts_oldest_when_full(monkeypatch):
    svc._LLM_CACHE.clear()
    monkeypatch.setattr(svc, "_LLM_CACHE_MAX", 3)
    for i in range(3):
        _llm_cache_set(f"k{i}", {"category": "public", "i": i})
    _llm_cache_set("k3", {"category": "public", "i": 3})  # evicts k0 (FIFO)
    assert "k0" not in svc._LLM_CACHE
    assert "k3" in svc._LLM_CACHE
    svc._LLM_CACHE.clear()


# ===========================================================================
# dlp_service.py — DLPDetector.from_workspace
# ===========================================================================
def test_from_workspace_invalid_id_returns_disabled(flask_core):
    with flask_core.app_context():
        d = DLPDetector.from_workspace("not-a-uuid")
    assert d.enabled is False


def test_from_workspace_empty_id_returns_disabled(flask_core):
    with flask_core.app_context():
        d = DLPDetector.from_workspace("")
    assert d.enabled is False


def test_from_workspace_not_found_returns_disabled(flask_core):
    import uuid
    with flask_core.app_context():
        d = DLPDetector.from_workspace(str(uuid.uuid4()))
    assert d.enabled is False


def test_from_workspace_loads_enabled_policy(flask_core, test_user):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Acme", owner_id=test_user["_id"], type="team")
        WorkspaceModel.update_settings_subkey(
            ws["_id"], "dlp", {"enabled": True, "sensitivity": "strict"}
        )
        d = DLPDetector.from_workspace(str(ws["_id"]))
    assert d.enabled is True
    assert d._sensitivity == "strict"


# ===========================================================================
# dlp_service.py — _make_snippet / _find_occurrences / _dedup_overlapping
# ===========================================================================
def test_make_snippet_masks_match_and_strips_newlines():
    text = "before\nstuff SECRET after\nmore"
    start = text.index("SECRET")
    end = start + len("SECRET")
    snippet = DLPDetector._make_snippet(text, start, end)
    assert "*" * 6 in snippet
    assert "SECRET" not in snippet
    assert "\n" not in snippet


def test_find_occurrences_exact():
    text = "the token TOK appears TOK twice"
    occ = DLPDetector._find_occurrences(text, "TOK")
    assert len(occ) == 2
    assert all(text[s:e] == "TOK" for s, e in occ)


def test_find_occurrences_empty_span():
    assert DLPDetector._find_occurrences("anything", "  ") == []


def test_find_occurrences_case_insensitive():
    text = "Hello WORLD here"
    occ = DLPDetector._find_occurrences(text, "world")
    assert occ == [(6, 11)]


def test_find_occurrences_whitespace_tolerant():
    text = "the secret  value  lives here"   # double spaces in source
    occ = DLPDetector._find_occurrences(text, "secret value lives")
    assert len(occ) == 1
    assert text[occ[0][0]:occ[0][1]].startswith("secret")


def test_find_occurrences_single_token_no_match_returns_empty():
    # No exact / ci hit and only one token -> the <2 token guard returns [].
    assert DLPDetector._find_occurrences("nothing here", "zzz") == []


def test_dedup_overlapping_empty():
    assert DLPDetector._dedup_overlapping([]) == []


def test_dedup_overlapping_keeps_higher_severity():
    low = DLPMatch("email", "Email", "low", "warn", "*", 0, 10)
    high = DLPMatch("ssn", "SSN", "high", "block", "*", 5, 15)
    kept = DLPDetector._dedup_overlapping([low, high])
    assert len(kept) == 1
    assert kept[0].rule_id == "ssn"


def test_dedup_overlapping_existing_wins_when_candidate_lower():
    high = DLPMatch("ssn", "SSN", "high", "block", "*", 0, 10)
    low = DLPMatch("email", "Email", "low", "warn", "*", 5, 15)
    kept = DLPDetector._dedup_overlapping([high, low])
    assert len(kept) == 1
    assert kept[0].rule_id == "ssn"


def test_dedup_overlapping_non_overlapping_both_kept():
    a = DLPMatch("email", "Email", "low", "warn", "*", 0, 5)
    b = DLPMatch("phone_intl", "Phone", "low", "warn", "*", 10, 20)
    kept = DLPDetector._dedup_overlapping([a, b])
    assert len(kept) == 2


# ===========================================================================
# dlp_service.py — scan() branches
# ===========================================================================
def test_scan_empty_text_returns_blank_result():
    res = _detector().scan("")
    assert res.matches == []
    assert res.text_length == 0
    assert res.highest_action == "allow"


def test_scan_disabled_detector_no_matches():
    d = DLPDetector(effective_policy({"enabled": False}))
    res = d.scan(_AWS_KEY)
    assert res.matches == []
    assert res.text_sha256 != ""  # hash still computed before the enabled gate


def test_scan_block_on_aws_key():
    res = _detector().scan(f"creds {_AWS_KEY} rotate")
    assert res.highest_action == "block"
    assert any(m.rule_id == "aws_access_key" for m in res.matches)


def test_scan_block_on_national_id():
    res = _detector().scan(f"my national id is {_NID}")
    assert res.highest_action == "block"
    assert any(m.rule_id == "national_id_iran" for m in res.matches)


def test_scan_credit_card_luhn_validated():
    res = _detector().scan(f"charge {_CARD} now")
    assert any(m.rule_id == "credit_card" for m in res.matches)


def test_scan_credit_card_invalid_luhn_filtered():
    # A 16-digit run that FAILS Luhn -> the validator continue branch (line 571).
    # 1234 5678 9012 3456 is not Luhn-valid.
    res = _detector().scan("number 1234 5678 9012 3456 here")
    assert not any(m.rule_id == "credit_card" for m in res.matches)


def test_scan_result_to_dict_serializes_matches():
    res = _detector().scan(f"contact {_AWS_KEY}")
    d = res.to_dict()
    assert d["highest_action"] == "block"
    assert d["text_sha256"] == res.text_sha256
    assert d["text_length"] == res.text_length
    m = d["matches"][0]
    assert {"rule_id", "rule_name", "severity", "action", "snippet",
            "offset_start", "offset_end", "source"} <= set(m)
    # category + description are included when present (builtin rules carry both).
    assert "category" in m and "description" in m


def test_scan_lenient_sensitivity_drops_low_and_medium():
    # lenient -> min rank 'high'; an email (low) is filtered out.
    d = DLPDetector(effective_policy({"enabled": True, "sensitivity": "lenient"}))
    res = d.scan(f"contact {_EMAIL}")
    assert res.matches == []


def test_scan_strict_sensitivity_admits_low_email():
    d = DLPDetector(effective_policy({"enabled": True, "sensitivity": "strict"}))
    res = d.scan(f"contact {_EMAIL}")
    assert any(m.rule_id == "email" for m in res.matches)
    assert res.highest_action == "warn"


def test_scan_override_to_allow_skips_rule():
    d = DLPDetector(effective_policy({
        "enabled": True, "sensitivity": "balanced",
        "rule_overrides": {"aws_access_key": "allow"},
    }))
    res = d.scan(f"key {_AWS_KEY}")
    assert not any(m.rule_id == "aws_access_key" for m in res.matches)


def test_scan_override_changes_action():
    # national_id_iran default is block; an explicit block override stays block.
    d = DLPDetector(effective_policy({
        "enabled": True, "sensitivity": "balanced",
        "rule_overrides": {"national_id_iran": "block"},
    }))
    res = d.scan(f"national id {_NID}")
    nid = next(m for m in res.matches if m.rule_id == "national_id_iran")
    assert nid.action == "block"


def test_scan_custom_pattern_matches():
    d = DLPDetector(effective_policy({
        "enabled": True, "sensitivity": "balanced",
        "custom_patterns": [{
            "id": "proj_codename", "name": "Codename",
            "regex": r"PROJECT-[A-Z]+", "severity": "high", "action": "require_confirm",
        }],
    }))
    res = d.scan("the secret is PROJECT-ZEUS launch")
    cm = next(m for m in res.matches if m.rule_id == "proj_codename")
    assert cm.source == "custom"
    assert cm.action == "block"


def test_scan_custom_pattern_invalid_regex_skipped():
    d = DLPDetector(effective_policy({
        "enabled": True, "sensitivity": "balanced",
        "custom_patterns": [
            {"name": "bad", "regex": "(", "severity": "high", "action": "warn"},
        ],
    }))
    # Invalid regex is compiled to None and skipped; no crash, no matches.
    res = d.scan("anything at all")
    assert res.matches == []


def test_scan_custom_pattern_empty_regex_skipped():
    d = DLPDetector(effective_policy({
        "enabled": True, "sensitivity": "balanced",
        "custom_patterns": [{"name": "blank", "regex": "", "severity": "high"}],
    }))
    res = d.scan("text")
    assert res.matches == []


def test_scan_custom_pattern_below_sensitivity_filtered():
    # A 'low' custom rule under balanced (min medium) is filtered out.
    d = DLPDetector(effective_policy({
        "enabled": True, "sensitivity": "balanced",
        "custom_patterns": [{
            "id": "lo", "name": "Lo", "regex": "MARKER",
            "severity": "low", "action": "warn",
        }],
    }))
    res = d.scan("here is a MARKER")
    assert res.matches == []


def test_scan_custom_pattern_defaults_id_and_name():
    # No id/name/severity/action -> defaults (medium/warn) and generated id/name.
    d = DLPDetector(effective_policy({
        "enabled": True, "sensitivity": "balanced",
        "custom_patterns": [{"regex": "WIDGET"}],
    }))
    res = d.scan("the WIDGET is here")
    cm = res.matches[0]
    assert cm.rule_id.startswith("custom:")
    assert cm.rule_name.startswith("Custom:")
    assert cm.severity == "medium"
    assert cm.action == "warn"


def test_scan_internal_hostname_rule():
    d = DLPDetector(effective_policy({
        "enabled": True, "sensitivity": "balanced",
        "internal_hostname_suffixes": [".corp.local"],
    }))
    res = d.scan("ssh into db01.corp.local now")
    hm = next(m for m in res.matches if m.rule_id == "internal_hostname")
    assert hm.severity == "medium"
    assert hm.action == "warn"
    assert hm.source == "hostname"


def test_scan_internal_hostname_override_allow():
    d = DLPDetector(effective_policy({
        "enabled": True, "sensitivity": "balanced",
        "internal_hostname_suffixes": [".corp.local"],
        "rule_overrides": {"internal_hostname": "allow"},
    }))
    res = d.scan("db01.corp.local")
    assert not any(m.rule_id == "internal_hostname" for m in res.matches)


def test_scan_internal_hostname_filtered_under_lenient():
    # medium severity hostname is dropped under lenient (min 'high').
    d = DLPDetector(effective_policy({
        "enabled": True, "sensitivity": "lenient",
        "internal_hostname_suffixes": [".corp.local"],
    }))
    res = d.scan("db01.corp.local")
    assert not any(m.rule_id == "internal_hostname" for m in res.matches)


# ===========================================================================
# dlp_service.py — smart-scan augmentation (llm_classify monkeypatched)
# ===========================================================================
def _stub_classify(verdict):
    def _fn(self, text, user_lang="en", *, user_id=None):
        return verdict
    return _fn


def test_scan_skips_llm_when_regex_blocks(monkeypatch):
    # block is non-overridable max action — LLM cannot escalate past it and
    # only adds latency. Fix A short-circuits before llm_classify.
    called = {"n": 0}

    def _spy(self, text, user_lang="en", *, user_id=None):
        called["n"] += 1
        return {"category": "restricted", "reason": "r", "spans": []}

    monkeypatch.setattr(DLPDetector, "llm_classify", _spy)
    res = _detector().scan(f"key {_AWS_KEY}")  # critical → block
    assert called["n"] == 0
    assert res.highest_action == "block"
    assert any(m.rule_id == "aws_access_key" for m in res.matches)


def test_scan_skip_llm_flag_skips_classify(monkeypatch):
    # Explicit skip_llm=True runs regex path only (gate confirm re-scan).
    called = {"n": 0}

    def _spy(self, text, user_lang="en", *, user_id=None):
        called["n"] += 1
        return {"category": "restricted", "reason": "r", "spans": ["ZEUS"]}

    monkeypatch.setattr(DLPDetector, "llm_classify", _spy)
    res = _detector().scan("launch codename ZEUS soon enough", skip_llm=True)
    assert called["n"] == 0
    assert res.matches == []
    assert res.highest_action == "allow"
    assert res.text_sha256  # sha still computed for token verify


def test_scan_block_regex_skips_llm_on_national_id(monkeypatch):
    # Builtin high rules are block, so smart-scan does not run.
    called = {"n": 0}

    def _spy(self, text, user_lang="en", *, user_id=None):
        called["n"] += 1
        return {"category": "restricted", "reason": "r", "spans": []}

    monkeypatch.setattr(DLPDetector, "llm_classify", _spy)
    res = _detector().scan(f"national id {_NID}")
    assert called["n"] == 0
    assert res.highest_action == "block"


def test_scan_smart_scan_masks_high_severity_warn(monkeypatch):
    # A high-severity warn (custom rule) still runs smart-scan. Remote path
    # masks those spans before the model call. Builtin high rules are block
    # and short-circuit before the LLM.
    called = {"n": 0, "texts": []}

    def _spy(self, text, user_lang="en", *, user_id=None):
        called["n"] += 1
        called["texts"].append(text)
        return {"category": "confidential", "reason": "r", "spans": []}

    monkeypatch.setattr(DLPDetector, "llm_classify", _spy)
    monkeypatch.setitem(
        __import__("app.services.dlp_service", fromlist=["settings"]).settings,
        "DLP_LLM_BASE_URL",
        "",
    )
    d = DLPDetector(effective_policy({
        "enabled": True,
        "sensitivity": "balanced",
        "custom_patterns": [{
            "id": "proj", "name": "Proj",
            "regex": "PROJECT-ZEUS", "severity": "high", "action": "warn",
        }],
    }))
    res = d.scan("launch PROJECT-ZEUS soon")
    assert called["n"] == 1
    assert "PROJECT-ZEUS" not in called["texts"][0]
    assert "[REDACTED]" in called["texts"][0]
    assert res.highest_action == "warn"


def test_scan_smart_scan_locates_span_and_raises_action(monkeypatch):
    # No regex match; classifier flags a restricted span present in the text.
    monkeypatch.setattr(
        DLPDetector, "llm_classify",
        _stub_classify({"category": "restricted", "reason": "key",
                        "spans": ["ZEUS"]}),
    )
    res = _detector().scan("launch codename ZEUS soon enough")
    llm = next(m for m in res.matches if m.source == "llm")
    assert llm.action == "block"
    assert llm.offset_end > llm.offset_start
    assert res.highest_action == "block"


def test_scan_smart_scan_confidential_warn(monkeypatch):
    monkeypatch.setattr(
        DLPDetector, "llm_classify",
        _stub_classify({"category": "confidential", "reason": "contact",
                        "spans": ["Bob Smith"]}),
    )
    res = _detector().scan("the manager is Bob Smith over there")
    llm = next(m for m in res.matches if m.source == "llm")
    assert llm.action == "warn"
    assert llm.severity == "medium"


def test_scan_smart_scan_public_no_match(monkeypatch):
    monkeypatch.setattr(
        DLPDetector, "llm_classify",
        _stub_classify({"category": "public", "reason": "", "spans": []}),
    )
    res = _detector().scan("just a normal question about things")
    assert res.matches == []
    assert res.highest_action == "allow"


def test_scan_smart_scan_spanless_marker_appended(monkeypatch):
    # Restricted but NO spans -> a spanless (0,0) marker is appended.
    monkeypatch.setattr(
        DLPDetector, "llm_classify",
        _stub_classify({"category": "restricted", "reason": "vague", "spans": []}),
    )
    res = _detector().scan("there is something sensitive in here somewhere")
    llm = [m for m in res.matches if m.source == "llm"]
    assert llm and any(m.offset_start == 0 and m.offset_end == 0 for m in llm)


def test_scan_smart_scan_unlocatable_span_marks_unredactable(monkeypatch):
    # Span that does not appear in the text -> has_unredactable -> (0,0) marker.
    monkeypatch.setattr(
        DLPDetector, "llm_classify",
        _stub_classify({"category": "restricted", "reason": "x",
                        "spans": ["NOT-IN-TEXT-AT-ALL"]}),
    )
    res = _detector().scan("a wholly unrelated message body here")
    llm = [m for m in res.matches if m.source == "llm"]
    assert any(m.offset_start == 0 and m.offset_end == 0 for m in llm)


def test_scan_smart_scan_span_overlapping_regex_skipped(monkeypatch):
    # The email regex (strict admits low) already covers the span; the llm
    # occurrence overlapping it is skipped (continue branch).
    monkeypatch.setattr(
        DLPDetector, "llm_classify",
        _stub_classify({"category": "confidential", "reason": "email",
                        "spans": [_EMAIL]}),
    )
    d = DLPDetector(effective_policy({"enabled": True, "sensitivity": "strict"}))
    res = d.scan(f"reach me at {_EMAIL} thanks")
    # Email present as a regex (builtin) match; the overlapping llm span is not
    # added as a duplicate located span.
    located_llm = [m for m in res.matches
                   if m.source == "llm" and m.offset_end > m.offset_start]
    assert located_llm == []


# ===========================================================================
# dlp_service.py — redact()
# ===========================================================================
def test_redact_no_matches_returns_text_unchanged():
    d = _detector()
    out, redactions, result = d.redact("nothing sensitive here at all")
    assert out == "nothing sensitive here at all"
    assert redactions == []
    assert result.matches == []


def test_redact_splices_card_with_placeholder():
    d = _detector()
    out, redactions, result = d.redact(f"please charge {_CARD} now")
    assert "[CARD_1]" in out
    assert _CARD not in out
    assert any(r["label"] == "CARD" for r in redactions)


def test_redact_reuses_placeholder_for_repeated_value():
    d = DLPDetector(effective_policy({"enabled": True, "sensitivity": "strict"}))
    out, redactions, _ = d.redact(f"mail {_EMAIL} and again {_EMAIL}")
    # Same value -> same token both times -> only one redaction descriptor.
    assert out.count("[EMAIL_1]") == 2
    assert len([r for r in redactions if r["label"] == "EMAIL"]) == 1


def test_redact_skips_spanless_llm_marker(monkeypatch):
    monkeypatch.setattr(
        DLPDetector, "llm_classify",
        _stub_classify({"category": "restricted", "reason": "x", "spans": []}),
    )
    d = _detector()
    out, redactions, result = d.redact("a generic message with no concrete value")
    # The spanless (0,0) marker can't be spliced -> text unchanged.
    assert out == "a generic message with no concrete value"
    assert redactions == []


# ===========================================================================
# dlp_service.py — llm_classify (OpenRouterService monkeypatched)
# ===========================================================================
def _enabled_llm_detector():
    return DLPDetector(effective_policy({
        "enabled": True, "sensitivity": "balanced",
        "llm_classifier": {"enabled": True},
    }))


def test_llm_classify_disabled_returns_none():
    # llm_classifier disabled by default.
    assert _detector().llm_classify("some long enough text here") is None


def test_llm_classify_blank_text_returns_none():
    assert _enabled_llm_detector().llm_classify("   ") is None


def test_llm_classify_too_short_returns_none():
    # Below _SMARTSCAN_MIN_CHARS (6) -> skipped.
    assert _enabled_llm_detector().llm_classify("hi") is None


def _patch_sync_completion(monkeypatch, return_value=None, raises=None):
    from app.services.openrouter_service import OpenRouterService

    def _fake(payload, **kwargs):
        if raises is not None:
            raise raises
        return return_value

    monkeypatch.setattr(OpenRouterService, "_sync_completion", staticmethod(_fake))


def _llm_json(category, spans=None, reason="because"):
    import json as _json
    content = _json.dumps({"category": category, "reason": reason,
                           "spans": spans or []})
    return {"choices": [{"message": {"content": content}}]}


def test_llm_classify_happy_restricted(monkeypatch):
    svc._LLM_CACHE.clear()
    _patch_sync_completion(monkeypatch, _llm_json("restricted", ["SECRET"]))
    v = _enabled_llm_detector().llm_classify("this message has a SECRET inside")
    assert v["category"] == "restricted"
    assert v["spans"] == ["SECRET"]
    svc._LLM_CACHE.clear()


def test_llm_classify_uses_cache(monkeypatch):
    svc._LLM_CACHE.clear()
    calls = {"n": 0}
    from app.services.openrouter_service import OpenRouterService

    def _fake(payload, **kwargs):
        calls["n"] += 1
        return _llm_json("confidential", ["a@b.com"])

    monkeypatch.setattr(OpenRouterService, "_sync_completion", staticmethod(_fake))
    d = _enabled_llm_detector()
    first = d.llm_classify("a repeated message body for caching")
    second = d.llm_classify("a repeated message body for caching")
    assert first == second
    assert calls["n"] == 1  # second served from cache
    svc._LLM_CACHE.clear()


def test_llm_classify_with_guidance_prompt(monkeypatch):
    svc._LLM_CACHE.clear()
    captured = {}
    from app.services.openrouter_service import OpenRouterService

    def _fake(payload, **kwargs):
        captured["system"] = payload["messages"][0]["content"]
        return _llm_json("public")

    monkeypatch.setattr(OpenRouterService, "_sync_completion", staticmethod(_fake))
    d = DLPDetector(effective_policy({
        "enabled": True, "sensitivity": "balanced",
        "llm_classifier": {"enabled": True, "guidance_prompt": "flag widgets"},
    }))
    d.llm_classify("a message long enough to scan for widgets")
    assert "flag widgets" in captured["system"]
    # Custom guidance is mounted as an authoritative WORKSPACE POLICY block
    # (not a weak footer that the span-empty rule can ignore).
    assert "WORKSPACE POLICY" in captured["system"]
    assert "prefer the workspace policy" in captured["system"].lower()
    svc._LLM_CACHE.clear()


def test_llm_classify_call_raises_fails_open(monkeypatch):
    svc._LLM_CACHE.clear()
    _patch_sync_completion(monkeypatch, raises=RuntimeError("boom"))
    assert _enabled_llm_detector().llm_classify("some message body to scan") is None
    svc._LLM_CACHE.clear()


def test_llm_classify_error_dict_returns_none(monkeypatch):
    svc._LLM_CACHE.clear()
    _patch_sync_completion(monkeypatch, {"error": "rate limited"})
    assert _enabled_llm_detector().llm_classify("another message body here") is None
    svc._LLM_CACHE.clear()


def test_llm_classify_non_dict_response_returns_none(monkeypatch):
    svc._LLM_CACHE.clear()
    _patch_sync_completion(monkeypatch, "not a dict")
    assert _enabled_llm_detector().llm_classify("yet another message body") is None
    svc._LLM_CACHE.clear()


def test_llm_classify_invalid_category_returns_none(monkeypatch):
    svc._LLM_CACHE.clear()
    _patch_sync_completion(monkeypatch, _llm_json("totally-bogus"))
    assert _enabled_llm_detector().llm_classify("a scannable message body") is None
    svc._LLM_CACHE.clear()


def test_llm_classify_malformed_json_returns_none(monkeypatch):
    svc._LLM_CACHE.clear()
    bad = {"choices": [{"message": {"content": "not json at all"}}]}
    _patch_sync_completion(monkeypatch, bad)
    assert _enabled_llm_detector().llm_classify("a scannable message body two") is None
    svc._LLM_CACHE.clear()


def test_llm_classify_strips_code_fence(monkeypatch):
    svc._LLM_CACHE.clear()
    import json as _json
    fenced = "```json\n" + _json.dumps(
        {"category": "confidential", "reason": "r", "spans": ["x@y.com"]}
    ) + "\n```"
    resp = {"choices": [{"message": {"content": fenced}}]}
    _patch_sync_completion(monkeypatch, resp)
    v = _enabled_llm_detector().llm_classify("a fenced response message body")
    assert v["category"] == "confidential"
    assert v["spans"] == ["x@y.com"]
    svc._LLM_CACHE.clear()


def test_llm_classify_caps_spans_at_30(monkeypatch):
    svc._LLM_CACHE.clear()
    many = [f"span-{i}" for i in range(50)]
    _patch_sync_completion(monkeypatch, _llm_json("restricted", many))
    v = _enabled_llm_detector().llm_classify("a message with very many spans")
    assert len(v["spans"]) == 30
    svc._LLM_CACHE.clear()


def test_llm_classify_drops_blank_and_nonstr_spans(monkeypatch):
    svc._LLM_CACHE.clear()
    spans = ["  ", "", 123, None, "real-span"]
    _patch_sync_completion(monkeypatch, _llm_json("restricted", spans))
    v = _enabled_llm_detector().llm_classify("a message with mixed span types")
    assert v["spans"] == ["real-span"]
    svc._LLM_CACHE.clear()


# --- Local Ollama backend (DLP_LLM_BASE_URL set) ---------------------------

def test_llm_classify_local_backend_used(monkeypatch):
    """With DLP_LLM_BASE_URL set, classify hits the local client (native shape),
    NOT OpenRouter, and the locked model becomes DLP_LLM_MODEL."""
    svc._LLM_CACHE.clear()
    import json as _json
    import app.services.local_llm_service as lls

    # OpenRouter path must NOT be taken — make it explode if it is.
    _patch_sync_completion(monkeypatch, raises=AssertionError("OpenRouter must not be called"))
    monkeypatch.setitem(svc.settings, "DLP_LLM_BASE_URL", "https://ollama.test:9443")
    monkeypatch.setitem(svc.settings, "DLP_LLM_MODEL", "qwen3.6:35b")

    captured = {}

    def _fake(messages, **kwargs):
        captured.update(kwargs)
        captured["messages"] = messages
        # Native /api/chat returns the content string directly (no choices wrap).
        return _json.dumps({"category": "restricted", "reason": "r", "spans": ["SECRET"]})

    monkeypatch.setattr(lls, "dlp_classify_content", _fake)

    v = _enabled_llm_detector().llm_classify("this message has a SECRET inside it")
    assert v["category"] == "restricted"
    assert v["spans"] == ["SECRET"]
    assert captured["base_url"] == "https://ollama.test:9443"
    assert captured["model"] == "qwen3.6:35b"
    svc._LLM_CACHE.clear()


def test_llm_classify_local_backend_failopen(monkeypatch):
    """Local client returning None (timeout/error) => fail-open, no OpenRouter fallback."""
    svc._LLM_CACHE.clear()
    import app.services.local_llm_service as lls

    _patch_sync_completion(monkeypatch, raises=AssertionError("no OpenRouter fallback allowed"))
    monkeypatch.setitem(svc.settings, "DLP_LLM_BASE_URL", "https://ollama.test:9443")
    monkeypatch.setattr(lls, "dlp_classify_content", lambda messages, **kw: None)

    assert _enabled_llm_detector().llm_classify("a scannable message body here") is None
    svc._LLM_CACHE.clear()


# ===========================================================================
# dlp_gate.py — gate()
# ===========================================================================
def _seed_ws(flask_core, owner_id, dlp):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Gate Co", owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, "owner", status="active")
        WorkspaceModel.update_settings_subkey(ws["_id"], "dlp", dlp)
        return WorkspaceModel.find_by_id(ws["_id"])


_ENABLED = {"enabled": True, "sensitivity": "balanced", "mode": "enforce"}


def test_gate_no_text_returns_none(flask_core):
    with flask_core.app_context():
        assert gate(text="", user_id=None, workspace_id="x", source="chat",
                    source_ref={"preflight": True}) is None


def test_gate_no_workspace_returns_none(flask_core):
    with flask_core.app_context():
        assert gate(text="hi", user_id=None, workspace_id=None, source="chat",
                    source_ref={"preflight": True}) is None


def test_gate_no_matches_returns_none(flask_core, test_user):
    ws = _seed_ws(flask_core, test_user["_id"], _ENABLED)
    with flask_core.app_context():
        assert gate(
            text="nothing sensitive here", user_id=test_user["_id"],
            workspace_id=ws["_id"], source="chat", source_ref={"preflight": True},
        ) is None


def test_gate_block_raises_dlp_blocked(flask_core, test_user):
    ws = _seed_ws(flask_core, test_user["_id"], _ENABLED)
    with flask_core.app_context():
        with pytest.raises(DLPBlockedError) as ei:
            gate(text=f"key {_AWS_KEY}", user_id=test_user["_id"],
                 workspace_id=ws["_id"], source="chat",
                 source_ref={"preflight": True})
    assert ei.value.code == "dlp_blocked"
    assert any(m["rule_id"] == "aws_access_key" for m in ei.value.matches)


def test_gate_national_id_blocks_even_when_confirmed(flask_core, test_user):
    ws = _seed_ws(flask_core, test_user["_id"], _ENABLED)
    with flask_core.app_context():
        with pytest.raises(DLPBlockedError) as ei:
            gate(text=f"national id {_NID}", user_id=test_user["_id"],
                 workspace_id=ws["_id"], source="chat",
                 source_ref={"preflight": True},
                 confirmed=True, dlp_confirm_token="garbage.token")
    assert ei.value.code == "dlp_blocked"


def test_gate_signed_token_does_not_unlock(flask_core, test_user):
    import hashlib
    from app.services.dlp_tokens import _sign_dlp_token, _DLP_CONFIRM_TOKEN_TTL_S

    ws = _seed_ws(flask_core, test_user["_id"], _ENABLED)
    text = f"national id {_NID}"
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    exp = int(time.time()) + _DLP_CONFIRM_TOKEN_TTL_S
    with flask_core.app_context():
        token = _sign_dlp_token(f"{sha}|{test_user['_id']}|{ws['_id']}|{exp}")
        with pytest.raises(DLPBlockedError) as ei:
            gate(
                text=text, user_id=test_user["_id"], workspace_id=ws["_id"],
                source="chat", source_ref={"preflight": True},
                confirmed=True, dlp_confirm_token=token,
            )
    assert ei.value.code == "dlp_blocked"
    assert ei.value.confirm_token is None


def test_gate_confirmed_token_does_not_skip_llm(flask_core, test_user, monkeypatch):
    # No regex hit. A confirm token must not skip the LLM or allow the send.
    import hashlib
    from app.services.dlp_tokens import _sign_dlp_token, _DLP_CONFIRM_TOKEN_TTL_S

    called = {"n": 0}

    def _spy(self, text, user_lang="en", *, user_id=None):
        called["n"] += 1
        return {"category": "restricted", "reason": "x", "spans": ["ZEUS"]}

    monkeypatch.setattr(DLPDetector, "llm_classify", _spy)
    ws = _seed_ws(flask_core, test_user["_id"], _ENABLED)
    text = "launch codename ZEUS soon enough"
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    exp = int(time.time()) + _DLP_CONFIRM_TOKEN_TTL_S
    with flask_core.app_context():
        token = _sign_dlp_token(f"{sha}|{test_user['_id']}|{ws['_id']}|{exp}")
        with pytest.raises(DLPBlockedError) as ei:
            gate(
                text=text, user_id=test_user["_id"], workspace_id=ws["_id"],
                source="chat", source_ref={"preflight": True},
                confirmed=True, dlp_confirm_token=token,
            )
    assert ei.value.code == "dlp_blocked"
    assert called["n"] == 1


def test_gate_garbage_token_still_blocks_llm_hit(
    flask_core, test_user, monkeypatch,
):
    monkeypatch.setattr(
        DLPDetector, "llm_classify",
        _stub_classify({"category": "restricted", "reason": "key",
                        "spans": ["ZEUS"]}),
    )
    ws = _seed_ws(flask_core, test_user["_id"], _ENABLED)
    with flask_core.app_context():
        with pytest.raises(DLPBlockedError) as ei:
            gate(
                text="launch codename ZEUS soon enough",
                user_id=test_user["_id"], workspace_id=ws["_id"],
                source="chat", source_ref={"preflight": True},
                confirmed=True, dlp_confirm_token="garbage.token",
            )
    assert ei.value.code == "dlp_blocked"


def test_gate_warn_returns_event_no_raise(flask_core, test_user):
    # strict sensitivity admits email (low/warn); warn neither blocks nor confirms.
    ws = _seed_ws(flask_core, test_user["_id"],
                  {"enabled": True, "sensitivity": "strict", "mode": "enforce"})
    with flask_core.app_context():
        event = gate(
            text=f"contact {_EMAIL}", user_id=test_user["_id"],
            workspace_id=ws["_id"], source="chat", source_ref={"preflight": True},
        )
    assert event is not None
    assert event["highest_action"] == "warn"


# ===========================================================================
# dlp_gate.py — gate_redactable()
# ===========================================================================
def test_gate_redactable_no_text():
    out = gate_redactable(text="", user_id=None, workspace_id="x", source="chat",
                          source_ref={"preflight": True})
    assert out == {"redacted": False, "redacted_text": "", "redactions": [],
                   "event": None}


def test_gate_redactable_enforce_delegates_to_gate(flask_core, test_user):
    # Enforce mode (not redact) -> delegates to gate(); a block raises.
    ws = _seed_ws(flask_core, test_user["_id"], _ENABLED)
    with flask_core.app_context():
        with pytest.raises(DLPBlockedError):
            gate_redactable(text=f"key {_AWS_KEY}", user_id=test_user["_id"],
                            workspace_id=ws["_id"], source="chat",
                            source_ref={"preflight": True})


def test_gate_redactable_enforce_clean_text_returns_unredacted(flask_core, test_user):
    ws = _seed_ws(flask_core, test_user["_id"], _ENABLED)
    with flask_core.app_context():
        out = gate_redactable(text="totally clean message", user_id=test_user["_id"],
                              workspace_id=ws["_id"], source="chat",
                              source_ref={"preflight": True})
    assert out["redacted"] is False
    assert out["redacted_text"] == "totally clean message"
    assert out["event"] is None


def test_gate_redactable_redact_mode_splices(flask_core, test_user):
    ws = _seed_ws(flask_core, test_user["_id"],
                  {"enabled": True, "sensitivity": "balanced", "mode": "redact"})
    with flask_core.app_context():
        out = gate_redactable(text=f"charge {_CARD} please", user_id=test_user["_id"],
                              workspace_id=ws["_id"], source="chat",
                              source_ref={"preflight": True})
    assert out["redacted"] is True
    assert "[CARD_1]" in out["redacted_text"]
    assert _CARD not in out["redacted_text"]
    assert out["event"] is not None
    assert any(r["label"] == "CARD" for r in out["redactions"])


def test_gate_redactable_redact_mode_clean_text_no_event(flask_core, test_user):
    ws = _seed_ws(flask_core, test_user["_id"],
                  {"enabled": True, "sensitivity": "balanced", "mode": "redact"})
    with flask_core.app_context():
        out = gate_redactable(text="a perfectly clean message", user_id=test_user["_id"],
                              workspace_id=ws["_id"], source="chat",
                              source_ref={"preflight": True})
    assert out["redacted"] is False
    assert out["event"] is None


def test_gate_redactable_force_redact_overrides_enforce(flask_core, test_user):
    # Policy is enforce, but force_redact=True triggers the redact path.
    ws = _seed_ws(flask_core, test_user["_id"], _ENABLED)
    with flask_core.app_context():
        out = gate_redactable(text=f"charge {_CARD} now", user_id=test_user["_id"],
                              workspace_id=ws["_id"], source="chat",
                              source_ref={"preflight": True}, force_redact=True)
    assert out["redacted"] is True
    assert "[CARD_1]" in out["redacted_text"]


def test_gate_redactable_spanless_llm_logs_but_sends(flask_core, test_user, monkeypatch):
    # redact mode + a spanless llm marker -> located spans redacted, spanless
    # remainder is advisory (sent), event persisted.
    monkeypatch.setattr(
        DLPDetector, "llm_classify",
        _stub_classify({"category": "restricted", "reason": "x",
                        "spans": ["VISIBLE-SPAN"]}),
    )
    ws = _seed_ws(flask_core, test_user["_id"],
                  {"enabled": True, "sensitivity": "balanced", "mode": "redact"})
    with flask_core.app_context():
        out = gate_redactable(
            text="please keep VISIBLE-SPAN safe but extra note", user_id=test_user["_id"],
            workspace_id=ws["_id"], source="chat", source_ref={"preflight": True},
        )
    assert out["redacted"] is True
    assert "VISIBLE-SPAN" not in out["redacted_text"]


# ===========================================================================
# dlp_gate.py — _highest_severity + format_blocked_response
# ===========================================================================
def test_gate_highest_severity_picks_strongest():
    matches = [{"severity": "low"}, {"severity": "high"}, {"severity": "medium"}]
    assert _highest_severity(matches) == "high"


def test_format_blocked_response_block():
    err = DLPBlockedError(
        code="dlp_blocked",
        matches=[{
            "rule_id": "aws_access_key", "rule_name": "AWS Access Key",
            "severity": "critical", "action": "block",
            "offset_start": 0, "offset_end": 5, "snippet": "*****",
        }],
    )
    body = format_blocked_response(err)
    assert body["code"] == "dlp_blocked"
    assert "blocked" in body["error"].lower()
    assert body["matches"][0]["rule_id"] == "aws_access_key"


def test_format_blocked_response_has_no_confirm_token():
    err = DLPBlockedError(
        code="dlp_blocked",
        matches=[{
            "rule_id": "jwt_token", "rule_name": "JWT",
            "severity": "high", "action": "block",
            "offset_start": 0, "offset_end": 4, "snippet": "****",
        }],
        confirm_token="not-minted",
    )
    body = format_blocked_response(err)
    assert body["code"] == "dlp_blocked"
    assert "confirm_token" not in body
    assert "confirmation" not in body["error"].lower()
