"""Direct facade coverage for the user + message model layer.

Mirrors tests/api/test_models_meetings_cov.py (real facades, app_context
bridge, legacy dict-shape ``_id`` alias) and the seeding helpers in
tests/api/test_users.py. No HTTP — every call runs inside
``flask_core.app_context()`` against the isolated ``unichat_*_test`` DB; no
external upstream is touched (these are pure DB facades).

Targets the uncovered ranges in:
  - app/models/user.py     (UserModel facade + _user_to_legacy_dict)
  - app/models/message.py  (MessageModel facade + _serialize_message / _coerce_uuid)
"""
import uuid

import pytest

from app.models.user import (
    UserModel,
    User,
    VALID_USER_ROLES,
    _user_to_legacy_dict,
)
from app.models.message import (
    MessageModel,
    Message,
    _serialize_message,
    _coerce_uuid,
)


# ===========================================================================
# Helpers.
# ===========================================================================
def _mk_conversation(flask_core, user_id, *, title="C", project_id=None):
    """Create a conversation (parent FK for messages) via the real facade."""
    from app.models.conversation import ConversationModel

    with flask_core.app_context():
        conv = ConversationModel.create(
            str(user_id), "quick:openai/gpt-4o", title=title, project_id=project_id
        )
    return conv["_id"]


def _mk_msg(flask_core, cid, role="user", content="hello", **kw):
    with flask_core.app_context():
        return MessageModel.create(cid, role, content, **kw)


# ===========================================================================
# _user_to_legacy_dict — None passthrough + password_hash re-injection.
# ===========================================================================
def test_user_to_legacy_dict_none():
    assert _user_to_legacy_dict(None) is None


def test_user_to_legacy_dict_includes_password_hash(flask_core, test_user):
    with flask_core.app_context():
        row = db_get_user(flask_core, test_user["_id"])
        d = _user_to_legacy_dict(row)
    assert d["_id"] == str(test_user["_id"])
    # password_hash is normally excluded by SerializableMixin; re-injected here.
    assert "password_hash" in d
    assert d["password_hash"] is not None


def db_get_user(flask_core, uid):
    from app.api.core import db
    return db.session.get(User, uuid.UUID(str(uid)))


# ===========================================================================
# UserModel.create — branches: defaults, role validation, display fallbacks.
# ===========================================================================
def test_user_create_happy_defaults(flask_core):
    with flask_core.app_context():
        u = UserModel.create(email="Created@Example.COM", password="Secret123!",
                             display_name="Created User", role="user")
    assert u["email"] == "created@example.com"  # normalized lowercase
    assert u["role"] == "user"
    assert u["profile"]["display_name"] == "Created User"
    # No personal workspace (mig 0026): org membership comes from Keycloak.
    assert u["active_workspace_id"] is None
    assert u["usage"]["messages_sent"] == 0


def test_user_create_display_name_from_email(flask_core):
    with flask_core.app_context():
        u = UserModel.create(email="noname@example.com", password="Secret123!",
                             display_name="")
    # Empty display_name -> derived from the local part of the email.
    assert u["profile"]["display_name"] == "noname"


def test_user_create_invalid_role_raises(flask_core):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            UserModel.create(email="bad@example.com", password="x", role="superuser")


def test_user_create_sso_no_password(flask_core):
    sub = str(uuid.uuid4())
    with flask_core.app_context():
        u = UserModel.create(email="sso@example.com", password=None,
                             display_name="SSO", keycloak_sub=sub)
    # password=None -> password_hash stays None (SSO-only user).
    assert u.get("password_hash") is None
    assert u["keycloak_sub"] == sub


def test_user_create_blank_email_blank_name(flask_core):
    # Both email and display_name blank -> display_name resolves to ''.
    with flask_core.app_context():
        u = UserModel.create(email="", password="Secret123!", display_name="")
    assert u["profile"]["display_name"] == ""


# ===========================================================================
# UserModel.set_role.
# ===========================================================================
def test_set_role_happy(flask_core, plain_user):
    with flask_core.app_context():
        assert UserModel.set_role(plain_user["_id"], "manager") is True
        assert UserModel.find_by_id(plain_user["_id"])["role"] == "manager"


def test_set_role_invalid_raises(flask_core, plain_user):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            UserModel.set_role(plain_user["_id"], "wizard")


def test_set_role_missing_user_false(flask_core):
    with flask_core.app_context():
        assert UserModel.set_role(str(uuid.uuid4()), "admin") is False


# ===========================================================================
# UserModel.find_by_id / find_by_email / find_by_ids — None / bad-id branches.
# ===========================================================================
def test_find_by_id_bad_uuid(flask_core):
    with flask_core.app_context():
        assert UserModel.find_by_id("not-a-uuid") is None


def test_find_by_id_missing(flask_core):
    with flask_core.app_context():
        assert UserModel.find_by_id(str(uuid.uuid4())) is None


def test_find_by_email_blank(flask_core):
    with flask_core.app_context():
        assert UserModel.find_by_email("") is None
        assert UserModel.find_by_email(None) is None


def test_find_by_email_case_insensitive(flask_core, test_user):
    with flask_core.app_context():
        row = UserModel.find_by_email("TEST@GMAIL.COM")
    assert row is not None and row["_id"] == str(test_user["_id"])


