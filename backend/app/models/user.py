from datetime import datetime
import bcrypt
from sqlalchemy import cast, select, update as sa_update, func, text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: F401
from sqlalchemy.orm.attributes import flag_modified
from app.extensions import db
from app.utils.ids import to_uuid

VALID_USER_ROLES = {'user', 'manager', 'admin'}

# bcrypt truncates the input at 72 bytes; everything past that is silently
# ignored, so two distinct >72-byte passwords sharing a 72-byte prefix would
# verify against each other. We REJECT >72-byte passwords at validation rather
# than pre-hash (pre-hashing changes the input and would invalidate every
# existing stored hash, including the break-glass admin's).
BCRYPT_MAX_PASSWORD_BYTES = 72


def password_within_bcrypt_limit(password: str) -> bool:
    """True when *password* fits bcrypt's 72-byte input window."""
    return len((password or '').encode('utf-8')) <= BCRYPT_MAX_PASSWORD_BYTES


# Fixed, precomputed bcrypt hash used as a constant-time decoy: when no account
# matches a login email we still run a full bcrypt verification against this so
# the unknown-email and wrong-password paths do equal cryptographic work
# (closes the login timing user-enumeration oracle). Computed once at import.
_DUMMY_BCRYPT_HASH = bcrypt.hashpw(b'x', bcrypt.gensalt())


def dummy_password_verify(password: str) -> bool:
    """Run a throw-away bcrypt comparison to match the cost of a real verify.

    Always returns ``False``; the point is the elapsed time, not the result.
    """
    try:
        pw = (password or '')[:BCRYPT_MAX_PASSWORD_BYTES].encode('utf-8')
        bcrypt.checkpw(pw, _DUMMY_BCRYPT_HASH)
    except Exception:  # noqa: BLE001 — decoy must never raise into the caller
        pass
    return False


def _user_to_legacy_dict(user) -> dict | None:
    """Render a :class:`User` ORM row in the legacy Mongo dict shape.

    Routes still read ``user['profile']['display_name']`` etc.; the JSONB
    columns already hold those nested structures so this is mostly a
    SerializableMixin pass-through with a couple of column renames.
    """
    if user is None:
        return None
    d = user.to_dict()
    # `to_dict()` already emits `_id` (str) + `id` (str). We additionally
    # expose `_id` as the canonical Mongo-style identifier the routes use.
    # `password_hash` is excluded by SerializableMixin; add it back for the
    # auth code path which expects to read the bcrypt blob.
    if user.password_hash is not None:
        d['password_hash'] = user.password_hash
    return d


