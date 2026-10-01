"""Integration tests for the meetings + meeting-series FastAPI routers.

Mirrors tests/api/test_auth.py: real model facades on Postgres via the
flask_ctx bridge, legacy-shaped JSON assertions (``_id`` alias). External
upstreams (the transcription/summary pipeline, ffprobe duration probe) are
monkeypatched so nothing hits OpenRouter / ElevenLabs / a real audio file —
the upload route's disk writer (``save_audio_stream``) is exercised for real
against a tmp UPLOAD_FOLDER, including the 413 cap.

Every meetings route is gated behind the ``meetings`` platform feature flag
(OFF by default) — the autouse ``enable_meetings_feature`` fixture flips it on
so the routes are reachable; ``test_feature_flag_off_404`` proves the gate.
"""
import io
import uuid

import pytest

import app.api.routers.meetings as meetings_router


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def enable_meetings_feature(flask_core):
    """Flip the ``meetings`` platform feature flag ON for every test.

    The flag is False in DEFAULT_FEATURES; the per-test truncate wipes
    platform_settings, so we re-enable inside an app_context each test.
    """
    from app.models.platform_settings import PlatformSettingsModel

    with flask_core.app_context():
        PlatformSettingsModel.set_feature("meetings", True, None)
    yield


@pytest.fixture
def upload_tmpdir(flask_core, tmp_path):
    """Point the meeting audio writer at an isolated tmp dir + restore after."""
    cfg = flask_core.config
    saved = (cfg.get("UPLOAD_FOLDER"), cfg.get("MEETING_MAX_AUDIO_BYTES"))
    cfg["UPLOAD_FOLDER"] = str(tmp_path)
    yield cfg
    cfg["UPLOAD_FOLDER"], cfg["MEETING_MAX_AUDIO_BYTES"] = saved


@pytest.fixture
def no_pipeline(monkeypatch):
    """Stub the background pipeline dispatchers so no daemon thread / LLM runs."""
    # Package split: dispatch lives on ``_common``; crud looks it up at call time.
    noop = lambda *a, **k: None  # noqa: E731
    monkeypatch.setattr(meetings_router._common, "_dispatch_pipeline", noop)
    monkeypatch.setattr(meetings_router._common, "_dispatch_regenerate", noop)
    monkeypatch.setattr(meetings_router, "_dispatch_pipeline", noop)
    monkeypatch.setattr(meetings_router, "_dispatch_regenerate", noop)
    # ffprobe is not guaranteed on the test host — force a deterministic answer.
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


def _make_summary(flask_core, meeting_id, *, exec_summary="The team decided to ship."):
    from app.models.meeting_summary import MeetingSummaryModel

    with flask_core.app_context():
        MeetingSummaryModel.create(meeting_id, {
            "exec_summary": exec_summary,
            "action_items": [{"text": "Email the deck", "owner": "Sam", "due_date": "2026-06-01"}],
            "decisions": ["Ship on Friday"],
            "model": "google/gemini-3.6-flash",
        })


# ===========================================================================
# Route registration smoke.
# ===========================================================================
def test_meetings_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/meetings/upload" in paths
    assert "/api/meetings/list" in paths
    assert "/api/meetings/suggest-series" in paths
    assert "/api/meetings/{meeting_id}" in paths
    assert "/api/meetings/{meeting_id}/transcript" in paths
    assert "/api/meetings/{meeting_id}/summary" in paths
    assert "/api/meetings/{meeting_id}/audio" in paths
    assert "/api/meetings/{meeting_id}/stream" in paths
    assert "/api/meetings/{meeting_id}/cancel" in paths
    assert "/api/meetings/{meeting_id}/regenerate-summary" in paths
    assert "/api/meetings/{meeting_id}/spawn-conversation" in paths
    assert "/api/meetings/{meeting_id}/save-artifact" in paths
    assert "/api/meetings/{meeting_id}/speakers/{speaker_id}" in paths
    # meeting-series
    assert "/api/meeting-series/list" in paths
    assert "/api/meeting-series/create" in paths
    assert "/api/meeting-series/{series_id}" in paths
    assert "/api/meeting-series/{series_id}/keyterms" in paths
    assert "/api/meeting-series/{series_id}/keyterms/{term_id}" in paths
    assert "/api/meeting-series/{series_id}/keyterms/{term_id}/accept" in paths
    assert "/api/meeting-series/{series_id}/speaker-names" in paths