def test_find_by_ids_mixed(flask_core, test_user, plain_user):
    with flask_core.app_context():
        rows = UserModel.find_by_ids(
            [test_user["_id"], "garbage", str(plain_user["_id"])]
        )
    ids = {r["_id"] for r in rows}
    assert ids == {str(test_user["_id"]), str(plain_user["_id"])}


def test_find_by_ids_empty_and_all_bad(flask_core):
    with flask_core.app_context():
        assert UserModel.find_by_ids([]) == []
        assert UserModel.find_by_ids(["nope", "also-nope"]) == []


# ===========================================================================
# UserModel.verify_password — all branches (no user, no hash, str/bytes).
# ===========================================================================
def test_verify_password_no_user(flask_core):
    with flask_core.app_context():
        assert UserModel.verify_password(None, "x") is False
        assert UserModel.verify_password({}, "x") is False


def test_verify_password_correct(flask_core, test_user):
    with flask_core.app_context():
        u = UserModel.find_by_email("test@gmail.com")
        assert UserModel.verify_password(u, "TestPassword123!") is True
        assert UserModel.verify_password(u, "WrongPass") is False


def test_verify_password_memoryview_hash(flask_core, test_user):
    with flask_core.app_context():
        u = UserModel.find_by_email("test@gmail.com")
        # Force the memoryview branch.
        u = dict(u)
        u["password_hash"] = memoryview(
            u["password_hash"] if isinstance(u["password_hash"], (bytes, bytearray))
            else u["password_hash"].encode("utf-8")
        )
        assert UserModel.verify_password(u, "TestPassword123!") is True


# ===========================================================================
# UserModel.update — top-level columns, dotted JSONB, blob replace, unknown.
# ===========================================================================
def test_update_missing_user_none(flask_core):
    with flask_core.app_context():
        assert UserModel.update(str(uuid.uuid4()), {"display_name": "x"}) is None


def test_update_dotted_jsonb_key(flask_core, plain_user):
    with flask_core.app_context():
        UserModel.update(plain_user["_id"], {"profile.bio": "Updated bio"})
        row = UserModel.find_by_id(plain_user["_id"])
    assert row["profile"]["bio"] == "Updated bio"


def test_update_dotted_into_nondict_blob(flask_core, plain_user):
    """Dotted key on a real JSONB column whose value isn't a dict yet.

    Force ``status`` to a non-dict value, then a dotted ``status.flag`` update
    must re-init the blob ({}), set the child, flag_modified, and commit —
    exercising the ``not isinstance(blob, dict)`` branch (user.py:264-265).
    """
    with flask_core.app_context():
        # Stomp the status JSONB to a scalar (non-dict) first.
        row = db_get_user(flask_core, plain_user["_id"])
        row.status = "scalar-not-a-dict"
        from app.api.core import db
        db.session.commit()
        UserModel.update(plain_user["_id"], {"status.flag": "v"})
        out = UserModel.find_by_id(plain_user["_id"])
    assert out["status"] == {"flag": "v"}


def test_update_role_and_email_and_display(flask_core, plain_user):
    with flask_core.app_context():
        UserModel.update(plain_user["_id"], {
            "role": "manager",
            "email": "renamed@example.com",
            "display_name": "Renamed",
        })
        row = UserModel.find_by_id(plain_user["_id"])
    assert row["role"] == "manager"
    assert row["email"] == "renamed@example.com"
    assert row["display_name"] == "Renamed"


def test_update_blob_replace(flask_core, plain_user):
    with flask_core.app_context():
        UserModel.update(plain_user["_id"], {
            "settings": {"theme": "light", "x": 1},
            "ai_preferences": {"enabled": False},
        })
        row = UserModel.find_by_id(plain_user["_id"])
    assert row["settings"]["theme"] == "light"
    assert row["ai_preferences"]["enabled"] is False


def test_update_active_workspace_and_keycloak(flask_core, plain_user):
    sub = str(uuid.uuid4())
    with flask_core.app_context():
        UserModel.update(plain_user["_id"], {
            "active_workspace_id": None,
            "keycloak_sub": sub,
            "password_hash": b"fakehashbytes",  # LargeBinary column => bytes
        })
        row = db_get_user(flask_core, plain_user["_id"])
        active_ws = row.active_workspace_id
        kc = str(row.keycloak_sub)
        ph = bytes(row.password_hash)
    assert active_ws is None
    assert kc == sub
    assert ph == b"fakehashbytes"


def test_update_unknown_key_falls_to_settings(flask_core, plain_user):
    with flask_core.app_context():
        UserModel.update(plain_user["_id"], {"some_random_pref": "abc"})
        row = UserModel.find_by_id(plain_user["_id"])
    assert row["settings"]["some_random_pref"] == "abc"


def test_update_hasattr_column_branch(flask_core, plain_user):
    # 'created_at' is a real column -> hits the hasattr setattr branch.
    from datetime import datetime
    new_dt = datetime(2020, 1, 1, 0, 0, 0)
    with flask_core.app_context():
        UserModel.update(plain_user["_id"], {"created_at": new_dt})
        row = db_get_user(flask_core, plain_user["_id"])
        year = row.created_at.year
    assert year == 2020


# ===========================================================================
# UserModel.update_last_active / increment_usage.
# ===========================================================================
def test_update_last_active_bad_uuid(flask_core):
    with flask_core.app_context():
        assert UserModel.update_last_active("bad") is None


