"""Direct coverage for the meetings background pipeline + transcription service.

Mirrors tests/api/test_models_meetings_cov.py (real model facades inside
``flask_core.app_context()`` against the isolated ``unichat_*_test`` DB) and
the seeding helpers in tests/api/test_meetings.py. NO HTTP — these exercise the
background-thread pipeline functions directly.

External upstreams are mocked at the service boundary:
  - ElevenLabs Scribe: a fake ``ElevenLabs`` class injected into the lazily
    imported ``elevenlabs`` module (transcription_service imports it inside
    ``transcribe``), plus config/env key overrides.
  - OpenRouter summarizer: ``summary_service.summarize`` monkeypatched to a
    canned dict.
  - DLP gate: meetings always pass ``workspace_id=None`` so ``dlp_gate.gate``
    short-circuits server-side (no LLM); the _DLPBlocked branch is driven by
    monkeypatching the gate to raise ``DLPBlockedError``.

Targets the uncovered ranges in:
  - app/services/meetings_pipeline.py
  - app/services/transcription_service.py
"""
import sys
import threading
import types
import uuid

import pytest

import app.services.meetings_pipeline as pipeline
import app.services.transcription_service as ts
import app.utils.outbound_proxy as outbound_proxy
from app.api.core import db
from app.models.meeting import MeetingModel
from app.models.meeting_series import MeetingSeriesModel
from app.models.meeting_summary import MeetingSummaryModel
from app.models.meeting_transcript import MeetingTranscriptModel
from app.services.dlp_gate import DLPBlockedError


# ===========================================================================
# Seeding helpers (mirror test_meetings.py / test_models_meetings_cov.py).
# ===========================================================================
def _mk_meeting(flask_core, owner_id, *, title="Quarterly Review", status="uploaded",
                series_id=None, speakers=None, audio_path="/tmp/audio.webm",
                num_speakers=None, meeting_brief=None):
    mid = str(uuid.uuid4())
    with flask_core.app_context():
        data = {
            "_id": mid,
            "title": title,
            "status": status,
            "series_id": series_id,
            "speakers": speakers or [],
            "audio_path": audio_path,
        }
        if num_speakers is not None:
            data["num_speakers"] = num_speakers
        if meeting_brief is not None:
            data["meeting_brief"] = meeting_brief
        MeetingModel.create(str(owner_id), data)
    return mid


def _mk_series(flask_core, owner_id, *, name="Weekly Sync", email_tone="formal"):
    with flask_core.app_context():
        return MeetingSeriesModel.create(str(owner_id), {"name": name, "email_tone": email_tone})


def _mk_transcript(flask_core, meeting_id, *, words=None, plain_text="hello world"):
    with flask_core.app_context():
        MeetingTranscriptModel.create(meeting_id, {
            "plain_text": plain_text,
            "raw_json": {},
            "words_json": words if words is not None else [],
            "language_code": "fas",
        })


def _meeting_status(flask_core, meeting_id):
    with flask_core.app_context():
        return (MeetingModel.find_by_id(meeting_id) or {}).get("status")


def _meeting_error(flask_core, meeting_id):
    with flask_core.app_context():
        return (MeetingModel.find_by_id(meeting_id) or {}).get("error_message")


_SUMMARY_DATA = {
    "exec_summary": "We shipped.",
    "action_items": [{"text": "Follow up", "owner": "Pat", "due_date": None}],
    "decisions": ["Adopt X"],
    "qa": [{"question": "Why?", "answer": "Because"}],
    "open_questions": [{"question": "Open?", "owner": None}],
    "email_draft": {"subject": "Recap", "body": "Hello team,"},
    "speaker_names": [{"speaker_id": "speaker_0", "display_name": "Pat"}],
}


def _words(*specs):
    """Build word dicts from (text, start, end, speaker) tuples."""
    out = []
    for text, start, end, speaker in specs:
        out.append({"text": text, "start": start, "end": end, "speaker_id": speaker})
    return out


# ===========================================================================
# transcription_service: _resolve_api_key.
# ===========================================================================
def test_resolve_api_key_from_config(flask_core):
    with flask_core.app_context():
        flask_core.config["ELEVENLABS_API_KEY"] = "  cfg-key  "
        try:
            assert ts._resolve_api_key() == "cfg-key"
        finally:
            flask_core.config["ELEVENLABS_API_KEY"] = None


def test_resolve_api_key_from_env(flask_core, monkeypatch):
    with flask_core.app_context():
        flask_core.config["ELEVENLABS_API_KEY"] = None
        monkeypatch.setenv("ELEVENLABS_API_KEY", "env-key")
        assert ts._resolve_api_key() == "env-key"


def test_resolve_api_key_missing(flask_core, monkeypatch):
    with flask_core.app_context():
        flask_core.config["ELEVENLABS_API_KEY"] = None
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        assert ts._resolve_api_key() == ""


def test_resolve_api_key_settings_runtimeerror_falls_through_to_env(monkeypatch):
    """The ``except RuntimeError`` branch (vestigial current_app.config guard).

    In the Flask-free settings shim ``settings.get`` never raises RuntimeError,
    so this branch is only reachable by forcing the raise — proving the env
    fallthrough still works when the config lookup blows up.
    """
    class _Boom:
        def get(self, *a, **k):
            raise RuntimeError("no app context")

    monkeypatch.setattr(ts, "settings", _Boom())
    monkeypatch.setenv("ELEVENLABS_API_KEY", "env-after-runtimeerror")
    assert ts._resolve_api_key() == "env-after-runtimeerror"


