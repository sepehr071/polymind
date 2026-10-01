"""Pure-unit tests for the presentation service.

Lives in tests/unit/ (NOT tests/api/) — no DB, no network. Covers the
owner-scoped source assembly (the IDOR guard) and the outline JSON parser.
``generate_outline`` is NOT exercised here (it would hit the network).
"""


def test_assemble_source_text_only_owned(monkeypatch):
    from app.services import presentation_service as ps
    monkeypatch.setattr(ps.UploadModel, 'get_extracted_text_for_user',
        staticmethod(lambda uid, user_id: {'extracted_text': 'DOC TEXT'} if uid == 'own' else None))
    monkeypatch.setattr(ps.KnowledgeItemModel, 'find_by_id',
        staticmethod(lambda iid: {'content': 'KB TEXT', 'user_id': 'u1'} if iid == 'k-own' else None))
    text = ps.assemble_source_text(user_id='u1', upload_ids=['own', 'foreign'],
                                   knowledge_ids=['k-own', 'k-missing'], max_chars=10000)
    # foreign upload id resolves to None via get_extracted_text_for_user
    # (SQL owner-scope) -> only the owned doc text survives.
    assert 'DOC TEXT' in text and 'KB TEXT' in text


def test_assemble_drops_foreign_knowledge(monkeypatch):
    from app.services import presentation_service as ps
    monkeypatch.setattr(ps.UploadModel, 'get_extracted_text_for_user', staticmethod(lambda uid, user_id: None))
    monkeypatch.setattr(ps.KnowledgeItemModel, 'find_by_id',
        staticmethod(lambda iid: {'content': 'OTHER USER', 'user_id': 'someone-else'}))
    text = ps.assemble_source_text(user_id='u1', upload_ids=[], knowledge_ids=['k1'], max_chars=10000)
    assert 'OTHER USER' not in text  # owner mismatch -> dropped


def test_parse_outline_strips_fences_and_normalizes():
    from app.services.presentation_service import _parse_outline_json
    raw = '```json\n{"title":"T","slides":[{"title":"A","bullets":["x",""]}]}\n```'
    out = _parse_outline_json(raw)
    assert out['title'] == 'T'
    assert out['slides'][0]['layout'] == 'content'      # default layout
    assert out['slides'][0]['bullets'] == ['x']          # empty bullet dropped


def test_parse_outline_handles_garbage():
    from app.services.presentation_service import _parse_outline_json
    import pytest
    with pytest.raises(Exception):
        _parse_outline_json('not json at all')


def test_parse_outline_hardens_malformed_slides():
    """Non-dict slides skipped; string bullets don't explode into chars;
    image_prompt coerced to str|None."""
    from app.services.presentation_service import _parse_outline_json
    raw = ('{"title":"T","slides":['
           '"junk",'                                       # non-dict -> skipped
           '{"title":"A","bullets":"oneline","image_prompt":123},'  # str bullets, numeric ip
           '{"title":"B","bullets":["ok"],"image_prompt":null}]}')
    out = _parse_outline_json(raw)
    assert len(out['slides']) == 2                          # "junk" dropped
    assert out['slides'][0]['bullets'] == []                # string NOT per-char
    assert out['slides'][0]['image_prompt'] == '123'        # coerced to str
    assert out['slides'][1]['image_prompt'] is None
