"""httpOnly-cookie auth migration — server-half contract tests.

Proves the cookie/CSRF behavior the frontend half relies on:
  - /login sets dev-named auth cookies (HttpOnly, SameSite=Lax, no Secure in
    the non-production test env);
  - a request authenticated by COOKIE ONLY (no Authorization header) resolves
    current_user on a protected route;
  - /refresh from the COOKIE rotates AND omits body tokens (XSS defense), while
    /refresh via header/body still returns body tokens (API-client back-compat);
  - /logout clears the cookies and revokes the tokens;
  - the CSRF middleware blocks a cookie-only mutation lacking X-CSRF-Token, and
    exempts the X-CSRF-Token, the Bearer, and the safe-method cases.

The TestClient keeps a cookie jar (``client.cookies``); ``client`` is
function-scoped so each test starts with an empty jar. We clear it explicitly
where a test needs to send a header WITHOUT the ambient login cookies
interfering (the cookie now takes precedence over the header in current_user).
"""
from app.api.cookies import access_cookie_name, refresh_cookie_name

_ACCESS = access_cookie_name()  # 'access_token' in the test env (FLASK_ENV != production)
_REFRESH = refresh_cookie_name()


def _login(client):
    return client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    })


# ---------------------------------------------------------------------------
# /login sets the auth cookies with the right attributes (dev env).
# ---------------------------------------------------------------------------
def test_login_sets_auth_cookies_dev_attrs(client, test_user):
    resp = _login(client)
    assert resp.status_code == 200, resp.text

    # Inspect the raw Set-Cookie headers for the attribute flags.
    set_cookie_blob = " ".join(
        v for k, v in resp.headers.items() if k.lower() == "set-cookie"
    )
    # In the test env FLASK_ENV is NOT production -> dev names, no Secure.
    assert _ACCESS == "access_token"
    assert _REFRESH == "refresh_token"
    assert "access_token=" in set_cookie_blob
    assert "refresh_token=" in set_cookie_blob
    assert "HttpOnly" in set_cookie_blob
    assert "samesite=lax" in set_cookie_blob.lower()
    assert "Path=/" in set_cookie_blob or "path=/" in set_cookie_blob.lower()
    assert "Secure" not in set_cookie_blob  # dev: no Secure so http localhost works

    # The cookies actually landed in the jar.
    assert client.cookies.get(_ACCESS)
    assert client.cookies.get(_REFRESH)


# ---------------------------------------------------------------------------
# Cookie-only auth resolves current_user on a protected GET (no Authorization).
# ---------------------------------------------------------------------------
def test_cookie_only_authenticates_protected_route(client, test_user):
    _login(client)
    # No Authorization header — the TestClient auto-attaches the access cookie.
    me = client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["id"] == str(test_user["_id"])


# ---------------------------------------------------------------------------
# /refresh from the COOKIE rotates the pair AND omits body tokens.
# ---------------------------------------------------------------------------
def test_refresh_from_cookie_omits_body_tokens(client, test_user):
    _login(client)
    old_access = client.cookies.get(_ACCESS)
    old_refresh = client.cookies.get(_REFRESH)

    # No header/body token -> the refresh cookie is the only credential. A custom
    # header satisfies CSRF (non-GET cookie-auth requires X-CSRF-Token).
    resp = client.post("/api/auth/refresh", headers={"X-CSRF-Token": "1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # XSS defense: cookie-sourced refresh NEVER echoes tokens in JSON.
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert body["token_type"] == "Bearer"

    # New cookies were set (rotation) and the jar updated to the new pair.
    new_access = client.cookies.get(_ACCESS)
    new_refresh = client.cookies.get(_REFRESH)
    assert new_access and new_access != old_access
    assert new_refresh and new_refresh != old_refresh

    # The new access cookie authenticates /me.
    assert client.get("/api/auth/me").status_code == 200

    # The rotated-out refresh token is revoked: replay via header is rejected.
    client.cookies.clear()
    replay = client.post("/api/auth/refresh",
                         headers={"Authorization": f"Bearer {old_refresh}"})
    assert replay.status_code == 401
    assert replay.json()["code"] == "token_revoked"


# ---------------------------------------------------------------------------
# /refresh via header (no cookie) STILL returns body tokens (back-compat).
# ---------------------------------------------------------------------------
def test_refresh_via_header_returns_body_tokens(client, test_user):
    login_body = _login(client).json()
    refresh_token = login_body["refresh_token"]
    # Drop the ambient login cookies so the header is the sole credential.
    client.cookies.clear()

    resp = client.post("/api/auth/refresh",
                       headers={"Authorization": f"Bearer {refresh_token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Header/body path keeps echoing tokens for API clients + tests.
    assert body["access_token"]
    assert body["refresh_token"]


def test_refresh_via_body_returns_body_tokens(client, test_user):
    login_body = _login(client).json()
    refresh_token = login_body["refresh_token"]
    client.cookies.clear()

    # Body-token path: no cookie, no header — refresh_token in JSON body.
    resp = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]


# ---------------------------------------------------------------------------
# /logout clears cookies + revokes the tokens.
# ---------------------------------------------------------------------------
def test_logout_clears_cookies_and_revokes(client, test_user):
    _login(client)
    # Cookie-auth mutation needs the CSRF header.
    logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": "1"})
    assert logout.status_code == 200, logout.text

    # delete_cookie emits Set-Cookie with an expiry in the past -> jar drops them.
    assert not client.cookies.get(_ACCESS)
    assert not client.cookies.get(_REFRESH)

    set_cookie_blob = " ".join(
        v for k, v in logout.headers.items() if k.lower() == "set-cookie"
    )
    assert "access_token=" in set_cookie_blob
    assert "refresh_token=" in set_cookie_blob


# ---------------------------------------------------------------------------
# CSRF middleware predicate matrix.
# ---------------------------------------------------------------------------
def test_csrf_blocks_cookie_only_mutation_without_header(client, test_user):
    _login(client)
    # POST to a protected /api route, cookie-auth, NO X-CSRF-Token -> 403.
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "csrf_failed"
    assert body["status"] == 403


def test_csrf_allows_cookie_mutation_with_header(client, test_user):
    _login(client)
    resp = client.post("/api/auth/logout", headers={"X-CSRF-Token": "1"})
    assert resp.status_code == 200


def test_csrf_exempts_bearer_no_cookie(client, test_user, auth_headers):
    # Bearer header, no auth cookie in the jar -> exempt from CSRF.
    client.cookies.clear()
    resp = client.post("/api/auth/logout", headers=auth_headers)
    assert resp.status_code == 200


def test_csrf_exempts_safe_methods(client, test_user):
    _login(client)
    # GET is a safe method even with cookie-auth + no CSRF header.
    assert client.get("/api/auth/me").status_code == 200


def test_csrf_ignores_non_api_paths(client):
    # A non-/api path is never CSRF-gated (no auth cookie here anyway).
    # /docs is enabled in the test env (FLASK_ENV != production).
    resp = client.post("/docs")
    # Whatever the route does (405/404), it must NOT be the CSRF 403.
    assert resp.status_code != 403 or resp.json().get("error") != "csrf_failed"
