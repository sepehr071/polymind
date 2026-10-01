"""
DLP gate — shared helper invoked at every server-side chokepoint.

Resolves the workspace policy, runs DLPDetector.scan, persists a DLPEventModel
row when matches are found, and raises DLPBlockedError on block.

Live actions are warn (log, send continues) and block (raise ``dlp_blocked``).
``require_confirm`` is not live — it is treated as block. ``confirmed`` and
``dlp_confirm_token`` are accepted and ignored; they never unlock a send.
"""
import logging
from dataclasses import asdict
from typing import Any, Optional

from app.models.dlp_event import DLPEventModel, _highest_severity_of
from app.services.dlp_service import DLPDetector, collapse_action

logger = logging.getLogger(__name__)


def _highest_severity(matches: list[dict[str, Any]]) -> str:
    """Pick the strongest severity across serialized matches.

    Thin wrapper over the model's ``_highest_severity_of`` so the gate has a
    single, local name for the helper (callers reference ``_highest_severity``).
    """
    return _highest_severity_of(matches)


class DLPBlockedError(Exception):
    """Raised when a DLP scan blocks the send. ``code`` is ``dlp_blocked``."""

    def __init__(
        self,
        code: str,
        matches: list[dict[str, Any]],
        message: str = "",
        confirm_token: Optional[str] = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.matches = matches  # list of serialized DLPMatch dicts
        # Confirm tokens are not minted or returned. Argument kept for callers.
        del confirm_token
        self.confirm_token = None


def gate(
    *,
    text: str,
    user_id: Any,
    workspace_id: Any,
    project_id: Any = None,
    source: str,
    source_ref: dict[str, Any],
    confirmed: bool = False,
    dlp_confirm_token: Optional[str] = None,
    user_lang: str = 'en',
) -> Optional[dict[str, Any]]:
    """
    Run DLP scan against text and persist an event when matches found.

    Returns the persisted dlp_event dict, or None when no scan needed (no
    workspace, empty text, or no matches).

    Raises DLPBlockedError (code ``dlp_blocked``) when the highest action is
    block. ``require_confirm`` is treated as block. ``confirmed`` and
    ``dlp_confirm_token`` do not unlock the send.
    """
    # Accepted for request compatibility. Never a bypass.
    del confirmed, dlp_confirm_token

    if not text or not workspace_id:
        return None

    detector = DLPDetector.from_workspace(str(workspace_id))
    result = detector.scan(text, user_lang=user_lang, user_id=user_id)

    if not result.matches:
        return None

    action = collapse_action(result.highest_action)
    matches_dicts = [asdict(m) for m in result.matches]
    for match in matches_dicts:
        match["action"] = collapse_action(match.get("action"))

    code: Optional[str] = None
    was_sent = True
    if action == "block":
        was_sent = False
        code = "dlp_blocked"

    event = DLPEventModel.create(
        user_id=user_id,
        workspace_id=workspace_id,
        project_id=project_id,
        source=source,
        source_ref=source_ref,
        matches=matches_dicts,
        highest_action=action,
        was_sent=was_sent,
        text_sha256=result.text_sha256,
        text_length=result.text_length,
    )

    if code is not None:
        raise DLPBlockedError(code=code, matches=matches_dicts)

    return event


def gate_redactable(
    *,
    text: str,
    user_id: Any,
    workspace_id: Any,
    project_id: Any = None,
    source: str,
    source_ref: dict[str, Any],
    force_redact: bool = False,
    confirmed: bool = False,
    dlp_confirm_token: Optional[str] = None,
    user_lang: str = 'en',
) -> dict[str, Any]:
    """Redaction-aware DLP chokepoint.

    When the workspace policy is in redact mode (or ``force_redact`` is set),
    sensitive spans are deterministically spliced out of ``text`` (replaced
    with typed placeholders) and the SCRUBBED text is returned for the caller
    to forward to the LLM. Otherwise this delegates to :func:`gate` (warn logs
    and continues; block raises).

    Returns a dict::

        {
          'redacted': bool,            # True only when spans were spliced
          'redacted_text': str,        # text to actually send downstream
          'redactions': list[dict],    # [{placeholder,label,severity,rule_id}]
          'event': dict | None,        # persisted dlp_event (or gate()'s return)
        }

    Raises:
        DLPBlockedError: in redact mode, when a high-severity smart-scan
            (``source == 'llm'``) restricted verdict cannot be span-redacted
            (no offsets to splice) — we refuse to send rather than leak it.
            In enforce mode, propagated from :func:`gate` (block).
    """
    if not text or not workspace_id:
        return {'redacted': False, 'redacted_text': text, 'redactions': [], 'event': None}

    detector = DLPDetector.from_workspace(str(workspace_id))
    should_redact = force_redact or detector.redaction_enabled

    if not should_redact:
        # Enforce posture: gate handles block/warn and may raise
        # DLPBlockedError. Confirm flags are forwarded and do not unlock a block.
        event = gate(
            text=text,
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
            source=source,
            source_ref=source_ref,
            confirmed=confirmed,
            dlp_confirm_token=dlp_confirm_token,
            user_lang=user_lang,
        )
        return {'redacted': False, 'redacted_text': text, 'redactions': [], 'event': event}

    redacted_text, redactions, result = detector.redact(
        text, user_lang=user_lang, user_id=user_id,
    )

    if not result.matches:
        # Clean text — nothing to redact, nothing to log.
        return {'redacted': False, 'redacted_text': text, 'redactions': [], 'event': None}

    matches_serialized = [asdict(m) for m in result.matches]

    # Smart-scan may flag content it cannot return as a locatable span (model
    # paraphrase, or a verdict carrying no concrete value). Those spanless llm
    # matches can't be spliced. In redact mode a spanless llm match does not
    # block the send — there is nothing to splice. Every located span (regex
    # + llm) was already redacted by detector.redact() above; an unlocatable llm
    # remainder is advisory only and the message is sent. The classifier is
    # instructed to return `public` when it can't quote a concrete value, so a
    # spanless non-public verdict is rare.
    spanless_llm = [
        m for m in result.matches
        if m.source == 'llm' and not (m.offset_end > m.offset_start)
    ]
    if spanless_llm:
        logger.info(
            "DLP redact: %d smart-scan match(es) without a locatable span — redacted located "
            "spans, sending remainder (source=%s workspace=%s)",
            len(spanless_llm), source, workspace_id,
        )

    event = DLPEventModel.create(
        user_id=user_id,
        workspace_id=workspace_id,
        project_id=project_id,
        source=source,
        source_ref=source_ref,
        matches=matches_serialized,
        highest_action='redact',
        highest_severity=_highest_severity(matches_serialized),
        status='redacted',
        was_sent=True,
        text_sha256=result.text_sha256,
        text_length=result.text_length,
    )

    return {
        'redacted': True,
        'redacted_text': redacted_text,
        'redactions': redactions,
        'event': event,
    }


def format_blocked_response(err: DLPBlockedError) -> dict[str, Any]:
    """Shape the JSON body returned to clients on a DLP block."""
    return {
        "error": "Sensitive content blocked by Content Safety policy",
        "code": err.code,
        "matches": [
            {
                "rule_id": m["rule_id"],
                "rule_name": m["rule_name"],
                "severity": m["severity"],
                "action": m["action"],
                "offset_start": m["offset_start"],
                "offset_end": m["offset_end"],
                "snippet": m["snippet"],
            }
            for m in err.matches
        ],
    }