# ===========================================================================
# Auth + feature gating.
# ===========================================================================
def test_list_no_token_401_token_missing(client):
    resp = client.get("/api/meetings/list")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_series_list_no_token_401(client):
    resp = client.get("/api/meeting-series/list")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_feature_flag_off_404(client, flask_core, auth_headers):
    """When the meetings flag is OFF, the feature gate hides the route (404)."""
    from app.models.platform_settings import PlatformSettingsModel

    with flask_core.app_context():
        PlatformSettingsModel.set_feature("meetings", False, None)

    resp = client.get("/api/meetings/list", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "feature_disabled"
    assert resp.json()["feature"] == "meetings"


def test_banned_user_blocked_403(client, banned_user, mint_token):
    headers = {"Authorization": f"Bearer {mint_token(banned_user['_id'], role='user')}"}
    resp = client.get("/api/meetings/list", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Account has been suspended"


# ===========================================================================
# GET /list.
# ===========================================================================
def test_list_meetings_empty(client, auth_headers):
    resp = client.get("/api/meetings/list", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"meetings": [], "has_more": False}


def test_list_meetings_returns_owned(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"], title="Board Meeting")
    resp = client.get("/api/meetings/list", headers=auth_headers)
    assert resp.status_code == 200
    meetings = resp.json()["meetings"]
    assert len(meetings) == 1
    assert meetings[0]["_id"] == mid
    assert meetings[0]["title"] == "Board Meeting"


def test_list_meetings_isolated_per_user(client, flask_core, admin_user, test_user, auth_headers):
    # A meeting owned by admin must NOT show for test_user.
    _make_meeting(flask_core, admin_user["_id"], title="Admin-only")
    resp = client.get("/api/meetings/list", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["meetings"] == []


# ===========================================================================
# GET /{meeting_id}.
# ===========================================================================
def test_get_meeting_ok(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    resp = client.get(f"/api/meetings/{mid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["meeting"]["_id"] == mid


def test_get_meeting_not_found_404(client, auth_headers):
    resp = client.get(f"/api/meetings/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Meeting not found"


def test_get_meeting_other_user_404(client, flask_core, admin_user, auth_headers):
    mid = _make_meeting(flask_core, admin_user["_id"])
    resp = client.get(f"/api/meetings/{mid}", headers=auth_headers)
    assert resp.status_code == 404


# ===========================================================================
# PATCH /{meeting_id}.
# ===========================================================================
def test_patch_meeting_title(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    resp = client.patch(f"/api/meetings/{mid}", headers=auth_headers, json={"title": "Renamed"})
    assert resp.status_code == 200
    assert resp.json()["meeting"]["title"] == "Renamed"


def test_patch_meeting_no_fields_400(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    resp = client.patch(f"/api/meetings/{mid}", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "No mutable fields supplied"


def test_patch_meeting_bad_title_type_400(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    resp = client.patch(f"/api/meetings/{mid}", headers=auth_headers, json={"title": 123})
    assert resp.status_code == 400
    assert resp.json()["error"] == "title must be a string"


def test_patch_meeting_not_found_404(client, auth_headers):
    resp = client.patch(f"/api/meetings/{uuid.uuid4()}", headers=auth_headers, json={"title": "x"})
    assert resp.status_code == 404


# ===========================================================================
# DELETE /{meeting_id}.
# ===========================================================================
def test_delete_meeting_ok(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    resp = client.delete(f"/api/meetings/{mid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Meeting deleted"
    # Now gone.
    assert client.get(f"/api/meetings/{mid}", headers=auth_headers).status_code == 404


def test_delete_meeting_not_found_404(client, auth_headers):
    resp = client.delete(f"/api/meetings/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


# ===========================================================================
# GET /{meeting_id}/transcript + /summary.
# ===========================================================================
def test_transcript_not_available_404(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    resp = client.get(f"/api/meetings/{mid}/transcript", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Transcript not available yet"


def test_transcript_ok(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    _make_transcript(flask_core, mid, plain_text="board notes here")
    resp = client.get(f"/api/meetings/{mid}/transcript", headers=auth_headers)
    assert resp.status_code == 200
    assert "transcript" in resp.json()


def test_summary_not_available_404(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    resp = client.get(f"/api/meetings/{mid}/summary", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Summary not available yet"


def test_summary_ok_unsuffixed_keys(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    _make_summary(flask_core, mid)
    resp = client.get(f"/api/meetings/{mid}/summary", headers=auth_headers)
    assert resp.status_code == 200
    summary = resp.json()["summary"]
    # Frontend contract: list fields are emitted UNSUFFIXED.
    assert "action_items" in summary
    assert "decisions" in summary
    assert "action_items_json" not in summary


# ===========================================================================
# GET /{meeting_id}/audio.
# ===========================================================================
def test_audio_no_path_404(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"], audio_path=None)
    resp = client.get(f"/api/meetings/{mid}/audio", headers=auth_headers)
    assert resp.status_code == 404


def test_audio_serves_file(client, flask_core, test_user, auth_headers, tmp_path):
    audio = tmp_path / "clip.webm"
    audio.write_bytes(b"\x00\x01\x02fake-audio")
    mid = _make_meeting(flask_core, test_user["_id"], audio_path=str(audio))
    resp = client.get(f"/api/meetings/{mid}/audio", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.content == b"\x00\x01\x02fake-audio"


# ===========================================================================
# POST /{meeting_id}/cancel.
# ===========================================================================
def test_cancel_meeting_ok(client, flask_core, test_user, auth_headers, monkeypatch):
    monkeypatch.setattr(
        meetings_router.meetings_pipeline, "request_cancel", lambda *_a, **_k: True
    )
    mid = _make_meeting(flask_core, test_user["_id"], status="transcribing")
    resp = client.post(f"/api/meetings/{mid}/cancel", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["meeting"]["status"] == "failed"


def test_cancel_done_meeting_409(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"], status="done")
    resp = client.post(f"/api/meetings/{mid}/cancel", headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["error"] == "Meeting already complete; cannot cancel"


def test_cancel_not_found_404(client, auth_headers):
    resp = client.post(f"/api/meetings/{uuid.uuid4()}/cancel", headers=auth_headers)
    assert resp.status_code == 404


# ===========================================================================
# POST /{meeting_id}/regenerate-summary.
# ===========================================================================
def test_regenerate_no_transcript_400(client, flask_core, test_user, auth_headers, no_pipeline):
    mid = _make_meeting(flask_core, test_user["_id"], status="done")
    resp = client.post(f"/api/meetings/{mid}/regenerate-summary", headers=auth_headers)
    assert resp.status_code == 400
    assert "no transcript" in resp.json()["error"].lower()


def test_regenerate_ok_202(client, flask_core, test_user, auth_headers, no_pipeline):
    mid = _make_meeting(flask_core, test_user["_id"], status="done")
    _make_transcript(flask_core, mid)
    resp = client.post(f"/api/meetings/{mid}/regenerate-summary", headers=auth_headers)
    assert resp.status_code == 202
    assert resp.json()["meeting"]["status"] == "summarizing"


# ===========================================================================
# POST /{meeting_id}/spawn-conversation.
# ===========================================================================
def test_spawn_conversation_seeds_chat(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"], title="Strategy")
    _make_transcript(flask_core, mid)
    _make_summary(flask_core, mid)
    resp = client.post(f"/api/meetings/{mid}/spawn-conversation", headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["reused"] is False
    assert body["conversation_id"]


def test_spawn_conversation_idempotent_reuse(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"], title="Strategy")
    _make_transcript(flask_core, mid)
    first = client.post(f"/api/meetings/{mid}/spawn-conversation", headers=auth_headers).json()
    second = client.post(f"/api/meetings/{mid}/spawn-conversation", headers=auth_headers)
    assert second.status_code == 200
    body = second.json()
    assert body["reused"] is True
    assert body["conversation_id"] == first["conversation_id"]


def test_spawn_conversation_not_found_404(client, auth_headers):
    resp = client.post(f"/api/meetings/{uuid.uuid4()}/spawn-conversation", headers=auth_headers)
    assert resp.status_code == 404


# ===========================================================================
# POST /{meeting_id}/save-artifact.
# ===========================================================================
def test_save_artifact_invalid_kind_400(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    resp = client.post(f"/api/meetings/{mid}/save-artifact", headers=auth_headers,
                       json={"artifact_kind": "nonsense"})
    assert resp.status_code == 400
    assert "Invalid artifact_kind" in resp.json()["error"]


def test_save_artifact_no_content_400(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    # No summary exists -> exec_summary content unavailable.
    resp = client.post(f"/api/meetings/{mid}/save-artifact", headers=auth_headers,
                       json={"artifact_kind": "exec_summary"})
    assert resp.status_code == 400
    assert "No content available" in resp.json()["error"]


def test_save_artifact_ok(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"], title="Roadmap")
    _make_summary(flask_core, mid, exec_summary="We agreed on Q3 goals.")
    resp = client.post(f"/api/meetings/{mid}/save-artifact", headers=auth_headers,
                       json={"artifact_kind": "exec_summary"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["message"] == "Artifact saved to Knowledge Vault"
    assert body["item"]["_id"]
    assert body["folder_id"]


# ===========================================================================
# PATCH /{meeting_id}/speakers/{speaker_id}.
# ===========================================================================
def test_rename_speaker_ok(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    resp = client.patch(f"/api/meetings/{mid}/speakers/speaker_0", headers=auth_headers,
                        json={"display_name": "Alice"})
    assert resp.status_code == 200
    speakers = resp.json()["meeting"]["speakers"]
    assert any(s["display_name"] == "Alice" for s in speakers)


def test_rename_speaker_bad_type_400(client, flask_core, test_user, auth_headers):
    mid = _make_meeting(flask_core, test_user["_id"])
    resp = client.patch(f"/api/meetings/{mid}/speakers/speaker_0", headers=auth_headers,
                        json={"display_name": 99})
    assert resp.status_code == 400
    assert resp.json()["error"] == "display_name must be a string or null"


# ===========================================================================
# GET /suggest-series.
# ===========================================================================
def test_suggest_series_no_title_returns_null(client, auth_headers):
    resp = client.get("/api/meetings/suggest-series", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"suggestion": None}


def test_suggest_series_match(client, flask_core, test_user, auth_headers):
    _make_series(flask_core, test_user["_id"], name="Weekly Engineering Sync")
    resp = client.get("/api/meetings/suggest-series",
                      headers=auth_headers, params={"title": "Weekly Engineering Sync"})
    assert resp.status_code == 200
    suggestion = resp.json()["suggestion"]
    # rapidfuzz must clear the 85 cutoff on an exact title.
    assert suggestion is not None
    assert suggestion["name"] == "Weekly Engineering Sync"


# ===========================================================================
# POST /upload — the highest-risk route. Real disk writer; pipeline stubbed.
# ===========================================================================
def test_upload_meeting_ok(client, auth_headers, upload_tmpdir, no_pipeline):
    files = {"file": ("clip.webm", io.BytesIO(b"x" * 2048), "audio/webm")}
    resp = client.post("/api/meetings/upload", headers={"Authorization": auth_headers["Authorization"]},
                       data={"title": "My Recording"}, files=files)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["message"] == "Meeting upload accepted"
    assert body["bytes_written"] == 2048
    assert body["meeting"]["_id"]
    assert body["meeting"]["title"] == "My Recording"
    assert body["meeting"]["status"] == "uploaded"


def test_upload_meeting_too_large_413(client, auth_headers, upload_tmpdir, no_pipeline):
    # Cap at 1 KB; send 4 KB -> save_audio_stream raises AudioTooLargeError -> 413.
    upload_tmpdir["MEETING_MAX_AUDIO_BYTES"] = 1024
    files = {"file": ("big.webm", io.BytesIO(b"y" * 4096), "audio/webm")}
    resp = client.post("/api/meetings/upload", headers={"Authorization": auth_headers["Authorization"]},
                       data={"title": "Too Big"}, files=files)
    assert resp.status_code == 413, resp.text
    body = resp.json()
    assert body["code"] == "audio_too_large"
    assert body["max_bytes"] == 1024


def test_upload_meeting_bad_num_speakers_400(client, auth_headers, upload_tmpdir, no_pipeline):
    files = {"file": ("clip.webm", io.BytesIO(b"x" * 512), "audio/webm")}
    resp = client.post("/api/meetings/upload", headers={"Authorization": auth_headers["Authorization"]},
                       data={"num_speakers": "notanint"}, files=files)
    assert resp.status_code == 400
    assert resp.json()["error"] == "num_speakers must be a positive integer"


def test_upload_meeting_no_token_401(client, upload_tmpdir):
    files = {"file": ("clip.webm", io.BytesIO(b"x" * 64), "audio/webm")}
    resp = client.post("/api/meetings/upload", data={"title": "x"}, files=files)
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ===========================================================================
# GET /{meeting_id}/stream — SSE poll-loop.
# ===========================================================================
def test_stream_terminal_status_first_frame(client, flask_core, test_user, auth_headers):
    # A 'done' meeting terminates immediately after the phase_change frame.
    mid = _make_meeting(flask_core, test_user["_id"], status="done")
    with client.stream("GET", f"/api/meetings/{mid}/stream", headers=auth_headers) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["x-accel-buffering"] == "no"
        first = next(resp.iter_lines())
        assert "event: phase_change" in first


def test_stream_not_found_404(client, auth_headers):
    resp = client.get(f"/api/meetings/{uuid.uuid4()}/stream", headers=auth_headers)
    assert resp.status_code == 404


# ===========================================================================
# meeting-series CRUD.
# ===========================================================================
def test_series_list_empty(client, auth_headers):
    resp = client.get("/api/meeting-series/list", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"series": []}


def test_series_create_ok(client, auth_headers):
    resp = client.post("/api/meeting-series/create", headers=auth_headers,
                       json={"name": "Standup", "email_tone": "casual"})
    assert resp.status_code == 201
    series = resp.json()["series"]
    assert series["_id"]
    assert series["name"] == "Standup"
    assert series["email_tone"] == "casual"


def test_series_create_missing_name_400(client, auth_headers):
    resp = client.post("/api/meeting-series/create", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "name is required"


def test_series_create_bad_tone_400(client, auth_headers):
    resp = client.post("/api/meeting-series/create", headers=auth_headers,
                       json={"name": "X", "email_tone": "angry"})
    assert resp.status_code == 400
    assert "email_tone must be one of" in resp.json()["error"]


def test_series_create_duplicate_409(client, flask_core, test_user, auth_headers):
    _make_series(flask_core, test_user["_id"], name="Dup Series")
    resp = client.post("/api/meeting-series/create", headers=auth_headers,
                       json={"name": "Dup Series"})
    assert resp.status_code == 409
    assert resp.json()["code"] == "duplicate_name"


def test_series_list_with_meeting_count(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"], name="Counted")
    _make_meeting(flask_core, test_user["_id"], series_id=sid)
    resp = client.get("/api/meeting-series/list", headers=auth_headers)
    assert resp.status_code == 200
    series = resp.json()["series"]
    assert len(series) == 1
    assert series[0]["_id"] == sid
    assert series[0]["meeting_count"] == 1


def test_series_get_ok(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    resp = client.get(f"/api/meeting-series/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["series"]["_id"] == sid


def test_series_get_not_found_404(client, auth_headers):
    resp = client.get(f"/api/meeting-series/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Series not found"


def test_series_get_other_user_404(client, flask_core, admin_user, auth_headers):
    sid = _make_series(flask_core, admin_user["_id"], name="Admin Series")
    resp = client.get(f"/api/meeting-series/{sid}", headers=auth_headers)
    assert resp.status_code == 404


def test_series_patch_name(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"], name="Old Name")
    resp = client.patch(f"/api/meeting-series/{sid}", headers=auth_headers,
                        json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["series"]["name"] == "New Name"


def test_series_patch_empty_name_400(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    resp = client.patch(f"/api/meeting-series/{sid}", headers=auth_headers, json={"name": ""})
    assert resp.status_code == 400
    assert resp.json()["error"] == "name cannot be empty"


def test_series_patch_no_fields_400(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    resp = client.patch(f"/api/meeting-series/{sid}", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "No mutable fields supplied"


def test_series_delete_ok(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    resp = client.delete(f"/api/meeting-series/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Series deleted"
    assert client.get(f"/api/meeting-series/{sid}", headers=auth_headers).status_code == 404


def test_series_delete_not_found_404(client, auth_headers):
    resp = client.delete(f"/api/meeting-series/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


# ===========================================================================
# meeting-series keyterms + speaker-names.
# ===========================================================================
def test_keyterms_empty(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    resp = client.get(f"/api/meeting-series/{sid}/keyterms", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"keyterms": []}


def test_keyterms_bad_source_400(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    resp = client.get(f"/api/meeting-series/{sid}/keyterms",
                      headers=auth_headers, params={"source": "bogus"})
    assert resp.status_code == 400
    assert "source must be one of" in resp.json()["error"]


def test_add_keyterm_ok(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    resp = client.post(f"/api/meeting-series/{sid}/keyterms",
                       headers=auth_headers, json={"term": "Kubernetes"})
    assert resp.status_code == 201
    assert resp.json()["keyterm"]["_id"]
    assert resp.json()["keyterm"]["term"] == "Kubernetes"


def test_add_keyterm_missing_term_400(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    resp = client.post(f"/api/meeting-series/{sid}/keyterms",
                       headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "term is required"


def test_accept_keyterm_ok(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    created = client.post(f"/api/meeting-series/{sid}/keyterms",
                          headers=auth_headers, json={"term": "Helm"}).json()
    term_id = created["keyterm"]["_id"]
    resp = client.post(f"/api/meeting-series/{sid}/keyterms/{term_id}/accept", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["keyterm"]["source"] == "accepted"


def test_accept_keyterm_unknown_404(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    resp = client.post(f"/api/meeting-series/{sid}/keyterms/{uuid.uuid4()}/accept", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Keyterm not found"


def test_reject_keyterm_ok(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    created = client.post(f"/api/meeting-series/{sid}/keyterms",
                          headers=auth_headers, json={"term": "Istio"}).json()
    term_id = created["keyterm"]["_id"]
    resp = client.delete(f"/api/meeting-series/{sid}/keyterms/{term_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Keyterm deleted"


def test_reject_keyterm_unknown_404(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    resp = client.delete(f"/api/meeting-series/{sid}/keyterms/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


def test_speaker_names_empty(client, flask_core, test_user, auth_headers):
    sid = _make_series(flask_core, test_user["_id"])
    resp = client.get(f"/api/meeting-series/{sid}/speaker-names", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"speaker_names": []}