class UserModel:
    collection_name = 'users'

    @staticmethod
    def set_role(user_id, role: str) -> bool:
        """Set a user's global role. Validates against VALID_USER_ROLES."""
        if role not in VALID_USER_ROLES:
            raise ValueError(f"Invalid role: {role!r}. Must be one of {VALID_USER_ROLES}")
        from app.models.user import User
        uid = to_uuid(user_id)
        result = db.session.execute(
            sa_update(User)
            .where(User.id == uid)
            .values(role=role, updated_at=datetime.utcnow())
        )
        db.session.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    def create(email, password=None, display_name='', role='user', keycloak_sub=None, locale=None):
        """Create a new user. Org membership comes from Keycloak sync / invites.

        Returns the new user as a legacy-shaped dict.
        """
        if role not in VALID_USER_ROLES:
            raise ValueError(f"Invalid role: {role!r}. Must be one of {VALID_USER_ROLES}")

        if password is not None and not password_within_bcrypt_limit(password):
            raise ValueError(
                f'Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes'
            )

        password_hash = (
            bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            if password is not None
            else None
        )

        normalized_email = email.lower().strip() if email else ''
        resolved_display_name = (display_name or '').strip()
        if not resolved_display_name:
            resolved_display_name = (
                normalized_email.split('@')[0] if normalized_email else ''
            )

        now = datetime.utcnow()
        profile = {
            'display_name': resolved_display_name,
            'avatar_url': None,
            'bio': '',
        }
        settings = {
            'default_config_id': None,
            'theme': 'dark',
            'notifications_enabled': True,
        }
        if locale in ('fa', 'en'):
            settings['locale'] = locale
        usage = {
            'messages_sent': 0,
            'tokens_used': 0,
            'tokens_limit': -1,
            'last_active': now.isoformat(),
        }
        status = {
            'is_banned': False,
            'ban_reason': None,
            'banned_at': None,
            'banned_by': None,
        }

        from app.models.user import User
        user = User(
            email=normalized_email,
            password_hash=password_hash,
            role=role,
            display_name=resolved_display_name,
            keycloak_sub=to_uuid(keycloak_sub) if keycloak_sub else None,
            profile=profile,
            settings=settings,
            usage=usage,
            status=status,
            ai_preferences={},
            created_at=now,
            updated_at=now,
        )
        db.session.add(user)
        db.session.commit()

        return _user_to_legacy_dict(user)

    @staticmethod
    def set_active_workspace(user_id, workspace_id):
        from app.models.user import User
        uid = to_uuid(user_id)
        wid = to_uuid(workspace_id) if workspace_id else None
        result = db.session.execute(
            sa_update(User)
            .where(User.id == uid)
            .values(active_workspace_id=wid, updated_at=datetime.utcnow())
        )
        db.session.commit()
        return result

    @staticmethod
    def null_active_workspace_for_workspace(workspace_id):
        """Reset ``active_workspace_id`` to NULL for every user pointing at
        *workspace_id*. Used after workspace delete so deleted-workspace
        bookmarks don't 404 their owners' next request."""
        from app.models.user import User
        try:
            wid = to_uuid(workspace_id)
        except (ValueError, TypeError):
            return 0
        result = db.session.execute(
            sa_update(User)
            .where(User.active_workspace_id == wid)
            .values(active_workspace_id=None, updated_at=datetime.utcnow())
        )
        db.session.commit()
        return result.rowcount or 0

    @staticmethod
    def null_active_workspace_for_user_if_match(user_id, workspace_id):
        """Conditionally reset active_workspace_id only when it matches."""
        from app.models.user import User
        try:
            uid = to_uuid(user_id)
            wid = to_uuid(workspace_id)
        except (ValueError, TypeError):
            return 0
        result = db.session.execute(
            sa_update(User)
            .where(User.id == uid, User.active_workspace_id == wid)
            .values(active_workspace_id=None, updated_at=datetime.utcnow())
        )
        db.session.commit()
        return result.rowcount or 0

    @staticmethod
    def find_by_email(email):
        """Find user by email. CITEXT column => already case-insensitive."""
        if not email:
            return None
        from app.models.user import User
        user = db.session.execute(
            select(User).where(User.email == email.strip())
        ).scalar_one_or_none()
        return _user_to_legacy_dict(user)

    @staticmethod
    def find_by_id(user_id):
        from app.models.user import User
        try:
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return None
        user = db.session.execute(
            select(User).where(User.id == uid)
        ).scalar_one_or_none()
        return _user_to_legacy_dict(user)

    @staticmethod
    def find_by_ids(user_ids):
        """Bulk fetch for ``$in``-style lookups. Returns a list of legacy
        dicts in arbitrary order; callers index by ``str(_id)`` themselves.
        Invalid IDs are silently skipped."""
        from app.models.user import User
        uids = []
        for v in user_ids or []:
            try:
                uids.append(to_uuid(v))
            except (ValueError, TypeError):
                continue
        if not uids:
            return []
        rows = db.session.execute(
            select(User).where(User.id.in_(uids))
        ).scalars().all()
        return [_user_to_legacy_dict(r) for r in rows]

    @staticmethod
    def verify_password(user, password):
        """Verify user password (accepts legacy-shaped dict)."""
        if not user or not user.get('password_hash'):
            return False
        ph = user['password_hash']
        if isinstance(ph, memoryview):
            ph = bytes(ph)
        elif isinstance(ph, str):
            ph = ph.encode('utf-8')
        return bcrypt.checkpw(password.encode('utf-8'), ph)

    @staticmethod
    def update(user_id, update_data):
        """Update arbitrary user columns / JSONB sub-keys.

        ``update_data`` keys map onto either top-level columns or one of
        the JSONB blobs (``profile.*``, ``settings.*``, ``usage.*``,
        ``status.*``) — same convention the Mongo body used. Dotted keys
        merge into the corresponding JSONB dict via flag_modified.
        """
        from app.models.user import User
        uid = to_uuid(user_id)
        user = db.session.execute(
            select(User).where(User.id == uid)
        ).scalar_one_or_none()
        if user is None:
            return None

        for k, v in (update_data or {}).items():
            if '.' in k:
                root, _, child = k.partition('.')
                blob = getattr(user, root, None)
                if not isinstance(blob, dict):
                    blob = {}
                blob[child] = v
                setattr(user, root, blob)
                flag_modified(user, root)
            elif k == 'role':
                user.role = v
            elif k in ('profile', 'settings', 'usage', 'status', 'ai_preferences'):
                setattr(user, k, v or {})
                flag_modified(user, k)
            elif k == 'display_name':
                user.display_name = v
            elif k == 'email':
                user.email = v
            elif k == 'active_workspace_id':
                user.active_workspace_id = to_uuid(v) if v else None
            elif k == 'keycloak_sub':
                user.keycloak_sub = to_uuid(v) if v else None
            elif k == 'password_hash':
                user.password_hash = v
            elif hasattr(user, k):
                setattr(user, k, v)
            else:
                # Unknown column / nested key (e.g. timezone) — drop onto
                # `settings` JSONB to keep parity with Mongo's free-form doc.
                blob = user.settings or {}
                blob[k] = v
                user.settings = blob
                flag_modified(user, 'settings')

        user.updated_at = datetime.utcnow()
        db.session.commit()
        return user

    @staticmethod
    def update_last_active(user_id):
        from app.models.user import User
        try:
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return None
        user = db.session.execute(
            select(User).where(User.id == uid)
        ).scalar_one_or_none()
        if user is None:
            return None
        usage = user.usage or {}
        usage['last_active'] = datetime.utcnow().isoformat()
        user.usage = usage
        flag_modified(user, 'usage')
        db.session.commit()
        return user

    @staticmethod
    def find_by_keycloak_sub(sub):
        from app.models.user import User
        if not sub:
            return None
        try:
            sub_uuid = to_uuid(sub)
        except (ValueError, TypeError):
            return None
        user = db.session.execute(
            select(User).where(User.keycloak_sub == sub_uuid)
        ).scalar_one_or_none()
        return _user_to_legacy_dict(user)

    @staticmethod
    def upsert_from_keycloak(sub, email, display_name, role, email_verified=False, locale=None):
        """Upsert a user from a Keycloak access-token payload.

        Two distinct code paths, hardened differently:

        * **sub-match** — the KC ``sub`` already links a row. This is an
          already-provisioned SSO identity; we re-sync email/display_name and
          let the IdP-derived ``role`` win (KC = source of truth on re-login).
          Behavior unchanged — this is by design.
        * **by-email fallback** — a NEW ``sub`` whose email matches an
          existing row. This is the account-takeover surface (CVE-class:
          unverified-email SSO link). It is now refused unless ALL hold:
            - the realm asserts ``email_verified is True`` (a synthesized
              ``…@<realm>.kc.local`` address is treated verified upstream in
              ``extract_profile``);
            - the matched row has NO ``password_hash`` (never hijack a
              password-backed / break-glass operator account); and
            - the matched row's ``role`` is plain ``user`` (never auto-link
              into a ``manager``/``admin`` principal).
          A refused link raises ``APIError`` ("link manually") and NEVER
          rebinds the sub or overwrites the matched row's ``role``.

        Neither matches -> a brand-new SSO-only user is created (no password,
        KC ``sub`` linked, KC role). Brand-new identities take this path, not
        the fallback, so they are unaffected by the fallback hardening.
        """
        from app.models.user import User
        from app.utils.errors import APIError
        normalized_email = email.lower().strip() if email else ''
        sub_uuid = to_uuid(sub)

        existing = db.session.execute(
            select(User).where(User.keycloak_sub == sub_uuid)
        ).scalar_one_or_none()

        if existing is not None:
            # sub-match: already-linked SSO user. Email, name, and role
            # re-sync from Keycloak on every login.
            changed = False
            if normalized_email and existing.email != normalized_email:
                existing.email = normalized_email
                changed = True
            # Realm roles are the source of truth on every SSO login.
            if role and existing.role != role:
                existing.role = role
                changed = True
            profile = existing.profile or {}
            if display_name and profile.get('display_name') != display_name:
                profile['display_name'] = display_name
                existing.profile = profile
                flag_modified(existing, 'profile')
                changed = True
            if display_name and existing.display_name != display_name:
                existing.display_name = display_name
                changed = True
            if locale in ('fa', 'en'):
                settings = existing.settings or {}
                if settings.get('locale') != locale:
                    settings['locale'] = locale
                    existing.settings = settings
                    flag_modified(existing, 'settings')
                    changed = True
            if changed:
                existing.updated_at = datetime.utcnow()
                db.session.commit()
            return _user_to_legacy_dict(existing)

        if normalized_email:
            by_email = db.session.execute(
                select(User).where(User.email == normalized_email)
            ).scalar_one_or_none()
            if by_email is not None:
                # by-email fallback: a fresh sub presenting an email that
                # already exists. Refuse to auto-link anything risky.
                if email_verified is not True:
                    raise APIError(
                        'This email is not verified by the identity provider; '
                        'cannot link it to an existing account.',
                        status_code=409,
                    )
                if (
                    by_email.password_hash is not None
                    or by_email.role in ('admin', 'manager')
                ):
                    # Password-backed (incl. break-glass operator) or a
                    # privileged principal. Never silently bind a sub or
                    # clobber the role — operator/admin must link manually.
                    raise APIError(
                        'An account with this email already exists. '
                        'Please link your SSO identity manually.',
                        status_code=409,
                    )
                # Safe to link: passwordless, non-privileged, verified email.
                # Bind the sub but DO NOT overwrite the existing row's role.
                by_email.keycloak_sub = sub_uuid
                if locale in ('fa', 'en'):
                    settings = by_email.settings or {}
                    if settings.get('locale') != locale:
                        settings['locale'] = locale
                        by_email.settings = settings
                        flag_modified(by_email, 'settings')
                by_email.updated_at = datetime.utcnow()
                db.session.commit()
                return _user_to_legacy_dict(by_email)

        return UserModel.create(
            email=normalized_email,
            password=None,
            display_name=display_name or (normalized_email.split('@')[0] if normalized_email else 'SSO User'),
            role=role,
            keycloak_sub=sub_uuid,
            locale=locale,
        )

    @staticmethod
    def increment_usage(user_id, messages=0, tokens=0):
        """Atomically bump the ``usage`` JSONB counters in a single UPDATE.

        Fires on every chat send, so it must NOT hydrate the full ``User`` row
        (all JSONB blobs) just to mutate two integers. Instead it does an
        in-place server-side ``jsonb_set`` of ``messages_sent`` / ``tokens_used``
        (each ``coalesce(..., 0) + delta``) + ``last_active`` in one statement;
        the increments stay atomic at the row level (no read-modify-write race).
        Returns the refreshed ``User`` on success, ``None`` when no row matched —
        the historical facade contract.
        """
        from app.models.user import User
        uid = to_uuid(user_id)
        now_iso = datetime.utcnow().isoformat()
        new_messages = (
            func.coalesce(
                cast(User.usage.op('->>')('messages_sent'), db.BigInteger), 0
            )
            + int(messages or 0)
        )
        new_tokens = (
            func.coalesce(
                cast(User.usage.op('->>')('tokens_used'), db.BigInteger), 0
            )
            + int(tokens or 0)
        )
        # Chain three jsonb_set calls over the same column: each rewrites one key
        # (create_missing defaults true, so an empty ``{}`` usage blob is fine).
        # to_jsonb wraps the bigint sums; the timestamp goes in as a JSON string.
        updated_usage = func.jsonb_set(
            func.jsonb_set(
                func.jsonb_set(
                    func.coalesce(User.usage, sa_text("'{}'::jsonb")),
                    sa_text("'{messages_sent}'"),
                    func.to_jsonb(new_messages),
                ),
                sa_text("'{tokens_used}'"),
                func.to_jsonb(new_tokens),
            ),
            sa_text("'{last_active}'"),
            func.to_jsonb(cast(now_iso, db.Text)),
        )
        result = db.session.execute(
            sa_update(User)
            .where(User.id == uid)
            .values(usage=updated_usage)
        )
        db.session.commit()
        if (result.rowcount or 0) == 0:
            return None
        return db.session.get(User, uid)

    @staticmethod
    def ban_user(user_id, reason, admin_id):
        from app.models.user import User
        uid = to_uuid(user_id)
        aid = to_uuid(admin_id) if admin_id else None
        user = db.session.execute(
            select(User).where(User.id == uid)
        ).scalar_one_or_none()
        if user is None:
            return None
        status = user.status or {}
        status['is_banned'] = True
        status['ban_reason'] = reason
        status['banned_at'] = datetime.utcnow().isoformat()
        status['banned_by'] = str(aid) if aid else None
        user.status = status
        flag_modified(user, 'status')
        user.updated_at = datetime.utcnow()
        db.session.commit()
        return user

    @staticmethod
    def unban_user(user_id):
        from app.models.user import User
        uid = to_uuid(user_id)
        user = db.session.execute(
            select(User).where(User.id == uid)
        ).scalar_one_or_none()
        if user is None:
            return None
        status = user.status or {}
        status['is_banned'] = False
        status['ban_reason'] = None
        status['banned_at'] = None
        status['banned_by'] = None
        user.status = status
        flag_modified(user, 'status')
        user.updated_at = datetime.utcnow()
        db.session.commit()
        return user

    @staticmethod
    def count(include_banned=True):
        from app.models.user import User
        stmt = select(func.count()).select_from(User)
        if not include_banned:
            stmt = stmt.where(
                sa_text("(status->>'is_banned')::bool IS NOT TRUE")
            )
        return int(db.session.execute(stmt).scalar() or 0)

    @staticmethod
    def ensure_default_admin(email, password, display_name='Admin'):
        existing = UserModel.find_by_email(email)
        if existing:
            if existing.get('role') != 'admin':
                UserModel.update(existing['_id'], {'role': 'admin'})
                print(f"[Admin] Updated {email} to admin role")
            return existing

        admin = UserModel.create(
            email=email,
            password=password,
            display_name=display_name,
            role='admin',
        )
        print(f"[Admin] Created default admin: {email}")
        return admin

    @staticmethod
    def get_default_ai_preferences():
        return {
            'enabled': True,
            'user_info': {
                'name': '',
                'language': 'English',
                'expertise_level': 'intermediate',
            },
            'behavior': {
                'tone': 'professional',
                'response_style': 'balanced',
            },
            'custom_instructions': '',
            'updated_at': None,
        }

    @staticmethod
    def get_ai_preferences(user_id):
        from app.models.user import User
        try:
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return UserModel.get_default_ai_preferences()
        prefs = db.session.execute(
            select(User.ai_preferences).where(User.id == uid)
        ).scalar_one_or_none()
        return prefs or UserModel.get_default_ai_preferences()

    @staticmethod
    def update_timezone(user_id: str, tz_str: str) -> None:
        import zoneinfo
        zoneinfo.ZoneInfo(tz_str)  # raises if invalid
        from app.models.user import User
        uid = to_uuid(user_id)
        user = db.session.execute(
            select(User).where(User.id == uid)
        ).scalar_one_or_none()
        if user is None:
            return None
        settings = user.settings or {}
        settings['timezone'] = tz_str
        user.settings = settings
        flag_modified(user, 'settings')
        user.updated_at = datetime.utcnow()
        db.session.commit()
        return None

    @staticmethod
    def get_timezone(user_id: str) -> str:
        from app.models.user import User
        try:
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return 'UTC'
        settings = db.session.execute(
            select(User.settings).where(User.id == uid)
        ).scalar_one_or_none()
        return (settings or {}).get('timezone') or 'UTC'

    @staticmethod
    def update_ai_preferences(user_id, preferences):
        """Merge AI preferences into the existing JSONB blob."""
        from app.models.user import User
        uid = to_uuid(user_id)
        user = db.session.execute(
            select(User).where(User.id == uid)
        ).scalar_one_or_none()
        if user is None:
            return None

        current = user.ai_preferences or UserModel.get_default_ai_preferences()
        if 'user_info' in preferences:
            current['user_info'] = {
                **current.get('user_info', {}),
                **preferences['user_info'],
            }
        if 'behavior' in preferences:
            current['behavior'] = {
                **current.get('behavior', {}),
                **preferences['behavior'],
            }
        if 'enabled' in preferences:
            current['enabled'] = preferences['enabled']
        if 'custom_instructions' in preferences:
            current['custom_instructions'] = preferences['custom_instructions'][:2000]

        current['updated_at'] = datetime.utcnow().isoformat()
        user.ai_preferences = current
        flag_modified(user, 'ai_preferences')
        user.updated_at = datetime.utcnow()
        db.session.commit()
        return user


