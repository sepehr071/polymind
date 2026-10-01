"""End-to-end tests proving the FastAPI bridge foundation.

These exercise the full path: TestClient -> CORS/security middleware ->
flask_ctx app_context (worker thread) -> real model facades on Postgres ->
legacy-shaped JSON. The concurrency test is the automated proof that the
yield-dependency keeps each request's db.session isolated per worker thread.
"""
import concurrent.futures

import jwt as pyjwt


# ---------------------------------------------------------------------------
# Login.
# ---------------------------------------------------------------------------
def test_login_valid_returns_tokens_and_legacy_user(client, test_user):
    resp = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "Bearer"
    assert "features" in body
    # Login response uses the explicit user payload (id, not _id) — match Flask.
    assert body["user"]["id"] == str(test_user["_id"])
    assert body["user"]["email"] == "test@gmail.com"
    assert body["user"]["role"] == "manager"
    # Login payload is merged straight into the authMe cache — OnboardingGate
    # needs user.settings (onboarding_seen_at) present without a /me round-trip.
    assert isinstance(body["user"]["settings"], dict)


def test_login_wrong_password_401(client, test_user):
    resp = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "WrongPassword!",
    })
    assert resp.status_code == 401
    assert resp.json()["error"] == "Invalid email or password"


def test_login_missing_fields_400(client):
    resp = client.post("/api/auth/login", json={"email": "x@y.com"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Email and password are required"


def test_login_no_body_400(client):
    resp = client.post("/api/auth/login")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /me — proves auth dependency + legacy _id alias.
# ---------------------------------------------------------------------------
def test_me_with_auth_headers(client, auth_headers, test_user):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(test_user["_id"])
    assert body["email"] == "test@gmail.com"
    assert body["role"] == "manager"
    assert "features" in body
    assert body["profile"]["display_name"] == "Test User"


def test_me_no_token_401_token_missing(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_me_malformed_header_401(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "garbage"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# Refresh flow.
# ---------------------------------------------------------------------------
def test_refresh_flow(client, test_user):
    login = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    }).json()
    refresh_token = login["refresh_token"]
    # Exercise the header/body refresh path: drop the auth cookies /login set so
    # the Bearer header is the sole credential (cookie-auth now takes precedence
    # and would omit body tokens — covered separately in test_cookie_auth.py).
    client.cookies.clear()

    resp = client.post("/api/auth/refresh",
                       headers={"Authorization": f"Bearer {refresh_token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    # The new access token must authenticate /me.
    me = client.get("/api/auth/me",
                    headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200

    # The old (rotated-out) refresh token is now revoked. Clear the freshly
    # rotated cookies so the OLD header token is the sole credential under test.
    client.cookies.clear()
    replay = client.post("/api/auth/refresh",
                         headers={"Authorization": f"Bearer {refresh_token}"})
    assert replay.status_code == 401
    assert replay.json()["code"] == "token_revoked"


def test_refresh_rejects_access_token(client, test_user):
    login = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    }).json()
    access_token = login["access_token"]
    # Drop the valid refresh cookie /login set so the (wrong-type) header token
    # is the sole credential under test.
    client.cookies.clear()
    resp = client.post("/api/auth/refresh",
                       headers={"Authorization": f"Bearer {access_token}"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout revokes the access token.
# ---------------------------------------------------------------------------
def test_logout_revokes_token(client, test_user):
    login = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    }).json()
    access_token = login["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # Token works before logout.
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    logout = client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 200

    # Same token now rejected as revoked.
    after = client.get("/api/auth/me", headers=headers)
    assert after.status_code == 401
    assert after.json()["code"] == "token_revoked"


# ---------------------------------------------------------------------------
# Auth gating matrix.
# ---------------------------------------------------------------------------
def test_gating_expired_token(client, test_user, mint_token):
    token = mint_token(test_user["_id"], role="manager", expired=True)
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_expired"


def test_gating_revoked_token(client, test_user, mint_token):
    token = mint_token(test_user["_id"], role="manager")
    headers = {"Authorization": f"Bearer {token}"}
    # Use logout to add it to the blocklist, then re-use it.
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    resp = client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_revoked"


def test_gating_garbage_token_invalid(client):
    resp = client.get("/api/auth/me",
                      headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_invalid"


def test_gating_banned_user_login_403_with_reason(client, banned_user):
    resp = client.post("/api/auth/login", json={
        "email": "banned@gmail.com", "password": "TestPassword123!",
    })
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "Account has been suspended"
    assert body["reason"] == "policy violation"


def test_change_password_requires_auth(client):
    resp = client.put("/api/auth/password", json={
        "current_password": "x", "new_password": "y",
    })
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# Keycloak config bootstrap (SSO disabled in tests -> {}).
# ---------------------------------------------------------------------------
def test_keycloak_config_disabled_returns_empty(client):
    resp = client.get("/api/auth/keycloak/config")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_keycloak_sync_disabled_503(client):
    resp = client.post("/api/auth/keycloak/sync", json={"access_token": "x"})
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# BRIDGE CONCURRENCY GUARD — the automated proof of flask_ctx isolation.
# Fire N concurrent authed requests across distinct users and assert every
# response maps to the correct identity (zero cross-request session bleed).
# ---------------------------------------------------------------------------
def test_bridge_concurrency_no_session_bleed(client, flask_core, mint_token):
    from app.models.user import UserModel

    n = 10
    users = []
    with flask_core.app_context():
        for i in range(n):
            u = UserModel.create(
                email=f"concurrent{i}@gmail.com",
                password="TestPassword123!",
                display_name=f"Concurrent {i}",
                role="user",
            )
            users.append(u)

    headers = [{"Authorization": f"Bearer {mint_token(u['_id'], role='user')}"}
               for u in users]

    def _hit(idx):
        r = client.get("/api/auth/me", headers=headers[idx])
        return idx, r.status_code, r.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(_hit, range(n)))

    for idx, status, body in results:
        assert status == 200, body
        # The returned identity MUST match the token's user, proving the
        # worker-thread-scoped db.session never crossed requests.
        assert body["id"] == str(users[idx]["_id"]), (idx, body)
        assert body["email"] == f"concurrent{idx}@gmail.com"


# ---------------------------------------------------------------------------
# Route-registration smoke.
# ---------------------------------------------------------------------------
def test_auth_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/auth/login" in paths
    assert "/api/auth/me" in paths
    assert "/api/auth/refresh" in paths
    assert "/api/auth/logout" in paths
    # /register was removed (Keycloak-only onboarding) — must NOT be registered.
    assert "/api/auth/register" not in paths
    assert "/api/auth/password" in paths
    assert "/api/auth/keycloak/config" in paths
    assert "/api/auth/keycloak/sync" in paths


def test_minted_token_decodes_with_same_secret(test_user, mint_token):
    """Sanity: HS256 minting matches the JWT_SECRET resolve_user_from_token uses."""
    import os

    token = mint_token(test_user["_id"], role="manager")
    decoded = pyjwt.decode(token, os.environ["JWT_SECRET_KEY"], algorithms=["HS256"])
    assert decoded["sub"] == str(test_user["_id"])


# ---------------------------------------------------------------------------
# Finding #11 — password change invalidates pre-existing tokens (iat cutoff).
# ---------------------------------------------------------------------------
def test_password_change_revokes_existing_tokens(client, flask_core, test_user):
    """A successful password change stamps settings.tokens_valid_after; any
    token minted BEFORE the change (older iat) is rejected as token_revoked."""
    import time

    from app.models.user import UserModel

    login = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    }).json()
    old_access = login["access_token"]
    old_refresh = login["refresh_token"]
    headers = {"Authorization": f"Bearer {old_access}"}

    # Token works before the change.
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    # Sleep so the cutoff epoch strictly exceeds the token's iat second.
    time.sleep(1.1)
    changed = client.put("/api/auth/password", headers=headers, json={
        "current_password": "TestPassword123!", "new_password": "BrandNewPass456!",
    })
    assert changed.status_code == 200, changed.text

    # The cutoff is persisted on the user.
    with flask_core.app_context():
        fresh = UserModel.find_by_id(test_user["_id"])
    assert isinstance(fresh["settings"].get("tokens_valid_after"), int)

    # The old access token is now rejected (older iat < cutoff).
    after = client.get("/api/auth/me", headers=headers)
    assert after.status_code == 401
    assert after.json()["code"] == "token_revoked"

    # The long-lived refresh token is ALSO dead (the whole point of the fix).
    replay = client.post("/api/auth/refresh",
                         headers={"Authorization": f"Bearer {old_refresh}"})
    assert replay.status_code == 401

    # A fresh login with the new password works and authenticates /me.
    relogin = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "BrandNewPass456!",
    })
    assert relogin.status_code == 200, relogin.text
    new_access = relogin.json()["access_token"]
    assert client.get("/api/auth/me",
                      headers={"Authorization": f"Bearer {new_access}"}).status_code == 200


