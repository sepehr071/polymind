"""DLP routes, translated from app/routes/dlp.py.

The Flask ``dlp_bp`` mounts at url_prefix ``/api`` with route paths
``/dlp/*``, ``/workspaces/<wid>/dlp/*`` and ``/admin/dlp/*``. The FastAPI
``router`` mirrors that exactly (mounted at prefix ``/api`` by the wiring step),
so every path string here is identical to the Flask one (``<wid>`` -> ``{wid}``).

The in-process deque rate-limiter is 60 calls / 60s rolling window, per worker.

DLPBlockedError is handled globally (``app/api/errors.py``); none of these
routes raise it directly (only the chokepoint streams do). ``/dlp/scan`` does
not mint a confirm token. ``require_confirm`` is coerced to ``block``.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from collections import deque
from datetime import datetime
from functools import partial
from typing import Any, Optional

import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import (
    flask_ctx,
    require_active,
    require_admin,
    workspace_member_dep,
)
from app.models.dlp_event import DLPEventModel, VALID_STATUSES
from app.models.user import UserModel
from app.models.workspace import WorkspaceModel
from app.services.dlp_rules import BUILTIN_RULES
from app.services.dlp_service import (
    DLPDetector,
    collapse_action,
    dlp_locked_model,
    effective_policy,
)
from app.services.openrouter_service import OpenRouterService
from app.services import spend_gate
from app.utils.helpers import serialize_doc, validate_object_id
from app.utils.permissions import check_workspace_access

logger = logging.getLogger(__name__)

# Router-level dependency: every request runs inside the Flask app_context so
# all model facades / services are reused VERBATIM.
router = APIRouter(dependencies=[Depends(flask_ctx)])


async def _json_body(request: Request) -> dict:
    """Read the request JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _attach_user_identity(rows: list[dict]) -> None:
    """Enrich DLP event rows in place with ``user_email`` + ``user_name``.

    ``user_id`` is already stringified by the model facade. Batch-fetches the
    referenced users once (same idiom as the usage / audit-log endpoints) and
    attaches the email + display name; both default to ``None`` for events with
    no/unknown user.
    """
    uid_strs = [ev['user_id'] for ev in rows if ev.get('user_id')]
    user_map: dict = {}
    if uid_strs:
        for u in UserModel.find_by_ids(uid_strs):
            user_map[str(u['_id'])] = {
                'email': u.get('email'),
                'display_name': (u.get('profile') or {}).get('display_name'),
            }
    for ev in rows:
        profile = user_map.get(ev.get('user_id') or '')
        ev['user_email'] = (profile or {}).get('email')
        ev['user_name'] = (profile or {}).get('display_name')


# ---------------------------------------------------------------------------
# Per-user rate limiter for /dlp/scan
# 60 calls per 60-second rolling window, in-memory PER GUNICORN WORKER.
# Ported VERBATIM from app/routes/dlp.py (module-level dict[str, deque]).
# ---------------------------------------------------------------------------

_RATE_LIMIT_WINDOW = 60        # seconds
_RATE_LIMIT_MAX = 60           # max calls per window
_scan_rate: dict[str, deque] = {}  # user_id -> deque of timestamps

# Inactivity sweep — bound the dict size so a long-running worker doesn't grow
# `_scan_rate` linearly with unique-users-ever-seen. Triggered every Nth call
# rather than on a wall-clock timer so we don't need a background thread.
_SWEEP_EVERY_N = 200
_sweep_counter = 0


def _sweep_inactive_buckets(now: float) -> None:
    """Drop user buckets whose deque is empty or whose newest entry is older
    than 2 * window. Cheap O(n) scan; n is bounded by active-users / worker.
    """
    cutoff = now - (2 * _RATE_LIMIT_WINDOW)
    stale = [
        uid for uid, dq in _scan_rate.items()
        if not dq or dq[-1] < cutoff
    ]
    for uid in stale:
        _scan_rate.pop(uid, None)


def _check_rate_limit(user_id: str) -> Optional[int]:
    """Return retry_after seconds if rate-limited, else None.

    Uses ``time.monotonic()`` rather than wall-clock so NTP slew / DST jumps
    can't reset or stretch the rolling window. Only deltas matter here, never
    absolute epoch values.
    """
    global _sweep_counter
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW

    _sweep_counter += 1
    if _sweep_counter >= _SWEEP_EVERY_N:
        _sweep_counter = 0
        _sweep_inactive_buckets(now)

    dq = _scan_rate.setdefault(user_id, deque())
    # Drop entries outside the window
    while dq and dq[0] < window_start:
        dq.popleft()

    if len(dq) >= _RATE_LIMIT_MAX:
        oldest = dq[0]
        retry_after = int(_RATE_LIMIT_WINDOW - (now - oldest)) + 1
        return retry_after

    dq.append(now)
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rule_catalog() -> list[dict]:
    """Return the static rule catalog in API-safe shape (no compiled regex)."""
    return [
        {
            'id': r['id'],
            'name': r['name'],
            'severity': r['severity'],
            'default_action': r['default_action'],
            'category': r['category'],
        }
        for r in BUILTIN_RULES
    ]


_ALLOWED_POLICY_KEYS = {
    'enabled',
    'sensitivity',
    'mode',
    'rule_overrides',
    'disabled_rules',
    'custom_patterns',
    'internal_hostname_suffixes',
    'llm_classifier',
    'notify_owners',
}

_VALID_SEVERITIES = {'low', 'medium', 'high', 'critical'}
_VALID_ACTIONS = {'warn', 'block'}
_VALID_SENSITIVITIES = {'lenient', 'balanced', 'strict'}
_VALID_MODES = {'enforce', 'redact'}

