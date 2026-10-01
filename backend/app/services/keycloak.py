"""Keycloak OIDC client.

Verifies RS256 access tokens issued by a Keycloak realm directly inside this
process — no proxy / introspection round-trip. Frontend obtains the token via
PKCE (Authorization Code with code_verifier) and POSTs it to
``/api/auth/keycloak/sync``; the route delegates verification + claim parsing
to this module.

Singleton-per-process. OIDC discovery is fetched once and cached forever;
JWKS is cached with a 5-minute TTL and force-refreshed on `kid` miss.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional
from urllib.parse import urlencode

import jwt
import requests
from app.settings import settings

logger = logging.getLogger(__name__)

_DISCOVERY_TIMEOUT_S = 10
_JWKS_TIMEOUT_S = 10
_JWKS_TTL_S = 300
_LEEWAY_S = 60


class KeycloakClient:
    """Verifies Keycloak-issued RS256 access tokens.

    Created lazily by :func:`get_keycloak_client`; one instance per process.
    Thread-safe: discovery + JWKS caches are guarded by a single lock.
    """

    def __init__(self, base_url: str, realm: str, client_id: str):
        self.base_url = base_url.rstrip('/')
        self.realm = realm
        self.client_id = client_id

        self._lock = threading.Lock()
        self._discovery: Optional[dict] = None
        self._jwks_by_kid: dict[str, dict] = {}
        self._jwks_fetched_at: float = 0.0

    # ---------------- OIDC discovery + JWKS ----------------

    def _discovery_url(self) -> str:
        return f"{self.base_url}/realms/{self.realm}/.well-known/openid-configuration"

    def discover(self) -> dict:
        """Fetch + cache OIDC discovery document. Cached forever after first hit."""
        with self._lock:
            if self._discovery is not None:
                return self._discovery
        # Network call outside the lock — first-hit race is harmless (idempotent).
        resp = requests.get(self._discovery_url(), timeout=_DISCOVERY_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
        with self._lock:
            self._discovery = data
        return data

    def get_jwks(self, force: bool = False) -> dict:
        """Fetch + cache JWKS. 5-minute TTL. ``force=True`` bypasses cache."""
        now = time.time()
        with self._lock:
            cache_fresh = (now - self._jwks_fetched_at) < _JWKS_TTL_S
            if not force and cache_fresh and self._jwks_by_kid:
                return {'keys': list(self._jwks_by_kid.values())}

        discovery = self.discover()
        jwks_uri = discovery.get('jwks_uri')
        if not jwks_uri:
            raise RuntimeError("Keycloak discovery missing 'jwks_uri'")
        resp = requests.get(jwks_uri, timeout=_JWKS_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()

        new_index: dict[str, dict] = {}
        for jwk in data.get('keys', []):
            kid = jwk.get('kid')
            if kid:
                new_index[kid] = jwk

        with self._lock:
            self._jwks_by_kid = new_index
            self._jwks_fetched_at = time.time()
        return data

    def _public_key_for(self, kid: str):
        with self._lock:
            jwk_dict = self._jwks_by_kid.get(kid)
        if jwk_dict is None:
            # Maybe key rotated since last fetch — force-refresh once.
            self.get_jwks(force=True)
            with self._lock:
                jwk_dict = self._jwks_by_kid.get(kid)
        if jwk_dict is None:
            raise jwt.InvalidTokenError(f"Unknown signing key id: {kid}")
        # PyJWT 2.x converts JWK -> RSAPublicKey via PyJWK.
        return jwt.PyJWK(jwk_dict).key

    # ---------------- token verification ----------------

    def verify_access_token(self, token: str) -> dict:
        """Verify a Keycloak RS256 access token and return its claims.

        Validates signature, ``iss`` (matches realm URL), ``exp`` (with 60s
        leeway). Audience check is manual to accept ``aud`` OR ``azp`` —
        Keycloak typically emits ``aud=['account']`` with the real audience
        in ``azp``. Raises :class:`jwt.InvalidTokenError` (or a subclass) on
        any failure; never returns None.
        """
        if not token:
            raise jwt.InvalidTokenError("Empty token")

        header = jwt.get_unverified_header(token)
        kid = header.get('kid')
        if not kid:
            raise jwt.InvalidTokenError("Access token missing 'kid' header")
        alg = header.get('alg')
        if alg != 'RS256':
            raise jwt.InvalidTokenError(f"Unexpected JWT alg: {alg!r}")

        public_key = self._public_key_for(kid)
        issuer = f"{self.base_url}/realms/{self.realm}"

        # Skip aud check (KC realms vary — `aud='account'` is common). Verify
        # `azp` instead: Keycloak always sets this to the requesting client_id.
        # Canonical "is this token meant for our client?" check.
        claims = jwt.decode(
            token,
            public_key,
            algorithms=['RS256'],
            issuer=issuer,
            leeway=_LEEWAY_S,
            options={'verify_aud': False, 'require': ['exp', 'iss']},
        )

        if claims.get('azp') != self.client_id:
            raise jwt.InvalidAudienceError(
                f"Token azp={claims.get('azp')!r} does not match client_id={self.client_id!r}"
            )

        return claims

    # ---------------- claim utilities ----------------

    # Realm roles are the only source for the three product levels.
    # ``workspace member`` (space) is accepted until the realm role is renamed.
    ROLE_PLATFORM_ADMIN = 'platform-admin'
    ROLE_ORG_ADMIN = 'org-admin'
    ROLE_WORKSPACE_MEMBER = 'workspace-member'

    @staticmethod
    def realm_roles(claims: dict) -> set[str]:
        try:
            roles = claims.get('realm_access', {}).get('roles', []) or []
        except AttributeError:
            return set()
        if not isinstance(roles, list):
            return set()
        return {r for r in roles if isinstance(r, str)}

    @staticmethod
    def map_roles(claims: dict) -> Optional[str]:
        """Map realm roles onto the product role column.

        ``platform-admin`` → ``admin`` (platform super-admin),
        ``org-admin`` → ``manager`` (admin of the orgs they belong to),
        ``workspace-member`` → ``user``. None when none of the three are present.
        """
        roles = KeycloakClient.realm_roles(claims)
        if KeycloakClient.ROLE_PLATFORM_ADMIN in roles:
            return 'admin'
        if KeycloakClient.ROLE_ORG_ADMIN in roles:
            return 'manager'
        if (
            KeycloakClient.ROLE_WORKSPACE_MEMBER in roles
            or 'workspace member' in roles
        ):
            return 'user'
        return None

    @staticmethod
    def organizations_from_claims(claims: dict) -> list[dict]:
        """Organizations embedded in the access token (Organization mapper).

        Keycloak emits ``{"alias": {"id": "...", "name": "..."}}`` or a list.
        """
        raw = claims.get('organization') if isinstance(claims, dict) else None
        out: list[dict] = []
        if isinstance(raw, dict):
            items = []
            for alias, meta in raw.items():
                if isinstance(meta, dict):
                    items.append((str(alias), meta))
                else:
                    items.append((str(alias), {}))
        elif isinstance(raw, list):
            items = []
            for meta in raw:
                if isinstance(meta, str):
                    items.append((meta, {'id': meta}))
                elif isinstance(meta, dict):
                    alias = str(meta.get('alias') or meta.get('name') or meta.get('id') or '')
                    items.append((alias, meta))
        else:
            return out
        for alias, meta in items:
            oid = str((meta or {}).get('id') or alias or '').strip()
            if not oid:
                continue
            name = str((meta or {}).get('name') or alias or oid)
            out.append({'id': oid, 'alias': alias or oid, 'name': name})
        return out

    @staticmethod
    def organizations_from_account(payload) -> list[dict]:
        """Organisations from ``GET /realms/{realm}/account/organizations``.

        Membership is not a realm role. The account API returns it for the
        caller's own token even when the access token has no ``organization``
        claim.
        """
        out: list[dict] = []
        if not isinstance(payload, list):
            return out
        for org in payload:
            if not isinstance(org, dict) or not org.get('id'):
                continue
            oid = str(org['id'])
            alias = str(org.get('alias') or oid)
            out.append({
                'id': oid,
                'alias': alias,
                'name': str(org.get('name') or alias),
            })
        return out

    def account_organizations(self, access_token: str) -> Optional[list[dict]]:
        """Orgs the access-token user belongs to. None when the account API refuses."""
        if not access_token:
            return None
        url = (
            f"{self.base_url}/realms/{self.realm}/account/organizations"
            "?first=0&max=100"
        )
        resp = requests.get(
            url,
            headers={
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json',
            },
            timeout=_DISCOVERY_TIMEOUT_S,
        )
        if resp.status_code in (401, 403):
            return None
        resp.raise_for_status()
        # ponytail: first 100 orgs, upgrade when a user belongs to more
        return self.organizations_from_account(resp.json())

    def admin_request(self, method: str, path: str):
        """Call the Keycloak admin API. None when no admin credentials are set."""
        token = self._admin_token()
        if not token:
            return None
        url = f"{self.base_url}/admin/realms/{self.realm}/{path.lstrip('/')}"
        resp = requests.request(
            method,
            url,
            headers={'Authorization': f'Bearer {token}'},
            timeout=_DISCOVERY_TIMEOUT_S,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        if not resp.content:
            return []
        return resp.json()

    def _admin_token(self) -> Optional[str]:
        import os
        now = time.time()
        cached = getattr(self, '_admin_token_cache', None)
        if cached and cached[1] > now + 15:
            return cached[0]
        cid = os.environ.get('KEYCLOAK_ADMIN_CLIENT_ID', '').strip()
        secret = os.environ.get('KEYCLOAK_ADMIN_CLIENT_SECRET', '').strip()
        user = os.environ.get('KEYCLOAK_ADMIN_USERNAME', '').strip()
        password = os.environ.get('KEYCLOAK_ADMIN_PASSWORD', '').strip()
        token_realm = os.environ.get('KEYCLOAK_ADMIN_REALM', '').strip() or self.realm
        token_url = (
            f"{self.base_url}/realms/{token_realm}/protocol/openid-connect/token"
        )
        data = None
        if cid and secret:
            data = {
                'grant_type': 'client_credentials',
                'client_id': cid,
                'client_secret': secret,
            }
        elif user and password:
            data = {
                'grant_type': 'password',
                'client_id': os.environ.get('KEYCLOAK_ADMIN_CLI', 'admin-cli'),
                'username': user,
                'password': password,
            }
        if not data:
            return None
        resp = requests.post(token_url, data=data, timeout=_DISCOVERY_TIMEOUT_S)
        resp.raise_for_status()
        body = resp.json()
        access = body.get('access_token')
        if not access:
            return None
        self._admin_token_cache = (access, now + int(body.get('expires_in') or 60))
        return access

    def organizations_for_user(self, user_id: str) -> Optional[list[dict]]:
        """Orgs this user belongs to. None when the admin API is not configured."""
        if not user_id or self._admin_token() is None:
            return None
        raw = self.admin_request(
            'GET', f'organizations/members/{user_id}/organizations'
        )
        if raw is None:
            return None
        out = []
        for org in raw or []:
            if not isinstance(org, dict) or not org.get('id'):
                continue
            out.append({
                'id': str(org['id']),
                'alias': str(org.get('alias') or org['id']),
                'name': str(org.get('name') or org.get('alias') or org['id']),
            })
        return out

    def organization_members(self, org_id: str) -> Optional[list[dict]]:
        """Members of one org, each with realm role names. None without admin API."""
        if not org_id or self._admin_token() is None:
            return None
        raw = self.admin_request('GET', f'organizations/{org_id}/members?max=500')
        if raw is None:
            return None
        out = []
        for member in raw or []:
            if not isinstance(member, dict) or not member.get('id'):
                continue
            uid = str(member['id'])
            roles_raw = self.admin_request(
                'GET', f'users/{uid}/role-mappings/realm'
            ) or []
            role_names = [
                r.get('name') for r in roles_raw
                if isinstance(r, dict) and r.get('name')
            ]
            given = (member.get('firstName') or '').strip()
            family = (member.get('lastName') or '').strip()
            out.append({
                'id': uid,
                'email': (member.get('email') or '').strip(),
                'username': (member.get('username') or '').strip(),
                'display_name': (' '.join(p for p in (given, family) if p)
                                 or member.get('username')
                                 or member.get('email')
                                 or 'User'),
                'realm_roles': role_names,
            })
        return out

    def userinfo(self, access_token: str) -> dict:
        """GET the OIDC userinfo endpoint. Fail-open: {} on any error.

        Access-token claims often omit ``name`` / ``locale`` unless protocol
        mappers are added; userinfo is the standard place those live.
        """
        if not access_token:
            return {}
        try:
            discovery = self.discover()
            endpoint = discovery.get('userinfo_endpoint')
            if not endpoint:
                return {}
            resp = requests.get(
                endpoint,
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=_DISCOVERY_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001 — login must not fail closed
            logger.warning('keycloak userinfo failed: %s', exc)
            return {}

    @staticmethod
    def normalize_locale(raw) -> Optional[str]:
        """Map KC locale (``fa``, ``fa-IR``, ``en_US``) to Polymind ``fa``|``en``."""
        if not raw or not isinstance(raw, str):
            return None
        base = raw.strip().lower().replace('_', '-').split('-', 1)[0]
        return base if base in ('fa', 'en') else None

    def extract_profile(self, claims: dict, userinfo: Optional[dict] = None) -> dict:
        """Pull a {sub, email, email_verified, display_name, locale} dict.

        ``userinfo`` fills fields the access token omitted. Email synthesis
        when neither source has ``email``: ``<preferred_username>@<realm>.kc.local``.

        ``email_verified`` surfaces the KC boolean only when the email came
        from a real claim/userinfo field — synthesized addresses are treated
        verified (they derive from signed ``preferred_username``).
        """
        info = userinfo if isinstance(userinfo, dict) else {}
        sub = claims.get('sub') or info.get('sub') or ''
        raw_email = (claims.get('email') or info.get('email') or '').strip()
        preferred = (
            (claims.get('preferred_username') or info.get('preferred_username') or '')
            .strip()
        )
        if raw_email:
            email = raw_email
            verified_claim = claims.get('email_verified')
            if verified_claim is None:
                verified_claim = info.get('email_verified')
            email_verified = verified_claim is True
        elif preferred:
            email = f"{preferred}@{self.realm}.kc.local"
            email_verified = True
        else:
            email = ''
            email_verified = False
        given = (info.get('given_name') or '').strip()
        family = (info.get('family_name') or '').strip()
        composed = ' '.join(p for p in (given, family) if p)
        display_name = (
            claims.get('name')
            or info.get('name')
            or composed
            or preferred
            or (raw_email.split('@', 1)[0] if raw_email else '')
            or 'User'
        )
        locale = self.normalize_locale(claims.get('locale') or info.get('locale'))
        return {
            'sub': str(sub),
            'email': email,
            'email_verified': email_verified,
            'display_name': display_name.strip() or 'User',
            'locale': locale,
        }

    # ---------------- federated logout ----------------

    def end_session_url(self, post_logout_redirect_uri: str, id_token_hint: Optional[str] = None) -> str:
        """Build the Keycloak end_session_endpoint URL for federated logout."""
        discovery = self.discover()
        endpoint = discovery.get('end_session_endpoint')
        if not endpoint:
            raise RuntimeError("Keycloak discovery missing 'end_session_endpoint'")
        params: dict[str, str] = {
            'client_id': self.client_id,
            'post_logout_redirect_uri': post_logout_redirect_uri,
        }
        if id_token_hint:
            params['id_token_hint'] = id_token_hint
        sep = '&' if '?' in endpoint else '?'
        return f"{endpoint}{sep}{urlencode(params)}"


# ---------------- module singleton ----------------

_client_lock = threading.Lock()
_client: Optional[KeycloakClient] = None
_client_initialized = False


def get_keycloak_client() -> Optional[KeycloakClient]:
    """Return the process-wide :class:`KeycloakClient`, or ``None`` if SSO is off.

    SSO is considered disabled when ``KEYCLOAK_URL`` is blank. The first call
    reads ``KEYCLOAK_URL/REALM/CLIENT_ID`` from ``app.settings.settings`` and
    constructs the singleton; later calls return it.
    """
    global _client, _client_initialized
    with _client_lock:
        if _client_initialized:
            return _client
        try:
            cfg = settings
        except RuntimeError:
            # No app context — caller will retry on a real request.
            return None
        url = (cfg.get('KEYCLOAK_URL') or '').strip().rstrip('/')
        realm = (cfg.get('KEYCLOAK_REALM') or '').strip()
        client_id = (cfg.get('KEYCLOAK_CLIENT_ID') or '').strip()
        if not url or not realm or not client_id:
            _client = None
            _client_initialized = True
            logger.info('Keycloak SSO disabled (KEYCLOAK_URL/REALM/CLIENT_ID not all set)')
            return None
        _client = KeycloakClient(
            base_url=url,
            realm=realm,
            client_id=client_id,
        )
        _client_initialized = True
        logger.info('Keycloak SSO enabled: realm=%s client_id=%s', realm, client_id)
        return _client


def reset_keycloak_client() -> None:
    """Test helper — drop the singleton so the next call re-reads config."""
    global _client, _client_initialized
    with _client_lock:
        _client = None
        _client_initialized = False