# ===========================================================================
# transcription_service: _serialize_word / _serialize_response.
# ===========================================================================
class _ModelDumpWord:
    def model_dump(self):
        return {"text": "md", "start": 1.0}


class _AttrWord:
    text = "attr"
    start = 0.5
    end = 0.9
    type = "word"
    speaker_id = "speaker_0"


def test_serialize_word_model_dump():
    assert ts._serialize_word(_ModelDumpWord()) == {"text": "md", "start": 1.0}


def test_serialize_word_dict_copy():
    src = {"text": "d", "start": 2.0}
    out = ts._serialize_word(src)
    assert out == src and out is not src


def test_serialize_word_attr_fallback():
    out = ts._serialize_word(_AttrWord())
    assert out == {"text": "attr", "start": 0.5, "end": 0.9,
                   "type": "word", "speaker_id": "speaker_0"}


def test_serialize_response_model_dump():
    class R:
        def model_dump(self):
            return {"k": "v"}
    assert ts._serialize_response(R()) == {"k": "v"}


def test_serialize_response_dict_and_other():
    src = {"a": 1}
    out = ts._serialize_response(src)
    assert out == src and out is not src
    assert ts._serialize_response(object()) == {}


# ===========================================================================
# transcription_service: transcribe.
# ===========================================================================
def test_transcribe_no_api_key_raises(flask_core, monkeypatch, tmp_path):
    audio = tmp_path / "a.webm"
    audio.write_bytes(b"x")
    with flask_core.app_context():
        flask_core.config["ELEVENLABS_API_KEY"] = None
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY is not configured"):
            ts.transcribe(audio)


def _install_fake_elevenlabs(monkeypatch, *, response=None, raise_exc=None, captured=None):
    """Inject a fake ``elevenlabs`` module so ``from elevenlabs import ElevenLabs`` works."""
    class _FakeConvert:
        def convert(self, **kwargs):
            if captured is not None:
                captured["convert_kwargs"] = kwargs
            if raise_exc is not None:
                raise raise_exc
            return response

    class _FakeElevenLabs:
        def __init__(self, **kwargs):
            if captured is not None:
                captured["init_kwargs"] = kwargs
            self.speech_to_text = _FakeConvert()

    fake_mod = types.ModuleType("elevenlabs")
    fake_mod.ElevenLabs = _FakeElevenLabs
    monkeypatch.setitem(sys.modules, "elevenlabs", fake_mod)


class _Resp:
    def __init__(self, words, language_code="fas"):
        self.words = words
        self.language_code = language_code

    def model_dump(self):
        return {"words": self.words, "language_code": self.language_code}


def test_transcribe_happy_no_proxy(flask_core, monkeypatch, tmp_path):
    audio = tmp_path / "clip.webm"
    audio.write_bytes(b"audio-bytes")
    captured = {}
    words = [
        {"text": "سلام", "start": 0.0, "end": 0.5, "type": "word", "speaker_id": "s0"},
        {"text": " ", "start": 0.5, "end": 0.6, "type": "spacing", "speaker_id": "s0"},
        {"text": "[noise]", "start": 0.6, "end": 0.7, "type": "audio_event", "speaker_id": "s1"},
        {"text": "خوبی", "start": 0.7, "end": 1.0, "type": "word", "speaker_id": "s1"},
    ]
    _install_fake_elevenlabs(monkeypatch, response=_Resp(words), captured=captured)
    monkeypatch.setattr(outbound_proxy, "proxy_enabled", lambda: False)

    with flask_core.app_context():
        flask_core.config["ELEVENLABS_API_KEY"] = "k"
        result = ts.transcribe(audio, num_speakers=2, keyterms=["Helm", "Istio"])

    # plain_text = only word + spacing types joined.
    assert result.plain_text == "سلام خوبی"
    # speaker ids in first-seen order, de-duped.
    assert result.speaker_ids == ["s0", "s1"]
    assert result.language_code == "fas"
    assert len(result.words) == 4
    assert result.raw["language_code"] == "fas"
    # convert kwargs carried num_speakers + keyterms.
    ck = captured["convert_kwargs"]
    assert ck["num_speakers"] == 2
    assert ck["keyterms"] == ["Helm", "Istio"]
    assert ck["model_id"] == "scribe_v2"
    assert ck["language_code"] == "fas"


def test_transcribe_no_words_empty_speakers(flask_core, monkeypatch, tmp_path):
    audio = tmp_path / "clip.webm"
    audio.write_bytes(b"x")
    # response.words is None -> [] fallback; language_code None -> 'fas'.
    _install_fake_elevenlabs(monkeypatch, response=_Resp(None, language_code=None))
    monkeypatch.setattr(outbound_proxy, "proxy_enabled", lambda: False)
    with flask_core.app_context():
        flask_core.config["ELEVENLABS_API_KEY"] = "k"
        result = ts.transcribe(audio)
    assert result.plain_text == ""
    assert result.speaker_ids == []
    assert result.language_code == "fas"


