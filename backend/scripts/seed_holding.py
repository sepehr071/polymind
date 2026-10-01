"""
Holding-company seeder for the new role model (CEO + managers + companies).
SQLAlchemy / Postgres edition (Phase 6 cutover).

Seeds a realistic medium-sized software holding "Acme Holding" with:
  - 1 CEO  (user.role = 'admin')
  - 3 Managers (user.role = 'manager'), one per company
  - 20 employees (user.role = 'user')
  - 3 company workspaces (Engineering, Design, Operations)
  - 6 projects per company (1-2 pinned, 1 archived)
  - 3 groups per company + project group-access grants
  - Sample conversations + messages on active projects
  - 1 pending invite per company
  - Audit-log entries per company
  - Credit-ledger top-ups, 30 days of synthetic usage_logs, DLP events,
    knowledge folders + items, workspace + project assistants, workflows
    + sample runs, generated images, one arena + one debate session.

Idempotent. Uses ONLY the new role enum (owner | editor | viewer).

Usage:
    cd backend
    ./.venv-uv/Scripts/python.exe scripts/seed_holding.py            # additive
    ./.venv-uv/Scripts/python.exe scripts/seed_holding.py --reset    # wipe + reseed
    ./.venv-uv/Scripts/python.exe scripts/seed_holding.py --wipe     # wipe only
"""
import argparse
import hashlib
import os
import random
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, '.env'), override=True)
sys.path.insert(0, ROOT)

from sqlalchemy import select, func, text as sa_text, update as sa_update  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.user import UserModel, User  # noqa: E402
from app.models.workspace import WorkspaceModel, Workspace  # noqa: E402
from app.models.workspace_member import WorkspaceMemberModel  # noqa: E402
from app.models.workspace_invite import WorkspaceInviteModel, WorkspaceInvite  # noqa: E402
from app.models.project import ProjectModel, Project  # noqa: E402
from app.models.project_member import ProjectMemberModel  # noqa: E402
from app.models.group import GroupModel, Group  # noqa: E402
from app.models.group_member import GroupMemberModel  # noqa: E402
from app.models.project_group_access import ProjectGroupAccessModel  # noqa: E402
from app.models.audit_log import AuditLogModel  # noqa: E402
from app.models.conversation import ConversationModel, Conversation  # noqa: E402
from app.models.message import MessageModel  # noqa: E402
from app.models.credit_ledger import CreditLedgerModel  # noqa: E402
from app.models.usage_log import UsageLogModel, UsageLog  # noqa: E402
from app.models.knowledge_folder import KnowledgeFolderModel, KnowledgeFolder  # noqa: E402
from app.models.knowledge_item import KnowledgeItemModel  # noqa: E402
from app.models.llm_config import LLMConfigModel  # noqa: E402
from app.models.dlp_event import DLPEventModel, DLPEvent  # noqa: E402
from app.models.workflow import WorkflowModel  # noqa: E402
from app.models.workflow_run import WorkflowRunModel, WorkflowRun  # noqa: E402
from app.models.generated_image import GeneratedImageModel, GeneratedImage  # noqa: E402
from app.models.arena_session import ArenaSession  # noqa: E402
from app.models.arena_message import ArenaMessageModel  # noqa: E402
from app.models.debate_session import DebateSession  # noqa: E402
from app.models.debate_message import DebateMessageModel  # noqa: E402
from app.utils.ids import to_uuid  # noqa: E402


DOMAIN = 'acme-holding.com'
DEMO_PASSWORD = 'Demo!Pass123'

# -----------------------------------------------------------------------------
# Cast
# -----------------------------------------------------------------------------

CEO = {
    'email': f'ceo@{DOMAIN}',
    'name':  'Sarah Chen',
    'role':  'admin',
}

MANAGERS = [
    {'email': f'eng-director@{DOMAIN}',  'name': 'Marcus Rivera', 'role': 'manager', 'company': 'engineering'},
    {'email': f'design-lead@{DOMAIN}',   'name': 'Amelia Park',   'role': 'manager', 'company': 'design'},
    {'email': f'ops-manager@{DOMAIN}',   'name': 'David Cohen',   'role': 'manager', 'company': 'operations'},
]

EMPLOYEES = [
    # Engineering (8)
    {'email': f'alex.kumar@{DOMAIN}',   'name': 'Alex Kumar',     'company': 'engineering', 'group': 'Backend',   'ws_role': 'editor'},
    {'email': f'jamie.lee@{DOMAIN}',    'name': 'Jamie Lee',      'company': 'engineering', 'group': 'Backend',   'ws_role': 'editor'},
    {'email': f'tom.nguyen@{DOMAIN}',   'name': 'Tom Nguyen',     'company': 'engineering', 'group': 'Frontend',  'ws_role': 'editor'},
    {'email': f'lisa.brown@{DOMAIN}',   'name': 'Lisa Brown',     'company': 'engineering', 'group': 'Frontend',  'ws_role': 'editor'},
    {'email': f'chris.wong@{DOMAIN}',   'name': 'Chris Wong',     'company': 'engineering', 'group': 'Platform',  'ws_role': 'editor'},
    {'email': f'emma.davis@{DOMAIN}',   'name': 'Emma Davis',     'company': 'engineering', 'group': 'Platform',  'ws_role': 'editor'},
    {'email': f'nina.patel@{DOMAIN}',   'name': 'Nina Patel',     'company': 'engineering', 'group': 'Backend',   'ws_role': 'viewer'},
    {'email': f'oscar.kim@{DOMAIN}',    'name': 'Oscar Kim',      'company': 'engineering', 'group': 'Frontend',  'ws_role': 'viewer'},

    # Design (6)
    {'email': f'mia.garcia@{DOMAIN}',   'name': 'Mia Garcia',     'company': 'design', 'group': 'Visual', 'ws_role': 'editor'},
    {'email': f'ben.taylor@{DOMAIN}',   'name': 'Ben Taylor',     'company': 'design', 'group': 'Visual', 'ws_role': 'editor'},
    {'email': f'sara.ito@{DOMAIN}',     'name': 'Sara Ito',       'company': 'design', 'group': 'UX',     'ws_role': 'editor'},
    {'email': f'leo.silva@{DOMAIN}',    'name': 'Leo Silva',      'company': 'design', 'group': 'UX',     'ws_role': 'editor'},
    {'email': f'ivy.zhang@{DOMAIN}',    'name': 'Ivy Zhang',      'company': 'design', 'group': 'Brand',  'ws_role': 'editor'},
    {'email': f'max.holm@{DOMAIN}',     'name': 'Max Holm',       'company': 'design', 'group': 'Brand',  'ws_role': 'viewer'},

    # Operations (6)
    {'email': f'amy.hr@{DOMAIN}',       'name': 'Amy Sanders',    'company': 'operations', 'group': 'HR',                'ws_role': 'editor'},
    {'email': f'ravi.hr@{DOMAIN}',      'name': 'Ravi Sharma',    'company': 'operations', 'group': 'HR',                'ws_role': 'editor'},
    {'email': f'olga.fin@{DOMAIN}',     'name': 'Olga Petrov',    'company': 'operations', 'group': 'Finance',           'ws_role': 'editor'},
    {'email': f'peter.fin@{DOMAIN}',    'name': 'Peter Lopez',    'company': 'operations', 'group': 'Finance',           'ws_role': 'editor'},
    {'email': f'julia.cs@{DOMAIN}',     'name': 'Julia Webb',     'company': 'operations', 'group': 'Customer Success',  'ws_role': 'editor'},
    {'email': f'mark.cs@{DOMAIN}',      'name': 'Mark Reilly',    'company': 'operations', 'group': 'Customer Success',  'ws_role': 'viewer'},
]

