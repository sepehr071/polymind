"""Meeting artifact routes: spawn-conversation, save-artifact, render helpers."""
from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import feature_dep, require_active
from app.models.conversation import ConversationModel
from app.models.knowledge_folder import KnowledgeFolderModel
from app.models.knowledge_item import KnowledgeItemModel
from app.models.meeting import MeetingModel
from app.models.meeting_summary import MeetingSummaryModel
from app.models.meeting_transcript import MeetingTranscriptModel
from app.models.message import MessageModel
from app.services.meetings_service import MEETING_DISCUSSION_MODEL, build_seed_text
from app.utils.helpers import serialize_doc

from ._common import _json_body, router

# ---------------------------------------------------------------------------
# POST /{meeting_id}/spawn-conversation — seed a chat conversation.
# ---------------------------------------------------------------------------

@router.post("/{meeting_id}/spawn-conversation")
def spawn_conversation(
    meeting_id: str,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])

    meeting = MeetingModel.find_owned(meeting_id, user_id)
    if not meeting:
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)

    # Idempotent: if a seed message already exists for this meeting and points
    # to a live conversation owned by this user, return it instead of spawning
    # a duplicate. Keeps the in-page Discuss tab from creating one chat per open.
    seed = MessageModel.find_meeting_seed(meeting_id)
    if seed:
        existing_conv = ConversationModel.find_by_id(seed['conversation_id'])
        if existing_conv and str(existing_conv.get('user_id')) == user_id and not existing_conv.get('archived'):
            return {
                'conversation_id': str(existing_conv['_id']),
                'message': 'Reusing existing meeting conversation',
                'reused': True,
            }

    transcript = MeetingTranscriptModel.find_by_meeting(meeting_id)
    summary = MeetingSummaryModel.find_latest_for_meeting(meeting_id)

    seed_text = build_seed_text(meeting, transcript, summary)

    title_source = meeting.get('title') or meeting.get('original_filename') or 'Untitled'
    conversation = ConversationModel.create(
        user_id=user['_id'],
        config_id=f'quick:{MEETING_DISCUSSION_MODEL}',
        title=f'Meeting: {title_source}'[:200],
        workspace_id=user.get('active_workspace_id'),
    )
    conv_id = conversation['_id']

    MessageModel.create(
        conversation_id=conv_id,
        role='system',
        content=seed_text,
        metadata={'source': 'meeting', 'meeting_id': meeting_id},
    )
    ConversationModel.increment_message_count(conv_id)

    return JSONResponse({
        'conversation_id': str(conv_id),
        'message': 'Conversation seeded with meeting context',
        'reused': False,
    }, status_code=201)


# ---------------------------------------------------------------------------
# POST /{meeting_id}/save-artifact — push a summary artifact into Knowledge.
# ---------------------------------------------------------------------------

_VALID_ARTIFACT_KINDS = {
    'exec_summary',
    'action_items',
    'decisions',
    'minutes',
    'qa',
    'open_questions',
    'email_draft',
    'transcript',
}


