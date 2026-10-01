"""
Demo data seeder for the Workspace + Projects redesign showcase (SQLAlchemy / Postgres).

Creates a realistic enterprise workspace ("Acme HQ") with 9 users, 5 groups,
9 projects (2 pinned, 1 archived), conversations + messages, 30 days of usage
logs, credit ledger entries, and audit-log activity. Idempotent: safe to run
multiple times. ``--reset`` wipes demo records (keyed off email + workspace
slug) before reseeding.

Usage:
    cd backend
    ./.venv-uv/Scripts/python.exe scripts/seed_demo.py            # seed (additive)
    ./.venv-uv/Scripts/python.exe scripts/seed_demo.py --reset    # wipe + reseed
    ./.venv-uv/Scripts/python.exe scripts/seed_demo.py --wipe     # wipe only
"""
import argparse
import os
import random
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

# Load env BEFORE importing app so Config locks real values.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, '.env'), override=True)
sys.path.insert(0, ROOT)

from sqlalchemy import select, text as sa_text, update as sa_update  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.user import UserModel, User  # noqa: E402
from app.models.workspace import WorkspaceModel, Workspace  # noqa: E402
from app.models.workspace_member import WorkspaceMemberModel  # noqa: E402
from app.models.project import ProjectModel, Project  # noqa: E402
from app.models.project_member import ProjectMemberModel  # noqa: E402
from app.models.group import GroupModel, Group  # noqa: E402
from app.models.group_member import GroupMemberModel  # noqa: E402
from app.models.project_group_access import ProjectGroupAccessModel  # noqa: E402
from app.models.credit_ledger import CreditLedgerModel  # noqa: E402
from app.models.usage_log import UsageLogModel, UsageLog  # noqa: E402
from app.models.audit_log import AuditLogModel  # noqa: E402
from app.models.conversation import ConversationModel, Conversation  # noqa: E402
from app.models.message import MessageModel  # noqa: E402
from app.utils.ids import to_uuid  # noqa: E402


# -----------------------------------------------------------------------------
# Demo dataset (mirrors design package /parts/data.jsx)
# -----------------------------------------------------------------------------

DEMO_PASSWORD = 'demo1234'

USERS = [
    {'email': 'ava@acme.com',   'name': 'Ava Patel',    'ws_role': 'owner',         'hue': 220},
    {'email': 'leo@acme.com',   'name': 'Leo Schmidt',  'ws_role': 'editor',        'hue': 280},
    {'email': 'mei@acme.com',   'name': 'Mei Tanaka',   'ws_role': 'editor',        'hue': 160},
    {'email': 'jonas@acme.com', 'name': 'Jonas Berg',   'ws_role': 'editor',        'hue': 30},
    {'email': 'sara@acme.com',  'name': 'Sara Cohen',   'ws_role': 'editor',        'hue': 340},
    {'email': 'diego@acme.com', 'name': 'Diego Ruiz',   'ws_role': 'viewer',        'hue': 180},
    {'email': 'priya@acme.com', 'name': 'Priya Iyer',   'ws_role': 'editor',        'hue': 60},
    {'email': 'tom@vendor.io',  'name': 'Tom Wilkins',  'ws_role': 'viewer',        'hue': 0},
    {'email': 'yuki@acme.com',  'name': 'Yuki Sato',    'ws_role': 'editor',        'hue': 100},
]

WORKSPACE = {
    'name': 'Acme HQ',
    'slug': 'acme-hq',
    'type': 'team',
    'domain': 'acme.com',
    'sso_enforced': True,
    'scim_enabled': True,
    'plan_tier': 'enterprise',
    'seats_total': 60,
    'budget_mtd_usd': 5200.0,
    'renews_at': datetime(2026, 8, 14),
}

GROUPS = [
    {'name': 'Engineering',      'color': '#5c9aed', 'icon': 'cpu',     'description': 'Backend, frontend, platform.'},
    {'name': 'Design',           'color': '#a78bfa', 'icon': 'sparkle', 'description': 'Product + brand.'},
    {'name': 'Marketing',        'color': '#ec4899', 'icon': 'flame',   'description': 'Campaigns, brand, growth.'},
    {'name': 'Customer Success', 'color': '#10b981', 'icon': 'message', 'description': 'Onboarding + support.'},
    {'name': 'Leadership',       'color': '#f59e0b', 'icon': 'shield',  'description': 'Exec staff.'},
]