COMPANIES = {
    'engineering': {
        'name': 'Acme Engineering',
        'slug': 'acme-engineering',
        'manager_email': f'eng-director@{DOMAIN}',
        'groups': [
            {'name': 'Backend',  'color': '#5c9aed', 'icon': 'cpu',     'description': 'API + services.'},
            {'name': 'Frontend', 'color': '#a78bfa', 'icon': 'sparkle', 'description': 'Web + mobile UI.'},
            {'name': 'Platform', 'color': '#10b981', 'icon': 'database','description': 'DevOps + infra.'},
        ],
        'projects': [
            {'slug': 'api-platform',    'name': 'API Platform',     'desc': 'Public REST + GraphQL gateway',           'color': '#5c9aed', 'icon': 'cpu',       'pinned': True,  'archived': False, 'tags': ['backend', 'platform'], 'group': 'Backend'},
            {'slug': 'mobile-app',      'name': 'Mobile App',       'desc': 'iOS + Android client',                    'color': '#a78bfa', 'icon': 'smartphone','pinned': True,  'archived': False, 'tags': ['mobile'],              'group': 'Frontend'},
            {'slug': 'devops-pipeline', 'name': 'DevOps Pipeline',  'desc': 'CI/CD + observability',                   'color': '#10b981', 'icon': 'gitBranch', 'pinned': False, 'archived': False, 'tags': ['ci', 'infra'],         'group': 'Platform'},
            {'slug': 'internal-tools',  'name': 'Internal Tools',   'desc': 'Admin dashboards + scripts',              'color': '#06b6d4', 'icon': 'wrench',    'pinned': False, 'archived': False, 'tags': ['internal'],            'group': 'Platform'},
            {'slug': 'auth-refactor',   'name': 'Auth Refactor',    'desc': 'OIDC migration + session redesign',       'color': '#f59e0b', 'icon': 'shield',    'pinned': False, 'archived': False, 'tags': ['security'],            'group': 'Backend'},
            {'slug': 'legacy-v2',       'name': 'Legacy v2',        'desc': 'Old monolith — kept for reference',       'color': '#71717a', 'icon': 'archive',   'pinned': False, 'archived': True,  'tags': ['archive'],             'group': 'Backend'},
        ],
        'project_group_access': {
            'api-platform':    [('Backend', 'editor'), ('Platform', 'viewer')],
            'mobile-app':      [('Frontend', 'editor'), ('Backend', 'viewer')],
            'devops-pipeline': [('Platform', 'editor')],
            'internal-tools':  [('Platform', 'editor'), ('Backend', 'viewer')],
            'auth-refactor':   [('Backend', 'editor')],
        },
    },
    'design': {
        'name': 'Acme Design',
        'slug': 'acme-design',
        'manager_email': f'design-lead@{DOMAIN}',
        'groups': [
            {'name': 'Visual', 'color': '#ec4899', 'icon': 'image',   'description': 'Visual + illustration.'},
            {'name': 'UX',     'color': '#a78bfa', 'icon': 'compass', 'description': 'User research + flows.'},
            {'name': 'Brand',  'color': '#f59e0b', 'icon': 'flame',   'description': 'Brand voice + identity.'},
        ],
        'projects': [
            {'slug': 'brand-refresh-2026', 'name': 'Brand Refresh 2026', 'desc': 'Identity + voice update',         'color': '#f59e0b', 'icon': 'flame',    'pinned': True,  'archived': False, 'tags': ['brand'],         'group': 'Brand'},
            {'slug': 'marketing-site-v3',  'name': 'Marketing Site v3',  'desc': 'New marketing site redesign',     'color': '#ec4899', 'icon': 'globe',    'pinned': True,  'archived': False, 'tags': ['web'],           'group': 'Visual'},
            {'slug': 'mobile-ux',          'name': 'Mobile UX',          'desc': 'Mobile app redesign',             'color': '#a78bfa', 'icon': 'compass',  'pinned': False, 'archived': False, 'tags': ['mobile', 'ux'],  'group': 'UX'},
            {'slug': 'design-system',      'name': 'Design System',      'desc': 'Component library + tokens',      'color': '#5c9aed', 'icon': 'package',  'pinned': False, 'archived': False, 'tags': ['system'],        'group': 'UX'},
            {'slug': 'icon-library',       'name': 'Icon Library',       'desc': 'Internal icon set',               'color': '#06b6d4', 'icon': 'sparkle',  'pinned': False, 'archived': False, 'tags': ['icons'],         'group': 'Visual'},
            {'slug': '2024-archive',       'name': '2024 Archive',       'desc': 'Old work — kept for reference',   'color': '#71717a', 'icon': 'archive',  'pinned': False, 'archived': True,  'tags': ['archive'],       'group': 'Brand'},
        ],
        'project_group_access': {
            'brand-refresh-2026': [('Brand', 'editor'), ('Visual', 'viewer')],
            'marketing-site-v3':  [('Visual', 'editor'), ('Brand', 'viewer')],
            'mobile-ux':          [('UX', 'editor')],
            'design-system':      [('UX', 'editor'), ('Visual', 'editor')],
            'icon-library':       [('Visual', 'editor')],
        },
    },
    'operations': {
        'name': 'Acme Operations',
        'slug': 'acme-operations',
        'manager_email': f'ops-manager@{DOMAIN}',
        'groups': [
            {'name': 'HR',                'color': '#10b981', 'icon': 'users',    'description': 'People + culture.'},
            {'name': 'Finance',           'color': '#5c9aed', 'icon': 'database', 'description': 'Books + budget.'},
            {'name': 'Customer Success',  'color': '#ec4899', 'icon': 'message',  'description': 'Onboarding + support.'},
        ],
        'projects': [
            {'slug': 'hr-onboarding',       'name': 'HR Onboarding',       'desc': 'New-hire workflow + checklists',     'color': '#10b981', 'icon': 'flag',     'pinned': True,  'archived': False, 'tags': ['hr'],          'group': 'HR'},
            {'slug': 'vendor-portal',       'name': 'Vendor Portal',       'desc': 'Vendor onboarding + ACH',            'color': '#5c9aed', 'icon': 'package',  'pinned': True,  'archived': False, 'tags': ['vendor'],      'group': 'Finance'},
            {'slug': 'analytics-dashboard', 'name': 'Analytics Dashboard', 'desc': 'Exec metrics + financial KPIs',      'color': '#a78bfa', 'icon': 'database', 'pinned': False, 'archived': False, 'tags': ['analytics'],   'group': 'Finance'},
            {'slug': 'compliance-tracker',  'name': 'Compliance Tracker',  'desc': 'SOC2 + GDPR evidence',               'color': '#f59e0b', 'icon': 'shield',   'pinned': False, 'archived': False, 'tags': ['compliance'],  'group': 'HR'},
            {'slug': 'knowledge-base',      'name': 'Knowledge Base',      'desc': 'Customer FAQ + runbooks',            'color': '#06b6d4', 'icon': 'message',  'pinned': False, 'archived': False, 'tags': ['cs', 'kb'],    'group': 'Customer Success'},
            {'slug': 'old-vendor',          'name': 'Old Vendor',          'desc': 'Sunset relationship — archived',     'color': '#71717a', 'icon': 'archive',  'pinned': False, 'archived': True,  'tags': ['archive'],     'group': 'Finance'},
        ],
        'project_group_access': {
            'hr-onboarding':       [('HR', 'editor')],
            'vendor-portal':       [('Finance', 'editor')],
            'analytics-dashboard': [('Finance', 'editor'), ('HR', 'viewer')],
            'compliance-tracker':  [('HR', 'editor'), ('Finance', 'viewer')],
            'knowledge-base':      [('Customer Success', 'editor')],
        },
    },
}

