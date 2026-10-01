"""
Feature catalog for the in-app Helper guide.

`FEATURES` is the single source of truth for every user-facing route the
Helper can recommend. Each entry carries a `min_role` so the prompt builder
can hide gated features from users who can't reach them.

Permission tiers:
    min_role = None        -> any authenticated user
    min_role = 'manager'   -> users with global role 'manager' or 'admin'
    min_role = 'admin'     -> users with global role 'admin' (super-admin)
    min_role = 'owner'     -> workspace owner role (member_role)
"""
from __future__ import annotations

from typing import Optional


FEATURES: list[dict] = [
    {
        'route': '/agent',
        'name': 'Agent',
        'one_liner': 'All-in-one agent: images, data analysis, documents, multi-step tools, clarifying questions.',
        'min_role': None,
    },
    {
        'route': '/chat',
        'name': 'Chat',
        'one_liner': 'Stream conversations with any model + custom assistant.',
        'min_role': None,
    },
    {
        'route': '/dashboard',
        'name': 'Dashboard',
        'one_liner': 'Snapshot of recent activity, pinned items, and quick actions.',
        'min_role': None,
    },
    {
        'route': '/chat-history',
        'name': 'Chat History',
        'one_liner': 'Search, filter, and revisit every past conversation.',
        'min_role': None,
    },
    {
        'route': '/image-history',
        'name': 'Image History',
        'one_liner': 'Browse and re-download every image you generated.',
        'min_role': None,
    },
    {
        'route': '/configs',
        'name': 'Configs',
        'one_liner': 'Create custom assistants with model + system prompt + parameters.',
        'min_role': None,
    },
    {
        'route': '/workflow',
        'name': 'Workflow Editor',
        'one_liner': 'Build multi-step AI pipelines on a node canvas.',
        'min_role': None,
    },
    {
        'route': '/arena',
        'name': 'Compare models',
        'one_liner': 'Compare 2-4 models side-by-side on the same prompt.',
        'min_role': None,
    },
    {
        'route': '/debate',
        'name': 'Debate',
        'one_liner': 'Run a structured debate between 2-5 LLMs with a judge verdict.',
        'min_role': None,
    },
    {
        'route': '/knowledge',
        'name': 'Knowledge Vault',
        'one_liner': 'Bookmark AI responses into folders for re-use as context.',
        'min_role': None,
    },
    {
        'route': '/image-studio',
        'name': 'Image Studio',
        'one_liner': 'Text-to-image and image-to-image generation across Gemini + GPT models.',
        'min_role': None,
    },
    {
        'route': '/ocr',
        'name': 'Image text reader (OCR)',
        'one_liner': 'Read text from images and PDFs with a custom prompt.',
        'min_role': None,
    },
    {
        'route': '/email-writer',
        'name': 'Email Writer',
        'one_liner': 'Draft formal Persian/English emails and letters.',
        'min_role': None,
    },
    {
        'route': '/cv-checker',
        'name': 'CV Checker',
        'one_liner': 'Screen or improve CVs against a job description.',
        'min_role': None,
    },
    {
        'route': '/research',
        'name': 'Deep research',
        'one_liner': 'Long-form multi-source research with citations.',
        'min_role': None,
    },
    {
        'route': '/contracts',
        'name': 'Contract Reviewer',
        'one_liner': 'Risk matrix and clause notes for uploaded contracts.',
        'min_role': None,
    },
    {
        'route': '/tenders',
        'name': 'Tender Assistant',
        'one_liner': 'Compliance checklist and bid pack for tenders/RFQs.',
        'min_role': None,
    },
    {
        'route': '/shop',
        'name': 'Shop Assistant',
        'one_liner': 'Compare Digikala and Technolife prices for office/IT purchases.',
        'min_role': None,
    },
    {
        'route': '/data-analyzer',
        'name': 'Data Analyzer',
        'one_liner': 'Analyze spreadsheets and documents with a sandboxed Python loop.',
        'min_role': None,
    },
    {
        'route': '/presentations',
        'name': 'Presentations',
        'one_liner': 'Generate editable slide decks from a topic or brief.',
        'min_role': None,
    },
    {
        'route': '/payroll',
        'name': 'Payroll',
        'one_liner': 'Batch payroll slips from a spreadsheet.',
        'min_role': None,
    },
    {
        'route': '/helper',
        'name': 'Helper',
        'one_liner': 'In-app guide: where to go and how to use each assistant.',
        'min_role': None,
    },
    {
        'route': '/automate-agent',
        'name': 'Automate Agent',
        'one_liner': 'Natural-language browser automation tasks via the Cloud agent.',
        'min_role': None,
    },
    {
        'route': '/meetings',
        'name': 'Meetings',
        'one_liner': 'List and upload meeting recordings for transcription and summary.',
        'min_role': None,
    },
    {
        'route': '/meetings/<id>',
        'name': 'Meeting Details',
        'one_liner': "View a meeting's transcript, summary, and generated artifacts.",
        'min_role': None,
    },
    {
        'route': '/meeting-series',
        'name': 'Meeting Series',
        'one_liner': 'Manage recurring meeting series, glossary, and speaker memory.',
        'min_role': None,
    },
    {
        'route': '/projects',
        'name': 'Projects',
        'one_liner': 'Group chats, configs, workflows, and knowledge under a project.',
        'min_role': None,
    },
    {
        'route': '/projects/<pid>/settings',
        'name': 'Project Settings',
        'one_liner': 'General, members, defaults, and danger zone for a project.',
        'min_role': None,
    },
    {
        'route': '/workspaces/new',
        'name': 'Create Company',
        'one_liner': 'Spin up a new company workspace (managers + admins only).',
        'min_role': 'manager',
    },
    {
        'route': '/workspaces/<wid>',
        'name': 'Company Overview',
        'one_liner': 'Company-level activity, members, and projects.',
        'min_role': None,
    },
    {
        'route': '/workspaces/<wid>/settings',
        'name': 'Company Settings',
        'one_liner': 'Manage members, billing, activity, content safety, and danger zone.',
        'min_role': 'owner',
    },
    {
        'route': '/settings',
        'name': 'Settings',
        'one_liner': 'AI preferences, language, theme, timezone.',
        'min_role': None,
    },
    {
        'route': '/admin',
        'name': 'Admin Dashboard',
        'one_liner': 'Platform-wide stats and admin entry point.',
        'min_role': 'admin',
    },
    {
        'route': '/admin/users',
        'name': 'User Management',
        'one_liner': 'Promote, ban, or inspect any user across the holding.',
        'min_role': 'admin',
    },
    {
        'route': '/admin/users/<userId>/history',
        'name': 'User History (Admin)',
        'one_liner': 'Inspect any user’s conversation, image, and usage history.',
        'min_role': 'admin',
    },
    {
        'route': '/admin/templates',
        'name': 'Templates',
        'one_liner': 'Manage shared LLM config + workflow templates.',
        'min_role': 'admin',
    },
    {
        'route': '/admin/audit',
        'name': 'Audit Log',
        'one_liner': 'Cross-tenant audit trail for sensitive actions.',
        'min_role': 'admin',
    },
    {
        'route': '/admin/companies',
        'name': 'Companies (Admin)',
        'one_liner': 'Super-admin holding view across every company.',
        'min_role': 'admin',
    },
    {
        'route': '/admin/companies/<wid>',
        'name': 'Company Detail (Admin)',
        'one_liner': 'Drill-down per company: top users, top models, per-project usage.',
        'min_role': 'admin',
    },
    {
        'route': '/admin/dlp',
        'name': 'DLP Dashboard',
        'one_liner': 'Cross-company Content Safety event log and policy drift view.',
        'min_role': 'admin',
    },
    {
        'route': '/platform/holding',
        'name': 'Platform Holding Overview',
        'one_liner': 'Platform-admin overview of the entire holding.',
        'min_role': 'platform_admin',
    },
    {
        'route': '/platform/companies',
        'name': 'Platform Companies',
        'one_liner': 'Platform-admin company list across the holding.',
        'min_role': 'platform_admin',
    },
    {
        'route': '/platform/companies/<wid>',
        'name': 'Platform Company Detail',
        'one_liner': 'Platform-admin drill-down for a single company.',
        'min_role': 'platform_admin',
    },
    {
        'route': '/platform/users-overview',
        'name': 'Platform Users Overview',
        'one_liner': 'Platform-admin overview of every user in the holding.',
        'min_role': 'platform_admin',
    },
    {
        'route': '/platform/features',
        'name': 'Platform Feature Flags',
        'one_liner': 'Toggle platform-wide feature flags.',
        'min_role': 'platform_admin',
    },
    {
        'route': '/platform/audit',
        'name': 'Platform Audit Log',
        'one_liner': 'Platform-admin audit trail across the holding.',
        'min_role': 'platform_admin',
    },
    {
        'route': '/platform/account',
        'name': 'Platform Account',
        'one_liner': 'Platform-admin account settings.',
        'min_role': 'platform_admin',
    },
]


