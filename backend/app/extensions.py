"""Flask-free application extensions.

``db`` is a minimal stand-in for the slice of flask_sqlalchemy this app uses
(db.Model, db.session, db.metadata/engine, and db.<Name> delegation to
sqlalchemy/sqlalchemy.orm). The SQLAlchemy session is scoped to a contextvar
token rather than a Flask app context: the FastAPI request dependency
(app/api/deps.flask_ctx) and ``db.session_scope()`` set a fresh token; anyio
worker threads inherit the request task's token via the copied contextvars
Context, so one scoped session serves the whole request and is isolated across
requests. A thread with no token set (a raw background thread before it enters
``session_scope``) falls back to its own thread id — never a shared session.

JWT verification/minting is PyJWT (app/api/deps.py + app/api/tokens.py); the old
flask_jwt_extended JWTManager + callbacks are gone.
"""
from __future__ import annotations

import contextlib
import contextvars
import logging
import threading

import sqlalchemy as _sa
from sqlalchemy import create_engine
from sqlalchemy import orm as _orm
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker

_logger = logging.getLogger(__name__)

# Per-request / per-scope DB session key. Default None → _scope_id falls back to
# the current thread id (isolated). Set to a unique object() by flask_ctx (the
# request dependency) and by db.session_scope() (background threads / scripts).
_session_scope: contextvars.ContextVar = contextvars.ContextVar(
    "db_session_scope", default=None
)


class _Model(DeclarativeBase):
    """Declarative base replacing flask_sqlalchemy's ``db.Model``."""

    pass


def _scope_id():
    tok = _session_scope.get()
    return tok if tok is not None else threading.get_ident()


class _SQLAlchemy:
    """Drop-in for the used subset of flask_sqlalchemy's ``SQLAlchemy`` object."""

    Model = _Model

    def __init__(self):
        self._engine = None
        # Match flask_sqlalchemy session defaults (autoflush + expire_on_commit).
        self._factory = sessionmaker(future=True, autoflush=True, expire_on_commit=True)
        self.session = scoped_session(self._factory, scopefunc=_scope_id)

    def configure(self, uri, engine_options=None):
        """Bind the engine. create_engine is lazy (no connection until first
        query), so import/boot stays independent of a live Postgres."""
        self._engine = create_engine(uri, **(engine_options or {}))
        self._factory.configure(bind=self._engine)
        return self._engine

    @property
    def engine(self):
        if self._engine is None:
            raise RuntimeError("db.configure() has not been called — engine is unbound")
        return self._engine

    @property
    def metadata(self):
        return self.Model.metadata

    def create_all(self):
        self.metadata.create_all(self.engine)

    def drop_all(self):
        self.metadata.drop_all(self.engine)

    @contextlib.contextmanager
    def session_scope(self):
        """Open a fresh DB-session scope for the block, then remove the session.

        Use in background threads + anywhere outside the FastAPI request
        dependency (which manages its own scope). Replaces the old
        ``with app.app_context():`` blocks whose only job was scoping db.session.
        """
        token = _session_scope.set(object())
        try:
            yield self.session
        finally:
            self.session.remove()
            _session_scope.reset(token)

    def __getattr__(self, name):
        # db.<Name> falls through to sqlalchemy then sqlalchemy.orm — exactly
        # flask_sqlalchemy's re-export behavior (db.Text, db.Integer, db.or_, ...).
        try:
            return getattr(_sa, name)
        except AttributeError:
            try:
                return getattr(_orm, name)
            except AttributeError:
                raise AttributeError(f"'db' has no attribute {name!r}")


# ``db`` is the canonical SQLAlchemy session for everything: identity, chat,
# workspaces, meetings, DLP, usage logs, audit. Postgres is the sole datastore.
db = _SQLAlchemy()

# Compatibility shim: a few model files still carry orphan
# `from app.extensions import mongo` imports. Importing `None` keeps boot green;
# removed in the Mongo-purge phase.
mongo = None
