"""Signed media-URL tests: services/signed_urls.py + the video-serving route +
the _record_usage burst-and-remove conn release.

Three groups:
  1. Pure unit tests on ``signed_urls`` (sign/verify round-trip, tamper, expiry,
     domain separation from DLP tokens). No DB.
  2. Route tests for ``GET /api/uploads/video/{filename}`` covering the staged
     enforcement matrix (valid -> 200, tampered -> 403, expired -> 403, unsigned
     with MEDIA_URL_SIGNING_REQUIRED unset -> 200+warning / set -> 403, and the
     existing prefix/traversal guards still reject). Reuses the ``client`` +
     ``upload_tmpdir`` fixtures from test_misc_a.py.
  3. _record_usage: when usage.cost is None and /generation is mocked, the row is
     still written with the right cost AND the runner thread's DB connection was
     released (db.session.remove) before the HTTP hop.

Additive — does not modify any existing test. The pre-existing
``test_get_video_serves_existing`` keeps passing (signing not required by
default -> unsigned URLs still serve, just with a deprecation warning).
"""
import time

import pytest

import app.services.signed_urls as su


# ---------------------------------------------------------------------------
# upload_tmpdir — module-local copy of test_misc_a.py's fixture (pytest module
# fixtures don't cross files; only conftest fixtures do). Points the upload
# writer/reader at an isolated tmp dir so the video-serving route finds files.
# ---------------------------------------------------------------------------
@pytest.fixture
def upload_tmpdir(flask_core, tmp_path):
    cfg = flask_core.config
    saved = cfg.get("UPLOAD_FOLDER")
    cfg["UPLOAD_FOLDER"] = str(tmp_path)
    yield tmp_path
    cfg["UPLOAD_FOLDER"] = saved


# ---------------------------------------------------------------------------
# 1. signed_urls unit tests (no DB)
# ---------------------------------------------------------------------------
def test_sign_verify_round_trip():
    exp, sig = su.sign_video_filename("video_u_g.mp4", ttl_seconds=60)
    assert su.verify_video_url("video_u_g.mp4", exp, sig) is True


def test_sign_video_url_query_shape():
    q = su.sign_video_url("video_u_g.mp4", ttl_seconds=60)
    assert q.startswith("exp=")
    assert "&sig=" in q
    exp_s, sig_s = (part.split("=", 1)[1] for part in q.split("&"))
    assert su.verify_video_url("video_u_g.mp4", exp_s, sig_s) is True


def test_verify_rejects_tampered_sig():
    exp, sig = su.sign_video_filename("video_u_g.mp4", ttl_seconds=60)
    assert su.verify_video_url("video_u_g.mp4", exp, sig + "x") is False


def test_verify_rejects_filename_rebind():
    # A sig minted for one file must not validate another (filename is in the MAC).
    exp, sig = su.sign_video_filename("video_u_g.mp4", ttl_seconds=60)
    assert su.verify_video_url("video_OTHER.mp4", exp, sig) is False


def test_verify_rejects_exp_extension():
    # Bumping exp to dodge expiry breaks the MAC (exp is signed).
    exp, sig = su.sign_video_filename("video_u_g.mp4", ttl_seconds=60)
    assert su.verify_video_url("video_u_g.mp4", exp + 10_000, sig) is False


def test_verify_rejects_expired():
    exp, sig = su.sign_video_filename("video_u_g.mp4", ttl_seconds=-5)
    assert su.verify_video_url("video_u_g.mp4", exp, sig) is False


def test_verify_rejects_missing_and_malformed():
    assert su.verify_video_url("video_u_g.mp4", None, None) is False
    assert su.verify_video_url("video_u_g.mp4", "notanint", "sig") is False
    assert su.verify_video_url("", 1, "sig") is False


def test_default_ttl_is_seven_days():
    assert su.default_ttl_seconds() == 7 * 24 * 60 * 60
    exp, _ = su.sign_video_filename("video_u_g.mp4")
    assert 6 * 24 * 3600 < (exp - int(time.time())) <= 7 * 24 * 3600