# Official Persian product names (FA glossary). Helper prompt uses these so
# users hear the same names as the hub/nav — never English "Email Writer".
NAME_FA: dict[str, str] = {
    '/agent': 'ایجنت',
    '/chat': 'چت',
    '/dashboard': 'داشبورد',
    '/chat-history': 'تاریخچه چت',
    '/image-history': 'تاریخچه تصاویر',
    '/configs': 'شخصیت‌ها',
    '/workflow': 'گردش کار',
    '/arena': 'مقایسهٔ مدل‌ها',
    '/debate': 'مناظره',
    '/knowledge': 'پایگاه دانش',
    '/image-studio': 'دستیار تولید عکس',
    '/ocr': 'متن‌خوان تصویر (OCR)',
    '/email-writer': 'نویسنده ایمیل / نامه',
    '/cv-checker': 'بررسی رزومه',
    '/research': 'پژوهش عمیق',
    '/contracts': 'بررسی قرارداد',
    '/tenders': 'دستیار مناقصه',
    '/shop': 'دستیار خرید',
    '/automate-agent': 'اتوماسیون',
    '/meetings': 'دستیار جلسات',
    '/meetings/<id>': 'جزئیات جلسه',
    '/meeting-series': 'سلسله جلسات',
    '/data-analyzer': 'دستیار تحلیل داده',
    '/presentations': 'ارائه‌ها',
    '/payroll': 'دستیار حقوق و دستمزد',
    '/helper': 'راهنما',
    '/projects': 'تیم‌ها',
    '/projects/<pid>/settings': 'تنظیمات تیم',
    '/workspaces/new': 'ایجاد شرکت',
    '/workspaces/<wid>': 'نمای کلی شرکت',
    '/workspaces/<wid>/settings': 'تنظیمات شرکت',
    '/settings': 'تنظیمات',
    '/admin': 'مدیریت',
    '/admin/users': 'کاربران',
    '/admin/users/<userId>/history': 'تاریخچه کاربر',
    '/admin/templates': 'قالب‌ها',
    '/admin/audit': 'گزارش فعالیت',
    '/admin/companies': 'شرکت‌ها',
    '/admin/companies/<wid>': 'جزئیات شرکت',
    '/admin/dlp': 'ایمنی محتوا',
}


