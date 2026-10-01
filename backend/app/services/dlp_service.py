"""
DLP detector service.

Usage:
    policy = effective_policy(workspace.get('settings', {}).get('dlp'))
    detector = DLPDetector(policy)
    result = detector.scan(user_text)

Or, fetching from DB:
    detector = DLPDetector.from_workspace(workspace_id_str)
    result = detector.scan(user_text)
"""
import hashlib
import json
import logging
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.services.dlp_rules import BUILTIN_RULES
from app.settings import settings

logger = logging.getLogger(__name__)

# Smart-scan cost gate: skip the LLM classify call for messages shorter than
# this (greetings, acknowledgements) that can't plausibly carry a flagged value.
# Conservative default; override via env. Kept low so short codenames aren't missed.
try:
    _SMARTSCAN_MIN_CHARS = max(0, int(os.environ.get('DLP_SMARTSCAN_MIN_CHARS', '6')))
except (TypeError, ValueError):
    _SMARTSCAN_MIN_CHARS = 6

# ReDoS containment for OWNER-AUTHORED custom regex patterns (match_type='regex').
# Custom patterns are validated for SYNTAX only at save time and run via CPython's
# backtracking SRE engine — a pathological pattern like ``(a+)+$`` can stall a
# worker thread (the GIL is held through the C-level finditer) for the whole
# offloaded DLP pass, which is cross-tenant blast radius on the shared threadpool.
# Save-time heuristics (api/routers/dlp.py) reject the obvious catastrophic shapes;
# this is the scan-time backstop — the custom-pattern finditer NEVER sees more than
# this many chars, so even a heuristic-evading pattern can't backtrack over the full
# 400k-char attachment ceiling (DOC_EXTRACT_TOTAL_MAX_CHARS). Builtin rules are
# UNCAPPED — they were benchmarked linear (each is anchored / pre_filtered). The
# durable fix is a linear-time engine (re2/pyre2); that's a new dep, out of scope.
try:
    _CUSTOM_REGEX_MAX_CHARS = max(0, int(os.environ.get('DLP_CUSTOM_REGEX_MAX_CHARS', '20000')))
except (TypeError, ValueError):
    _CUSTOM_REGEX_MAX_CHARS = 20000

# ---------------------------------------------------------------------------
# Action / severity ranking helpers
# ---------------------------------------------------------------------------

ACTION_RANK: dict[str, int] = {
    "allow": 0,
    "warn": 1,
    # Historical rank only. Live policy never emits this; collapse_action maps it to block.
    "require_confirm": 2,
    "block": 3,
}


def collapse_action(action) -> str:
    """Live actions are warn and block. ``require_confirm`` is not live."""
    if action == "require_confirm":
        return "block"
    if isinstance(action, str):
        return action
    return ""

SEVERITY_RANK: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}

# Effective minimum severity rank per sensitivity
_SENSITIVITY_MIN_RANK: dict[str, int] = {
    "lenient": SEVERITY_RANK["high"],
    "balanced": SEVERITY_RANK["medium"],
    "strict": SEVERITY_RANK["low"],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DLPMatch:
    rule_id: str
    rule_name: str
    severity: str
    action: str
    snippet: str          # ±20 chars context with match replaced by '*'
    offset_start: int
    offset_end: int
    category: Optional[str] = None
    description: Optional[str] = None
    # 'builtin' | 'custom' | 'hostname' | 'llm'
    source: str = 'builtin'


@dataclass
class DLPScanResult:
    matches: list[DLPMatch] = field(default_factory=list)
    highest_action: str = "allow"
    text_sha256: str = ""
    text_length: int = 0

    def to_dict(self) -> dict:
        out_matches: list[dict] = []
        for m in self.matches:
            entry: dict = {
                "rule_id": m.rule_id,
                "rule_name": m.rule_name,
                "severity": m.severity,
                "action": m.action,
                "snippet": m.snippet,
                "offset_start": m.offset_start,
                "offset_end": m.offset_end,
                "source": m.source,
            }
            if m.category is not None:
                entry["category"] = m.category
            if m.description is not None:
                entry["description"] = m.description
            out_matches.append(entry)
        return {
            "matches": out_matches,
            "highest_action": self.highest_action,
            "text_sha256": self.text_sha256,
            "text_length": self.text_length,
        }


# ---------------------------------------------------------------------------
# Policy resolver
# ---------------------------------------------------------------------------

_POLICY_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "sensitivity": "balanced",
    # "enforce" = block/warn posture. "redact" = splice sensitive
    # spans out (replace with typed placeholders) and let the scrubbed text pass.
    "mode": "enforce",
    "rule_overrides": {},
    # Rule ids the workspace owner has switched off entirely (simple on/off
    # toggle, independent of rule_overrides action tuning). Disabled rules are
    # skipped at scan time regardless of severity.
    "disabled_rules": [],
    "custom_patterns": [],
    "internal_hostname_suffixes": [],
    "llm_classifier": {
        "enabled": False,
        "model": "google/gemini-3.5-flash-lite",
        "guidance_prompt": "",
        "action_thresholds": {
            "confidential": "warn",
            "restricted": "block",
        },
    },
    "notify_owners": True,
}


# Server-side lock for the smart-scan model on the OpenRouter path.
_LOCKED_LLM_MODEL = "google/gemini-3.5-flash-lite"


def dlp_locked_model() -> str:
    """The model the smart-scan classifier is locked to, given the active backend.

    When ``DLP_LLM_BASE_URL`` is configured the classifier runs against the local
    Ollama server, so the locked model is ``DLP_LLM_MODEL`` (e.g. ``qwen3.6:35b``);
    otherwise it's the OpenRouter default. Imported by ``api/routers/dlp.py`` so
    the stored/displayed policy model reflects whichever backend is live.
    """
    if (settings.get('DLP_LLM_BASE_URL') or '').strip():
        return settings.get('DLP_LLM_MODEL') or 'qwen3.6:35b'
    return _LOCKED_LLM_MODEL


