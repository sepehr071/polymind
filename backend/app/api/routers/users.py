"""User profile / settings / stats / costs + AI-preferences routes.

Translated from app/routes/users.py (users_bp) and app/routes/ai_preferences.py
(ai_preferences_bp). BOTH Flask blueprints registered under the SAME url_prefix
``/api/users`` — so they collapse into ONE FastAPI router here.

Every Flask handler maps 1:1 to a FastAPI path operation:
- ``@jwt_required()`` + ``@active_user_required`` -> ``Depends(require_active)``
  (which itself depends on ``current_user`` so auth resolves once per request and
  the missing-token-401 > banned-403 precedence is preserved).
- ``get_current_user()`` -> the ``user`` dict yielded by ``require_active``.
- ``request.get_json(silent=True) or {}`` -> ``await request.json()`` guarded.
- ``request.args.get(...)`` -> typed query params.
- Response shapes (incl. the legacy ``_id`` alias from the model facades) are
  preserved byte-for-byte; NO ``response_model`` (would strip fields).

The router-level ``Depends(flask_ctx)`` runs every request inside one Flask
app_context so the existing model facades are reused verbatim.
"""
from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.deps import flask_ctx, require_active
from app.models.conversation import ConversationModel
from app.models.llm_config import LLMConfigModel
from app.models.usage_log import UsageLogModel
from app.models.user import UserModel
from app.utils.permissions import check_workspace_access
from app.utils.validators import validate_display_name

logger = logging.getLogger(__name__)

# Router-level dependency: every request runs inside the Flask app_context.
router = APIRouter(dependencies=[Depends(flask_ctx)])


# Valid options for validation (mirror ai_preferences.py).
VALID_EXPERTISE_LEVELS = ["beginner", "intermediate", "expert"]
VALID_TONES = ["professional", "friendly", "casual"]
VALID_RESPONSE_STYLES = ["concise", "detailed", "balanced"]

# Whitelist top-level keys accepted on the AI-preferences PUT. Anything else is
# silently dropped to prevent clients stashing arbitrary nested data.
ALLOWED_TOP_LEVEL_KEYS = {
    "enabled",
    "user_info",
    "behavior",
    "custom_instructions",
    "timezone",
}
ALLOWED_USER_INFO_KEYS = {"name", "language", "expertise_level"}
ALLOWED_BEHAVIOR_KEYS = {"tone", "response_style"}