def test_ttl_env_override(monkeypatch):
    monkeypatch.setenv("MEDIA_URL_SIGNING_TTL_S", "120")
    assert su.default_ttl_seconds() == 120
    monkeypatch.setenv("MEDIA_URL_SIGNING_TTL_S", "0")  # non-positive ignored
    assert su.default_ttl_seconds() == 7 * 24 * 60 * 60


def test_signing_required_env_parsing(monkeypatch):
    for truthy in ("1", "true", "TRUE", "yes", " Yes "):
        monkeypatch.setenv("MEDIA_URL_SIGNING_REQUIRED", truthy)
        assert su.signing_required() is True
    for falsy in ("0", "false", "no", ""):
        monkeypatch.setenv("MEDIA_URL_SIGNING_REQUIRED", falsy)
        assert su.signing_required() is False
    monkeypatch.delenv("MEDIA_URL_SIGNING_REQUIRED", raising=False)
    assert su.signing_required() is False


def test_domain_separated_from_dlp_token():
    """A video sig must not equal a DLP-style MAC over the same logical string.

    Both modules key off JWT_SECRET_KEY; the b"video:" domain prefix is the only
    thing keeping a video signature from colliding with another HMAC use.
    """
    import hashlib
    import hmac

    filename, exp = "video_u_g.mp4", 1_900_000_000
    video_mac_b64 = su._sign(filename, exp)
    # Same key + same message bytes but WITHOUT the domain prefix -> different MAC.
    raw_msg = f"{filename}|{exp}".encode("utf-8")
    raw_mac = hmac.new(su._hmac_key(), raw_msg, hashlib.sha256).digest()
    raw_mac_b64 = su._b64url(raw_mac)
    assert video_mac_b64 != raw_mac_b64


# ---------------------------------------------------------------------------
# 2. Route tests — GET /api/uploads/video/{filename}
#    Reuses `client` (conftest) + `upload_tmpdir` (test_misc_a.py, same package).
# ---------------------------------------------------------------------------
_VIDEO = "video_u_g.mp4"
_MP4_BYTES = b"\x00\x00\x00\x18ftypmp42"


def _put_video(upload_tmpdir):
    (upload_tmpdir / _VIDEO).write_bytes(_MP4_BYTES)


