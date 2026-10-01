"""Coverage tests for app/api/routers/auth.py + app/services/keycloak.py.

Mirrors tests/api/test_auth.py (TestClient + auth_headers + flask_core app_context),
but drives the uncovered branches: register validation matrix, platform-admin login,
refresh with platform-admin claim + logout-with-refresh-token, change-password flow,
keycloak /config (enabled) + /sync (fully mocked KC client), and direct unit tests of
the KeycloakClient (RS256 verify, role mapping, profile/email synthesis, JWKS cache,
end_session_url) with all Keycloak HTTP monkeypatched at the requests boundary.
"""
import time
import uuid

import jwt as pyjwt
import pytest
from jwt.algorithms import RSAAlgorithm
from cryptography.hazmat.primitives.asymmetric import rsa


# ===========================================================================
# Helpers — build a self-contained RS256 keypair + JWK so the KeycloakClient
# can verify a token with ZERO network (we seed _jwks_by_kid directly).
# ===========================================================================
def _make_rsa_keypair(kid="kid-test"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return key, jwk


def _sign_rs256(private_key, claims, kid="kid-test"):
    return pyjwt.encode(
        claims, private_key, algorithm="RS256", headers={"kid": kid}
    )


def _new_client(base_url="http://kc.local", realm="polymind", client_id="polymind-app"):
    from app.services.keycloak import KeycloakClient

    return KeycloakClient(base_url=base_url, realm=realm, client_id=client_id)


# ===========================================================================
# /register was removed (Keycloak-only onboarding). The HTTP route no longer
# exists; a single guard test asserts the endpoint is gone (see below).
# ===========================================================================
def test_register_endpoint_removed(client):
    resp = client.post("/api/auth/register", json={
        "email": "brand_new@gmail.com", "password": "ValidPass123!", "display_name": "Brand New",
    })
    # Path is unregistered -> 404 (never the old 201/400/409).
    assert resp.status_code == 404
    assert resp.status_code not in (200, 201)


# ===========================================================================
# /login — operator/break-glass success path + throttle branch (auth.py 140-175)
# ===========================================================================
def test_login_operator_success(client, admin_user):
    resp = client.post("/api/auth/login", json={
        "email": "admin@gmail.com", "password": "AdminPassword123!",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["user"]["role"] == "admin"
    assert "features" in body


def test_login_throttled_after_repeated_failures(client, test_user, monkeypatch):
    import app.utils.login_throttle as throttle

    # Force the throttle branch deterministically (no real failure accumulation).
    monkeypatch.setattr(throttle, "is_blocked", lambda ip, email: True)
    monkeypatch.setattr(throttle, "retry_after_seconds", lambda: 42)

    resp = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    })
    assert resp.status_code == 429
    assert resp.json()["code"] == "login_throttled"
    assert resp.headers["Retry-After"] == "42"


def test_login_user_includes_avatar_url_key(client, test_user):
    resp = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    })
    assert resp.status_code == 200
    # avatar_url branch in the user payload (auth.py 207).
    assert "avatar_url" in resp.json()["user"]


