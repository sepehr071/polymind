"""Integration tests for the admin router (app/api/routers/admin.py).

Mirror tests/api/test_auth.py: drive the full path TestClient -> flask_ctx
app_context (worker thread) -> real model facades on Postgres -> legacy JSON.
Every admin route is gated by ``require_admin`` (user.role == 'admin'); we cover
the happy path (status + _id shape), auth gating (no token 401 token_missing,
non-admin 403), and the per-route error codes (400/404).
"""
import uuid


# ---------------------------------------------------------------------------
# Helpers: seed entities via the real model facades inside an app_context.
# ---------------------------------------------------------------------------
def _seed_user(flask_core, *, email, role="user", display_name="Seed User"):
    from app.models.user import UserModel

    with flask_core.app_context():
        return UserModel.create(
            email=email, password="TestPassword123!",
            display_name=display_name, role=role,
        )


def _seed_template(flask_core, *, name="Tmpl", model_id="openai/gpt-5"):
    from app.models.llm_config import LLMConfigModel

    with flask_core.app_context():
        return LLMConfigModel.create(
            name=name, model_id=model_id, model_name=model_id,
            owner_id=None, visibility="template",
        )


# ---------------------------------------------------------------------------
# Auth gating matrix (representative routes).
# ---------------------------------------------------------------------------
def test_users_no_token_401_token_missing(client):
    resp = client.get("/api/admin/users")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_users_non_admin_403(client, plain_headers):
    resp = client.get("/api/admin/users", headers=plain_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Admin access required"


def test_users_manager_role_403(client, auth_headers):
    # auth_headers is the manager test_user — still not admin.
    resp = client.get("/api/admin/users", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Admin access required"


def test_analytics_no_token_401(client):
    resp = client.get("/api/admin/analytics")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_companies_non_admin_403(client, plain_headers):
    resp = client.get("/api/admin/companies", headers=plain_headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /users — list + pagination + filters.
# ---------------------------------------------------------------------------
def test_get_users_happy_path(client, admin_headers, admin_user, plain_user):
    resp = client.get("/api/admin/users", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "users" in body
    assert body["total"] >= 2
    assert body["page"] == 1
    assert body["limit"] == 20
    # Legacy _id alias on every row.
    assert all("_id" in u for u in body["users"])
    # password_hash present in to_dict()? list view does not strip — just confirm shape.
    emails = {u["email"] for u in body["users"]}
    assert "admin@gmail.com" in emails
    assert "plain@gmail.com" in emails


def test_get_users_role_filter(client, admin_headers, admin_user, plain_user):
    resp = client.get("/api/admin/users?role=admin", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert all(u["role"] == "admin" for u in body["users"])
    assert body["total"] >= 1


def test_get_users_search(client, admin_headers, admin_user, plain_user):
    resp = client.get("/api/admin/users?search=plain", headers=admin_headers)
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()["users"]}
    assert "plain@gmail.com" in emails


def test_get_users_exclude_banned(client, admin_headers, admin_user, banned_user):
    resp = client.get("/api/admin/users?include_banned=false", headers=admin_headers)
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()["users"]}
    assert "banned@gmail.com" not in emails


# ---------------------------------------------------------------------------
# GET /users/{id} — detail + stats, 404.
# ---------------------------------------------------------------------------
def test_get_user_detail_happy(client, admin_headers, plain_user):
    resp = client.get(f"/api/admin/users/{plain_user['_id']}", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["_id"] == str(plain_user["_id"])
    assert body["user"]["email"] == "plain@gmail.com"
    # Detail view strips the password hash.
    assert "password_hash" not in body["user"]
    assert "stats" in body["user"]
    assert "conversation_count" in body["user"]["stats"]
    assert "config_count" in body["user"]["stats"]


def test_get_user_detail_404(client, admin_headers):
    resp = client.get(f"/api/admin/users/{uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "User not found"


# ---------------------------------------------------------------------------
# PATCH /users/{id} — role update, validation, 404.
# ---------------------------------------------------------------------------
def test_update_user_role_happy(client, admin_headers, plain_user):
    resp = client.patch(f"/api/admin/users/{plain_user['_id']}",
                        headers=admin_headers, json={"role": "manager"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["role"] == "manager"
    assert "password_hash" not in resp.json()["user"]


def test_update_user_invalid_role_400(client, admin_headers, plain_user):
    resp = client.patch(f"/api/admin/users/{plain_user['_id']}",
                        headers=admin_headers, json={"role": "superuser"})
    assert resp.status_code == 400
    assert "role must be one of" in resp.json()["error"]


def test_update_user_no_fields_400(client, admin_headers, plain_user):
    resp = client.patch(f"/api/admin/users/{plain_user['_id']}",
                        headers=admin_headers, json={"nope": 1})
    assert resp.status_code == 400
    assert resp.json()["error"] == "No valid fields to update"


def test_update_user_404(client, admin_headers):
    resp = client.patch(f"/api/admin/users/{uuid.uuid4()}",
                        headers=admin_headers, json={"role": "user"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /users/{id}/ban — happy + guard rails.
# ---------------------------------------------------------------------------
def test_ban_user_happy(client, admin_headers, plain_user):
    resp = client.put(f"/api/admin/users/{plain_user['_id']}/ban",
                      headers=admin_headers, json={"reason": "spam"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"] == "User banned"
    assert body["reason"] == "spam"


def test_ban_self_400(client, admin_headers, admin_user):
    resp = client.put(f"/api/admin/users/{admin_user['_id']}/ban",
                      headers=admin_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Cannot ban yourself"


def test_ban_other_admin_400(client, admin_headers, flask_core):
    other_admin = _seed_user(flask_core, email="other-admin@gmail.com", role="admin")
    resp = client.put(f"/api/admin/users/{other_admin['_id']}/ban",
                      headers=admin_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Cannot ban admin users"


def test_ban_user_404(client, admin_headers):
    resp = client.put(f"/api/admin/users/{uuid.uuid4()}/ban",
                      headers=admin_headers, json={})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /users/{id}/unban.
# ---------------------------------------------------------------------------
def test_unban_user_happy(client, admin_headers, banned_user):
    resp = client.put(f"/api/admin/users/{banned_user['_id']}/unban",
                      headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "User unbanned"


def test_unban_user_404(client, admin_headers):
    resp = client.put(f"/api/admin/users/{uuid.uuid4()}/unban", headers=admin_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /users/{id}/limits.
# ---------------------------------------------------------------------------
def test_set_user_limits_happy(client, admin_headers, plain_user):
    resp = client.put(f"/api/admin/users/{plain_user['_id']}/limits",
                      headers=admin_headers, json={"tokens_limit": 5000})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"] == "User limits updated"
    assert body["tokens_limit"] == 5000


def test_set_user_limits_404(client, admin_headers):
    resp = client.put(f"/api/admin/users/{uuid.uuid4()}/limits",
                      headers=admin_headers, json={"tokens_limit": 1})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /users/{id}/history.
# ---------------------------------------------------------------------------
def test_get_user_history_happy(client, admin_headers, plain_user):
    resp = client.get(f"/api/admin/users/{plain_user['_id']}/history",
                      headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "conversations" in body
    assert body["user"]["id"] == str(plain_user["_id"])
    assert body["user"]["email"] == "plain@gmail.com"


def test_get_user_history_404(client, admin_headers):
    resp = client.get(f"/api/admin/users/{uuid.uuid4()}/history", headers=admin_headers)
    assert resp.status_code == 404


def test_get_user_history_list_omits_messages_by_default(client, admin_headers, plain_user, flask_core):
    from app.models.conversation import ConversationModel
    from app.models.llm_config import LLMConfigModel
    from app.models.message import MessageModel

    with flask_core.app_context():
        cfg = LLMConfigModel.create(name="C", model_id="m", model_name="m",
                                    owner_id=plain_user["_id"])
        conv = ConversationModel.create(plain_user["_id"], str(cfg["_id"]))
        MessageModel.create(str(conv["_id"]), role="user", content="hi")

    resp = client.get(f"/api/admin/users/{plain_user['_id']}/history",
                      headers=admin_headers)
    assert resp.status_code == 200, resp.text
    convs = resp.json()["conversations"]
    assert len(convs) == 1
    # Light list: no eager messages on the conversation rows.
    assert "messages" not in convs[0]


def test_get_user_history_messages_lazy(client, admin_headers, plain_user, flask_core):
    from app.models.conversation import ConversationModel
    from app.models.llm_config import LLMConfigModel
    from app.models.message import MessageModel

    with flask_core.app_context():
        cfg = LLMConfigModel.create(name="C", model_id="m", model_name="m",
                                    owner_id=plain_user["_id"])
        conv = ConversationModel.create(plain_user["_id"], str(cfg["_id"]))
        MessageModel.create(str(conv["_id"]), role="user", content="hi")
        conv_id = str(conv["_id"])

    resp = client.get(
        f"/api/admin/users/{plain_user['_id']}/history/{conv_id}/messages",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    msgs = resp.json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["content"] == "hi"
    assert "_id" in msgs[0]


def test_get_user_history_messages_wrong_user_404(client, admin_headers, plain_user, flask_core):
    # A conversation that does NOT belong to the target user -> 404.
    other = _seed_user(flask_core, email="other-hist@gmail.com")
    from app.models.conversation import ConversationModel
    from app.models.llm_config import LLMConfigModel

    with flask_core.app_context():
        cfg = LLMConfigModel.create(name="C", model_id="m", model_name="m",
                                    owner_id=other["_id"])
        conv = ConversationModel.create(other["_id"], str(cfg["_id"]))
        conv_id = str(conv["_id"])

    resp = client.get(
        f"/api/admin/users/{plain_user['_id']}/history/{conv_id}/messages",
        headers=admin_headers,
    )
    assert resp.status_code == 404


def test_get_user_history_messages_non_admin_403(client, plain_headers, plain_user):
    resp = client.get(
        f"/api/admin/users/{plain_user['_id']}/history/{uuid.uuid4()}/messages",
        headers=plain_headers,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Templates CRUD.
# ---------------------------------------------------------------------------
def test_get_templates_happy(client, admin_headers, flask_core):
    _seed_template(flask_core, name="Listed")
    resp = client.get("/api/admin/templates", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "templates" in body
    names = {t["name"] for t in body["templates"]}
    assert "Listed" in names
    assert all("_id" in t for t in body["templates"])


def test_create_template_happy(client, admin_headers):
    resp = client.post("/api/admin/templates", headers=admin_headers, json={
        "name": "New Tmpl", "model_id": "openai/gpt-5", "description": "d",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["template"]["name"] == "New Tmpl"
    assert body["template"]["visibility"] == "template"
    assert "_id" in body["template"]


def test_create_template_missing_fields_400(client, admin_headers):
    resp = client.post("/api/admin/templates", headers=admin_headers, json={"name": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Name and model_id are required"


def test_update_template_happy(client, admin_headers, flask_core):
    tmpl = _seed_template(flask_core, name="Before")
    resp = client.put(f"/api/admin/templates/{tmpl['_id']}",
                      headers=admin_headers, json={"name": "After"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["template"]["name"] == "After"


def test_update_template_404(client, admin_headers):
    resp = client.put(f"/api/admin/templates/{uuid.uuid4()}",
                      headers=admin_headers, json={"name": "x"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Template not found"


def test_delete_template_happy(client, admin_headers, flask_core):
    tmpl = _seed_template(flask_core, name="ToDelete")
    resp = client.delete(f"/api/admin/templates/{tmpl['_id']}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Template deleted"


def test_delete_template_404(client, admin_headers):
    resp = client.delete(f"/api/admin/templates/{uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Analytics.
# ---------------------------------------------------------------------------
def test_analytics_happy(client, admin_headers, plain_user):
    resp = client.get("/api/admin/analytics?days=7", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    a = resp.json()["analytics"]
    assert a["period_days"] == 7
    assert a["users"]["total"] >= 1
    assert "conversations" in a
    assert "messages" in a
    assert "tokens" in a
    assert "model_usage" in a


def test_cost_analytics_happy(client, admin_headers):
    resp = client.get("/api/admin/analytics/costs?days=14", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    costs = resp.json()["costs"]
    assert costs["period_days"] == 14
    assert "by_model" in costs
    assert "total_cost_usd" in costs


def test_timeseries_analytics_happy(client, admin_headers):
    resp = client.get("/api/admin/analytics/timeseries?days=5", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    ts = resp.json()["timeseries"]
    assert ts["period_days"] == 5
    assert ts["granularity"] == "day"
    # Daily-filled series length == days.
    assert len(ts["messages"]) == 5
    assert len(ts["users"]) == 5
    assert len(ts["conversations"]) == 5


# ---------------------------------------------------------------------------
# Audit logs.
# ---------------------------------------------------------------------------
def test_audit_logs_happy(client, admin_headers, admin_user, flask_core):
    from app.models.audit_log import AuditLogModel

    with flask_core.app_context():
        AuditLogModel.create(action="user_banned", admin_id=admin_user["_id"],
                             target_id=str(uuid.uuid4()), target_type="user")
    resp = client.get("/api/admin/audit-logs", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert body["skip"] == 0
    assert body["limit"] == 50
    # Hydrated admin email.
    assert any(log.get("admin_email") == "admin@gmail.com" for log in body["logs"])


def test_audit_logs_action_filter(client, admin_headers, admin_user, flask_core):
    from app.models.audit_log import AuditLogModel

    with flask_core.app_context():
        AuditLogModel.create(action="role_changed", admin_id=admin_user["_id"])
        AuditLogModel.create(action="user_banned", admin_id=admin_user["_id"])
    resp = client.get("/api/admin/audit-logs?action=role_changed", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert all(log["action"] == "role_changed" for log in body["logs"])


# ---------------------------------------------------------------------------
# Cross-company analytics.
# ---------------------------------------------------------------------------
def test_list_companies_empty(client, admin_headers):
    resp = client.get("/api/admin/companies", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "companies" in body
    assert "totals" in body
    assert body["days"] == 30


def test_list_companies_with_workspace(client, admin_headers, admin_user, flask_core):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        WorkspaceModel.create(name="Acme Co", owner_id=admin_user["_id"], type="team")
    resp = client.get("/api/admin/companies?days=10", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["days"] == 10
    names = {c["name"] for c in body["companies"]}
    assert "Acme Co" in names
    assert all("_id" in c for c in body["companies"])


def test_company_detail_happy(client, admin_headers, admin_user, flask_core):
    from app.models.workspace import WorkspaceModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Detail Co", owner_id=admin_user["_id"], type="team")
    resp = client.get(f"/api/admin/companies/{ws['_id']}", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["workspace"]["_id"] == str(ws["_id"])
    assert body["workspace"]["name"] == "Detail Co"
    assert "projects" in body
    assert "top_users" in body
    assert "by_role" in body


def test_company_detail_404(client, admin_headers):
    resp = client.get(f"/api/admin/companies/{uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"] == "not found"


def test_company_detail_garbage_id_404(client, admin_headers):
    # company_detail returns None on un-parseable id -> 404.
    resp = client.get("/api/admin/companies/not-a-uuid", headers=admin_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Users overview.
# ---------------------------------------------------------------------------
def test_users_overview_happy(client, admin_headers, admin_user, plain_user):
    resp = client.get("/api/admin/users-overview?days=7", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "users" in body
    assert body["days"] == 7
    assert body["page"] == 1
    assert "totals" in body
    assert all("_id" in u for u in body["users"])


def test_users_overview_invalid_role_400(client, admin_headers):
    resp = client.get("/api/admin/users-overview?role=superuser", headers=admin_headers)
    assert resp.status_code == 400
    assert "role must be one of" in resp.json()["error"]


def test_users_overview_non_admin_403(client, plain_headers):
    resp = client.get("/api/admin/users-overview", headers=plain_headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Route-registration smoke.
# ---------------------------------------------------------------------------
def test_admin_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/admin/users" in paths
    assert "/api/admin/users/{user_id}" in paths
    assert "/api/admin/templates" in paths
    assert "/api/admin/analytics" in paths
    assert "/api/admin/analytics/costs" in paths
    assert "/api/admin/analytics/timeseries" in paths
    assert "/api/admin/audit-logs" in paths
    assert "/api/admin/companies" in paths
    assert "/api/admin/companies/{wid}" in paths
    assert "/api/admin/users-overview" in paths