def test_update_last_active_missing(flask_core):
    with flask_core.app_context():
        assert UserModel.update_last_active(str(uuid.uuid4())) is None


def test_update_last_active_ok(flask_core, plain_user):
    with flask_core.app_context():
        u = UserModel.update_last_active(plain_user["_id"])
        assert u is not None
        assert "last_active" in u.usage


def test_increment_usage_missing(flask_core):
    with flask_core.app_context():
        assert UserModel.increment_usage(str(uuid.uuid4())) is None


def test_increment_usage_ok(flask_core, plain_user):
    with flask_core.app_context():
        UserModel.increment_usage(plain_user["_id"], messages=3, tokens=50)
        UserModel.increment_usage(plain_user["_id"], messages=2, tokens=10)
        row = UserModel.find_by_id(plain_user["_id"])
    assert row["usage"]["messages_sent"] == 5
    assert row["usage"]["tokens_used"] == 60


# ===========================================================================
# UserModel ban / unban.
# ===========================================================================
def test_ban_user_missing(flask_core):
    with flask_core.app_context():
        assert UserModel.ban_user(str(uuid.uuid4()), "reason", None) is None


def test_ban_then_unban(flask_core, plain_user, admin_user):
    with flask_core.app_context():
        UserModel.ban_user(plain_user["_id"], "spam", admin_id=admin_user["_id"])
        row = UserModel.find_by_id(plain_user["_id"])
        assert row["status"]["is_banned"] is True
        assert row["status"]["ban_reason"] == "spam"
        assert row["status"]["banned_by"] == str(admin_user["_id"])

        UserModel.unban_user(plain_user["_id"])
        row2 = UserModel.find_by_id(plain_user["_id"])
    assert row2["status"]["is_banned"] is False
    assert row2["status"]["ban_reason"] is None


def test_unban_user_missing(flask_core):
    with flask_core.app_context():
        assert UserModel.unban_user(str(uuid.uuid4())) is None


# ===========================================================================
# UserModel.count (include_banned filter).
#
# ``get_all`` was removed in the 2026-06-15 facade cleanup (the admin user-list
# route lists via an inline ``select(User)`` query, not a model facade). ``count``
# is still live (admin analytics, admin.py). This locks the ``include_banned``
# filter: a banned user is counted only when ``include_banned=True``.
# ===========================================================================
def test_count_include_banned_filter(flask_core, plain_user, banned_user):
    with flask_core.app_context():
        total = UserModel.count(include_banned=True)
        active = UserModel.count(include_banned=False)
    # The banned user is in the total but excluded from the active count, so the
    # banned-inclusive count is strictly larger by at least that one row.
    assert total > active
    assert total - active >= 1


# ===========================================================================
# UserModel.find_by_keycloak_sub + upsert_from_keycloak.
# ===========================================================================
def test_find_by_keycloak_sub_blank_and_bad(flask_core):
    with flask_core.app_context():
        assert UserModel.find_by_keycloak_sub(None) is None
        assert UserModel.find_by_keycloak_sub("") is None
        assert UserModel.find_by_keycloak_sub("not-a-uuid") is None
        assert UserModel.find_by_keycloak_sub(str(uuid.uuid4())) is None


def test_upsert_from_keycloak_creates_new(flask_core):
    sub = str(uuid.uuid4())
    with flask_core.app_context():
        u = UserModel.upsert_from_keycloak(sub, "kc@example.com", "KC User", "user")
        found = UserModel.find_by_keycloak_sub(sub)
    assert u["email"] == "kc@example.com"
    assert found is not None and found["_id"] == u["_id"]


def test_upsert_from_keycloak_updates_existing_by_sub(flask_core):
    sub = str(uuid.uuid4())
    with flask_core.app_context():
        UserModel.upsert_from_keycloak(sub, "kc2@example.com", "Old Name", "user")
        # Re-login with a new role + email + display name -> update branch.
        u = UserModel.upsert_from_keycloak(sub, "kc2new@example.com", "New Name", "manager")
        row = UserModel.find_by_keycloak_sub(sub)
    assert u["role"] == "manager"
    assert row["email"] == "kc2new@example.com"
    assert row["profile"]["display_name"] == "New Name"


def test_upsert_from_keycloak_no_change_branch(flask_core):
    sub = str(uuid.uuid4())
    with flask_core.app_context():
        UserModel.upsert_from_keycloak(sub, "same@example.com", "Same", "user")
        # Identical payload -> changed stays False, no commit.
        u = UserModel.upsert_from_keycloak(sub, "same@example.com", "Same", "user")
    assert u["email"] == "same@example.com"


def test_upsert_from_keycloak_refuses_link_to_password_backed_email(flask_core):
    """SECURE contract (#2): the by-email fallback must NOT auto-link a fresh
    SSO ``sub`` onto a PASSWORD-BACKED row (the account-takeover surface) — even
    with a verified email — and must NOT overwrite that row's role. Refusal
    raises ``APIError`` (409); the row is left untouched."""
    from app.utils.errors import APIError

    sub = str(uuid.uuid4())
    with flask_core.app_context():
        existing = UserModel.create(email="link@example.com", password="Secret123!",
                                    display_name="Link", role="user")
        with pytest.raises(APIError) as exc:
            UserModel.upsert_from_keycloak(
                sub, "link@example.com", "Link", "manager", email_verified=True,
            )
        assert exc.value.status_code == 409
        row = db_get_user(flask_core, existing["_id"])
        kc = row.keycloak_sub
        role = row.role
    # Sub NOT rebound, role NOT overwritten.
    assert kc is None
    assert role == "user"
    with flask_core.app_context():
        assert UserModel.find_by_keycloak_sub(sub) is None


