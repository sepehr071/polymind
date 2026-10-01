"""Direct facade + helper coverage for the meetings model/service layer.

Mirrors tests/api/test_models.py (real facades, app_context bridge, legacy
dict-shape ``_id`` alias) and the seeding helpers in tests/api/test_meetings.py.
No HTTP — every call runs inside ``flask_core.app_context()`` against the
isolated ``unichat_*_test`` DB; no external upstream is touched (the meetings
service helpers are pure string builders).

Targets the uncovered ranges in:
  - app/models/meeting_series.py  (MeetingSeriesModel / KeytermModel / SpeakerNameModel)
  - app/models/meeting.py         (MeetingModel + _meeting_to_dict / _speakers_for_meetings)
  - app/services/meetings_service.py  (format helpers + build_seed_text)
"""
import uuid

import pytest

from app.models.meeting import (
    MeetingModel,
    VALID_MEETING_STATUSES,
    _meeting_to_dict,
    _speakers_for_meetings,
    Meeting,
)
from app.models.meeting_series import (
    MeetingSeriesModel,
    KeytermModel,
    SpeakerNameModel,
    _to_uuid,
)
import app.services.meetings_service as svc


# ===========================================================================
# Helpers.
# ===========================================================================
def _mk_series(flask_core, owner_id, *, name="Weekly Sync", email_tone="formal",
               description=None):
    with flask_core.app_context():
        data = {"name": name, "email_tone": email_tone}
        if description is not None:
            data["description"] = description
        return MeetingSeriesModel.create(str(owner_id), data)


def _mk_meeting(flask_core, owner_id, *, title="Quarterly Review", status="uploaded",
                series_id=None, speakers=None, audio_path=None):
    mid = str(uuid.uuid4())
    with flask_core.app_context():
        MeetingModel.create(str(owner_id), {
            "_id": mid,
            "title": title,
            "status": status,
            "series_id": series_id,
            "speakers": speakers or [],
            "audio_path": audio_path,
        })
    return mid


# ===========================================================================
# _to_uuid (both modules share an identical helper).
# ===========================================================================
def test_to_uuid_none():
    assert _to_uuid(None) is None


def test_to_uuid_passthrough_instance():
    u = uuid.uuid4()
    assert _to_uuid(u) is u


def test_to_uuid_from_string():
    u = uuid.uuid4()
    assert _to_uuid(str(u)) == u


def test_to_uuid_garbage_returns_none():
    assert _to_uuid("not-a-uuid") is None


