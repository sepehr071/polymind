"""Conversations + branch-management routes, translated from
app/routes/conversations.py (Flask blueprint ``conversations_bp``, mounted at
``/api/conversations``).

Every Flask handler maps 1:1 to a FastAPI path operation under ``router``. The
router-level ``Depends(flask_ctx)`` binds a Flask app_context to each request so
the existing model facades (ConversationModel / MessageModel / permissions) run
VERBATIM. Bodies are read with ``_json_body`` (tolerant of empty/garbage, like
the legacy ``request.get_json(silent=True) or {}``).

There is NO SSE here: the two streaming ``Response`` objects in the Flask source
are file *downloads* (the JSON / Markdown export endpoints) — translated to
Starlette ``Response`` with a ``Content-Disposition`` attachment header, NOT to
``sse_stream``.

Response shapes are preserved byte-for-byte, including the legacy ``_id`` alias
emitted by ``serialize_doc`` (the frontend was built against the old Mongo JSON).
``@active_user_required`` -> ``Depends(require_active)``; ownership + project ACL
are enforced in-handler exactly as the Flask ``_fetch_owned_conversation`` did.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.api.deps import flask_ctx, require_active
from app.models.conversation import ConversationModel, NULL_PROJECT_SENTINEL
from app.models.conversation_share import ConversationShareModel
from app.models.message import MessageModel, sender_public
from app.models.project import ProjectModel
from app.services.chat_export import (
    EMPTY_ERROR,
    ascii_filename,
    build_export,
    content_disposition,
    display_filename,
    has_dialogue,
    render_json,
    render_markdown,
)
from app.services.chat_export_pdf import render_chat_pdf
from app.utils.helpers import serialize_doc, validate_object_id
from app.utils.permissions import (
    WORKSPACE_ACCESS_DENIED,
    check_project_access,
    is_workspace_member_or_admin,
    resolve_conversation_access,
)

# Router-level dependency: every request runs inside the Flask app_context.
router = APIRouter(dependencies=[Depends(flask_ctx)])


async def _json_body(request: Request) -> dict:
    """Read the request JSON body, tolerating empty/garbage (get_json(silent=True))."""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Access helpers — translated 1:1 from the Flask module-level helpers. Identity
# is the resolved legacy user dict (``user['_id']``), never a JWT claim.
# ---------------------------------------------------------------------------
def _accessible_project_ids(user_id):
    """IDs of every project the caller can currently view (mirror of Flask).

    Explicit + workspace-implied membership union runs as a SINGLE query
    (``ProjectModel.accessible_ids_for_user``) — same id set as the previous
    3-query fan-out.
    """
    return ProjectModel.accessible_ids_for_user(user_id)


def _conv_is_accessible(conv: dict, accessible: set) -> bool:
    """Predicate for post-filtering ConversationModel.find_by_user results."""
    pid = conv.get('project_id')
    if pid is None:
        return True
    accessible_strs = {str(a) for a in accessible}
    return str(pid) in accessible_strs


def _resolve_project_filter(raw):
    """Mirror of folders._resolve_project_filter.

    Returns ``(filter_value, error_response_or_None)``. The error is a
    JSONResponse here (vs. Flask's ``(jsonify, code)`` tuple).
    """
    if raw is None or raw == '':
        return None, None
    if raw == 'null':
        return NULL_PROJECT_SENTINEL, None
    if not validate_object_id(raw):
        return None, JSONResponse({'error': 'Invalid project_id'}, status_code=400)
    return raw, None


def _resolve_list_workspace(user: dict, raw):
    """Org scope for chat lists: ``?workspace_id`` else the active workspace.

    Returns ``(workspace_id_or_None, error_response_or_None)``. ``None`` with no
    error means nothing resolves — the caller answers with an empty list.
    Non-admins must be an ACTIVE member of the org (403
    ``workspace_access_denied``); the super-admin may read any org.
    """
    if raw is not None and raw != '':
        if not validate_object_id(raw):
            return None, JSONResponse(
                {'error': 'Invalid workspace_id', 'status': 400}, status_code=400
            )
        wid = str(raw)
    else:
        active = user.get('active_workspace_id')
        wid = str(active) if active else None
    if wid is None:
        return None, None
    if not is_workspace_member_or_admin(user, wid):
        return None, JSONResponse(dict(WORKSPACE_ACCESS_DENIED), status_code=403)
    return wid, None


def _fetch_owned_conversation(conversation_id: str, user_id: str,
                              min_role: str = 'viewer'):
    """Look up a conversation, enforce ownership + project ACL.

    Returns ``(conversation_doc, error_response_or_None)``. The error is a
    JSONResponse (vs. Flask's ``(jsonify, code)`` tuple).
    """
    conversation = ConversationModel.find_by_id(conversation_id)
    if not conversation or str(conversation['user_id']) != user_id:
        return None, JSONResponse({'error': 'Conversation not found'}, status_code=404)
    pid = conversation.get('project_id')
    if pid and not check_project_access(user_id, str(pid), min_role):
        return None, JSONResponse(
            {'error': 'Project access denied', 'status': 403}, status_code=403
        )
    return conversation, None


def _fetch_accessible_conversation(conversation_id: str, user_id: str,
                                   min_role: str = 'viewer'):
    """Look up a conversation, allowing the owner OR a member of any team it is
    shared into (read + contribute). Returns ``(conversation, error_response)``.

    Use for read/contribute paths; keep ``_fetch_owned_conversation`` for
    owner-only management (share, rename, move, delete, archive, branches).
    """
    conversation = ConversationModel.find_by_id(conversation_id)
    _role, err = resolve_conversation_access(conversation, user_id, min_role)
    if err:
        msg, status = err
        payload: dict = {'error': msg}
        if status == 403:
            payload['status'] = 403
        return None, JSONResponse(payload, status_code=status)
    return conversation, None


# ---------------------------------------------------------------------------
# /api/conversations  (conversations_bp)
# ---------------------------------------------------------------------------
@router.get("")
def get_conversations(request: Request, user: dict = Depends(require_active)):
    """Get user's conversations."""
    user_id = str(user['_id'])

    args = request.query_params
    folder_id = args.get('folder_id')
    archived = (args.get('archived', 'false') or 'false').lower() == 'true'
    search = args.get('search')
    page = int(args.get('page', 1) or 1)
    limit = int(args.get('limit', 20) or 20)
    sort_by = args.get('sort', 'last_message_at') or 'last_message_at'
    # None -> no filter (returns chat + data); 'chat'/'data' -> only that kind.
    kind = args.get('kind')

    raw_project = args.get('project_id')
    project_filter, err = _resolve_project_filter(raw_project)
    if err:
        return err
    if project_filter and project_filter != NULL_PROJECT_SENTINEL:
        if not check_project_access(user_id, project_filter, 'viewer'):
            return JSONResponse(
                {'error': 'Project access denied', 'status': 403}, status_code=403
            )

    skip = (page - 1) * limit

    workspace_id, err = _resolve_list_workspace(user, args.get('workspace_id'))
    if err:
        return err
    if workspace_id is None:
        return {
            'conversations': [],
            'total': 0,
            'page': page,
            'limit': limit,
            'has_more': False,
        }

    is_team_scope = bool(project_filter) and project_filter != NULL_PROJECT_SENTINEL
    if is_team_scope:
        # A team lives in exactly one org; the project ACL already scopes rows
        # (own chats there + chats shared into it), so only check the org match.
        project = ProjectModel.find_by_id(project_filter) or {}
        if str(project.get('workspace_id') or '') != str(workspace_id):
            return {
                'conversations': [],
                'total': 0,
                'page': page,
                'limit': limit,
                'has_more': False,
            }
        # Team scope: surface chats colleagues shared into this team alongside
        # the caller's own (the access check above proved they can view it).
        conversations = ConversationModel.find_for_user_in_scope(
            user_id=user_id,
            project_id=project_filter,
            archived=archived,
            search=search,
            skip=skip,
            limit=limit,
            sort_by=sort_by,
            kind=kind,
        )
        total = ConversationModel.count_for_user_in_scope(
            user_id, project_filter, archived=archived, kind=kind
        )
    else:
        # Personal / null / unscoped: owner-only — shares never leak here.
        conversations = ConversationModel.find_by_user(
            user_id=user_id,
            folder_id=folder_id,
            archived=archived,
            search=search,
            skip=skip,
            limit=limit,
            sort_by=sort_by,
            project_id=project_filter,
            kind=kind,
            workspace_id=workspace_id,
        )
        accessible = _accessible_project_ids(user_id)
        conversations = [c for c in conversations if _conv_is_accessible(c, accessible)]
        total = ConversationModel.count_by_user(
            user_id, archived=archived, project_id=project_filter, kind=kind,
            workspace_id=workspace_id,
        )

    # Compact share state per row (one batch query for the page).
    summaries = ConversationShareModel.summary_for_many(
        [c.get('_id') for c in conversations]
    )
    for c in conversations:
        c['share'] = summaries.get(
            str(c.get('_id')),
            {'is_shared': False, 'via_link': False, 'teams': []},
        )

    return {
        'conversations': serialize_doc(conversations),
        'total': total,
        'page': page,
        'limit': limit,
        'has_more': skip + len(conversations) < total,
    }


@router.post("")
async def create_conversation(request: Request, user: dict = Depends(require_active)):
    """Create a new conversation."""
    data = await _json_body(request)

    config_id = data.get('config_id')
    title = data.get('title', 'New conversation')
    folder_id = data.get('folder_id')
    project_id = data.get('project_id')
    # Optional discriminator; only 'chat' (default) | 'data' are valid.
    kind = data.get('kind') if data.get('kind') in ('chat', 'data', 'agent') else 'chat'

    if not config_id:
        return JSONResponse({'error': 'config_id is required'}, status_code=400)

    if project_id:
        if not validate_object_id(project_id):
            return JSONResponse({'error': 'Invalid project_id'}, status_code=400)
        if not check_project_access(str(user['_id']), project_id, 'editor'):
            return JSONResponse(
                {'error': 'Project access denied', 'status': 403}, status_code=403
            )

    conversation = ConversationModel.create(
        user_id=str(user['_id']),
        config_id=config_id,
        title=title,
        folder_id=folder_id,
        project_id=project_id,
        kind=kind,
        workspace_id=user.get('active_workspace_id'),
    )

    return JSONResponse({'conversation': serialize_doc(conversation)}, status_code=201)


@router.put("/{conversation_id}")
async def update_conversation(conversation_id: str, request: Request,
                              user: dict = Depends(require_active)):
    """Update conversation details."""
    user_id = str(user['_id'])

    conversation, err = _fetch_owned_conversation(conversation_id, user_id, 'editor')
    if err:
        return err

    data = await _json_body(request)

    if 'project_id' in data:
        return JSONResponse({
            'error': 'project_id cannot be changed via PUT — use POST /<id>/move',
            'code': 'cannot_reassign_project',
        }, status_code=400)

    update_fields = {}
    if 'title' in data:
        update_fields['title'] = data['title']
    if 'folder_id' in data:
        update_fields['folder_id'] = data['folder_id'] if data['folder_id'] else None
    if 'tags' in data:
        update_fields['tags'] = data['tags']
    if 'is_pinned' in data:
        update_fields['is_pinned'] = data['is_pinned']

    if update_fields:
        ConversationModel.update(conversation_id, update_fields)

    updated = ConversationModel.find_by_id(conversation_id)
    return {'conversation': serialize_doc(updated)}


@router.post("/{conversation_id}/move")
async def move_conversation(conversation_id: str, request: Request,
                            user: dict = Depends(require_active)):
    """Move a conversation to a different project (or unfile it)."""
    user_id = str(user['_id'])

    conversation, err = _fetch_owned_conversation(conversation_id, user_id, 'editor')
    if err:
        return err

    data = await _json_body(request)
    if 'project_id' not in data:
        return JSONResponse({'error': 'project_id is required'}, status_code=400)

    raw = data.get('project_id')
    new_pid = None
    if raw is not None and raw != '':
        if not validate_object_id(raw):
            return JSONResponse({'error': 'Invalid project_id'}, status_code=400)
        if not check_project_access(user_id, raw, 'editor'):
            return JSONResponse({
                'error': 'Project access denied',
                'code': 'project_access_denied',
            }, status_code=403)
        new_pid = raw

    fields = {'project_id': new_pid}
    if new_pid:
        # The chat follows its team into that team's org.
        project = ProjectModel.find_by_id(new_pid) or {}
        if project.get('workspace_id'):
            fields['workspace_id'] = project['workspace_id']
    ConversationModel.update(conversation_id, fields)
    updated = ConversationModel.find_by_id(conversation_id)
    return {'conversation': serialize_doc(updated)}


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str, user: dict = Depends(require_active)):
    """Delete a conversation and its messages."""
    user_id = str(user['_id'])

    _, err = _fetch_owned_conversation(conversation_id, user_id, 'editor')
    if err:
        return err

    # Delete with the chat: team grants (live access) AND the frozen link
    # snapshot. The snapshot is full-content and cross-tenant readable, so it
    # must NOT be left resident after the source is erased — hard-delete every
    # share row (recipients keep any copy they already saved via /share/save).
    ConversationShareModel.delete_for_conversation(conversation_id)
    MessageModel.delete_by_conversation(conversation_id)
    ConversationModel.delete(conversation_id)

    return {'message': 'Conversation deleted'}


@router.post("/{conversation_id}/archive")
def toggle_archive(conversation_id: str, user: dict = Depends(require_active)):
    """Archive or unarchive a conversation."""
    user_id = str(user['_id'])

    conversation, err = _fetch_owned_conversation(conversation_id, user_id, 'editor')
    if err:
        return err

    new_status = not conversation.get('is_archived', False)
    ConversationModel.toggle_archive(conversation_id, new_status)

    return {
        'message': 'Archived' if new_status else 'Unarchived',
        'is_archived': new_status,
    }


@router.get("/search")
def search_conversations(request: Request, user: dict = Depends(require_active)):
    """Search conversations (title ILIKE)."""
    user_id = str(user['_id'])

    query = (request.query_params.get('q', '') or '').strip()
    if not query:
        return JSONResponse({'error': 'Search query required'}, status_code=400)

    workspace_id, err = _resolve_list_workspace(
        user, request.query_params.get('workspace_id')
    )
    if err:
        return err
    if workspace_id is None:
        return {'conversations': [], 'query': query}

    conversations = ConversationModel.find_by_user(
        user_id=user_id, search=query, limit=20, workspace_id=workspace_id
    )

    accessible = _accessible_project_ids(user_id)
    conversations = [c for c in conversations if _conv_is_accessible(c, accessible)]

    return {'conversations': serialize_doc(conversations), 'query': query}


@router.get("/search/messages")
def search_messages(request: Request, user: dict = Depends(require_active)):
    """Search within message content across all user's conversations."""
    user_id = str(user['_id'])

    query = (request.query_params.get('q', '') or '').strip()
    if not query:
        return JSONResponse({'error': 'Search query required'}, status_code=400)

    limit = min(int(request.query_params.get('limit', 50) or 50), 100)

    # Search message text via a JOIN to the owning conversation, filtered in
    # SQL by ownership + project ACL (personal-scope OR an accessible project).
    # The trgm GIN index on messages.content drives the ILIKE — no 1000-id
    # enumeration / scope cap anymore, and conversations in lost-access projects
    # are excluded so their message text doesn't leak.
    accessible = _accessible_project_ids(user_id)
    results = MessageModel.search_in_user_conversations(
        user_id=user_id,
        query=query,
        accessible_project_ids=accessible,
        limit=limit,
    )

    return {
        'results': serialize_doc(results),
        'query': query,
        'total': len(results),
    }


# NOTE: registered AFTER the static ``/search`` + ``/search/messages`` routes so
# FastAPI's first-match routing doesn't let ``/{conversation_id}`` swallow them.
@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, request: Request,
                     user: dict = Depends(require_active)):
    """Get a specific conversation with messages (owner or shared-team member)."""
    user_id = str(user['_id'])

    conversation, err = _fetch_accessible_conversation(conversation_id, user_id, 'viewer')
    if err:
        return err

    branch_id = request.query_params.get(
        'branch_id', conversation.get('active_branch', 'main')
    )
    messages = MessageModel.find_by_conversation(conversation_id, branch_id=branch_id)

    conversation['share'] = ConversationShareModel.summary_for(conversation_id)
    return {
        'conversation': serialize_doc(conversation),
        'messages': serialize_doc(messages),
        'active_branch': conversation.get('active_branch', 'main'),
    }