# ===========================================================================
# /refresh — malformed-token guards + claim propagation (auth.py 218-257)
# ===========================================================================
def test_refresh_missing_auth_header_401(client):
    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_refresh_malformed_auth_header_401(client):
    resp = client.post("/api/auth/refresh", headers={"Authorization": "garbage"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_refresh_expired_token_401(client, test_user):
    # Mint an EXPIRED refresh-type token via a real login, then expire it.
    resp = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    })
    refresh_token = resp.json()["refresh_token"]
    # Decode to confirm shape, then craft an expired variant with same secret.
    import os
    from datetime import datetime, timedelta, timezone

    claims = pyjwt.decode(refresh_token, os.environ["JWT_SECRET_KEY"],
                          algorithms=["HS256"])
    claims["exp"] = datetime.now(timezone.utc) - timedelta(minutes=5)
    expired = pyjwt.encode(claims, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
    # Drop the valid refresh cookie /login set so the expired header token is the
    # sole credential (cookie-auth takes precedence otherwise).
    client.cookies.clear()
    out = client.post("/api/auth/refresh",
                      headers={"Authorization": f"Bearer {expired}"})
    assert out.status_code == 401
    assert out.json()["code"] == "token_expired"


def test_refresh_invalid_token_401(client):
    resp = client.post("/api/auth/refresh",
                       headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_invalid"


def test_refresh_header_path_rotates_access(client, test_user):
    login = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    }).json()
    # Exercise the header refresh path: drop the auth cookies /login set so the
    # Bearer header is the sole credential and body tokens are still returned.
    client.cookies.clear()
    refreshed = client.post("/api/auth/refresh", headers={
        "Authorization": f"Bearer {login['refresh_token']}"
    })
    assert refreshed.status_code == 200, refreshed.text
    new_access = refreshed.json()["access_token"]
    # The rotated access token authenticates /me as the same identity.
    me = client.get("/api/auth/me",
                    headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 200
    assert me.json()["id"] == str(test_user["_id"])


# ===========================================================================
# /logout — with refresh_token in body (auth.py 275-284)
# ===========================================================================
def test_logout_also_revokes_supplied_refresh_token(client, test_user):
    login = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    }).json()
    access, refresh = login["access_token"], login["refresh_token"]

    out = client.post("/api/auth/logout",
                      headers={"Authorization": f"Bearer {access}"},
                      json={"refresh_token": refresh})
    assert out.status_code == 200

    # The supplied refresh token is now revoked too.
    replay = client.post("/api/auth/refresh",
                         headers={"Authorization": f"Bearer {refresh}"})
    assert replay.status_code == 401
    assert replay.json()["code"] == "token_revoked"


def test_logout_with_garbage_refresh_token_still_200(client, test_user):
    login = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    }).json()
    out = client.post("/api/auth/logout",
                      headers={"Authorization": f"Bearer {login['access_token']}"},
                      json={"refresh_token": "not.a.jwt"})
    # The decode failure is swallowed (auth.py 283-284) -> still success.
    assert out.status_code == 200


# ===========================================================================
# /password — full success + error branches (auth.py 347-367)
# ===========================================================================
def test_change_password_no_body_400(client, auth_headers):
    resp = client.put("/api/auth/password", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "No data provided"


def test_change_password_missing_fields_400(client, auth_headers):
    resp = client.put("/api/auth/password", headers=auth_headers,
                      json={"current_password": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Current and new password are required"


def test_change_password_wrong_current_401(client, auth_headers):
    resp = client.put("/api/auth/password", headers=auth_headers, json={
        "current_password": "WRONG!", "new_password": "NewValidPass123!",
    })
    assert resp.status_code == 401
    assert resp.json()["error"] == "Current password is incorrect"


def test_change_password_weak_new_400(client, auth_headers):
    resp = client.put("/api/auth/password", headers=auth_headers, json={
        "current_password": "TestPassword123!", "new_password": "x",
    })
    assert resp.status_code == 400
    assert resp.json()["error"]


def test_change_password_success_then_login_with_new(client, test_user):
    login = client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    }).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    out = client.put("/api/auth/password", headers=headers, json={
        "current_password": "TestPassword123!", "new_password": "BrandNewPass123!",
    })
    assert out.status_code == 200, out.text
    assert out.json()["message"] == "Password updated successfully"

    # New password authenticates; old one no longer does.
    assert client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "BrandNewPass123!",
    }).status_code == 200
    assert client.post("/api/auth/login", json={
        "email": "test@gmail.com", "password": "TestPassword123!",
    }).status_code == 401


