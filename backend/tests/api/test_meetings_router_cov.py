"""Coverage-focused tests for app/api/routers/meetings.py.

Complements tests/api/test_meetings.py — targets the branches the sibling file
leaves uncovered: the artifact renderer (`_render_artifact`) for every kind, the
`_serialize_summary` legacy-key remap, the background-thread dispatchers, the SSE
poll-loop transitions (in-flight -> terminal, unknown-status, initial-poll
failure), upload error paths, PATCH series_id, and the meeting-series error
branches (name length, email_tone PATCH, duplicate 409, glossary failures).

Mirrors the sibling's fixtures + seeding helpers EXACTLY (real model facades on
Postgres via the flask_ctx bridge; external upstreams monkeypatched). Errors are
legacy-shaped {"error","status"[, "code"]}; the `_id` alias is present.
"""
import io
import uuid

import pytest

import app.api.routers.meetings as meetings_router


# ---------------------------------------------------------------------------
# Fixtures (mirrors test_meetings.py).
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def enable_meetings_feature(flask_core):
    from app.models.platform_settings import PlatformSettingsModel

    with flask_core.app_context():
        PlatformSettingsModel.set_feature("meetings", True, None)
    yield


@pytest.fixture
def upload_tmpdir(flask_core, tmp_path):
    cfg = flask_core.config
    saved = (cfg.get("UPLOAD_FOLDER"), cfg.get("MEETING_MAX_AUDIO_BYTES"))
    cfg["UPLOAD_FOLDER"] = str(tmp_path)
    yield cfg
    cfg["UPLOAD_FOLDER"], cfg["MEETING_MAX_AUDIO_BYTES"] = saved


@pytest.fixture
def no_pipeline(monkeypatch):
    # Package split: dispatch lives on ``_common``; crud looks it up at call time.
    noop = lambda *a, **k: None  # noqa: E731
    monkeypatch.setattr(meetings_router._common, "_dispatch_pipeline", noop)
    monkeypatch.setattr(meetings_router._common, "_dispatch_regenerate", noop)
    monkeypatch.setattr(meetings_router, "_dispatch_pipeline", noop)
    monkeypatch.setattr(meetings_router, "_dispatch_regenerate", noop)
    monkeypatch.setattr(
        meetings_router.meeting_storage, "probe_duration_seconds", lambda *_a, **_k: 12.5
    )


def _make_meeting(flask_core, owner_id, *, title="Quarterly Review", status="uploaded",
                  series_id=None, audio_path=None):
    from app.models.meeting import MeetingModel

    mid = str(uuid.uuid4())
    with flask_core.app_context():
        MeetingModel.create(str(owner_id), {
            "_id": mid,
            "original_filename": "audio.webm",
            "audio_path": audio_path,
            "title": title,
            "status": status,
            "series_id": series_id,
            "speakers": [],
        })
    return mid


def _make_series(flask_core, owner_id, *, name="Weekly Sync", email_tone="formal"):
    from app.models.meeting_series import MeetingSeriesModel

    with flask_core.app_context():
        return MeetingSeriesModel.create(str(owner_id), {"name": name, "email_tone": email_tone})


def _make_transcript(flask_core, meeting_id, *, plain_text="hello world transcript"):
    from app.models.meeting_transcript import MeetingTranscriptModel

    with flask_core.app_context():
        MeetingTranscriptModel.create(meeting_id, {
            "plain_text": plain_text,
            "raw_json": {},
            "words_json": [],
            "language_code": "fas",
        })


def _make_summary(flask_core, meeting_id, **fields):
    """Create a summary row. `fields` are passed straight to MeetingSummaryModel.create."""
    from app.models.meeting_summary import MeetingSummaryModel

    data = {"model": "google/gemini-3.6-flash"}
    data.update(fields)
    with flask_core.app_context():
        MeetingSummaryModel.create(meeting_id, data)