# Member-role hierarchy for workspace roles (mirrors workspace_member.ROLE_HIERARCHY).
_MEMBER_HIERARCHY = {'viewer': 1, 'editor': 2, 'owner': 3}


def _meets_min_role(
    min_role: Optional[str],
    user_role: str,
    member_role: Optional[str],
) -> bool:
    """Return True if the user can access a feature gated by `min_role`."""
    if min_role is None:
        return True
    # Global super-admin sees everything.
    if user_role == 'admin':
        return True
    if min_role == 'admin':
        return user_role == 'admin'
    if min_role == 'manager':
        return user_role in ('admin', 'manager')
    if min_role in _MEMBER_HIERARCHY:
        # Workspace-scoped role check.
        if not member_role or member_role not in _MEMBER_HIERARCHY:
            return False
        return _MEMBER_HIERARCHY[member_role] >= _MEMBER_HIERARCHY[min_role]
    return False


def build_features_section(user_role: str, member_role: Optional[str]) -> str:
    """Markdown bullet list of features visible to this user, for the system prompt."""
    user_role = user_role or 'user'
    visible = [
        f
        for f in FEATURES
        if _meets_min_role(f.get('min_role'), user_role, member_role)
    ]
    lines = [
        f"- **{NAME_FA.get(f['route'], f['name'])}** (`{f['route']}`): {f['one_liner']}"
        for f in visible
    ]
    return '\n'.join(lines)