# Each entry: members = list of email keys.
GROUP_MEMBERS = {
    'Engineering':      ['leo@acme.com', 'jonas@acme.com', 'yuki@acme.com', 'mei@acme.com'],
    'Design':           ['mei@acme.com', 'ava@acme.com'],
    'Marketing':        ['priya@acme.com', 'sara@acme.com'],
    'Customer Success': ['diego@acme.com', 'priya@acme.com'],
    'Leadership':       ['ava@acme.com', 'leo@acme.com'],
}

PROJECTS = [
    {'slug': 'q3-launch-campaign',     'name': 'Q3 Launch Campaign',     'desc': 'Cross-team campaign for Helios v4',           'color': '#ec4899', 'icon': 'flame',     'pinned': True,  'archived': False, 'tags': ['campaign', 'helios'],     'group': 'Marketing'},
    {'slug': 'sales-enablement-bot',   'name': 'Sales Enablement Bot',   'desc': 'GPT-4o agent for AE objection handling',      'color': '#5c9aed', 'icon': 'bot',       'pinned': True,  'archived': False, 'tags': ['production', 'agent'],    'group': 'Marketing'},
    {'slug': 'internal-knowledge-hub', 'name': 'Internal Knowledge Hub', 'desc': 'RAG over Confluence + Notion',                'color': '#10b981', 'icon': 'database',  'pinned': False, 'archived': False, 'tags': ['rag', 'prod'],            'group': 'Engineering'},
    {'slug': 'brand-guidelines-v2',    'name': 'Brand Guidelines v2',    'desc': 'Voice + tone reference + asset gen',          'color': '#a78bfa', 'icon': 'package',   'pinned': False, 'archived': False, 'tags': ['brand'],                  'group': 'Design'},
    {'slug': 'legal-contracts',        'name': 'Legal — Contracts',      'desc': 'Restricted. NDA + MSA review agent',          'color': '#f59e0b', 'icon': 'shield',    'pinned': False, 'archived': False, 'tags': ['restricted'],             'group': 'Leadership'},
    {'slug': 'onboarding-playbook',    'name': 'Onboarding Playbook',    'desc': 'New-hire q&a + day-one checklist',            'color': '#06b6d4', 'icon': 'flag',      'pinned': False, 'archived': False, 'tags': ['hr'],                     'group': 'Customer Success'},
    {'slug': 'engineering-rfcs',       'name': 'Engineering RFCs',       'desc': 'Design doc reviewer + arch debates',          'color': '#6366f1', 'icon': 'gitBranch', 'pinned': False, 'archived': False, 'tags': ['rfc', 'arch'],            'group': 'Engineering'},
    {'slug': 'customer-research',      'name': 'Customer Research',      'desc': 'Interview synthesis + insights',              'color': '#84cc16', 'icon': 'users',     'pinned': False, 'archived': False, 'tags': [],                         'group': 'Customer Success'},
    {'slug': 'helios-v3-archived',     'name': 'Helios v3 (archived)',   'desc': 'Last cycle — kept for reference',             'color': '#71717a', 'icon': 'archive',   'pinned': False, 'archived': True,  'tags': ['archive'],                'group': 'Engineering'},
]

# Group access grants per project (group name → role).
PROJECT_GROUP_ACCESS = {
    'q3-launch-campaign':     [('Marketing', 'editor'), ('Design', 'viewer')],
    'sales-enablement-bot':   [('Marketing', 'editor')],
    'internal-knowledge-hub': [('Engineering', 'editor'), ('Customer Success', 'viewer')],
    'brand-guidelines-v2':    [('Design', 'editor'), ('Marketing', 'viewer')],
    'legal-contracts':        [('Leadership', 'editor')],
    'onboarding-playbook':    [('Customer Success', 'editor')],
    'engineering-rfcs':       [('Engineering', 'editor')],
    'customer-research':      [('Customer Success', 'editor')],
}

MODELS = [
    ('openai/gpt-4o',                  'OpenAI',    0.62),
    ('anthropic/claude-sonnet-4.5',    'Anthropic', 0.24),
    ('google/gemini-3.6-flash',  'Google',    0.09),
    ('x-ai/grok-4.1-fast',             'xAI',       0.05),
]