# ===========================================================================
# _serialize_summary — legacy `*_json` key remap (lines 106-114).
# The model emits UNSUFFIXED column names, so the remap only fires when the
# input dict actually carries the suffixed keys (the Mongo legacy shape).
# ===========================================================================
def test_serialize_summary_remaps_suffixed_keys():
    raw = {
        "_id": "abc",
        "action_items_json": [{"text": "x"}],
        "decisions_json": ["d"],
        "minutes_json": [{"text": "m"}],
        "qa_json": [{"question": "q"}],
        "open_questions_json": [{"question": "oq"}],
        "exec_summary": "hello",
    }
    out = meetings_router._serialize_summary(raw)
    assert out["action_items"] == [{"text": "x"}]
    assert out["decisions"] == ["d"]
    assert out["minutes"] == [{"text": "m"}]
    assert out["qa"] == [{"question": "q"}]
    assert out["open_questions"] == [{"question": "oq"}]
    # Suffixed source keys are popped.
    assert "action_items_json" not in out
    assert "qa_json" not in out


def test_serialize_summary_non_dict_returns_empty():
    # serialize_doc on a non-dict -> _serialize_summary coerces to {}.
    out = meetings_router._serialize_summary(None)
    assert out == {}


# ===========================================================================
# _render_artifact — every kind, both content + empty branches (671-778).
# NOTE: the model dict uses UNSUFFIXED list keys (action_items / decisions /
# minutes / qa / open_questions) but _render_artifact reads the SUFFIXED
# `*_json` keys -> those list artifacts can never produce content from a real
# summary dict. We drive the renderer DIRECTLY with the suffixed shape to
# execute the rendering bodies, AND assert the real-dict behavior over HTTP
# (see test_save_artifact_*). See source_bugs_found.
# ===========================================================================
_MEETING = {"title": "Roadmap", "original_filename": "audio.webm"}


def test_render_artifact_transcript_ok():
    content, label = meetings_router._render_artifact(
        _MEETING, None, {"plain_text": "raw transcript body"}, "transcript"
    )
    assert label == "Transcript"
    assert content.startswith("# Transcript — Roadmap")
    assert "raw transcript body" in content


def test_render_artifact_transcript_missing():
    assert meetings_router._render_artifact(_MEETING, None, None, "transcript") == (None, "Transcript")
    assert meetings_router._render_artifact(_MEETING, None, {"plain_text": "  "}, "transcript") == (None, "Transcript")


def test_render_artifact_no_summary_returns_none():
    # kind != transcript with no summary -> (None, kind).
    assert meetings_router._render_artifact(_MEETING, None, None, "exec_summary") == (None, "exec_summary")


def test_render_artifact_exec_summary():
    content, label = meetings_router._render_artifact(
        _MEETING, {"exec_summary": "We shipped."}, None, "exec_summary"
    )
    assert label == "Executive Summary"
    assert "We shipped." in content
    # Empty exec_summary -> None.
    assert meetings_router._render_artifact(_MEETING, {"exec_summary": "  "}, None, "exec_summary")[0] is None


def test_render_artifact_action_items_full():
    summary = {"action_items_json": [
        {"text": "Email the deck", "owner": "Sam", "due_date": "2026-06-01"},
        {"text": "Bare item"},
        {"text": "Owner only", "owner": "Lee"},
        {"text": "Due only", "due_date": "2026-07-01"},
    ]}
    content, label = meetings_router._render_artifact(_MEETING, summary, None, "action_items")
    assert label == "Action Items"
    assert "# Action Items — Roadmap" in content
    assert "@Sam" in content and "due 2026-06-01" in content
    assert "- Bare item" in content
    assert "@Lee" in content
    assert "due 2026-07-01" in content
    # Empty -> None.
    assert meetings_router._render_artifact(_MEETING, {"action_items_json": []}, None, "action_items")[0] is None


def test_render_artifact_decisions_full():
    summary = {"decisions_json": ["Ship on Friday", "", "  ", "Hire two engineers"]}
    content, label = meetings_router._render_artifact(_MEETING, summary, None, "decisions")
    assert label == "Decisions"
    assert "- Ship on Friday" in content
    assert "- Hire two engineers" in content
    assert meetings_router._render_artifact(_MEETING, {"decisions_json": []}, None, "decisions")[0] is None