# ===========================================================================
# MeetingSeriesModel — CRUD.
# ===========================================================================
def test_series_create_and_find_by_id(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"], name="Alpha", description="d")
    with flask_core.app_context():
        row = MeetingSeriesModel.find_by_id(sid)
    assert row is not None
    assert row["_id"] == sid
    assert row["name"] == "Alpha"
    assert row["description"] == "d"
    assert row["owner_id"] == str(test_user["_id"])
    assert row["email_tone"] == "formal"


def test_series_create_default_email_tone(flask_core, test_user):
    with flask_core.app_context():
        sid = MeetingSeriesModel.create(str(test_user["_id"]), {"name": "NoTone"})
        row = MeetingSeriesModel.find_by_id(sid)
    assert row["email_tone"] == "formal"


def test_series_create_with_explicit_id(flask_core, test_user):
    forced = str(uuid.uuid4())
    with flask_core.app_context():
        sid = MeetingSeriesModel.create(str(test_user["_id"]), {"_id": forced, "name": "Pinned"})
    assert sid == forced


def test_series_create_invalid_email_tone_raises(flask_core, test_user):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            MeetingSeriesModel.create(str(test_user["_id"]), {"name": "X", "email_tone": "angry"})


def test_series_find_by_id_bad_uuid(flask_core):
    with flask_core.app_context():
        assert MeetingSeriesModel.find_by_id("nonsense") is None


def test_series_find_by_id_missing(flask_core):
    with flask_core.app_context():
        assert MeetingSeriesModel.find_by_id(str(uuid.uuid4())) is None


def test_series_find_owned_ok(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"], name="Owned")
    with flask_core.app_context():
        row = MeetingSeriesModel.find_owned(sid, str(test_user["_id"]))
    assert row is not None and row["_id"] == sid


def test_series_find_owned_wrong_owner(flask_core, test_user, admin_user):
    sid = _mk_series(flask_core, test_user["_id"], name="Mine")
    with flask_core.app_context():
        assert MeetingSeriesModel.find_owned(sid, str(admin_user["_id"])) is None


def test_series_find_owned_bad_uuids(flask_core, test_user):
    with flask_core.app_context():
        assert MeetingSeriesModel.find_owned("bad", str(test_user["_id"])) is None
        assert MeetingSeriesModel.find_owned(str(uuid.uuid4()), "bad") is None


def test_series_list_for_user(flask_core, test_user):
    _mk_series(flask_core, test_user["_id"], name="One")
    _mk_series(flask_core, test_user["_id"], name="Two")
    with flask_core.app_context():
        rows = MeetingSeriesModel.list_for_user(str(test_user["_id"]))
    assert {r["name"] for r in rows} == {"One", "Two"}


def test_series_list_for_user_pagination(flask_core, test_user):
    _mk_series(flask_core, test_user["_id"], name="A")
    _mk_series(flask_core, test_user["_id"], name="B")
    with flask_core.app_context():
        rows = MeetingSeriesModel.list_for_user(str(test_user["_id"]), skip=1, limit=1)
    assert len(rows) == 1


def test_series_list_for_user_bad_owner(flask_core):
    with flask_core.app_context():
        assert MeetingSeriesModel.list_for_user("bad") == []


def test_series_update_name_and_tone(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"], name="Before")
    with flask_core.app_context():
        ok = MeetingSeriesModel.update(sid, str(test_user["_id"]),
                                       {"name": "After", "email_tone": "casual",
                                        "description": "newdesc"})
        assert ok is True
        row = MeetingSeriesModel.find_by_id(sid)
    assert row["name"] == "After"
    assert row["email_tone"] == "casual"
    assert row["description"] == "newdesc"


def test_series_update_empty_data(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert MeetingSeriesModel.update(sid, str(test_user["_id"]), {}) is False


def test_series_update_bad_tone_raises(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        with pytest.raises(ValueError):
            MeetingSeriesModel.update(sid, str(test_user["_id"]), {"email_tone": "loud"})


def test_series_update_bad_uuid(flask_core, test_user):
    with flask_core.app_context():
        assert MeetingSeriesModel.update("bad", str(test_user["_id"]), {"name": "x"}) is False


def test_series_update_unknown_field_ignored(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"], name="Keep")
    with flask_core.app_context():
        # 'bogus' is filtered out; updated_at is always set so rowcount > 0.
        ok = MeetingSeriesModel.update(sid, str(test_user["_id"]), {"bogus": "ignored"})
        assert ok is True
        assert MeetingSeriesModel.find_by_id(sid)["name"] == "Keep"


def test_series_delete_ok(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert MeetingSeriesModel.delete(sid, str(test_user["_id"])) is True
        assert MeetingSeriesModel.find_by_id(sid) is None


def test_series_delete_wrong_owner(flask_core, test_user, admin_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert MeetingSeriesModel.delete(sid, str(admin_user["_id"])) is False


def test_series_delete_bad_uuid(flask_core, test_user):
    with flask_core.app_context():
        assert MeetingSeriesModel.delete("bad", str(test_user["_id"])) is False


# ===========================================================================
# KeytermModel.
# ===========================================================================
def test_keyterm_find_by_id_bad_uuid(flask_core):
    with flask_core.app_context():
        assert KeytermModel.find_by_id("bad") is None
        assert KeytermModel.find_by_id(str(uuid.uuid4())) is None


def test_keyterm_upsert_new(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        out = KeytermModel.upsert_term(sid, "Istio", "suggested")
    assert out["term"] == "Istio"
    assert out["source"] == "suggested"


def test_keyterm_upsert_promotes_suggested_to_manual(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        KeytermModel.upsert_term(sid, "Promote", "suggested")
        out = KeytermModel.upsert_term(sid, "Promote", "manual")
    assert out["source"] == "manual"


def test_keyterm_upsert_does_not_demote(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        KeytermModel.upsert_term(sid, "Stay", "manual")
        out = KeytermModel.upsert_term(sid, "Stay", "suggested")
    # manual must NOT be demoted to suggested.
    assert out["source"] == "manual"


def test_keyterm_upsert_invalid_source_raises(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        with pytest.raises(ValueError):
            KeytermModel.upsert_term(sid, "X", "bogus")


def test_keyterm_upsert_bad_series_raises(flask_core):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            KeytermModel.upsert_term("bad", "X")


def test_keyterm_list_for_series_and_filter(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        KeytermModel.upsert_term(sid, "ManualOne", "manual")
        KeytermModel.upsert_term(sid, "SuggestedOne", "suggested")
        all_terms = KeytermModel.list_for_series(sid)
        manual_only = KeytermModel.list_for_series(sid, source="manual")
    assert {t["term"] for t in all_terms} == {"ManualOne", "SuggestedOne"}
    assert {t["term"] for t in manual_only} == {"ManualOne"}


def test_keyterm_list_bad_series(flask_core):
    with flask_core.app_context():
        assert KeytermModel.list_for_series("bad") == []


def test_keyterm_list_bad_source_filter_raises(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        with pytest.raises(ValueError):
            KeytermModel.list_for_series(sid, source="bogus")


def test_keyterm_set_source(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        tid = KeytermModel.upsert_term(sid, "Accept Me", "suggested")["_id"]
        assert KeytermModel.set_source(tid, "accepted") is True
        assert KeytermModel.find_by_id(tid)["source"] == "accepted"


def test_keyterm_set_source_invalid_raises(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        tid = KeytermModel.upsert_term(sid, "T")["_id"]
        with pytest.raises(ValueError):
            KeytermModel.set_source(tid, "bogus")


def test_keyterm_set_source_bad_uuid(flask_core):
    with flask_core.app_context():
        assert KeytermModel.set_source("bad", "manual") is False


def test_keyterm_delete(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        tid = KeytermModel.upsert_term(sid, "Del")["_id"]
        assert KeytermModel.delete(tid) is True
        assert KeytermModel.find_by_id(tid) is None


def test_keyterm_delete_bad_uuid(flask_core):
    with flask_core.app_context():
        assert KeytermModel.delete("bad") is False


def test_keyterm_delete_for_series(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        KeytermModel.upsert_term(sid, "K1")
        KeytermModel.upsert_term(sid, "K2")
        n = KeytermModel.delete_for_series(sid)
        assert n == 2
        assert KeytermModel.list_for_series(sid) == []


def test_keyterm_delete_for_series_bad_uuid(flask_core):
    with flask_core.app_context():
        assert KeytermModel.delete_for_series("bad") == 0


# ===========================================================================
# SpeakerNameModel.
# ===========================================================================
def test_speaker_upsert_new(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        out = SpeakerNameModel.upsert(sid, "Alice")
    assert out["display_name"] == "Alice"
    assert out["series_id"] == sid


def test_speaker_upsert_idempotent_touch(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        first = SpeakerNameModel.upsert(sid, "Bob")
        second = SpeakerNameModel.upsert(sid, "Bob")
    # Same row (PK preserved) — conflict path updates last_used_at only.
    assert first["_id"] == second["_id"]


def test_speaker_upsert_bad_series_raises(flask_core):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            SpeakerNameModel.upsert("bad", "Dan")


def test_speaker_list_for_series(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        SpeakerNameModel.upsert(sid, "X")
        SpeakerNameModel.upsert(sid, "Y")
        rows = SpeakerNameModel.list_for_series(sid)
    assert {r["display_name"] for r in rows} == {"X", "Y"}


def test_speaker_list_bad_series(flask_core):
    with flask_core.app_context():
        assert SpeakerNameModel.list_for_series("bad") == []


def test_speaker_delete(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        out = SpeakerNameModel.upsert(sid, "Erin")
        assert SpeakerNameModel.delete(out["_id"]) is True


def test_speaker_delete_bad_uuid(flask_core):
    with flask_core.app_context():
        assert SpeakerNameModel.delete("bad") is False


def test_speaker_delete_for_series(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    with flask_core.app_context():
        SpeakerNameModel.upsert(sid, "S1")
        SpeakerNameModel.upsert(sid, "S2")
        n = SpeakerNameModel.delete_for_series(sid)
    assert n == 2


def test_speaker_delete_for_series_bad_uuid(flask_core):
    with flask_core.app_context():
        assert SpeakerNameModel.delete_for_series("bad") == 0


# ===========================================================================
# MeetingModel — CRUD + status helpers.
# ===========================================================================
def test_meeting_create_and_find(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"], title="Board")
    with flask_core.app_context():
        row = MeetingModel.find_by_id(mid)
    assert row["_id"] == mid
    assert row["title"] == "Board"
    assert row["owner_id"] == str(test_user["_id"])
    assert row["language"] == "fas"
    assert row["status"] == "uploaded"
    assert row["speakers"] == []


def test_meeting_create_with_speakers_and_duration(flask_core, test_user):
    mid = str(uuid.uuid4())
    with flask_core.app_context():
        MeetingModel.create(str(test_user["_id"]), {
            "_id": mid,
            "title": "WithSpeakers",
            "duration_s": 90.7,
            "language": "eng",
            "email_tone": "casual",
            "error_message": "none-yet",
            "speakers": [
                {"speaker_id": "speaker_0", "display_name": "A"},
                {"speaker_id": "speaker_1", "display_name": "B"},
            ],
        })
        row = MeetingModel.find_by_id(mid)
    assert row["duration_s"] == 90  # int() coercion
    assert row["language"] == "eng"
    assert {s["speaker_id"] for s in row["speakers"]} == {"speaker_0", "speaker_1"}


def test_meeting_create_invalid_status_raises(flask_core, test_user):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            MeetingModel.create(str(test_user["_id"]), {"status": "bogus"})


def test_meeting_create_with_series(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    mid = _mk_meeting(flask_core, test_user["_id"], series_id=sid)
    with flask_core.app_context():
        row = MeetingModel.find_by_id(mid)
    assert row["series_id"] == sid


def test_meeting_find_by_id_bad_uuid(flask_core):
    with flask_core.app_context():
        assert MeetingModel.find_by_id("bad") is None
        assert MeetingModel.find_by_id(str(uuid.uuid4())) is None


def test_meeting_find_owned(flask_core, test_user, admin_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert MeetingModel.find_owned(mid, str(test_user["_id"]))["_id"] == mid
        assert MeetingModel.find_owned(mid, str(admin_user["_id"])) is None
        assert MeetingModel.find_owned("bad", str(test_user["_id"])) is None
        assert MeetingModel.find_owned(mid, "bad") is None


def test_meeting_list_for_user_filters(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    _mk_meeting(flask_core, test_user["_id"], title="Alpha Meeting", series_id=sid)
    _mk_meeting(flask_core, test_user["_id"], title="Beta Meeting")
    with flask_core.app_context():
        all_rows = MeetingModel.list_for_user(str(test_user["_id"]))
        by_series = MeetingModel.list_for_user(str(test_user["_id"]), series_id=sid)
        by_q = MeetingModel.list_for_user(str(test_user["_id"]), q="Alpha")
    assert len(all_rows) == 2
    assert len(by_series) == 1 and by_series[0]["series_id"] == sid
    assert len(by_q) == 1 and by_q[0]["title"] == "Alpha Meeting"


def test_meeting_list_for_user_bad_owner(flask_core):
    with flask_core.app_context():
        assert MeetingModel.list_for_user("bad") == []


def test_meeting_list_speakers_batched(flask_core, test_user):
    mid = str(uuid.uuid4())
    with flask_core.app_context():
        MeetingModel.create(str(test_user["_id"]), {
            "_id": mid, "title": "Batched",
            "speakers": [{"speaker_id": "speaker_0", "display_name": "Z"}],
        })
        rows = MeetingModel.list_for_user(str(test_user["_id"]))
    assert rows[0]["speakers"][0]["display_name"] == "Z"


def test_meeting_update_translated_fields(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        ok = MeetingModel.update(mid, str(test_user["_id"]), {
            "title": "Renamed",
            "error_message": "boom",
            "language": "deu",
            "latest_summary_id": "ignored",  # skipped
            "num_speakers": 3,               # skipped
        })
        assert ok is True
        row = MeetingModel.find_by_id(mid)
    assert row["title"] == "Renamed"
    assert row["error_message"] == "boom"
    assert row["language"] == "deu"


def test_meeting_update_series_id(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        ok = MeetingModel.update(mid, str(test_user["_id"]), {"series_id": sid})
        assert ok is True
        assert MeetingModel.find_by_id(mid)["series_id"] == sid


def test_meeting_update_empty(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert MeetingModel.update(mid, str(test_user["_id"]), {}) is False


def test_meeting_update_bad_status_raises(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        with pytest.raises(ValueError):
            MeetingModel.update(mid, str(test_user["_id"]), {"status": "bogus"})


def test_meeting_update_bad_uuid(flask_core, test_user):
    with flask_core.app_context():
        assert MeetingModel.update("bad", str(test_user["_id"]), {"title": "x"}) is False
        assert MeetingModel.update(str(uuid.uuid4()), "bad", {"title": "x"}) is False


def test_meeting_count_for_series(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    _mk_meeting(flask_core, test_user["_id"], series_id=sid)
    _mk_meeting(flask_core, test_user["_id"], series_id=sid)
    with flask_core.app_context():
        assert MeetingModel.count_for_series(str(test_user["_id"]), sid) == 2
        assert MeetingModel.count_for_series("bad", sid) == 0
        assert MeetingModel.count_for_series(str(test_user["_id"]), "bad") == 0


def test_meeting_count_by_series_for_owner(flask_core, test_user):
    sid1 = _mk_series(flask_core, test_user["_id"], name="S1")
    sid2 = _mk_series(flask_core, test_user["_id"], name="S2")
    _mk_meeting(flask_core, test_user["_id"], series_id=sid1)
    _mk_meeting(flask_core, test_user["_id"], series_id=sid1)
    _mk_meeting(flask_core, test_user["_id"], series_id=sid2)
    _mk_meeting(flask_core, test_user["_id"])  # NULL series, excluded
    with flask_core.app_context():
        all_counts = MeetingModel.count_by_series_for_owner(str(test_user["_id"]))
        scoped = MeetingModel.count_by_series_for_owner(str(test_user["_id"]), series_ids=[sid1])
    assert all_counts == {sid1: 2, sid2: 1}
    assert scoped == {sid1: 2}


def test_meeting_count_by_series_bad_owner(flask_core):
    with flask_core.app_context():
        assert MeetingModel.count_by_series_for_owner("bad") == {}


def test_meeting_count_by_series_empty_id_list(flask_core, test_user):
    with flask_core.app_context():
        assert MeetingModel.count_by_series_for_owner(str(test_user["_id"]),
                                                      series_ids=["bad"]) == {}


def test_meeting_null_series_for_owner(flask_core, test_user):
    sid = _mk_series(flask_core, test_user["_id"])
    mid = _mk_meeting(flask_core, test_user["_id"], series_id=sid)
    with flask_core.app_context():
        n = MeetingModel.null_series_for_owner(str(test_user["_id"]), sid)
        assert n == 1
        assert MeetingModel.find_by_id(mid)["series_id"] is None
        assert MeetingModel.null_series_for_owner("bad", sid) == 0


def test_meeting_set_status(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert MeetingModel.set_status(mid, "failed", error_message="x") is True
        row = MeetingModel.find_by_id(mid)
    assert row["status"] == "failed"
    assert row["error_message"] == "x"


def test_meeting_set_status_invalid_raises(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        with pytest.raises(ValueError):
            MeetingModel.set_status(mid, "bogus")


def test_meeting_set_status_bad_uuid(flask_core):
    with flask_core.app_context():
        assert MeetingModel.set_status("bad", "done") is False


def test_meeting_set_language(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert MeetingModel.set_language(mid, "ita") is True
        assert MeetingModel.find_by_id(mid)["language"] == "ita"
        assert MeetingModel.set_language(mid, "") is False
        assert MeetingModel.set_language("bad", "ita") is False


def test_meeting_set_latest_summary(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert MeetingModel.set_latest_summary(mid, uuid.uuid4()) is True
        assert MeetingModel.set_latest_summary("bad", None) is False


def test_meeting_upsert_speakers(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        ok = MeetingModel.upsert_speakers(mid, [
            {"speaker_id": "speaker_0", "display_name": "A"},
            {"speaker_id": "speaker_1"},
        ])
        assert ok is True
        row = MeetingModel.find_by_id(mid)
    labels = {s["speaker_id"] for s in row["speakers"]}
    assert labels == {"speaker_0", "speaker_1"}


def test_meeting_upsert_speakers_bad_uuid(flask_core):
    with flask_core.app_context():
        assert MeetingModel.upsert_speakers("bad", []) is False


def test_meeting_add_speaker(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert MeetingModel.add_speaker(mid, "speaker_0", "First") is True
        assert MeetingModel.add_speaker(mid, "speaker_1", "Second") is True
        row = MeetingModel.find_by_id(mid)
    # order_idx increments — second appended after first.
    assert [s["speaker_id"] for s in row["speakers"]] == ["speaker_0", "speaker_1"]


def test_meeting_add_speaker_bad_uuid(flask_core):
    with flask_core.app_context():
        assert MeetingModel.add_speaker("bad", "speaker_0") is False


def test_meeting_update_speaker_display_name(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        MeetingModel.add_speaker(mid, "speaker_0", "Old")
        assert MeetingModel.update_speaker_display_name(mid, "speaker_0", "New") is True
        # No matching label -> rowcount 0.
        assert MeetingModel.update_speaker_display_name(mid, "missing", "Z") is False
        assert MeetingModel.update_speaker_display_name("bad", "speaker_0", "Z") is False
        row = MeetingModel.find_by_id(mid)
    assert row["speakers"][0]["display_name"] == "New"


def test_meeting_set_speaker_name_updates_existing(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        MeetingModel.add_speaker(mid, "speaker_0", "Orig")
        # Existing label -> update branch.
        assert MeetingModel.set_speaker_name(mid, "speaker_0", "Updated") is True
        row = MeetingModel.find_by_id(mid)
    assert row["speakers"][0]["display_name"] == "Updated"


def test_meeting_set_speaker_name_adds_when_absent(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        # No such label yet -> add branch.
        assert MeetingModel.set_speaker_name(mid, "speaker_9", "Added") is True
        row = MeetingModel.find_by_id(mid)
    assert any(s["speaker_id"] == "speaker_9" for s in row["speakers"])


def test_meeting_cancel(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"], status="transcribing")
    with flask_core.app_context():
        assert MeetingModel.cancel(mid) is True
        row = MeetingModel.find_by_id(mid)
    assert row["status"] == "cancelled"
    assert row["cancel_requested"] is True


def test_meeting_cancel_bad_uuid(flask_core):
    with flask_core.app_context():
        assert MeetingModel.cancel("bad") is False


def test_meeting_search_by_title(flask_core, test_user):
    _mk_meeting(flask_core, test_user["_id"], title="Roadmap Planning")
    _mk_meeting(flask_core, test_user["_id"], title="Budget Review")
    with flask_core.app_context():
        hits = MeetingModel.search_by_title(str(test_user["_id"]), "Roadmap")
        assert len(hits) == 1 and hits[0]["title"] == "Roadmap Planning"
        # blank / bad-owner short circuits.
        assert MeetingModel.search_by_title(str(test_user["_id"]), "   ") == []
        assert MeetingModel.search_by_title("bad", "Roadmap") == []


def test_meeting_delete(flask_core, test_user, admin_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        # Wrong owner / bad uuid first.
        assert MeetingModel.delete(mid, str(admin_user["_id"])) is False
        assert MeetingModel.delete("bad", str(test_user["_id"])) is False
        assert MeetingModel.delete(mid, "bad") is False
        # Real delete.
        assert MeetingModel.delete(mid, str(test_user["_id"])) is True
        assert MeetingModel.find_by_id(mid) is None


# ===========================================================================
# _speakers_for_meetings + _meeting_to_dict helpers (direct).
# ===========================================================================
def test_speakers_for_meetings_empty():
    assert _speakers_for_meetings([]) == {}
    assert _speakers_for_meetings(None) == {}
    assert _speakers_for_meetings([None]) == {}


def test_speakers_for_meetings_populated(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"])
    with flask_core.app_context():
        MeetingModel.add_speaker(mid, "speaker_0", "Solo")
        m_uuid = uuid.UUID(mid)
        out = _speakers_for_meetings([m_uuid])
    assert out[m_uuid][0]["display_name"] == "Solo"


def test_meeting_to_dict_single_path(flask_core, test_user):
    mid = _mk_meeting(flask_core, test_user["_id"], title="Single")
    with flask_core.app_context():
        MeetingModel.add_speaker(mid, "speaker_0", "X")
        row = db_get_meeting(flask_core, mid)
        out = _meeting_to_dict(row)  # no speakers_map -> per-row SELECT branch
    assert out["title"] == "Single"
    assert out["speakers"][0]["display_name"] == "X"
    assert out["owner_id"] == str(test_user["_id"])


def db_get_meeting(flask_core, mid):
    from app.api.core import db
    return db.session.get(Meeting, uuid.UUID(mid))


def test_valid_meeting_statuses_constant():
    assert "cancelled" in VALID_MEETING_STATUSES
    assert "done" in VALID_MEETING_STATUSES


# ===========================================================================
# meetings_service — pure string helpers.
# ===========================================================================
def test_format_action_item_full():
    out = svc._format_action_item({"text": "Ship", "owner": "Sam", "due_date": "2026-06-01"})
    assert out == "- Ship _(@Sam, due 2026-06-01)_"


def test_format_action_item_text_only():
    assert svc._format_action_item({"text": "Just do it"}) == "- Just do it"


def test_format_action_item_owner_only():
    assert svc._format_action_item({"text": "Task", "owner": "Bo"}) == "- Task _(@Bo)_"


def test_format_action_item_empty():
    # No text, no meta -> just the dash, rstripped.
    assert svc._format_action_item({}) == "-"


def test_format_qa():
    out = svc._format_qa([
        {"question": "Why?", "answer": "Because"},
        {"question": "How?"},          # no answer -> only the Q line
        {"answer": "orphan"},          # no question -> skipped
    ])
    assert out == ["- **Q:** Why?", "  **A:** Because", "- **Q:** How?"]


def test_format_open_questions():
    out = svc._format_open_questions([
        {"question": "Open one", "owner": "Lee"},
        {"question": "Open two"},
        {"owner": "noq"},  # skipped (no question)
    ])
    assert out == ["- Open one _(Lee)_", "- Open two"]


def test_format_minutes_with_names_and_time():
    names = {"speaker_0": "Alice"}
    out = svc._format_minutes(
        [
            {"speaker_id": "speaker_0", "text": "hi", "start_s": 1.0, "end_s": 2.5},
            {"speaker_id": "speaker_9", "text": "anon"},  # unmapped -> raw id
            {"speaker_id": "speaker_0", "text": ""},      # blank text -> skipped
        ],
        speaker_names=names,
    )
    assert out[0] == "- **Alice** `[1.00-2.50]`: hi"
    assert out[1] == "- **speaker_9**: anon"
    assert len(out) == 2


def test_format_minutes_no_speaker_id():
    out = svc._format_minutes([{"text": "ghost"}], speaker_names={})
    assert out == ["- **speaker_?**: ghost"]


def test_speaker_name_map():
    meeting = {"speakers": [
        {"speaker_id": "speaker_0", "display_name": "Ann"},
        {"speaker_id": "speaker_1", "display_name": "  "},  # blank stripped -> skip
        {"speaker_id": None, "display_name": "NoId"},       # no id -> skip
    ]}
    assert svc._speaker_name_map(meeting) == {"speaker_0": "Ann"}


def test_speaker_name_map_empty():
    assert svc._speaker_name_map({}) == {}


def test_build_seed_text_title_only():
    out = svc.build_seed_text({"title": "Strategy"}, None, None)
    assert out.startswith("# Meeting: Strategy")
    assert out.endswith("\n")


def test_build_seed_text_untitled_fallback():
    out = svc.build_seed_text({"title": "   "}, None, None)
    assert "# Meeting: Untitled" in out


def test_build_seed_text_with_transcript():
    out = svc.build_seed_text(
        {"title": "T"}, {"plain_text": "spoken words"}, None
    )
    assert "## Transcript" in out
    assert "spoken words" in out


def test_build_seed_text_empty_transcript_dropped():
    out = svc.build_seed_text({"title": "T"}, {"plain_text": "   "}, None)
    assert "## Transcript" not in out


def test_build_seed_text_full_summary():
    meeting = {
        "title": "All Hands",
        "speakers": [{"speaker_id": "speaker_0", "display_name": "Pat"}],
    }
    summary = {
        "exec_summary": "We shipped.",
        "action_items_json": [{"text": "Follow up", "owner": "Pat", "due_date": "2026-07-01"}],
        "decisions_json": ["Adopt X", "", 123],  # blank + non-str skipped
        "minutes_json": [{"speaker_id": "speaker_0", "text": "intro", "start_s": 0, "end_s": 1}],
        "qa_json": [{"question": "Q1?", "answer": "A1"}],
        "open_questions_json": [{"question": "Still open?"}],
        "email_subject": "Recap",
        "email_draft": "Hello team,",
    }
    out = svc.build_seed_text(meeting, {"plain_text": "raw transcript"}, summary)
    for heading in ("## Transcript", "## Summary", "## Action Items", "## Decisions",
                    "## Minutes", "## Q&A", "## Open Questions", "## Follow-up Email"):
        assert heading in out
    assert "We shipped." in out
    assert "- Adopt X" in out
    assert "**Subject:** Recap" in out
    assert "Hello team," in out
    assert "**Pat**" in out  # minutes used the resolved display name


def test_build_seed_text_email_subject_only():
    out = svc.build_seed_text({"title": "T"}, None, {"email_subject": "Just Subject"})
    assert "## Follow-up Email" in out
    assert "**Subject:** Just Subject" in out


def test_build_seed_text_email_body_only():
    out = svc.build_seed_text({"title": "T"}, None, {"email_draft": "Body text"})
    assert "## Follow-up Email" in out
    assert "Body text" in out


def test_build_seed_text_summary_no_sections():
    # Summary present but every list empty / blank -> no sub-headings emitted.
    out = svc.build_seed_text({"title": "T"}, None, {"exec_summary": "   "})
    assert "## Summary" not in out
    assert "## Action Items" not in out


def test_meeting_discussion_model_constant():
    assert svc.MEETING_DISCUSSION_MODEL == "google/gemini-3.6-flash"
