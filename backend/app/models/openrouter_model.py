"""OpenRouter model catalog cache.

Phase 4D: PG-backed via ORM ``OpenRouterModel``. PK is the model slug (TEXT) —
no UUID. ``_id`` alias on the serialized dict equals the slug for FE compat.
"""

from datetime import datetime, timezone


# Fields the bulk-upsert is allowed to touch — anything else is dropped.
_ALLOWED_UPSERT_FIELDS = {
    'id', 'display_name', 'context_length', 'architecture', 'pricing',
    'supported_parameters', 'raw', 'expiration_date',
}


class OpenRouterModelDoc:
    """Façade on top of ``OpenRouterModel`` ORM rows."""

    collection_name = 'openrouter_models'

    @staticmethod
    def _coerce_pricing(pricing: dict) -> dict:
        """OpenRouter returns pricing values as strings — coerce to float."""
        if not pricing:
            return {}
        result = {}
        for key, val in pricing.items():
            try:
                result[key] = float(val)
            except (TypeError, ValueError):
                result[key] = 0.0
        return result

    @staticmethod
    def upsert_many(items: list) -> int:
        """Bulk upsert. Returns the count of rows touched."""
        if not items:
            return 0
        now = datetime.now(timezone.utc)
        values: list[dict] = []
        for item in items:
            model_id = item.get('id')
            if not model_id:
                continue
            arch_raw = item.get('architecture', {}) or {}
            input_modalities = arch_raw.get('input_modalities')
            if not input_modalities and arch_raw.get('modality'):
                # Legacy 'modality' format like 'text+image->text'.
                input_modalities = arch_raw.get('modality').split('+text')[0].split('+')
            if not input_modalities:
                input_modalities = ['text']
            architecture = {
                'input_modalities': input_modalities,
                'output_modalities': arch_raw.get('output_modalities', ['text']),
            }
            pricing = OpenRouterModelDoc._coerce_pricing(item.get('pricing', {}))
            row = {
                'id': model_id,
                'display_name': item.get('name') or item.get('display_name') or model_id,
                'context_length': item.get('context_length'),
                'architecture': architecture,
                'pricing': pricing,
                'supported_parameters': item.get('supported_parameters', []) or [],
                'raw': item,
                'expiration_date': item.get('expiration_date'),
                'last_synced_at': now,
            }
            # Drop anything outside the allow-list (defence-in-depth).
            row = {k: v for k, v in row.items() if k in _ALLOWED_UPSERT_FIELDS or k == 'last_synced_at'}
            values.append(row)

        if not values:
            return 0

        stmt = pg_insert(OpenRouterModel).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=['id'],
            set_={
                'display_name': stmt.excluded.display_name,
                'context_length': stmt.excluded.context_length,
                'architecture': stmt.excluded.architecture,
                'pricing': stmt.excluded.pricing,
                'supported_parameters': stmt.excluded.supported_parameters,
                'raw': stmt.excluded.raw,
                'expiration_date': stmt.excluded.expiration_date,
                'last_synced_at': stmt.excluded.last_synced_at,
            },
        )
        db.session.execute(stmt)
        db.session.commit()
        return len(values)

    @staticmethod
    def find_by_modality(input_modalities=None, output_modalities=None) -> list:
        """Models that contain ALL listed modalities (JSONB @> contains)."""
        stmt = select(OpenRouterModel)
        if input_modalities:
            stmt = stmt.where(
                OpenRouterModel.architecture['input_modalities'].contains(input_modalities)
            )
        if output_modalities:
            stmt = stmt.where(
                OpenRouterModel.architecture['output_modalities'].contains(output_modalities)
            )
        rows = db.session.execute(stmt).scalars().all()
        return [_orm_to_dict(r) for r in rows]

    @staticmethod
    def find_by_capability(supported_parameter: str) -> list:
        stmt = select(OpenRouterModel).where(
            OpenRouterModel.supported_parameters.contains([supported_parameter])
        )
        rows = db.session.execute(stmt).scalars().all()
        return [_orm_to_dict(r) for r in rows]

    @staticmethod
    def get_by_id(model_id: str) -> dict | None:
        if not model_id:
            return None
        row = db.session.get(OpenRouterModel, model_id)
        return _orm_to_dict(row) if row else None

    @staticmethod
    def get_last_sync_at():
        """Return the latest last_synced_at across the table, or None if empty."""
        return db.session.execute(
            select(func.max(OpenRouterModel.last_synced_at))
        ).scalar()

    @staticmethod
    def count() -> int:
        return int(
            db.session.execute(select(func.count(OpenRouterModel.id))).scalar() or 0
        )

    @staticmethod
    def find_all(skip: int = 0, limit: int = 500,
                 sort_by: str = 'created', sort_dir: int = -1) -> list:
        """Paginated list. ``sort_by`` legacy values: 'created' (no col on PG) →
        defaults to ``last_synced_at`` descending."""
        col_map = {
            'created': OpenRouterModel.last_synced_at,
            'last_synced_at': OpenRouterModel.last_synced_at,
            'context_length': OpenRouterModel.context_length,
            'id': OpenRouterModel.id,
        }
        sort_col = col_map.get(sort_by, OpenRouterModel.last_synced_at)
        ordering = sort_col.desc() if sort_dir == -1 else sort_col.asc()
        rows = db.session.execute(
            select(OpenRouterModel).order_by(ordering).offset(skip).limit(limit)
        ).scalars().all()
        return [_orm_to_dict(r) for r in rows]


def _orm_to_dict(row: 'OpenRouterModel') -> dict:
    out = row.to_dict()
    # Legacy alias: ``name`` field (callers may still expect it).
    out['name'] = row.display_name
    # ``_id`` from SerializableMixin is the slug — fine. Also expose `created`
    # alias for legacy sort/list templates that read it.
    out.setdefault('created', None)
    return out


# ======================================================================
# Phase 3 — SQLAlchemy 2.0 ORM model
# ======================================================================

from datetime import datetime as _dt_orm, date as _date_orm

from sqlalchemy import (
    Date,
    DateTime,
    Index,
    Integer,
    Text,
    text as _sql_text_orm,
    select,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models._base import SerializableMixin


class OpenRouterModel(db.Model, SerializableMixin):
    __tablename__ = 'openrouter_models'

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    architecture: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default=_sql_text_orm("'{}'::jsonb")
    )
    pricing: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default=_sql_text_orm("'{}'::jsonb")
    )
    supported_parameters: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, server_default=_sql_text_orm("'[]'::jsonb")
    )
    raw: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default=_sql_text_orm("'{}'::jsonb")
    )
    expiration_date: Mapped[_date_orm | None] = mapped_column(Date, nullable=True)
    last_synced_at: Mapped[_dt_orm | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            'ix_openrouter_models_output_modalities',
            _sql_text_orm("(architecture->'output_modalities')"),
            postgresql_using='gin',
        ),
        Index(
            'ix_openrouter_models_input_modalities',
            _sql_text_orm("(architecture->'input_modalities')"),
            postgresql_using='gin',
        ),
        Index('ix_openrouter_models_expiration', 'expiration_date'),
        Index('ix_openrouter_models_last_synced', 'last_synced_at'),
    )