async def _json_body(request: Request) -> dict:
    """Read the JSON body, tolerating empty/garbage like get_json(silent=True)."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _iso(value):
    """Render a datetime-or-already-ISO-string value as an ISO string.

    The legacy dict (``_user_to_legacy_dict`` -> ``to_dict()``) emits datetime
    columns as ISO strings already, while some nested ``usage`` fields are
    stored as ISO strings too; the old Flask route called ``.isoformat()``
    unconditionally. We tolerate both so the response stays an ISO string.
    """
    return value.isoformat() if hasattr(value, "isoformat") else value


# ---------------------------------------------------------------------------
# users_bp -> /api/users
# ---------------------------------------------------------------------------
@router.get("/profile")
def get_profile(user: dict = Depends(require_active)):
    """Get user profile."""
    return {
        "profile": {
            "id": str(user["_id"]),
            "email": user["email"],
            "display_name": user["profile"]["display_name"],
            "avatar_url": user["profile"].get("avatar_url"),
            "bio": user["profile"].get("bio", ""),
            "created_at": _iso(user["created_at"]),
        }
    }


@router.put("/profile")
async def update_profile(request: Request, user: dict = Depends(require_active)):
    """Update user profile."""
    data = await _json_body(request)

    update_fields = {}

    if "display_name" in data and not user.get("keycloak_sub"):
        is_valid, error = validate_display_name(data["display_name"])
        if not is_valid:
            return JSONResponse({"error": error}, status_code=400)
        update_fields["profile.display_name"] = data["display_name"].strip()

    if "avatar_url" in data:
        update_fields["profile.avatar_url"] = data["avatar_url"]

    if "bio" in data:
        bio = data["bio"][:500] if data["bio"] else ""  # Limit bio length
        update_fields["profile.bio"] = bio

    if update_fields:
        UserModel.update(user["_id"], update_fields)

    updated_user = UserModel.find_by_id(user["_id"])
    return {
        "profile": {
            "id": str(updated_user["_id"]),
            "display_name": updated_user["profile"]["display_name"],
            "avatar_url": updated_user["profile"].get("avatar_url"),
            "bio": updated_user["profile"].get("bio", ""),
        }
    }


@router.get("/stats")
def get_stats(user: dict = Depends(require_active)):
    """Get user usage statistics."""
    user_id = str(user["_id"])

    total_conversations, archived_conversations = (
        ConversationModel.count_active_and_archived_by_user(user_id)
    )
    total_configs = LLMConfigModel.count_by_owner(user_id)

    return {
        "stats": {
            "messages_sent": user["usage"]["messages_sent"],
            "tokens_used": user["usage"]["tokens_used"],
            "tokens_limit": user["usage"]["tokens_limit"],
            "tokens_remaining": (
                user["usage"]["tokens_limit"] - user["usage"]["tokens_used"]
                if user["usage"]["tokens_limit"] != -1
                else -1
            ),
            "total_conversations": total_conversations,
            "archived_conversations": archived_conversations,
            "total_configs": total_configs,
            "last_active": _iso(user["usage"]["last_active"]),
        }
    }


@router.get("/costs")
def get_user_costs(
    user: dict = Depends(require_active),
    days: int = Query(30),
):
    """Get user cost breakdown."""
    user_id = str(user["_id"])

    costs = UsageLogModel.get_user_costs(user_id, days)
    total = UsageLogModel.get_user_total_cost(user_id)
    daily = UsageLogModel.get_daily_costs(user_id, days)

    return {
        "costs": {
            "period": costs,
            "total": total,
            "daily": [
                {"date": d["_id"], "cost": d["cost"], "tokens": d["tokens"]}
                for d in daily
            ],
        }
    }


@router.get("/settings")
def get_settings(user: dict = Depends(require_active)):
    """Get user settings."""
    return {
        "settings": {
            "default_config_id": (
                str(user["settings"]["default_config_id"])
                if user["settings"].get("default_config_id")
                else None
            ),
            "theme": user["settings"].get("theme", "dark"),
            "notifications_enabled": user["settings"].get("notifications_enabled", True),
        }
    }


@router.put("/settings")
async def update_settings(request: Request, user: dict = Depends(require_active)):
    """Update user settings."""
    data = await _json_body(request)

    update_fields = {}

    if "default_config_id" in data:
        config_id = data["default_config_id"]
        if config_id:
            # Verify config exists and user has access.
            config = LLMConfigModel.find_by_id(config_id)
            if not config:
                return JSONResponse({"error": "Config not found"}, status_code=404)
            update_fields["settings.default_config_id"] = config_id
        else:
            update_fields["settings.default_config_id"] = None

    if "theme" in data:
        if data["theme"] in ["dark", "light"]:
            update_fields["settings.theme"] = data["theme"]

    if "notifications_enabled" in data:
        update_fields["settings.notifications_enabled"] = bool(
            data["notifications_enabled"]
        )

    if update_fields:
        UserModel.update(user["_id"], update_fields)

    updated_user = UserModel.find_by_id(user["_id"])
    return {
        "settings": {
            "default_config_id": (
                str(updated_user["settings"]["default_config_id"])
                if updated_user["settings"].get("default_config_id")
                else None
            ),
            "theme": updated_user["settings"].get("theme", "dark"),
            "notifications_enabled": updated_user["settings"].get(
                "notifications_enabled", True
            ),
        }
    }


@router.post("/onboarding-seen")
def mark_onboarding_seen(user: dict = Depends(require_active)):
    """Stamp settings.onboarding_seen_at (idempotent — first show wins).

    OnboardingGate stops force-redirecting to /onboarding once this is set,
    so the wizard auto-appears exactly once per account.
    """
    seen_at = (user.get("settings") or {}).get("onboarding_seen_at")
    if not seen_at:
        seen_at = datetime.utcnow().isoformat()
        UserModel.update(user["_id"], {"settings.onboarding_seen_at": seen_at})
    return {"onboarding_seen_at": seen_at}


@router.put("/active-workspace")
async def set_active_workspace(request: Request, user: dict = Depends(require_active)):
    """Persist the user's active workspace (the UI's current company/team).

    The frontend switcher used to write ONLY localStorage + React state, so the
    DB ``users.active_workspace_id`` went stale. Several gated paths resolve the
    governing workspace from that column — DLP scan + spend gate for chat
    (``chat.py``), helper (``misc_b.py``), arena, debate and automate. A stale
    value meant a turn was scanned under the *previously*-active workspace's DLP
    policy, so a chat in a DLP-*off* workspace surfaced the violation modal even
    though the visible workspace had DLP off ("it's off but I see the modal").
    Persisting the switch keeps the server-side policy source in lockstep with
    the UI.

    Membership is verified server-side on purpose: the column doubles as an
    anti-bypass DLP/budget source, so a client must not be able to point it at a
    weaker-policy workspace it isn't a member of.
    """
    data = await _json_body(request)
    workspace_id = data.get("workspace_id")
    if not workspace_id:
        return JSONResponse({"error": "workspace_id is required"}, status_code=400)
    try:
        allowed = check_workspace_access(user["_id"], workspace_id)
    except Exception:  # noqa: BLE001 — malformed id / lookup failure -> deny
        allowed = False
    if not allowed:
        return JSONResponse(
            {"error": "Workspace not found or access denied"}, status_code=403
        )
    UserModel.set_active_workspace(user["_id"], workspace_id)
    return {"active_workspace_id": str(workspace_id)}


# ---------------------------------------------------------------------------
# ai_preferences_bp -> /api/users  (same prefix, merged into this router)
# ---------------------------------------------------------------------------
@router.get("/ai-preferences")
def get_ai_preferences(user: dict = Depends(require_active)):
    """Get current user's AI preferences."""
    user_id = str(user["_id"])

    preferences = UserModel.get_ai_preferences(user_id)
    timezone = UserModel.get_timezone(user_id)

    return {
        "preferences": preferences,
        "timezone": timezone,
    }


