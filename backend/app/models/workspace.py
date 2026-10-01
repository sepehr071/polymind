import re
import secrets
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.utils.ids import to_uuid


# Department-plan monthly INCLUDED usage allowance (USD) per tier. This is the
# free monthly spend a workspace gets before its prepaid wallet is drawn; the
# spend gate only hard-blocks (402) once the wallet hits $0 in overage. ``None``
# == unlimited-included / custom (enterprise) — the wallet is never the limiter.
# A workspace may override the tier default with an explicit
# ``settings.monthly_allowance_usd``. ``team`` is the legacy paid tier.
PLAN_TIER_ALLOWANCE = {
    'free': 0,
    'starter': 50,
    'growth': 250,
    'scale': 1000,
    'enterprise': None,
    'team': 250,
}


def _coerce_allowance(value):
    """Normalize a monthly-allowance value: non-negative float, or ``None``.

    Unlike :func:`_coerce_cap`, ``0`` is a MEANINGFUL value here (the ``free``
    tier = no included allowance, wallet draws from the first cent), so only
    ``None`` / empty / non-numeric / negative collapse to ``None`` (== unlimited
    included / unset). ``0`` is preserved verbatim.
    """
    if value is None or value == '':
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num >= 0 else None


def _coerce_cap(value) -> float | None:
    """Normalize a spend-cap value to a non-negative float, or ``None`` (disabled).

    Treats ``None`` / empty / non-numeric / ``<= 0`` as "no cap" — a cap of 0 is
    meaningless (it would block all spend), so callers express "off" with null.
    """
    if value is None or value == '':
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def _ws_to_legacy_dict(ws) -> dict | None:
    """Render a :class:`Workspace` ORM row in the legacy Mongo dict shape.

    Legacy fields the routes still read:
        ``name``, ``slug``, ``type`` (personal|team), ``owner_id``, ``plan``,
        ``plan_tier``, ``seats_total``, ``credits_balance_usd``,
        ``budget_mtd_usd``, ``renews_at``, ``sso_enforced``, ``scim_enabled``,
        ``domain``, ``ip_allowlist``, ``enforce_2fa``, ``avatar``, ``settings``.
    """
    if ws is None:
        return None
    d = ws.to_dict()
    settings = ws.settings or {}
    d['name'] = ws.display_name or settings.get('name') or ''
    d['type'] = 'personal' if ws.is_personal else 'team'
    d['owner_id'] = str(ws.owner_user_id) if ws.owner_user_id else None
    d['plan'] = settings.get('plan') or 'free'
    d['plan_tier'] = settings.get('plan_tier') or 'free'
    d['seats_total'] = int(settings.get('seats_total') or 5)
    d['budget_mtd_usd'] = float(settings.get('budget_mtd_usd') or 0.0)
    # Department-plan monthly INCLUDED allowance (USD). Hoisted alongside
    # ``budget_mtd_usd`` so the spend gate + billing route read it off the dict.
    # Distinct from the budget: ``None`` (unset / enterprise) == unlimited
    # included, ``0`` == no allowance (free tier). Preserve the None/0 split.
    d['monthly_allowance_usd'] = _coerce_allowance(settings.get('monthly_allowance_usd'))
    # Per-user / per-model monthly spend caps (USD). Stored in the same JSONB
    # settings blob as the workspace budget; ``None`` sub-key == cap disabled.
    raw_caps = settings.get('spend_caps') or {}
    d['spend_caps'] = {
        'per_user_usd': _coerce_cap(raw_caps.get('per_user_usd')),
        'per_model_usd': _coerce_cap(raw_caps.get('per_model_usd')),
    }
    d['renews_at'] = settings.get('renews_at')
    d['sso_enforced'] = bool(settings.get('sso_enforced') or False)
    d['scim_enabled'] = bool(settings.get('scim_enabled') or False)
    d['domain'] = settings.get('domain')
    d['enforce_2fa'] = bool(settings.get('enforce_2fa') or False)
    # `credits_balance_usd` lives as a real Numeric column.
    d['credits_balance_usd'] = float(ws.credits_balance_usd or 0)
    # `ip_allowlist`, `avatar` already top-level columns.
    return d


