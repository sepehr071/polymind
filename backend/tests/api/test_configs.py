"""Integration tests for the FastAPI configs + prompt-templates routers
(app/api/routers/configs.py).

Mirrors tests/api/test_auth.py: real model facades on Postgres, the flask_ctx
bridge, legacy-shaped JSON. The only external call any of these routes makes is
``OpenRouterService.chat_completion`` (from ``/api/configs/enhance-prompt``),
which is monkeypatched so no test hits a real upstream.

Two prefixes under test:
  * ``/api/configs``           — LLMConfig CRUD + publish/duplicate/enhance
  * ``/api/prompt-templates``  — read for any authed user, write = admin only

LLMConfig.visibility semantics (private/public/template/project) drive the
cross-owner visibility tests. Project-scoped configs need a workspace + owner
membership so ``check_project_access`` grants the caller editor/viewer.
"""
import uuid

import pytest

from app.services.openrouter_service import OpenRouterService


# A canned non-streaming OpenRouter completion for enhance-prompt.
_FAKE_COMPLETION = {
    "choices": [{
        "message": {"content": "  An improved, sharper system prompt.  "},
        "finish_reason": "stop",
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


@pytest.fixture(autouse=True)
def _mock_openrouter(monkeypatch):
    """Patch the only OpenRouter entrypoint this router can hit."""
    monkeypatch.setattr(
        OpenRouterService, "chat_completion",
        staticmethod(lambda *a, **k: dict(_FAKE_COMPLETION)),
    )
    yield


# ---------------------------------------------------------------------------
# Seeding helpers — all run inside the Flask app_context.
# ---------------------------------------------------------------------------
def _seed_workspace(flask_core, owner_id, *, role="owner", name="Acme Co"):
    """Create a workspace owned by ``owner_id`` + an active membership row."""
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, role, status="active")
        return ws


def _seed_project_via_api(client, headers, workspace_id, name="Alpha"):
    """Create a project through the API (mirrors production owner-grant path)."""
    resp = client.post("/api/projects/create", headers=headers,
                       json={"workspace_id": str(workspace_id), "name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_config(client, headers, **overrides):
    """POST /api/configs with sensible defaults, returning the created doc."""
    body = {"name": "My Persona", "model_id": "openai/gpt-5"}
    body.update(overrides)
    resp = client.post("/api/configs", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["config"]


def _seed_template(flask_core, *, name="Greeting", category="general",
                   template_text="Hello {name}"):
    from app.models.prompt_template import PromptTemplateModel

    with flask_core.app_context():
        return PromptTemplateModel.create(
            name=name, category=category, template_text=template_text,
        )


def _other_user(flask_core, *, email):
    from app.models.user import UserModel

    with flask_core.app_context():
        return UserModel.create(email=email, password="TestPassword123!",
                                display_name="Other", role="user")


# ===========================================================================
# /api/configs — auth gating.
# ===========================================================================
def test_get_configs_no_token_401(client):
    resp = client.get("/api/configs")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_create_config_no_token_401(client):
    resp = client.post("/api/configs", json={"name": "x"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_get_config_no_token_401(client):
    resp = client.get(f"/api/configs/{uuid.uuid4()}")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_configs_banned_user_403(client, banned_user, mint_token):
    token = mint_token(banned_user["_id"], role="user")
    resp = client.get("/api/configs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["error"] == "Account has been suspended"


# ===========================================================================
# /api/configs — create happy path + legacy _id shape.
# ===========================================================================
def test_create_config_returns_legacy_id_shape(client, plain_headers):
    cfg = _create_config(client, plain_headers, name="Summarizer")
    # Legacy Mongo alias: row.to_dict() emits '_id'.
    assert "_id" in cfg
    uuid.UUID(str(cfg["_id"]))  # valid UUID string
    assert cfg["name"] == "Summarizer"
    assert cfg["model_id"] == "openai/gpt-5"
    assert cfg["visibility"] == "private"  # default w/o project_id


def test_create_config_name_required_400(client, plain_headers):
    resp = client.post("/api/configs", headers=plain_headers,
                       json={"name": "", "model_id": "openai/gpt-5"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Config name is required"


def test_create_config_model_id_required_400(client, plain_headers):
    resp = client.post("/api/configs", headers=plain_headers, json={"name": "Valid"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "model_id is required"


def test_create_config_invalid_visibility_400(client, plain_headers):
    resp = client.post("/api/configs", headers=plain_headers, json={
        "name": "Valid", "model_id": "openai/gpt-5", "visibility": "bogus",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid visibility"


def test_create_config_system_prompt_too_long_400(client, plain_headers):
    resp = client.post("/api/configs", headers=plain_headers, json={
        "name": "Valid", "model_id": "openai/gpt-5", "system_prompt": "x" * 10001,
    })
    assert resp.status_code == 400
    assert "10000" in resp.json()["error"]


# ===========================================================================
# /api/configs — get / list.
# ===========================================================================
def test_list_configs_returns_owned(client, plain_headers):
    _create_config(client, plain_headers, name="One")
    _create_config(client, plain_headers, name="Two")
    resp = client.get("/api/configs", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["limit"] == 50
    assert {c["name"] for c in body["configs"]} == {"One", "Two"}
    assert all("_id" in c for c in body["configs"])


def test_get_config_owner(client, plain_headers):
    cfg = _create_config(client, plain_headers)
    resp = client.get(f"/api/configs/{cfg['_id']}", headers=plain_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["config"]["_id"] == cfg["_id"]


def test_get_config_not_found_404(client, plain_headers):
    resp = client.get(f"/api/configs/{uuid.uuid4()}", headers=plain_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Config not found"


def test_get_private_config_other_user_404(client, plain_headers, plain_user,
                                           flask_core, mint_token):
    cfg = _create_config(client, plain_headers)  # private, owned by plain_user
    other = _other_user(flask_core, email="stranger@gmail.com")
    other_headers = {"Authorization": f"Bearer {mint_token(other['_id'], role='user')}",
                     "Content-Type": "application/json"}
    resp = client.get(f"/api/configs/{cfg['_id']}", headers=other_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Config not found"


def test_get_public_config_other_user_200(client, plain_headers, flask_core,
                                          mint_token):
    cfg = _create_config(client, plain_headers)
    # Publish it, then a stranger can read it.
    client.post(f"/api/configs/{cfg['_id']}/publish", headers=plain_headers)
    other = _other_user(flask_core, email="reader@gmail.com")
    other_headers = {"Authorization": f"Bearer {mint_token(other['_id'], role='user')}",
                     "Content-Type": "application/json"}
    resp = client.get(f"/api/configs/{cfg['_id']}", headers=other_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["config"]["visibility"] == "public"


# ===========================================================================
# /api/configs — update / cannot_reassign_project / delete.
# ===========================================================================
def test_update_config_owner(client, plain_headers):
    cfg = _create_config(client, plain_headers, name="Before")
    resp = client.put(f"/api/configs/{cfg['_id']}", headers=plain_headers,
                      json={"name": "After", "description": "new"})
    assert resp.status_code == 200, resp.text
    updated = resp.json()["config"]
    assert updated["name"] == "After"
    assert updated["description"] == "new"


def test_update_config_not_owner_404(client, plain_headers, flask_core, mint_token):
    cfg = _create_config(client, plain_headers)
    other = _other_user(flask_core, email="intruder@gmail.com")
    other_headers = {"Authorization": f"Bearer {mint_token(other['_id'], role='user')}",
                     "Content-Type": "application/json"}
    resp = client.put(f"/api/configs/{cfg['_id']}", headers=other_headers,
                      json={"name": "Hijack"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Config not found"


def test_update_config_invalid_visibility_400(client, plain_headers):
    cfg = _create_config(client, plain_headers)
    resp = client.put(f"/api/configs/{cfg['_id']}", headers=plain_headers,
                      json={"visibility": "nope"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid visibility"


def test_update_config_cannot_reassign_project_400(client, plain_headers):
    cfg = _create_config(client, plain_headers)  # personal-scope (project_id None)
    resp = client.put(f"/api/configs/{cfg['_id']}", headers=plain_headers,
                      json={"project_id": str(uuid.uuid4())})
    assert resp.status_code == 400
    assert resp.json()["error"] == "cannot_reassign_project"


def test_delete_config_owner(client, plain_headers):
    cfg = _create_config(client, plain_headers)
    resp = client.delete(f"/api/configs/{cfg['_id']}", headers=plain_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Config deleted"
    # Gone.
    assert client.get(f"/api/configs/{cfg['_id']}",
                      headers=plain_headers).status_code == 404


def test_delete_config_not_owner_404(client, plain_headers, flask_core, mint_token):
    cfg = _create_config(client, plain_headers)
    other = _other_user(flask_core, email="del@gmail.com")
    other_headers = {"Authorization": f"Bearer {mint_token(other['_id'], role='user')}"}
    resp = client.delete(f"/api/configs/{cfg['_id']}", headers=other_headers)
    assert resp.status_code == 404


# ===========================================================================
# /api/configs — publish / unpublish / duplicate.
# ===========================================================================
def test_publish_unpublish_config(client, plain_headers):
    cfg = _create_config(client, plain_headers)
    pub = client.post(f"/api/configs/{cfg['_id']}/publish", headers=plain_headers)
    assert pub.status_code == 200
    assert pub.json() == {"message": "Config published", "visibility": "public"}

    unp = client.post(f"/api/configs/{cfg['_id']}/unpublish", headers=plain_headers)
    assert unp.status_code == 200
    assert unp.json() == {"message": "Config unpublished", "visibility": "private"}


def test_publish_not_owner_404(client, plain_headers, flask_core, mint_token):
    cfg = _create_config(client, plain_headers)
    other = _other_user(flask_core, email="pub@gmail.com")
    other_headers = {"Authorization": f"Bearer {mint_token(other['_id'], role='user')}"}
    resp = client.post(f"/api/configs/{cfg['_id']}/publish", headers=other_headers)
    assert resp.status_code == 404


def test_duplicate_own_config(client, plain_headers):
    cfg = _create_config(client, plain_headers, name="Original")
    resp = client.post(f"/api/configs/{cfg['_id']}/duplicate", headers=plain_headers,
                       json={"name": "Clone"})
    assert resp.status_code == 201, resp.text
    dup = resp.json()["config"]
    assert dup["name"] == "Clone"
    assert dup["_id"] != cfg["_id"]
    assert dup["visibility"] == "private"


def test_duplicate_private_config_other_user_404(client, plain_headers, flask_core,
                                                 mint_token):
    cfg = _create_config(client, plain_headers)  # private
    other = _other_user(flask_core, email="dup@gmail.com")
    other_headers = {"Authorization": f"Bearer {mint_token(other['_id'], role='user')}",
                     "Content-Type": "application/json"}
    resp = client.post(f"/api/configs/{cfg['_id']}/duplicate", headers=other_headers,
                       json={})
    assert resp.status_code == 404


def test_duplicate_public_config_other_user_201(client, plain_headers, flask_core,
                                                mint_token):
    cfg = _create_config(client, plain_headers)
    client.post(f"/api/configs/{cfg['_id']}/publish", headers=plain_headers)
    other = _other_user(flask_core, email="dupok@gmail.com")
    other_headers = {"Authorization": f"Bearer {mint_token(other['_id'], role='user')}",
                     "Content-Type": "application/json"}
    resp = client.post(f"/api/configs/{cfg['_id']}/duplicate", headers=other_headers,
                       json={})
    assert resp.status_code == 201, resp.text
    # The duplicate is owned by the new user + reset to private.
    assert resp.json()["config"]["visibility"] == "private"


# ===========================================================================
# /api/configs — project-scoped create + list (visibility='project').
# ===========================================================================
def test_create_project_config_requires_access(client, plain_headers):
    """A project the caller has no access to => 403 Forbidden (real UUID)."""
    resp = client.post("/api/configs", headers=plain_headers, json={
        "name": "ProjCfg", "model_id": "openai/gpt-5",
        "project_id": str(uuid.uuid4()),
    })
    assert resp.status_code == 403
    assert resp.json()["error"] == "Forbidden"


def test_create_project_config_invalid_project_id_400(client, plain_headers):
    resp = client.post("/api/configs", headers=plain_headers, json={
        "name": "ProjCfg", "model_id": "openai/gpt-5", "project_id": "not-a-uuid",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid project_id"


def test_create_and_list_project_scoped_config(client, auth_headers, test_user,
                                               flask_core):
    """Owner of a workspace+project can create a project-scoped config and see it."""
    ws = _seed_workspace(flask_core, test_user["_id"])
    project = _seed_project_via_api(client, auth_headers, ws["_id"])
    pid = project["_id"] if "_id" in project else project.get("id")

    resp = client.post("/api/configs", headers=auth_headers, json={
        "name": "ProjPersona", "model_id": "openai/gpt-5", "project_id": str(pid),
    })
    assert resp.status_code == 201, resp.text
    cfg = resp.json()["config"]
    # Visibility defaults to 'project' when project_id present; workspace derived.
    assert cfg["visibility"] == "project"
    assert str(cfg["project_id"]) == str(pid)
    assert str(cfg["workspace_id"]) == str(ws["_id"])

    # List scoped to the project surfaces it (viewer access).
    listed = client.get(f"/api/configs?project_id={pid}", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert any(str(c["_id"]) == str(cfg["_id"]) for c in body["configs"])


def test_list_configs_project_forbidden_403(client, plain_headers):
    resp = client.get(f"/api/configs?project_id={uuid.uuid4()}", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Forbidden"


def test_list_configs_project_invalid_400(client, plain_headers):
    resp = client.get("/api/configs?project_id=not-a-uuid", headers=plain_headers)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid project_id"


# ===========================================================================
# /api/configs/enhance-prompt — LLM-backed (mocked).
# ===========================================================================
def test_enhance_prompt_happy(client, plain_headers):
    resp = client.post("/api/configs/enhance-prompt", headers=plain_headers,
                       json={"prompt": "Be helpful."})
    assert resp.status_code == 200, resp.text
    # Mock returns a content string with surrounding whitespace -> trimmed.
    assert resp.json()["enhanced_prompt"] == "An improved, sharper system prompt."


def test_enhance_prompt_empty_400(client, plain_headers):
    resp = client.post("/api/configs/enhance-prompt", headers=plain_headers,
                       json={"prompt": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Prompt is required"


def test_enhance_prompt_too_long_400(client, plain_headers):
    resp = client.post("/api/configs/enhance-prompt", headers=plain_headers,
                       json={"prompt": "x" * 10001})
    assert resp.status_code == 400
    assert "10000" in resp.json()["error"]


def test_enhance_prompt_no_token_401(client):
    resp = client.post("/api/configs/enhance-prompt", json={"prompt": "x"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_enhance_prompt_llm_error_500(client, plain_headers, monkeypatch):
    monkeypatch.setattr(
        OpenRouterService, "chat_completion",
        staticmethod(lambda *a, **k: {"error": {"message": "upstream boom"}}),
    )
    resp = client.post("/api/configs/enhance-prompt", headers=plain_headers,
                       json={"prompt": "Be nice."})
    assert resp.status_code == 500
    assert resp.json()["error"] == "upstream boom"


# ===========================================================================
# /api/prompt-templates — read (any authed user).
# ===========================================================================
def test_templates_list_no_token_401(client):
    resp = client.get("/api/prompt-templates/list")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_templates_list_empty(client, plain_headers):
    resp = client.get("/api/prompt-templates/list", headers=plain_headers)
    assert resp.status_code == 200
    assert resp.json() == {"templates": []}


def test_templates_list_and_category(client, plain_headers, flask_core):
    _seed_template(flask_core, name="A", category="writing")
    _seed_template(flask_core, name="B", category="coding")
    resp = client.get("/api/prompt-templates/list", headers=plain_headers)
    assert resp.status_code == 200
    templates = resp.json()["templates"]
    assert len(templates) == 2
    assert all("_id" in t for t in templates)
    # Legacy aliases surfaced.
    assert all("name" in t and "template_text" in t for t in templates)

    filtered = client.get("/api/prompt-templates/list?category=coding",
                          headers=plain_headers)
    assert filtered.status_code == 200
    only = filtered.json()["templates"]
    assert len(only) == 1
    assert only[0]["name"] == "B"


def test_templates_categories(client, plain_headers, flask_core):
    _seed_template(flask_core, name="A", category="writing")
    _seed_template(flask_core, name="B", category="writing")
    _seed_template(flask_core, name="C", category="coding")
    resp = client.get("/api/prompt-templates/categories", headers=plain_headers)
    assert resp.status_code == 200
    cats = {c["category"]: c["count"] for c in resp.json()["categories"]}
    assert cats == {"writing": 2, "coding": 1}


def test_template_use_increments(client, plain_headers, flask_core):
    tmpl = _seed_template(flask_core)
    resp = client.post(f"/api/prompt-templates/{tmpl['_id']}/use", headers=plain_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Usage recorded"


def test_template_use_not_found_404(client, plain_headers):
    resp = client.post(f"/api/prompt-templates/{uuid.uuid4()}/use", headers=plain_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Template not found"


# ===========================================================================
# /api/prompt-templates — write (admin only).
# ===========================================================================
def test_template_create_requires_admin(client, plain_headers):
    resp = client.post("/api/prompt-templates/create", headers=plain_headers, json={
        "name": "T", "category": "c", "template_text": "body",
    })
    assert resp.status_code == 403
    assert resp.json()["error"] == "Admin access required"


def test_template_create_admin_201(client, admin_headers):
    resp = client.post("/api/prompt-templates/create", headers=admin_headers, json={
        "name": "Welcome", "category": "onboarding", "template_text": "Hi {name}",
        "variables": ["name"], "description": "greet",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["message"] == "Template created"
    assert body["template"]["name"] == "Welcome"
    assert "_id" in body["template"]


def test_template_create_missing_name_400(client, admin_headers):
    resp = client.post("/api/prompt-templates/create", headers=admin_headers, json={
        "category": "c", "template_text": "body",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Name is required"


def test_template_create_missing_category_400(client, admin_headers):
    resp = client.post("/api/prompt-templates/create", headers=admin_headers, json={
        "name": "T", "template_text": "body",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Category is required"


def test_template_create_missing_text_400(client, admin_headers):
    resp = client.post("/api/prompt-templates/create", headers=admin_headers, json={
        "name": "T", "category": "c",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Template text is required"


def test_template_update_admin(client, admin_headers, flask_core):
    tmpl = _seed_template(flask_core, name="Old")
    resp = client.put(f"/api/prompt-templates/{tmpl['_id']}", headers=admin_headers,
                      json={"name": "New", "category": "fresh"})
    assert resp.status_code == 200
    assert resp.json()["message"] == "Template updated"
    # Reflected in list.
    listed = client.get("/api/prompt-templates/list", headers=admin_headers).json()
    names = {t["name"] for t in listed["templates"]}
    assert "New" in names


def test_template_update_requires_admin(client, plain_headers, flask_core):
    tmpl = _seed_template(flask_core)
    resp = client.put(f"/api/prompt-templates/{tmpl['_id']}", headers=plain_headers,
                      json={"name": "X"})
    assert resp.status_code == 403
    assert resp.json()["error"] == "Admin access required"


def test_template_update_not_found_404(client, admin_headers):
    resp = client.put(f"/api/prompt-templates/{uuid.uuid4()}", headers=admin_headers,
                      json={"name": "X"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Template not found"


def test_template_delete_admin(client, admin_headers, flask_core):
    tmpl = _seed_template(flask_core)
    resp = client.delete(f"/api/prompt-templates/{tmpl['_id']}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Template deleted"


def test_template_delete_requires_admin(client, plain_headers, flask_core):
    tmpl = _seed_template(flask_core)
    resp = client.delete(f"/api/prompt-templates/{tmpl['_id']}", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Admin access required"


def test_template_delete_not_found_404(client, admin_headers):
    resp = client.delete(f"/api/prompt-templates/{uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "Template not found"


# ===========================================================================
# /api/configs — image-assistant parameter validation.
# ===========================================================================
def _seed_upload(flask_core, owner_id, *, name="ref.png"):
    from app.models.upload import UploadModel

    with flask_core.app_context():
        return UploadModel.create(
            user_id=str(owner_id), filename=f"{uuid.uuid4().hex}.png",
            original_name=name, mime_type="image/png", size=10, type="image",
        )


def test_create_image_assistant_bad_kind_400(client, plain_headers):
    resp = client.post("/api/configs", headers=plain_headers, json={
        "name": "Painter", "model_id": "google/img",
        "parameters": {"kind": "video"},
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid parameters.kind"


def test_create_image_assistant_sanitizes_base_images(
    client, plain_headers, plain_user, flask_core
):
    owned = _seed_upload(flask_core, plain_user["_id"])
    other = _other_user(flask_core, email="stranger@gmail.com")
    not_owned = _seed_upload(flask_core, other["_id"], name="theirs.png")

    cfg = _create_config(
        client, plain_headers,
        parameters={
            "kind": "image",
            "base_images": [
                # Owned: kept, narrowed to whitelisted keys (junk dropped).
                {"upload_id": owned["_id"], "url": "u", "thumb_url": "t",
                 "name": "ref", "junk": "x"},
                # Not owned by caller: dropped.
                {"upload_id": not_owned["_id"]},
                # Missing upload_id: dropped.
                {"url": "nope"},
            ],
        },
    )
    base = cfg["parameters"]["base_images"]
    assert len(base) == 1
    assert base[0]["upload_id"] == owned["_id"]
    assert set(base[0].keys()) == {"upload_id", "url", "thumb_url", "name"}


def test_update_image_assistant_validates_base_images(
    client, plain_headers, plain_user, flask_core
):
    cfg = _create_config(client, plain_headers,
                         parameters={"kind": "image", "base_images": []})
    other = _other_user(flask_core, email="stranger2@gmail.com")
    not_owned = _seed_upload(flask_core, other["_id"], name="theirs.png")

    resp = client.put(f"/api/configs/{cfg['_id']}", headers=plain_headers, json={
        "parameters": {"kind": "image",
                       "base_images": [{"upload_id": not_owned["_id"]}]},
    })
    assert resp.status_code == 200, resp.text
    # The non-owned base image is dropped.
    assert resp.json()["config"]["parameters"]["base_images"] == []


def test_create_text_assistant_kind_passes(client, plain_headers):
    cfg = _create_config(client, plain_headers,
                         parameters={"kind": "text", "temperature": 0.5})
    assert cfg["parameters"]["kind"] == "text"


# ===========================================================================
# Route-registration smoke — proves both prefixes + exact paths registered.
# These will only resolve once the wiring step adds both routers to ALL_ROUTERS,
# so they assert against the live app's route table.
# ===========================================================================
def test_configs_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    # The empty-string route mounts exactly at the prefix (no trailing slash).
    assert "/api/configs" in paths
    assert "/api/configs/{config_id}" in paths
    assert "/api/configs/{config_id}/publish" in paths
    assert "/api/configs/{config_id}/unpublish" in paths
    assert "/api/configs/{config_id}/duplicate" in paths
    assert "/api/configs/enhance-prompt" in paths
    assert "/api/prompt-templates/list" in paths
    assert "/api/prompt-templates/categories" in paths
    assert "/api/prompt-templates/create" in paths
    assert "/api/prompt-templates/{template_id}" in paths
    assert "/api/prompt-templates/{template_id}/use" in paths


# ===========================================================================
# resolve_config ownership/visibility gate (IDOR regression).
#
# The chat /send + /stream handlers feed a raw client-supplied config_id into
# resolve_config and do NOT re-validate ownership, so the resolver MUST gate
# personal-scope configs. Before the fix, a private config with project_id None
# fell straight through to ``return config`` with no owner/visibility check —
# any user could run another user's private persona (leaking system_prompt +
# model_id and mutating its usage stats). These assert the resolver directly.
# ===========================================================================
def _resolve(flask_core, config_id, user_id=None, project_id=None):
    from app.utils.config_resolver import resolve_config

    with flask_core.app_context():
        return resolve_config(config_id, user_id, project_id)


def test_resolver_private_config_blocked_for_other_user(
    client, plain_headers, plain_user, flask_core
):
    """The IDOR: another user's private (personal-scope) config must NOT resolve."""
    cfg = _create_config(client, plain_headers)  # private, owner = plain_user
    other = _other_user(flask_core, email="idor-victim@gmail.com")
    # Stranger passes their own id -> not the owner, not public/template -> None.
    assert _resolve(flask_core, cfg["_id"], str(other["_id"])) is None


def test_resolver_private_config_blocked_when_no_user_id(
    client, plain_headers, flask_core
):
    """No acting user id => cannot prove ownership => private config blocked."""
    cfg = _create_config(client, plain_headers)
    assert _resolve(flask_core, cfg["_id"], None) is None


def test_resolver_private_config_resolves_for_owner(
    client, plain_headers, plain_user, flask_core
):
    """The owner's OWN private config must still resolve (no regression)."""
    cfg = _create_config(client, plain_headers)
    out = _resolve(flask_core, cfg["_id"], str(plain_user["_id"]))
    assert out is not None
    assert str(out["_id"]) == str(cfg["_id"])


def test_resolver_public_config_resolves_for_other_user(
    client, plain_headers, flask_core
):
    """A published (public) config resolves for any user."""
    cfg = _create_config(client, plain_headers)
    client.post(f"/api/configs/{cfg['_id']}/publish", headers=plain_headers)
    other = _other_user(flask_core, email="public-reader@gmail.com")
    out = _resolve(flask_core, cfg["_id"], str(other["_id"]))
    assert out is not None
    assert out["visibility"] == "public"


def test_resolver_template_config_resolves_for_other_user(
    client, admin_user, flask_core, mint_token
):
    """A template config resolves for any user (catalog persona)."""
    admin_headers = {
        "Authorization": f"Bearer {mint_token(admin_user['_id'], role='admin')}",
        "Content-Type": "application/json",
    }
    cfg = _create_config(client, admin_headers, visibility="template")
    other = _other_user(flask_core, email="template-reader@gmail.com")
    out = _resolve(flask_core, cfg["_id"], str(other["_id"]))
    assert out is not None
    assert out["visibility"] == "template"


def test_resolver_quick_and_agent_unaffected(flask_core):
    """quick:/agent: early-return branches stay open (no owner check) for
    CURATED quick models, but an off-allowlist quick id is rejected (the
    denial-of-wallet fix: only QUICK_MODELS keys resolve)."""
    from app.utils.quick_models import QUICK_MODELS

    curated = next(iter(QUICK_MODELS))  # a real curated quick-model id
    quick = _resolve(flask_core, f"quick:{curated}", None)
    assert quick is not None and quick["model_id"] == curated
    # Off-allowlist model id must NOT resolve (would route to a premium model on
    # the shared key otherwise).
    assert _resolve(flask_core, "quick:openai/o1-pro-premium", None) is None
    agent = _resolve(flask_core, "agent:canvas", None)
    assert agent is not None and agent.get("is_agent") is True


def test_resolver_project_config_resolves_for_member(
    client, auth_headers, test_user, flask_core
):
    """Project-scoped config still resolves for the owner with matching scope.

    Project creation requires manager/admin -> use the ``test_user`` (manager)
    + ``auth_headers`` fixtures, mirroring test_create_and_list_project_scoped_config.
    """
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])
    pid = str(proj["_id"] if "_id" in proj else proj.get("id"))
    cfg = _create_config(client, auth_headers, project_id=pid,
                         workspace_id=str(ws["_id"]))
    out = _resolve(flask_core, cfg["_id"], str(test_user["_id"]), pid)
    assert out is not None
    assert str(out["_id"]) == str(cfg["_id"])


def test_resolver_project_config_blocked_without_scope(
    client, auth_headers, test_user, flask_core
):
    """Project-scoped config is invisible when no project context is supplied."""
    ws = _seed_workspace(flask_core, test_user["_id"])
    proj = _seed_project_via_api(client, auth_headers, ws["_id"])
    pid = str(proj["_id"] if "_id" in proj else proj.get("id"))
    cfg = _create_config(client, auth_headers, project_id=pid,
                         workspace_id=str(ws["_id"]))
    # Even the owner gets None without an active project scope (pre-existing rule).
    assert _resolve(flask_core, cfg["_id"], str(test_user["_id"]), None) is None
