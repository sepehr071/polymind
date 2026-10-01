"""Presentation outline orchestration.

  * ``assemble_source_text`` — owner-scoped assembly of upload + knowledge.
  * ``generate_outline`` — multi-agent pipeline (see presentation_pipeline).
  * ``_parse_outline_json`` / ``_norm_slide`` — outline schema normalization.
"""

import json
import re

from app.models.upload import UploadModel
from app.models.knowledge_item import KnowledgeItemModel
from app.prompts.presentation import VALID_LAYOUTS

_MAX_SOURCE_CHARS = 200_000
_VALID_LAYOUTS = frozenset(VALID_LAYOUTS)
_ICON_ALLOW = frozenset({
    'growth', 'shield', 'users', 'bolt', 'target', 'chart',
    'globe', 'check', 'star', 'rocket', 'clock', 'lightbulb',
})


def assemble_source_text(*, user_id, upload_ids=None, knowledge_ids=None,
                         max_chars=_MAX_SOURCE_CHARS):
    """Owner-scoped only. Foreign/missing ids silently dropped."""
    chunks = []
    for uid in (upload_ids or []):
        rec = UploadModel.get_extracted_text_for_user(uid, user_id)
        if rec and rec.get('extracted_text'):
            chunks.append(rec['extracted_text'])
    for kid in (knowledge_ids or []):
        item = KnowledgeItemModel.find_by_id(kid)
        if item and str(item.get('user_id')) == str(user_id) and item.get('content'):
            chunks.append(item['content'])
    return ("\n\n---\n\n".join(chunks))[:max_chars]


def _str_or_none(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _str_list(raw):
    if not isinstance(raw, list):
        return []
    return [str(b).strip() for b in raw if str(b).strip()]


def _col_side(raw):
    if not isinstance(raw, dict):
        return {'title': '', 'bullets': []}
    return {
        'title': (raw.get('title') or raw.get('label') or '').strip(),
        'bullets': _str_list(raw.get('bullets')),
    }


def _norm_metrics(raw):
    if not isinstance(raw, list):
        return []
    out = []
    for m in raw[:6]:
        if not isinstance(m, dict):
            continue
        value = (m.get('value') or '').strip()
        label = (m.get('label') or '').strip()
        if not value and not label:
            continue
        out.append({
            'value': value,
            'label': label,
            'delta': _str_or_none(m.get('delta')),
        })
    return out


def _norm_steps(raw, key='steps'):
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        title = (item.get('title') or item.get('label') or '').strip()
        body = (item.get('body') or item.get('detail') or '').strip()
        if not title and not body:
            continue
        icon = _str_or_none(item.get('icon'))
        if icon and icon not in _ICON_ALLOW:
            icon = None
        out.append({'title': title, 'body': body, 'icon': icon})
    return out


def _norm_events(raw):
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        label = (item.get('label') or item.get('title') or '').strip()
        detail = (item.get('detail') or item.get('body') or '').strip()
        if not label and not detail:
            continue
        out.append({
            'label': label,
            'detail': detail,
            'when': _str_or_none(item.get('when')),
        })
    return out


def _norm_features(raw):
    return _norm_steps(raw)  # same shape {title, body, icon}


def _norm_chart(raw):
    if not isinstance(raw, dict):
        return None
    ctype = (raw.get('type') or 'bar').strip().lower()
    if ctype not in ('bar', 'line', 'pie'):
        ctype = 'bar'
    cats = _str_list(raw.get('categories'))
    series_in = raw.get('series')
    series = []
    if isinstance(series_in, list):
        for s in series_in[:4]:
            if not isinstance(s, dict):
                continue
            name = (s.get('name') or '').strip() or 'Series'
            vals = []
            for v in (s.get('values') or []):
                try:
                    vals.append(float(v))
                except (TypeError, ValueError):
                    continue
            if vals:
                series.append({'name': name, 'values': vals})
    if not cats or not series:
        return None
    # Align series lengths to categories
    n = len(cats)
    for s in series:
        s['values'] = (s['values'] + [0.0] * n)[:n]
    return {
        'type': ctype,
        'categories': cats,
        'series': series,
        'unit': _str_or_none(raw.get('unit')),
    }


def _norm_visual_recipe(raw):
    if not isinstance(raw, dict):
        return {
            'composition': 'default',
            'accent': 'edge',
            'image_role': 'none',
        }
    comp = (raw.get('composition') or 'default').strip().lower()
    if comp not in ('default', 'hero_split', 'cards_row', 'big_number', 'full_bleed'):
        comp = 'default'
    accent = (raw.get('accent') or 'edge').strip().lower()
    if accent not in ('edge', 'band', 'card', 'none'):
        accent = 'edge'
    role = (raw.get('image_role') or 'none').strip().lower()
    if role not in ('none', 'support', 'hero'):
        role = 'none'
    return {'composition': comp, 'accent': accent, 'image_role': role}


def _norm_slide(s):
    layout = (s.get('layout') or 'content').strip().lower()
    if layout not in _VALID_LAYOUTS:
        layout = 'content'
    cols_raw = s.get('columns') if isinstance(s.get('columns'), dict) else None
    columns = None
    if cols_raw is not None:
        columns = {
            'left': _col_side(cols_raw.get('left')),
            'right': _col_side(cols_raw.get('right')),
        }
    purpose = _str_or_none(s.get('purpose'))
    return {
        'layout': layout,
        'title': (s.get('title') or '').strip(),
        'subtitle': _str_or_none(s.get('subtitle')),
        'kicker': _str_or_none(s.get('kicker')),
        'bullets': _str_list(s.get('bullets')),
        'items': _str_list(s.get('items')) or None,
        'speaker_notes': (s.get('speaker_notes') or '').strip(),
        'image_prompt': _str_or_none(s.get('image_prompt')),
        'caption': _str_or_none(s.get('caption')),
        'quote': _str_or_none(s.get('quote')),
        'attribution': _str_or_none(s.get('attribution')),
        'columns': columns,
        'metrics': _norm_metrics(s.get('metrics')) or None,
        'steps': _norm_steps(s.get('steps')) or None,
        'events': _norm_events(s.get('events')) or None,
        'features': _norm_features(s.get('features')) or None,
        'chart': _norm_chart(s.get('chart')),
        'purpose': purpose,
        'visual_recipe': _norm_visual_recipe(s.get('visual_recipe')),
    }


def _parse_outline_json(raw):
    raw = (raw or '').strip()
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
    start, end = raw.find('{'), raw.rfind('}')
    if start != -1 and end != -1:
        raw = raw[start:end + 1]
    data = json.loads(raw)
    norm = []
    for s in (data.get('slides') or []):
        if not isinstance(s, dict):
            continue
        norm.append(_norm_slide(s))
    return {
        'title': (data.get('title') or '').strip(),
        'language': data.get('language') or 'fa',
        'slides': norm,
    }


def generate_outline(*, topic, source_text, slide_count, tone, audience, language,
                     user_id, workspace_id, project_id, origin='web', stop_event=None):
    """Blocking multi-agent pipeline — caller runs on SSE worker thread.

    Prefer iterating ``presentation_pipeline.run_outline_pipeline`` when the
    caller needs SSE phase events; this helper returns the final outline only.
    """
    from app.services.presentation_pipeline import generate_outline_via_pipeline
    return generate_outline_via_pipeline(
        topic=topic,
        source_text=source_text,
        slide_count=slide_count,
        tone=tone,
        audience=audience,
        language=language,
        user_id=user_id,
        workspace_id=workspace_id,
        project_id=project_id,
        origin=origin,
        stop_event=stop_event,
    )