@router.get("/{conversation_id}/export")
def export_conversation(conversation_id: str, request: Request,
                        user: dict = Depends(require_active)):
    """Download the open chat as JSON, Markdown, or PDF/A."""
    user_id = str(user['_id'])

    conversation, err = _fetch_owned_conversation(conversation_id, user_id, 'viewer')
    if err:
        return err

    args = request.query_params
    export_format = (args.get('format', 'markdown') or 'markdown').lower()
    if export_format == 'md':
        export_format = 'markdown'

    branch_id = args.get('branch_id') or conversation.get('active_branch') or 'main'

    messages = MessageModel.find_by_conversation(
        conversation_id, limit=10000, branch_id=branch_id,
    )
    if not has_dialogue(messages):
        return JSONResponse(
            {'error': EMPTY_ERROR, 'status': 400}, status_code=400,
        )
    if export_format not in ('json', 'markdown', 'pdf'):
        return JSONResponse(
            {'error': 'فرمت خروجی نامعتبر است.', 'status': 400}, status_code=400,
        )

    doc = build_export(conversation, messages, user_id)
    title = conversation.get('title') or 'چت'
    when = datetime.now(ZoneInfo('Asia/Tehran'))
    if export_format == 'json':
        body = render_json(doc).encode('utf-8')
        media = 'application/json'
        ext = 'json'
    elif export_format == 'pdf':
        body = render_chat_pdf(doc, title)
        media = 'application/pdf'
        ext = 'pdf'
    else:
        body = render_markdown(doc, title).encode('utf-8')
        media = 'text/markdown'
        ext = 'md'
    ascii_name = ascii_filename(conversation, ext, when)
    return Response(
        content=body,
        media_type=media,
        headers={
            'Content-Disposition': content_disposition(
                ascii_name, display_filename(title, ext),
            ),
        },
    )