@router.put("/ai-preferences")
async def update_ai_preferences(request: Request, user: dict = Depends(require_active)):
    """Update current user's AI preferences (PARTIAL — whitelisted keys only)."""
    user_id = str(user["_id"])
    data = await _json_body(request)

    if not data:
        return JSONResponse({"error": "Request body is required"}, status_code=400)

    # Whitelist: drop unknown top-level keys; reject if client passed only junk.
    unknown_keys = [k for k in data.keys() if k not in ALLOWED_TOP_LEVEL_KEYS]
    data = {k: v for k, v in data.items() if k in ALLOWED_TOP_LEVEL_KEYS}
    if not data:
        return JSONResponse(
            {
                "error": "No recognized preference fields provided",
                "allowed": sorted(ALLOWED_TOP_LEVEL_KEYS),
                "rejected": unknown_keys,
            },
            status_code=400,
        )

    # Whitelist nested keys on user_info / behavior so clients can't sneak
    # arbitrary fields through (e.g. user_info.is_admin).
    if isinstance(data.get("user_info"), dict):
        data["user_info"] = {
            k: v for k, v in data["user_info"].items() if k in ALLOWED_USER_INFO_KEYS
        }
    if isinstance(data.get("behavior"), dict):
        data["behavior"] = {
            k: v for k, v in data["behavior"].items() if k in ALLOWED_BEHAVIOR_KEYS
        }

    # Validate fields if provided.
    errors = []

    if "enabled" in data and not isinstance(data["enabled"], bool):
        errors.append("enabled must be a boolean")

    if "user_info" in data:
        user_info = data["user_info"]
        if not isinstance(user_info, dict):
            errors.append("user_info must be an object")
        else:
            if "name" in user_info and not isinstance(user_info["name"], str):
                errors.append("user_info.name must be a string")
            if "language" in user_info and not isinstance(user_info["language"], str):
                errors.append("user_info.language must be a string")
            if "expertise_level" in user_info:
                if user_info["expertise_level"] not in VALID_EXPERTISE_LEVELS:
                    errors.append(
                        f'user_info.expertise_level must be one of: {", ".join(VALID_EXPERTISE_LEVELS)}'
                    )

    if "behavior" in data:
        behavior = data["behavior"]
        if not isinstance(behavior, dict):
            errors.append("behavior must be an object")
        else:
            if "tone" in behavior and behavior["tone"] not in VALID_TONES:
                errors.append(f'behavior.tone must be one of: {", ".join(VALID_TONES)}')
            if (
                "response_style" in behavior
                and behavior["response_style"] not in VALID_RESPONSE_STYLES
            ):
                errors.append(
                    f'behavior.response_style must be one of: {", ".join(VALID_RESPONSE_STYLES)}'
                )

    if "custom_instructions" in data:
        if not isinstance(data["custom_instructions"], str):
            errors.append("custom_instructions must be a string")
        elif len(data["custom_instructions"]) > 2000:
            errors.append("custom_instructions must not exceed 2000 characters")

    if "timezone" in data:
        tz_str = data.get("timezone")
        if not isinstance(tz_str, str) or not tz_str.strip():
            errors.append("timezone must be a non-empty string")
        else:
            try:
                zoneinfo.ZoneInfo(tz_str)
            except Exception:  # noqa: BLE001
                errors.append(f"timezone is not a valid IANA timezone: {tz_str}")

    if errors:
        return JSONResponse(
            {"error": "Validation failed", "details": errors}, status_code=400
        )

    # Update preferences + timezone. Timezone is a separate write; if it fails
    # we surface a 500 rather than silently leaving stale tz under fresh prefs.
    UserModel.update_ai_preferences(user_id, data)
    if "timezone" in data:
        try:
            UserModel.update_timezone(user_id, data["timezone"].strip())
        except Exception as exc:  # noqa: BLE001
            logger.exception("ai_preferences: timezone update failed")
            return JSONResponse(
                {
                    "error": "Preferences saved but timezone update failed",
                    "detail": str(exc),
                },
                status_code=500,
            )

    updated_preferences = UserModel.get_ai_preferences(user_id)
    timezone = UserModel.get_timezone(user_id)

    return {
        "message": "AI preferences updated successfully",
        "preferences": updated_preferences,
        "timezone": timezone,
    }
