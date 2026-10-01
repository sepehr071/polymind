"""The ``app`` package — the Polymind backend (importable as ``app``).

Flask has been removed: the FastAPI app (``app.asgi:app``) is the sole server.
``create_app()`` is kept ONLY as a thin compatibility shim returning the
Flask-free app core (app/api/core.py) so the dev scripts that do
``app = create_app(); with app.app_context(): ...`` keep working unchanged.
"""


def create_app(*args, **kwargs):
    """Return the Flask-free app core (see app/api/core.py).

    Positional/keyword args (e.g. the old ``create_app(get_config())``) are
    accepted and ignored for back-compat. The returned object exposes
    ``.app_context()`` (a DB-session scope) and ``.config`` (settings).
    """
    from app.api.core import app_core

    return app_core