# Action severity ordering — used to enforce per-rule "loosening" floors below.
# require_confirm is coerced to block before this lookup.
_ACTION_ORDER = {'allow': 0, 'warn': 1, 'block': 2}

# Per-severity minimum allowed override action. The override may go HIGHER
# (tighter) than the floor, but never lower (looser). `critical` is strict:
# overriding it is forbidden entirely — any value other than 'block' is rejected.
_SEVERITY_FLOOR_ACTION = {
    'critical': 'block',           # non-overridable (block-or-reject)
    'high': 'block',               # cannot loosen to warn/allow
    'medium': 'warn',              # may tighten, can't loosen below warn
    'low': 'allow',                # any value accepted, including 'allow' (disable)
}


def _builtin_severity_map() -> dict[str, str]:
    """rule_id -> default severity, for builtin rules only."""
    return {r['id']: r['severity'] for r in BUILTIN_RULES}


# ---------------------------------------------------------------------------
# ReDoS guard for owner-authored custom regex (match_type='regex')
# ---------------------------------------------------------------------------
# Custom patterns run on the cross-tenant offloaded DLP threadpool via CPython's
# backtracking SRE engine (no timeout, GIL held through finditer). Catastrophic
# patterns — nested unbounded quantifiers like ``(a+)+$`` or adjacent unbounded
# quantifiers like ``\d+\d+`` — exhibit exponential/polynomial backtracking and
# can stall a worker for seconds-to-minutes on an adversarial input. We reject
# the obvious shapes structurally at save time, then run a hard-budget adversarial
# probe to catch shapes the heuristic misses. The durable fix is a linear-time
# engine (re2 / pyre2); that is a NEW dependency and intentionally OUT OF SCOPE —
# the save-time guard + the scan-time char cap (dlp_service._CUSTOM_REGEX_MAX_CHARS)
# are the layered mitigations.

# A regex token that introduces unbounded repetition: ``+`` / ``*`` / ``{n,}``
# (open-ended). Bounded forms (``{2,5}``, ``?``) are linear and allowed.
_UNBOUNDED_QUANTIFIER_RE = re.compile(r'(?<!\\)[+*]|(?<!\\)\{\d*,\}')

# Adjacent unbounded quantifiers on the SAME (overlapping) atom, e.g. ``a+a+``,
# ``.*.*``, ``\d+\d*`` — polynomial backtracking. Narrowly scoped to an identical
# repeated atom (single char OR a ``\X`` escape) so DISJOINT-class pairs like
# ``\S+\s*`` or ``\w+@`` (linear, common, safe) are NOT falsely rejected. ``atom``
# is back-referenced so only a literal repeat trips it.
_ADJACENT_SAME_ATOM_RE = re.compile(
    r'(?P<atom>\\[a-zA-Z]|\.|[^\\()\[\]{}|+*?])'  # an overlap-prone atom
    r'(?:[+*]|\{\d*,\})[?+]?'                      # unbounded quantifier (+ lazy/poss)
    r'(?P=atom)'                                   # the SAME atom again
    r'(?:[+*]|\{\d*,\})'                           # unbounded quantifier again
)

# Adversarial probe budget. A short trigger string is enough: a catastrophic
# pattern blows up exponentially even on ~40 chars, while a linear pattern
# finishes in microseconds. Kept generous so a slow-but-linear pattern on a busy
# box isn't falsely rejected.
_REDOS_PROBE_BUDGET_S = 0.20
_REDOS_PROBE_LEN = 40


def _strip_escaped_and_classes(pattern: str) -> str:
    """Blank out escaped chars and char-class interiors so the structural scan
    doesn't trip on ``\\+``, ``\\(`` or a ``+`` living inside ``[...]`` (literal
    there). Replaces those spans with spaces to preserve indexing where cheap;
    char-class interiors collapse to a single placeholder.
    """
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == '\\':
            out.append('  ')  # escape + escaped char -> 2 inert chars
            i += 2
            continue
        if ch == '[':
            # Consume to the closing ']' (first ']' may be literal if it's first).
            j = i + 1
            if j < n and pattern[j] == '^':
                j += 1
            if j < n and pattern[j] == ']':
                j += 1
            while j < n and pattern[j] != ']':
                if pattern[j] == '\\':
                    j += 2
                    continue
                j += 1
            out.append('C')  # collapse the class to an inert single char
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def _has_nested_unbounded_quantifier(pattern: str) -> bool:
    """True when an unbounded-quantified group ``(...)`` wraps a body that itself
    contains an unbounded quantifier — the classic exponential ReDoS shape
    (``(a+)+``, ``(\\d+)*``, ``(a|b+)+``). Walks balanced parens on the
    escape/class-stripped pattern and inspects each group that is immediately
    followed by ``+`` / ``*`` / ``{n,}`` (optionally a lazy/possessive marker).
    """
    s = _strip_escaped_and_classes(pattern)
    n = len(s)
    stack: list[int] = []  # indices of '(' open positions
    for i, ch in enumerate(s):
        if ch == '(':
            stack.append(i)
        elif ch == ')' and stack:
            open_idx = stack.pop()
            # What follows the close-paren? Skip a single lazy/possessive marker.
            k = i + 1
            quantified = False
            if k < n and s[k] in '+*':
                quantified = True
            elif k < n and s[k] == '{':
                m = re.match(r'\{\d*,\}', s[k:])
                if m:
                    quantified = True
            if not quantified:
                continue
            body = s[open_idx + 1:i]
            # Strip a leading group-flag token like ``?:`` / ``?i`` / ``?=`` so a
            # non-capturing wrapper doesn't hide the inner quantifier.
            if _UNBOUNDED_QUANTIFIER_RE.search(body):
                return True
    return False