def test_upsert_from_keycloak_links_passwordless_user_no_role_overwrite(flask_core):
    """SECURE contract (#2): a PASSWORDLESS plain-``user`` row with a VERIFIED
    email is safe to link — the sub binds, but the pre-existing role is
    preserved (KC role is NOT applied on a by-email link)."""
    sub = str(uuid.uuid4())
    with flask_core.app_context():
        existing = UserModel.create(email="link2@example.com", password=None,
                                    display_name="Link2", role="user")
        u = UserModel.upsert_from_keycloak(
            sub, "link2@example.com", "Link2", "manager", email_verified=True,
        )
        row = db_get_user(flask_core, existing["_id"])
        kc = str(row.keycloak_sub)
        role = row.role
    assert u["_id"] == existing["_id"]
    assert kc == sub
    # KC said 'manager' on a by-email link -> ignored; stays 'user'.
    assert role == "user"


# ===========================================================================
# AI preferences + timezone helpers.
# ===========================================================================
def test_get_default_ai_preferences():
    d = UserModel.get_default_ai_preferences()
    assert d["enabled"] is True
    assert d["user_info"]["language"] == "English"
    assert d["custom_instructions"] == ""


def test_get_ai_preferences_bad_uuid_returns_default(flask_core):
    with flask_core.app_context():
        d = UserModel.get_ai_preferences("bad")
    assert d == UserModel.get_default_ai_preferences()


def test_get_ai_preferences_existing(flask_core, plain_user):
    with flask_core.app_context():
        UserModel.update(plain_user["_id"], {"ai_preferences": {"enabled": False}})
        d = UserModel.get_ai_preferences(plain_user["_id"])
    assert d == {"enabled": False}


def test_get_ai_preferences_empty_returns_default(flask_core, plain_user):
    # Fresh user has ai_preferences = {} -> falsy -> default returned.
    with flask_core.app_context():
        d = UserModel.get_ai_preferences(plain_user["_id"])
    assert d == UserModel.get_default_ai_preferences()


def test_update_ai_preferences_missing(flask_core):
    with flask_core.app_context():
        assert UserModel.update_ai_preferences(str(uuid.uuid4()), {"enabled": True}) is None


def test_update_ai_preferences_merge_all_sections(flask_core, plain_user):
    with flask_core.app_context():
        UserModel.update_ai_preferences(plain_user["_id"], {
            "user_info": {"name": "Sam"},
            "behavior": {"tone": "casual"},
            "enabled": False,
            "custom_instructions": "z" * 3000,  # truncated to 2000
        })
        prefs = UserModel.get_ai_preferences(plain_user["_id"])
    assert prefs["user_info"]["name"] == "Sam"
    assert prefs["behavior"]["tone"] == "casual"
    assert prefs["enabled"] is False
    assert len(prefs["custom_instructions"]) == 2000
    assert prefs["updated_at"] is not None


def test_update_timezone_valid(flask_core, plain_user):
    with flask_core.app_context():
        UserModel.update_timezone(plain_user["_id"], "America/New_York")
        assert UserModel.get_timezone(plain_user["_id"]) == "America/New_York"


def test_update_timezone_invalid_raises(flask_core, plain_user):
    import zoneinfo
    with flask_core.app_context():
        with pytest.raises(zoneinfo.ZoneInfoNotFoundError):
            UserModel.update_timezone(plain_user["_id"], "Not/AZone")


def test_update_timezone_missing_user(flask_core):
    with flask_core.app_context():
        assert UserModel.update_timezone(str(uuid.uuid4()), "UTC") is None


def test_get_timezone_default(flask_core, plain_user):
    with flask_core.app_context():
        assert UserModel.get_timezone(plain_user["_id"]) == "UTC"
        assert UserModel.get_timezone("bad") == "UTC"


# ===========================================================================
# UserModel.set_active_workspace / null helpers.
# ===========================================================================
def test_null_active_workspace_for_workspace(flask_core, plain_user):
    with flask_core.app_context():
        wid = plain_user["active_workspace_id"]
        n = UserModel.null_active_workspace_for_workspace(wid)
        assert n >= 1
        assert db_get_user(flask_core, plain_user["_id"]).active_workspace_id is None


def test_null_active_workspace_for_workspace_bad_uuid(flask_core):
    with flask_core.app_context():
        assert UserModel.null_active_workspace_for_workspace("bad") == 0


def test_null_active_workspace_for_user_if_match(flask_core, plain_user):
    with flask_core.app_context():
        wid = plain_user["active_workspace_id"]
        # Mismatch -> 0
        assert UserModel.null_active_workspace_for_user_if_match(
            plain_user["_id"], str(uuid.uuid4())
        ) == 0
        # Match -> 1
        assert UserModel.null_active_workspace_for_user_if_match(
            plain_user["_id"], wid
        ) == 1