# ---------------------------------------------------------------------------
# Export helpers — translated verbatim; return Starlette Response downloads.
# ---------------------------------------------------------------------------
def _safe_datetime_str(dt, fmt='iso'):
    """Safely convert datetime to string."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat() if fmt == 'iso' else dt.strftime(fmt)
    return str(dt) if dt else None


# ---------------------------------------------------------------------------
# Sharing — frozen link snapshot + live team grants. Management is owner-only
# (``_fetch_owned_conversation``); the public snapshot view lives in
# ``routers/share.py``. Reading/contributing to a team-shared chat is handled by
# the existing GET/chat routes via ``_fetch_accessible_conversation``.
# ---------------------------------------------------------------------------
def _snapshot_conversation(conversation, messages) -> dict:
    """Build a frozen, self-contained snapshot for a link share.

    Mirrors the JSON-export shape but adds a COARSE, PII-free per-message
    ``sender`` (role-based label only — never the real id/email-derived
    name/avatar, since any authenticated user can read the snapshot) and STRIPS
    base64 attachments (keeps a filename/type ref only) to bound the stored row
    size.
    """
    out_messages = []
    for msg in messages:
        atts = []
        for a in (msg.get('attachments') or []):
            if isinstance(a, dict):
                atts.append({
                    'filename': a.get('filename') or a.get('name'),
                    'content_type': a.get('content_type') or a.get('type'),
                })
        meta = msg.get('metadata') or {}
        out_messages.append({
            'role': msg['role'],
            'content': msg['content'],
            'created_at': _safe_datetime_str(msg.get('created_at')),
            'sender': sender_public(msg),
            'model': meta.get('model_id'),
            'annotations': meta.get('annotations'),
            'attachments': atts,
        })
    return {
        'conversation': {
            'id': str(conversation['_id']),
            'title': conversation.get('title', 'Untitled'),
            'created_at': _safe_datetime_str(conversation.get('created_at')),
            'message_count': conversation.get('message_count', len(messages)),
        },
        'messages': out_messages,
        'snapshot_at': datetime.utcnow().isoformat(),
    }


@router.get("/{conversation_id}/shares")
def list_conversation_shares(conversation_id: str,
                             user: dict = Depends(require_active)):
    """Owner view of a conversation's current shares (link + team ids)."""
    user_id = str(user['_id'])
    _, err = _fetch_owned_conversation(conversation_id, user_id, 'viewer')
    if err:
        return err
    link = ConversationShareModel.get_link(conversation_id)
    return {
        'link': ({'token': link['token']} if link else None),
        'teams': ConversationShareModel.team_project_ids(conversation_id),
    }