# ---------------------------------------------------------------------------
# SQLAlchemy ORM model (Phase 3 strangler-fig — Mongo `UserModel` above stays
# live until Phase 4 façade cutover).
# ---------------------------------------------------------------------------
import uuid as _uuid  # noqa: E402
from datetime import datetime as _datetime  # noqa: E402

from sqlalchemy import (  # noqa: E402
    CheckConstraint,
    ForeignKey,
    Index,
    LargeBinary,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import (  # noqa: E402
    CITEXT,
    JSONB,
    TIMESTAMP,
    UUID as PG_UUID,
)
from sqlalchemy.orm import Mapped, mapped_column  # noqa: E402

from app.models._base import SerializableMixin  # noqa: E402


class User(db.Model, SerializableMixin):
    __tablename__ = 'users'
    _serialize_exclude = ('password_hash',)

    id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    password_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    role: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'user'"),
    )
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    keycloak_sub: Mapped[_uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    active_workspace_id: Mapped[_uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('workspaces.id', ondelete='SET NULL'),
        nullable=True,
    )
    profile: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{}')
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{}')
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{}')
    status: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{}')
    ai_preferences: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default='{}'
    )
    created_at: Mapped[_datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[_datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    __table_args__ = (
        # Role lookup (manager/admin gates run on every page load).
        Index('ix_users_role', 'role'),
        # SSO binding: sparse unique — only enforce when populated.
        Index(
            'uq_users_keycloak_sub',
            'keycloak_sub',
            unique=True,
            postgresql_where=text('keycloak_sub IS NOT NULL'),
        ),
        # Banned-user partial index (matches Mongo `status.is_banned` shape).
        Index(
            'ix_users_banned',
            'id',
            postgresql_where=text("(status->>'is_banned')::bool = true"),
        ),
        CheckConstraint(
            "role IN ('user', 'manager', 'admin')",
            name='ck_users_role',
        ),
    )
