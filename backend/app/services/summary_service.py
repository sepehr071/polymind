"""
Summary service — turns a diarized Persian transcript into a structured
meeting brief via OpenRouter (model hard-locked to Gemini 3.6 Flash).

All LLM traffic flows through ``OpenRouterService._sync_completion`` so
``usage_logs`` rows pick up ``origin='meeting'`` + ``feature='meeting'``
attribution automatically. Never call out to OpenRouter (or any other
provider) directly here — that path skips usage accounting.

The schema mirrors upstream meeting-assistant verbatim. ``minutes`` is
intentionally excluded: the pipeline builds it server-side from the
diarized words to dodge LLM output-token truncation on long meetings.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from jsonschema import ValidationError, validate

logger = logging.getLogger(__name__)


MEETING_SUMMARY_MODEL = 'google/gemini-3.6-flash'


JSON_SCHEMA: dict = {
    'type': 'object',
    'additionalProperties': False,
    'required': [
        'exec_summary',
        'action_items',
        'decisions',
        'qa',
        'open_questions',
        'email_draft',
        'speaker_names',
    ],
    'properties': {
        'exec_summary': {'type': 'string'},
        'action_items': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['text', 'owner', 'due_date'],
                'properties': {
                    'text': {'type': 'string'},
                    'owner': {'type': ['string', 'null']},
                    'due_date': {'type': ['string', 'null']},
                },
            },
        },
        'decisions': {'type': 'array', 'items': {'type': 'string'}},
        'qa': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['question', 'answer'],
                'properties': {
                    'question': {'type': 'string'},
                    'answer': {'type': ['string', 'null']},
                },
            },
        },
        'open_questions': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['question', 'owner'],
                'properties': {
                    'question': {'type': 'string'},
                    'owner': {'type': ['string', 'null']},
                },
            },
        },
        'email_draft': {
            'type': 'object',
            'additionalProperties': False,
            'required': ['subject', 'body'],
            'properties': {
                'subject': {'type': 'string'},
                'body': {'type': 'string'},
            },
        },
        'speaker_names': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['speaker_id', 'display_name'],
                'properties': {
                    'speaker_id': {'type': 'string'},
                    'display_name': {'type': 'string'},
                },
            },
        },
    },
}


EMAIL_TONE_FORMAL = 'formal'
EMAIL_TONE_CASUAL = 'casual'
_VALID_TONES = {EMAIL_TONE_FORMAL, EMAIL_TONE_CASUAL}


TONE_FORMAL = (
    "Email tone: FORMAL. Use respectful Persian (احتراماً، با تشکر، خواهشمندیم). "
    "Address attendees collectively. Keep the body 4-8 short paragraphs."
)
TONE_CASUAL = (
    "Email tone: CASUAL. Use friendly conversational Persian (سلام، ممنون، می‌بینمتون). "
    "Drop honorifics. Short and to-the-point. 3-6 short paragraphs."
)

_TONE_FRAGMENTS = {
    EMAIL_TONE_FORMAL: TONE_FORMAL,
    EMAIL_TONE_CASUAL: TONE_CASUAL,
}


_PROMPT_PATH = Path(__file__).resolve().parent.parent / 'prompts' / 'meeting_summary_system.txt'
SYSTEM_PROMPT_TEXT = _PROMPT_PATH.read_text(encoding='utf-8')


def _build_messages(
    diarized_prompt: str,
    context: Optional[str],
    email_tone: str,
) -> list[dict]:
    messages: list[dict] = [{'role': 'system', 'content': SYSTEM_PROMPT_TEXT}]
    tone = email_tone if email_tone in _VALID_TONES else EMAIL_TONE_FORMAL
    messages.append({'role': 'system', 'content': _TONE_FRAGMENTS[tone]})
    if context and context.strip():
        messages.append({
            'role': 'system',
            'content': (
                "## Meeting context (provided by user)\n"
                "Use this to disambiguate names, products, and acronyms when "
                "transcribing into action items / decisions / minutes. Map "
                "speaker_ids to attendee names listed here when the speaker "
                "introduces themselves or is addressed by name in the transcript.\n\n"
                + context.strip()
            ),
        })
    messages.append({'role': 'user', 'content': diarized_prompt})
    return messages


def summarize(
    diarized_prompt: str,
    *,
    user_id: Optional[str],
    context: Optional[str] = None,
    email_tone: str = EMAIL_TONE_FORMAL,
) -> dict:
    """
    Run the summarizer against a diarized prompt.

    Returns a dict matching ``JSON_SCHEMA`` (no ``minutes`` key — the
    pipeline appends that one server-side).

    Raises:
        ValueError: schema validation failed or the model returned non-JSON.
        RuntimeError: OpenRouter call returned an error payload.
    """
    # Lazy import — keeps this module importable in contexts (tests, indexing)
    # where openrouter_service isn't fully wired yet.
    from app.services.openrouter_service import OpenRouterService

    payload = {
        'model': MEETING_SUMMARY_MODEL,
        'messages': _build_messages(diarized_prompt, context, email_tone),
        'response_format': {
            'type': 'json_schema',
            'json_schema': {
                'name': 'meeting_brief',
                'strict': True,
                'schema': JSON_SCHEMA,
            },
        },
        # Low temperature for stable speaker mapping + clean JSON.
        'temperature': 0.2,
        # Minimal reasoning shrinks latency on long transcripts; exclude=True
        # strips reasoning tokens from the response payload (unused here).
        'reasoning': {'effort': 'minimal', 'exclude': True},
        'stream': False,
    }

    resp = OpenRouterService._sync_completion(
        payload,
        user_id=user_id,
        conversation_id=None,
        feature='meeting',
        workspace_id=None,
        project_id=None,
        origin='meeting',
        timeout=120,
    )

    if not isinstance(resp, dict) or 'error' in resp:
        err = resp.get('error') if isinstance(resp, dict) else resp
        raise RuntimeError(f"summarizer LLM call failed: {err}")

    try:
        content = resp['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"summarizer response missing content: {exc}") from exc

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"summarizer returned non-JSON content: {exc}") from exc

    try:
        validate(instance=parsed, schema=JSON_SCHEMA)
    except ValidationError as exc:
        raise ValueError(f"summarizer schema validation failed: {exc.message}") from exc

    return parsed