def test_null_active_workspace_for_user_if_match_bad_uuid(flask_core):
    with flask_core.app_context():
        assert UserModel.null_active_workspace_for_user_if_match("bad", "bad") == 0


# ===========================================================================
# UserModel.ensure_default_admin.
# ===========================================================================
def test_ensure_default_admin_creates(flask_core):
    with flask_core.app_context():
        u = UserModel.ensure_default_admin("freshadmin@example.com", "AdminPass123!")
    assert u["role"] == "admin"


def test_ensure_default_admin_promotes_existing(flask_core):
    with flask_core.app_context():
        UserModel.create(email="promote@example.com", password="Secret123!", role="user")
        u = UserModel.ensure_default_admin("promote@example.com", "ignored")
        row = UserModel.find_by_email("promote@example.com")
    assert row["role"] == "admin"


def test_ensure_default_admin_already_admin(flask_core, admin_user):
    with flask_core.app_context():
        u = UserModel.ensure_default_admin("admin@gmail.com", "ignored")
    assert u["role"] == "admin"


def test_valid_user_roles_constant():
    assert VALID_USER_ROLES == {"user", "manager", "admin"}


# ===========================================================================
# ===========================================================================
#  MESSAGE MODEL
# ===========================================================================
# ===========================================================================


# ---- _coerce_uuid -----------------------------------------------------------
def test_msg_coerce_uuid_none_and_empty():
    assert _coerce_uuid(None) is None
    assert _coerce_uuid("") is None
    assert _coerce_uuid(b"") is None


def test_msg_coerce_uuid_passthrough():
    u = uuid.uuid4()
    assert _coerce_uuid(u) is u


def test_msg_coerce_uuid_bytes():
    u = uuid.uuid4()
    assert _coerce_uuid(str(u).encode("utf-8")) == u


def test_msg_coerce_uuid_bad_string():
    assert _coerce_uuid("not-a-uuid") is None


def test_msg_coerce_uuid_other_type():
    assert _coerce_uuid(12345) is None


# ---- _serialize_message -----------------------------------------------------
def test_serialize_message_none():
    assert _serialize_message(None) is None


# ---- create / _next_seq -----------------------------------------------------
def test_msg_next_seq_bad_conversation(flask_core):
    with flask_core.app_context():
        assert MessageModel._next_seq("bad") == 0


def test_msg_create_bad_conversation_raises(flask_core):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            MessageModel.create("bad", "user", "hi")