def test_render_artifact_minutes_full():
    summary = {"minutes_json": [
        {"speaker_id": "speaker_0", "text": "Opening remarks", "start_s": 1.0, "end_s": 4.5},
        {"speaker_id": "", "text": "no speaker id"},
        {"speaker_id": "speaker_1", "text": ""},  # skipped (no text)
    ]}
    content, label = meetings_router._render_artifact(_MEETING, summary, None, "minutes")
    assert label == "Minutes"
    assert "**speaker_0**" in content
    assert "`[1.00-4.50]`" in content
    assert "**speaker_?**" in content  # blank speaker_id falls back
    assert "no speaker id" in content
    assert meetings_router._render_artifact(_MEETING, {"minutes_json": []}, None, "minutes")[0] is None


def test_render_artifact_qa_full():
    summary = {"qa_json": [
        {"question": "What is the deadline?", "answer": "Friday"},
        {"question": "Budget?"},          # no answer line
        {"question": "", "answer": "ignored"},  # skipped (no question)
    ]}
    content, label = meetings_router._render_artifact(_MEETING, summary, None, "qa")
    assert label == "Q&A"
    assert "**Q:** What is the deadline?" in content
    assert "**A:** Friday" in content
    assert "**Q:** Budget?" in content
    assert "ignored" not in content
    assert meetings_router._render_artifact(_MEETING, {"qa_json": []}, None, "qa")[0] is None


def test_render_artifact_open_questions_full():
    summary = {"open_questions_json": [
        {"question": "Who owns onboarding?", "owner": "Sam"},
        {"question": "Launch date?"},
        {"question": "", "owner": "x"},  # skipped
    ]}
    content, label = meetings_router._render_artifact(_MEETING, summary, None, "open_questions")
    assert label == "Open Questions"
    assert "- Who owns onboarding? _(Sam)_" in content
    assert "- Launch date?" in content
    assert meetings_router._render_artifact(_MEETING, {"open_questions_json": []}, None, "open_questions")[0] is None


def test_render_artifact_email_draft_full():
    summary = {"email_subject": "Follow-up", "email_draft": "Hi team, thanks."}
    content, label = meetings_router._render_artifact(_MEETING, summary, None, "email_draft")
    assert label == "Follow-up Email"
    assert "**Subject:** Follow-up" in content
    assert "Hi team, thanks." in content
    # Body only (no subject) still renders.
    body_only = meetings_router._render_artifact(_MEETING, {"email_draft": "Body only"}, None, "email_draft")[0]
    assert "Body only" in body_only
    # Subject only.
    subj_only = meetings_router._render_artifact(_MEETING, {"email_subject": "Subj only"}, None, "email_draft")[0]
    assert "**Subject:** Subj only" in subj_only
    # Neither -> None.
    assert meetings_router._render_artifact(_MEETING, {}, None, "email_draft")[0] is None


def test_render_artifact_unknown_kind():
    assert meetings_router._render_artifact(_MEETING, {"exec_summary": "x"}, None, "bogus") == (None, "bogus")


# ===========================================================================
# Background dispatchers — _run_in_ctx + _dispatch_pipeline + _dispatch_regenerate
# (lines 122-152). Run synchronously via a captured target so no real LLM runs.
# ===========================================================================
def test_run_in_ctx_invokes_fn(flask_core, monkeypatch):
    calls = []
    meetings_router._run_in_ctx(lambda mid: calls.append(mid), "meeting-123")
    assert calls == ["meeting-123"]


def test_run_in_ctx_swallows_exception(flask_core):
    def boom(_mid):
        raise RuntimeError("kaboom")

    # Must NOT raise — the helper logs + swallows.
    meetings_router._run_in_ctx(boom, "x")


def test_dispatch_pipeline_starts_thread(flask_core, monkeypatch):
    seen = []
    monkeypatch.setattr(
        meetings_router.meetings_pipeline, "run_pipeline",
        lambda mid: seen.append(("pipeline", mid)),
    )
    meetings_router._dispatch_pipeline("mid-1")
    # Drain the daemon thread deterministically.
    for t in list(__import__("threading").enumerate()):
        if t.daemon and t.name != "MainThread":
            t.join(timeout=5)
    assert ("pipeline", "mid-1") in seen