def effective_policy(raw_dlp: Optional[dict]) -> dict:
    """
    Merge workspace DLP settings with defaults.

    Args:
        raw_dlp: The value of workspaces.settings.dlp (may be None or partial).

    Returns:
        Fully populated policy dict.

    Note (P0.7): the LLM classifier ``model`` field is force-overwritten to
    the locked value even when the workspace doc holds a stale value (e.g. a
    legacy row that pre-dates the validator clamp in routes/dlp.py). The
    request path reads from here, so this is the single chokepoint that
    matters at scan time.
    """
    if raw_dlp is None:
        raw_dlp = {}

    merged: dict[str, Any] = dict(_POLICY_DEFAULTS)

    for key in _POLICY_DEFAULTS:
        if key in raw_dlp:
            raw_val = raw_dlp[key]
            # Deep-merge llm_classifier sub-dict
            if key == "llm_classifier" and isinstance(raw_val, dict):
                merged[key] = {**_POLICY_DEFAULTS[key], **raw_val}
            else:
                merged[key] = raw_val

    # Force-lock the smart-scan model irrespective of stored config (P0.7).
    lc = merged.get("llm_classifier")
    if isinstance(lc, dict):
        lc["model"] = dlp_locked_model()
        thresholds = lc.get("action_thresholds")
        if isinstance(thresholds, dict):
            lc["action_thresholds"] = {
                key: collapse_action(val) if isinstance(val, str) else val
                for key, val in thresholds.items()
            }

    overrides = merged.get("rule_overrides")
    if isinstance(overrides, dict):
        merged["rule_overrides"] = {
            key: collapse_action(val) if isinstance(val, str) else val
            for key, val in overrides.items()
        }

    patterns = merged.get("custom_patterns")
    if isinstance(patterns, list):
        collapsed_patterns = []
        for pat in patterns:
            if isinstance(pat, dict) and isinstance(pat.get("action"), str):
                pat = {**pat, "action": collapse_action(pat["action"])}
            collapsed_patterns.append(pat)
        merged["custom_patterns"] = collapsed_patterns

    return merged


# ---------------------------------------------------------------------------
# Language resolution for smart-scan reason output
# ---------------------------------------------------------------------------

# Common 2-char prefixes the chokepoints emit (truncated from
# user.ai_preferences.user_info.language). Maps to full English language names
# the model can recognize. Unknown values fall back to English.
_LANG_NAMES: dict[str, str] = {
    'en': 'English',
    'fa': 'Persian',
    'pe': 'Persian',
    'ar': 'Arabic',
    'de': 'German',
    'ge': 'German',
    'fr': 'French',
    'es': 'Spanish',
    'sp': 'Spanish',
    'it': 'Italian',
    'pt': 'Portuguese',
    'po': 'Portuguese',
    'ru': 'Russian',
    'tr': 'Turkish',
    'tu': 'Turkish',
    'ja': 'Japanese',
    'ko': 'Korean',
    'zh': 'Chinese',
    'ch': 'Chinese',
    'hi': 'Hindi',
    'nl': 'Dutch',
    'sv': 'Swedish',
    'pl': 'Polish',
}


def _resolve_lang_name(user_lang: str) -> str:
    code = (user_lang or '').strip().lower()[:2]
    return _LANG_NAMES.get(code, 'English')


# ---------------------------------------------------------------------------
# Smart-scan LLM verdict cache (module-level, in-memory)
# ---------------------------------------------------------------------------

# sha256 -> (verdict_dict, expires_at_epoch)
# OrderedDict gives O(1) FIFO eviction via popitem(last=False) — the previous
# `min(..., key=...)` scan was O(n) on every insert past the cap.
_LLM_CACHE: "OrderedDict[str, tuple[dict, float]]" = OrderedDict()
_LLM_CACHE_TTL = 24 * 3600  # 24 hours
_LLM_CACHE_MAX = 2000


def _llm_cache_get(key: str) -> Optional[dict]:
    """Return cached verdict if present and not expired, else None."""
    entry = _LLM_CACHE.get(key)
    if entry is None:
        return None
    verdict, expires_at = entry
    if time.time() > expires_at:
        _LLM_CACHE.pop(key, None)
        return None
    return verdict


def _llm_cache_set(key: str, verdict: dict) -> None:
    """Insert a verdict into the cache, evicting the oldest entry when full.

    Uses ``OrderedDict.popitem(last=False)`` for O(1) FIFO eviction — the
    earliest insert wins eviction. Since TTL is fixed, earliest-insert ==
    earliest-expires, so this matches the prior semantics with better cost.
    """
    # If the key already exists, drop it first so re-insert appends to the tail
    # (otherwise the original insertion order would be preserved and the entry
    # could be evicted soon after a refresh).
    if key in _LLM_CACHE:
        _LLM_CACHE.pop(key, None)
    while len(_LLM_CACHE) >= _LLM_CACHE_MAX:
        _LLM_CACHE.popitem(last=False)
    _LLM_CACHE[key] = (verdict, time.time() + _LLM_CACHE_TTL)


# ---------------------------------------------------------------------------
# Redaction placeholder labels
# ---------------------------------------------------------------------------