def test_route_valid_signature_serves_200(client, upload_tmpdir):
    _put_video(upload_tmpdir)
    q = su.sign_video_url(_VIDEO, ttl_seconds=300)
    resp = client.get(f"/api/uploads/video/{_VIDEO}?{q}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/mp4"


def test_route_tampered_signature_403(client, upload_tmpdir):
    _put_video(upload_tmpdir)
    exp, sig = su.sign_video_filename(_VIDEO, ttl_seconds=300)
    resp = client.get(f"/api/uploads/video/{_VIDEO}?exp={exp}&sig={sig}deadbeef")
    assert resp.status_code == 403


def test_route_expired_signature_403(client, upload_tmpdir):
    _put_video(upload_tmpdir)
    exp, sig = su.sign_video_filename(_VIDEO, ttl_seconds=-5)
    resp = client.get(f"/api/uploads/video/{_VIDEO}?exp={exp}&sig={sig}")
    assert resp.status_code == 403


def test_route_unsigned_permissive_default_200_with_warning(
    client, upload_tmpdir, monkeypatch, caplog
):
    # MEDIA_URL_SIGNING_REQUIRED unset -> legacy unsigned URL still serves + warns.
    monkeypatch.delenv("MEDIA_URL_SIGNING_REQUIRED", raising=False)
    _put_video(upload_tmpdir)
    with caplog.at_level("WARNING"):
        resp = client.get(f"/api/uploads/video/{_VIDEO}")
    assert resp.status_code == 200
    assert any("unsigned video URL served" in r.message for r in caplog.records)


def test_route_unsigned_enforced_403(client, upload_tmpdir, monkeypatch):
    monkeypatch.setenv("MEDIA_URL_SIGNING_REQUIRED", "1")
    _put_video(upload_tmpdir)
    resp = client.get(f"/api/uploads/video/{_VIDEO}")
    assert resp.status_code == 403


def test_route_present_but_invalid_sig_403_even_when_not_enforced(
    client, upload_tmpdir, monkeypatch
):
    # The tamper guard ignores the enforcement flag: a PRESENT-but-bad sig is 403
    # even in permissive mode.
    monkeypatch.delenv("MEDIA_URL_SIGNING_REQUIRED", raising=False)
    _put_video(upload_tmpdir)
    resp = client.get(f"/api/uploads/video/{_VIDEO}?exp=1&sig=garbage")
    assert resp.status_code == 403


def test_route_prefix_guard_still_rejects(client, upload_tmpdir):
    # Non-video_ prefix / non-mp4 -> 400 before any signature check.
    resp = client.get(f"/api/uploads/video/notavideo.txt?{su.sign_video_url('notavideo.txt')}")
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid filename"


def test_route_traversal_guard_still_rejects(client, upload_tmpdir):
    resp = client.get("/api/uploads/video/sub/dir/video_u_g.mp4")
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid filename"


# ---------------------------------------------------------------------------
# 3. _record_usage burst-and-remove: row still written with the right cost when
#    usage.cost is None and /generation is mocked; db.session.remove() fired.
# ---------------------------------------------------------------------------
def test_record_usage_cost_none_releases_conn_and_writes_row(
    flask_core, test_user, monkeypatch
):
    from app.extensions import db
    from app.models.usage_log import UsageLog
    from app.services.openrouter_service import OpenRouterService
    import app.services.openrouter_service as ors_mod

    # Keep the deprecation memo off the DB (mirrors the cov module's autouse).
    monkeypatch.setattr(ors_mod, "_expiration_for", lambda model: None, raising=False)

    removed = {"n": 0}
    real_remove = db.session.remove

    def counting_remove():
        removed["n"] += 1
        return real_remove()

    monkeypatch.setattr(db.session, "remove", counting_remove)

    def fake_request(method, url, **kw):
        assert method == "GET"
        assert "generation?id=gen-release" in url

        class _R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"total_cost": 0.77}}

        return _R()

    monkeypatch.setattr(ors_mod._session, "request", fake_request)

    with flask_core.app_context():
        OpenRouterService._record_usage(
            test_user["_id"], None, "openai/gpt-4o",
            {"prompt_tokens": 2, "completion_tokens": 2},  # no 'cost' key
            "chat",
            generation_id="gen-release",
        )
        row = (db.session.query(UsageLog)
               .order_by(UsageLog.created_at.desc()).first())

    # Connection was returned to the pool before the /generation hop...
    assert removed["n"] >= 1
    # ...and the row was still written with the gen-id cost via a fresh checkout.
    assert row is not None
    assert float(row.cost_usd) == pytest.approx(0.77)
    assert row.generation_id == "gen-release"


def test_record_usage_local_pricing_fallback_no_remove(
    flask_core, test_user, monkeypatch
):
    # No generation_id -> the /generation branch (and its remove()) is skipped;
    # local pricing still writes the row. Guards the fallback path.
    from app.extensions import db
    from app.models.usage_log import UsageLog
    from app.services.openrouter_service import OpenRouterService
    import app.services.openrouter_service as ors_mod
    import app.services.model_registry_service as mrs

    monkeypatch.setattr(ors_mod, "_expiration_for", lambda model: None, raising=False)
    monkeypatch.setattr(
        mrs.ModelRegistryService, "get_pricing",
        lambda self, mid: {"prompt": 0.001, "completion": 0.002, "cached": 0.0},
    )

    with flask_core.app_context():
        OpenRouterService._record_usage(
            test_user["_id"], None, "openai/gpt-4o",
            {"prompt_tokens": 100, "completion_tokens": 50}, "chat",
        )
        row = (db.session.query(UsageLog)
               .order_by(UsageLog.created_at.desc()).first())

    assert row is not None
    assert float(row.cost_usd) == pytest.approx(0.001 * 100 + 0.002 * 50)