PENDING_INVITES = {
    'engineering': {'email': f'newhire.eng@{DOMAIN}', 'role': 'editor'},
    'design':      {'email': f'newhire.design@{DOMAIN}', 'role': 'editor'},
    'operations':  {'email': f'newhire.ops@{DOMAIN}', 'role': 'viewer'},
}

SAMPLE_PROMPTS = [
    'Draft the launch announcement.',
    'Summarize the latest customer feedback.',
    'Outline the architecture for the new service.',
    'Critique this blog draft.',
    'Generate three campaign ideas.',
    'What objections come up most often?',
    'Help plan an onboarding sequence.',
    'Translate this paragraph into plain English.',
]
SAMPLE_REPLIES = [
    "Here's a draft. Three sections so you can swap pieces independently.",
    "Top three themes: pricing, integration timelines, and reliability concerns.",
    "Sketching service-A on Postgres + Redis, behind the existing API gateway.",
    "Tone reads stiff in para 2 — loosen up and drop the buzzwords.",
    "Three angles: outcome-led, story-led, and POV-led campaigns.",
    "Most-asked: data residency, seat pricing >500, custom SSO.",
    "Day-1 setup, week-1 paired-coding, week-2 first PR, week-3 retro.",
    "Means: liability is capped at 12× monthly fee, max $50k.",
]

MODEL_IDS = [
    'openai/gpt-4o',
    'anthropic/claude-sonnet-4.5',
    'google/gemini-3.6-flash',
    'x-ai/grok-4.1-fast',
]


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def log(msg):
    try:
        print(f'[seed-holding] {msg}', flush=True)
    except UnicodeEncodeError:
        print(f'[seed-holding] {msg.encode("ascii", "replace").decode("ascii")}', flush=True)


def upsert_user(email: str, name: str, role: str = 'user') -> dict:
    existing = UserModel.find_by_email(email)
    if existing:
        if existing.get('role') != role:
            UserModel.set_role(existing['_id'], role)
            existing = UserModel.find_by_email(email)
        return existing
    UserModel.create(email, DEMO_PASSWORD, name, role=role)
    return UserModel.find_by_email(email)


def find_workspace_by_slug(slug: str):
    return WorkspaceModel.find_by_slug(slug)


def find_project_by_slug(workspace_id, slug: str):
    wid = to_uuid(workspace_id)
    p = db.session.execute(
        select(Project).where(Project.workspace_id == wid, Project.slug == slug)
    ).scalar_one_or_none()
    if p is None:
        return None
    out = p.to_dict()
    out['_id'] = str(p.id)
    out['workspace_id'] = str(p.workspace_id)
    settings = p.settings or {}
    out['pinned'] = bool(settings.get('pinned') or False)
    out['archived'] = bool(p.archived)
    return out


def find_group_by_name(workspace_id, name: str):
    wid = to_uuid(workspace_id)
    g = db.session.execute(
        select(Group).where(Group.workspace_id == wid, Group.name == name)
    ).scalar_one_or_none()
    if g is None:
        return None
    out = g.to_dict()
    out['_id'] = str(g.id)
    return out


def upsert_membership(workspace_id, user_id, role: str, invited_by, email: str) -> None:
    """Idempotent: forces row + role + status=active."""
    WorkspaceMemberModel.add(
        workspace_id, user_id, role,
        invited_by=invited_by,
        invited_email=email,
        status='active',
    )
    WorkspaceMemberModel.update_role(workspace_id, user_id, role)
    WorkspaceMemberModel.update_status(workspace_id, user_id, 'active')


def _force_workspace_extras(workspace_id, extras: dict) -> None:
    wid = to_uuid(workspace_id)
    ws = db.session.execute(select(Workspace).where(Workspace.id == wid)).scalar_one()
    settings = dict(ws.settings or {})
    settings.update(extras)
    ws.settings = settings
    flag_modified(ws, 'settings')
    ws.updated_at = datetime.utcnow()
    db.session.commit()


def _patch_project_decoration(project_id, decoration: dict) -> None:
    pid = to_uuid(project_id)
    p = db.session.execute(select(Project).where(Project.id == pid)).scalar_one()
    settings = dict(p.settings or {})

    if 'pinned' in decoration:
        settings['pinned'] = bool(decoration['pinned'])
    if 'archived' in decoration:
        p.archived = bool(decoration['archived'])
    if 'tags' in decoration and decoration['tags'] is not None:
        p.tags = list(decoration['tags'])
        flag_modified(p, 'tags')
    if 'group' in decoration:
        settings['group'] = decoration['group']
    if 'last_activity_at' in decoration:
        v = decoration['last_activity_at']
        settings['last_activity_at'] = v.isoformat() if isinstance(v, datetime) else v

    p.settings = settings
    flag_modified(p, 'settings')
    p.updated_at = datetime.utcnow()
    db.session.commit()


def _backdate_conversation(conversation_id, created_at: datetime, last_message_at: datetime) -> None:
    cid = to_uuid(conversation_id)
    db.session.execute(
        sa_update(Conversation)
        .where(Conversation.id == cid)
        .values(created_at=created_at, last_message_at=last_message_at)
    )
    db.session.commit()


def _backdate_usage_log(generation_id: str, ts: datetime) -> None:
    db.session.execute(
        sa_update(UsageLog)
        .where(UsageLog.generation_id == generation_id)
        .values(created_at=ts)
    )
    db.session.commit()


def _backdate_image(image_id, ts: datetime) -> None:
    iid = to_uuid(image_id)
    db.session.execute(
        sa_update(GeneratedImage)
        .where(GeneratedImage.id == iid)
        .values(created_at=ts)
    )
    db.session.commit()


def _backdate_workflow_run(run_id, started_at: datetime) -> None:
    rid = to_uuid(run_id)
    db.session.execute(
        sa_update(WorkflowRun)
        .where(WorkflowRun.id == rid)
        .values(started_at=started_at)
    )
    db.session.commit()


def _backdate_dlp_event(event_id, ts: datetime) -> None:
    eid = to_uuid(event_id)
    db.session.execute(
        sa_update(DLPEvent)
        .where(DLPEvent.id == eid)
        .values(created_at=ts)
    )
    db.session.commit()


def _backdate_invite_expires(invite_id, expires_at: datetime) -> None:
    iid = to_uuid(invite_id)
    db.session.execute(
        sa_update(WorkspaceInvite)
        .where(WorkspaceInvite.id == iid)
        .values(expires_at=expires_at)
    )
    db.session.commit()