def _redos_probe_exceeds_budget(compiled: "re.Pattern") -> bool:
    """Run the compiled pattern against a few short adversarial strings and time
    it. Returns True if any probe blows the wall-clock budget — a strong signal
    of catastrophic backtracking. Runs in-thread (``re`` can't be interrupted
    cross-thread), so the strings are deliberately SHORT: exponential blowup is
    already visible at ~40 chars while linear patterns finish in microseconds.

    The probes mix a long homogeneous run with a trailing sentinel char. The
    sentinel forces the engine to FAIL the overall match after greedily consuming
    the run, which is exactly what triggers the backtracking explosion in
    ``(a+)+$``-style patterns (a bare ``search`` that matches early never
    backtracks). ``fullmatch`` adds end-anchoring pressure for unanchored shapes.
    """
    probes = (
        'a' * _REDOS_PROBE_LEN + '!',
        '0' * _REDOS_PROBE_LEN + '!',
        ('a ' * (_REDOS_PROBE_LEN // 2)) + '!',
    )
    for probe in probes:
        for matcher in (compiled.search, compiled.fullmatch):
            start = time.perf_counter()
            try:
                matcher(probe)
            except Exception:  # noqa: BLE001 - any engine error -> not a timing signal
                return False
            if time.perf_counter() - start > _REDOS_PROBE_BUDGET_S:
                return True
    return False


def _custom_regex_redos_error(regex_str: str, idx: int) -> Optional[str]:
    """Return a validation error string if ``regex_str`` looks catastrophic
    (nested/adjacent unbounded quantifiers or an empirically slow probe), else
    None. Caller has already confirmed it compiles."""
    if _has_nested_unbounded_quantifier(regex_str):
        return (
            f"custom_patterns[{idx}].regex is rejected: nested unbounded quantifiers "
            "(e.g. \"(a+)+\") can cause catastrophic backtracking. Rewrite without a "
            "repeated group that itself repeats."
        )
    if _ADJACENT_SAME_ATOM_RE.search(regex_str):
        return (
            f"custom_patterns[{idx}].regex is rejected: adjacent unbounded quantifiers "
            "on the same atom (e.g. \"a+a+\" or \".*.*\") can cause catastrophic "
            "backtracking. Use a single quantifier or bounded repetition instead."
        )
    try:
        compiled = re.compile(regex_str)
    except re.error:
        return None  # syntax already reported by the caller
    if _redos_probe_exceeds_budget(compiled):
        return (
            f"custom_patterns[{idx}].regex is rejected: it backtracks excessively on a "
            "short adversarial input and could stall content scanning. Simplify the "
            "pattern (avoid nested/overlapping unbounded quantifiers)."
        )
    return None


def _validate_custom_pattern(pat: Any, idx: int) -> Optional[str]:
    """Return an error string if the pattern is invalid, else None."""
    if not isinstance(pat, dict):
        return f"custom_patterns[{idx}] must be an object"
    name = pat.get('name', '')
    if not name or not str(name).strip():
        return f"custom_patterns[{idx}].name must be a non-empty string"
    match_type = pat.get('match_type', 'regex')
    if match_type not in ('text', 'regex'):
        return f"custom_patterns[{idx}].match_type must be 'text' or 'regex'"
    if match_type == 'text':
        # Plain text — escaped to regex server-side, always valid. No compile.
        if not str(pat.get('text', '')).strip():
            return f"custom_patterns[{idx}].text must be a non-empty string"
    else:
        regex_str = pat.get('regex', '')
        if not regex_str:
            return f"custom_patterns[{idx}].regex must be a non-empty string"
        try:
            re.compile(regex_str)
        except re.error as exc:
            return f"custom_patterns[{idx}].regex is invalid: {exc}"
        # ReDoS guard — reject catastrophic-backtracking patterns at save time so
        # a pathological custom regex can't stall the shared scan threadpool.
        redos_err = _custom_regex_redos_error(str(regex_str), idx)
        if redos_err:
            return redos_err
    severity = pat.get('severity', '')
    if severity not in _VALID_SEVERITIES:
        return f"custom_patterns[{idx}].severity must be one of {sorted(_VALID_SEVERITIES)}"
    action = collapse_action(pat.get('action', ''))
    if action not in _VALID_ACTIONS:
        return f"custom_patterns[{idx}].action must be one of {sorted(_VALID_ACTIONS)}"
    return None


_VALID_CONFIDENTIAL_ACTIONS = {'warn', 'block'}
_VALID_RESTRICTED_ACTIONS = {'warn', 'block'}


def _validate_llm_classifier(lc: Any) -> tuple[Optional[dict], Optional[str]]:
    if not isinstance(lc, dict):
        return None, "llm_classifier must be an object"
    clean: dict = {}
    if 'enabled' in lc:
        clean['enabled'] = bool(lc['enabled'])
    # Model is locked to the active backend — silently ignore client-supplied value
    clean['model'] = dlp_locked_model()
    if 'guidance_prompt' in lc:
        gp = str(lc['guidance_prompt'] or '')
        if len(gp) > 4000:
            return None, "llm_classifier.guidance_prompt must be 4000 characters or less"
        clean['guidance_prompt'] = gp
    if 'action_thresholds' in lc:
        at = lc['action_thresholds']
        if not isinstance(at, dict):
            return None, "llm_classifier.action_thresholds must be an object"
        clean_at: dict = {}
        if 'confidential' in at:
            v = collapse_action(at['confidential'])
            if v not in _VALID_CONFIDENTIAL_ACTIONS:
                return None, f"llm_classifier.action_thresholds.confidential must be one of {sorted(_VALID_CONFIDENTIAL_ACTIONS)}"
            clean_at['confidential'] = v
        if 'restricted' in at:
            v = collapse_action(at['restricted'])
            if v not in _VALID_RESTRICTED_ACTIONS:
                return None, f"llm_classifier.action_thresholds.restricted must be one of {sorted(_VALID_RESTRICTED_ACTIONS)}"
            clean_at['restricted'] = v
        clean['action_thresholds'] = clean_at
    return clean, None


def _build_policy_payload(body: dict) -> tuple[Optional[dict], Any]:
    """
    Validate and normalise the PUT /dlp/policy request body.
    Returns (clean_payload, error). On success, error is None.
    On failure, error is either a string (simple validation error) OR a dict
    (structured error payload, e.g. rule_override floor violations) that the
    caller jsonifies directly.
    """
    unknown = set(body.keys()) - _ALLOWED_POLICY_KEYS
    if unknown:
        return None, f"Unknown policy key(s): {sorted(unknown)}"

    clean: dict = {}

    if 'enabled' in body:
        clean['enabled'] = bool(body['enabled'])

    if 'sensitivity' in body:
        sens = body['sensitivity']
        if sens not in _VALID_SENSITIVITIES:
            return None, f"sensitivity must be one of {sorted(_VALID_SENSITIVITIES)}"
        clean['sensitivity'] = sens

    if 'mode' in body:
        mode = body['mode'] or 'enforce'
        if mode not in _VALID_MODES:
            return None, f"mode must be one of {sorted(_VALID_MODES)}"
        clean['mode'] = mode

    if 'rule_overrides' in body:
        ro = body['rule_overrides']
        if not isinstance(ro, dict):
            return None, "rule_overrides must be an object"
        valid_actions_with_allow = {'allow', 'warn', 'block'}
        coerced_ro: dict = {}
        for rule_id, action in ro.items():
            if not isinstance(action, str):
                return None, f"rule_overrides[{rule_id!r}] must be one of {sorted(valid_actions_with_allow)}"
            action = collapse_action(action)
            if action not in valid_actions_with_allow:
                return None, f"rule_overrides[{rule_id!r}] must be one of {sorted(valid_actions_with_allow)}"
            coerced_ro[rule_id] = action
        ro = coerced_ro

        # Enforce per-severity floors on builtin rules. Custom (non-builtin) rule_ids
        # bypass the floor — they're user-authored.
        severity_map = _builtin_severity_map()
        violations: list[dict] = []
        for rule_id, action in ro.items():
            severity = severity_map.get(rule_id)
            if severity is None:
                continue  # unknown / custom rule — no floor
            floor = _SEVERITY_FLOOR_ACTION.get(severity)
            if floor is None:
                continue
            if _ACTION_ORDER[action] < _ACTION_ORDER[floor]:
                violations.append({
                    'rule_id': rule_id,
                    'severity': severity,
                    'min_action': floor,
                    'proposed_action': action,
                })
        if violations:
            return None, {
                'error': 'rule_override_below_floor',
                'violations': violations,
            }
        clean['rule_overrides'] = ro

    if 'disabled_rules' in body:
        dr = body['disabled_rules']
        if not isinstance(dr, list):
            return None, "disabled_rules must be an array"
        # Simple on/off — any rule id (builtin, dynamic, or custom) may be
        # switched off. No severity floor: disabling is a deliberate owner choice.
        clean['disabled_rules'] = sorted({str(x).strip() for x in dr if str(x).strip()})

    if 'custom_patterns' in body:
        patterns = body['custom_patterns']
        if not isinstance(patterns, list):
            return None, "custom_patterns must be an array"
        normalised = []
        for i, pat in enumerate(patterns):
            # Skip empty/abandoned rows — a rule with no word/phrase (or regex)
            # carries nothing to match and must not abort the whole policy save.
            if isinstance(pat, dict):
                _mt = pat.get('match_type', 'regex')
                _val = pat.get('text') if _mt == 'text' else pat.get('regex')
                if not str(_val or '').strip():
                    continue
            err = _validate_custom_pattern(pat, i)
            if err:
                return None, err
            match_type = pat.get('match_type', 'regex')
            entry = {
                'id': str(pat.get('id') or uuid.uuid4().hex[:12]),
                'name': str(pat['name']).strip(),
                'match_type': match_type,
                'severity': pat['severity'],
                'action': collapse_action(pat['action']),
            }
            if match_type == 'text':
                text = str(pat['text']).strip()
                entry['text'] = text
                # Case-insensitive substring ban — backend is the source of
                # truth so a bypassed client can't inject an unescaped pattern.
                entry['regex'] = '(?i)' + re.escape(text)
            else:
                entry['regex'] = str(pat['regex'])
            normalised.append(entry)
        clean['custom_patterns'] = normalised

    if 'internal_hostname_suffixes' in body:
        suffixes = body['internal_hostname_suffixes']
        if not isinstance(suffixes, list):
            return None, "internal_hostname_suffixes must be an array"
        clean['internal_hostname_suffixes'] = [str(s).strip() for s in suffixes if s]

    if 'llm_classifier' in body:
        lc_clean, lc_err = _validate_llm_classifier(body['llm_classifier'])
        if lc_err:
            return None, lc_err
        clean['llm_classifier'] = lc_clean

    if 'notify_owners' in body:
        clean['notify_owners'] = bool(body['notify_owners'])

    return clean, None


# ---------------------------------------------------------------------------
# Pre-send scan
# ---------------------------------------------------------------------------

def _attachment_text_for_scan(attachments: Any, user_id) -> str:
    """Owner-scoped extracted text for pre-flight — SAME join as chat gate.

    Delegates to ``attachment_text_for_dlp`` so the scan and the chokepoint
    see the same bytes. Bare id strings are normalized to ``{upload_id}`` dicts.
    """
    from app.services.chat_attachments import attachment_text_for_dlp

    if not attachments:
        return ''
    items = attachments if isinstance(attachments, list) else []
    normalized = []
    for item in items:
        if isinstance(item, dict):
            normalized.append(item)
        elif isinstance(item, str):
            normalized.append({'upload_id': item})
    return attachment_text_for_dlp(normalized, user_id=user_id)


@router.post("/dlp/scan")
async def dlp_scan(request: Request, current: dict = Depends(require_active)):
    """
    Pre-send DLP scan.

    Writes a dlp_event when highest_action is block or warn so the
    manager dashboard sees attempts even when the client aborts the send.

    Body: {
      text: str,
      workspace_id: str,
      project_id?: str,
      source: str,
      attachments?: [{upload_id}] | upload_ids?: [str]
    }

    Attachment text is loaded owner-scoped and joined with ``text`` the same way
    the chat chokepoint does.
    """
    from dataclasses import asdict

    user_id_str = str(current['_id'])

    # Rate limit check
    retry_after = _check_rate_limit(user_id_str)
    if retry_after is not None:
        return JSONResponse(
            {'error': 'rate_limited', 'retry_after': retry_after},
            status_code=429,
            headers={'Retry-After': str(int(retry_after))},
        )

    body = await _json_body(request)
    text = body.get('text', '')
    if text is None:
        text = ''
    if not isinstance(text, str):
        text = str(text)
    workspace_id = body.get('workspace_id', '')
    project_id = body.get('project_id') or None
    source = body.get('source', '')
    # Prefer explicit attachments[]; also accept upload_ids[] shorthand.
    attachments = body.get('attachments')
    if not attachments and body.get('upload_ids'):
        attachments = body.get('upload_ids')

    if not workspace_id:
        return JSONResponse({'error': 'workspace_id is required'}, status_code=400)
    if not validate_object_id(workspace_id):
        return JSONResponse({'error': 'Invalid workspace_id'}, status_code=400)
    if not source:
        return JSONResponse({'error': 'source is required'}, status_code=400)

    # Verify user has at least viewer access to the workspace
    if not check_workspace_access(current['_id'], workspace_id, 'viewer'):
        return JSONResponse({'error': 'Workspace access denied', 'code': 'forbidden'}, status_code=403)

    attachment_text = _attachment_text_for_scan(attachments, current['_id'])
    scan_text = f"{text}\n\n{attachment_text}" if attachment_text else text
    if not str(scan_text).strip():
        return JSONResponse(
            {'error': 'text or attachments with extractable text required'},
            status_code=400,
        )

    body_lang = (body.get('lang') or '').strip()
    user_lang = (
        body_lang
        or current.get('ai_preferences', {}).get('user_info', {}).get('language', 'en')
        or 'en'
    )[:2].lower()

    detector = DLPDetector.from_workspace(workspace_id)
    result = detector.scan(scan_text, user_lang=user_lang, user_id=current['_id'])

    event_id: Optional[str] = None
    # P2.27 — persist warn events too. Pre-flight has not yet sent the message,
    # so was_sent=False is correct for every action level. Audit dashboards
    # need warn rows to spot policy drift.
    if result.matches and result.highest_action in ('warn', 'block'):
        try:
            inserted = DLPEventModel.create(
                user_id=current['_id'],
                workspace_id=workspace_id,
                project_id=project_id,
                source=source or 'chat',
                source_ref={'preflight': True},
                matches=[asdict(m) for m in result.matches],
                highest_action=result.highest_action,
                was_sent=False,
                text_sha256=result.text_sha256,
                text_length=result.text_length,
            )
            event_id = inserted.get('_id') if isinstance(inserted, dict) else None
        except Exception:
            pass  # never let event-write failure break the scan response

    # Redactability is MODE-INDEPENDENT: a span is spliceable when it has a real
    # (start,end) range and is NOT a smart-scan (llm) verdict (those carry no
    # offsets). The client uses this to surface a per-send "Redact & send" option
    # even in enforce mode. `auto_redact` separately tells the client the
    # workspace is in redact mode, so the server will scrub on send (no block
    # modal needed — just send).
    redactable = any(
        m.offset_end > m.offset_start and m.source != 'llm'
        for m in result.matches
    )

    response_body = {
        'result': result.to_dict(),
        'event_id': str(event_id) if event_id else None,
        'redactable': redactable,
        'auto_redact': bool(detector.redaction_enabled),
    }
    if redactable:
        # redact() re-scans (smart-scan is sha-cached, so this is cheap) and
        # returns (redacted_text, redactions, result); we only need the spliced
        # preview string here. Preview uses message body only so the composer
        # can swap the bubble text without re-hydrating attachment payloads.
        # Attachment scrubbing still happens server-side on send in redact mode.
        redacted_text, _redactions, _redact_result = detector.redact(
            text if text.strip() else scan_text,
            user_lang=user_lang,
            user_id=current['_id'],
        )
        response_body['redacted_preview'] = redacted_text
    return response_body


# ---------------------------------------------------------------------------
# Test classifier playground (owner-only)
# ---------------------------------------------------------------------------

@router.post("/dlp/test")
async def dlp_test(request: Request, current: dict = Depends(require_active)):
    """
    DLP classifier playground — runs a full scan against a sample of text
    WITHOUT persisting a dlp_event and WITHOUT counting against the rate
    limit. Owner-only.

    Body: { text: str, workspace_id: str }
    """
    body = await _json_body(request)
    text = body.get('text', '')
    workspace_id = body.get('workspace_id', '')

    if not text:
        return JSONResponse({'error': 'text is required'}, status_code=400)
    if not workspace_id:
        return JSONResponse({'error': 'workspace_id is required'}, status_code=400)
    if not validate_object_id(workspace_id):
        return JSONResponse({'error': 'Invalid workspace_id'}, status_code=400)

    if not check_workspace_access(current['_id'], workspace_id, 'owner'):
        return JSONResponse({'error': 'Workspace access denied', 'code': 'forbidden'}, status_code=403)

    body_lang = (body.get('lang') or '').strip()
    user_lang = (
        body_lang
        or current.get('ai_preferences', {}).get('user_info', {}).get('language', 'en')
        or 'en'
    )[:2].lower()

    detector = DLPDetector.from_workspace(workspace_id)
    result = detector.scan(text, user_lang=user_lang)

    return {'result': result.to_dict()}


# ---------------------------------------------------------------------------
# Workspace DLP policy
# ---------------------------------------------------------------------------

@router.get("/workspaces/{wid}/dlp/policy")
def get_dlp_policy(wid: str, current: dict = Depends(workspace_member_dep('viewer', 'wid'))):
    """Return effective DLP policy + rule catalog for a workspace."""
    if not validate_object_id(wid):
        return JSONResponse({'error': 'Invalid workspace ID'}, status_code=400)

    workspace = WorkspaceModel.find_by_id(wid)
    if workspace is None:
        return JSONResponse({'error': 'Workspace not found'}, status_code=404)

    raw_dlp = (workspace.get('settings') or {}).get('dlp')
    policy = effective_policy(raw_dlp)

    return {
        'policy': policy,
        'rule_catalog': _rule_catalog(),
    }


# Max draft length for guidance enhance (policy field is 4000; leave headroom).
_GUIDANCE_ENHANCE_MAX = 4000
_GUIDANCE_ENHANCE_MODEL = 'google/gemini-3.5-flash-lite'


@router.post("/workspaces/{wid}/dlp/enhance-guidance")
async def enhance_dlp_guidance(
    wid: str,
    request: Request,
    current: dict = Depends(workspace_member_dep('owner', 'wid')),
):
    """Rewrite a manager's DLP smart-scan guidance via OpenRouter.

    Owner-only (same gate as policy edit). Body: ``{ prompt: str, lang?: str }``.
    Returns ``{ enhanced_prompt: str }``. Uses the same flash-lite model as
    persona ✨enhance; billed as ``feature='dlp_guidance'``, ``origin='web'``.
    """
    if not validate_object_id(wid):
        return JSONResponse({'error': 'Invalid workspace ID'}, status_code=400)

    body = await _json_body(request)
    prompt = (body.get('prompt') or '').strip()
    if not prompt:
        return JSONResponse({'error': 'prompt is required'}, status_code=400)
    if len(prompt) > _GUIDANCE_ENHANCE_MAX:
        return JSONResponse(
            {'error': f'prompt too long (max {_GUIDANCE_ENHANCE_MAX} characters)'},
            status_code=400,
        )

    user_id = str(current['_id'])
    lang = ((body.get('lang') or '')[:2] or 'en').lower()
    lang_name = 'Persian' if lang in ('fa', 'pe') else 'English'

    def _spend() -> None:
        spend_gate.gate(
            user_id=user_id,
            workspace_id=str(wid),
            project_id=None,
            origin='web',
            feature='dlp_guidance',
        )

    await anyio.to_thread.run_sync(_spend)

    # Keep the rewrite SHORT. Managers read this box in UI; long legal-style
    # policies confuse them and burn smart-scan context. Hard style rules below
    # + low temperature + tight max_tokens keep output compact.
    enhancement_prompt = f"""Rewrite the manager draft into a SHORT workspace DLP guidance for an AI content-safety classifier.

HARD LIMITS (must follow):
- Length: at most 4 short sentences OR 4 short bullet lines. Target ~80–200 words. NEVER write essays, numbered chapters, or long lists of examples.
- Language: {lang_name}
- Keep the manager's original intent and any named entities/phrases
- Structure: (1) what to FLAG, (2) what is ALLOWED as generic talk without real values, optional (3) one severity hint (confidential vs restricted) if obvious
- Plain words a non-lawyer manager understands — no "دستورالعمل نظارت", no "واحد امنیت اطلاعات", no meta titles, no "قواعد اجرایی"
- Presence vs topic: flag when a concrete name/amount/id appears; allow abstract how-to questions without those values
- Return ONLY the guidance text — no preamble, no markdown headings, no code fences

Good style example (English):
"Flag company names next to deal amounts, FX rates, or transaction IDs as confidential. Flag named client aliases in renewals as restricted. Generic accounting process questions with no real names or numbers are public."

Manager draft:
{prompt}
"""

    response = await anyio.to_thread.run_sync(
        partial(
            OpenRouterService.chat_completion,
            messages=[{'role': 'user', 'content': enhancement_prompt}],
            model=_GUIDANCE_ENHANCE_MODEL,
            max_tokens=320,
            temperature=0.1,
            stream=False,
            user_id=user_id,
            conversation_id=None,
            feature='dlp_guidance',
            workspace_id=str(wid),
            project_id=None,
            origin='web',
        )
    )

    if isinstance(response, dict) and response.get('error'):
        err = response['error']
        msg = err.get('message', 'Enhancement failed') if isinstance(err, dict) else str(err)
        return JSONResponse({'error': msg}, status_code=500)

    try:
        enhanced = (response['choices'][0]['message']['content'] or '').strip()
    except (KeyError, IndexError, TypeError):
        return JSONResponse({'error': 'Invalid response from LLM'}, status_code=500)

    if not enhanced:
        return JSONResponse({'error': 'Empty enhancement'}, status_code=500)

    # Soft UI-friendly cap (policy field allows 4000; we keep enhance short).
    _SOFT_CAP = 800
    if len(enhanced) > _SOFT_CAP:
        cut = enhanced[:_SOFT_CAP]
        # Prefer ending on a sentence/line boundary.
        for sep in ('. ', '.\n', '。', '\n'):
            idx = cut.rfind(sep)
            if idx >= 200:
                cut = cut[: idx + len(sep.rstrip())]
                break
        enhanced = cut.rstrip()
    if len(enhanced) > _GUIDANCE_ENHANCE_MAX:
        enhanced = enhanced[:_GUIDANCE_ENHANCE_MAX].rstrip()

    return {'enhanced_prompt': enhanced}


@router.put("/workspaces/{wid}/dlp/policy")
async def update_dlp_policy(
    wid: str,
    request: Request,
    current: dict = Depends(workspace_member_dep('owner', 'wid')),
):
    """Update workspace DLP policy. Only workspace owners may call this."""
    if not validate_object_id(wid):
        return JSONResponse({'error': 'Invalid workspace ID'}, status_code=400)

    workspace = WorkspaceModel.find_by_id(wid)
    if workspace is None:
        return JSONResponse({'error': 'Workspace not found'}, status_code=404)

    body = await _json_body(request)
    payload, err = _build_policy_payload(body)
    if err:
        # Structured floor-violation payload (dict) vs simple string error
        if isinstance(err, dict):
            return JSONResponse(err, status_code=400)
        return JSONResponse({'error': err}, status_code=400)

    # Merge with existing settings.dlp
    existing_dlp = (workspace.get('settings') or {}).get('dlp') or {}
    merged_dlp = {**existing_dlp, **payload}

    # Persist
    WorkspaceModel.update_settings_subkey(wid, 'dlp', merged_dlp)

    return {'policy': effective_policy(merged_dlp)}


# ---------------------------------------------------------------------------
# Workspace DLP events
# ---------------------------------------------------------------------------

@router.get("/workspaces/{wid}/dlp/events")
def list_dlp_events(
    request: Request,
    wid: str,
    current: dict = Depends(workspace_member_dep('owner', 'wid')),
):
    """Paginated DLP event list for a workspace. Owner-only."""
    if not validate_object_id(wid):
        return JSONResponse({'error': 'Invalid workspace ID'}, status_code=400)

    args = request.query_params
    user_id_filter = args.get('user_id') or None
    if user_id_filter and not validate_object_id(user_id_filter):
        return JSONResponse({'error': 'Invalid user_id filter'}, status_code=400)

    severity = args.get('severity') or None
    source = args.get('source') or None
    status = args.get('status') or None
    action = args.get('action') or None
    from_dt = args.get('from') or None
    to_dt = args.get('to') or None

    try:
        skip = int(args.get('skip', 0))
        limit = int(args.get('limit', 50))
    except (TypeError, ValueError):
        return JSONResponse({'error': 'skip and limit must be integers'}, status_code=400)
    limit = max(1, min(200, limit))

    try:
        rows, total = DLPEventModel.find_by_workspace(
            wid,
            user_id=user_id_filter,
            severity=severity,
            source=source,
            status=status,
            action=action,
            from_dt=from_dt,
            to_dt=to_dt,
            skip=skip,
            limit=limit,
        )
    except (ValueError, Exception) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)

    _attach_user_identity(rows)

    return {
        'rows': serialize_doc(rows),
        'total': total,
        'skip': skip,
        'limit': limit,
    }


@router.get("/workspaces/{wid}/dlp/events/{event_id}")
def get_dlp_event(
    wid: str,
    event_id: str,
    current: dict = Depends(workspace_member_dep('owner', 'wid')),
):
    """Fetch a single DLP event. 404 if it doesn't belong to this workspace."""
    if not validate_object_id(wid):
        return JSONResponse({'error': 'Invalid workspace ID'}, status_code=400)
    if not validate_object_id(event_id):
        return JSONResponse({'error': 'Invalid event ID'}, status_code=400)

    event = DLPEventModel.find_by_id(event_id)
    if event is None or str(event.get('workspace_id', '')) != wid:
        return JSONResponse({'error': 'Event not found', 'code': 'not_found'}, status_code=404)

    return {'event': serialize_doc(event)}


@router.patch("/workspaces/{wid}/dlp/events/{event_id}")
async def patch_dlp_event(
    wid: str,
    event_id: str,
    request: Request,
    current: dict = Depends(workspace_member_dep('owner', 'wid')),
):
    """Update status + review_note on a DLP event."""
    if not validate_object_id(wid):
        return JSONResponse({'error': 'Invalid workspace ID'}, status_code=400)
    if not validate_object_id(event_id):
        return JSONResponse({'error': 'Invalid event ID'}, status_code=400)

    event = DLPEventModel.find_by_id(event_id)
    if event is None or str(event.get('workspace_id', '')) != wid:
        return JSONResponse({'error': 'Event not found', 'code': 'not_found'}, status_code=404)

    body = await _json_body(request)
    new_status = body.get('status')
    if not new_status:
        return JSONResponse({'error': 'status is required'}, status_code=400)
    if new_status not in VALID_STATUSES:
        return JSONResponse({'error': f'status must be one of {sorted(VALID_STATUSES)}'}, status_code=400)

    review_note = body.get('review_note')

    try:
        updated = DLPEventModel.update_review(
            event_id,
            reviewer_id=current['_id'],
            status=new_status,
            review_note=review_note,
        )
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)

    return {'event': serialize_doc(updated)}