@router.post("/{conversation_id}/share/link")
def create_link_share(conversation_id: str, user: dict = Depends(require_active)):
    """Create (or replace) the frozen-snapshot link share — owner-only.

    Any logged-in user can later open ``/api/share/{token}`` to view the
    snapshot, read-only; messages added after this call do NOT change it.
    """
    user_id = str(user['_id'])
    conversation, err = _fetch_owned_conversation(conversation_id, user_id, 'viewer')
    if err:
        return err
    branch_id = conversation.get('active_branch') or 'main'
    messages = MessageModel.find_by_conversation(
        conversation_id, limit=10000, branch_id=branch_id,
    )
    snapshot = _snapshot_conversation(conversation, messages)
    share = ConversationShareModel.create_link(conversation_id, user_id, snapshot)
    return {'token': share['token']}


@router.delete("/{conversation_id}/share/link")
def revoke_link_share(conversation_id: str, user: dict = Depends(require_active)):
    """Revoke the conversation's active link share — owner-only."""
    user_id = str(user['_id'])
    _, err = _fetch_owned_conversation(conversation_id, user_id, 'viewer')
    if err:
        return err
    ConversationShareModel.revoke_link(conversation_id)
    return {'success': True}


@router.put("/{conversation_id}/share/teams")
async def set_conversation_team_shares(conversation_id: str, request: Request,
                                       user: dict = Depends(require_active)):
    """Replace the set of teams this conversation is shared into — owner-only.

    Each target must be a team the OWNER is a member of (you can't share into a
    team you don't belong to). Invalid/inaccessible ids are dropped silently.
    """
    user_id = str(user['_id'])
    _, err = _fetch_owned_conversation(conversation_id, user_id, 'viewer')
    if err:
        return err
    data = await _json_body(request)
    raw_ids = data.get('project_ids')
    if not isinstance(raw_ids, list):
        return JSONResponse({'error': 'project_ids must be a list'}, status_code=400)
    valid = [
        str(pid) for pid in raw_ids
        if validate_object_id(pid) and check_project_access(user_id, str(pid), 'viewer')
    ]
    teams = ConversationShareModel.set_team_shares(conversation_id, user_id, valid)
    return {'teams': teams}