def _mark_invite_accepted(invite_id, accepted_at: datetime) -> None:
    iid = to_uuid(invite_id)
    db.session.execute(
        sa_update(WorkspaceInvite)
        .where(WorkspaceInvite.id == iid)
        .values(accepted_at=accepted_at)
    )
    db.session.commit()


def _find_pending_invite(workspace_id, email: str):
    wid = to_uuid(workspace_id)
    row = db.session.execute(
        select(WorkspaceInvite).where(
            WorkspaceInvite.workspace_id == wid,
            WorkspaceInvite.email == email,
            WorkspaceInvite.accepted_at.is_(None),
        )
    ).scalar_one_or_none()
    return row


def _find_knowledge_folder(project_id, name: str):
    pid = to_uuid(project_id)
    f = db.session.execute(
        select(KnowledgeFolder).where(
            KnowledgeFolder.project_id == pid,
            KnowledgeFolder.name == name,
        )
    ).scalar_one_or_none()
    if f is None:
        return None
    out = f.to_dict()
    out['_id'] = str(f.id)
    return out


# Per-model token costs (USD per token).
_MODEL_COSTS = {
    'openai/gpt-4o':                 (0.0000025, 0.0000100),
    'anthropic/claude-sonnet-4.5':   (0.0000030, 0.0000150),
    'google/gemini-3.6-flash': (0.0000003, 0.0000012),
    'x-ai/grok-4.1-fast':            (0.0000005, 0.0000015),
}
_MODEL_PROVIDERS = {
    'openai/gpt-4o': 'OpenAI',
    'anthropic/claude-sonnet-4.5': 'Anthropic',
    'google/gemini-3.6-flash': 'Google',
    'x-ai/grok-4.1-fast': 'xAI',
}
_MODEL_WEIGHTS = [0.55, 0.28, 0.12, 0.05]


def seed_credit_ledger(ws, owner) -> None:
    """Top up workspace credits + sync cached balance on the workspace doc."""
    entries = [
        (5000.0, 'top_up',     'Initial annual top-up'),
        (1500.0, 'top_up',     'Mid-year reload'),
        (-120.0, 'adjustment', 'Refund for unused vendor tokens'),
    ]
    for amount, type_, note in entries:
        try:
            CreditLedgerModel.add_entry(
                ws['_id'],
                amount_usd=amount,
                type=type_,
                note=note,
                added_by=owner['_id'],
            )
        except Exception as exc:
            log(f'    ! ledger entry skipped: {exc}')

    try:
        total = CreditLedgerModel.sum_credits(ws['_id'])
        WorkspaceModel.update(ws['_id'], {'credits_balance_usd': float(total)})
    except Exception as exc:
        log(f'    ! credit balance sync skipped: {exc}')


