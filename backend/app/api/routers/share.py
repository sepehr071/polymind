"""Public shared-snapshot view + import. Mounted at ``/api/share``.

A link share is a self-contained FROZEN snapshot, readable by ANY authenticated
user (product decision: not public-no-auth). It is NOT live sharing:

  * ``GET /{token}``       — read the frozen snapshot (read-only preview).
  * ``POST /{token}/save`` — import the snapshot as the caller's OWN new
    conversation. The copy is fully independent: it survives the original being
    deleted, and the original owner's later messages never touch it.

The snapshot outlives its source conversation (the FK is SET NULL), so these
work even after the original chat is deleted.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import flask_ctx, require_active
from app.models.conversation import ConversationModel
from app.models.conversation_share import ConversationShareModel
from app.models.message import MessageModel
from app.utils.rate_limit import check_rate_limit

router = APIRouter(dependencies=[Depends(flask_ctx)])

# Default model the imported copy is created under so the recipient can continue
# chatting (mirrors the chat default — first quick model).
_SAVE_DEFAULT_CONFIG = 'quick:google/gemini-3.5-flash-lite'


@router.get("/{token}")
def get_shared_snapshot(token: str, user: dict = Depends(require_active)):
    """Return the frozen snapshot behind a share token (any logged-in user)."""
    retry_after = check_rate_limit(
        'share_view', str(user['_id']), max_calls=30, window=60
    )
    if retry_after is not None:
        return JSONResponse(
            {'error': 'rate_limited', 'retry_after': retry_after},
            status_code=429,
            headers={'Retry-After': str(int(retry_after))},
        )
    share = ConversationShareModel.get_by_token(token)
    if not share:
        return JSONResponse({'error': 'Shared chat not found'}, status_code=404)
    return {
        'snapshot': share.get('snapshot') or {},
        'shared_at': share.get('created_at'),
    }


@router.post("/{token}/save")
def save_shared_snapshot(token: str, user: dict = Depends(require_active)):
    """Import the snapshot as the caller's OWN new conversation.

    Independent copy — model name + web-search citations are carried over so the
    saved chat reads like the original, but it is no longer tied to the source.
    """
    retry_after = check_rate_limit(
        'share_save', str(user['_id']), max_calls=10, window=60
    )
    if retry_after is not None:
        return JSONResponse(
            {'error': 'rate_limited', 'retry_after': retry_after},
            status_code=429,
            headers={'Retry-After': str(int(retry_after))},
        )
    share = ConversationShareModel.get_by_token(token)
    if not share:
        return JSONResponse({'error': 'Shared chat not found'}, status_code=404)

    snapshot = share.get('snapshot') or {}
    src_messages = snapshot.get('messages') or []
    src_title = (snapshot.get('conversation') or {}).get('title') or 'Shared chat'

    new_conv = ConversationModel.create(
        user_id=str(user['_id']),
        config_id=_SAVE_DEFAULT_CONFIG,
        title=src_title,
        workspace_id=user.get('active_workspace_id'),
    )
    cid = str(new_conv['_id'])

    count = 0
    for m in src_messages:
        role = m.get('role')
        if role not in ('user', 'assistant'):
            continue
        meta = {}
        if role == 'assistant':
            if m.get('model'):
                meta['model_id'] = m['model']
            if m.get('annotations'):
                meta['annotations'] = m['annotations']
        MessageModel.create(
            conversation_id=cid, role=role, content=m.get('content') or '',
            metadata=(meta or None),
        )
        count += 1
    ConversationModel.set_message_count(cid, count)

    return {'conversation_id': cid}