def _render_artifact(meeting: dict, summary: dict | None, transcript: dict | None, kind: str) -> tuple[str | None, str]:
    """Return (content_text, suggested_title_fragment) for an artifact kind.

    Content is plain markdown. Returns (None, _) if the source data is missing.
    """
    title_source = (meeting.get('title') or meeting.get('original_filename') or 'Untitled').strip()

    if kind == 'transcript':
        if not transcript:
            return None, 'Transcript'
        plain = (transcript.get('plain_text') or '').strip()
        if not plain:
            return None, 'Transcript'
        return f"# Transcript — {title_source}\n\n{plain}", 'Transcript'

    if not summary:
        return None, kind

    if kind == 'exec_summary':
        txt = (summary.get('exec_summary') or '').strip()
        return (f"# Executive Summary — {title_source}\n\n{txt}" if txt else None, 'Executive Summary')

    if kind == 'action_items':
        items = summary.get('action_items_json') or []
        if not items:
            return None, 'Action Items'
        lines = [f"# Action Items — {title_source}", ""]
        for item in items:
            text = (item.get('text') or '').strip()
            owner = (item.get('owner') or '').strip()
            due = (item.get('due_date') or '').strip()
            bits = [text]
            meta = []
            if owner:
                meta.append(f"@{owner}")
            if due:
                meta.append(f"due {due}")
            if meta:
                bits.append(f"_({', '.join(meta)})_")
            lines.append(f"- {' '.join(b for b in bits if b)}".rstrip())
        return '\n'.join(lines), 'Action Items'

    if kind == 'decisions':
        items = summary.get('decisions_json') or []
        if not items:
            return None, 'Decisions'
        lines = [f"# Decisions — {title_source}", ""]
        for entry in items:
            if isinstance(entry, str) and entry.strip():
                lines.append(f"- {entry.strip()}")
        return '\n'.join(lines), 'Decisions'

    if kind == 'minutes':
        items = summary.get('minutes_json') or []
        if not items:
            return None, 'Minutes'
        lines = [f"# Minutes — {title_source}", ""]
        for entry in items:
            speaker = (entry.get('speaker_id') or '').strip() or 'speaker_?'
            text = (entry.get('text') or '').strip()
            if not text:
                continue
            start = entry.get('start_s')
            end = entry.get('end_s')
            tag = ''
            if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                tag = f" `[{float(start):.2f}-{float(end):.2f}]`"
            lines.append(f"- **{speaker}**{tag}: {text}")
        return '\n'.join(lines), 'Minutes'

    if kind == 'qa':
        items = summary.get('qa_json') or []
        if not items:
            return None, 'Q&A'
        lines = [f"# Q&A — {title_source}", ""]
        for entry in items:
            q = (entry.get('question') or '').strip()
            a = (entry.get('answer') or '').strip()
            if not q:
                continue
            lines.append(f"- **Q:** {q}")
            if a:
                lines.append(f"  **A:** {a}")
        return '\n'.join(lines), 'Q&A'

    if kind == 'open_questions':
        items = summary.get('open_questions_json') or []
        if not items:
            return None, 'Open Questions'
        lines = [f"# Open Questions — {title_source}", ""]
        for entry in items:
            q = (entry.get('question') or '').strip()
            owner = (entry.get('owner') or '').strip()
            if not q:
                continue
            line = f"- {q}"
            if owner:
                line += f" _({owner})_"
            lines.append(line)
        return '\n'.join(lines), 'Open Questions'

    if kind == 'email_draft':
        subject = (summary.get('email_subject') or '').strip()
        body = (summary.get('email_draft') or '').strip()
        if not subject and not body:
            return None, 'Follow-up Email'
        lines = [f"# Follow-up Email — {title_source}", ""]
        if subject:
            lines.append(f"**Subject:** {subject}")
            lines.append("")
        if body:
            lines.append(body)
        return '\n'.join(lines), 'Follow-up Email'

    return None, kind


def _find_or_create_meeting_folder(user_id: str, meeting: dict) -> str:
    """Return a folder_id (string) for storing this meeting's artifacts.

    Uses the meeting title as the folder name; falls back to ``original_filename``.
    Personal-scope only (no project_id) for v1.
    """
    folder_name = (meeting.get('title') or meeting.get('original_filename') or 'Meeting')[:100]
    existing = KnowledgeFolderModel.find_by_user_scope_name(user_id, folder_name)
    if existing:
        return str(existing['_id'])
    folder = KnowledgeFolderModel.create(user_id=user_id, name=folder_name)
    return str(folder['_id'])


@router.post("/{meeting_id}/save-artifact")
async def save_artifact(
    meeting_id: str,
    request: Request,
    user: dict = Depends(require_active),
    _feat: dict = Depends(feature_dep('meetings')),
):
    user_id = str(user['_id'])

    meeting = MeetingModel.find_owned(meeting_id, user_id)
    if not meeting:
        return JSONResponse({'error': 'Meeting not found'}, status_code=404)

    data = await _json_body(request)
    kind = (data.get('artifact_kind') or '').strip()
    if kind not in _VALID_ARTIFACT_KINDS:
        return JSONResponse({
            'error': f"Invalid artifact_kind. Must be one of {sorted(_VALID_ARTIFACT_KINDS)}",
        }, status_code=400)

    transcript = MeetingTranscriptModel.find_by_meeting(meeting_id)
    summary = MeetingSummaryModel.find_latest_for_meeting(meeting_id)

    content, kind_label = _render_artifact(meeting, summary, transcript, kind)
    if not content:
        return JSONResponse({'error': f'No content available for artifact_kind={kind}'}, status_code=400)

    folder_id_raw = data.get('folder_id')
    folder_id = (folder_id_raw or '').strip() if isinstance(folder_id_raw, str) else None
    if not folder_id:
        folder_id = _find_or_create_meeting_folder(user_id, meeting)

    title_source = (meeting.get('title') or meeting.get('original_filename') or 'Untitled').strip()
    item_title = f"{title_source} — {kind_label}"[:200]

    item = KnowledgeItemModel.create(
        user_id=user_id,
        source_type='meeting',
        source_id=meeting_id,
        content=content,
        title=item_title,
        folder_id=folder_id,
        metadata={'artifact_kind': kind},
    )

    return JSONResponse({
        'message': 'Artifact saved to Knowledge Vault',
        'item': serialize_doc(item),
        'folder_id': folder_id,
    }, status_code=201)