def seed_usage_logs(ws, users, projects, days: int = 30) -> int:
    """Backfill `days` days of realistic usage_logs across users + projects."""
    if not users or not projects:
        return 0

    total = 0
    seed_id = str(ws['_id'])[-6:]
    for day in range(days):
        ts_base = datetime.utcnow() - timedelta(days=day)
        n_calls = random.randint(40, 90)
        for _ in range(n_calls):
            user = random.choice(users)
            project = random.choice(projects)
            model = random.choices(list(_MODEL_COSTS.keys()), weights=_MODEL_WEIGHTS)[0]
            prompt_tokens = random.randint(180, 4200)
            completion_tokens = random.randint(60, 1100)
            cached_tokens = random.randint(0, prompt_tokens // 4)
            p_cost, c_cost = _MODEL_COSTS[model]
            cost_usd = (prompt_tokens - cached_tokens) * p_cost \
                + cached_tokens * (p_cost * 0.1) \
                + completion_tokens * c_cost
            ts = ts_base.replace(
                hour=random.randint(8, 22),
                minute=random.randint(0, 59),
                second=random.randint(0, 59),
                microsecond=0,
            )
            gen_id = f'gen-acme-{seed_id}-{day:02d}-{total:05d}'
            try:
                UsageLogModel.create(
                    generation_id=gen_id,
                    user_id=user['_id'],
                    workspace_id=ws['_id'],
                    project_id=project['_id'],
                    model=model,
                    provider=_MODEL_PROVIDERS[model],
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cached_tokens=cached_tokens,
                    cost_usd=round(cost_usd, 6),
                    origin=random.choice(['web', 'web', 'web', 'arena', 'workflow']),
                    is_streaming=random.random() < 0.7,
                    finish_reason='stop',
                )
                _backdate_usage_log(gen_id, ts)
                total += 1
            except Exception:
                pass
    return total


# -----------------------------------------------------------------------------
# Knowledge folders + items + assistants
# -----------------------------------------------------------------------------

KNOWLEDGE_FOLDERS = {
    'engineering': [
        {'name': 'Architecture Notes',  'color': '#5c9aed'},
        {'name': 'Bug Investigations',  'color': '#ef4444'},
        {'name': 'Onboarding Snippets', 'color': '#10b981'},
    ],
    'design': [
        {'name': 'Brand Voice',          'color': '#f59e0b'},
        {'name': 'Component Specs',      'color': '#a78bfa'},
        {'name': 'Research Highlights',  'color': '#ec4899'},
    ],
    'operations': [
        {'name': 'Runbooks',             'color': '#10b981'},
        {'name': 'Vendor Notes',         'color': '#5c9aed'},
        {'name': 'Compliance Evidence',  'color': '#f59e0b'},
    ],
}

KNOWLEDGE_ITEMS = [
    ('Service-A handshake decision',
     'Standardized on Postgres + Redis behind the existing API gateway. Hold on a service mesh until > 5k RPS.',
     ['decision', 'arch']),
    ('Auth refactor — phase 1',
     'Split session-token storage from refresh-token storage. Refresh tokens move to encrypted-at-rest with rotation on each use.',
     ['auth', 'security']),
    ('Customer feedback themes',
     'Top three: pricing transparency, integration timelines, reliability concerns on EU region.',
     ['cs', 'feedback']),
    ('Brand voice — concise',
     'Calm, warm, opinionated. Drop buzzwords. Lead with outcome, follow with proof.',
     ['brand']),
    ('Onboarding day-1 checklist',
     'Slack invite, GitHub access, paired-coding ticket, manager 1:1 booked, lunch buddy assigned.',
     ['hr', 'onboarding']),
    ('SOC2 audit gap — Q2',
     'Need evidence on access-review cadence and key-rotation logs. Owner: Olga. Due: 2026-06-15.',
     ['compliance']),
]

ASSISTANT_PRESETS = {
    'engineering': [
        {
            'name': 'Code Reviewer',
            'desc': 'Strict reviewer focused on correctness, perf, and security. No style nits.',
            'model_id': 'anthropic/claude-sonnet-4.5', 'model_name': 'Claude Sonnet 4.5',
            'sys': 'You are a senior staff engineer reviewing diffs. Flag correctness bugs, perf regressions, and security issues. Skip style nits. One line per finding: file:line — problem — fix.',
            'tags': ['review', 'engineering'],
        },
        {
            'name': 'Incident Postmortem',
            'desc': 'Drafts blameless postmortems from raw incident notes.',
            'model_id': 'openai/gpt-4o', 'model_name': 'GPT-4o',
            'sys': 'You write blameless postmortems. Sections: TL;DR, Timeline, Root cause, Contributing factors, Action items (owner + due date). Avoid blame language.',
            'tags': ['ops', 'engineering'],
        },
    ],
    'design': [
        {
            'name': 'Brand Copywriter',
            'desc': 'Calm, warm, opinionated. Writes Instagram + landing copy.',
            'model_id': 'google/gemini-3.6-flash', 'model_name': 'Gemini 3 Flash',
            'sys': 'You write in a calm, warm, opinionated voice. Lead with outcome, drop buzzwords. Variants must differ in angle, not phrasing.',
            'tags': ['copy', 'brand'],
        },
        {
            'name': 'UX Critic',
            'desc': 'Critiques flows for cognitive load and accessibility blockers.',
            'model_id': 'anthropic/claude-sonnet-4.5', 'model_name': 'Claude Sonnet 4.5',
            'sys': 'Critique UX flows. Surface cognitive-load issues, accessibility blockers, and edge cases. Tone: direct, no praise.',
            'tags': ['ux', 'a11y'],
        },
    ],
    'operations': [
        {
            'name': 'HR Onboarding Bot',
            'desc': 'Answers HR onboarding FAQs with company-specific policies.',
            'model_id': 'openai/gpt-4o', 'model_name': 'GPT-4o',
            'sys': 'You are the HR onboarding assistant for Acme Operations. Cite policy section names when relevant. Escalate benefits questions to a human.',
            'tags': ['hr'],
        },
        {
            'name': 'Vendor Triage',
            'desc': 'Triages vendor support tickets into priority + owner.',
            'model_id': 'x-ai/grok-4.1-fast', 'model_name': 'Grok 4.1 Fast',
            'sys': 'Triage vendor support tickets. Output: priority (P0-P3), owner team, suggested first reply.',
            'tags': ['vendor'],
        },
    ],
}


def seed_knowledge_and_assistants(ws, manager, projects, company_key):
    """Per-project knowledge folders + items, plus 1 workspace + 1 project assistant."""
    folders_specs = KNOWLEDGE_FOLDERS.get(company_key, [])
    if not projects or not folders_specs:
        return 0, 0, 0

    folder_count = 0
    item_count = 0
    for project in projects:
        for spec in folders_specs[: random.randint(2, 3)]:
            existing = _find_knowledge_folder(project['_id'], spec['name'])
            if existing:
                folder = existing
            else:
                try:
                    folder = KnowledgeFolderModel.create(
                        user_id=manager['_id'],
                        name=spec['name'],
                        color=spec['color'],
                        project_id=project['_id'],
                        workspace_id=ws['_id'],
                    )
                    folder_count += 1
                except Exception as exc:
                    log(f'    ! skip kfolder {spec["name"]}: {exc}')
                    continue
            sample = random.sample(KNOWLEDGE_ITEMS, k=min(random.randint(2, 4), len(KNOWLEDGE_ITEMS)))
            for title, content, tags in sample:
                try:
                    KnowledgeItemModel.create(
                        user_id=manager['_id'],
                        source_type='chat',
                        source_id=None,
                        message_id=None,
                        content=content,
                        title=title,
                        tags=tags,
                        folder_id=str(folder['_id']),
                        project_id=project['_id'],
                        workspace_id=ws['_id'],
                    )
                    item_count += 1
                except Exception:
                    pass

    assistant_count = 0
    presets = ASSISTANT_PRESETS.get(company_key, [])
    if presets:
        first = presets[0]
        try:
            LLMConfigModel.create(
                name=first['name'],
                model_id=first['model_id'],
                model_name=first['model_name'],
                owner_id=manager['_id'],
                description=first['desc'],
                system_prompt=first['sys'],
                visibility='public',
                tags=first['tags'],
                workspace_id=ws['_id'],
            )
            assistant_count += 1
        except Exception as exc:
            log(f'    ! skip assistant {first["name"]}: {exc}')

        if len(presets) > 1 and projects:
            second = presets[1]
            target_project = projects[0]
            try:
                LLMConfigModel.create(
                    name=second['name'],
                    model_id=second['model_id'],
                    model_name=second['model_name'],
                    owner_id=manager['_id'],
                    description=second['desc'],
                    system_prompt=second['sys'],
                    visibility='project',
                    tags=second['tags'],
                    project_id=target_project['_id'],
                    workspace_id=ws['_id'],
                )
                assistant_count += 1
            except Exception as exc:
                log(f'    ! skip assistant {second["name"]}: {exc}')

    return folder_count, item_count, assistant_count


# -----------------------------------------------------------------------------
# DLP events + invite variety
# -----------------------------------------------------------------------------

DLP_RULE_SAMPLES = [
    {'rule_id': 'aws_access_key', 'rule_name': 'AWS Access Key',
     'severity': 'critical', 'action_taken': 'block',
     'description': 'AWS access key detected in user input.', 'source': 'builtin',
     'snippet': 'AKIA••••••••XYZ12'},
    {'rule_id': 'openai_api_key', 'rule_name': 'OpenAI API Key',
     'severity': 'critical', 'action_taken': 'block',
     'description': 'OpenAI API key detected.', 'source': 'builtin',
     'snippet': 'sk-proj-••••••••abc'},
    {'rule_id': 'email_address', 'rule_name': 'Email PII',
     'severity': 'medium', 'action_taken': 'warn',
     'description': 'Email address detected.', 'source': 'builtin',
     'snippet': 'a••••@acme-holding.com'},
    {'rule_id': 'national_id_iran', 'rule_name': 'Iran National ID',
     'severity': 'high', 'action_taken': 'require_confirm',
     'description': 'Iran national ID pattern detected.', 'source': 'builtin',
     'snippet': '••••••1234'},
    {'rule_id': 'cc_pan', 'rule_name': 'Credit Card PAN',
     'severity': 'high', 'action_taken': 'require_confirm',
     'description': 'Credit card number detected.', 'source': 'builtin',
     'snippet': '4242•••••••4242'},
    {'rule_id': 'internal_jira_id', 'rule_name': 'Internal Jira ID',
     'severity': 'low', 'action_taken': 'warn',
     'description': 'Internal Jira ticket reference.', 'source': 'custom',
     'snippet': 'ENG-12••'},
]


def seed_dlp_events(ws, manager, employees_users, projects):
    if not projects or not employees_users:
        return 0
    actors = employees_users + [manager]
    count = 0
    for day in range(14):
        for _ in range(random.randint(0, 3)):
            sample = random.choice(DLP_RULE_SAMPLES)
            user = random.choice(actors)
            project = random.choice(projects)
            highest = sample['action_taken']
            was_sent = highest == 'warn' or (highest == 'require_confirm' and random.random() < 0.5)
            text = f'Sample violation snippet {sample["rule_id"]} #{count}'
            text_sha = hashlib.sha256(text.encode()).hexdigest()
            match = {
                'rule_id': sample['rule_id'],
                'rule_name': sample['rule_name'],
                'severity': sample['severity'],
                'action_taken': sample['action_taken'],
                'snippet': sample['snippet'],
                'description': sample['description'],
                'source': sample['source'],
                'offset_start': 0,
                'offset_end': len(sample['snippet']),
            }
            try:
                doc = DLPEventModel.create(
                    user_id=user['_id'],
                    workspace_id=ws['_id'],
                    project_id=project['_id'],
                    source=random.choice(['chat', 'chat', 'chat', 'arena', 'workflow']),
                    source_ref={},
                    matches=[match],
                    highest_action=highest,
                    was_sent=was_sent,
                    text_sha256=text_sha,
                    text_length=len(text),
                    user_acknowledged=(highest == 'require_confirm' and was_sent),
                    status=random.choice(['open', 'open', 'open', 'reviewed', 'dismissed']),
                )
                ts = datetime.utcnow() - timedelta(days=day, hours=random.randint(0, 23))
                _backdate_dlp_event(doc['_id'], ts)
                count += 1
            except Exception:
                pass
    return count


def seed_invite_variety(ws, manager, company_key):
    """Add 1 expired + 1 accepted-historic invite per company (on top of base pending invite)."""
    extra_emails = {
        'engineering': [
            {'email': f'expired.eng@{DOMAIN}',     'role': 'editor', 'state': 'expired'},
            {'email': f'joined.eng.q1@{DOMAIN}',   'role': 'editor', 'state': 'accepted'},
        ],
        'design': [
            {'email': f'expired.design@{DOMAIN}',     'role': 'viewer', 'state': 'expired'},
            {'email': f'joined.design.q1@{DOMAIN}',   'role': 'editor', 'state': 'accepted'},
        ],
        'operations': [
            {'email': f'expired.ops@{DOMAIN}',     'role': 'viewer', 'state': 'expired'},
            {'email': f'joined.ops.q1@{DOMAIN}',   'role': 'editor', 'state': 'accepted'},
        ],
    }
    added = 0
    for spec in extra_emails.get(company_key, []):
        try:
            invite = WorkspaceInviteModel.create(
                ws['_id'], spec['email'], spec['role'], manager['_id'],
            )
        except Exception:
            continue
        if spec['state'] == 'expired':
            _backdate_invite_expires(invite['_id'], datetime.utcnow() - timedelta(days=2))
        elif spec['state'] == 'accepted':
            _mark_invite_accepted(invite['_id'], datetime.utcnow() - timedelta(days=random.randint(1, 30)))
        added += 1
    return added


# -----------------------------------------------------------------------------
# Workflows + workflow runs
# -----------------------------------------------------------------------------

def _build_simple_workflow(name_prefix: str, project_name: str) -> dict:
    """Tiny 2-node textInput -> aiAgent workflow."""
    nodes = [
        {
            'id': 'brief-1',
            'type': 'textInput',
            'position': {'x': 50, 'y': 100},
            'data': {
                'label': 'Brief',
                'text': f'Draft launch announcement for {project_name}.',
                'placeholder': 'Describe the brief...',
            },
        },
        {
            'id': 'copy-1',
            'type': 'aiAgent',
            'position': {'x': 400, 'y': 100},
            'data': {
                'label': 'Copywriter',
                'model': 'google/gemini-3.6-flash',
                'systemPrompt': 'You write tight launch announcements: hook, 3 bullets, CTA.',
                'user_prompt_template': '{{input}}',
                'output': None,
            },
        },
    ]
    edges = [{
        'id': 'e-brief-copy-1',
        'source': 'brief-1', 'target': 'copy-1',
        'sourceHandle': 'output', 'targetHandle': 'input-0',
    }]
    return {
        'name': f'{name_prefix} — {project_name}',
        'description': f'Launch copy for {project_name}',
        'nodes': nodes,
        'edges': edges,
    }


def seed_workflows_and_runs(ws, manager, projects):
    if not projects:
        return 0, 0
    wf_count = 0
    run_count = 0
    for project in projects[:3]:
        spec = _build_simple_workflow('Launch Copy', project['name'])
        try:
            wf_id = WorkflowModel.create(
                user_id=str(manager['_id']),
                name=spec['name'],
                description=spec['description'],
                nodes=spec['nodes'],
                edges=spec['edges'],
                project_id=str(project['_id']),
                workspace_id=str(ws['_id']),
                category='social-media',
            )
            wf_count += 1
        except Exception as exc:
            log(f'    ! skip workflow {spec["name"]}: {exc}')
            continue

        for status, output in [('completed', 'Launch announcement draft v1.'), ('failed', None)]:
            try:
                run_id = WorkflowRunModel.create(
                    workflow_id=wf_id,
                    user_id=str(manager['_id']),
                    execution_mode='full',
                )
                if status == 'completed':
                    WorkflowRunModel.update_node_result(run_id, 'copy-1', {
                        'status': 'completed',
                        'text': output,
                        'generation_time_ms': random.randint(800, 3000),
                        'completed_at': datetime.utcnow(),
                    })
                    WorkflowRunModel.update_status(run_id, 'completed')
                else:
                    WorkflowRunModel.update_node_result(run_id, 'copy-1', {
                        'status': 'failed',
                        'error': 'OpenRouter timeout after 30s.',
                    })
                    WorkflowRunModel.update_status(run_id, 'failed')
                _backdate_workflow_run(
                    run_id,
                    datetime.utcnow() - timedelta(days=random.randint(0, 10)),
                )
                run_count += 1
            except Exception:
                pass
    return wf_count, run_count


# -----------------------------------------------------------------------------
# Generated images + arena + debate
# -----------------------------------------------------------------------------

# 1×1 transparent PNG so we don't bloat the DB with real binary data.
_TINY_PNG = (
    'data:image/png;base64,'
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=='
)

IMAGE_PROMPTS = [
    'Square 1:1 product hero shot, warm light, minimal background.',
    'Wide 16:9 landing banner, abstract gradient, brand-warm palette.',
    'Portrait 9:16 social story, lifestyle scene, soft morning light.',
    'Square illustrated icon, flat 2-color style, brand accent palette.',
]

DEBATE_TOPICS = [
    'Should we adopt monorepo or polyrepo?',
    'Is offshore expansion worth the operational tax?',
    'Should we prioritize EU launch or APAC launch first?',
]


def _create_arena_session(user_id, title, config_ids):
    """Insert an ArenaSession row directly (the legacy model accepted raw inserts)."""
    s = ArenaSession(
        user_id=to_uuid(user_id),
        title=title,
        config_ids=config_ids,
    )
    db.session.add(s)
    db.session.commit()
    return str(s.id)


def _create_debate_session(user_id, topic, config_ids, judge_config_id, final_verdict):
    """Insert a DebateSession row directly so we can attach quick: configs."""
    s = DebateSession(
        user_id=to_uuid(user_id),
        topic=topic,
        config_ids=config_ids,
        judge_config_id=judge_config_id,
        settings={'rounds': 2, 'max_tokens': 1024, 'thinking_type': 'balanced', 'response_length': 'balanced'},
        status='completed',
        current_round=2,
        final_verdict=final_verdict,
    )
    db.session.add(s)
    db.session.commit()
    return str(s.id)


def seed_artifacts(ws, manager, employees_users):
    """Generated images + 1 arena session + 1 debate session per company."""
    if not employees_users:
        return 0, 0, 0
    img_count = 0
    arena_count = 0
    debate_count = 0

    image_actors = [manager] + random.sample(
        employees_users, k=min(2, len(employees_users))
    )
    for actor in image_actors:
        for _ in range(random.randint(2, 3)):
            try:
                doc = GeneratedImageModel.create(
                    user_id=str(actor['_id']),
                    prompt=random.choice(IMAGE_PROMPTS),
                    model_id=random.choice([
                        'google/gemini-2.5-flash-image',
                        'google/gemini-3.1-flash-image',
                        'openai/gpt-5-image',
                    ]),
                    image_data=_TINY_PNG,
                    settings={'input_images_count': 0, 'has_input_images': False, 'aspect_ratio': '1:1'},
                    metadata={'workspace_id': str(ws['_id'])},
                )
                _backdate_image(doc['_id'], datetime.utcnow() - timedelta(days=random.randint(0, 14)))
                img_count += 1
            except Exception:
                pass

    # Arena — 1 session w/ 2 quick configs (stored as strings).
    try:
        sess_id = _create_arena_session(
            manager['_id'],
            'Model comparison — launch copy',
            ['quick:gpt-4o', 'quick:claude-sonnet-4-5'],
        )
        ArenaMessageModel.create(sess_id, 'user',
                                 'Draft a launch announcement for the new SDK.',
                                 config_id=None)
        ArenaMessageModel.create(sess_id, 'assistant',
                                 'Hook + 3 bullets + CTA. Tight, no buzzwords.',
                                 config_id='quick:gpt-4o')
        ArenaMessageModel.create(sess_id, 'assistant',
                                 'Lead with developer outcome, then proof, then CTA.',
                                 config_id='quick:claude-sonnet-4-5')
        arena_count = 1
    except Exception:
        pass

    # Debate — 1 session w/ 2 debaters + judge.
    try:
        deb_id = _create_debate_session(
            manager['_id'],
            random.choice(DEBATE_TOPICS),
            ['quick:gpt-4o', 'quick:claude-sonnet-4-5'],
            'quick:gemini-3-flash',
            'Both arguments valid. Lean monorepo if tooling discipline holds.',
        )
        DebateMessageModel.create(deb_id, 1, 'quick:gpt-4o', 'debater',
                                  'Monorepo wins on atomic commits + shared tooling.', 0)
        DebateMessageModel.create(deb_id, 1, 'quick:claude-sonnet-4-5', 'debater',
                                  'Polyrepo isolates blast radius and CI cost.', 1)
        DebateMessageModel.create(deb_id, 0, 'quick:gemini-3-flash', 'judge',
                                  'Both arguments valid. Lean monorepo.', 0)
        debate_count = 1
    except Exception:
        pass

    return img_count, arena_count, debate_count


# -----------------------------------------------------------------------------
# Seed steps
# -----------------------------------------------------------------------------

def seed_users():
    log('seeding users…')
    by_email = {}
    by_email[CEO['email']] = upsert_user(CEO['email'], CEO['name'], CEO['role'])
    for m in MANAGERS:
        by_email[m['email']] = upsert_user(m['email'], m['name'], m['role'])
    for e in EMPLOYEES:
        by_email[e['email']] = upsert_user(e['email'], e['name'], 'user')
    log(f'  -> {len(by_email)} users (1 CEO + {len(MANAGERS)} managers + {len(EMPLOYEES)} employees)')
    return by_email


def seed_company(company_key: str, users_by_email: dict):
    spec = COMPANIES[company_key]
    log(f'seeding company "{spec["name"]}"…')

    manager = users_by_email[spec['manager_email']]
    ceo = users_by_email[CEO['email']]

    # Workspace
    ws = find_workspace_by_slug(spec['slug'])
    if not ws:
        WorkspaceModel.create(spec['name'], manager['_id'], type='team')
        ws = find_workspace_by_slug(spec['slug'])
    _force_workspace_extras(ws['_id'], {
        'domain': DOMAIN,
        'plan_tier': 'business',
    })
    ws = find_workspace_by_slug(spec['slug'])

    # Memberships: manager owns; CEO owner too; employees per spec
    upsert_membership(ws['_id'], manager['_id'], 'owner', manager['_id'], spec['manager_email'])
    upsert_membership(ws['_id'], ceo['_id'], 'owner', manager['_id'], CEO['email'])
    for e in EMPLOYEES:
        if e['company'] != company_key:
            continue
        user = users_by_email[e['email']]
        upsert_membership(ws['_id'], user['_id'], e['ws_role'], manager['_id'], e['email'])
        # Set active workspace so demo users land in their company
        UserModel.set_active_workspace(user['_id'], ws['_id'])

    # Groups
    groups_by_name = {}
    for g in spec['groups']:
        existing = find_group_by_name(ws['_id'], g['name'])
        if existing:
            groups_by_name[g['name']] = existing
            continue
        try:
            doc = GroupModel.create(
                workspace_id=ws['_id'],
                name=g['name'],
                created_by=manager['_id'],
                color=g['color'],
                icon=g['icon'],
                description=g['description'],
            )
            groups_by_name[g['name']] = doc
        except Exception as exc:
            log(f'    ! skip group {g["name"]}: {exc}')
    for e in EMPLOYEES:
        if e['company'] != company_key:
            continue
        group = groups_by_name.get(e['group'])
        if not group:
            continue
        user = users_by_email[e['email']]
        GroupMemberModel.add(group['_id'], user['_id'], manager['_id'])
    for g in groups_by_name.values():
        try:
            GroupModel.recompute_member_count(g['_id'])
        except Exception:
            pass

    # Projects
    company_employees = [e for e in EMPLOYEES if e['company'] == company_key]
    projects_by_slug = {}
    for p in spec['projects']:
        existing = find_project_by_slug(ws['_id'], p['slug'])
        if existing:
            project = existing
        else:
            project = ProjectModel.create(
                workspace_id=ws['_id'],
                name=p['name'],
                created_by=manager['_id'],
                color=p['color'],
                icon=p['icon'],
                description=p['desc'],
            )
        _patch_project_decoration(project['_id'], {
            'pinned': p['pinned'],
            'archived': p['archived'],
            'tags': p['tags'],
            'group': p['group'],
            'last_activity_at': datetime.utcnow() - timedelta(minutes=random.randint(5, 4320)),
        })
        project = ProjectModel.find_by_id(project['_id'])
        projects_by_slug[p['slug']] = project

        # Manager is implicit owner via workspace fallback — no explicit project owner.
        # Add 1-3 explicit editor members from the company.
        sample = random.sample(company_employees, k=min(3, len(company_employees)))
        for emp in sample:
            user = users_by_email[emp['email']]
            ProjectMemberModel.add(
                project['_id'], user['_id'],
                emp['ws_role'] if emp['ws_role'] in ('editor', 'viewer') else 'editor',
                added_by=manager['_id'],
            )

    # Group access on projects
    for slug, grants in spec['project_group_access'].items():
        project = projects_by_slug.get(slug)
        if not project:
            continue
        for group_name, role in grants:
            group = groups_by_name.get(group_name)
            if not group:
                continue
            ProjectGroupAccessModel.set(
                project['_id'], group['_id'], role,
                created_by=manager['_id'],
            )

    # Pending invite (so the Pending Invites UI has something to show)
    invite_spec = PENDING_INVITES.get(company_key)
    if invite_spec:
        existing_invite = _find_pending_invite(ws['_id'], invite_spec['email'])
        if not existing_invite:
            try:
                WorkspaceInviteModel.create(
                    ws['_id'], invite_spec['email'], invite_spec['role'], manager['_id'],
                )
            except Exception as exc:
                log(f'    ! skip invite {invite_spec["email"]}: {exc}')

    # Conversations + messages on non-archived projects.
    msg_count = 0
    employee_users = [users_by_email[e['email']] for e in company_employees]
    active_projects = [p for p in projects_by_slug.values() if not p.get('archived')]

    # Manager: 2 chats per active project
    for project in active_projects:
        for _ in range(2):
            conv = ConversationModel.create(
                user_id=manager['_id'],
                config_id=None,
                title=random.choice([
                    f"{project['name']} planning",
                    f"Notes — {project['name']}",
                    f"{project['name']} review",
                    f"Roadmap — {project['name']}",
                ]),
                project_id=project['_id'],
            )
            _backdate_conversation(
                conv['_id'],
                datetime.utcnow() - timedelta(days=random.randint(0, 14)),
                datetime.utcnow() - timedelta(minutes=random.randint(2, 7200)),
            )
            for _ in range(random.randint(2, 4)):
                MessageModel.create_user_message(conv['_id'], random.choice(SAMPLE_PROMPTS))
                MessageModel.create_assistant_message(
                    conv['_id'],
                    random.choice(SAMPLE_REPLIES),
                    model_id=random.choice(MODEL_IDS),
                )
                msg_count += 2

    # Each employee: 1 chat in a random active project
    for emp_user in employee_users:
        if not active_projects:
            break
        project = random.choice(active_projects)
        conv = ConversationModel.create(
            user_id=emp_user['_id'],
            config_id=None,
            title=f"My notes — {project['name']}",
            project_id=project['_id'],
        )
        _backdate_conversation(
            conv['_id'],
            datetime.utcnow() - timedelta(days=random.randint(0, 14)),
            datetime.utcnow() - timedelta(minutes=random.randint(2, 7200)),
        )
        for _ in range(random.randint(2, 3)):
            MessageModel.create_user_message(conv['_id'], random.choice(SAMPLE_PROMPTS))
            MessageModel.create_assistant_message(
                conv['_id'],
                random.choice(SAMPLE_REPLIES),
                model_id=random.choice(MODEL_IDS),
            )
            msg_count += 2

    # Credit ledger — top-ups so Billing reads non-trivially
    seed_credit_ledger(ws, manager)

    # Usage logs — 30 days of activity for Dashboard charts
    usage_count = seed_usage_logs(ws, employee_users + [manager], active_projects)
    msg_count_str = f'{msg_count} messages, {usage_count} usage rows'

    # Audit log entries
    for action, target in [
        ('workspace_create',     spec['name']),
        ('member_invited',       invite_spec['email'] if invite_spec else 'newhire'),
        ('project_created',      spec['projects'][0]['name']),
        ('project_pinned',       spec['projects'][0]['name']),
        ('project_archived',     spec['projects'][-1]['name']),
        ('group_created',        spec['groups'][0]['name']),
    ]:
        try:
            AuditLogModel.create(
                action=action,
                admin_id=manager['_id'],
                target_id=str(ws['_id']),
                target_type='workspace',
                details={'workspace_id': str(ws['_id']), 'target': target},
            )
        except Exception:
            pass

    # Extensions
    active_project_list = active_projects
    folder_n, item_n, assistant_n = seed_knowledge_and_assistants(
        ws, manager, active_project_list, company_key,
    )
    dlp_n = seed_dlp_events(ws, manager, employee_users, active_project_list)
    invite_extra = seed_invite_variety(ws, manager, company_key)
    wf_n, wf_run_n = seed_workflows_and_runs(ws, manager, active_project_list)
    img_n, arena_n, debate_n = seed_artifacts(ws, manager, employee_users)

    log(f'  -> {len(spec["projects"])} projects, {len(groups_by_name)} groups, '
        f'{len(company_employees)} employees, {msg_count_str}')
    log(f'  -> knowledge: {folder_n} folders, {item_n} items; '
        f'assistants: {assistant_n}; dlp: {dlp_n}; invites+: {invite_extra}')
    log(f'  -> workflows: {wf_n} ({wf_run_n} runs); '
        f'images: {img_n}; arena: {arena_n}; debate: {debate_n}')
    return ws


def seed_holding():
    users = seed_users()
    for company_key in COMPANIES.keys():
        seed_company(company_key, users)


# -----------------------------------------------------------------------------
# Wipe (single TRUNCATE — Postgres FK cascade does the rest)
# -----------------------------------------------------------------------------

# Tables touched by this seeder; TRUNCATE … CASCADE wipes them + every
# FK-dependent row in one statement (workspaces ⇒ projects ⇒ conversations
# ⇒ messages, etc.). Demo users are removed by email afterwards so personal
# workspaces get rebuilt on the next signup.
_WIPE_TABLES = (
    'workspaces', 'workspace_members', 'workspace_invites',
    'projects', 'project_members', 'project_group_access',
    'groups', 'group_members',
    'conversations', 'messages',
    'usage_logs', 'credit_ledger', 'audit_logs',
    'knowledge_folders', 'knowledge_items',
    'llm_configs',
    'workflows', 'workflow_runs',
    'generated_images',
    'arena_sessions', 'arena_messages',
    'debate_sessions', 'debate_messages',
    'dlp_events',
)


def wipe_holding():
    log('wiping holding data via TRUNCATE…')
    db.session.execute(sa_text(
        f'TRUNCATE {", ".join(_WIPE_TABLES)} RESTART IDENTITY CASCADE'
    ))
    demo_emails = (
        [CEO['email']]
        + [m['email'] for m in MANAGERS]
        + [e['email'] for e in EMPLOYEES]
        + [v['email'] for v in PENDING_INVITES.values()]
        + [
            f'expired.eng@{DOMAIN}',  f'joined.eng.q1@{DOMAIN}',
            f'expired.design@{DOMAIN}',  f'joined.design.q1@{DOMAIN}',
            f'expired.ops@{DOMAIN}',  f'joined.ops.q1@{DOMAIN}',
        ]
    )
    db.session.execute(
        sa_text('DELETE FROM users WHERE email = ANY(:emails)'),
        {'emails': demo_emails},
    )
    db.session.commit()
    log('  -> wiped')


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Seed Acme Holding demo data.')
    parser.add_argument('--reset', action='store_true', help='Wipe + reseed.')
    parser.add_argument('--wipe',  action='store_true', help='Wipe only.')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.wipe or args.reset:
            wipe_holding()
        if args.wipe:
            log('done (wipe only).')
            return
        seed_holding()
        log('done.')

        company_slugs = [c['slug'] for c in COMPANIES.values()]
        ws_count = int(db.session.execute(
            select(func.count()).select_from(Workspace).where(Workspace.slug.in_(company_slugs))
        ).scalar() or 0)
        user_count = int(db.session.execute(
            select(func.count()).select_from(User).where(
                User.email.like(f'%@{DOMAIN}')
            )
        ).scalar() or 0)
        ws_ids_subq = select(Workspace.id).where(Workspace.slug.in_(company_slugs))
        proj_count = int(db.session.execute(
            select(func.count()).select_from(Project).where(Project.workspace_id.in_(ws_ids_subq))
        ).scalar() or 0)

        log(f'summary: {user_count} users, {ws_count} companies, {proj_count} projects')
        log(f'login: {CEO["email"]} / {DEMO_PASSWORD}  (CEO)')
        for m in MANAGERS:
            log(f'login: {m["email"]} / {DEMO_PASSWORD}  ({m["name"]} — {m["company"]} manager)')


if __name__ == '__main__':
    main()