def test_transcribe_proxy_enabled_path(flask_core, monkeypatch, tmp_path):
    audio = tmp_path / "clip.webm"
    audio.write_bytes(b"x")
    captured = {}
    _install_fake_elevenlabs(
        monkeypatch,
        response=_Resp([{"text": "hi", "start": 0.0, "end": 0.1, "type": "word", "speaker_id": "s0"}]),
        captured=captured,
    )
    monkeypatch.setattr(outbound_proxy, "proxy_enabled", lambda: True)
    monkeypatch.setattr(
        outbound_proxy, "rewrite",
        lambda url: ("https://proxy.local", {"Host": "api.elevenlabs.io"}),
    )
    with flask_core.app_context():
        flask_core.config["ELEVENLABS_API_KEY"] = "k"
        result = ts.transcribe(audio)
    assert result.plain_text == "hi"
    # proxy branch builds an httpx_client + base_url; the fake just records it.
    assert "base_url" in captured["init_kwargs"]
    assert captured["init_kwargs"]["base_url"] == "https://proxy.local"
    assert "httpx_client" in captured["init_kwargs"]


def test_transcribe_sdk_error_wrapped(flask_core, monkeypatch, tmp_path):
    audio = tmp_path / "clip.webm"
    audio.write_bytes(b"x")
    _install_fake_elevenlabs(monkeypatch, raise_exc=ValueError("boom"))
    monkeypatch.setattr(outbound_proxy, "proxy_enabled", lambda: False)
    with flask_core.app_context():
        flask_core.config["ELEVENLABS_API_KEY"] = "k"
        with pytest.raises(RuntimeError, match="Scribe failed: boom"):
            ts.transcribe(audio)


# ===========================================================================
# meetings_pipeline: word helpers.
# ===========================================================================
def test_word_text():
    assert pipeline._word_text({"text": "hi"}) == "hi"
    assert pipeline._word_text({"text": None}) == ""
    assert pipeline._word_text({}) == ""


def test_word_speaker():
    assert pipeline._word_speaker({"speaker_id": "s0"}) == "s0"
    assert pipeline._word_speaker({"speaker_id": 7}) == "7"
    assert pipeline._word_speaker({"speaker_id": None}) is None
    assert pipeline._word_speaker({}) is None


def test_word_start_end_valid_and_invalid():
    assert pipeline._word_start({"start": "1.5"}) == 1.5
    assert pipeline._word_start({"start": None}) is None
    assert pipeline._word_start({"start": "nope"}) is None
    assert pipeline._word_end({"end": 2}) == 2.0
    assert pipeline._word_end({"end": None}) is None
    assert pipeline._word_end({"end": object()}) is None


# ===========================================================================
# meetings_pipeline: _segment_words / build_diarized_prompt / build_minutes.
# ===========================================================================
def test_segment_words_speaker_change_and_gap():
    words = _words(
        ("Hello", 0.0, 0.5, "s0"),
        ("there", 0.5, 1.0, "s0"),
        # speaker change -> new segment
        ("Hi", 1.1, 1.5, "s1"),
        # same speaker but big gap (>1.2s from 1.5) -> new segment
        ("again", 5.0, 5.4, "s1"),
    )
    segs = pipeline._segment_words(words)
    assert len(segs) == 3
    # Word texts are joined with NO separator (spacing arrives as its own word).
    assert segs[0] == ("s0", 0.0, 1.0, "Hellothere")
    assert segs[1][0] == "s1" and segs[1][3] == "Hi"
    assert segs[2][3] == "again"


def test_segment_words_missing_timestamps_and_default_speaker():
    # No speaker_id -> 'speaker_0'; missing start falls back to prev end.
    words = [
        {"text": "a", "start": None, "end": None},
        {"text": "b", "start": None, "end": None},
    ]
    segs = pipeline._segment_words(words)
    assert len(segs) == 1
    assert segs[0][0] == "speaker_0"
    assert "a" in segs[0][3] and "b" in segs[0][3]


def test_segment_words_blank_text_flushed_to_nothing():
    # Whitespace-only text -> flush() returns early (no segment).
    segs = pipeline._segment_words([{"text": "   ", "start": 0.0, "end": 0.1, "speaker_id": "s0"}])
    assert segs == []


def test_build_diarized_prompt():
    words = _words(("Hello", 0.0, 1.0, "s0"), ("Hi", 2.5, 3.0, "s1"))
    out = pipeline.build_diarized_prompt(words)
    lines = out.split("\n")
    assert lines[0] == "[s0 0.00-1.00] Hello"
    assert lines[1] == "[s1 2.50-3.00] Hi"


def test_build_minutes_segments():
    words = _words(("Hello", 0.0, 1.0, "s0"))
    out = pipeline.build_minutes_segments(words)
    assert out == [{"speaker_id": "s0", "text": "Hello", "start_s": 0.0, "end_s": 1.0}]


def test_build_minutes_segments_empty():
    assert pipeline.build_minutes_segments([]) == []


# ===========================================================================
# meetings_pipeline: cancel registry.
# ===========================================================================
def test_cancel_registry_lifecycle():
    mid = str(uuid.uuid4())
    assert pipeline.request_cancel(mid) is False  # nothing registered
    ev = pipeline._register_cancel_event(mid)
    assert ev.is_set() is False
    # _check_cancel does nothing while unset.
    pipeline._check_cancel(ev)
    assert pipeline.request_cancel(mid) is True
    assert ev.is_set() is True
    with pytest.raises(pipeline._CancelledByUser):
        pipeline._check_cancel(ev)
    pipeline._unregister_cancel_event(mid)
    assert pipeline.request_cancel(mid) is False


