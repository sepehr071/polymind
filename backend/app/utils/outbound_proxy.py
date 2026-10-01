"""Outbound HTTP proxy for Iran-VPS-blocked hosts.

When the backend runs on an Iran VPS that can't reach `openrouter.ai` or
`api.elevenlabs.io` directly, ops front us with an outbound proxy on an
out-of-Iran host. Contract:

    Backend hits  {OUTBOUND_PROXY_URL}<orig-path>?<orig-query>
    Headers:      Host:          <orig-hostname>      (host-based routing key)
                  X-Proxy-Key:   <OUTBOUND_PROXY_KEY> (only when set)
                  Authorization: ...                  (untouched, passed through)
    Proxy then forwards to https://<Host><orig-path>?<orig-query>.

Env unset => `rewrite()` is identity, no headers injected. Lets dev/CI
outside Iran hit the real hosts unchanged.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit


def _proxy_cfg() -> tuple[str | None, str | None]:
    return os.environ.get('OUTBOUND_PROXY_URL'), os.environ.get('OUTBOUND_PROXY_KEY')


def proxy_enabled() -> bool:
    return bool(_proxy_cfg()[0])


def rewrite(url: str) -> tuple[str, dict[str, str]]:
    """Return (effective_url, extra_headers).

    Proxy disabled => (url, {}). Proxy enabled => swap scheme+netloc to the
    proxy, preserve path+query, and emit a `Host` header set to the original
    target so the proxy can host-route. `X-Proxy-Key` only when configured.
    requests/httpx both honor an explicit Host header while connecting to the
    proxy address.
    """
    proxy, key = _proxy_cfg()
    if not proxy:
        return url, {}

    p = urlsplit(url)
    pp = urlsplit(proxy.rstrip('/'))
    effective = urlunsplit((pp.scheme, pp.netloc, p.path, p.query, ''))
    headers = {'Host': p.hostname or ''}
    if key:
        headers['X-Proxy-Key'] = key
    return effective, headers
