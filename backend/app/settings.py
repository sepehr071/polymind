"""Flask-free application settings — replaces ``current_app.config`` /
``flask_core.config`` for the services + API layer.

Backed by the active ``Config`` class (``app.config``), whose UPPERCASE class
attributes are read from ``os.environ`` at class-definition time — exactly the
values Flask's ``app.config.from_object(Config)`` exposed. So
``settings.get('KEY', default)`` is a drop-in for the old
``current_app.config.get('KEY', default)`` and ``settings['KEY']`` for
``current_app.config['KEY']``.
"""
from __future__ import annotations

from app.config import Config


class _Settings:
    """Mutable mapping view over a Config class (attribute-backed).

    Reads fall through to the Config class attributes; writes land in an instance
    override dict that takes precedence — so it behaves like Flask's mutable
    ``app.config`` dict (tests + code that set/restore a key, e.g. UPLOAD_FOLDER,
    keep working) without mutating the shared Config class.
    """

    def __init__(self, cfg):
        self._cfg = cfg
        self._overrides = {}

    def get(self, key, default=None):
        if key in self._overrides:
            return self._overrides[key]
        return getattr(self._cfg, key, default)

    def __getitem__(self, key):
        if key in self._overrides:
            return self._overrides[key]
        try:
            return getattr(self._cfg, key)
        except AttributeError as exc:
            raise KeyError(key) from exc

    def __setitem__(self, key, value):
        self._overrides[key] = value

    def __delitem__(self, key):
        self._overrides.pop(key, None)

    def __contains__(self, key):
        return key in self._overrides or hasattr(self._cfg, key)


# Single process-wide instance. (The prod-vs-dev Config selection is reconciled
# when the Flask app factory is removed in the demolition phase; the keys the
# services read are identical across Config subclasses.)
settings = _Settings(Config)

__all__ = ["settings"]