# Maps a rule_id to the SHORT, human-readable token used inside a redaction
# placeholder, e.g. rule_id 'email' -> '[EMAIL_1]'. Several distinct API-key
# rules collapse to the same 'API_KEY' label intentionally — the user only
# needs to know "a key was removed here", not which vendor's. Any rule_id not
# listed falls back to the match's uppercased ``category`` (or 'SENSITIVE').
_REDACT_LABELS: dict[str, str] = {
    'email': 'EMAIL',
    'phone_intl': 'PHONE',
    'credit_card': 'CARD',
    'iban': 'IBAN',
    'national_id_iran': 'NID',
    'ipv4_private': 'IP',
    'internal_hostname': 'HOST',
    'jwt_token': 'JWT',
    'aws_access_key': 'AWS_KEY',
    'aws_secret_key': 'AWS_SECRET',
    'anthropic_api_key': 'API_KEY',
    'openai_api_key': 'API_KEY',
    'google_api_key': 'API_KEY',
    'github_pat': 'TOKEN',
    'slack_token': 'TOKEN',
    'stripe_secret': 'API_KEY',
    'private_key_pem': 'PRIVATE_KEY',
    'high_entropy_token': 'SECRET',
    'generic_api_key': 'API_KEY',
    # Smart-scan (llm) matches: use a neutral token rather than leaking the
    # policy class ('restricted'/'confidential') into the chat bubble.
    'ai_smart_scan': 'SENSITIVE',
}


def _redact_label(match: "DLPMatch") -> str:
    """Return the placeholder label for a match.

    Prefers the explicit per-rule label, else the uppercased category, else a
    generic ``SENSITIVE``. Custom-pattern rule_ids (not in the map) naturally
    fall through to their category / the generic fallback.
    """
    label = _REDACT_LABELS.get(match.rule_id)
    if label:
        return label
    return (match.category or 'SENSITIVE').upper()


# ---------------------------------------------------------------------------
# DLP Detector
# ---------------------------------------------------------------------------