# ---------------------------------------------------------------------------
# Workspace DLP stats
# ---------------------------------------------------------------------------

@router.get("/workspaces/{wid}/dlp/stats")
def get_dlp_stats(
    request: Request,
    wid: str,
    current: dict = Depends(workspace_member_dep('owner', 'wid')),
):
    """Aggregated stats for a workspace. Owner-only."""
    if not validate_object_id(wid):
        return JSONResponse({'error': 'Invalid workspace ID'}, status_code=400)

    try:
        days = int(request.query_params.get('days', 7))
    except (TypeError, ValueError):
        return JSONResponse({'error': 'days must be an integer'}, status_code=400)
    days = max(1, min(365, days))

    stats = DLPEventModel.aggregate_workspace_stats(wid, days=days)
    return serialize_doc(stats)


# ---------------------------------------------------------------------------
# Admin endpoints (cross-workspace)
# ---------------------------------------------------------------------------

@router.get("/admin/dlp/events")
def admin_list_dlp_events(request: Request, current: dict = Depends(require_admin)):
    """Cross-workspace DLP event list for platform admins."""
    from datetime import timedelta

    args = request.query_params
    workspace_id_filter = args.get('workspace_id') or None
    if workspace_id_filter and not validate_object_id(workspace_id_filter):
        return JSONResponse({'error': 'Invalid workspace_id filter'}, status_code=400)

    user_id_filter = args.get('user_id') or None
    if user_id_filter and not validate_object_id(user_id_filter):
        return JSONResponse({'error': 'Invalid user_id filter'}, status_code=400)

    severity = args.get('severity') or None
    source = args.get('source') or None
    status = args.get('status') or None
    action = args.get('action') or None
    from_dt = args.get('from') or None
    to_dt = args.get('to') or None

    days_param = args.get('days') or None
    if days_param and not from_dt:
        try:
            days_int = max(1, min(365, int(days_param)))
        except (TypeError, ValueError):
            return JSONResponse({'error': 'days must be an integer'}, status_code=400)
        from_dt = (datetime.utcnow() - timedelta(days=days_int)).isoformat()

    try:
        skip = int(args.get('skip', 0))
        limit = int(args.get('limit', 50))
    except (TypeError, ValueError):
        return JSONResponse({'error': 'skip and limit must be integers'}, status_code=400)
    limit = max(1, min(200, limit))

    try:
        rows, total = DLPEventModel.find_all(
            workspace_id=workspace_id_filter,
            user_id=user_id_filter,
            severity=severity,
            source=source,
            status=status,
            action=action,
            from_dt=from_dt,
            to_dt=to_dt,
            skip=skip,
            limit=limit,
        )
    except (ValueError, Exception) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)

    _attach_user_identity(rows)

    return {
        'rows': serialize_doc(rows),
        'total': total,
        'skip': skip,
        'limit': limit,
    }