ACTIVITY_VERBS = [
    ('invited',  'sara@acme.com to Acme HQ',                 'workspace_invite'),
    ('updated',  'system prompt in Sales Enablement Bot',    'project_update'),
    ('archived', 'project Helios v3',                        'project_archive'),
    ('created',  'Q3 Launch Campaign',                       'project_create'),
    ('shared',   'Brand Guidelines v2 with Design group',    'project_share'),
    ('joined',   'Engineering group',                        'group_join'),
    ('rotated',  'workspace invite link',                    'invite_rotate'),
]


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def log(msg):
    try:
        print(f'[seed-demo] {msg}', flush=True)
    except UnicodeEncodeError:
        print(f'[seed-demo] {msg.encode("ascii", "replace").decode("ascii")}', flush=True)


def upsert_user(spec):
    existing = UserModel.find_by_email(spec['email'])
    if existing:
        return existing
    UserModel.create(spec['email'], DEMO_PASSWORD, spec['name'])
    return UserModel.find_by_email(spec['email'])


def find_project_by_slug(workspace_id, slug: str):
    """Find a project by (workspace_id, slug) directly via ORM."""
    wid = to_uuid(workspace_id)
    p = db.session.execute(
        select(Project).where(Project.workspace_id == wid, Project.slug == slug)
    ).scalar_one_or_none()
    if p is None:
        return None
    out = p.to_dict()
    out['_id'] = str(p.id)
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


def random_in_window(days_back: int) -> datetime:
    now = datetime.utcnow()
    delta_seconds = random.randint(0, days_back * 86400)
    return now - timedelta(seconds=delta_seconds)


def _force_workspace_extras(workspace_id, extras: dict) -> None:
    """Patch billing/decoration fields onto a Workspace row via ORM.

    Mirrors the Mongo `update_one({'$set': ...})` pattern but writes to
    columns and the ``settings`` JSONB blob directly.
    """
    from sqlalchemy.orm.attributes import flag_modified

    wid = to_uuid(workspace_id)
    ws = db.session.execute(select(Workspace).where(Workspace.id == wid)).scalar_one()
    settings = dict(ws.settings or {})
    settings.update(extras)
    ws.settings = settings
    flag_modified(ws, 'settings')
    ws.updated_at = datetime.utcnow()
    db.session.commit()


def _patch_project_decoration(project_id, decoration: dict) -> None:
    """Force pinned/archived/tags/group/last_activity_at onto a Project row.

    ``decoration`` may contain keys: ``pinned``, ``archived``, ``tags``,
    ``group``, ``last_activity_at`` (datetime).
    """
    from sqlalchemy.orm.attributes import flag_modified

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


def _set_active_workspace(user_id, workspace_id) -> None:
    UserModel.set_active_workspace(user_id, workspace_id)


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


# -----------------------------------------------------------------------------
# Seed steps
# -----------------------------------------------------------------------------

def seed_users() -> dict:
    log('seeding users…')
    by_email = {}
    for spec in USERS:
        user = upsert_user(spec)
        by_email[spec['email']] = user
    log(f'  -> {len(by_email)} users present')
    return by_email


def seed_workspace(users_by_email) -> dict:
    log('seeding workspace…')
    owner = users_by_email['ava@acme.com']
    ws = WorkspaceModel.find_by_slug(WORKSPACE['slug'])
    if not ws:
        WorkspaceModel.create(WORKSPACE['name'], owner['_id'], type='team')
        # If the natural slug was unique, find by the canonical slug; otherwise
        # the slug collision-resolver appended a suffix and we look up by owner.
        ws = WorkspaceModel.find_by_slug(WORKSPACE['slug'])
        if not ws:
            owned = WorkspaceModel.find_by_owner(owner['_id'])
            ws = next((w for w in owned if w.get('name') == WORKSPACE['name'] and w.get('type') == 'team'), None)

    _force_workspace_extras(ws['_id'], {
        'domain': WORKSPACE['domain'],
        'sso_enforced': WORKSPACE['sso_enforced'],
        'scim_enabled': WORKSPACE['scim_enabled'],
        'plan_tier': WORKSPACE['plan_tier'],
        'seats_total': WORKSPACE['seats_total'],
        'budget_mtd_usd': WORKSPACE['budget_mtd_usd'],
        'renews_at': WORKSPACE['renews_at'].isoformat() if isinstance(WORKSPACE['renews_at'], datetime) else WORKSPACE['renews_at'],
    })
    ws = WorkspaceModel.find_by_id(ws['_id'])
    log(f'  -> workspace {ws["name"]} ({ws["_id"]})')
    return ws