# ==================== Branch Management Routes ====================
@router.post("/{conversation_id}/branch/{message_id}")
async def create_branch(conversation_id: str, message_id: str, request: Request,
                        user: dict = Depends(require_active)):
    """Create a new branch from a specific message."""
    user_id = str(user['_id'])

    conversation, err = _fetch_owned_conversation(conversation_id, user_id, 'editor')
    if err:
        return err

    message = MessageModel.find_by_id(message_id)
    if not message or str(message['conversation_id']) != conversation_id:
        return JSONResponse({'error': 'Message not found'}, status_code=404)

    data = await _json_body(request)
    branch_name = data.get('name')

    branch_id = str(uuid.uuid4())[:12]
    source_branch = message.get('branch_id', 'main')

    branch_data = {
        'id': branch_id,
        'name': branch_name or "Branch from message",
        'parent_branch': source_branch,
        'branch_point_message_id': str(message['_id']),
    }

    if not ConversationModel.add_branch(conversation_id, branch_data):
        return JSONResponse({'error': 'Failed to create branch'}, status_code=500)

    # Bulk-copy in one commit (was N commits via per-message copy_to_branch).
    # ``copy_many_to_branch`` allocates a contiguous block of fresh monotonic
    # ``seq`` values, so cloned rows never collide on the
    # ``uq_messages_conv_seq`` (conversation_id, seq) unique constraint.
    messages_to_copy = MessageModel.find_up_to(conversation_id, message_id, source_branch)
    copied_messages = MessageModel.copy_many_to_branch(messages_to_copy, branch_id)

    ConversationModel.set_active_branch(conversation_id, branch_id)

    updated_conversation = ConversationModel.find_by_id(conversation_id)

    return JSONResponse({
        'branch_id': branch_id,
        'branches': serialize_doc(updated_conversation.get('branches', [])),
        'messages': serialize_doc(copied_messages),
        'active_branch': branch_id,
    }, status_code=201)