def test_msg_create_and_serialize(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m = _mk_msg(flask_core, cid, role="user", content="hello world",
                attachments=[{"name": "f.txt"}], metadata={"k": "v"})
    # metadata aliased back from message_metadata.
    assert m["metadata"] == {"k": "v"}
    assert m["attachments"] == [{"name": "f.txt"}]
    assert m["role"] == "user"
    assert m["content"] == "hello world"
    assert m["seq"] >= 1


def test_msg_create_defaults(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m = _mk_msg(flask_core, cid)
    assert m["attachments"] == []
    assert m["metadata"] == {}
    assert m["branch_id"] == "main"


def test_msg_seq_monotonic(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    a = _mk_msg(flask_core, cid, content="a")
    b = _mk_msg(flask_core, cid, content="b")
    assert b["seq"] > a["seq"]


# ---- create_user_message / create_assistant_message / create_error_message --
def test_msg_create_user_message(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    with flask_core.app_context():
        m = MessageModel.create_user_message(cid, "hi there", metadata={"a": 1})
    assert m["role"] == "user"
    assert m["metadata"] == {"a": 1}


def test_msg_create_assistant_message(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    with flask_core.app_context():
        m = MessageModel.create_assistant_message(
            cid, "answer", model_id="openai/gpt-4o",
            prompt_tokens=10, completion_tokens=20,
            generation_time_ms=500, finish_reason="stop",
        )
    assert m["role"] == "assistant"
    assert m["metadata"]["model_id"] == "openai/gpt-4o"
    assert m["metadata"]["tokens"] == {"prompt": 10, "completion": 20}
    assert m["metadata"]["generation_time_ms"] == 500


def test_msg_create_error_message(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    with flask_core.app_context():
        m = MessageModel.create_error_message(cid, "boom", model_id="m1")
    assert m["is_error"] is True
    assert m["error_message"] == "boom"
    assert m["metadata"]["model_id"] == "m1"


def test_msg_create_error_message_bad_conversation_raises(flask_core):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            MessageModel.create_error_message("bad", "boom")


# ---- find_by_conversation / find_by_id / pagination / branch filter ---------
def test_msg_find_by_conversation_bad(flask_core):
    with flask_core.app_context():
        assert MessageModel.find_by_conversation("bad") == []


def test_msg_find_by_conversation_and_branch(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    _mk_msg(flask_core, cid, content="main-1")
    _mk_msg(flask_core, cid, content="alt-1", branch_id="alt")
    with flask_core.app_context():
        all_rows = MessageModel.find_by_conversation(cid)
        main_rows = MessageModel.find_by_conversation(cid, branch_id="main")
        alt_rows = MessageModel.find_by_conversation(cid, branch_id="alt")
    assert len(all_rows) == 2
    assert len(main_rows) == 1 and main_rows[0]["content"] == "main-1"
    assert len(alt_rows) == 1 and alt_rows[0]["content"] == "alt-1"


def test_msg_find_by_conversation_pagination(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    for i in range(3):
        _mk_msg(flask_core, cid, content=f"m{i}")
    with flask_core.app_context():
        page = MessageModel.find_by_conversation(cid, skip=1, limit=1)
    assert len(page) == 1


def test_msg_find_by_id_bad_and_missing(flask_core):
    with flask_core.app_context():
        assert MessageModel.find_by_id("bad") is None
        assert MessageModel.find_by_id(str(uuid.uuid4())) is None


def test_msg_find_by_id_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m = _mk_msg(flask_core, cid, content="findme")
    with flask_core.app_context():
        row = MessageModel.find_by_id(m["_id"])
    assert row["content"] == "findme"


# ---- update_content / update_with_edit_history ------------------------------
def test_msg_update_content_bad(flask_core):
    with flask_core.app_context():
        assert MessageModel.update_content("bad", "x") is None


def test_msg_update_content_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m = _mk_msg(flask_core, cid, content="old")
    with flask_core.app_context():
        MessageModel.update_content(m["_id"], "new content")
        row = MessageModel.find_by_id(m["_id"])
    assert row["content"] == "new content"


def test_msg_update_with_edit_history_bad(flask_core):
    with flask_core.app_context():
        assert MessageModel.update_with_edit_history("bad", "x", []) is None


def test_msg_update_with_edit_history_missing(flask_core):
    with flask_core.app_context():
        assert MessageModel.update_with_edit_history(str(uuid.uuid4()), "x", []) is None


def test_msg_update_with_edit_history_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m = _mk_msg(flask_core, cid, content="v1")
    with flask_core.app_context():
        MessageModel.update_with_edit_history(m["_id"], "v2", [{"content": "v1"}])
        row = MessageModel.find_by_id(m["_id"])
    assert row["content"] == "v2"
    assert row["metadata"]["is_edited"] is True
    assert row["metadata"]["edit_history"] == [{"content": "v1"}]
    assert "edited_at" in row["metadata"]


# ---- find_meeting_seed ------------------------------------------------------
def test_msg_find_meeting_seed_none(flask_core):
    with flask_core.app_context():
        assert MessageModel.find_meeting_seed(str(uuid.uuid4())) is None


def test_msg_find_meeting_seed_match(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    meeting_id = str(uuid.uuid4())
    with flask_core.app_context():
        MessageModel.create(
            cid, "system", "seed",
            metadata={"source": "meeting", "meeting_id": meeting_id},
        )
        out = MessageModel.find_meeting_seed(meeting_id)
    assert out is not None
    assert out["metadata"]["meeting_id"] == meeting_id


# ---- mark_error / update_content_and_metadata / update_metadata -------------
def test_msg_mark_error_bad(flask_core):
    with flask_core.app_context():
        assert MessageModel.mark_error("bad", "e") is None


def test_msg_mark_error_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m = _mk_msg(flask_core, cid)
    with flask_core.app_context():
        MessageModel.mark_error(m["_id"], "failed")
        row = MessageModel.find_by_id(m["_id"])
    assert row["is_error"] is True
    assert row["error_message"] == "failed"


def test_msg_update_content_and_metadata_bad(flask_core):
    with flask_core.app_context():
        assert MessageModel.update_content_and_metadata("bad", "x", {}) is None


def test_msg_update_content_and_metadata_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m = _mk_msg(flask_core, cid, content="c0")
    with flask_core.app_context():
        MessageModel.update_content_and_metadata(m["_id"], "c1", {"x": 1})
        row = MessageModel.find_by_id(m["_id"])
    assert row["content"] == "c1"
    assert row["metadata"] == {"x": 1}


def test_msg_update_metadata_bad(flask_core):
    with flask_core.app_context():
        assert MessageModel.update_metadata("bad", {}) is None


def test_msg_update_metadata_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m = _mk_msg(flask_core, cid, metadata={"old": 1})
    with flask_core.app_context():
        MessageModel.update_metadata(m["_id"], {"new": 2})
        row = MessageModel.find_by_id(m["_id"])
    assert row["metadata"] == {"new": 2}


# ---- merge_metadata ---------------------------------------------------------
def test_msg_merge_metadata_bad_and_empty(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m = _mk_msg(flask_core, cid)
    with flask_core.app_context():
        assert MessageModel.merge_metadata("bad", {"a": 1}) is None
        assert MessageModel.merge_metadata(m["_id"], {}) is None  # empty patch
        assert MessageModel.merge_metadata(m["_id"], None) is None


def test_msg_merge_metadata_missing(flask_core):
    with flask_core.app_context():
        assert MessageModel.merge_metadata(str(uuid.uuid4()), {"a": 1}) is None


def test_msg_merge_metadata_preserves(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m = _mk_msg(flask_core, cid, metadata={"model_id": "m1", "keep": True})
    with flask_core.app_context():
        MessageModel.merge_metadata(m["_id"], {"annotations": ["a"]})
        row = MessageModel.find_by_id(m["_id"])
    assert row["metadata"]["model_id"] == "m1"
    assert row["metadata"]["keep"] is True
    assert row["metadata"]["annotations"] == ["a"]


# ---- update_attachments -----------------------------------------------------
def test_msg_update_attachments_bad_and_missing(flask_core):
    with flask_core.app_context():
        assert MessageModel.update_attachments("bad", []) is None
        assert MessageModel.update_attachments(str(uuid.uuid4()), []) is None


def test_msg_update_attachments_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m = _mk_msg(flask_core, cid)
    with flask_core.app_context():
        MessageModel.update_attachments(m["_id"], [{"name": "x.pdf"}])
        row = MessageModel.find_by_id(m["_id"])
    assert row["attachments"] == [{"name": "x.pdf"}]


def test_msg_update_attachments_none_clears(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m = _mk_msg(flask_core, cid, attachments=[{"name": "a"}])
    with flask_core.app_context():
        MessageModel.update_attachments(m["_id"], None)
        row = MessageModel.find_by_id(m["_id"])
    assert row["attachments"] == []


# ---- delete / delete_by_conversation / count_by_conversation ----------------
def test_msg_delete_bad(flask_core):
    with flask_core.app_context():
        assert MessageModel.delete("bad") is None


def test_msg_delete_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m = _mk_msg(flask_core, cid)
    with flask_core.app_context():
        MessageModel.delete(m["_id"])
        assert MessageModel.find_by_id(m["_id"]) is None


def test_msg_delete_by_conversation_bad(flask_core):
    with flask_core.app_context():
        assert MessageModel.delete_by_conversation("bad") is None


def test_msg_delete_by_conversation_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    _mk_msg(flask_core, cid, content="a")
    _mk_msg(flask_core, cid, content="b")
    with flask_core.app_context():
        MessageModel.delete_by_conversation(cid)
        assert MessageModel.count_by_conversation(cid) == 0


def test_msg_count_by_conversation_bad(flask_core):
    with flask_core.app_context():
        assert MessageModel.count_by_conversation("bad") == 0


def test_msg_count_by_conversation_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    _mk_msg(flask_core, cid, content="x")
    _mk_msg(flask_core, cid, content="y")
    with flask_core.app_context():
        assert MessageModel.count_by_conversation(cid) == 2


# ---- get_context_messages ---------------------------------------------------
def test_msg_get_context_bad(flask_core):
    with flask_core.app_context():
        assert MessageModel.get_context_messages("bad") == []


def test_msg_get_context_excludes_errors_and_branch(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    _mk_msg(flask_core, cid, content="ok1")
    with flask_core.app_context():
        MessageModel.create_error_message(cid, "err")
    _mk_msg(flask_core, cid, content="ok2", branch_id="alt")
    with flask_core.app_context():
        ctx_all = MessageModel.get_context_messages(cid, limit=20)
        ctx_main = MessageModel.get_context_messages(cid, limit=20, branch_id="main")
    contents_all = [m["content"] for m in ctx_all]
    assert "err" not in contents_all  # errors excluded
    assert "ok1" in contents_all and "ok2" in contents_all
    # main branch only -> ok1, not the alt-branch ok2.
    contents_main = [m["content"] for m in ctx_main]
    assert "ok1" in contents_main and "ok2" not in contents_main


# ---- search_in_conversations + search_in_user_conversations -----------------
def test_msg_search_in_conversations_empty(flask_core):
    with flask_core.app_context():
        assert MessageModel.search_in_conversations([], "x") == []
        assert MessageModel.search_in_conversations(["cid"], "") == []
        assert MessageModel.search_in_conversations(["bad-id"], "x") == []


def test_msg_search_in_conversations_match(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"], title="Searchable")
    _mk_msg(flask_core, cid, content="needle in haystack")
    _mk_msg(flask_core, cid, content="nothing here")
    with flask_core.app_context():
        hits = MessageModel.search_in_conversations([cid], "needle")
    assert len(hits) == 1
    assert hits[0]["content"] == "needle in haystack"
    assert hits[0]["conversation_title"] == "Searchable"
    assert hits[0]["score"] == 1.0


def test_msg_search_in_user_conversations_empty_query(flask_core, test_user):
    with flask_core.app_context():
        assert MessageModel.search_in_user_conversations(
            test_user["_id"], "", []
        ) == []


def test_msg_search_in_user_conversations_bad_user(flask_core):
    with flask_core.app_context():
        assert MessageModel.search_in_user_conversations("bad", "x", []) == []


def test_msg_search_in_user_conversations_personal_scope(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"], title="Personal")
    _mk_msg(flask_core, cid, content="findable text")
    with flask_core.app_context():
        # No accessible projects -> only personal-scope (project_id IS NULL).
        hits = MessageModel.search_in_user_conversations(
            test_user["_id"], "findable", []
        )
    assert len(hits) == 1
    assert hits[0]["content"] == "findable text"


def test_msg_search_in_user_conversations_with_accessible(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"], title="P2")
    _mk_msg(flask_core, cid, content="alpha beta gamma")
    with flask_core.app_context():
        # Passing accessible project ids (incl. a bad one) exercises the
        # accessible_uuids branch; personal-scope row still matches.
        hits = MessageModel.search_in_user_conversations(
            test_user["_id"], "beta", [str(uuid.uuid4()), "bad-id"]
        )
    assert any(h["content"] == "alpha beta gamma" for h in hits)


# ---- delete_after_message / find_up_to --------------------------------------
def test_msg_delete_after_bad_ids(flask_core):
    with flask_core.app_context():
        assert MessageModel.delete_after_message("bad", "bad") == 0


def test_msg_delete_after_missing_target(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert MessageModel.delete_after_message(cid, str(uuid.uuid4())) == 0


def test_msg_delete_after_message_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m1 = _mk_msg(flask_core, cid, content="keep")
    import time
    time.sleep(0.01)
    _mk_msg(flask_core, cid, content="drop1")
    _mk_msg(flask_core, cid, content="drop2")
    with flask_core.app_context():
        n = MessageModel.delete_after_message(cid, m1["_id"], branch_id="main")
        remaining = [m["content"] for m in MessageModel.find_by_conversation(cid)]
    assert n == 2
    assert remaining == ["keep"]


def test_msg_find_up_to_bad_ids(flask_core):
    with flask_core.app_context():
        assert MessageModel.find_up_to("bad", "bad") == []


def test_msg_find_up_to_missing_target(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert MessageModel.find_up_to(cid, str(uuid.uuid4())) == []


def test_msg_find_up_to_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m1 = _mk_msg(flask_core, cid, content="a")
    import time
    time.sleep(0.01)
    m2 = _mk_msg(flask_core, cid, content="b")
    time.sleep(0.01)
    _mk_msg(flask_core, cid, content="c")
    with flask_core.app_context():
        rows = MessageModel.find_up_to(cid, m2["_id"], branch_id="main")
    contents = [r["content"] for r in rows]
    assert contents == ["a", "b"]


# ---- copy_to_branch / copy_many_to_branch / _build_branch_copy --------------
def test_msg_copy_to_branch_missing_conversation_raises(flask_core):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            MessageModel.copy_to_branch({"role": "user", "content": "x"}, "alt")


def test_msg_copy_to_branch_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    src = _mk_msg(flask_core, cid, content="orig", metadata={"model_id": "m"})
    with flask_core.app_context():
        copy = MessageModel.copy_to_branch(src, "alt")
    assert copy["branch_id"] == "alt"
    assert copy["content"] == "orig"
    assert copy["seq"] > src["seq"]  # fresh monotonic seq


def test_msg_copy_to_branch_with_edit_fields(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    src = _mk_msg(flask_core, cid, content="edited-src")
    # Inject legacy root-level edit fields + a string created_at.
    src = dict(src)
    src["is_edited"] = True
    src["edit_history"] = [{"content": "v0"}]
    src["edited_at"] = "2026-01-01T00:00:00"
    src["created_at"] = "2026-01-01T00:00:00"
    with flask_core.app_context():
        copy = MessageModel.copy_to_branch(src, "branch2")
    assert copy["metadata"]["is_edited"] is True
    assert copy["metadata"]["edit_history"] == [{"content": "v0"}]
    assert copy["metadata"]["edited_at"] == "2026-01-01T00:00:00"


def test_msg_copy_to_branch_datetime_created_at(flask_core, test_user):
    from datetime import datetime
    cid = _mk_conversation(flask_core, test_user["_id"])
    src = _mk_msg(flask_core, cid, content="dt-src")
    src = dict(src)
    src["edited_at"] = datetime(2025, 5, 5, 12, 0, 0)
    src["created_at"] = datetime(2025, 5, 5, 12, 0, 0)
    with flask_core.app_context():
        copy = MessageModel.copy_to_branch(src, "branch3")
    assert copy["metadata"]["edited_at"] == "2025-05-05T12:00:00"


def test_msg_copy_to_branch_bad_created_at_string(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    src = _mk_msg(flask_core, cid, content="bad-dt")
    src = dict(src)
    src["created_at"] = "garbage-not-a-date"
    with flask_core.app_context():
        # Unparseable created_at -> set to None, server_default kicks in (no raise).
        copy = MessageModel.copy_to_branch(src, "branch4")
    assert copy["branch_id"] == "branch4"


def test_msg_copy_many_to_branch_empty(flask_core):
    with flask_core.app_context():
        assert MessageModel.copy_many_to_branch([], "alt") == []


def test_msg_copy_many_to_branch_missing_conversation_raises(flask_core):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            MessageModel.copy_many_to_branch([{"role": "user", "content": "x"}], "alt")


def test_msg_copy_many_to_branch_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    m1 = _mk_msg(flask_core, cid, content="m1")
    m2 = _mk_msg(flask_core, cid, content="m2")
    with flask_core.app_context():
        copies = MessageModel.copy_many_to_branch([m1, m2], "newbranch")
    assert [c["content"] for c in copies] == ["m1", "m2"]
    assert all(c["branch_id"] == "newbranch" for c in copies)
    # Contiguous, strictly-increasing seqs.
    assert copies[1]["seq"] == copies[0]["seq"] + 1


# ---- delete_by_branch -------------------------------------------------------
def test_msg_delete_by_branch_bad(flask_core):
    with flask_core.app_context():
        assert MessageModel.delete_by_branch("bad", "alt") == 0


def test_msg_delete_by_branch_ok(flask_core, test_user):
    cid = _mk_conversation(flask_core, test_user["_id"])
    _mk_msg(flask_core, cid, content="main", branch_id="main")
    _mk_msg(flask_core, cid, content="alt1", branch_id="alt")
    _mk_msg(flask_core, cid, content="alt2", branch_id="alt")
    with flask_core.app_context():
        n = MessageModel.delete_by_branch(cid, "alt")
        remaining = [m["branch_id"] for m in MessageModel.find_by_conversation(cid)]
    assert n == 2
    assert remaining == ["main"]