def seed_workspace_members(ws, users_by_email, owner) -> None:
    log('seeding workspace members…')
    for spec in USERS:
        user = users_by_email[spec['email']]
        # `add` is idempotent (returns existing row).
        WorkspaceMemberModel.add(
            ws['_id'],
            user['_id'],
            spec['ws_role'],
            invited_by=owner['_id'],
            invited_email=spec['email'],
            status='active',
        )
        # Force the demo role if the row pre-existed with something else.
        WorkspaceMemberModel.update_role(ws['_id'], user['_id'], spec['ws_role'])
        WorkspaceMemberModel.update_status(ws['_id'], user['_id'], 'active')

        # Set active_workspace_id on each demo user → they land in Acme HQ.
        _set_active_workspace(user['_id'], ws['_id'])
    log(f'  -> {len(USERS)} memberships set')


def seed_groups(ws, users_by_email, owner) -> dict:
    log('seeding groups…')
    by_name = {}
    for spec in GROUPS:
        existing = find_group_by_name(ws['_id'], spec['name'])
        if existing:
            by_name[spec['name']] = existing
            continue
        try:
            doc = GroupModel.create(
                workspace_id=ws['_id'],
                name=spec['name'],
                created_by=owner['_id'],
                color=spec['color'],
                icon=spec['icon'],
                description=spec['description'],
            )
            by_name[spec['name']] = doc
        except Exception as e:
            log(f'    ! skip group {spec["name"]}: {e}')

    for group_name, member_emails in GROUP_MEMBERS.items():
        group = by_name.get(group_name)
        if not group:
            continue
        for email in member_emails:
            user = users_by_email.get(email)
            if not user:
                continue
            GroupMemberModel.add(group['_id'], user['_id'], owner['_id'])
        try:
            GroupModel.recompute_member_count(group['_id'])
        except Exception:
            pass
    log(f'  -> {len(by_name)} groups + members')
    return by_name


def seed_projects(ws, users_by_email, groups_by_name, owner) -> dict:
    log('seeding projects…')
    by_slug = {}
    for spec in PROJECTS:
        existing = find_project_by_slug(ws['_id'], spec['slug'])
        if existing:
            project = existing
        else:
            project = ProjectModel.create(
                workspace_id=ws['_id'],
                name=spec['name'],
                created_by=owner['_id'],
                color=spec['color'],
                icon=spec['icon'],
                description=spec['desc'],
            )
        _patch_project_decoration(project['_id'], {
            'pinned': spec['pinned'],
            'tags': spec['tags'],
            'archived': spec['archived'],
            'group': spec['group'],
            'last_activity_at': datetime.utcnow() - timedelta(minutes=random.randint(2, 4320)),
        })
        project = ProjectModel.find_by_id(project['_id'])
        by_slug[spec['slug']] = project

        # Direct project owner = workspace owner (ava). Add a few direct members.
        ProjectMemberModel.add(project['_id'], owner['_id'], 'owner', added_by=owner['_id'])
        for email in ['mei@acme.com', 'priya@acme.com', 'jonas@acme.com'][:random.randint(1, 3)]:
            user = users_by_email.get(email)
            if not user:
                continue
            ProjectMemberModel.add(project['_id'], user['_id'], 'editor', added_by=owner['_id'])

    # Group access grants.
    for slug, grants in PROJECT_GROUP_ACCESS.items():
        project = by_slug.get(slug)
        if not project:
            continue
        for group_name, role in grants:
            group = groups_by_name.get(group_name)
            if not group:
                continue
            ProjectGroupAccessModel.set(
                project['_id'],
                group['_id'],
                role,
                created_by=owner['_id'],
            )
    log(f'  -> {len(by_slug)} projects + members + group access')
    return by_slug