class WorkspaceModel:
    """Model for Workspaces (personal or team) - top-level container for projects/resources."""

    collection_name = 'workspaces'

    @staticmethod
    def _slugify(name: str) -> str:
        s = (name or '').lower()
        s = re.sub(r'[^a-z0-9]+', '-', s)
        s = re.sub(r'-+', '-', s).strip('-')
        return s or 'workspace'

    @staticmethod
    def create(name: str, owner_id, type: str = 'team', avatar: dict = None,
               settings: dict = None) -> dict:
        from app.models.workspace import Workspace
        owner_uuid = to_uuid(owner_id) if owner_id else None
        if type not in ('personal', 'team'):
            raise ValueError(f"Invalid workspace type: {type}")

        if avatar is None:
            initials = ''.join(part[0] for part in (name or 'W').split() if part)[:2].upper() or 'W'
            avatar = {'type': 'initials', 'value': initials}
        if settings is None:
            settings = {}

        # Mirror the Mongo doc's enterprise/billing extras into the JSONB
        # settings blob so callers reading `ws.get('plan_tier')` etc. keep
        # functioning untouched.
        settings = {
            **settings,
            'plan': settings.get('plan', 'free'),
            'plan_tier': settings.get('plan_tier', 'free'),
            'seats_total': settings.get('seats_total', 5),
            'budget_mtd_usd': settings.get('budget_mtd_usd', 0.0),
            'spend_caps': settings.get('spend_caps') or {},
            'renews_at': settings.get('renews_at'),
            'sso_enforced': settings.get('sso_enforced', False),
            'scim_enabled': settings.get('scim_enabled', False),
            'domain': settings.get('domain'),
            'enforce_2fa': settings.get('enforce_2fa', False),
        }

        base_slug = WorkspaceModel._slugify(name)
        now = datetime.utcnow()
        slug = base_slug

        for _attempt in range(6):
            ws = Workspace(
                slug=slug,
                owner_user_id=owner_uuid,
                is_personal=(type == 'personal'),
                display_name=name,
                settings=settings,
                ip_allowlist=[],
                avatar=avatar,
                credits_balance_usd=0,
                created_at=now,
                updated_at=now,
            )
            db.session.add(ws)
            try:
                db.session.commit()
                return _ws_to_legacy_dict(ws)
            except IntegrityError:
                db.session.rollback()
                slug = f"{base_slug}-{secrets.token_hex(3)}"

        raise RuntimeError(f"Could not generate unique slug for workspace '{name}'")

    @staticmethod
    def find_by_keycloak_org_id(org_id: str) -> dict | None:
        from app.models.workspace import Workspace
        if not org_id:
            return None
        ws = db.session.scalar(
            select(Workspace).where(
                Workspace.settings['keycloak_org_id'].astext == str(org_id)
            )
        )
        return _ws_to_legacy_dict(ws) if ws is not None else None

    @staticmethod
    def find_by_id(workspace_id) -> dict:
        from app.models.workspace import Workspace
        try:
            wid = to_uuid(workspace_id)
        except (ValueError, TypeError):
            return None
        ws = db.session.execute(
            select(Workspace).where(Workspace.id == wid)
        ).scalar_one_or_none()
        return _ws_to_legacy_dict(ws)

    @staticmethod
    def find_by_owner(owner_id) -> list:
        from app.models.workspace import Workspace
        try:
            uid = to_uuid(owner_id)
        except (ValueError, TypeError):
            return []
        rows = db.session.execute(
            select(Workspace)
            .where(Workspace.owner_user_id == uid)
            .order_by(Workspace.created_at.asc())
        ).scalars().all()
        return [_ws_to_legacy_dict(w) for w in rows]

    @staticmethod
    def find_by_member(user_id) -> list:
        from app.models.workspace import Workspace
        from app.models.workspace_member import WorkspaceMember
        try:
            uid = to_uuid(user_id)
        except (ValueError, TypeError):
            return []
        rows = db.session.execute(
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == uid, WorkspaceMember.status == 'active')
            .order_by(Workspace.display_name.asc(), Workspace.created_at.asc())
        ).scalars().all()
        return [_ws_to_legacy_dict(w) for w in rows]

    @staticmethod
    def update(workspace_id, update_data: dict, commit: bool = True) -> bool:
        from app.models.workspace import Workspace
        from sqlalchemy.orm.attributes import flag_modified
        wid = to_uuid(workspace_id)

        allowed_fields = {
            'name', 'avatar', 'plan', 'settings',
            'domain', 'sso_enforced', 'scim_enabled',
            'plan_tier', 'seats_total', 'credits_balance_usd',
            'budget_mtd_usd', 'monthly_allowance_usd', 'spend_caps', 'renews_at',
            'ip_allowlist', 'enforce_2fa',
        }
        clean = {k: v for k, v in (update_data or {}).items() if k in allowed_fields}
        if not clean:
            return False

        # Validation mirrors the Mongo body.
        if 'plan_tier' in clean:
            # Department plan tiers + legacy 'free'/'team' for back-compat.
            if clean['plan_tier'] not in PLAN_TIER_ALLOWANCE:
                raise ValueError(
                    "plan_tier must be one of "
                    "'free' | 'starter' | 'growth' | 'scale' | 'enterprise' | 'team'"
                )
        if 'ip_allowlist' in clean:
            value = clean['ip_allowlist']
            if not isinstance(value, list):
                raise ValueError('ip_allowlist must be a list of strings')
            cleaned_list = []
            for item in value:
                if not isinstance(item, str):
                    raise ValueError('ip_allowlist must be a list of non-empty strings')
                stripped = item.strip()
                if not stripped:
                    raise ValueError('ip_allowlist must be a list of non-empty strings')
                cleaned_list.append(stripped)
            clean['ip_allowlist'] = cleaned_list
        if 'enforce_2fa' in clean:
            clean['enforce_2fa'] = bool(clean['enforce_2fa'])
        if 'budget_mtd_usd' in clean:
            clean['budget_mtd_usd'] = _coerce_cap(clean['budget_mtd_usd']) or 0.0
        if 'monthly_allowance_usd' in clean:
            # number >= 0, or None (unlimited included). 0 is preserved (free
            # tier = wallet draws immediately) — unlike budget_mtd_usd, 0 is NOT
            # collapsed to "off".
            value = clean['monthly_allowance_usd']
            if value is not None and value != '':
                try:
                    num = float(value)
                except (TypeError, ValueError):
                    raise ValueError('monthly_allowance_usd must be a number >= 0 or null')
                if num < 0:
                    raise ValueError('monthly_allowance_usd must be a number >= 0 or null')
                clean['monthly_allowance_usd'] = num
            else:
                clean['monthly_allowance_usd'] = None
        if 'spend_caps' in clean:
            value = clean['spend_caps']
            if value is None:
                value = {}
            if not isinstance(value, dict):
                raise ValueError('spend_caps must be an object')
            clean['spend_caps'] = {
                'per_user_usd': _coerce_cap(value.get('per_user_usd')),
                'per_model_usd': _coerce_cap(value.get('per_model_usd')),
            }

        ws = db.session.execute(
            select(Workspace).where(Workspace.id == wid)
        ).scalar_one_or_none()
        if ws is None:
            return False

        settings = dict(ws.settings or {})
        changed = False
        for k, v in clean.items():
            if k == 'name':
                ws.display_name = v
                settings['name'] = v
                changed = True
            elif k == 'avatar':
                ws.avatar = v or {}
                changed = True
            elif k == 'ip_allowlist':
                ws.ip_allowlist = v
                changed = True
            elif k == 'credits_balance_usd':
                ws.credits_balance_usd = v
                changed = True
            elif k == 'settings':
                ws.settings = v or {}
                flag_modified(ws, 'settings')
                changed = True
                # Skip nested merge below — caller is replacing the blob.
                settings = ws.settings
                continue
            else:
                # All other enterprise/billing extras land in `settings` JSONB.
                settings[k] = v
                changed = True

        ws.settings = settings
        flag_modified(ws, 'settings')
        ws.updated_at = datetime.utcnow()
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return changed

    @staticmethod
    def update_settings_subkey(workspace_id, subkey: str, value) -> bool:
        """Set ``settings.<subkey>`` to *value* in the workspace JSONB blob.

        Used for nested-key updates (e.g. ``settings.dlp``) where the caller
        already has the merged sub-document. The merge with existing
        settings keys happens in-Python before the SQL update.
        """
        from app.models.workspace import Workspace
        from sqlalchemy.orm.attributes import flag_modified
        try:
            wid = to_uuid(workspace_id)
        except (ValueError, TypeError):
            return False
        ws = db.session.execute(
            select(Workspace).where(Workspace.id == wid)
        ).scalar_one_or_none()
        if ws is None:
            return False
        settings = dict(ws.settings or {})
        settings[subkey] = value
        ws.settings = settings
        flag_modified(ws, 'settings')
        ws.updated_at = datetime.utcnow()
        db.session.commit()
        return True

    @staticmethod
    def delete(workspace_id) -> bool:
        from app.models.workspace import Workspace
        try:
            wid = to_uuid(workspace_id)
        except (ValueError, TypeError):
            return False
        ws = db.session.execute(
            select(Workspace).where(Workspace.id == wid)
        ).scalar_one_or_none()
        if ws is None:
            return False
        db.session.delete(ws)
        db.session.commit()
        return True

    @staticmethod
    def set_owner(workspace_id, new_owner_id) -> bool:
        from app.models.workspace import Workspace
        wid = to_uuid(workspace_id)
        new_owner_uuid = to_uuid(new_owner_id)
        ws = db.session.execute(
            select(Workspace).where(Workspace.id == wid)
        ).scalar_one_or_none()
        if ws is None:
            return False
        ws.owner_user_id = new_owner_uuid
        ws.updated_at = datetime.utcnow()
        db.session.commit()
        return True

    @staticmethod
    def find_by_slug(slug: str) -> dict:
        from app.models.workspace import Workspace
        ws = db.session.execute(
            select(Workspace).where(Workspace.slug == slug)
        ).scalar_one_or_none()
        return _ws_to_legacy_dict(ws)

    @staticmethod
    def credits_remaining_usd(workspace_id) -> float:
        """Reconciled remaining prepaid credit (USD) for one workspace.

        ``Σ credit_ledger − company LIFETIME spend rollup``. The spend half is a
        single indexed point-read of the ``spend_rollups`` company LIFETIME
        sentinel (``period_month == 1970-01-01``) — the same counter the
        spend-gate reconciles against — NOT an unbounded ``SUM(usage_logs)``,
        because this is a display hot path (overview + billing headline). The
        gate uses the identical read at ``services/spend_gate.py``.

        ``credits_balance_usd`` (a real column) is lifetime top-ups that never
        decrements, so it must NOT be used as the headline "remaining" figure;
        both the overview and billing tabs read this method instead.

        Drift caveat: the rollups are a best-effort second commit in
        ``OpenRouterService._record_usage``; if one is ever missed the LIFETIME
        sentinel under-counts spend (remaining reads slightly high). A brand-new
        company with no usage simply has no sentinel row → ``get_spent`` returns
        ``0.0`` (genuinely zero spend), which is correct — do NOT fall back to a
        ``SUM`` to "repair" a zero (it can't tell genuine-zero from missing).
        Reconcile drift with ``scripts/backfill_spend_rollups.py``.
        """
        from app.models.credit_ledger import CreditLedgerModel
        from app.models.spend_rollup import SpendRollupModel
        lifetime_topups = float(CreditLedgerModel.sum_credits(workspace_id))
        lifetime_spend = float(
            SpendRollupModel.get_spent('company', workspace_id, SpendRollupModel.LIFETIME)
        )
        return round(lifetime_topups - lifetime_spend, 10)


