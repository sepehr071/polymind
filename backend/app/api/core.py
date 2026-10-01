"""Application core for the FastAPI app.

Binds the SQLAlchemy engine and exposes a tiny Flask-free ``app_core`` facade
(aliased ``flask_core`` for the existing call sites + the test harness) providing
the only two things the API layer ever used the old Flask app for:

* ``.config``        → the ``settings`` mapping (app/settings.py)
* ``.app_context()`` → ``db.session_scope()`` (a contextvar-scoped DB session)

Flask has been removed; there is no ``create_app`` Flask factory anymore.
"""
from __future__ import annotations

from app.extensions import db
from app.settings import settings

# Bind the engine once at import. create_engine is lazy (no connection until the
# first query), so this does not require a live Postgres at import time.
db.configure(settings["SQLALCHEMY_DATABASE_URI"], settings.get("SQLALCHEMY_ENGINE_OPTIONS"))


class _AppCore:
    """Flask-free facade: ``.config`` → settings, ``.app_context()`` → DB scope.

    Kept so the ~15 modules + test fixtures that do ``flask_core.app_context()``
    / ``flask_core.config[...]`` work unchanged after Flask's removal.
    """

    config = settings

    @staticmethod
    def app_context():
        return db.session_scope()


app_core = _AppCore()
flask_core = app_core  # back-compat name for existing imports + tests/api/conftest

__all__ = ["db", "settings", "app_core", "flask_core"]
