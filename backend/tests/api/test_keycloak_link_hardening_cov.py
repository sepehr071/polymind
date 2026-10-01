"""Regression lock for the Keycloak SSO account-link hardening (audit #2).

A KC RS256 token is signature-verified but carries NO trust about its `email`
claim. The historical ``UserModel.upsert_from_keycloak`` by-email fallback bound
a fresh `sub` to ANY existing row sharing the email AND overwrote that row's
role — so a token with ``email=ADMIN_EMAIL`` hijacked the break-glass operator
(super-admin takeover) and clobbered its role.

These tests pin the hardened contract directly at the model facade (the same
layer the conftest user-factories exercise), inside a ``flask_core`` app_context:

* by-email fallback to a password-backed admin row is REFUSED, with the sub
  NOT rebound and the role NOT overwritten;
* an unverified email (``email_verified is not True``) never links, even to a
  passwordless non-privileged row;
* a brand-new SSO-only identity (no pre-existing email row) still provisions;
* a verified email linking to a passwordless plain-``user`` row succeeds but
  does NOT overwrite that row's role; and
* the sub-MATCH path still re-syncs the KC role (the intended KC=truth
  per-login behavior the fix must not regress).

Plus a unit check that ``KeycloakClient.extract_profile`` surfaces the
``email_verified`` boolean the fallback gate depends on.
"""
import uuid

import pytest

from app.utils.errors import APIError


def _new_kc_client(realm="polymind"):
    from app.services.keycloak import KeycloakClient

    return KeycloakClient(base_url="http://kc.local", realm=realm, client_id="polymind-app")


# ---------------------------------------------------------------------------
# by-email fallback -> password-backed admin row is REFUSED (the takeover path)
# ---------------------------------------------------------------------------
def test_upsert_refuses_link_to_password_backed_admin(flask_core, admin_user):
    """A fresh KC sub presenting ``email=ADMIN_EMAIL`` must NOT bind to the
    break-glass operator row, even with email_verified=True."""
    from app.models.user import UserModel

    attacker_sub = str(uuid.uuid4())
    with flask_core.app_context():
        with pytest.raises(APIError) as exc:
            UserModel.upsert_from_keycloak(
                sub=attacker_sub,
                email="admin@gmail.com",       # == seeded operator email
                display_name="Mallory",
                role="admin",                   # IdP-derived role (attempted clobber)
                email_verified=True,
            )
    assert exc.value.status_code == 409

    # The admin row is untouched: sub still unbound, role still 'admin'.
    with flask_core.app_context():
        admin = UserModel.find_by_email("admin@gmail.com")
        assert admin is not None
        assert admin["role"] == "admin"
        assert admin.get("keycloak_sub") in (None, "")
        # The attacker's sub never became resolvable.
        assert UserModel.find_by_keycloak_sub(attacker_sub) is None


def test_upsert_refuses_link_to_password_backed_plain_user(flask_core, plain_user):
    """Even a plain-``user`` row is protected when it is password-backed
    (the password_hash guard, independent of role)."""
    from app.models.user import UserModel

    attacker_sub = str(uuid.uuid4())
    with flask_core.app_context():
        with pytest.raises(APIError) as exc:
            UserModel.upsert_from_keycloak(
                sub=attacker_sub,
                email="plain@gmail.com",
                display_name="Mallory",
                role="user",
                email_verified=True,
            )
    assert exc.value.status_code == 409
    with flask_core.app_context():
        assert UserModel.find_by_keycloak_sub(attacker_sub) is None


def test_upsert_refuses_link_to_privileged_manager_even_if_passwordless(flask_core):
    """A passwordless but privileged (manager) row is still refused on the
    role guard — never auto-link into an elevated principal."""
    from app.models.user import UserModel

    email = f"mgr_{uuid.uuid4().hex[:8]}@example.com"
    with flask_core.app_context():
        # SSO-style manager: no password, no sub yet.
        UserModel.create(email=email, password=None, display_name="Mgr", role="manager")

    attacker_sub = str(uuid.uuid4())
    with flask_core.app_context():
        with pytest.raises(APIError) as exc:
            UserModel.upsert_from_keycloak(
                sub=attacker_sub, email=email, display_name="Mallory",
                role="manager", email_verified=True,
            )
    assert exc.value.status_code == 409
    with flask_core.app_context():
        assert UserModel.find_by_keycloak_sub(attacker_sub) is None


# ---------------------------------------------------------------------------
# unverified email -> never links (even to a safe passwordless plain row)
# ---------------------------------------------------------------------------
def test_upsert_refuses_link_when_email_unverified(flask_core):
    from app.models.user import UserModel

    email = f"unv_{uuid.uuid4().hex[:8]}@example.com"
    with flask_core.app_context():
        UserModel.create(email=email, password=None, display_name="Unv", role="user")

    attacker_sub = str(uuid.uuid4())
    with flask_core.app_context():
        with pytest.raises(APIError) as exc:
            UserModel.upsert_from_keycloak(
                sub=attacker_sub, email=email, display_name="Mallory",
                role="user", email_verified=False,
            )
    assert exc.value.status_code == 409
    with flask_core.app_context():
        # No rebind happened.
        assert UserModel.find_by_keycloak_sub(attacker_sub) is None