# ---------------------------------------------------------------------------
# SQLAlchemy ORM model (Phase 3 strangler-fig).
# ---------------------------------------------------------------------------
import uuid as _uuid  # noqa: E402
from datetime import datetime as _datetime  # noqa: E402

from sqlalchemy import (  # noqa: E402
    Boolean,
    ForeignKey,
    Index,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import (  # noqa: E402
    JSONB,
    TIMESTAMP,
    UUID as PG_UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship  # noqa: E402

from app.models._base import SerializableMixin  # noqa: E402


class Workspace(db.Model, SerializableMixin):
    __tablename__ = 'workspaces'

    id: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    owner_user_id: Mapped[_uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey('users.id'),
        nullable=True,
    )
    is_personal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('false')
    )
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{}')
    ip_allowlist: Mapped[list] = mapped_column(JSONB, nullable=False, server_default='[]')
    avatar: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{}')
    credits_balance_usd: Mapped[float] = mapped_column(
        Numeric(14, 8), nullable=False, server_default=text('0')
    )
    created_at: Mapped[_datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[_datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Relationships (only one-to-many sides we'll routinely join in Python).
    members: Mapped[list['WorkspaceMember']] = relationship(  # noqa: F821
        back_populates='workspace', cascade='all, delete-orphan'
    )
    invites: Mapped[list['WorkspaceInvite']] = relationship(  # noqa: F821
        back_populates='workspace', cascade='all, delete-orphan'
    )
    projects: Mapped[list['Project']] = relationship(  # noqa: F821
        back_populates='workspace', cascade='all, delete-orphan'
    )
    groups: Mapped[list['Group']] = relationship(  # noqa: F821
        back_populates='workspace', cascade='all, delete-orphan'
    )

    __table_args__ = (
        Index('ix_workspaces_owner_user_id', 'owner_user_id'),
    )
