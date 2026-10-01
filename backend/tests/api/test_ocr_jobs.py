"""OCR job history: owner isolation + list omits file content."""
import uuid

from app.models.ocr_job import OcrJobModel


def _job(flask_core, user_id, **kw):
    files = kw.pop(
        "files",
        [
            {
                "upload_id": str(uuid.uuid4()),
                "original_name": "scan.pdf",
                "status": "ok",
                "content": "SECRET TEXT FROM THE DOCUMENT",
                "error": None,
            }
        ],
    )
    with flask_core.app_context():
        return OcrJobModel.create(
            user_id=str(user_id),
            prompt=kw.get("prompt", "extract totals"),
            files=files,
            status=kw.get("status", "done"),
        )


def test_list_empty(client, auth_headers):
    resp = client.get("/api/ocr/jobs", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"jobs": []}


def test_list_omits_content_and_foreign_rows(
    client, flask_core, test_user, plain_user, auth_headers
):
    mine = _job(flask_core, test_user["_id"])
    _job(flask_core, plain_user["_id"], prompt="theirs")

    resp = client.get("/api/ocr/jobs", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()["jobs"]
    assert len(rows) == 1
    assert rows[0]["_id"] == mine["_id"]
    assert rows[0]["files"]
    assert "content" not in rows[0]["files"][0]
    assert rows[0]["files"][0]["original_name"] == "scan.pdf"


def test_get_returns_content_owner_only(
    client, flask_core, test_user, plain_headers, auth_headers
):
    rec = _job(flask_core, test_user["_id"])
    ok = client.get(f"/api/ocr/jobs/{rec['_id']}", headers=auth_headers)
    assert ok.status_code == 200
    assert ok.json()["files"][0]["content"] == "SECRET TEXT FROM THE DOCUMENT"

    foreign = client.get(f"/api/ocr/jobs/{rec['_id']}", headers=plain_headers)
    assert foreign.status_code == 404
    assert foreign.json()["error"] == "Job not found"


def test_delete_owner_only(client, flask_core, test_user, plain_headers, auth_headers):
    rec = _job(flask_core, test_user["_id"])
    denied = client.delete(f"/api/ocr/jobs/{rec['_id']}", headers=plain_headers)
    assert denied.status_code == 404

    gone = client.delete(f"/api/ocr/jobs/{rec['_id']}", headers=auth_headers)
    assert gone.status_code == 200
    missing = client.get(f"/api/ocr/jobs/{rec['_id']}", headers=auth_headers)
    assert missing.status_code == 404