@router.get("/admin/dlp/events/{event_id}")
def admin_get_dlp_event(event_id: str, current: dict = Depends(require_admin)):
    """Fetch any DLP event (cross-workspace) for platform admins."""
    if not validate_object_id(event_id):
        return JSONResponse({'error': 'Invalid event ID'}, status_code=400)

    event = DLPEventModel.find_by_id(event_id)
    if event is None:
        return JSONResponse({'error': 'Event not found', 'code': 'not_found'}, status_code=404)

    return {'event': serialize_doc(event)}


@router.patch("/admin/dlp/events/{event_id}")
async def admin_patch_dlp_event(
    event_id: str,
    request: Request,
    current: dict = Depends(require_admin),
):
    """Update review status + note on any DLP event (cross-workspace). Admin-only."""
    if not validate_object_id(event_id):
        return JSONResponse({'error': 'Invalid event ID'}, status_code=400)

    body = await _json_body(request)
    new_status = body.get('status')
    if not new_status:
        return JSONResponse({'error': 'status is required'}, status_code=400)
    if new_status not in VALID_STATUSES:
        return JSONResponse(
            {'error': f'status must be one of {sorted(VALID_STATUSES)}'},
            status_code=400,
        )

    try:
        updated = DLPEventModel.update_review(
            event_id,
            reviewer_id=current['_id'],
            status=new_status,
            review_note=body.get('note'),
        )
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)

    if updated is None:
        return JSONResponse({'error': 'Event not found', 'code': 'not_found'}, status_code=404)

    return {'event': serialize_doc(updated)}


@router.get("/admin/dlp/stats")
def admin_get_dlp_stats(request: Request, current: dict = Depends(require_admin)):
    """Global DLP stats for platform admins."""
    try:
        days = int(request.query_params.get('days', 7))
    except (TypeError, ValueError):
        return JSONResponse({'error': 'days must be an integer'}, status_code=400)
    days = max(1, min(365, days))

    stats = DLPEventModel.aggregate_global_stats(days=days)
    return serialize_doc(stats)


__all__ = ["router"]
