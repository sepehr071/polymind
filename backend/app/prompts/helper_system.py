"""
System-prompt builder for the in-app Helper guide.

The Helper is a read-only narrator: it answers "how do I..." / "where is..."
questions about Polymind AI, returning markdown with relative-path deep links
the frontend can render as clickable router pushes. It must never claim to
have *done* anything on the user's behalf — it has no tool surface.
"""
from __future__ import annotations

from typing import Optional

from app.prompts.helper_features import build_features_section


def _safe_get(d: Optional[dict], *keys, default: str = '') -> str:
    """Walk a nested dict; return default if any hop is missing."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur if isinstance(cur, (str, int, float)) else default


def build_helper_system_prompt(
    user: dict,
    workspace: Optional[dict],
    project: Optional[dict],
    member_role: Optional[str],
    route: str,
    params: dict,
) -> str:
    """Compose the Helper system prompt from user + workspace + project + route context.

    Args:
        user: UserModel document (the full doc, not just user_id).
        workspace: WorkspaceModel doc or None (no active workspace).
        project: ProjectModel doc or None (no active project).
        member_role: workspace member role string ('owner'|'editor'|'viewer') or None.
        route: client-side router pathname (e.g. '/chat/abc123').
        params: arbitrary JSON-serializable dict of route params / query.

    Returns:
        A single system-prompt string ready to hand to the LLM.
    """
    user_role = (user or {}).get('role') or 'user'

    # --- Identity ----------------------------------------------------------
    identity = (
        "You are the Polymind AI in-app guide. You are read-only: you can describe "
        "features, explain how to reach them, and produce clickable deep-links, "
        "but you never take actions on behalf of the user and never claim to "
        "have done anything. Be concise, friendly, and direct."
    )

    # --- User profile ------------------------------------------------------
    profile_lines: list[str] = []
    ai_prefs = (user or {}).get('ai_preferences') or {}
    if ai_prefs.get('enabled', False):
        name = _safe_get(ai_prefs, 'user_info', 'name')
        language = _safe_get(ai_prefs, 'user_info', 'language')
        expertise = _safe_get(ai_prefs, 'user_info', 'expertise_level')
        tone = _safe_get(ai_prefs, 'behavior', 'tone')
        response_style = _safe_get(ai_prefs, 'behavior', 'response_style')
        custom = ai_prefs.get('custom_instructions') or ''

        if name:
            profile_lines.append(f"- Name: {name}")
        if language:
            profile_lines.append(f"- Preferred language: {language}")
        if expertise:
            profile_lines.append(f"- Expertise level: {expertise}")
        if tone:
            profile_lines.append(f"- Preferred tone: {tone}")
        if response_style:
            profile_lines.append(f"- Response style: {response_style}")
        if custom:
            profile_lines.append(f"- Custom instructions: {custom}")

    profile_section = ''
    if profile_lines:
        profile_section = "## User profile\n" + "\n".join(profile_lines)

    # --- Active context ----------------------------------------------------
    ws_name = (workspace or {}).get('name') if workspace else None
    proj_name = (project or {}).get('name') if project else None
    context_lines = [
        f"- Company: {ws_name or 'Personal'}",
        f"- Project: {proj_name or 'No project active'}",
        f"- Global role: {user_role}",
        f"- Company role: {member_role or 'none'}",
    ]
    context_section = "## Active context\n" + "\n".join(context_lines)

    # --- Current page ------------------------------------------------------
    page_lines = [f"- Route: {route}"]
    if params:
        page_lines.append(f"- Params: {params}")
    page_section = "## Current page\n" + "\n".join(page_lines)

    # --- Available features ------------------------------------------------
    features_md = build_features_section(user_role=user_role, member_role=member_role)
    features_section = (
        "## Available features\n"
        "Names below are the official Persian product names. When the user "
        "speaks Persian, use these names exactly — do not translate them to "
        "English (e.g. نویسنده ایمیل / نامه, not Email Writer).\n"
        + features_md
    )

    # --- Deep-link contract ------------------------------------------------
    deep_link_section = (
        "## Deep-link contract\n"
        "When suggesting where the user should go, ALWAYS use markdown links "
        "with relative paths inside Polymind AI. Never use `http://` or `https://` "
        "URLs for internal navigation.\n"
        "If a feature is gated by role and the user cannot access it, do not "
        "produce a deep-link to it; suggest the closest available alternative."
    )

    # --- Output rules ------------------------------------------------------
    output_rules = (
        "## Output rules\n"
        "- Keep replies concise: prefer ≤200 tokens unless the user asks a deep "
        "technical question. Bullet lists beat paragraphs.\n"
        "- Use markdown formatting. Persian/Arabic text must read naturally in RTL.\n"
        "- Never claim to have executed anything. If the user asks you to do "
        "something, describe the steps and link them to the page that does it.\n"
        "- If the user's question is off-topic for Polymind AI (general knowledge, "
        "world events, etc.), gently redirect to /chat where they can ask any "
        "model directly."
    )

    sections = [identity]
    if profile_section:
        sections.append(profile_section)
    sections.append(context_section)
    sections.append(page_section)
    sections.append(features_section)
    sections.append(deep_link_section)
    sections.append(output_rules)

    return "\n\n".join(sections)
