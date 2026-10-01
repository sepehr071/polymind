"""All-in-one router agent — tool schemas + helpers.

Tool definitions, tool list assembly, and small pure helpers. Turn
orchestration (SSE producer) lives in ``app.services.agent_turn``.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.settings import settings

logger = logging.getLogger(__name__)

AGENT_FEATURE = 'agent'

# Tabular / doc exts that should be prepared into a sandbox workdir (mirror data analyzer).
_DATA_EXTS = frozenset({
    'csv', 'tsv', 'xlsx', 'xls', 'xlsm', 'parquet', 'json', 'jsonl',
    'txt', 'text', 'pdf', 'docx', 'pptx', 'html', 'htm', 'md', 'xml',
    'png', 'jpg', 'jpeg', 'webp', 'gif',
})


ASK_USER_TOOL: Dict[str, Any] = {
    'type': 'function',
    'function': {
        'name': 'ask_user',
        'description': (
            'Pause and ask the user clarifying questions before continuing. '
            'Use when goals, constraints, or inputs are ambiguous. Max 3 questions.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'questions': {
                    'type': 'array',
                    'minItems': 1,
                    'maxItems': 3,
                    'items': {
                        'type': 'object',
                        'properties': {
                            'id': {
                                'type': 'string',
                                'description': 'Stable id for this question (e.g. q1).',
                            },
                            'prompt': {
                                'type': 'string',
                                'description': 'Question text shown to the user.',
                            },
                            'options': {
                                'type': 'array',
                                'items': {'type': 'string'},
                                'description': 'Optional multiple-choice options.',
                            },
                        },
                        'required': ['id', 'prompt'],
                        'additionalProperties': False,
                    },
                },
            },
            'required': ['questions'],
            'additionalProperties': False,
        },
    },
}

GENERATE_IMAGE_TOOL: Dict[str, Any] = {
    'type': 'function',
    'function': {
        'name': 'generate_image',
        'description': (
            'Generate an image from a detailed visual prompt. Returns an image id '
            'and URL the user can see. Use for illustrations, diagrams, mockups.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'prompt': {
                    'type': 'string',
                    'description': 'Detailed image generation prompt.',
                },
                'aspect_ratio': {
                    'type': 'string',
                    'description': 'Optional aspect ratio, e.g. 1:1, 16:9, 9:16, 4:3.',
                },
            },
            'required': ['prompt'],
            'additionalProperties': False,
        },
    },
}

RUN_PYTHON_TOOL: Dict[str, Any] = {
    'type': 'function',
    'function': {
        'name': 'run_python',
        'description': (
            'Execute Python against preloaded data in a sandbox. Installed: '
            'pandas, numpy, scipy, sklearn, statsmodels, pyarrow, openpyxl, xlrd, duckdb. '
            'Preloaded: df, dfs, datafiles. Injected helpers (do not import): '
            'show_metric, show_insight, show_table, show_chart, save_output, sql. '
            'NO matplotlib/seaborn/plotly — charts ONLY via show_chart(...). '
            'Use print() to inspect. Never invent numbers.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'code': {
                    'type': 'string',
                    'description': 'Self-contained Python source to execute.',
                },
            },
            'required': ['code'],
            'additionalProperties': False,
        },
    },
}


def orchestrator_model() -> str:
    return (
        settings.get('AGENT_ORCHESTRATOR_MODEL')
        or 'anthropic/claude-sonnet-5'
    )


def image_model() -> str:
    return (
        settings.get('AGENT_IMAGE_MODEL')
        or 'google/gemini-3.1-flash-image'
    )


def max_rounds() -> int:
    try:
        return max(1, int(settings.get('AGENT_MAX_ROUNDS', 12)))
    except (TypeError, ValueError):
        return 12


def reasoning_effort() -> str | None:
    """Orchestrator reasoning effort. None = omit (provider default)."""
    raw = str(settings.get('AGENT_REASONING_EFFORT') or 'low').strip().lower()
    if raw in ('', 'none', 'off', '0'):
        return None
    if raw in ('low', 'medium', 'high'):
        return raw
    return 'low'


def subagent_enabled() -> bool:
    # Default OFF — openrouter:subagent adds latency and is flaky under egress
    # proxy; enable with AGENT_SUBAGENT=1 when needed.
    raw = str(settings.get('AGENT_SUBAGENT', '0') or '0').strip().lower()
    return raw in ('1', 'true', 'yes', 'on')


def web_search_params() -> Dict[str, Any]:
    """OpenRouter server web_search knobs for the agent tool loop.

    ``engine: native`` matches shop/research (better freshness than bare default).
    Higher max_results than chat default so news digests have more to pick from.
    """
    try:
        max_results = int(settings.get('AGENT_WEB_SEARCH_MAX_RESULTS') or 8)
    except (TypeError, ValueError):
        max_results = 8
    max_results = max(3, min(15, max_results))
    engine = (settings.get('AGENT_WEB_SEARCH_ENGINE') or 'native').strip() or 'native'
    return {
        'max_results': max_results,
        'engine': engine,
    }


def current_time_block() -> str:
    """Inject wall-clock so the model does not treat 2024/2025 as 'latest'."""
    from datetime import datetime, timezone

    try:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo('Asia/Tehran'))
        tz_label = 'Asia/Tehran'
    except Exception:  # noqa: BLE001
        now = datetime.now(timezone.utc)
        tz_label = 'UTC'
    return (
        f"\n\n## Current time\n"
        f"Today is **{now.strftime('%Y-%m-%d')}** ({tz_label}). "
        f"Calendar year is **{now.year}**. "
        f"Treat anything older than ~6 months as stale for 'latest news' requests "
        f"unless the user asks for history.\n"
    )


def build_agent_tools(*, include_run_python: bool = True) -> List[Dict[str, Any]]:
    """Function tools + optional OpenRouter server subagent tool."""
    tools: List[Dict[str, Any]] = [ASK_USER_TOOL, GENERATE_IMAGE_TOOL]
    if include_run_python:
        tools.append(RUN_PYTHON_TOOL)

    if subagent_enabled():
        worker = (
            settings.get('AGENT_SUBAGENT_MODEL')
            or 'google/gemini-3.5-flash-lite'
        )
        tools.append({
            'type': 'openrouter:subagent',
            'parameters': {
                'model': worker,
                'instructions': (
                    'You are a focused research worker. Complete the task exactly. '
                    'Use web search/fetch when needed. Return structured findings '
                    'with sources. No chit-chat.'
                ),
                'tools': [
                    {'type': 'openrouter:web_search'},
                    {'type': 'openrouter:web_fetch'},
                ],
                'max_tool_calls': 8,
            },
        })
    return tools


def attachment_ext(att: dict) -> str:
    name = (
        (att or {}).get('original_name')
        or (att or {}).get('filename')
        or (att or {}).get('name')
        or ''
    )
    if '.' not in name:
        mime = ((att or {}).get('mime_type') or (att or {}).get('content_type') or '')
        if 'spreadsheet' in mime or 'excel' in mime:
            return 'xlsx'
        if 'csv' in mime:
            return 'csv'
        if 'pdf' in mime:
            return 'pdf'
        if mime.startswith('image/'):
            return mime.split('/', 1)[-1]
        return ''
    return name.rsplit('.', 1)[-1].lower()


def needs_dataset(attachments: Optional[List[dict]]) -> bool:
    for a in attachments or []:
        if attachment_ext(a) in _DATA_EXTS:
            return True
    return False


def normalize_questions(raw: Any) -> List[Dict[str, Any]]:
    """Sanitize ask_user questions for SSE + storage."""
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for i, q in enumerate(raw[:3]):
        if not isinstance(q, dict):
            continue
        qid = str(q.get('id') or f'q{i + 1}').strip()[:64]
        prompt = str(q.get('prompt') or '').strip()[:2000]
        if not prompt:
            continue
        item: Dict[str, Any] = {'id': qid, 'prompt': prompt}
        opts = q.get('options')
        if isinstance(opts, list):
            cleaned = [str(o).strip()[:200] for o in opts if str(o).strip()]
            if cleaned:
                item['options'] = cleaned[:8]
        out.append(item)
    return out


def format_answers_for_model(questions: List[dict], answers: dict) -> str:
    lines = ['User answers to your clarifying questions:']
    for q in questions:
        qid = q.get('id')
        prompt = q.get('prompt') or qid
        val = answers.get(qid) if isinstance(answers, dict) else None
        if val is None or str(val).strip() == '':
            val = '(no answer)'
        lines.append(f'- {prompt}: {val}')
    return '\n'.join(lines)


def dump_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)
