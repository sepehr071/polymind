"""Platform-level settings — feature flags + holding-credit pool.

Phase 4D: PG-backed via ORM ``PlatformSetting``. The Mongo singleton-doc
shape (one row at ``_id='singleton'``) is fanned out across multiple
TEXT-keyed rows in PG:
    key='features'                    -> value = {arena: bool, ...}
    key='holding_credits_topups_usd'  -> value = {'amount': float}

The legacy ``PlatformSettingsModel.get()`` still returns ONE merged dict
(``{_id:'singleton', features, holding_credits_topups_usd, ...}``) so
routes/utils that read it don't need to change.
"""

import copy
import os
import threading
import time
import uuid
from datetime import datetime, timezone


DEFAULT_FEATURES = {
    'arena': False,
    'debate': False,
    'image_studio': True,
    'workflow': False,
    'knowledge': True,
    'automate_agent': False,
    'meetings': True,
    'code_canvas_run': True,
    'data_analyzer': True,
    'payroll': True,
    'presentations': False,   # enable from /admin/features once ready
    'agent': True,            # all-in-one router agent at /agent
    'ocr_assistant': True,    # /ocr document extract (Gemini Flash Lite)
    'email_writer': True,     # /email-writer formal letters
    'cv_checker': True,       # /cv-checker HR screen + improve
    'research_assistant': True,  # /research deep research
    'contract_reviewer': False,  # /contracts — enable after smoke
    'tender_assistant': False,   # /tenders — enable after smoke
    'shop_assistant': False,     # /shop Digikala+Technolife procurement — enable after smoke
    'billing_enforcement': False,
}

SINGLETON_ID = 'singleton'

# Internal PG keys.
_KEY_FEATURES = 'features'
_KEY_CREDITS = 'holding_credits_topups_usd'
_KEY_TRANSFERRED = 'holding_credits_transferred_usd'
_KEY_MARKUP = 'markup_pct'
_KEY_CREDITS_PER_USD = 'credits_per_usd'

# Billing knobs (profit redesign 2026-06-29). ``markup_pct`` is the flat margin
# applied to upstream OpenRouter cost in OpenRouterService._record_usage
# (price = upstream × (1 + markup_pct)); default 0.0 = no behavior change until
# the CEO sets it. ``credits_per_usd`` scales the user-facing "Polymind Credits"
# display unit (credits = round(price × credits_per_usd)); default 1000 →
# $0.001 = 1 credit. Both bounds-guarded against a fat-finger.
_DEFAULT_MARKUP_PCT = 0.0
_DEFAULT_CREDITS_PER_USD = 1000.0
_MARKUP_PCT_MAX = 5.0
_CREDITS_PER_USD_MAX = 1_000_000_000.0

# ----------------------------------------------------------------------
# Process-local TTL cache for the features dict.
#
# ``get_features()`` is read on EVERY LLM call (spend_gate.gate), on the
# feature_dep route gate, and from workspaces.py — a DB read on the hot
# path. We cache the features dict per-worker for ``FEATURES_CACHE_TTL``
# seconds (monotonic clock, immune to wall-clock jumps/NTP skew).
#
# Cross-worker flip latency: a feature flip invalidates the cache only on
# the worker that performed the write. Other gunicorn workers keep serving
# their cached copy until their own entry expires — so a flip is visible
# fleet-wide within ≤ FEATURES_CACHE_TTL seconds. Acceptable for the
# dark-launched flags this gates; do NOT lower TTL toward 0 to "fix" this.
#
# Thread-safety: ``get_features()`` hands out a deepcopy, never the cached
# reference. Callers such as ``set_feature`` mutate the returned dict in
# place (``features[name] = enabled``); handing out the live reference
# would corrupt the cache for every other thread.
# ----------------------------------------------------------------------
_FEATURES_CACHE_TTL = int(os.environ.get('FEATURES_CACHE_TTL', '5'))
_features_cache: dict = {'value': None, 'expires': 0.0}
_features_cache_lock = threading.Lock()


def _invalidate_features_cache() -> None:
    """Drop the cached features dict so the next read hits the DB.

    Called on every features write path; also exposed for tests to reset
    state between cases.
    """
    with _features_cache_lock:
        _features_cache['value'] = None
        _features_cache['expires'] = 0.0


