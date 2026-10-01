"""
Series glossary — keyterms + speaker-name memory per recurring meeting series.

Backed by Postgres via the ``KeytermModel`` + ``SpeakerNameModel`` façades
on ``meeting_series_keyterms`` and ``meeting_series_speaker_names``
respectively. Both façades use UUID4 string IDs (mirrors ``meeting_series._id``).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app.models.meeting_series import KeytermModel, SpeakerNameModel

logger = logging.getLogger(__name__)


# Keyterm length / count caps. ``BATCH_*`` apply to async Scribe v2 calls.
# Realtime values are kept for forward-compat (live captions are out-of-scope
# in v1 but the constants live here so glossary callers don't drift).
BATCH_MAX_TERMS = 1000
BATCH_MAX_CHARS = 50
REALTIME_MAX_TERMS = 50
REALTIME_MAX_CHARS = 20
KEYTERM_MAX_WORDS = 5

KEYTERM_SOURCE_MANUAL = 'manual'
KEYTERM_SOURCE_SUGGESTED = 'suggested'
KEYTERM_SOURCE_ACCEPTED = 'accepted'
_VALID_SOURCES = {KEYTERM_SOURCE_MANUAL, KEYTERM_SOURCE_SUGGESTED, KEYTERM_SOURCE_ACCEPTED}


_TOKEN_PUNCT = re.compile(r"[\s،.,;:!?\(\)\[\]\{\}\"'«»\-_/\\|]+")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _series_id_str(series_id) -> str | None:
    """Normalise a series id to its stored representation (UUID4 string)."""
    if not series_id:
        return None
    return str(series_id)


def _is_valid_keyterm(term: str, *, max_chars: int) -> bool:
    if not term:
        return False
    term = term.strip()
    if len(term) < 2 or len(term) > max_chars:
        return False
    word_count = len([w for w in _TOKEN_PUNCT.split(term) if w])
    if word_count > KEYTERM_MAX_WORDS:
        return False
    if term.isdigit():
        return False
    return True


def get_active_keyterms(series_id, *, realtime: bool = False) -> list[str]:
    """Return de-duplicated, validated MANUAL+ACCEPTED keyterms for a series.

    ``series_id`` must be a UUID4 string. Ordered by insertion time.
    Capped per ``BATCH_MAX_TERMS`` / ``REALTIME_MAX_TERMS``.
    """
    sid = _series_id_str(series_id)
    if not sid:
        return []
    max_terms = REALTIME_MAX_TERMS if realtime else BATCH_MAX_TERMS
    max_chars = REALTIME_MAX_CHARS if realtime else BATCH_MAX_CHARS

    out: list[str] = []
    seen: set[str] = set()
    for source in (KEYTERM_SOURCE_MANUAL, KEYTERM_SOURCE_ACCEPTED):
        for row in KeytermModel.list_for_series(sid, source=source):
            term = (row.get('term') or '').strip()
            if term in seen:
                continue
            if not _is_valid_keyterm(term, max_chars=max_chars):
                continue
            seen.add(term)
            out.append(term)
            if len(out) >= max_terms:
                return out
    return out


def add_suggested_terms(series_id, terms: list[str]) -> int:
    """Upsert SUGGESTED terms; existing rows are left alone (manual wins).

    Returns count of newly-inserted rows.
    """
    sid = _series_id_str(series_id)
    if not sid or not terms:
        return 0

    existing_terms = {
        (row.get('term') or '').strip()
        for row in KeytermModel.list_for_series(sid)
    }
    added = 0
    for raw in terms:
        if not raw:
            continue
        term = raw.strip()
        if not _is_valid_keyterm(term, max_chars=BATCH_MAX_CHARS):
            continue
        if term in existing_terms:
            continue
        KeytermModel.upsert_term(sid, term, KEYTERM_SOURCE_SUGGESTED)
        added += 1
    return added


def add_manual_term(series_id, term: str) -> dict | None:
    """Insert a MANUAL term, or promote an existing SUGGESTED row to MANUAL.

    Returns the resulting document (with ``_id``) or ``None`` if the term
    failed validation.
    """
    sid = _series_id_str(series_id)
    if not sid:
        return None
    term = (term or '').strip()
    if not _is_valid_keyterm(term, max_chars=BATCH_MAX_CHARS):
        return None
    return KeytermModel.upsert_term(sid, term, KEYTERM_SOURCE_MANUAL) or None


def accept_term(term_id) -> bool:
    """Promote SUGGESTED → ACCEPTED. Returns True on match."""
    if not term_id:
        return False
    return KeytermModel.set_source(str(term_id), KEYTERM_SOURCE_ACCEPTED)


def reject_term(term_id) -> bool:
    """Reject = delete row. Returns True if a row was removed."""
    if not term_id:
        return False
    return KeytermModel.delete(str(term_id))


def list_keyterms(series_id, source: str | None = None) -> list[dict]:
    """Return all keyterms for a series, optionally filtered by source.

    Ordered by ``created_at`` ascending.
    """
    sid = _series_id_str(series_id)
    if not sid:
        return []
    if source is not None and source not in _VALID_SOURCES:
        return []
    return KeytermModel.list_for_series(sid, source=source)


def _filter_tokens(tokens: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        clean = tok.strip()
        if clean in seen:
            continue
        if not _is_valid_keyterm(clean, max_chars=BATCH_MAX_CHARS):
            continue
        seen.add(clean)
        out.append(clean)
    return out


def upsert_speaker_name(series_id, display_name: str) -> None:
    """Insert-or-bump a speaker name in this series' memory."""
    sid = _series_id_str(series_id)
    if not sid:
        return
    name = (display_name or '').strip()
    if not name:
        return
    SpeakerNameModel.upsert(sid, name)


def list_speaker_names(series_id) -> list[str]:
    """Recent display names for this series, newest-first."""
    sid = _series_id_str(series_id)
    if not sid:
        return []
    rows = SpeakerNameModel.list_for_series(sid)
    return [row.get('display_name', '') for row in rows if row.get('display_name')]
