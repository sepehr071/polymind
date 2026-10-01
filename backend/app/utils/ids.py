"""ID coercion helpers for the Postgres cutover.

After Phase 4 the canonical primary key on every identity table is a UUID,
not a Mongo ``ObjectId``. Routes still pass IDs as strings (or pre-parsed
UUIDs); this helper centralises the conversion + the legacy-rejection
behaviour ("no data preserved across the wipe").
"""

from __future__ import annotations

import re
import uuid


_LEGACY_OBJECTID_RE = re.compile(r'^[0-9a-fA-F]{24}$')


def to_uuid(val) -> uuid.UUID:
    """Coerce *val* to a :class:`uuid.UUID`.

    * Accepts :class:`uuid.UUID` (returned as-is).
    * Accepts a UUID string in any of the canonical 36/32-char layouts.
    * Rejects legacy 24-hex Mongo ObjectId strings — there is no data to
      preserve after the Postgres cutover; callers that still hand us a
      24-hex id are pointing at deleted rows.

    Raises ``ValueError`` on any other input.
    """
    if isinstance(val, uuid.UUID):
        return val
    if val is None:
        raise ValueError('id is required')
    if isinstance(val, str):
        s = val.strip()
        if _LEGACY_OBJECTID_RE.match(s):
            raise ValueError(
                'legacy ObjectId not supported after PG cutover; '
                'pass a UUID instead'
            )
        return uuid.UUID(s)
    raise ValueError(f'cannot coerce {type(val).__name__} to UUID')


def maybe_to_uuid(val) -> uuid.UUID | None:
    """Like :func:`to_uuid` but returns ``None`` for ``None`` / empty input."""
    if val is None:
        return None
    if isinstance(val, str) and not val.strip():
        return None
    return to_uuid(val)


def is_valid_id(val) -> bool:
    """True iff ``val`` parses as a UUID. Used in route argument validation
    in place of the legacy ``ObjectId.is_valid`` predicate.
    """
    try:
        to_uuid(val)
        return True
    except (ValueError, TypeError):
        return False