def seed_conversations_and_messages(ws, users_by_email, projects_by_slug) -> int:
    log('seeding conversations + messages…')
    sample_prompts = [
        'Draft launch announcement for Helios v4.',
        'Summarize this MSA section in plain English.',
        'What objections come up most often in enterprise sales calls?',
        'Generate three blog post ideas about RAG.',
        'Critique this brand voice paragraph.',
        'Help me design an onboarding sequence for new engineers.',
    ]
    sample_replies = [
        "Here's a draft. I broke it into hero, body, and CTA sections so you can swap pieces independently.",
        "The clause limits liability to 12× the monthly fee, capped at $50k. Standard language for SaaS MSAs.",
        "Top three by frequency: integration timelines, data residency, and seat-based pricing for >500 users.",
        "1) State of the RAG stack in 2026  2) Embedding choice playbook  3) Failure-mode taxonomy.",
        "Voice reads slightly stiff. Loosening the second sentence and dropping 'leverage' would help.",
        "Day 1 setup, week 1 paired-coding, week 2 first PR, week 3 retrospective. Drafting checklists now.",
    ]

    total = 0
    for slug, project in projects_by_slug.items():
        if project.get('archived'):
            continue
        n_convs = random.randint(2, 5)
        for i in range(n_convs):
            user = random.choice(list(users_by_email.values()))
            conv = ConversationModel.create(
                user_id=user['_id'],
                config_id=None,
                title=random.choice([
                    f"{project['name']} planning",
                    f"Brainstorm — {project['name']}",
                    f"Notes on {project['name']}",
                    f"{project['name']} review",
                ]),
                project_id=project['_id'],
            )
            _backdate_conversation(
                conv['_id'],
                datetime.utcnow() - timedelta(days=random.randint(0, 14)),
                datetime.utcnow() - timedelta(minutes=random.randint(2, 7200)),
            )
            n_msgs = random.randint(2, 6)
            for j in range(n_msgs):
                prompt = random.choice(sample_prompts)
                reply = random.choice(sample_replies)
                MessageModel.create_user_message(conv['_id'], prompt)
                MessageModel.create_assistant_message(
                    conv['_id'],
                    reply,
                    model_id=random.choice([m[0] for m in MODELS]),
                )
                total += 2
    log(f'  -> {total} messages across conversations')
    return total


def seed_credit_ledger(ws, owner) -> None:
    log('seeding credit ledger…')
    # Three top-ups so the dashboard balance reads non-trivially.
    entries = [
        (5000.0, 'top_up',     'Initial annual top-up (Apr 2026)'),
        (2000.0, 'top_up',     'Mid-year reload'),
        (-150.0, 'adjustment', 'Refund to vendor for unused tokens'),
    ]
    for amount, type_, note in entries:
        CreditLedgerModel.add_entry(
            ws['_id'],
            amount_usd=amount,
            type=type_,
            note=note,
            added_by=owner['_id'],
        )

    # Rebuild the cached credits_balance_usd off the ledger sum.
    total_credits = CreditLedgerModel.sum_credits(ws['_id'])
    WorkspaceModel.update(ws['_id'], {'credits_balance_usd': float(total_credits)})
    log(f'  -> balance set to ${total_credits:,.2f}')