def test_upsert_default_email_verified_is_fail_closed(flask_core):
    """Omitting email_verified must behave as unverified (fail-closed)."""
    from app.models.user import UserModel

    email = f"def_{uuid.uuid4().hex[:8]}@example.com"
    with flask_core.app_context():
        UserModel.create(email=email, password=None, display_name="Def", role="user")

    attacker_sub = str(uuid.uuid4())
    with flask_core.app_context():
        with pytest.raises(APIError):
            UserModel.upsert_from_keycloak(
                sub=attacker_sub, email=email, display_name="Mallory", role="user",
            )  # email_verified omitted -> defaults False


# ---------------------------------------------------------------------------
# brand-new SSO-only identity still provisions (NOT the fallback path)
# ---------------------------------------------------------------------------
def test_upsert_creates_brand_new_sso_user(flask_core):
    from app.models.user import UserModel

    sub = str(uuid.uuid4())
    email = f"fresh_{uuid.uuid4().hex[:8]}@example.com"
    with flask_core.app_context():
        created = UserModel.upsert_from_keycloak(
            sub=sub, email=email, display_name="Fresh SSO", role="manager",
            email_verified=True,
        )
    assert created is not None
    assert created["email"] == email
    assert created["role"] == "manager"
    assert created.get("password_hash") in (None, b"", "")  # passwordless SSO row

    with flask_core.app_context():
        linked = UserModel.find_by_keycloak_sub(sub)
        assert linked is not None
        assert linked["email"] == email


# ---------------------------------------------------------------------------
# verified + passwordless + plain-user -> links, but does NOT overwrite role
# ---------------------------------------------------------------------------
def test_upsert_links_verified_passwordless_user_without_role_overwrite(flask_core):
    from app.models.user import UserModel

    email = f"link_{uuid.uuid4().hex[:8]}@example.com"
    with flask_core.app_context():
        UserModel.create(email=email, password=None, display_name="Linkable", role="user")

    sub = str(uuid.uuid4())
    with flask_core.app_context():
        out = UserModel.upsert_from_keycloak(
            sub=sub, email=email, display_name="Linkable",
            role="admin",            # KC says admin — must NOT be applied on a by-email link
            email_verified=True,
        )
    assert out is not None
    # Sub bound...
    assert out.get("keycloak_sub") == sub
    # ...but the pre-existing role is preserved, NOT overwritten to 'admin'.
    assert out["role"] == "user"
    with flask_core.app_context():
        assert UserModel.find_by_keycloak_sub(sub)["role"] == "user"


# ---------------------------------------------------------------------------
# sub-MATCH path is unchanged: KC role re-sync on re-login (by design)
# ---------------------------------------------------------------------------
def test_upsert_sub_match_resyncs_role(flask_core):
    from app.models.user import UserModel

    sub = str(uuid.uuid4())
    email = f"sync_{uuid.uuid4().hex[:8]}@example.com"
    with flask_core.app_context():
        # First login provisions as 'user'.
        UserModel.upsert_from_keycloak(
            sub=sub, email=email, display_name="Sync", role="user",
            email_verified=True,
        )
    with flask_core.app_context():
        # Re-login with an elevated KC role -> sub-match path re-syncs it.
        out = UserModel.upsert_from_keycloak(
            sub=sub, email=email, display_name="Sync", role="manager",
            email_verified=True,
        )
    assert out["role"] == "manager"


# ---------------------------------------------------------------------------
# extract_profile surfaces the email_verified gate input
# ---------------------------------------------------------------------------
def test_extract_profile_surfaces_email_verified_true():
    c = _new_kc_client()
    out = c.extract_profile({"sub": "s", "email": "a@b.com", "email_verified": True})
    assert out["email_verified"] is True


def test_extract_profile_email_verified_false_when_claim_absent():
    c = _new_kc_client()
    out = c.extract_profile({"sub": "s", "email": "a@b.com"})
    # Absent/at-most-truthy claim must collapse to a strict bool False.
    assert out["email_verified"] is False


def test_extract_profile_email_verified_false_when_claim_not_true():
    c = _new_kc_client()
    # A string "true" or any non-bool must NOT be trusted.
    out = c.extract_profile({"sub": "s", "email": "a@b.com", "email_verified": "true"})
    assert out["email_verified"] is False


def test_extract_profile_synthesized_email_is_verified():
    c = _new_kc_client(realm="polymind")
    # Username-only identity -> synthesized address derives from the signed
    # preferred_username, so it is treated as verified.
    out = c.extract_profile({"sub": "s", "preferred_username": "jdoe"})
    assert out["email"] == "jdoe@polymind.kc.local"
    assert out["email_verified"] is True
