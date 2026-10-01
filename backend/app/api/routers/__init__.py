"""Router registry for the FastAPI bridge.

``ALL_ROUTERS`` is the single list ``asgi.py`` iterates over to mount routers.
Each entry is ``(router, prefix)``. Prefixes mirror the Flask blueprint
url_prefixes in ``app/__init__.py``.

Ordering: auth + keycloak first (more specific keycloak prefix before the
shared ``/api/auth``). Feature routers next under their dedicated prefixes.
The two broad ``/api`` mounts (dlp, usage ``api_router``) come LAST so the more
specific feature prefixes are matched first by registration order.
"""
from __future__ import annotations

from app.api.routers.auth import keycloak_router, router as auth_router
from app.api.routers.chat import router as chat_router
from app.api.routers.arena import router as arena_router
from app.api.routers.debate import router as debate_router
from app.api.routers.automate_agent import router as automate_agent_router
from app.api.routers.users import router as users_router
from app.api.routers.models import router as models_router
from app.api.routers.workspaces import router as workspaces_router
from app.api.routers.projects import router as projects_router
from app.api.routers.admin import router as admin_router
from app.api.routers.admin_holding import router as admin_holding_router
from app.api.routers.conversations import router as conversations_router
from app.api.routers.share import router as share_router
from app.api.routers.meetings import router as meetings_router, series_router as meeting_series_router
from app.api.routers.dlp import router as dlp_router
from app.api.routers.workflow import router as workflow_router, workflow_ai_router
from app.api.routers.knowledge import (
    knowledge_router,
    knowledge_folders_router,
    folders_router,
)
from app.api.routers.configs import router as configs_router, prompt_templates_router
from app.api.routers.uploads import router as uploads_router
from app.api.routers.image_gen import image_router
from app.api.routers.helper import helper_router
from app.api.routers.usage import api_router
from app.api.routers.health import health_router
from app.api.routers.payroll import router as payroll_router
from app.api.routers.presentations import router as presentations_router
from app.api.routers.agent import router as agent_router
from app.api.routers.ocr import router as ocr_router
from app.api.routers.email_writer import router as email_writer_router
from app.api.routers.cv_checker import router as cv_checker_router
from app.api.routers.research import router as research_router
from app.api.routers.contracts import router as contracts_router
from app.api.routers.tenders import router as tenders_router
from app.api.routers.shop import router as shop_router

# (router, url_prefix) — mirrors app/__init__.py register_blueprint prefixes.
# NOTE: order matters for overlapping prefixes — keycloak before /api/auth,
# and the broad /api mounts (dlp, usage api_router) sit last.
ALL_ROUTERS = [
    (auth_router, "/api/auth"),
    (keycloak_router, "/api/auth/keycloak"),
    (chat_router, "/api/chat"),
    (arena_router, "/api/arena"),
    (debate_router, "/api/debate"),
    (automate_agent_router, "/api/automate-agent"),
    (users_router, "/api/users"),
    (models_router, "/api/models"),
    (workspaces_router, "/api/workspaces"),
    (projects_router, "/api/projects"),
    (admin_router, "/api/admin"),
    (admin_holding_router, "/api/admin"),
    (conversations_router, "/api/conversations"),
    (share_router, "/api/share"),
    (meetings_router, "/api/meetings"),
    (meeting_series_router, "/api/meeting-series"),
    (workflow_router, "/api/workflow"),
    (workflow_ai_router, "/api/workflow-ai"),
    (knowledge_router, "/api/knowledge"),
    (knowledge_folders_router, "/api/knowledge-folders"),
    (folders_router, "/api/folders"),
    (configs_router, "/api/configs"),
    (prompt_templates_router, "/api/prompt-templates"),
    (uploads_router, "/api/uploads"),
    (image_router, "/api/image-gen"),
    (payroll_router, "/api/payroll"),
    (presentations_router, "/api/presentations"),
    (agent_router, "/api/agent"),
    (ocr_router, "/api/ocr"),
    (email_writer_router, "/api/email-writer"),
    (cv_checker_router, "/api/cv-checker"),
    (research_router, "/api/research"),
    (contracts_router, "/api/contracts"),
    (tenders_router, "/api/tenders"),
    (shop_router, "/api/shop"),
    (helper_router, "/api/helper"),
    (health_router, "/api/v1"),
    # Broad /api mounts last so specific feature prefixes match first.
    (dlp_router, "/api"),
    (api_router, "/api"),
]

__all__ = ["ALL_ROUTERS"]