# Process-local TTL cache for the billing knobs (markup_pct + credits_per_usd),
# mirroring the features cache: ``get_credits_per_usd`` runs on every
# user-facing usage read and ``get_markup_pct`` on every billable LLM call.
_billing_cache: dict = {'value': None, 'expires': 0.0}
_billing_cache_lock = threading.Lock()


def _invalidate_billing_cache() -> None:
    """Drop the cached billing knobs so the next read hits the DB."""
    with _billing_cache_lock:
        _billing_cache['value'] = None
        _billing_cache['expires'] = 0.0


def _to_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except Exception:
        return None


class PlatformSettingsModel:
    collection_name = 'platform_settings'

    @staticmethod
    def ensure_singleton():
        """Seed the ``features`` row with defaults if missing. Idempotent."""
        now = datetime.now(timezone.utc)
        stmt = pg_insert(PlatformSetting).values(
            key=_KEY_FEATURES,
            value=dict(DEFAULT_FEATURES),
            updated_at=now,
            updated_by_user_id=None,
        ).on_conflict_do_nothing(index_elements=['key'])
        db.session.execute(stmt)
        # Seed credits row if missing.
        stmt2 = pg_insert(PlatformSetting).values(
            key=_KEY_CREDITS,
            value={'amount': 0.0},
            updated_at=now,
            updated_by_user_id=None,
        ).on_conflict_do_nothing(index_elements=['key'])
        db.session.execute(stmt2)
        # Seed billing knobs if missing.
        stmt3 = pg_insert(PlatformSetting).values(
            key=_KEY_MARKUP,
            value={'value': _DEFAULT_MARKUP_PCT},
            updated_at=now,
            updated_by_user_id=None,
        ).on_conflict_do_nothing(index_elements=['key'])
        db.session.execute(stmt3)
        stmt4 = pg_insert(PlatformSetting).values(
            key=_KEY_CREDITS_PER_USD,
            value={'value': _DEFAULT_CREDITS_PER_USD},
            updated_at=now,
            updated_by_user_id=None,
        ).on_conflict_do_nothing(index_elements=['key'])
        db.session.execute(stmt4)
        db.session.commit()

    @staticmethod
    def get():
        """Merged-singleton view. Always returns the same dict shape."""
        rows = db.session.execute(
            select(PlatformSetting).where(
                PlatformSetting.key.in_([_KEY_FEATURES, _KEY_CREDITS, _KEY_TRANSFERRED])
            )
        ).scalars().all()
        features = dict(DEFAULT_FEATURES)
        credits = 0.0
        transferred = 0.0
        updated_at = None
        updated_by = None
        for r in rows:
            if r.key == _KEY_FEATURES:
                stored = r.value if isinstance(r.value, dict) else {}
                features.update(stored)
                if r.updated_at and (updated_at is None or r.updated_at > updated_at):
                    updated_at = r.updated_at
                    updated_by = r.updated_by_user_id
            elif r.key == _KEY_CREDITS:
                val = r.value or {}
                credits = float(val.get('amount') or 0)
            elif r.key == _KEY_TRANSFERRED:
                val = r.value or {}
                transferred = float(val.get('amount') or 0)
        return {
            '_id': SINGLETON_ID,
            'features': features,
            'updated_at': updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
            'updated_by': str(updated_by) if updated_by else None,
            'holding_credits_topups_usd': credits,
            'holding_credits_transferred_usd': transferred,
        }

    @staticmethod
    def get_features() -> dict:
        """Return the features dict alone (Phase-4 plan helper).

        Served from a process-local TTL cache (see module-level cache notes).
        Always returns a fresh deepcopy so a caller mutating the result
        cannot corrupt the shared cache.
        """
        now = time.monotonic()
        with _features_cache_lock:
            cached = _features_cache['value']
            if cached is not None and now < _features_cache['expires']:
                return copy.deepcopy(cached)

        # Miss / expired — read from DB outside the lock (the DB read may
        # block; we don't want to serialize every worker thread on it).
        features = PlatformSettingsModel.get().get('features', dict(DEFAULT_FEATURES))

        with _features_cache_lock:
            _features_cache['value'] = features
            _features_cache['expires'] = time.monotonic() + _FEATURES_CACHE_TTL
        return copy.deepcopy(features)

    @staticmethod
    def set_features(features_dict: dict, by=None) -> dict:
        """Replace the whole features row. Validates against DEFAULT_FEATURES."""
        if not isinstance(features_dict, dict):
            raise ValueError("features_dict must be a dict")
        unknown = [k for k in features_dict.keys() if k not in DEFAULT_FEATURES]
        if unknown:
            raise ValueError(f"Unknown feature keys: {unknown}")
        for k, v in features_dict.items():
            if not isinstance(v, bool):
                raise ValueError(f"Feature {k!r} value must be bool")
        merged = {**DEFAULT_FEATURES}
        # Merge with existing so partial updates don't wipe other flags.
        existing = PlatformSettingsModel.get_features()
        merged.update(existing)
        merged.update(features_dict)
        return PlatformSettingsModel._write_features(merged, by)

    @staticmethod
    def _write_features(features: dict, by) -> dict:
        now = datetime.now(timezone.utc)
        stmt = pg_insert(PlatformSetting).values(
            key=_KEY_FEATURES,
            value=features,
            updated_at=now,
            updated_by_user_id=_to_uuid(by),
        ).on_conflict_do_update(
            index_elements=['key'],
            set_={
                'value': features,
                'updated_at': now,
                'updated_by_user_id': _to_uuid(by),
            },
        )
        db.session.execute(stmt)
        db.session.commit()
        # Single chokepoint for every features write (set_feature, bulk_set,
        # set_features all route here) — invalidate so this worker sees the
        # flip immediately; other workers see it within ≤ TTL.
        _invalidate_features_cache()
        return PlatformSettingsModel.get()

    @staticmethod
    def set_feature(name: str, enabled: bool, by):
        if name not in DEFAULT_FEATURES:
            raise ValueError(
                f"Unknown feature: {name!r}. Must be one of {sorted(DEFAULT_FEATURES.keys())}"
            )
        if not isinstance(enabled, bool):
            raise ValueError(f"`enabled` must be bool, got {type(enabled).__name__}")
        features = PlatformSettingsModel.get_features()
        features[name] = enabled
        return PlatformSettingsModel._write_features(features, by)

    @staticmethod
    def bulk_set(features_dict: dict, by):
        if not isinstance(features_dict, dict) or not features_dict:
            raise ValueError("features_dict must be a non-empty dict")
        unknown = [k for k in features_dict.keys() if k not in DEFAULT_FEATURES]
        if unknown:
            raise ValueError(f"Unknown feature keys: {unknown}")
        for k, v in features_dict.items():
            if not isinstance(v, bool):
                raise ValueError(f"Feature {k!r} value must be bool, got {type(v).__name__}")
        features = PlatformSettingsModel.get_features()
        features.update(features_dict)
        return PlatformSettingsModel._write_features(features, by)

    # ------------------------------------------------------------------
    # Billing knobs — markup_pct + credits_per_usd (profit redesign).
    # ------------------------------------------------------------------
    @staticmethod
    def get_billing_config() -> dict:
        """``{'markup_pct': float, 'credits_per_usd': float}`` — TTL-cached.

        Falls back to the module defaults for any missing/corrupt row, so a
        fresh DB (pre-seed) still reads markup 0 / credits_per_usd 1000.
        """
        now = time.monotonic()
        with _billing_cache_lock:
            cached = _billing_cache['value']
            if cached is not None and now < _billing_cache['expires']:
                return dict(cached)

        rows = db.session.execute(
            select(PlatformSetting).where(
                PlatformSetting.key.in_([_KEY_MARKUP, _KEY_CREDITS_PER_USD])
            )
        ).scalars().all()
        cfg = {
            'markup_pct': _DEFAULT_MARKUP_PCT,
            'credits_per_usd': _DEFAULT_CREDITS_PER_USD,
        }
        for r in rows:
            val = r.value if isinstance(r.value, dict) else {}
            raw = val.get('value')
            if raw is None:
                continue
            try:
                num = float(raw)
            except (TypeError, ValueError):
                continue
            if r.key == _KEY_MARKUP and num >= 0:
                cfg['markup_pct'] = num
            elif r.key == _KEY_CREDITS_PER_USD and num > 0:
                cfg['credits_per_usd'] = num

        with _billing_cache_lock:
            _billing_cache['value'] = cfg
            _billing_cache['expires'] = time.monotonic() + _FEATURES_CACHE_TTL
        return dict(cfg)

    @staticmethod
    def get_markup_pct() -> float:
        return PlatformSettingsModel.get_billing_config()['markup_pct']

    @staticmethod
    def get_credits_per_usd() -> float:
        return PlatformSettingsModel.get_billing_config()['credits_per_usd']

    @staticmethod
    def _write_scalar(key: str, value: float, by) -> None:
        now = datetime.now(timezone.utc)
        stmt = pg_insert(PlatformSetting).values(
            key=key,
            value={'value': value},
            updated_at=now,
            updated_by_user_id=_to_uuid(by),
        ).on_conflict_do_update(
            index_elements=['key'],
            set_={
                'value': {'value': value},
                'updated_at': now,
                'updated_by_user_id': _to_uuid(by),
            },
        )
        db.session.execute(stmt)
        db.session.commit()
        _invalidate_billing_cache()

    @staticmethod
    def set_markup_pct(value, by) -> dict:
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError("markup_pct must be a number")
        if not (0.0 <= v <= _MARKUP_PCT_MAX):
            raise ValueError(f"markup_pct must be between 0 and {_MARKUP_PCT_MAX}")
        PlatformSettingsModel._write_scalar(_KEY_MARKUP, v, by)
        return PlatformSettingsModel.get_billing_config()

    @staticmethod
    def set_credits_per_usd(value, by) -> dict:
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError("credits_per_usd must be a number")
        if not (0 < v <= _CREDITS_PER_USD_MAX):
            raise ValueError(
                f"credits_per_usd must be between 0 (exclusive) and {_CREDITS_PER_USD_MAX}"
            )
        PlatformSettingsModel._write_scalar(_KEY_CREDITS_PER_USD, v, by)
        return PlatformSettingsModel.get_billing_config()

    @staticmethod
    def set_billing_config(cfg: dict, by) -> dict:
        """Partial update of the two knobs. Each is validated independently."""
        if not isinstance(cfg, dict) or not cfg:
            raise ValueError("cfg must be a non-empty dict")
        if cfg.get('markup_pct') is not None:
            PlatformSettingsModel.set_markup_pct(cfg['markup_pct'], by)
        if cfg.get('credits_per_usd') is not None:
            PlatformSettingsModel.set_credits_per_usd(cfg['credits_per_usd'], by)
        return PlatformSettingsModel.get_billing_config()

    @staticmethod
    def add_holding_credits(amount_usd: float, by) -> dict:
        """Increment the holding-level credit pool. Returns merged singleton view."""
        now = datetime.now(timezone.utc)
        row = db.session.execute(
            select(PlatformSetting).where(PlatformSetting.key == _KEY_CREDITS)
        ).scalar_one_or_none()
        current = float((row.value or {}).get('amount') or 0) if row else 0.0
        new_total = current + float(amount_usd or 0)
        stmt = pg_insert(PlatformSetting).values(
            key=_KEY_CREDITS,
            value={'amount': new_total},
            updated_at=now,
            updated_by_user_id=_to_uuid(by),
        ).on_conflict_do_update(
            index_elements=['key'],
            set_={
                'value': {'amount': new_total},
                'updated_at': now,
                'updated_by_user_id': _to_uuid(by),
            },
        )
        db.session.execute(stmt)
        db.session.commit()
        return PlatformSettingsModel.get()

    @staticmethod
    def add_holding_transferred(amount_usd: float, by, commit: bool = True,
                                guarded: bool = False) -> dict | bool:
        """Increment the holding-credit *transferred* counter (credits moved out
        of the pool into a company wallet). Mirrors ``add_holding_credits`` but
        tracks a separate, never-decrementing total so the transferable pool
        remaining = ``topups − transferred``.

        ``commit=False`` lets a caller fold this upsert into a larger atomic
        transaction (e.g. the holding→company transfer in ``charge_company``).

        The increment is done atomically AT THE SQL LEVEL (a JSONB expression
        that reads the row's own current ``amount``), NOT read-modify-write in
        Python — two concurrent transfers can no longer clobber each other's
        increment (lost update). Whoever commits second adds to the first's
        already-committed value rather than overwriting a stale Python read.

        ``guarded=True`` ALSO serializes the read-check-act against the pool
        ceiling so the pool can never be over-drawn below zero by concurrent
        transfers (TOCTOU): the upsert only fires when
        ``transferred + amount <= topups`` (re-evaluated against the LIVE rows
        under PG's row lock on the conflicting transferred row). Returns
        ``True`` when a row was written, ``False`` when the guard rejected it
        (caller raises the insufficient-credits 402). With ``guarded=False``
        (the default) the unconditional upsert runs and the merged singleton
        view is returned, preserving the legacy contract.
        """
        now = datetime.now(timezone.utc)
        amount = float(amount_usd or 0)

        if guarded:
            # Single atomic statement covering BOTH the first-transfer INSERT and
            # the subsequent ON-CONFLICT UPDATE, each gated on the LIVE topups
            # row so ``transferred + amount`` can never exceed ``topups``:
            #   * INSERT path: the SELECT source yields a row only when the guard
            #     holds (so an over-draw inserts nothing -> rowcount 0).
            #   * UPDATE path: PG row-locks the conflicting transferred row, the
            #     WHERE re-reads the committed topups+transferred values, so two
            #     concurrent transfers serialize (the 2nd sees the 1st's commit).
            stmt = _sql_text_orm(
                """
                INSERT INTO platform_settings (key, value, updated_at, updated_by_user_id)
                SELECT :tkey,
                       jsonb_build_object(
                           'amount',
                           coalesce((tr.value->>'amount')::numeric, 0) + :amt),
                       :now, :by
                FROM (SELECT value FROM platform_settings WHERE key = :ckey) AS tp
                LEFT JOIN (SELECT value FROM platform_settings WHERE key = :tkey) AS tr
                       ON true
                WHERE coalesce((tr.value->>'amount')::numeric, 0) + :amt
                      <= coalesce((tp.value->>'amount')::numeric, 0)
                ON CONFLICT (key) DO UPDATE
                SET value = jsonb_build_object(
                        'amount',
                        coalesce((platform_settings.value->>'amount')::numeric, 0) + :amt),
                    updated_at = :now,
                    updated_by_user_id = :by
                WHERE coalesce((platform_settings.value->>'amount')::numeric, 0) + :amt
                      <= (SELECT coalesce((value->>'amount')::numeric, 0)
                          FROM platform_settings WHERE key = :ckey)
                """
            ).bindparams(
                tkey=_KEY_TRANSFERRED,
                ckey=_KEY_CREDITS,
                amt=amount,
                now=now,
                by=_to_uuid(by),
            )
            result = db.session.execute(stmt)
            wrote = (result.rowcount or 0) > 0
            if not wrote:
                # Over-draw: nothing was written. Roll back so the caller's
                # surrounding transaction (ledger/balance writes it deferred)
                # is discarded and no pooled connection lingers 'idle in
                # transaction'.
                db.session.rollback()
                return False
            if commit:
                db.session.commit()
            return True

        # On INSERT (first transfer ever) the row is seeded with {'amount': N};
        # on CONFLICT the set_ reads the LIVE stored value via the table-name
        # reference (``platform_settings.value``), so the add is serialized by PG.
        increment_expr = _sql_text_orm(
            "jsonb_build_object('amount', "
            "coalesce((platform_settings.value->>'amount')::numeric, 0) + :amt)"
        ).bindparams(amt=amount)
        stmt = pg_insert(PlatformSetting).values(
            key=_KEY_TRANSFERRED,
            value={'amount': amount},
            updated_at=now,
            updated_by_user_id=_to_uuid(by),
        ).on_conflict_do_update(
            index_elements=['key'],
            set_={
                'value': increment_expr,
                'updated_at': now,
                'updated_by_user_id': _to_uuid(by),
            },
        )
        db.session.execute(stmt)
        if commit:
            db.session.commit()
        return PlatformSettingsModel.get()


# ======================================================================
# Phase 3 — SQLAlchemy 2.0 ORM model
# ======================================================================

import uuid as _uuid_orm
from datetime import datetime as _dt_orm

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Text,
    text as _sql_text_orm,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class PlatformSetting(db.Model, SerializableMixin):
    __tablename__ = 'platform_settings'

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=_sql_text_orm("'{}'::jsonb")
    )
    updated_at: Mapped[_dt_orm | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Holds the acting super-admin's ``users.id``. The FK pointed at
    # ``platform_admins.id`` between migrations 0002 and 0017; the platform-admin
    # principal merge (0017) retargets it back to ``users.id``.
    updated_by_user_id: Mapped[_uuid_orm.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )

    def to_dict(self) -> dict:  # override — there is no `id`, use `key`
        out: dict = {}
        for col in self.__table__.columns:
            if col.name in self._serialize_exclude:
                continue
            v = getattr(self, col.name)
            if isinstance(v, _uuid_orm.UUID):
                v = str(v)
            elif isinstance(v, _dt_orm):
                v = v.isoformat()
            out[col.name] = v
        out['_id'] = self.key
        return out
