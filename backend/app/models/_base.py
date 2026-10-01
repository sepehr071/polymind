from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Standalone declarative base. Phase 3 ORM models subclass both
    Flask-SQLAlchemy's ``db.Model`` and ``SerializableMixin`` so they bind to
    ``db.session`` while emitting the Mongo-compatible ``_id`` alias.
    """

    pass


class SerializableMixin:
    """Emit an ``_id`` alias on every payload so the frontend (built against
    the Mongo JSON shape) stays untouched after the Postgres cutover.

    Subclasses may set ``_serialize_exclude`` to skip sensitive columns
    (e.g. ``password_hash``) from the dict output.
    """

    _serialize_exclude: tuple = ()

    def to_dict(self) -> dict:
        out: dict = {}
        for col in self.__table__.columns:
            if col.name in self._serialize_exclude:
                continue
            v = getattr(self, col.name)
            if isinstance(v, uuid.UUID):
                v = str(v)
            elif isinstance(v, datetime):
                v = v.isoformat()
            out[col.name] = v
        pk = getattr(self, 'id', None)
        if pk is not None:
            out['_id'] = str(pk)
        return out