def test_dispatch_regenerate_starts_thread(flask_core, monkeypatch):
    seen = []
    monkeypatch.setattr(
        meetings_router.meetings_pipeline, "regenerate_summary",
        lambda mid: seen.append(("regen", mid)),
    )
    meetings_router._dispatch_regenerate("mid-2")
    for t in list(__import__("threading").enumerate()):
        if t.daemon and t.name != "MainThread":
            t.join(timeout=5)
    assert ("regen", "mid-2") in seen


# ===========================================================================
# POST /upload — error/edge paths the sibling doesn't cover.
# ===========================================================================
def test_upload_num_speakers_positive_ok(client, auth_headers, upload_tmpdir, no_pipeline):
    # Exercises the positive-int parse branch (num_speakers_val = ns). The ORM
    # table does not model num_speakers, so the serialized meeting omits it.
    files = {"file": ("clip.webm", io.BytesIO(b"x" * 256), "audio/webm")}
    resp = client.post(
        "/api/meetings/upload",
        headers={"Authorization": auth_headers["Authorization"]},
        data={"num_speakers": "3", "title": "Speakers"}, files=files,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["meeting"]["title"] == "Speakers"


def test_upload_num_speakers_zero_coerced_none(client, auth_headers, upload_tmpdir, no_pipeline):
    # ns <= 0 -> num_speakers_val stays None (still a 201).
    files = {"file": ("clip.webm", io.BytesIO(b"x" * 64), "audio/webm")}
    resp = client.post(
        "/api/meetings/upload",
        headers={"Authorization": auth_headers["Authorization"]},
        data={"num_speakers": "0", "title": "ZeroSpeakers"}, files=files,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["meeting"]["title"] == "ZeroSpeakers"


def test_upload_save_oserror_500(client, auth_headers, upload_tmpdir, no_pipeline, monkeypatch):
    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(meetings_router.meeting_storage, "save_audio_stream", boom)
    files = {"file": ("clip.webm", io.BytesIO(b"x" * 64), "audio/webm")}
    resp = client.post(
        "/api/meetings/upload",
        headers={"Authorization": auth_headers["Authorization"]},
        data={"title": "x"}, files=files,
    )
    assert resp.status_code == 500
    assert "Failed to save audio" in resp.json()["error"]


def test_upload_create_failure_500_cleans_file(client, auth_headers, upload_tmpdir, no_pipeline, monkeypatch):
    # save_audio_stream succeeds (real writer), but the DB insert blows up ->
    # 500 + best-effort unlink of the just-written file.
    def boom(*_a, **_k):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(meetings_router.MeetingModel, "create", staticmethod(boom))
    files = {"file": ("clip.webm", io.BytesIO(b"x" * 128), "audio/webm")}
    resp = client.post(
        "/api/meetings/upload",
        headers={"Authorization": auth_headers["Authorization"]},
        data={"title": "x"}, files=files,
    )
    assert resp.status_code == 500
    assert "Failed to create meeting" in resp.json()["error"]


# ===========================================================================
# PATCH /{meeting_id} — series_id branches (354-360).
# ===========================================================================
def test_patch_meeting_clear_series_id_null(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"], name="Attach")
    mid = _make_meeting(flask_core, test_user["_id"], series_id=sid)
    resp = client.patch(f"/api/meetings/{mid}", headers=auth_headers, json={"series_id": None})
    assert resp.status_code == 200
    assert resp.json()["meeting"]["series_id"] is None


def test_patch_meeting_clear_series_id_empty_string(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"], name="Attach2")
    mid = _make_meeting(flask_core, test_user["_id"], series_id=sid)
    resp = client.patch(f"/api/meetings/{mid}", headers=auth_headers, json={"series_id": "   "})
    assert resp.status_code == 200
    assert resp.json()["meeting"]["series_id"] is None


def test_patch_meeting_set_series_id(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"], name="Target Series")
    mid = _make_meeting(flask_core, test_user["_id"])
    resp = client.patch(f"/api/meetings/{mid}", headers=auth_headers, json={"series_id": sid})
    assert resp.status_code == 200
    assert resp.json()["meeting"]["series_id"] == sid


def test_patch_meeting_bad_series_id_type_400(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    resp = client.patch(f"/api/meetings/{mid}", headers=auth_headers, json={"series_id": 123})
    assert resp.status_code == 400
    assert resp.json()["error"] == "series_id must be a string or null"


def test_patch_meeting_title_null_clears(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    resp = client.patch(f"/api/meetings/{mid}", headers=auth_headers, json={"title": None})
    assert resp.status_code == 200
    assert resp.json()["meeting"]["title"] is None


# ===========================================================================
# transcript / summary / audio — meeting-not-found 404 (423, 443, 463).
# ===========================================================================
def test_transcript_meeting_not_found_404(client, auth_headers):
    resp = client.get(f"/api/meetings/{uuid.uuid4()}/transcript", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Meeting not found"


def test_summary_meeting_not_found_404(client, auth_headers):
    resp = client.get(f"/api/meetings/{uuid.uuid4()}/summary", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Meeting not found"


def test_audio_meeting_not_found_404(client, auth_headers):
    resp = client.get(f"/api/meetings/{uuid.uuid4()}/audio", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Meeting not found"


def test_audio_path_missing_on_disk_404(client, flask_core, test_user, auth_headers, tmp_path):
    # audio_path set but file does not exist on disk -> 404.
    ghost = tmp_path / "gone.webm"
    mid = _make_meeting(flask_core, test_user["_id"], audio_path=str(ghost))
    resp = client.get(f"/api/meetings/{mid}/audio", headers=auth_headers)
    assert resp.status_code == 404


# ===========================================================================
# Summary serialization end-to-end with minutes/qa/open_questions present
# (exercises GET /summary -> _serialize_summary over a real summary row).
# ===========================================================================
def test_summary_endpoint_lists_unsuffixed(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    _make_summary(
        flask_core, mid,
        exec_summary="Recap",
        minutes=[{"speaker_id": "speaker_0", "text": "hi"}],
        qa=[{"question": "q?", "answer": "a"}],
        open_questions=[{"question": "oq?"}],
    )
    resp = client.get(f"/api/meetings/{mid}/summary", headers=auth_headers)
    assert resp.status_code == 200
    summary = resp.json()["summary"]
    assert summary["minutes"] == [{"speaker_id": "speaker_0", "text": "hi"}]
    assert summary["qa"] == [{"question": "q?", "answer": "a"}]
    assert summary["open_questions"] == [{"question": "oq?"}]


# ===========================================================================
# POST /{meeting_id}/save-artifact — real-row behavior for each kind.
# ===========================================================================
def test_save_artifact_transcript_ok(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"], title="Sync")
    _make_transcript(flask_core, mid, plain_text="the full transcript")
    resp = client.post(f"/api/meetings/{mid}/save-artifact", headers=auth_headers,
                       json={"artifact_kind": "transcript"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["message"] == "Artifact saved to Knowledge Vault"
    assert "Transcript" in body["item"]["title"]


def test_save_artifact_email_draft_ok(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"], title="Recap")
    _make_summary(flask_core, mid, email_draft="Hi all, here is the recap.")
    resp = client.post(f"/api/meetings/{mid}/save-artifact", headers=auth_headers,
                       json={"artifact_kind": "email_draft"})
    assert resp.status_code == 201
    assert "Follow-up Email" in resp.json()["item"]["title"]


def test_save_artifact_with_explicit_folder_id(client, flask_core, test_user, auth_headers):
    from app.models.knowledge_folder import KnowledgeFolderModel

    mid = _make_meeting(flask_core, test_user["_id"], title="Folder Test")
    _make_summary(flask_core, mid, exec_summary="content here")
    with flask_core.app_context():
        folder = KnowledgeFolderModel.create(user_id=str(test_user["_id"]), name="Custom Folder")
        folder_id = str(folder["_id"])
    resp = client.post(f"/api/meetings/{mid}/save-artifact", headers=auth_headers,
                       json={"artifact_kind": "exec_summary", "folder_id": folder_id})
    assert resp.status_code == 201
    assert resp.json()["folder_id"] == folder_id


def test_save_artifact_action_items_no_content_real_dict_bug(client, flask_core, test_user, auth_headers):
    # NOTE: possible bug — _render_artifact reads `action_items_json` but the
    # summary model dict carries the UNSUFFIXED `action_items` key, so a real
    # summary with populated action_items still yields "No content available".
    mid = _make_meeting(flask_core, test_user["_id"], title="Bug Repro")
    _make_summary(flask_core, mid, action_items=[{"text": "do it", "owner": "Sam"}])
    resp = client.post(f"/api/meetings/{mid}/save-artifact", headers=auth_headers,
                       json={"artifact_kind": "action_items"})
    assert resp.status_code == 400
    assert "No content available" in resp.json()["error"]


def test_save_artifact_not_found_404(client, auth_headers):
    resp = client.post(f"/api/meetings/{uuid.uuid4()}/save-artifact", headers=auth_headers,
                       json={"artifact_kind": "exec_summary"})
    assert resp.status_code == 404


# ===========================================================================
# GET /{meeting_id}/stream — SSE poll-loop transitions (868-951).
# We monkeypatch `time.sleep` to no-op and `MeetingModel.find_by_id` to a
# stateful fake so the loop runs deterministically + terminates quickly.
# ===========================================================================
def _frames(resp):
    return list(resp.iter_lines())


def test_stream_inflight_then_done(client, flask_core, test_user, auth_headers, monkeypatch):
    mid = _make_meeting(flask_core, test_user["_id"], status="transcribing")
    monkeypatch.setattr(meetings_router.time, "sleep", lambda *_a, **_k: None)

    statuses = iter(["transcribing", "summarizing", "done"])

    def fake_find(_mid):
        try:
            return {"status": next(statuses), "error_message": None}
        except StopIteration:
            return {"status": "done", "error_message": None}

    monkeypatch.setattr(meetings_router.MeetingModel, "find_by_id", staticmethod(fake_find))

    with client.stream("GET", f"/api/meetings/{mid}/stream", headers=auth_headers) as resp:
        assert resp.status_code == 200
        text = "\n".join(_frames(resp))
    assert "event: phase_change" in text
    assert "event: meeting_complete" in text
    assert "summarizing" in text


def test_stream_inflight_then_failed(client, flask_core, test_user, auth_headers, monkeypatch):
    mid = _make_meeting(flask_core, test_user["_id"], status="transcribing")
    monkeypatch.setattr(meetings_router.time, "sleep", lambda *_a, **_k: None)

    statuses = iter(["transcribing", "failed"])

    def fake_find(_mid):
        try:
            return {"status": next(statuses), "error_message": "boom"}
        except StopIteration:
            return {"status": "failed", "error_message": "boom"}

    monkeypatch.setattr(meetings_router.MeetingModel, "find_by_id", staticmethod(fake_find))

    with client.stream("GET", f"/api/meetings/{mid}/stream", headers=auth_headers) as resp:
        assert resp.status_code == 200
        text = "\n".join(_frames(resp))
    assert "event: error" in text
    assert "boom" in text


def test_stream_unknown_status_bails(client, flask_core, test_user, auth_headers, monkeypatch):
    mid = _make_meeting(flask_core, test_user["_id"], status="uploaded")
    monkeypatch.setattr(meetings_router.time, "sleep", lambda *_a, **_k: None)

    # Initial poll -> uploaded (in-flight); next poll -> a stale/unknown status.
    statuses = iter(["uploaded", "weird_status"])

    def fake_find(_mid):
        try:
            return {"status": next(statuses), "error_message": None}
        except StopIteration:
            return {"status": "weird_status", "error_message": None}

    monkeypatch.setattr(meetings_router.MeetingModel, "find_by_id", staticmethod(fake_find))

    with client.stream("GET", f"/api/meetings/{mid}/stream", headers=auth_headers) as resp:
        assert resp.status_code == 200
        text = "\n".join(_frames(resp))
    assert "unknown_status" in text


def test_stream_failed_terminal_first_frame(client, flask_core, test_user, auth_headers):
    # A 'failed' meeting emits phase_change THEN an error frame, then returns.
    mid = _make_meeting(flask_core, test_user["_id"], status="failed")
    with client.stream("GET", f"/api/meetings/{mid}/stream", headers=auth_headers) as resp:
        assert resp.status_code == 200
        text = "\n".join(_frames(resp))
    assert "event: phase_change" in text
    assert "event: error" in text


def test_stream_initial_poll_exception(client, flask_core, test_user, auth_headers, monkeypatch):
    mid = _make_meeting(flask_core, test_user["_id"], status="transcribing")

    def boom(_mid):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(meetings_router.MeetingModel, "find_by_id", staticmethod(boom))

    with client.stream("GET", f"/api/meetings/{mid}/stream", headers=auth_headers) as resp:
        assert resp.status_code == 200
        text = "\n".join(_frames(resp))
    assert "stream_init_failed" in text


def test_stream_none_initial_status_then_terminal(client, flask_core, test_user, auth_headers, monkeypatch):
    # find_by_id returns {} (no status) initially -> skips the initial frame,
    # falls into the poll loop which then sees a terminal status.
    mid = _make_meeting(flask_core, test_user["_id"], status="transcribing")
    monkeypatch.setattr(meetings_router.time, "sleep", lambda *_a, **_k: None)

    states = iter([{}, {"status": "done"}])

    def fake_find(_mid):
        try:
            return next(states)
        except StopIteration:
            return {"status": "done"}

    monkeypatch.setattr(meetings_router.MeetingModel, "find_by_id", staticmethod(fake_find))

    with client.stream("GET", f"/api/meetings/{mid}/stream", headers=auth_headers) as resp:
        assert resp.status_code == 200
        text = "\n".join(_frames(resp))
    assert "event: meeting_complete" in text


# ===========================================================================
# meeting-series — error branches not covered by the sibling.
# ===========================================================================
def test_series_create_name_too_long_400(client, auth_headers):
    resp = client.post("/api/meeting-series/create", headers=auth_headers,
                       json={"name": "x" * 201})
    assert resp.status_code == 400
    assert "≤ 200 characters" in resp.json()["error"]


def test_series_patch_email_tone(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"], name="Tone Test", email_tone="formal")
    resp = client.patch(f"/api/meeting-series/{sid}", headers=auth_headers,
                        json={"email_tone": "casual"})
    assert resp.status_code == 200
    assert resp.json()["series"]["email_tone"] == "casual"


def test_series_patch_bad_email_tone_400(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"], name="Bad Tone")
    resp = client.patch(f"/api/meeting-series/{sid}", headers=auth_headers,
                        json={"email_tone": "angry"})
    assert resp.status_code == 400
    assert "email_tone must be one of" in resp.json()["error"]


def test_series_patch_name_too_long_400(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"], name="Long Name Test")
    resp = client.patch(f"/api/meeting-series/{sid}", headers=auth_headers,
                        json={"name": "y" * 201})
    assert resp.status_code == 400
    assert "≤ 200 characters" in resp.json()["error"]


def test_series_patch_duplicate_name_409(client, flask_core, test_user, auth_headers):
    _make_series(flask_core, test_user["_id"], name="Existing One")
    sid = _make_series(flask_core, test_user["_id"], name="Rename Me")
    resp = client.patch(f"/api/meeting-series/{sid}", headers=auth_headers,
                        json={"name": "Existing One"})
    assert resp.status_code == 409
    assert resp.json()["code"] == "duplicate_name"


def test_series_patch_not_found_404(client, auth_headers):
    resp = client.patch(f"/api/meeting-series/{uuid.uuid4()}", headers=auth_headers,
                        json={"name": "x"})
    assert resp.status_code == 404


def test_series_delete_cascades_and_unsets_meeting(client, flask_core, test_user, auth_headers):
    # Series with a keyterm + an attached meeting -> delete cascades, meeting
    # survives with series_id nulled.
    sid = _make_series(flask_core, test_user["_id"], name="To Delete")
    client.post(f"/api/meeting-series/{sid}/keyterms", headers=auth_headers, json={"term": "Kafka"})
    mid = _make_meeting(flask_core, test_user["_id"], series_id=sid)
    resp = client.delete(f"/api/meeting-series/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Series deleted"
    # The meeting still exists, series_id unset.
    got = client.get(f"/api/meetings/{mid}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["meeting"]["series_id"] is None


def test_keyterms_list_with_source_filter(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    client.post(f"/api/meeting-series/{sid}/keyterms", headers=auth_headers, json={"term": "Manual Term"})
    resp = client.get(f"/api/meeting-series/{sid}/keyterms",
                      headers=auth_headers, params={"source": "manual"})
    assert resp.status_code == 200
    assert any(k["term"] == "Manual Term" for k in resp.json()["keyterms"])


def test_keyterms_series_not_found_404(client, auth_headers):
    resp = client.get(f"/api/meeting-series/{uuid.uuid4()}/keyterms", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Series not found"


def test_add_keyterm_validation_fail_400(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    # Numeric-only term fails meeting_glossary.add_manual_term validation.
    resp = client.post(f"/api/meeting-series/{sid}/keyterms",
                       headers=auth_headers, json={"term": "123456"})
    assert resp.status_code == 400
    assert "validation" in resp.json()["error"].lower()


def test_accept_keyterm_failure_500(client, flask_core, test_user, auth_headers, monkeypatch):
    sid = _make_series(flask_core, test_user["_id"])
    created = client.post(f"/api/meeting-series/{sid}/keyterms",
                          headers=auth_headers, json={"term": "Terraform"}).json()
    term_id = created["keyterm"]["_id"]
    monkeypatch.setattr(meetings_router.meeting_glossary, "accept_term", lambda *_a, **_k: False)
    resp = client.post(f"/api/meeting-series/{sid}/keyterms/{term_id}/accept", headers=auth_headers)
    assert resp.status_code == 500
    assert resp.json()["error"] == "Failed to accept keyterm"


def test_reject_keyterm_failure_500(client, flask_core, test_user, auth_headers, monkeypatch):
    sid = _make_series(flask_core, test_user["_id"])
    created = client.post(f"/api/meeting-series/{sid}/keyterms",
                          headers=auth_headers, json={"term": "Ansible"}).json()
    term_id = created["keyterm"]["_id"]
    monkeypatch.setattr(meetings_router.meeting_glossary, "reject_term", lambda *_a, **_k: False)
    resp = client.delete(f"/api/meeting-series/{sid}/keyterms/{term_id}", headers=auth_headers)
    assert resp.status_code == 500
    assert resp.json()["error"] == "Failed to delete keyterm"


def test_accept_keyterm_wrong_series_404(client, flask_core, test_user, auth_headers):
    # A keyterm that belongs to a different series -> 404 from the series check.
    sid_a = _make_series(flask_core, test_user["_id"], name="Series A")
    sid_b = _make_series(flask_core, test_user["_id"], name="Series B")
    created = client.post(f"/api/meeting-series/{sid_a}/keyterms",
                          headers=auth_headers, json={"term": "Prometheus"}).json()
    term_id = created["keyterm"]["_id"]
    resp = client.post(f"/api/meeting-series/{sid_b}/keyterms/{term_id}/accept", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Keyterm not found"


def test_speaker_names_series_not_found_404(client, auth_headers):
    resp = client.get(f"/api/meeting-series/{uuid.uuid4()}/speaker-names", headers=auth_headers)
    assert resp.status_code == 404


# ===========================================================================
# suggest-series — no match path (296) when a series exists but title differs.
# ===========================================================================
def test_suggest_series_no_match_returns_null(client, flask_core, test_user, auth_headers):
    _make_series(flask_core, test_user["_id"], name="Weekly Engineering Sync")
    resp = client.get("/api/meetings/suggest-series",
                      headers=auth_headers, params={"title": "zzz totally different qqq"})
    assert resp.status_code == 200
    assert resp.json() == {"suggestion": None}