@router.post("/{conversation_id}/branch-to-new/{message_id}")
def branch_to_new_conversation(conversation_id: str, message_id: str,
                               user: dict = Depends(require_active)):
    """Create a new conversation from messages up to a specific point."""
    user_id = str(user['_id'])

    conversation, err = _fetch_owned_conversation(conversation_id, user_id, 'viewer')
    if err:
        return err

    message = MessageModel.find_by_id(message_id)
    if not message or str(message['conversation_id']) != conversation_id:
        return JSONResponse({'error': 'Message not found'}, status_code=404)

    source_branch = message.get('branch_id', 'main')

    messages_to_copy = MessageModel.find_up_to(conversation_id, message_id, source_branch)
    if not messages_to_copy:
        return JSONResponse({'error': 'No messages found'}, status_code=400)

    new_title = f"{conversation.get('title', 'Chat')} (branch)"
    new_conversation = ConversationModel.create(
        user_id=user_id,
        config_id=str(conversation.get('config_id')),
        title=new_title,
        folder_id=str(conversation.get('folder_id')) if conversation.get('folder_id') else None,
        workspace_id=conversation.get('workspace_id') or user.get('active_workspace_id'),
    )

    if not new_conversation:
        return JSONResponse({'error': 'Failed to create new conversation'}, status_code=500)

    new_conversation_id = new_conversation['_id']

    copied_messages = []
    for msg in messages_to_copy:
        new_msg = MessageModel.create(
            conversation_id=new_conversation_id,
            role=msg['role'],
            content=msg['content'],
            branch_id='main',
            metadata=msg.get('metadata', {}),
            attachments=msg.get('attachments', []),
        )
        copied_messages.append(new_msg)

    ConversationModel.set_message_count(new_conversation_id, len(copied_messages))

    return JSONResponse({
        'conversation_id': str(new_conversation_id),
        'title': new_title,
        'message_count': len(copied_messages),
    }, status_code=201)