# ===========================================================================
# meetings_pipeline: apply_speaker_names.
# ===========================================================================
def test_apply_speaker_names_empty_mapping(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        meeting = MeetingModel.find_by_id(mid)
        assert pipeline.apply_speaker_names(meeting, None) == 0
        assert pipeline.apply_speaker_names(meeting, []) == 0


def test_apply_speaker_names_no_meeting_id():
    assert pipeline.apply_speaker_names({"speakers": []}, [{"speaker_id": "s0", "display_name": "A"}]) == 0


def test_apply_speaker_names_applies_new(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        meeting = MeetingModel.find_by_id(mid)
        applied = pipeline.apply_speaker_names(meeting, [
            {"speaker_id": "s0", "display_name": "Alice"},
            {"speaker_id": "s1", "display_name": ""},   # blank name -> skipped
            {"speaker_id": "", "display_name": "Bob"},  # blank id -> skipped
            None,                                        # None entry -> skipped
        ])
        assert applied == 1
        row = MeetingModel.find_by_id(mid)
    assert any(s["speaker_id"] == "s0" and s["display_name"] == "Alice"
               for s in row["speakers"])


def test_apply_speaker_names_manual_edit_wins(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"],
                      speakers=[{"speaker_id": "s0", "display_name": "Manual"}])
    with flask_core.app_context():
        meeting = MeetingModel.find_by_id(mid)
        applied = pipeline.apply_speaker_names(meeting, [
            {"speaker_id": "s0", "display_name": "LLMName"},
        ])
        assert applied == 0  # manual edit preserved
        row = MeetingModel.find_by_id(mid)
    assert row["speakers"][0]["display_name"] == "Manual"


def test_apply_speaker_names_with_series_pushes_memory(flask_core, test_user, monkeypatch):
    sid = _mk_series(flask_core, test_user["_id"])
    mid = _mk_meeting(flask_core, test_user["_id"], series_id=sid)
    calls = {"upsert": [], "suggest": []}
    monkeypatch.setattr(pipeline.meeting_glossary, "upsert_speaker_name",
                        lambda s, n: calls["upsert"].append((s, n)))
    monkeypatch.setattr(pipeline.meeting_glossary, "add_suggested_terms",
                        lambda s, names: calls["suggest"].append((s, list(names))))
    with flask_core.app_context():
        meeting = MeetingModel.find_by_id(mid)
        applied = pipeline.apply_speaker_names(meeting, [
            {"speaker_id": "s0", "display_name": "Carol"},
        ])
    assert applied == 1
    assert calls["upsert"] == [(sid, "Carol")]
    assert calls["suggest"] == [(sid, ["Carol"])]


def test_apply_speaker_names_series_memory_errors_swallowed(flask_core, test_user, monkeypatch):
    sid = _mk_series(flask_core, test_user["_id"])
    mid = _mk_meeting(flask_core, test_user["_id"], series_id=sid)

    def _boom(*a, **k):
        raise RuntimeError("memory down")

    monkeypatch.setattr(pipeline.meeting_glossary, "upsert_speaker_name", _boom)
    monkeypatch.setattr(pipeline.meeting_glossary, "add_suggested_terms", _boom)
    with flask_core.app_context():
        meeting = MeetingModel.find_by_id(mid)
        # Defensive try/except — applied still counts despite memory failures.
        assert pipeline.apply_speaker_names(meeting, [
            {"speaker_id": "s0", "display_name": "Dan"},
        ]) == 1


# ===========================================================================
# meetings_pipeline: _load_meeting_context / _build_summary_context.
# ===========================================================================
def test_load_meeting_context_no_series(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"], audio_path="/x/y.webm")
    with flask_core.app_context():
        meeting = MeetingModel.find_by_id(mid)
        ctx = pipeline._load_meeting_context(meeting)
    assert ctx.audio_path == "/x/y.webm"
    # MeetingModel.create does not persist num_speakers/meeting_brief, so the
    # context picks them up as None — assert the actual stored shape.
    assert ctx.num_speakers is None
    assert ctx.meeting_brief is None
    assert ctx.series_id is None
    assert ctx.email_tone == pipeline.EMAIL_TONE_FORMAL
    assert ctx.keyterms == []
    assert ctx.series_name is None


def test_load_meeting_context_with_series_casual(flask_core, test_user, monkeypatch):
    sid = _mk_series(flask_core, test_user["_id"], name="Eng Sync", email_tone="casual")
    mid = _mk_meeting(flask_core, test_user["_id"], series_id=sid)
    monkeypatch.setattr(pipeline.meeting_glossary, "get_active_keyterms",
                        lambda s: ["Helm", "Istio"])
    with flask_core.app_context():
        meeting = MeetingModel.find_by_id(mid)
        ctx = pipeline._load_meeting_context(meeting)
    assert ctx.series_id == sid
    assert ctx.email_tone == pipeline.EMAIL_TONE_CASUAL
    assert ctx.series_name == "Eng Sync"
    assert ctx.keyterms == ["Helm", "Istio"]


def test_build_summary_context_none_when_empty(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        ctx = pipeline._load_meeting_context(MeetingModel.find_by_id(mid))
    assert pipeline._build_summary_context(ctx) is None


def test_build_summary_context_full(flask_core, test_user, monkeypatch):
    sid = _mk_series(flask_core, test_user["_id"], name="Recurring X")
    mid = _mk_meeting(flask_core, test_user["_id"], series_id=sid)
    monkeypatch.setattr(pipeline.meeting_glossary, "get_active_keyterms", lambda s: [])
    monkeypatch.setattr(pipeline.meeting_glossary, "list_speaker_names",
                        lambda s: ["Ann", "Bob"])
    with flask_core.app_context():
        meeting = MeetingModel.find_by_id(mid)
        # meeting_brief is not persisted by create; inject it on the dict so the
        # brief branch in _load_meeting_context/_build_summary_context executes.
        meeting["meeting_brief"] = "The brief"
        ctx = pipeline._load_meeting_context(meeting)
        out = pipeline._build_summary_context(ctx)
    assert "Recurring series: Recurring X" in out
    assert "Ann, Bob" in out
    assert "The brief" in out


def test_build_summary_context_speaker_names_error(flask_core, test_user, monkeypatch):
    sid = _mk_series(flask_core, test_user["_id"], name="S")
    mid = _mk_meeting(flask_core, test_user["_id"], series_id=sid)
    monkeypatch.setattr(pipeline.meeting_glossary, "get_active_keyterms", lambda s: [])

    def _boom(_s):
        raise RuntimeError("down")

    monkeypatch.setattr(pipeline.meeting_glossary, "list_speaker_names", _boom)
    with flask_core.app_context():
        ctx = pipeline._load_meeting_context(MeetingModel.find_by_id(mid))
        out = pipeline._build_summary_context(ctx)
    # Series name still emitted; speaker-name lookup error swallowed.
    assert out is not None
    assert "Recurring series: S" in out


# ===========================================================================
# meetings_pipeline: _persist_transcript / _persist_summary / _fail.
# ===========================================================================
class _FakeResult:
    def __init__(self, *, plain_text="text", words=None, speaker_ids=None,
                 raw=None, language_code="fas"):
        self.plain_text = plain_text
        self.words = words or []
        self.speaker_ids = speaker_ids or []
        self.raw = raw or {}
        self.language_code = language_code


def test_persist_transcript_appends_new_speakers(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"],
                      speakers=[{"speaker_id": "s0", "display_name": "Existing"}])
    result = _FakeResult(
        plain_text="hi",
        words=_words(("hi", 0.0, 1.0, "s0")),
        speaker_ids=["s0", "s1"],   # s0 exists, s1 new
        language_code="eng",
    )
    with flask_core.app_context():
        ctx = pipeline._load_meeting_context(MeetingModel.find_by_id(mid))
        words = pipeline._persist_transcript(mid, result, ctx)
        row = MeetingModel.find_by_id(mid)
        transcript = MeetingTranscriptModel.find_by_meeting(mid)
    assert len(words) == 1
    ids = {s["speaker_id"] for s in row["speakers"]}
    assert ids == {"s0", "s1"}
    # Existing manual name preserved.
    assert any(s["speaker_id"] == "s0" and s["display_name"] == "Existing"
               for s in row["speakers"])
    assert row["language"] == "eng"
    assert transcript["plain_text"] == "hi"


def test_persist_transcript_no_new_speakers(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    result = _FakeResult(plain_text="x", words=[], speaker_ids=[], language_code=None)
    with flask_core.app_context():
        ctx = pipeline._load_meeting_context(MeetingModel.find_by_id(mid))
        words = pipeline._persist_transcript(mid, result, ctx)
        row = MeetingModel.find_by_id(mid)
    assert words == []
    assert row["speakers"] == []


def test_persist_summary_marks_done(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"], status="summarizing")
    data = dict(_SUMMARY_DATA)
    data["minutes"] = [{"speaker_id": "s0", "text": "x", "start_s": 0, "end_s": 1}]
    with flask_core.app_context():
        sid = pipeline._persist_summary(mid, data, email_tone="formal")
        row = MeetingModel.find_by_id(mid)
        summary = MeetingSummaryModel.find_latest_for_meeting(mid)
    assert sid
    assert row["status"] == "done"
    assert summary["exec_summary"] == "We shipped."
    # _persist_summary maps email_draft.body -> the email_draft column. There is
    # no email_subject column on meeting_summaries, so it is dropped on create.
    assert summary["email_draft"] == "Hello team,"
    assert "email_subject" not in summary


def test_persist_summary_invalid_tone_nulled(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"], status="summarizing")
    data = dict(_SUMMARY_DATA)
    with flask_core.app_context():
        pipeline._persist_summary(mid, data, email_tone="weird")
        summary = MeetingSummaryModel.find_latest_for_meeting(mid)
    assert summary["email_tone"] is None


def test_fail_records_error(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        pipeline._fail(mid, "kaboom")
        row = MeetingModel.find_by_id(mid)
    assert row["status"] == "failed"
    assert row["error_message"] == "kaboom"


def test_fail_swallows_bad_meeting_id(flask_core):
    # set_status raises ValueError on bad uuid -> swallowed by _fail's except.
    with flask_core.app_context():
        pipeline._fail("not-a-uuid", "err")  # must not raise


# ===========================================================================
# meetings_pipeline: _scan_dlp.
# ===========================================================================
def test_scan_dlp_noop_empty_text(flask_core, test_user):
    with flask_core.app_context():
        # No text -> early return, no exception.
        pipeline._scan_dlp(meeting_id="m", owner_id=test_user["_id"], text="",
                           phase="transcript")
        # No owner -> early return.
        pipeline._scan_dlp(meeting_id="m", owner_id=None, text="hi", phase="transcript")


def test_scan_dlp_workspace_none_short_circuits(flask_core, test_user):
    # owner present + text present, but meetings pass workspace_id=None so the
    # real gate() short-circuits server-side -> no LLM, no exception.
    with flask_core.app_context():
        pipeline._scan_dlp(meeting_id="m", owner_id=test_user["_id"],
                           text="some sensitive looking text", phase="transcript",
                           artifact="exec_summary")


def test_scan_dlp_block_raises_dlpblocked(flask_core, test_user, monkeypatch):
    def _raise_gate(**kwargs):
        raise DLPBlockedError(
            code="dlp_blocked",
            matches=[{"rule_name": "SSN"}, {"rule_id": "card"}],
        )

    monkeypatch.setattr(pipeline, "dlp_gate", _raise_gate)
    with flask_core.app_context():
        with pytest.raises(pipeline._DLPBlocked) as ei:
            pipeline._scan_dlp(meeting_id="m", owner_id=test_user["_id"],
                               text="leak", phase="summary_input", artifact="qa")
    msg = ei.value.message
    assert "Content Safety (qa)" in msg
    assert "SSN" in msg


def test_scan_dlp_block_uses_code_when_no_rule_names(flask_core, test_user, monkeypatch):
    def _raise_gate(**kwargs):
        raise DLPBlockedError(code="dlp_blocked", matches=[{}])

    monkeypatch.setattr(pipeline, "dlp_gate", _raise_gate)
    with flask_core.app_context():
        with pytest.raises(pipeline._DLPBlocked) as ei:
            pipeline._scan_dlp(meeting_id="m", owner_id=test_user["_id"],
                               text="leak", phase="transcript")
    # No artifact -> scope is the phase; rule names resolve to '?'.
    assert "Content Safety (transcript)" in ei.value.message


# ===========================================================================
# meetings_pipeline: run_pipeline.
# ===========================================================================
def _patch_summarize(monkeypatch, data=None, raise_exc=None):
    def _fake(prompt, *, user_id, context, email_tone):
        if raise_exc is not None:
            raise raise_exc
        return dict(data if data is not None else _SUMMARY_DATA)

    monkeypatch.setattr(pipeline.summary_service, "summarize", _fake)


def _patch_transcribe(monkeypatch, result=None, raise_exc=None):
    def _fake(audio_path, *, num_speakers=None, keyterms=None):
        if raise_exc is not None:
            raise raise_exc
        return result

    monkeypatch.setattr(pipeline.transcription_service, "transcribe", _fake)


def test_run_pipeline_not_found(flask_core):
    with db.session_scope():
        # Returns silently — no exception.
        pipeline.run_pipeline(str(uuid.uuid4()))


def test_run_pipeline_already_done(flask_core, test_user, monkeypatch):
    mid = _mk_meeting(flask_core, test_user["_id"], status="done")
    # transcribe must NOT be called; make it explode if it is.
    _patch_transcribe(monkeypatch, raise_exc=AssertionError("should not transcribe"))
    with db.session_scope():
        pipeline.run_pipeline(mid)
    assert _meeting_status(flask_core, mid) == "done"


def test_run_pipeline_happy(flask_core, test_user, monkeypatch):
    mid = _mk_meeting(flask_core, test_user["_id"])
    result = _FakeResult(
        plain_text="diarized text",
        words=_words(("Hello", 0.0, 1.0, "s0"), ("Hi", 1.2, 2.0, "s1")),
        speaker_ids=["s0", "s1"],
        language_code="fas",
    )
    _patch_transcribe(monkeypatch, result=result)
    _patch_summarize(monkeypatch)
    with db.session_scope():
        pipeline.run_pipeline(mid)
    assert _meeting_status(flask_core, mid) == "done"
    with flask_core.app_context():
        summary = MeetingSummaryModel.find_latest_for_meeting(mid)
        transcript = MeetingTranscriptModel.find_by_meeting(mid)
    assert summary is not None
    assert summary["exec_summary"] == "We shipped."
    # minutes built server-side from words.
    assert len(summary["minutes"]) >= 1
    assert transcript["plain_text"] == "diarized text"


def test_run_pipeline_no_audio_path_fails(flask_core, test_user, monkeypatch):
    mid = _mk_meeting(flask_core, test_user["_id"], audio_path=None)
    _patch_transcribe(monkeypatch, raise_exc=AssertionError("unreached"))
    with db.session_scope():
        pipeline.run_pipeline(mid)
    assert _meeting_status(flask_core, mid) == "failed"
    assert "no audio_path" in (_meeting_error(flask_core, mid) or "")


def test_run_pipeline_empty_words_fails(flask_core, test_user, monkeypatch):
    mid = _mk_meeting(flask_core, test_user["_id"])
    result = _FakeResult(plain_text="", words=[], speaker_ids=[], language_code="fas")
    _patch_transcribe(monkeypatch, result=result)
    _patch_summarize(monkeypatch, raise_exc=AssertionError("should not summarize"))
    with db.session_scope():
        pipeline.run_pipeline(mid)
    assert _meeting_status(flask_core, mid) == "failed"
    assert "words_json is empty" in (_meeting_error(flask_core, mid) or "")


def test_run_pipeline_transcribe_raises_fails(flask_core, test_user, monkeypatch):
    mid = _mk_meeting(flask_core, test_user["_id"])
    _patch_transcribe(monkeypatch, raise_exc=RuntimeError("scribe down"))
    with db.session_scope():
        pipeline.run_pipeline(mid)
    assert _meeting_status(flask_core, mid) == "failed"
    assert "scribe down" in (_meeting_error(flask_core, mid) or "")


def test_run_pipeline_dlp_block_fails(flask_core, test_user, monkeypatch):
    mid = _mk_meeting(flask_core, test_user["_id"])
    result = _FakeResult(
        plain_text="leak",
        words=_words(("x", 0.0, 1.0, "s0")),
        speaker_ids=["s0"],
        language_code="fas",
    )
    _patch_transcribe(monkeypatch, result=result)

    def _raise_gate(**kwargs):
        raise DLPBlockedError(code="dlp_blocked", matches=[{"rule_name": "PII"}])

    monkeypatch.setattr(pipeline, "dlp_gate", _raise_gate)
    with db.session_scope():
        pipeline.run_pipeline(mid)
    assert _meeting_status(flask_core, mid) == "failed"
    err = _meeting_error(flask_core, mid) or ""
    assert "Content Safety" in err and "PII" in err


def test_run_pipeline_cancelled_leaves_status(flask_core, test_user, monkeypatch):
    mid = _mk_meeting(flask_core, test_user["_id"])
    result = _FakeResult(
        plain_text="t", words=_words(("x", 0.0, 1.0, "s0")),
        speaker_ids=["s0"], language_code="fas",
    )

    # Cancel right after transcribe via request_cancel in the fake.
    def _fake_transcribe(audio_path, *, num_speakers=None, keyterms=None):
        pipeline.request_cancel(mid)  # flips the registered event
        return result

    monkeypatch.setattr(pipeline.transcription_service, "transcribe", _fake_transcribe)
    _patch_summarize(monkeypatch, raise_exc=AssertionError("should not summarize"))
    with db.session_scope():
        pipeline.run_pipeline(mid)
    # _CancelledByUser path returns without flipping to failed — status is
    # whatever the last set_status wrote (TRANSCRIBING).
    assert _meeting_status(flask_core, mid) == "transcribing"


# ===========================================================================
# meetings_pipeline: regenerate_summary.
# ===========================================================================
def test_regenerate_not_found_raises(flask_core):
    with db.session_scope():
        with pytest.raises(RuntimeError, match="not found"):
            pipeline.regenerate_summary(str(uuid.uuid4()))


def test_regenerate_no_transcript_raises(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"], status="done")
    with db.session_scope():
        with pytest.raises(RuntimeError, match="no transcript"):
            pipeline.regenerate_summary(mid)


def test_regenerate_no_words_raises(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"], status="done")
    _mk_transcript(flask_core, mid, words=[])
    with db.session_scope():
        with pytest.raises(RuntimeError, match="no words"):
            pipeline.regenerate_summary(mid)


def test_regenerate_happy(flask_core, test_user, monkeypatch):
    mid = _mk_meeting(flask_core, test_user["_id"], status="done")
    _mk_transcript(flask_core, mid, words=_words(("Hi", 0.0, 1.0, "s0")))
    _patch_summarize(monkeypatch)
    with db.session_scope():
        new_id = pipeline.regenerate_summary(mid)
    assert new_id
    assert _meeting_status(flask_core, mid) == "done"
    with flask_core.app_context():
        summary = MeetingSummaryModel.find_latest_for_meeting(mid)
    assert summary["exec_summary"] == "We shipped."


def test_regenerate_dlp_block_returns_empty(flask_core, test_user, monkeypatch):
    mid = _mk_meeting(flask_core, test_user["_id"], status="done")
    _mk_transcript(flask_core, mid, words=_words(("leak", 0.0, 1.0, "s0")))

    def _raise_gate(**kwargs):
        raise DLPBlockedError(code="dlp_blocked", matches=[{"rule_name": "Secret"}])

    monkeypatch.setattr(pipeline, "dlp_gate", _raise_gate)
    with db.session_scope():
        out = pipeline.regenerate_summary(mid)
    assert out == ""
    assert _meeting_status(flask_core, mid) == "failed"
    assert "Content Safety" in (_meeting_error(flask_core, mid) or "")


def test_regenerate_cancelled_returns_empty(flask_core, test_user, monkeypatch):
    mid = _mk_meeting(flask_core, test_user["_id"], status="done")
    _mk_transcript(flask_core, mid, words=_words(("Hi", 0.0, 1.0, "s0")))

    def _fake_summarize(prompt, *, user_id, context, email_tone):
        pipeline.request_cancel(mid)
        pipeline._check_cancel(pipeline._cancel_events[mid])
        return dict(_SUMMARY_DATA)

    monkeypatch.setattr(pipeline.summary_service, "summarize", _fake_summarize)
    with db.session_scope():
        out = pipeline.regenerate_summary(mid)
    assert out == ""


def test_regenerate_summarize_error_reraises(flask_core, test_user, monkeypatch):
    mid = _mk_meeting(flask_core, test_user["_id"], status="done")
    _mk_transcript(flask_core, mid, words=_words(("Hi", 0.0, 1.0, "s0")))
    _patch_summarize(monkeypatch, raise_exc=RuntimeError("LLM exploded"))
    with db.session_scope():
        with pytest.raises(RuntimeError, match="LLM exploded"):
            pipeline.regenerate_summary(mid)
    assert _meeting_status(flask_core, mid) == "failed"


# ===========================================================================
# meetings_pipeline: concurrency semaphore (MEETING_PIPELINE_CONCURRENCY).
#
# The heavy body (transcribe + summarize) acquires a shared
# BoundedSemaphore(MEETING_PIPELINE_CONCURRENCY) BEFORE the transcribe phase and
# releases in finally. Extra uploads queue on the permit instead of fanning out
# N concurrent external-API runs.
# ===========================================================================
def test_pipeline_third_run_waits_on_semaphore(flask_core, test_user, monkeypatch):
    """With concurrency=2, two runs hold both permits and a 3rd blocks until one
    releases — proving the heavy body is gated, not run N-wide.
    """
    # Pin the module semaphore to a 2-permit pool for this test, restore after.
    sem = threading.BoundedSemaphore(2)
    monkeypatch.setattr(pipeline, "_pipeline_semaphore", sem)

    # Gate inside transcribe so a started run parks while holding its permit.
    in_transcribe = threading.Semaphore(0)   # +1 each time a run enters transcribe
    release_transcribe = threading.Event()   # held runs block until this is set

    def _blocking_transcribe(audio_path, *, num_speakers=None, keyterms=None):
        in_transcribe.release()              # signal "a permit was acquired + body entered"
        release_transcribe.wait(timeout=5)
        return _FakeResult(
            plain_text="t", words=_words(("x", 0.0, 1.0, "s0")),
            speaker_ids=["s0"], language_code="fas",
        )

    monkeypatch.setattr(pipeline.transcription_service, "transcribe", _blocking_transcribe)
    _patch_summarize(monkeypatch)

    ids = [_mk_meeting(flask_core, test_user["_id"]) for _ in range(3)]

    def _run(mid):
        with db.session_scope():
            pipeline.run_pipeline(mid)

    threads = [threading.Thread(target=_run, args=(mid,), daemon=True) for mid in ids]
    try:
        for th in threads:
            th.start()

        # Exactly two runs should enter transcribe (both permits taken); the
        # third must be parked on the semaphore acquire and NOT in transcribe.
        assert in_transcribe.acquire(timeout=3), "first run never entered transcribe"
        assert in_transcribe.acquire(timeout=3), "second run never entered transcribe"
        assert not in_transcribe.acquire(timeout=1), "third run entered transcribe before a permit freed"

        # Both permits are held -> a non-blocking acquire fails.
        assert sem.acquire(blocking=False) is False
    finally:
        # Let the two in-flight runs finish, freeing permits for the third.
        release_transcribe.set()
        for th in threads:
            th.join(timeout=10)

    # The third run eventually entered transcribe once a permit freed.
    assert in_transcribe.acquire(timeout=3), "third run never entered transcribe after release"

    # All permits returned to the pool: drain both back out (proving >=2 were
    # available), confirm none beyond that, then restore to full and trip the
    # BoundedSemaphore over-release guard — a clean ValueError on the 3rd release
    # proves EXACTLY 2 permits exist (balanced acquire/release in the source).
    assert sem.acquire(blocking=False) is True
    assert sem.acquire(blocking=False) is True
    assert sem.acquire(blocking=False) is False  # nothing leaked beyond 2
    sem.release()
    sem.release()
    with pytest.raises(ValueError):
        sem.release()  # over-release guard — confirms exactly 2 permits exist

    for mid in ids:
        assert _meeting_status(flask_core, mid) == "done"


def test_pipeline_cancelled_while_queued_does_no_work_and_holds_no_permit(
    flask_core, test_user, monkeypatch
):
    """A meeting cancelled WHILE queued (no free permit) must bail without
    transcribing/summarizing and must never hold a permit.
    """
    # 1-permit pool, fully drained so any new run is forced to queue.
    sem = threading.BoundedSemaphore(1)
    assert sem.acquire(blocking=False) is True  # drain: 0 permits left
    monkeypatch.setattr(pipeline, "_pipeline_semaphore", sem)

    # Poll fast so the queued loop spins a few times before we observe it.
    monkeypatch.setattr(pipeline, "_ACQUIRE_POLL_S", 0.01)

    transcribe_calls = []
    summarize_calls = []
    monkeypatch.setattr(
        pipeline.transcription_service, "transcribe",
        lambda *a, **k: transcribe_calls.append(1),
    )
    monkeypatch.setattr(
        pipeline.summary_service, "summarize",
        lambda *a, **k: summarize_calls.append(1),
    )

    mid = _mk_meeting(flask_core, test_user["_id"])

    # run_pipeline registers its OWN cancel event at entry (overwriting any the
    # test pre-registers), so we trip cancellation by handing it an ALREADY-SET
    # event: its first _check_cancel in the permit-acquire loop then raises
    # _CancelledByUser before ever taking the (drained) permit.
    real_register = pipeline._register_cancel_event

    def _register_already_cancelled(meeting_id):
        ev = real_register(meeting_id)
        ev.set()
        return ev

    monkeypatch.setattr(pipeline, "_register_cancel_event", _register_already_cancelled)

    with db.session_scope():
        pipeline.run_pipeline(mid)  # _CancelledByUser swallowed internally

    # No external work happened.
    assert transcribe_calls == []
    assert summarize_calls == []
    # Status untouched (still the pre-transcription UPLOADED) — the run bailed
    # before flipping to TRANSCRIBING.
    assert _meeting_status(flask_core, mid) == "uploaded"
    # The cancelled-while-queued run never took the (already drained) permit:
    # the pool is still empty, so a non-blocking acquire fails.
    assert sem.acquire(blocking=False) is False
    # Restore the one permit we drained for the test.
    sem.release()