class DLPDetector:
    """
    Scans text against the effective workspace DLP policy.

    The caller is responsible for resolving the workspace policy via
    effective_policy() and passing the result to __init__.
    """

    def __init__(self, policy: dict, *, workspace_id: Optional[str] = None) -> None:
        self._policy = policy
        self._workspace_id: Optional[str] = workspace_id
        self.enabled: bool = bool(policy.get("enabled", False))
        # Redact mode replaces sensitive spans with typed placeholders instead
        # of blocking/confirming. Independent of ``enabled`` semantics: a
        # disabled policy never scans, so redaction only fires when enabled too.
        self.redaction_enabled: bool = (policy.get("mode") == "redact")
        self._sensitivity: str = policy.get("sensitivity", "balanced")
        self._min_severity_rank: int = _SENSITIVITY_MIN_RANK.get(
            self._sensitivity, SEVERITY_RANK["medium"]
        )
        self._rule_overrides: dict[str, str] = policy.get("rule_overrides", {}) or {}
        # Owner-disabled rules — skipped entirely at scan time (simple on/off).
        self._disabled_rules: set[str] = set(policy.get("disabled_rules") or [])
        self._custom_patterns: list[dict] = policy.get("custom_patterns", []) or []
        self._hostname_suffixes: list[str] = policy.get(
            "internal_hostname_suffixes", []
        ) or []

        # Compiled custom pattern cache: {regex_str: compiled | None (bad regex)}
        self._custom_compiled: dict[str, Optional[re.Pattern]] = {}

    # ------------------------------------------------------------------
    # Class method factory
    # ------------------------------------------------------------------

    @classmethod
    def from_workspace(cls, workspace_id: str) -> "DLPDetector":
        """
        Load workspace from DB and return a configured DLPDetector.
        If the ID is malformed, workspace not found, or DLP not enabled,
        returns a no-op detector. Malformed IDs log a warning — callers
        upstream should validate before reaching here, but we never crash.
        """
        from app.models.workspace import WorkspaceModel
        from app.utils.helpers import validate_object_id

        if not workspace_id or not validate_object_id(workspace_id):
            logger.warning(
                "DLPDetector.from_workspace: invalid workspace_id %r — returning disabled detector",
                workspace_id,
            )
            return cls({"enabled": False}, workspace_id=workspace_id)

        workspace = WorkspaceModel.find_by_id(workspace_id)
        if workspace is None:
            logger.warning("DLPDetector.from_workspace: workspace %s not found", workspace_id)
            return cls({"enabled": False}, workspace_id=workspace_id)

        raw_dlp = (workspace.get("settings") or {}).get("dlp")
        policy = effective_policy(raw_dlp)
        return cls(policy, workspace_id=workspace_id)

    # ------------------------------------------------------------------
    # Snippet helper
    # ------------------------------------------------------------------

    @staticmethod
    def _make_snippet(text: str, start: int, end: int) -> str:
        """
        Return ±20 chars around the match with the match itself masked by '*'.
        Newlines in the surrounding context are replaced by space to keep
        the snippet single-line.
        """
        match_len = end - start
        masked_match = '*' * match_len

        before = text[max(0, start - 20):start].replace('\n', ' ')
        after = text[end:end + 20].replace('\n', ' ')

        return before + masked_match + after

    @staticmethod
    def _find_occurrences(text: str, span: str) -> list[tuple[int, int]]:
        """All non-overlapping occurrences of ``span`` in ``text``.

        Used to map a smart-scan-returned sensitive substring back to concrete
        offsets so it can be spliced like a regex match. Tries exact, then
        case-insensitive, then a whitespace-tolerant pass (the model often
        normalizes spacing/newlines). Returns ``[]`` when the substring can't be
        located — the caller then leaves that remainder un-spliced (advisory).
        """
        s = (span or '').strip()
        if not s:
            return []

        def _scan(haystack: str, needle: str) -> list[tuple[int, int]]:
            out: list[tuple[int, int]] = []
            start = 0
            while True:
                i = haystack.find(needle, start)
                if i == -1:
                    break
                out.append((i, i + len(needle)))
                start = i + len(needle)
            return out

        exact = _scan(text, s)
        if exact:
            return exact
        ci = _scan(text.lower(), s.lower())
        if ci:
            return ci

        # Whitespace-tolerant pass: treat every run of whitespace in the span as
        # \s+ in the text, so minor spacing/newline drift from the model still
        # locates the value. Matching on the original text keeps offsets exact.
        tokens = [re.escape(tok) for tok in s.split()]
        if len(tokens) < 2:
            return []
        try:
            pat = re.compile(r'\s+'.join(tokens), re.IGNORECASE)
        except re.error:
            return []
        return [(m.start(), m.end()) for m in pat.finditer(text)]

    # ------------------------------------------------------------------
    # Overlap deduplication
    # ------------------------------------------------------------------

    @staticmethod
    def _dedup_overlapping(matches: list[DLPMatch]) -> list[DLPMatch]:
        """
        When two matches overlap in the text, keep the one with the highest
        severity (ties broken by earlier offset_start).

        Implementation: each candidate is compared against the current ``kept``
        list. When an overlap is found, we decide which match wins and rebuild
        ``kept`` as a fresh list instead of mutating it during a loop. The
        previous version relied on ``break`` immediately after ``kept.remove``
        — safe, but fragile to anyone editing the loop body.
        """
        if not matches:
            return matches

        # Sort by start offset, then by severity desc
        sorted_matches = sorted(
            matches,
            key=lambda m: (m.offset_start, -SEVERITY_RANK.get(m.severity, 0))
        )

        kept: list[DLPMatch] = []
        for candidate in sorted_matches:
            cand_rank = SEVERITY_RANK.get(candidate.severity, 0)
            new_kept: list[DLPMatch] = []
            placed = False
            overlapped = False

            for kept_match in kept:
                overlap = (
                    candidate.offset_start < kept_match.offset_end
                    and candidate.offset_end > kept_match.offset_start
                )
                if overlap:
                    overlapped = True
                    kept_rank = SEVERITY_RANK.get(kept_match.severity, 0)
                    if cand_rank > kept_rank:
                        # Drop the existing match; the candidate will land in
                        # ``new_kept`` after we finish scanning.
                        continue
                    # Existing match wins — keep it, candidate is shadowed.
                    new_kept.append(kept_match)
                    placed = True
                else:
                    new_kept.append(kept_match)

            if not overlapped:
                new_kept.append(candidate)
            elif not placed:
                # Candidate overlapped one or more entries and outranked every
                # one of them (those were dropped above) — add it now.
                new_kept.append(candidate)

            kept = new_kept

        return kept

    # ------------------------------------------------------------------
    # Core scan
    # ------------------------------------------------------------------

    def scan(
        self,
        text: str,
        user_lang: str = 'en',
        *,
        user_id: Any = None,
        skip_llm: bool = False,
    ) -> DLPScanResult:
        """
        Scan text against all active rules. Returns a DLPScanResult.
        Does not persist events — caller is responsible for that.

        Args:
            text: The user-supplied text to scan.
            user_lang: 'en' or 'fa' — controls the language of LLM-generated
                Smart-scan reasons. Forwarded to ``llm_classify``.
            user_id: The user whose request triggered the scan, propagated to
                the smart-scan LLM call so ``usage_logs`` rows attribute the
                cost to the right user (workspace is already on the detector).
            skip_llm: When True, run regex/hostname/custom path only and skip
                ``llm_classify``.
        """
        result = DLPScanResult()

        if not text:
            return result

        result.text_length = len(text)
        result.text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

        if not self.enabled:
            return result

        all_matches: list[DLPMatch] = []

        # --- Builtin rules ---
        for rule in BUILTIN_RULES:
            rule_id: str = rule["id"]
            severity: str = rule["severity"]

            # Owner switched this rule off entirely
            if rule_id in self._disabled_rules:
                continue

            # Sensitivity filter
            if SEVERITY_RANK.get(severity, 0) < self._min_severity_rank:
                continue

            # Override to allow → skip entirely
            override_action = self._rule_overrides.get(rule_id)
            if override_action == "allow":
                continue

            # Determine effective action. require_confirm is not live.
            action = collapse_action(
                override_action if override_action else rule["default_action"]
            )

            pattern: re.Pattern = rule["regex"]
            validator: Optional[Callable[[str], bool]] = rule.get("validate")

            # Cheap pre-filter: rules like credit-card and Iran-ID run an
            # O(n) validator on every match, so on text with no digit clusters
            # we can skip the heavy regex+validator pass entirely.
            pre_filter: Optional[re.Pattern] = rule.get("pre_filter")
            if pre_filter is not None and not pre_filter.search(text):
                continue

            for m in pattern.finditer(text):
                matched_text = m.group(0)

                # Optional length filter
                min_len = rule.get("min_len", 0)
                if len(matched_text) < min_len:
                    continue

                # Optional validator (Luhn, IBAN mod-97, etc.)
                if validator is not None and not validator(matched_text):
                    continue

                snippet = self._make_snippet(text, m.start(), m.end())
                all_matches.append(DLPMatch(
                    rule_id=rule_id,
                    rule_name=rule["name"],
                    severity=severity,
                    action=action,
                    snippet=snippet,
                    offset_start=m.start(),
                    offset_end=m.end(),
                    category=rule.get("category"),
                    description=rule.get("description"),
                    source='builtin',
                ))

        # --- Custom patterns from policy ---
        # ReDoS containment: owner-authored regex runs on at most the first
        # ``_CUSTOM_REGEX_MAX_CHARS`` of the message so a catastrophic-backtracking
        # pattern can't peg a worker thread over the full (up to 400k-char) text.
        # Offsets/snippets are computed against this SAME slice, so they stay
        # internally consistent; matches beyond the cap are simply not detected on
        # the custom pass (builtins still scan full text). 0 disables the cap.
        custom_scan_text = (
            text[:_CUSTOM_REGEX_MAX_CHARS]
            if _CUSTOM_REGEX_MAX_CHARS and len(text) > _CUSTOM_REGEX_MAX_CHARS
            else text
        )
        for custom in self._custom_patterns:
            regex_str = custom.get("regex", "")
            if not regex_str:
                continue

            if regex_str not in self._custom_compiled:
                try:
                    self._custom_compiled[regex_str] = re.compile(regex_str)
                except re.error as exc:
                    logger.warning(
                        "DLPDetector: invalid custom regex %r skipped: %s",
                        regex_str, exc
                    )
                    self._custom_compiled[regex_str] = None

            compiled = self._custom_compiled.get(regex_str)
            if compiled is None:
                continue

            custom_severity = custom.get("severity", "medium")
            custom_action = collapse_action(custom.get("action", "warn"))
            custom_name = custom.get("name", f"Custom: {regex_str[:30]}")
            custom_id = custom.get("id", f"custom:{regex_str[:20]}")

            # Sensitivity filter for custom rules too
            if SEVERITY_RANK.get(custom_severity, 0) < self._min_severity_rank:
                continue

            for m in compiled.finditer(custom_scan_text):
                snippet = self._make_snippet(custom_scan_text, m.start(), m.end())
                all_matches.append(DLPMatch(
                    rule_id=custom_id,
                    rule_name=custom_name,
                    severity=custom_severity,
                    action=custom_action,
                    snippet=snippet,
                    offset_start=m.start(),
                    offset_end=m.end(),
                    source='custom',
                ))

        # --- Dynamic internal_hostname rule ---
        if self._hostname_suffixes and "internal_hostname" not in self._disabled_rules:
            # Escape suffixes and build alternation
            escaped = [re.escape(suffix) for suffix in self._hostname_suffixes]
            hostname_pattern = re.compile(
                r'\b[\w.-]+(?:' + '|'.join(escaped) + r')\b',
                re.IGNORECASE,
            )
            for m in hostname_pattern.finditer(text):
                # Sensitivity: medium
                if SEVERITY_RANK["medium"] < self._min_severity_rank:
                    continue
                override_action = self._rule_overrides.get("internal_hostname")
                if override_action == "allow":
                    continue
                action = collapse_action(override_action if override_action else "warn")
                snippet = self._make_snippet(text, m.start(), m.end())
                all_matches.append(DLPMatch(
                    rule_id="internal_hostname",
                    rule_name="Internal Hostname",
                    severity="medium",
                    action=action,
                    snippet=snippet,
                    offset_start=m.start(),
                    offset_end=m.end(),
                    category='network',
                    description='Internal company hostname',
                    source='hostname',
                ))

        # --- Dedup overlapping matches ---
        deduplicated = self._dedup_overlapping(all_matches)

        result.matches = deduplicated

        # --- Compute highest_action ---
        if deduplicated:
            highest_rank = max(
                ACTION_RANK.get(m.action, 0) for m in deduplicated
            )
            for action_str, rank in ACTION_RANK.items():
                if rank == highest_rank:
                    result.highest_action = collapse_action(action_str)
                    break

        # --- Smart scan augmentation (LLM second pass) ---
        # Short-circuits (no llm_classify):
        #   * skip_llm=True — regex/custom/hostname only
        #   * highest_action == 'block' — non-overridable max; LLM only adds
        #     latency (cannot escalate past block, cannot override it)
        # Otherwise, when enabled, always run. We used to SKIP the entire LLM
        # call whenever any high/critical regex match existed (privacy: don't
        # ship secrets to OpenRouter). That also skipped workspace *guidance*
        # on real HR/finance uploads where phone/national_id/EMP-id regex flood
        # dominates — smart scan never ran. Fix:
        #   * local Ollama (DLP_LLM_BASE_URL) → classify full text (on-prem)
        #   * remote OpenRouter + high-severity regex hits → mask those spans
        #     first, then classify (guidance still sees the rest)
        #   * no high-severity hits → classify full text either way
        if skip_llm or result.highest_action == 'block':
            return result

        has_high_severity = any(
            SEVERITY_RANK.get(m.severity, 0) >= SEVERITY_RANK['high']
            for m in result.matches
        )
        local_base = (settings.get('DLP_LLM_BASE_URL') or '').strip()
        llm_text = text
        if has_high_severity and not local_base:
            llm_text = self._mask_high_severity_spans(text, result.matches)

        verdict = self.llm_classify(llm_text, user_lang=user_lang, user_id=user_id)
        if verdict is not None and verdict.get('category') != 'public':
            thresholds = (self._policy.get('llm_classifier') or {}).get(
                'action_thresholds') or {}
            category = verdict['category']
            default_action = 'warn' if category == 'confidential' else 'block'
            llm_action = collapse_action(thresholds.get(category, default_action))
            severity = 'medium' if category == 'confidential' else 'high'
            reason = verdict.get('reason', '')

            def _make_llm_match(start: int, end: int) -> DLPMatch:
                return DLPMatch(
                    rule_id='ai_smart_scan',
                    rule_name='Smart scan',
                    severity=severity,
                    action=llm_action,
                    snippet=self._make_snippet(text, start, end) if end > start else '',
                    offset_start=start,
                    offset_end=end,
                    category=category,
                    description=reason,
                    source='llm',
                )

            # Locate each LLM-returned sensitive substring so it can be
            # spliced like a regex match. Skip occurrences already covered by
            # a regex match (it will redact them) and overlapping duplicates.
            # Spans are resolved against the ORIGINAL text (not the masked
            # remote-LLM input) so redaction offsets stay valid.
            existing_spans = [
                (m.offset_start, m.offset_end)
                for m in result.matches
                if m.offset_end > m.offset_start
            ]
            spans = verdict.get('spans') or []
            # No spans at all -> the flagged content can't be auto-scrubbed.
            has_unredactable = not spans
            for span in spans:
                occ = self._find_occurrences(text, span)
                if not occ:
                    # Model couldn't return this value verbatim -> can't splice.
                    has_unredactable = True
                    continue
                for s, e in occ:
                    if any(s < ee and e > ss for ss, ee in existing_spans):
                        continue  # already covered by a regex match
                    result.matches.append(_make_llm_match(s, e))
                    existing_spans.append((s, e))

            # When something the LLM flagged could not be located/spliced,
            # emit a spanless marker so enforce mode still warns or blocks
            # instead of silently sending the un-scrubbed content.
            if has_unredactable:
                result.matches.append(_make_llm_match(0, 0))

            # Raise highest_action only — never lower.
            current_rank = ACTION_RANK.get(result.highest_action, 0)
            llm_rank = ACTION_RANK.get(llm_action, 0)
            if llm_rank > current_rank:
                for action_str, rank in ACTION_RANK.items():
                    if rank == llm_rank:
                        result.highest_action = collapse_action(action_str)
                        break

        return result

    @staticmethod
    def _clip_for_llm(text: str, max_chars: int) -> str:
        """Bound LLM input; keep head + tail so long sheets don't lose endings."""
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        if max_chars < 80:
            return text[:max_chars]
        marker = "\n\n[...truncated middle...]\n\n"
        budget = max_chars - len(marker)
        head = int(budget * 0.75)
        tail = budget - head
        if tail < 1:
            return text[:max_chars]
        return text[:head] + marker + text[-tail:]

    @staticmethod
    def _mask_high_severity_spans(text: str, matches: list) -> str:
        """Replace high/critical regex spans with fixed placeholders for remote LLM.

        Keeps length roughly stable so the model still sees structure (tables,
        headers) without receiving raw secrets on the OpenRouter path.
        """
        if not text or not matches:
            return text
        spans = sorted(
            (
                (m.offset_start, m.offset_end)
                for m in matches
                if m.offset_end > m.offset_start
                and SEVERITY_RANK.get(m.severity, 0) >= SEVERITY_RANK['high']
            ),
            key=lambda se: se[0],
        )
        if not spans:
            return text
        # Merge overlaps
        merged: list[tuple[int, int]] = []
        for s, e in spans:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        out: list[str] = []
        cursor = 0
        for s, e in merged:
            if s > cursor:
                out.append(text[cursor:s])
            out.append('[REDACTED]')
            cursor = e
        if cursor < len(text):
            out.append(text[cursor:])
        return ''.join(out)

    # ------------------------------------------------------------------
    # Deterministic redaction
    # ------------------------------------------------------------------

    def redact(
        self,
        text: str,
        user_lang: str = 'en',
        *,
        user_id: Any = None,
    ) -> tuple[str, list[dict], DLPScanResult]:
        """Scan ``text`` and splice every span-bearing match out, replacing it
        with a typed placeholder (e.g. ``[EMAIL_1]``).

        Deterministic: uses the offsets the scanner already recorded
        (``offset_start``/``offset_end``) — NO LLM rewrite. Smart-scan matches
        (``source == 'llm'``) ARE spliced too when the classifier returned a
        locatable verbatim span (real offsets); spanless smart-scan markers
        (0,0 — the model couldn't pinpoint the value) are skipped here and the
        gate falls back to a confirm.

        Consistency: the SAME raw value (normalized via ``strip().lower()``)
        always maps to the SAME placeholder within one call, so repeated PII
        keeps a stable token across the message.

        Returns ``(redacted_text, redactions, result)`` where ``redactions`` is
        a list of ``{'placeholder','label','severity','rule_id'}`` dicts. Raw
        sensitive values are NEVER included.
        """
        result = self.scan(text, user_lang=user_lang, user_id=user_id)

        # Only matches with a real, non-empty span are redactable. This now
        # includes smart-scan (llm) matches whose returned substring was located
        # in the text (real offsets); spanless llm markers (0,0) are skipped.
        redactable = [
            m for m in result.matches
            if m.offset_end > m.offset_start
        ]

        if not redactable:
            return text, [], result

        # Maps a normalized raw value -> already-assigned placeholder, so the
        # same value reuses one token. Per-label counter drives the suffix.
        value_to_placeholder: dict[str, str] = {}
        label_counters: dict[str, int] = {}
        # placeholder -> redaction descriptor (deduped; one entry per token).
        redactions_by_placeholder: dict[str, dict] = {}

        # Splice from the end backwards so earlier offsets stay valid.
        redacted_text = text
        for m in sorted(redactable, key=lambda x: x.offset_start, reverse=True):
            raw = text[m.offset_start:m.offset_end]
            norm = raw.strip().lower()
            label = _redact_label(m)

            placeholder = value_to_placeholder.get(norm)
            if placeholder is None:
                label_counters[label] = label_counters.get(label, 0) + 1
                placeholder = f"[{label}_{label_counters[label]}]"
                value_to_placeholder[norm] = placeholder
                redactions_by_placeholder[placeholder] = {
                    'placeholder': placeholder,
                    'label': label,
                    'severity': m.severity,
                    'rule_id': m.rule_id,
                }

            redacted_text = (
                redacted_text[:m.offset_start]
                + placeholder
                + redacted_text[m.offset_end:]
            )

        # Order placeholders by their numeric assignment for a stable result.
        redactions = list(redactions_by_placeholder.values())
        return redacted_text, redactions, result

    # ------------------------------------------------------------------
    # LLM classifier stub
    # ------------------------------------------------------------------

    def llm_classify(
        self,
        text: str,
        user_lang: str = 'en',
        *,
        user_id: Any = None,
    ) -> Optional[dict]:
        """
        Smart-scan LLM second-pass classifier.

        Returns ``{"category": "public" | "confidential" | "restricted",
        "reason": str}`` on success, or ``None`` when disabled, skipped
        (text blank), the LLM call fails, the response is malformed,
        or the category is unrecognized. Never raises to the caller —
        Smart scan is fail-open.

        Args:
            text: The user-supplied text. Truncated to 2000 chars before
                being sent upstream to bound cost.
            user_lang: ``'en'`` or ``'fa'`` — instructs the model to phrase
                ``reason`` in the user's UI language.
            user_id: Propagated to ``OpenRouterService._sync_completion`` so
                ``usage_logs`` rows attribute smart-scan cost to the right
                user. Workspace is taken from the detector instance.
        """
        lc = self._policy.get('llm_classifier') or {}
        if not lc.get('enabled', False):
            return None
        stripped = text.strip()
        if not stripped:
            return None
        # Cost gate: skip the LLM call for very short messages that can't
        # plausibly carry a flagged value (greetings, "ok thanks", "اوکی مرسی").
        if len(stripped) < _SMARTSCAN_MIN_CHARS:
            return None

        guidance = (lc.get('guidance_prompt') or '').strip()
        model = dlp_locked_model()

        # Cache key includes model + lang + guidance + text so any change
        # invalidates prior verdicts.
        cache_key = hashlib.sha256(
            f"{model}|{user_lang}|{guidance}|{text}".encode('utf-8')
        ).hexdigest()
        cached = _llm_cache_get(cache_key)
        if cached is not None:
            return cached

        # Resolve UI language to a full English name the model can ground its
        # response language on. `user_lang` arrives as a 2-char prefix from the
        # chokepoints (chat_stream/arena_stream/workflow), e.g. 'en', 'pe',
        # 'ge'. Fall back to English when unknown.
        lang_name = _resolve_lang_name(user_lang)
        # Workspace guidance is appended as an AUTHORITATIVE policy section.
        # Historical bug: the base text forced "public whenever spans are empty",
        # which made custom guidance fail for semantic / business-sensitive text
        # (customer names, deal terms, internal project phrases) when the model
        # hesitated to quote a span. Spans remain preferred for redaction; empty
        # spans still allow a non-public category so enforce-mode can confirm.
        base_prompt = (
            "You are a content-safety classifier. A user's message is about to be sent to an AI assistant. "
            "Decide whether the message contains sensitive information that should not leave the company.\n"
            "\n"
            "Sensitivity comes from TWO sources (either is enough to flag):\n"
            "1) BASE TYPES — sensitive VALUES literally present in the text: API keys, passwords, private keys, "
            "tokens, financial account/card numbers, personal contact info (email, phone), employee names, "
            "internal hostnames, customer names / account identifiers, salaries/comp figures tied to a person, "
            "contract/deal terms with concrete numbers or counterparty names, unreleased product or codename strings.\n"
            "2) WORKSPACE POLICY — the WORKSPACE POLICY section below (when present) EXTENDS and can OVERRIDE "
            "what THIS company treats as sensitive (named projects, client aliases, deal codes, department topics, "
            "forbidden phrases). If the policy names an entity/phrase and that string (or a clear instance) appears "
            "in the message, treat it as sensitive even if it is not a classic credential.\n"
            "\n"
            "Presence vs topic:\n"
            "- Flag when a sensitive VALUE, name, number, or policy-listed phrase is present in the text.\n"
            "- Do NOT flag generic questions that only discuss a TYPE of secret without any concrete value "
            "(e.g. \"how do I rotate API keys?\" or \"what was the project name?\" with no name given → public).\n"
            "- Semantic business content counts: e.g. \"Acme Corp's Q3 revenue was $4.2M\" or "
            "\"offer Sara 45M IRR base\" is sensitive even though it is not an API key.\n"
            "\n"
            "Category:\n"
            "- public: nothing sensitive by base types or workspace policy.\n"
            "- confidential: contact PII, employee names, internal hostnames, or policy-marked confidential content.\n"
            "- restricted: credentials/secrets, financial account data, customer/account identifiers, "
            "concrete commercial terms, codenames/product names, or policy-marked restricted content.\n"
            "\n"
            "Then write a SHORT, SPECIFIC, USER-FRIENDLY reason (≤30 words) that:\n"
            "- names the TYPE of sensitive data (e.g. \"customer name\", \"salary figure\", \"API key\", \"project codename\"),\n"
            "- explains briefly why sharing it is risky,\n"
            "- uses a calm, second-person tone (\"Your message contains…\"),\n"
            "- never quotes the actual sensitive value verbatim,\n"
            "- never mentions \"AI classifier\", \"flagged\", \"the model\", or other meta language.\n"
            "\n"
            f"Write the reason in {lang_name}.\n"
            "\n"
            "Spans (for automatic redaction):\n"
            "- \"spans\" is a JSON array of EXACT sensitive substrings copied character-for-character from the message "
            "(same case, spacing, punctuation). Prefer listing every concrete value/name/number/phrase you flagged.\n"
            "- For non-public verdicts, include at least one span whenever a concrete phrase is present.\n"
            "- If workspace policy or semantic context makes the message sensitive but you cannot quote a clean "
            "substring, STILL return the correct non-public category with \"spans\": [] — do NOT downgrade to public "
            "just because spans are empty.\n"
            "- Only \"spans\" may contain raw values; the \"reason\" must not.\n"
            "\n"
            'Output ONLY a single JSON object: {"category": "...", "reason": "...", "spans": ["...", "..."]}. '
            "No markdown, no prose, no code fences — JSON only."
        )
        if guidance:
            system = (
                f"{base_prompt}\n\n"
                "=== WORKSPACE POLICY (authoritative for this company) ===\n"
                f"{guidance}\n"
                "=== END WORKSPACE POLICY ===\n"
                "Apply the workspace policy in addition to base types. "
                "When they disagree on WHETHER something is sensitive, prefer the workspace policy. "
                "When a policy-listed name or phrase appears in the message, put that exact substring in spans."
            )
        else:
            system = (
                f"{base_prompt}\n\n"
                "=== WORKSPACE POLICY (default) ===\n"
                "Treat as restricted: API keys, passwords, private keys, tokens, customer names, "
                "account identifiers, internal codenames, unreleased product names, financial account numbers, "
                "concrete salaries/comp, and named commercial deal terms.\n"
                "Treat as confidential: emails, phone numbers, internal hostnames, employee names.\n"
                "Everything else is public.\n"
                "=== END WORKSPACE POLICY ==="
            )

        max_input_chars = int(settings.get('DLP_LLM_MAX_INPUT_CHARS') or 8000)
        messages = [
            {'role': 'system', 'content': system},
            # Prefer head+tail on long attachments so spreadsheet headers AND
            # late rows both reach the model (naive prefix-only clip missed
            # guidance hits buried past the char budget).
            {'role': 'user', 'content': self._clip_for_llm(text, max_input_chars)},
        ]

        local_base = (settings.get('DLP_LLM_BASE_URL') or '').strip()
        if local_base:
            # Privacy path: classify on the self-hosted Ollama server. Isolated
            # client bypasses the egress proxy and records no usage. Fail-open.
            from app.services import local_llm_service

            # TLS verify: a pinned CA bundle (PEM path) wins — verification stays
            # ON against the self-signed Ollama cert. Else fall back to the bool
            # (default False = no verify; logged as insecure by the client).
            ca_bundle = (settings.get('DLP_LLM_CA_BUNDLE') or '').strip()
            verify_arg = ca_bundle if ca_bundle else bool(settings.get('DLP_LLM_VERIFY_SSL'))

            content = local_llm_service.dlp_classify_content(
                messages,
                base_url=local_base,
                model=model,
                timeout=int(settings.get('DLP_LLM_TIMEOUT') or 8),
                verify=verify_arg,
                num_ctx=int(settings.get('DLP_LLM_NUM_CTX') or 8192),
            )
            if content is None:
                return None
        else:
            # OpenRouter path (default). `reasoning` + `response_format` are
            # OpenRouter-specific knobs the local /api/chat client doesn't take.
            payload = {
                'model': model,
                'messages': messages,
                'temperature': 0.1,
                'max_tokens': 700,
                'reasoning': {'effort': 'minimal'},
                'response_format': {'type': 'json_object'},
            }

            # Lazy import — avoids any chance of circular import at module load.
            from app.services.openrouter_service import OpenRouterService

            try:
                resp = OpenRouterService._sync_completion(
                    payload,
                    user_id=str(user_id) if user_id is not None else None,
                    conversation_id=None,
                    feature='content_safety',
                    workspace_id=self._workspace_id,
                    project_id=None,
                    origin='dlp',
                    timeout=10,
                )
            except Exception as exc:
                logger.error(
                    "DLP smart-scan failed: %s — failing open",
                    exc,
                    exc_info=True,
                )
                return None

            if not isinstance(resp, dict) or 'error' in resp:
                err = resp.get('error') if isinstance(resp, dict) else resp
                logger.error("Smart scan LLM error: %s", err)
                return None

            try:
                content = resp['choices'][0]['message']['content']
            except (KeyError, IndexError, TypeError) as exc:
                logger.error("Smart scan response shape error: %s", exc)
                return None

        # Unified parse (both backends). `content` is a JSON string.
        try:
            stripped = content.strip()
            # Defensive: a thinking model may still emit a <think>…</think>
            # wrapper despite think:false + the schema. Strip it before parsing.
            if '<think>' in stripped:
                stripped = re.sub(r'<think>.*?</think>', '', stripped, flags=re.DOTALL).strip()
            if stripped.startswith('```'):
                stripped = stripped.split('\n', 1)[1] if '\n' in stripped else stripped
                if stripped.endswith('```'):
                    stripped = stripped[:-3].rstrip()
            parsed = json.loads(stripped)
            category = parsed.get('category')
            if category not in ('public', 'confidential', 'restricted'):
                logger.warning("Smart scan invalid category: %r", category)
                return None
            spans_raw = parsed.get('spans')
            spans: list[str] = []
            if isinstance(spans_raw, list):
                for sp in spans_raw:
                    if isinstance(sp, str) and sp.strip():
                        spans.append(sp[:500])
                    if len(spans) >= 30:
                        break
            verdict = {
                'category': category,
                'reason': str(parsed.get('reason', ''))[:400],
                'spans': spans,
            }
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, AttributeError) as exc:
            logger.error("Smart scan parse error: %s", exc)
            return None

        _llm_cache_set(cache_key, verdict)
        return verdict
