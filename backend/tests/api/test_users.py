"""Integration tests for the translated users router (app.api.routers.users).

Covers both merged blueprints (users_bp + ai_preferences_bp -> /api/users):
profile GET/PUT, stats, costs, settings GET/PUT, ai-preferences GET/PUT.

Mirrors tests/api/test_auth.py: real model facades on the unichat_test Postgres,
auth via the conftest fixtures. No external HTTP is touched by these routes.
"""


# ---------------------------------------------------------------------------
# /profile
# ---------------------------------------------------------------------------
def test_get_profile_happy(client, auth_headers, test_user):
    resp = client.get("/api/users/profile", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    prof = resp.json()["profile"]
    assert prof["id"] == str(test_user["_id"])
    assert prof["email"] == "test@gmail.com"
    assert prof["display_name"] == "Test User"
    # created_at must serialize to an ISO string (datetime-or-string tolerant).
    assert isinstance(prof["created_at"], str)


def test_get_profile_no_token_401(client):
    resp = client.get("/api/users/profile")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


def test_get_profile_banned_403(client, banned_user, mint_token):
    token = mint_token(banned_user["_id"], role="user")
    resp = client.get("/api/users/profile",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["error"] == "Account has been suspended"


def test_update_profile_happy(client, auth_headers, test_user):
    resp = client.put("/api/users/profile", headers=auth_headers, json={
        "display_name": "Renamed User",
        "bio": "hello world",
        "avatar_url": "https://example.com/a.png",
    })
    assert resp.status_code == 200, resp.text
    prof = resp.json()["profile"]
    assert prof["display_name"] == "Renamed User"
    assert prof["bio"] == "hello world"
    assert prof["avatar_url"] == "https://example.com/a.png"

    # Persisted: a fresh GET reflects the change.
    again = client.get("/api/users/profile", headers=auth_headers)
    assert again.json()["profile"]["display_name"] == "Renamed User"


def test_update_profile_invalid_display_name_400(client, auth_headers):
    resp = client.put("/api/users/profile", headers=auth_headers,
                      json={"display_name": "x"})  # < 2 chars
    assert resp.status_code == 400
    assert "at least 2 characters" in resp.json()["error"]


def test_update_profile_bio_truncated_to_500(client, auth_headers):
    long_bio = "a" * 800
    resp = client.put("/api/users/profile", headers=auth_headers,
                      json={"bio": long_bio})
    assert resp.status_code == 200
    assert len(resp.json()["profile"]["bio"]) == 500


def test_update_profile_no_token_401(client):
    resp = client.put("/api/users/profile", json={"display_name": "Nope"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------
def test_get_stats_happy(client, auth_headers, test_user, flask_core):
    from app.models.conversation import ConversationModel

    # Seed one active + one archived conversation for the count assertions.
    with flask_core.app_context():
        ConversationModel.create(test_user["_id"], None, title="C1")
        c2 = ConversationModel.create(test_user["_id"], None, title="C2")
        ConversationModel.toggle_archive(c2["_id"], archived=True)

    resp = client.get("/api/users/stats", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    stats = resp.json()["stats"]
    assert stats["total_conversations"] == 1
    assert stats["archived_conversations"] == 1
    assert stats["tokens_limit"] == -1
    assert stats["tokens_remaining"] == -1  # unlimited sentinel
    assert "messages_sent" in stats
    assert isinstance(stats["last_active"], str)


def test_get_stats_no_token_401(client):
    resp = client.get("/api/users/stats")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# /costs
# ---------------------------------------------------------------------------
def test_get_costs_empty(client, auth_headers):
    resp = client.get("/api/users/costs", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    costs = resp.json()["costs"]
    assert costs["total"]["total_cost_usd"] == 0
    assert costs["period"]["by_model"] == []
    assert costs["daily"] == []


def test_get_costs_respects_days_param(client, auth_headers):
    resp = client.get("/api/users/costs?days=7", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["costs"]["period"]["period_days"] == 7


def test_get_costs_no_token_401(client):
    resp = client.get("/api/users/costs")
    assert resp.status_code == 401
    assert resp.json()["code"] == "token_missing"


# ---------------------------------------------------------------------------
# /settings
# ---------------------------------------------------------------------------
def test_get_settings_defaults(client, auth_headers):
    resp = client.get("/api/users/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    settings = resp.json()["settings"]
    assert settings["default_config_id"] is None
    assert settings["theme"] == "dark"
    assert settings["notifications_enabled"] is True


def test_update_settings_happy(client, auth_headers):
    resp = client.put("/api/users/settings", headers=auth_headers, json={
        "theme": "light",
        "notifications_enabled": False,
    })
    assert resp.status_code == 200, resp.text
    settings = resp.json()["settings"]
    assert settings["theme"] == "light"
    assert settings["notifications_enabled"] is False


def test_update_settings_sets_default_config(client, auth_headers, test_user, flask_core):
    from app.models.llm_config import LLMConfigModel

    with flask_core.app_context():
        cfg = LLMConfigModel.create(
            name="My Config", model_id="openai/gpt-4o-mini",
            model_name="GPT-4o mini", owner_id=test_user["_id"],
        )
    config_id = str(cfg["_id"])

    resp = client.put("/api/users/settings", headers=auth_headers,
                      json={"default_config_id": config_id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["settings"]["default_config_id"] == config_id


def test_update_settings_unknown_config_404(client, auth_headers):
    import uuid

    resp = client.put("/api/users/settings", headers=auth_headers,
                      json={"default_config_id": str(uuid.uuid4())})
    assert resp.status_code == 404
    assert resp.json()["error"] == "Config not found"


def test_update_settings_clear_default_config(client, auth_headers):
    resp = client.put("/api/users/settings", headers=auth_headers,
                      json={"default_config_id": None})
    assert resp.status_code == 200
    assert resp.json()["settings"]["default_config_id"] is None


def test_settings_no_token_401(client):
    assert client.get("/api/users/settings").status_code == 401
    assert client.put("/api/users/settings", json={}).status_code == 401


# ---------------------------------------------------------------------------
# /ai-preferences
# ---------------------------------------------------------------------------
def test_get_ai_preferences_defaults(client, auth_headers):
    resp = client.get("/api/users/ai-preferences", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "preferences" in body
    assert body["timezone"] == "UTC"  # default tz


def test_update_ai_preferences_happy(client, auth_headers):
    resp = client.put("/api/users/ai-preferences", headers=auth_headers, json={
        "enabled": True,
        "user_info": {"name": "Sam", "expertise_level": "expert"},
        "behavior": {"tone": "friendly", "response_style": "concise"},
        "custom_instructions": "be terse",
        "timezone": "Europe/Paris",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"] == "AI preferences updated successfully"
    assert body["timezone"] == "Europe/Paris"
    prefs = body["preferences"]
    assert prefs["enabled"] is True
    assert prefs["user_info"]["name"] == "Sam"
    assert prefs["user_info"]["expertise_level"] == "expert"
    assert prefs["behavior"]["tone"] == "friendly"
    assert prefs["custom_instructions"] == "be terse"


def test_update_ai_preferences_partial_does_not_clobber_siblings(client, auth_headers):
    # First write both name and timezone.
    client.put("/api/users/ai-preferences", headers=auth_headers, json={
        "user_info": {"name": "Original"},
        "timezone": "Asia/Tehran",
    })
    # Now write ONLY timezone — name must survive (partial merge).
    resp = client.put("/api/users/ai-preferences", headers=auth_headers,
                      json={"timezone": "America/New_York"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["timezone"] == "America/New_York"
    assert body["preferences"]["user_info"]["name"] == "Original"


def test_update_ai_preferences_strips_unknown_nested_keys(client, auth_headers):
    resp = client.put("/api/users/ai-preferences", headers=auth_headers, json={
        "user_info": {"name": "Eve", "is_admin": True},  # is_admin stripped
    })
    assert resp.status_code == 200, resp.text
    user_info = resp.json()["preferences"]["user_info"]
    assert user_info["name"] == "Eve"
    assert "is_admin" not in user_info


def test_update_ai_preferences_empty_body_400(client, auth_headers):
    resp = client.put("/api/users/ai-preferences", headers=auth_headers, json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "Request body is required"


def test_update_ai_preferences_only_unknown_keys_400(client, auth_headers):
    resp = client.put("/api/users/ai-preferences", headers=auth_headers,
                      json={"totally_unknown": 1, "another": 2})
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "No recognized preference fields provided"
    assert set(body["rejected"]) == {"totally_unknown", "another"}
    assert "enabled" in body["allowed"]


def test_update_ai_preferences_invalid_enum_400(client, auth_headers):
    resp = client.put("/api/users/ai-preferences", headers=auth_headers, json={
        "user_info": {"expertise_level": "wizard"},
    })
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "Validation failed"
    assert any("expertise_level" in d for d in body["details"])


def test_update_ai_preferences_invalid_timezone_400(client, auth_headers):
    resp = client.put("/api/users/ai-preferences", headers=auth_headers,
                      json={"timezone": "Mars/Olympus"})
    assert resp.status_code == 400
    assert any("IANA timezone" in d for d in resp.json()["details"])


def test_update_ai_preferences_custom_instructions_too_long_400(client, auth_headers):
    resp = client.put("/api/users/ai-preferences", headers=auth_headers,
                      json={"custom_instructions": "x" * 2001})
    assert resp.status_code == 400
    assert any("2000 characters" in d for d in resp.json()["details"])


def test_ai_preferences_no_token_401(client):
    assert client.get("/api/users/ai-preferences").status_code == 401
    assert client.put("/api/users/ai-preferences", json={"enabled": True}).status_code == 401


# ---------------------------------------------------------------------------
# /onboarding-seen
# ---------------------------------------------------------------------------
def test_mark_onboarding_seen_sets_flag(client, auth_headers):
    resp = client.post("/api/users/onboarding-seen", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    seen = resp.json()["onboarding_seen_at"]
    assert isinstance(seen, str) and seen

    # Flows through the /auth/me full-settings passthrough (OnboardingGate
    # reads user.settings.onboarding_seen_at).
    me = client.get("/api/auth/me", headers=auth_headers)
    assert me.json()["settings"]["onboarding_seen_at"] == seen


def test_mark_onboarding_seen_idempotent(client, auth_headers):
    first = client.post("/api/users/onboarding-seen", headers=auth_headers).json()
    second = client.post("/api/users/onboarding-seen", headers=auth_headers).json()
    # Second POST must NOT overwrite the original timestamp.
    assert second["onboarding_seen_at"] == first["onboarding_seen_at"]


def test_mark_onboarding_seen_no_token_401(client):
    assert client.post("/api/users/onboarding-seen").status_code == 401


# ---------------------------------------------------------------------------
# Route-registration smoke.
# ---------------------------------------------------------------------------
def test_users_routes_registered(app):
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/users/profile" in paths
    assert "/api/users/stats" in paths
    assert "/api/users/costs" in paths
    assert "/api/users/settings" in paths
    assert "/api/users/ai-preferences" in paths
    assert "/api/users/onboarding-seen" in paths