@router.get("/{conversation_id}/branches")
def list_branches(conversation_id: str, user: dict = Depends(require_active)):
    """List all branches for a conversation."""
    user_id = str(user['_id'])

    conversation, err = _fetch_owned_conversation(conversation_id, user_id, 'viewer')
    if err:
        return err

    branches = conversation.get('branches', [{'id': 'main', 'name': 'Main'}])
    active_branch = conversation.get('active_branch', 'main')

    return {
        'branches': serialize_doc(branches),
        'active_branch': active_branch,
    }


@router.put("/{conversation_id}/branch/{branch_id}")
def switch_branch(conversation_id: str, branch_id: str,
                  user: dict = Depends(require_active)):
    """Switch to a different branch."""
    user_id = str(user['_id'])

    _, err = _fetch_owned_conversation(conversation_id, user_id, 'editor')
    if err:
        return err

    branch = ConversationModel.get_branch(conversation_id, branch_id)
    if not branch:
        return JSONResponse({'error': 'Branch not found'}, status_code=404)

    if not ConversationModel.set_active_branch(conversation_id, branch_id):
        return JSONResponse({'error': 'Failed to switch branch'}, status_code=500)

    messages = MessageModel.find_by_conversation(conversation_id, branch_id=branch_id)

    return {
        'active_branch': branch_id,
        'messages': serialize_doc(messages),
    }