def seed_usage_logs(ws, users_by_email, projects_by_slug) -> int:
    log('seeding 30-day usage logs…')
    user_list = list(users_by_email.values())
    project_list = [p for p in projects_by_slug.values() if not p.get('archived')]
    model_weights = [m[2] for m in MODELS]
    model_ids = [m[0] for m in MODELS]
    providers = {m[0]: m[1] for m in MODELS}

    # Per-model per-token cost (USD) tuned so MTD totals look real.
    model_costs = {
        'openai/gpt-4o':                 (0.0000025, 0.0000100),  # prompt, completion per-token
        'anthropic/claude-sonnet-4.5':   (0.0000030, 0.0000150),
        'google/gemini-3.6-flash': (0.0000003, 0.0000012),
        'x-ai/grok-4.1-fast':            (0.0000005, 0.0000015),
    }

    total = 0
    # ~6 calls/day per active project * 30 days
    for day in range(30):
        ts_base = datetime.utcnow() - timedelta(days=day)
        n_calls = random.randint(80, 160)
        for _ in range(n_calls):
            user = random.choice(user_list)
            project = random.choice(project_list)
            model = random.choices(model_ids, weights=model_weights)[0]
            prompt_tokens = random.randint(180, 4200)
            completion_tokens = random.randint(60, 1100)
            cached_tokens = random.randint(0, prompt_tokens // 4)
            p_cost, c_cost = model_costs[model]
            cost_usd = (prompt_tokens - cached_tokens) * p_cost \
                + cached_tokens * (p_cost * 0.1) \
                + completion_tokens * c_cost
            ts = ts_base.replace(
                hour=random.randint(8, 22),
                minute=random.randint(0, 59),
                second=random.randint(0, 59),
                microsecond=0,
            )
            gen_id = f'gen-demo-{day:02d}-{total:05d}'
            UsageLogModel.create(
                generation_id=gen_id,
                user_id=user['_id'],
                workspace_id=ws['_id'],
                project_id=project['_id'],
                model=model,
                provider=providers[model],
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
    log(f'  -> {total} usage_logs rows')
    return total


def seed_audit_log(ws, users_by_email) -> None:
    log('seeding audit log…')
    actor_pool = ['ava@acme.com', 'leo@acme.com', 'mei@acme.com', 'priya@acme.com', 'jonas@acme.com']
    for verb, what, action in ACTIVITY_VERBS:
        actor = users_by_email[random.choice(actor_pool)]
        AuditLogModel.create(
            action=action,
            admin_id=actor['_id'],
            target_id=str(ws['_id']),
            target_type='workspace',
            details={'workspace_id': str(ws['_id']), 'verb': verb, 'what': what},
        )


# -----------------------------------------------------------------------------
# Wipe (SQL TRUNCATE — single statement cascades through all FK chains)
# -----------------------------------------------------------------------------

def wipe_demo():
    """Remove every record introduced by this script via a single TRUNCATE
    cascade. The Postgres FK chain handles dependent rows automatically:
    workspaces ⇒ workspace_members + invites + projects ⇒ project_members +
    project_group_access + conversations ⇒ messages, plus credit_ledger /
    usage_logs / audit_logs scoped to those workspaces.
    """
    log('wiping previous demo data via TRUNCATE…')
    db.session.execute(sa_text(
        'TRUNCATE workspaces, workspace_members, workspace_invites, '
        'projects, project_members, project_group_access, '
        'groups, group_members, '
        'conversations, messages, '
        'usage_logs, credit_ledger, audit_logs '
        'RESTART IDENTITY CASCADE'
    ))
    # Drop demo users last (after their owned workspaces vanish).
    demo_emails = [u['email'] for u in USERS]
    if demo_emails:
        db.session.execute(
            sa_text('DELETE FROM users WHERE email = ANY(:emails)'),
            {'emails': demo_emails},
        )
    db.session.commit()
    log('  -> wipe complete')


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Seed demo data for the redesign showcase.')
    parser.add_argument('--reset', action='store_true', help='Wipe demo data first, then reseed.')
    parser.add_argument('--wipe', action='store_true', help='Wipe demo data only (no reseed).')
    parser.add_argument('--seed', type=int, default=42, help='Random seed (default 42).')
    args = parser.parse_args()
    random.seed(args.seed)

    app = create_app()
    with app.app_context():
        if args.wipe or args.reset:
            wipe_demo()
        if args.wipe and not args.reset:
            return

        users = seed_users()
        ws = seed_workspace(users)
        owner = users['ava@acme.com']
        seed_workspace_members(ws, users, owner)
        groups = seed_groups(ws, users, owner)
        projects = seed_projects(ws, users, groups, owner)
        seed_conversations_and_messages(ws, users, projects)
        seed_credit_ledger(ws, owner)
        seed_usage_logs(ws, users, projects)
        seed_audit_log(ws, users)

        log('')
        log('=' * 60)
        log('Demo seeded. Sign in as any of these users (password: demo1234):')
        for u in USERS:
            log(f'  {u["ws_role"]:<14}  {u["email"]:<22}  {u["name"]}')
        log('=' * 60)
        log(f'Workspace: {ws["name"]} (slug "{ws["slug"]}")')
        log(f'Visit /workspaces/{ws["_id"]} for overview.')


if __name__ == '__main__':
    main()