# ===========================================================================
# /keycloak/config — ENABLED path (auth.py 378-391)
# ===========================================================================
def test_keycloak_config_enabled_returns_payload(client, flask_core):
    from app.services import keycloak as kc_mod

    cfg = flask_core.config
    cfg["KEYCLOAK_URL"] = "http://kc.local/"
    cfg["KEYCLOAK_REALM"] = "polymind"
    cfg["KEYCLOAK_CLIENT_ID"] = "polymind-app"
    kc_mod.reset_keycloak_client()
    try:
        resp = client.get(
            "/api/auth/keycloak/config",
            headers={"Origin": "https://app.example"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["url"] == "http://kc.local"  # trailing slash stripped
        assert body["realm"] == "polymind"
        assert body["client_id"] == "polymind-app"
        assert body["redirect_uri"] == "https://app.example/login/callback"
        assert body["post_logout_redirect_uri"] == "https://app.example/login"
        assert body["end_session_endpoint"] == (
            "http://kc.local/realms/polymind/protocol/openid-connect/logout"
        )
        assert body["account_console_url"] == "http://kc.local/realms/polymind/account"
    finally:
        del cfg["KEYCLOAK_URL"]
        del cfg["KEYCLOAK_REALM"]
        del cfg["KEYCLOAK_CLIENT_ID"]
        kc_mod.reset_keycloak_client()


def test_keycloak_config_app_public_url_wins_over_origin(client, flask_core):
    from app.services import keycloak as kc_mod

    cfg = flask_core.config
    cfg["KEYCLOAK_URL"] = "http://kc.local"
    cfg["KEYCLOAK_REALM"] = "polymind"
    cfg["KEYCLOAK_CLIENT_ID"] = "polymind-app"
    cfg["APP_PUBLIC_URL"] = "https://unichat.example.com/"
    kc_mod.reset_keycloak_client()
    try:
        resp = client.get(
            "/api/auth/keycloak/config",
            headers={"Origin": "http://localhost:3000"},
        )
        body = resp.json()
        assert body["redirect_uri"] == "https://unichat.example.com/login/callback"
        assert body["post_logout_redirect_uri"] == "https://unichat.example.com/login"
    finally:
        del cfg["KEYCLOAK_URL"]
        del cfg["KEYCLOAK_REALM"]
        del cfg["KEYCLOAK_CLIENT_ID"]
        del cfg["APP_PUBLIC_URL"]
        kc_mod.reset_keycloak_client()


# ===========================================================================
# /keycloak/sync — full flow with a fully mocked KeycloakClient
# (auth.py 396-504)
# ===========================================================================
class _FakeKCClient:
    base_url = "http://kc.local"
    realm = "polymind"
    client_id = "polymind-app"
    expected_audience = "polymind-app"

    def __init__(self, claims=None, profile=None, role="user", raise_exc=None,
                 userinfo=None, userinfo_exc=None):
        self._claims = claims or {"sub": "idp-sub", "exp": int(time.time()) + 3600}
        self._profile = profile
        self._role = role
        self._raise = raise_exc
        self._userinfo = userinfo if userinfo is not None else {}
        self._userinfo_exc = userinfo_exc

    def verify_access_token(self, token):
        if self._raise is not None:
            raise self._raise
        return self._claims

    def userinfo(self, token):
        if self._userinfo_exc is not None:
            raise self._userinfo_exc
        return self._userinfo

    def extract_profile(self, claims, userinfo=None):
        if self._profile is not None:
            return self._profile
        return {"sub": "idp-sub", "email": "kcuser@example.com",
                "display_name": "KC User", "locale": None}

    def map_roles(self, claims):
        return self._role


def _patch_get_client(monkeypatch, fake):
    import app.services.keycloak as kc_mod

    monkeypatch.setattr(kc_mod, "get_keycloak_client", lambda: fake)


def test_keycloak_sync_disabled_503(client, monkeypatch):
    _patch_get_client(monkeypatch, None)
    resp = client.post("/api/auth/keycloak/sync", json={"access_token": "x"})
    assert resp.status_code == 503
    assert resp.json()["error"] == "Keycloak SSO is not configured"


def test_keycloak_sync_missing_access_token_400(client, monkeypatch):
    _patch_get_client(monkeypatch, _FakeKCClient())
    resp = client.post("/api/auth/keycloak/sync", json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "access_token is required"


def test_keycloak_sync_invalid_token_401(client, monkeypatch):
    fake = _FakeKCClient(raise_exc=pyjwt.InvalidTokenError("bad sig"))
    _patch_get_client(monkeypatch, fake)
    resp = client.post("/api/auth/keycloak/sync", json={"access_token": "tok"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "Invalid Keycloak access token"


def test_keycloak_sync_unexpected_verify_error_401(client, monkeypatch):
    fake = _FakeKCClient(raise_exc=RuntimeError("boom"))
    _patch_get_client(monkeypatch, fake)
    resp = client.post("/api/auth/keycloak/sync", json={"access_token": "tok"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "Token verification failed"


def test_keycloak_sync_missing_sub_401(client, monkeypatch):
    fake = _FakeKCClient(profile={"sub": "", "email": "x@y.com", "display_name": "X"})
    _patch_get_client(monkeypatch, fake)
    resp = client.post("/api/auth/keycloak/sync", json={"access_token": "tok"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "Token missing 'sub' claim"


def test_keycloak_sync_missing_email_401(client, monkeypatch):
    fake = _FakeKCClient(profile={"sub": "idp-sub", "email": "", "display_name": "X"})
    _patch_get_client(monkeypatch, fake)
    resp = client.post("/api/auth/keycloak/sync", json={"access_token": "tok"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "Token missing 'email' / 'preferred_username'"


def test_keycloak_sync_creates_user_success(client, monkeypatch, flask_core):
    sub = str(uuid.uuid4())
    email = f"kc_{uuid.uuid4().hex[:8]}@example.com"
    claims = {"sub": sub, "exp": int(time.time()) + 1234}
    fake = _FakeKCClient(
        claims=claims,
        profile={"sub": sub, "email": email, "display_name": "Fresh KC"},
        role="manager",
    )
    _patch_get_client(monkeypatch, fake)

    resp = client.post("/api/auth/keycloak/sync",
                       json={"access_token": "tok", "refresh_token": "rt"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"] == "tok"
    assert body["refresh_token"] == "rt"
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] > 0  # exp - now (auth.py 486-488)
    assert body["user"]["email"] == email.lower()
    assert body["user"]["role"] == "manager"
    # Same authMe-cache merge contract as the operator login payload.
    assert isinstance(body["user"]["settings"], dict)
    assert "features" in body

    # User actually provisioned with keycloak_sub link.
    from app.models.user import UserModel

    with flask_core.app_context():
        u = UserModel.find_by_email(email.lower())
        assert u is not None
        assert u["role"] == "manager"


def test_keycloak_sync_persists_locale_and_sso_flag(client, monkeypatch, flask_core):
    sub = str(uuid.uuid4())
    email = f"kc_{uuid.uuid4().hex[:8]}@example.com"
    fake = _FakeKCClient(
        claims={"sub": sub, "exp": int(time.time()) + 1234},
        profile={
            "sub": sub, "email": email, "display_name": "Ali",
            "email_verified": True, "locale": "fa",
        },
    )
    _patch_get_client(monkeypatch, fake)
    resp = client.post("/api/auth/keycloak/sync", json={"access_token": "tok"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["sso"] is True
    assert body["user"]["settings"].get("locale") == "fa"

    from app.models.user import UserModel
    with flask_core.app_context():
        u = UserModel.find_by_email(email.lower())
        assert u["settings"].get("locale") == "fa"


def test_keycloak_sync_userinfo_failure_still_succeeds(client, monkeypatch, flask_core):
    sub = str(uuid.uuid4())
    email = f"kc_{uuid.uuid4().hex[:8]}@example.com"
    fake = _FakeKCClient(
        claims={"sub": sub, "exp": int(time.time()) + 1234},
        profile={"sub": sub, "email": email, "display_name": "X"},
        userinfo_exc=RuntimeError("userinfo down"),
    )
    _patch_get_client(monkeypatch, fake)
    resp = client.post("/api/auth/keycloak/sync", json={"access_token": "tok"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["email"] == email.lower()


def test_keycloak_sync_banned_user_403(client, monkeypatch, flask_core, banned_user):
    # An ALREADY keycloak-linked banned user re-logging-in via KC -> 403
    # (auth.py 466-470). The link must already exist: the banned fixture is a
    # password-backed row, so the hardened by-email fallback would now refuse to
    # auto-link a fresh sub onto it (409). Pre-bind the sub so the upsert takes
    # the unchanged sub-MATCH branch (re-sync, no APIError) and the suspended
    # check is what produces the 403.
    from app.models.user import UserModel

    sub = str(uuid.uuid4())
    with flask_core.app_context():
        UserModel.update(banned_user["_id"], {"keycloak_sub": sub})

    fake = _FakeKCClient(
        profile={"sub": sub, "email": "banned@gmail.com", "display_name": "Banned"},
        role="user",
    )
    _patch_get_client(monkeypatch, fake)

    resp = client.post("/api/auth/keycloak/sync", json={"access_token": "tok"})
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "Account has been suspended"
    assert body["reason"] == "policy violation"


def test_keycloak_sync_upsert_attribute_error_503(client, monkeypatch):
    sub = str(uuid.uuid4())
    fake = _FakeKCClient(
        profile={"sub": sub, "email": "ae@example.com", "display_name": "AE"},
    )
    _patch_get_client(monkeypatch, fake)

    from app.models.user import UserModel

    def _boom(*a, **k):
        raise AttributeError("upsert_from_keycloak missing")

    monkeypatch.setattr(UserModel, "upsert_from_keycloak", staticmethod(_boom))
    resp = client.post("/api/auth/keycloak/sync", json={"access_token": "tok"})
    assert resp.status_code == 503
    assert resp.json()["error"] == "Keycloak user provisioning is not yet wired"


def test_keycloak_sync_upsert_generic_error_500(client, monkeypatch):
    sub = str(uuid.uuid4())
    fake = _FakeKCClient(
        profile={"sub": sub, "email": "ge@example.com", "display_name": "GE"},
    )
    _patch_get_client(monkeypatch, fake)

    from app.models.user import UserModel

    def _boom(*a, **k):
        raise ValueError("db down")

    monkeypatch.setattr(UserModel, "upsert_from_keycloak", staticmethod(_boom))
    resp = client.post("/api/auth/keycloak/sync", json={"access_token": "tok"})
    assert resp.status_code == 500
    assert resp.json()["error"] == "Failed to provision user"


def test_keycloak_sync_upsert_returns_none_500(client, monkeypatch):
    sub = str(uuid.uuid4())
    fake = _FakeKCClient(
        profile={"sub": sub, "email": "none@example.com", "display_name": "None"},
    )
    _patch_get_client(monkeypatch, fake)

    from app.models.user import UserModel

    monkeypatch.setattr(UserModel, "upsert_from_keycloak",
                        staticmethod(lambda **k: None))
    resp = client.post("/api/auth/keycloak/sync", json={"access_token": "tok"})
    assert resp.status_code == 500
    assert resp.json()["error"] == "Failed to provision user"


# ===========================================================================
# KeycloakClient unit — verify_access_token (keycloak.py 109-149)
# ===========================================================================
def test_verify_access_token_empty_raises():
    import jwt

    c = _new_client()
    with pytest.raises(jwt.InvalidTokenError):
        c.verify_access_token("")


def test_verify_access_token_missing_kid_raises():
    import jwt

    c = _new_client()
    key, _ = _make_rsa_keypair()
    tok = pyjwt.encode({"sub": "s"}, key, algorithm="RS256")  # no kid header
    with pytest.raises(jwt.InvalidTokenError):
        c.verify_access_token(tok)


def test_verify_access_token_wrong_alg_raises():
    import jwt

    c = _new_client()
    tok = pyjwt.encode({"sub": "s"}, "hs-secret", algorithm="HS256",
                       headers={"kid": "kid-test"})
    with pytest.raises(jwt.InvalidTokenError):
        c.verify_access_token(tok)


def test_verify_access_token_happy(monkeypatch):
    c = _new_client(base_url="http://kc.local", realm="polymind", client_id="polymind-app")
    key, jwk = _make_rsa_keypair("kid-1")
    # Seed the JWKS cache directly — no network.
    c._jwks_by_kid = {"kid-1": jwk}
    c._jwks_fetched_at = time.time()

    claims = {
        "sub": "idp-sub", "azp": "polymind-app",
        "iss": "http://kc.local/realms/polymind",
        "exp": int(time.time()) + 3600,
    }
    tok = _sign_rs256(key, claims, kid="kid-1")
    out = c.verify_access_token(tok)
    assert out["sub"] == "idp-sub"
    assert out["azp"] == "polymind-app"


def test_verify_access_token_wrong_azp_raises():
    import jwt

    c = _new_client(client_id="polymind-app")
    key, jwk = _make_rsa_keypair("kid-1")
    c._jwks_by_kid = {"kid-1": jwk}
    c._jwks_fetched_at = time.time()
    claims = {
        "sub": "s", "azp": "some-other-client",
        "iss": "http://kc.local/realms/polymind",
        "exp": int(time.time()) + 3600,
    }
    tok = _sign_rs256(key, claims, kid="kid-1")
    with pytest.raises(jwt.InvalidAudienceError):
        c.verify_access_token(tok)


# ===========================================================================
# _public_key_for — kid-miss triggers a forced JWKS refresh (keycloak.py 95-105)
# ===========================================================================
def test_public_key_for_kid_miss_force_refresh(monkeypatch):
    c = _new_client()
    key, jwk = _make_rsa_keypair("rotated-kid")
    # Cache empty -> _public_key_for must force a refresh that "fetches" the kid.
    calls = {"n": 0}

    def _fake_get_jwks(force=False):
        calls["n"] += 1
        c._jwks_by_kid = {"rotated-kid": jwk}
        return {"keys": [jwk]}

    monkeypatch.setattr(c, "get_jwks", _fake_get_jwks)
    pubkey = c._public_key_for("rotated-kid")
    assert pubkey is not None
    assert calls["n"] == 1  # forced refresh fired exactly once


def test_public_key_for_unknown_kid_raises(monkeypatch):
    import jwt

    c = _new_client()
    monkeypatch.setattr(c, "get_jwks", lambda force=False: {"keys": []})
    with pytest.raises(jwt.InvalidTokenError):
        c._public_key_for("never-existed")


# ===========================================================================
# get_jwks + discover — all mocked at requests boundary (keycloak.py 54-92)
# ===========================================================================
class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def test_discover_fetches_and_caches(monkeypatch):
    import app.services.keycloak as kc_mod

    c = _new_client()
    disc = {"jwks_uri": "http://kc.local/realms/polymind/jwks",
            "end_session_endpoint": "http://kc.local/logout"}
    calls = {"n": 0}

    def _fake_get(url, timeout=None):
        calls["n"] += 1
        return _FakeResp(disc)

    monkeypatch.setattr(kc_mod.requests, "get", _fake_get)
    assert c.discover() == disc
    # Second call hits the cache (no extra request).
    assert c.discover() == disc
    assert calls["n"] == 1


def test_get_jwks_fetches_indexes_and_caches(monkeypatch):
    import app.services.keycloak as kc_mod

    c = _new_client()
    _, jwk = _make_rsa_keypair("k-1")
    disc = {"jwks_uri": "http://kc.local/jwks"}
    jwks_payload = {"keys": [jwk, {"no_kid": True}]}

    def _fake_get(url, timeout=None):
        if url.endswith("openid-configuration"):
            return _FakeResp(disc)
        return _FakeResp(jwks_payload)

    monkeypatch.setattr(kc_mod.requests, "get", _fake_get)
    out = c.get_jwks()
    assert "keys" in out
    # kid indexed; the keyless entry skipped (keycloak.py 84-87).
    assert "k-1" in c._jwks_by_kid

    # Cached path: returns from _jwks_by_kid without hitting the network again.
    cached = c.get_jwks()
    assert cached["keys"][0]["kid"] == "k-1"


def test_get_jwks_missing_uri_raises(monkeypatch):
    import app.services.keycloak as kc_mod

    c = _new_client()
    monkeypatch.setattr(kc_mod.requests, "get",
                        lambda url, timeout=None: _FakeResp({}))
    with pytest.raises(RuntimeError):
        c.get_jwks()


# ===========================================================================
# map_roles (keycloak.py 153-169)
# ===========================================================================
def test_map_roles_platform_admin():
    from app.services.keycloak import KeycloakClient

    assert KeycloakClient.map_roles(
        {"realm_access": {"roles": ["platform-admin", "org-admin"]}}) == "admin"


def test_map_roles_org_admin():
    from app.services.keycloak import KeycloakClient

    assert KeycloakClient.map_roles(
        {"realm_access": {"roles": ["org-admin", "workspace-member"]}}) == "manager"


def test_map_roles_workspace_member():
    from app.services.keycloak import KeycloakClient

    assert KeycloakClient.map_roles(
        {"realm_access": {"roles": ["workspace-member"]}}) == "user"


def test_map_roles_legacy_names_are_not_product_levels():
    from app.services.keycloak import KeycloakClient

    assert KeycloakClient.map_roles(
        {"realm_access": {"roles": ["super-admin", "admin", "user"]}}) is None


def test_map_roles_no_realm_access_is_rejected():
    from app.services.keycloak import KeycloakClient

    assert KeycloakClient.map_roles({}) is None


def test_map_roles_malformed_realm_access_is_rejected():
    from app.services.keycloak import KeycloakClient

    assert KeycloakClient.map_roles({"realm_access": "not-a-dict"}) is None


def test_organizations_from_account_membership():
    from app.services.keycloak import KeycloakClient

    orgs = KeycloakClient.organizations_from_account([
        {"id": "org-1", "alias": "rayan", "name": "rayan"},
        {"alias": "skip-me"},
        "nope",
    ])
    assert orgs == [{"id": "org-1", "alias": "rayan", "name": "rayan"}]


def test_organizations_from_claims_alias_map():
    from app.services.keycloak import KeycloakClient

    orgs = KeycloakClient.organizations_from_claims({
        "organization": {"acme": {"id": "org-1", "name": "Acme"}},
    })
    assert orgs == [{"id": "org-1", "alias": "acme", "name": "Acme"}]


def test_assert_can_enter_rules():
    from app.services.keycloak_orgs import KcAccessDenied, assert_can_enter

    assert_can_enter("admin", [])
    assert_can_enter("manager", [{"id": "org-1"}])
    try:
        assert_can_enter(None, [{"id": "org-1"}])
        raise AssertionError("roleless user entered")
    except KcAccessDenied as exc:
        assert exc.code == "kc_role_required"
    try:
        assert_can_enter("user", [])
        raise AssertionError("member without org entered")
    except KcAccessDenied as exc:
        assert exc.code == "kc_org_required"


# ===========================================================================
# extract_profile — email synthesis + display_name fallbacks (keycloak.py 171-199)
# ===========================================================================
def test_extract_profile_real_email():
    c = _new_client(realm="polymind")
    out = c.extract_profile({
        "sub": "abc", "email": "Real@Example.com", "name": "Real Name",
    })
    assert out["sub"] == "abc"
    assert out["email"] == "Real@Example.com"
    assert out["display_name"] == "Real Name"


def test_extract_profile_synthesizes_email_from_username():
    c = _new_client(realm="polymind")
    out = c.extract_profile({"sub": "abc", "preferred_username": "jdoe"})
    assert out["email"] == "jdoe@polymind.kc.local"
    assert out["display_name"] == "jdoe"


def test_extract_profile_no_email_no_username():
    c = _new_client(realm="polymind")
    out = c.extract_profile({"sub": "abc"})
    assert out["email"] == ""
    assert out["display_name"] == "User"  # final fallback


def test_extract_profile_display_name_from_email_local_part():
    c = _new_client(realm="polymind")
    out = c.extract_profile({"sub": "abc", "email": "localpart@x.com"})
    # No name/preferred -> derive from email local-part (keycloak.py 192).
    assert out["display_name"] == "localpart"


def test_extract_profile_locale_and_name_from_userinfo():
    c = _new_client(realm="polymind")
    out = c.extract_profile(
        {"sub": "abc", "preferred_username": "jdoe"},
        {"locale": "fa-IR", "name": "علی", "email": "ali@example.com"},
    )
    assert out["locale"] == "fa"
    assert out["display_name"] == "علی"
    assert out["email"] == "ali@example.com"


def test_normalize_locale_rejects_unknown():
    from app.services.keycloak import KeycloakClient

    assert KeycloakClient.normalize_locale("de") is None
    assert KeycloakClient.normalize_locale("en_US") == "en"
    assert KeycloakClient.normalize_locale(None) is None


# ===========================================================================
# end_session_url (keycloak.py 203-216)
# ===========================================================================
def test_end_session_url_builds_query(monkeypatch):
    import app.services.keycloak as kc_mod

    c = _new_client(client_id="polymind-app")
    disc = {"end_session_endpoint": "http://kc.local/logout"}
    monkeypatch.setattr(kc_mod.requests, "get",
                        lambda url, timeout=None: _FakeResp(disc))
    url = c.end_session_url("http://app/login", id_token_hint="idtok")
    assert url.startswith("http://kc.local/logout?")
    assert "client_id=polymind-app" in url
    assert "id_token_hint=idtok" in url
    assert "post_logout_redirect_uri=" in url


def test_end_session_url_endpoint_with_existing_query(monkeypatch):
    import app.services.keycloak as kc_mod

    c = _new_client(client_id="polymind-app")
    disc = {"end_session_endpoint": "http://kc.local/logout?foo=bar"}
    monkeypatch.setattr(kc_mod.requests, "get",
                        lambda url, timeout=None: _FakeResp(disc))
    url = c.end_session_url("http://app/login")
    # Existing query -> '&' separator (keycloak.py 215).
    assert "?foo=bar&" in url


def test_end_session_url_missing_endpoint_raises(monkeypatch):
    import app.services.keycloak as kc_mod

    c = _new_client()
    monkeypatch.setattr(kc_mod.requests, "get",
                        lambda url, timeout=None: _FakeResp({}))
    with pytest.raises(RuntimeError):
        c.end_session_url("http://app/login")


# ===========================================================================
# get_keycloak_client / reset_keycloak_client singleton (keycloak.py 226-265)
# ===========================================================================
def test_get_keycloak_client_disabled_when_unset(flask_core):
    import app.services.keycloak as kc_mod

    kc_mod.reset_keycloak_client()
    cfg = flask_core.config
    # Ensure unset.
    for k in ("KEYCLOAK_URL", "KEYCLOAK_REALM", "KEYCLOAK_CLIENT_ID"):
        cfg[k] = ""
    try:
        assert kc_mod.get_keycloak_client() is None
        # Cached "disabled" state — second call returns the same None fast.
        assert kc_mod.get_keycloak_client() is None
    finally:
        for k in ("KEYCLOAK_URL", "KEYCLOAK_REALM", "KEYCLOAK_CLIENT_ID"):
            del cfg[k]
        kc_mod.reset_keycloak_client()


def test_get_keycloak_client_enabled_builds_singleton(flask_core):
    import app.services.keycloak as kc_mod

    kc_mod.reset_keycloak_client()
    cfg = flask_core.config
    cfg["KEYCLOAK_URL"] = "http://kc.local/"
    cfg["KEYCLOAK_REALM"] = "polymind"
    cfg["KEYCLOAK_CLIENT_ID"] = "polymind-app"
    try:
        c1 = kc_mod.get_keycloak_client()
        assert c1 is not None
        assert c1.base_url == "http://kc.local"  # rstrip('/')
        assert c1.realm == "polymind"
        assert c1.client_id == "polymind-app"
        # Singleton: same instance returned (initialized flag short-circuit).
        assert kc_mod.get_keycloak_client() is c1
    finally:
        for k in ("KEYCLOAK_URL", "KEYCLOAK_REALM", "KEYCLOAK_CLIENT_ID"):
            del cfg[k]
        kc_mod.reset_keycloak_client()