@router.delete("/{conversation_id}/branch/{branch_id}")
def delete_branch(conversation_id: str, branch_id: str,
                  user: dict = Depends(require_active)):
    """Delete a branch (cannot delete 'main')."""
    user_id = str(user['_id'])

    if branch_id == 'main':
        return JSONResponse({'error': 'Cannot delete the main branch'}, status_code=400)

    _, err = _fetch_owned_conversation(conversation_id, user_id, 'editor')
    if err:
        return err

    branch = ConversationModel.get_branch(conversation_id, branch_id)
    if not branch:
        return JSONResponse({'error': 'Branch not found'}, status_code=404)

    MessageModel.delete_by_branch(conversation_id, branch_id)

    if not ConversationModel.remove_branch(conversation_id, branch_id):
        return JSONResponse({'error': 'Failed to delete branch'}, status_code=500)

    return {'success': True}


@router.put("/{conversation_id}/branch/{branch_id}/rename")
async def rename_branch(conversation_id: str, branch_id: str, request: Request,
                        user: dict = Depends(require_active)):
    """Rename a branch."""
    user_id = str(user['_id'])

    if branch_id == 'main':
        return JSONResponse({'error': 'Cannot rename the main branch'}, status_code=400)

    _, err = _fetch_owned_conversation(conversation_id, user_id, 'editor')
    if err:
        return err

    branch = ConversationModel.get_branch(conversation_id, branch_id)
    if not branch:
        return JSONResponse({'error': 'Branch not found'}, status_code=404)

    data = await _json_body(request)
    new_name = (data.get('name', '') or '').strip()

    if not new_name:
        return JSONResponse({'error': 'Branch name is required'}, status_code=400)

    if len(new_name) > 50:
        return JSONResponse(
            {'error': 'Branch name too long (max 50 characters)'}, status_code=400
        )

    if not ConversationModel.update_branch_name(conversation_id, branch_id, new_name):
        return JSONResponse({'error': 'Failed to rename branch'}, status_code=500)

    return {
        'success': True,
        'branch': {'id': branch_id, 'name': new_name},
    }