def test_tokens_valid_after_unset_leaves_tokens_working(client, test_user):
    """Backward-compat: with no cutoff set, an ordinary login token verifies."""
    login = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    }).json()
    me = client.get("/api/auth/me",
                    headers={"Authorization": f"Bearer {login['access_token']}"})
    assert me.status_code == 200


# ---------------------------------------------------------------------------
# Finding #13 — bcrypt 72-byte truncation rejected at validation.
# ---------------------------------------------------------------------------
def test_change_password_rejects_over_72_bytes(client, test_user):
    login = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    }).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    over = "A1" + ("x" * 80)  # >72 bytes, satisfies letter+digit+length rules
    resp = client.put("/api/auth/password", headers=headers, json={
        "current_password": "TestPassword123!", "new_password": over,
    })
    assert resp.status_code == 400
    assert "72" in resp.json()["error"]


def test_user_create_rejects_over_72_byte_password(flask_core):
    import pytest

    from app.models.user import UserModel

    with flask_core.app_context():
        with pytest.raises(ValueError):
            UserModel.create(
                email="toolong@gmail.com",
                password="A1" + ("x" * 80),
                display_name="Too Long",
                role="user",
            )


# ---------------------------------------------------------------------------
# Finding #14 — unknown-email login returns the SAME generic failure as a
# wrong password (and still runs through the dummy-verify path without error).
# ---------------------------------------------------------------------------
def test_login_unknown_email_generic_401(client):
    resp = client.post("/api/auth/login", json={
        "email": "nobody-here@gmail.com", "password": "WhateverPass123!",
    })
    assert resp.status_code == 401
    assert resp.json()["error"] == "Invalid email or password"


def test_login_unknown_and_wrong_password_same_error(client, test_user):
    unknown = client.post("/api/auth/login", json={
        "email": "ghost@gmail.com", "password": "WhateverPass123!",
    })
    wrong = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "WrongPassword!",
    })
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"] == wrong.json()["error"] == "Invalid email or password"
