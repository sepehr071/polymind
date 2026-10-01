"""Direct facade coverage for three translated models:

  - app/models/usage_log.py   (UsageLogModel.create + every aggregation)
  - app/models/llm_config.py  (LLMConfigModel CRUD / visibility / counts / resolve)
  - app/models/folder.py      (FolderModel CRUD / move / scoping / reorder)

Mirrors tests/api/test_models.py + tests/api/test_configs.py: real model
facades on Postgres via the ``flask_core.app_context()`` bridge, legacy
dict-shape ``_id`` alias, isolated ``unichat_*_test`` DB (per-test TRUNCATE).
No HTTP, no external upstream — these are pure model/DB exercises.

FK note: ``usage_logs`` / ``llm_configs`` carry nullable FKs to ``workspaces``
/ ``projects`` / ``users`` with ``ON DELETE SET NULL``. A *non-existent* UUID
still violates the FK on insert, so workspace/project-scoped rows seed REAL
parent rows; user_id uses the seeded test users; pure parse-failure branches
pass bogus strings (coerced to None -> no FK touched).
"""
import uuid
from datetime import datetime, timedelta

import pytest

from app.models.usage_log import UsageLogModel, UsageLog, _to_uuid
from app.models.llm_config import (
    LLMConfigModel,
    LLMConfig,
    _as_uuid,
    _row_to_legacy_dict,
)
from app.models.folder import (
    FolderModel,
    Folder,
    NULL_PROJECT_SENTINEL,
    _coerce_uuid,
    _serialize_folder,
)


# ===========================================================================
# Seeding helpers (real parent rows for FK-bound columns).
# ===========================================================================
def _seed_workspace(flask_core, owner_id, *, name="Acme Co"):
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name=name, owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, "owner", status="active")
        return ws


def _seed_project(flask_core, workspace_id, owner_id, *, name="Alpha"):
    from app.models.project import ProjectModel

    with flask_core.app_context():
        return ProjectModel.create(
            workspace_id=workspace_id, name=name, created_by=owner_id
        )


def _proj_id(project):
    return project["_id"] if "_id" in project else project.get("id")


# ===========================================================================
# Module-level coerce helpers.
# ===========================================================================
def test_usage_to_uuid_none():
    assert _to_uuid(None) is None


def test_usage_to_uuid_passthrough():
    u = uuid.uuid4()
    assert _to_uuid(u) is u


def test_usage_to_uuid_from_str():
    u = uuid.uuid4()
    assert _to_uuid(str(u)) == u


def test_usage_to_uuid_garbage():
    assert _to_uuid("not-a-uuid") is None


def test_config_as_uuid_branches():
    u = uuid.uuid4()
    assert _as_uuid(None) is None
    assert _as_uuid(u) is u
    assert _as_uuid(str(u)) == u
    assert _as_uuid("garbage") is None
    # ObjectId branch -> None.
    from bson import ObjectId

    assert _as_uuid(ObjectId()) is None


def test_folder_coerce_uuid_branches():
    u = uuid.uuid4()
    assert _coerce_uuid(None) is None
    assert _coerce_uuid("") is None
    assert _coerce_uuid(b"") is None
    assert _coerce_uuid(u) is u
    assert _coerce_uuid(str(u)) == u
    assert _coerce_uuid(str(u).encode("utf-8")) == u
    assert _coerce_uuid("nope") is None
    assert _coerce_uuid(b"nope") is None
    assert _coerce_uuid(12345) is None


def test_serialize_folder_none():
    assert _serialize_folder(None) is None


# ===========================================================================
# UsageLogModel.create — kwargs, data-dict, legacy tokens-dict shims.
# ===========================================================================
def test_usage_create_basic_kwargs(flask_core, plain_user):
    with flask_core.app_context():
        out = UsageLogModel.create(
            user_id=plain_user["_id"],
            model="openai/gpt-4o",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=0.01,
            feature="chat",
            origin="web",
        )
    assert "_id" in out
    assert out["model"] == "openai/gpt-4o"
    assert out["provider"] == "openai"  # derived from "model" with "/"
    assert out["input_tokens"] == 10
    assert out["output_tokens"] == 5
    assert out["total_tokens"] == 15  # falls back to prompt+completion
    assert float(out["cost_usd"]) == 0.01
    assert out["origin"] == "web"


def test_usage_create_with_data_dict(flask_core, plain_user):
    with flask_core.app_context():
        out = UsageLogModel.create(data={
            "user_id": plain_user["_id"],
            "model": "anthropic/claude-sonnet-4.5",
            "provider": "anthropic",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "cached_tokens": 20,
            "reasoning_tokens": 7,
            "image_tokens": 3,
            "web_search_tokens": 1,
            "total_tokens": 161,
            "cost_usd": 0.5,
            "origin": "helper",
            "generation_id": "gen-abc-123",
            "is_streaming": True,
            "finish_reason": "stop",
        })
    assert out["model"] == "anthropic/claude-sonnet-4.5"
    assert out["provider"] == "anthropic"
    assert out["cached_tokens"] == 20
    assert out["reasoning_tokens"] == 7
    assert out["image_tokens"] == 3
    assert out["web_search_tokens"] == 1
    assert out["total_tokens"] == 161
    assert out["origin"] == "helper"
    assert out["generation_id"] == "gen-abc-123"


def test_usage_create_legacy_tokens_dict(flask_core, plain_user):
    """Old (message_id, tokens=dict) callers still extract token fields.

    cost_usd defaults to 0.0 (NOT None), so the ``cost_usd if cost_usd is not
    None else total_cost`` resolution keeps 0.0 even when total_cost is given —
    asserting the ACTUAL behavior here.
    """
    with flask_core.app_context():
        out = UsageLogModel.create(
            user_id=plain_user["_id"],
            model_id="x/y",  # legacy model_id, provider derived from "x"
            message_id="ignored",
            tokens={
                "prompt": 8,
                "completion": 4,
                "cached": 2,
                "reasoning": 1,
                "image": 0,
                "web_search": 0,
                "total": 12,
            },
            total_cost=0.25,
        )
    assert out["model"] == "x/y"
    assert out["provider"] == "x"
    assert out["input_tokens"] == 8
    assert out["output_tokens"] == 4
    assert out["cached_tokens"] == 2
    assert out["reasoning_tokens"] == 1
    assert out["total_tokens"] == 12
    # default cost_usd=0.0 wins over total_cost (cost_usd is not None).
    assert float(out["cost_usd"]) == 0.0


def test_usage_create_total_cost_fallback(flask_core, plain_user):
    """When cost_usd is explicitly None, total_cost is the fallback."""
    with flask_core.app_context():
        out = UsageLogModel.create(
            user_id=plain_user["_id"],
            model="x/y",
            cost_usd=None,
            total_cost=0.42,
        )
    assert float(out["cost_usd"]) == pytest.approx(0.42)


def test_usage_create_no_model_defaults_unknown(flask_core, plain_user):
    with flask_core.app_context():
        out = UsageLogModel.create(user_id=plain_user["_id"])
    assert out["model"] == "unknown"
    assert out["provider"] is None  # no "/" -> provider stays None


def test_usage_create_tokens_dict_none_values(flask_core, plain_user):
    """tokens dict with None values coalesce to 0; total absent -> computed."""
    with flask_core.app_context():
        out = UsageLogModel.create(
            user_id=plain_user["_id"],
            model="m/n",
            tokens={"prompt": None, "completion": None},
        )
    assert out["input_tokens"] == 0
    assert out["output_tokens"] == 0
    assert out["total_tokens"] == 0


# ===========================================================================
# UsageLogModel — per-user aggregations.
# ===========================================================================
def _seed_usage(flask_core, **kw):
    with flask_core.app_context():
        return UsageLogModel.create(**kw)


def test_get_user_costs_rollup(flask_core, plain_user):
    uid = plain_user["_id"]
    _seed_usage(flask_core, user_id=uid, model="a/m1", cost_usd=1.0,
                prompt_tokens=10, completion_tokens=0, total_tokens=10)
    _seed_usage(flask_core, user_id=uid, model="a/m1", cost_usd=2.0,
                prompt_tokens=5, completion_tokens=5, total_tokens=10)
    _seed_usage(flask_core, user_id=uid, model="b/m2", cost_usd=0.5,
                prompt_tokens=1, completion_tokens=1, total_tokens=2)
    with flask_core.app_context():
        res = UsageLogModel.get_user_costs(uid, days=30)
    assert res["period_days"] == 30
    assert res["total_cost_usd"] == pytest.approx(3.5)
    by_model = {r["_id"]: r for r in res["by_model"]}
    # Ordered by cost desc -> m1 first.
    assert res["by_model"][0]["_id"] == "a/m1"
    assert by_model["a/m1"]["total_cost"] == pytest.approx(3.0)
    assert by_model["a/m1"]["request_count"] == 2
    assert by_model["a/m1"]["total_tokens"] == 20


def test_get_user_costs_invalid_id(flask_core):
    with flask_core.app_context():
        res = UsageLogModel.get_user_costs("not-a-uuid", days=7)
    assert res == {"by_model": [], "total_cost_usd": 0.0, "period_days": 7}


def test_get_user_total_cost(flask_core, plain_user):
    uid = plain_user["_id"]
    _seed_usage(flask_core, user_id=uid, model="a/m", cost_usd=1.25,
                prompt_tokens=3, completion_tokens=2, total_tokens=5)
    with flask_core.app_context():
        res = UsageLogModel.get_user_total_cost(uid)
    assert res["total_cost_usd"] == pytest.approx(1.25)
    assert res["total_tokens"] == 5


def test_get_user_total_cost_invalid_id(flask_core):
    with flask_core.app_context():
        assert UsageLogModel.get_user_total_cost("bad") == {
            "total_cost_usd": 0, "total_tokens": 0
        }


def test_get_daily_costs_no_user(flask_core, plain_user):
    _seed_usage(flask_core, user_id=plain_user["_id"], model="a/m", cost_usd=1.0,
                prompt_tokens=1, completion_tokens=1, total_tokens=2)
    with flask_core.app_context():
        rows = UsageLogModel.get_daily_costs(days=30)
    assert len(rows) == 1
    assert rows[0]["cost"] == pytest.approx(1.0)
    assert rows[0]["requests"] == 1
    assert isinstance(rows[0]["_id"], str)


def test_get_daily_costs_with_user(flask_core, plain_user):
    _seed_usage(flask_core, user_id=plain_user["_id"], model="a/m", cost_usd=2.0,
                prompt_tokens=1, completion_tokens=1, total_tokens=2)
    with flask_core.app_context():
        rows = UsageLogModel.get_daily_costs(user_id=plain_user["_id"], days=30)
    assert len(rows) == 1
    assert rows[0]["cost"] == pytest.approx(2.0)


def test_get_daily_costs_invalid_user(flask_core):
    with flask_core.app_context():
        assert UsageLogModel.get_daily_costs(user_id="bad", days=30) == []


# ===========================================================================
# UsageLogModel.aggregate_by + aggregate_by_with_workspace.
# ===========================================================================
def test_aggregate_by_feature(flask_core, plain_user):
    uid = plain_user["_id"]
    _seed_usage(flask_core, user_id=uid, model="a/m", feature="chat",
                cost_usd=1.0, prompt_tokens=4, completion_tokens=2)
    _seed_usage(flask_core, user_id=uid, model="a/m", feature="chat",
                cost_usd=1.0, prompt_tokens=1, completion_tokens=1)
    _seed_usage(flask_core, user_id=uid, model="a/m", feature=None,
                cost_usd=0.5, prompt_tokens=1, completion_tokens=0)
    with flask_core.app_context():
        rows = UsageLogModel.aggregate_by("feature")
    by_key = {r["key"]: r for r in rows}
    assert by_key["chat"]["count"] == 2
    assert by_key["chat"]["total_cost"] == pytest.approx(2.0)
    assert by_key["chat"]["total_tokens"] == 8  # (4+2)+(1+1)
    # None feature serialized to the literal "None".
    assert "None" in by_key


def test_aggregate_by_model_and_user_and_day(flask_core, plain_user):
    uid = plain_user["_id"]
    _seed_usage(flask_core, user_id=uid, model="a/m", cost_usd=1.0,
                prompt_tokens=2, completion_tokens=1)
    with flask_core.app_context():
        assert UsageLogModel.aggregate_by("model")[0]["key"] == "a/m"
        assert UsageLogModel.aggregate_by("user")[0]["key"] == str(uid)
        day_rows = UsageLogModel.aggregate_by("day")
    assert len(day_rows) == 1


def test_aggregate_by_invalid_group(flask_core):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            UsageLogModel.aggregate_by("bogus")


def test_aggregate_by_user_filter_and_dates(flask_core, plain_user):
    uid = plain_user["_id"]
    _seed_usage(flask_core, user_id=uid, model="a/m", cost_usd=1.0,
                prompt_tokens=1, completion_tokens=1)
    now = datetime.utcnow()
    with flask_core.app_context():
        rows = UsageLogModel.aggregate_by(
            "model", user_id=uid,
            from_=now - timedelta(days=1), to=now + timedelta(days=1),
        )
    assert rows[0]["key"] == "a/m"


def test_aggregate_by_invalid_user(flask_core):
    with flask_core.app_context():
        assert UsageLogModel.aggregate_by("model", user_id="bad") == []


def test_aggregate_by_with_workspace(flask_core, plain_user):
    uid = plain_user["_id"]
    ws = _seed_workspace(flask_core, uid)
    _seed_usage(flask_core, user_id=uid, workspace_id=ws["_id"], model="a/m",
                feature="chat", cost_usd=1.0, prompt_tokens=2, completion_tokens=1)
    now = datetime.utcnow()
    with flask_core.app_context():
        rows = UsageLogModel.aggregate_by_with_workspace(
            "feature", user_id=uid,
            from_=now - timedelta(days=1), to=now + timedelta(days=1),
        )
    assert len(rows) == 1
    assert rows[0]["key"] == "chat"
    assert str(rows[0]["workspace_id"]) == str(ws["_id"])
    assert rows[0]["count"] == 1


def test_aggregate_by_with_workspace_invalid_group(flask_core):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            UsageLogModel.aggregate_by_with_workspace("bogus")


def test_aggregate_by_with_workspace_invalid_user(flask_core):
    with flask_core.app_context():
        assert UsageLogModel.aggregate_by_with_workspace("model", user_id="bad") == []


def test_aggregate_by_with_workspace_model_user_day(flask_core, plain_user):
    uid = plain_user["_id"]
    ws = _seed_workspace(flask_core, uid)
    _seed_usage(flask_core, user_id=uid, workspace_id=ws["_id"], model="a/m",
                cost_usd=1.0, prompt_tokens=1, completion_tokens=1)
    with flask_core.app_context():
        assert UsageLogModel.aggregate_by_with_workspace("model")[0]["key"] == "a/m"
        assert UsageLogModel.aggregate_by_with_workspace("user")[0]["key"] == str(uid)
        assert len(UsageLogModel.aggregate_by_with_workspace("day")) == 1


# ===========================================================================
# UsageLogModel — workspace-scoped aggregations.
# ===========================================================================
def test_aggregate_workspace_spend(flask_core, plain_user):
    uid = plain_user["_id"]
    ws = _seed_workspace(flask_core, uid)
    _seed_usage(flask_core, user_id=uid, workspace_id=ws["_id"], model="a/m",
                cost_usd=1.5, prompt_tokens=1, completion_tokens=1)
    _seed_usage(flask_core, user_id=uid, workspace_id=ws["_id"], model="a/m",
                cost_usd=2.5, prompt_tokens=1, completion_tokens=1)
    now = datetime.utcnow()
    with flask_core.app_context():
        total = UsageLogModel.aggregate_workspace_spend(
            ws["_id"], start=now - timedelta(days=1), end=now + timedelta(days=1)
        )
    assert total == pytest.approx(4.0)


def test_aggregate_workspace_spend_invalid(flask_core):
    with flask_core.app_context():
        assert UsageLogModel.aggregate_workspace_spend("bad") == 0.0


def test_aggregate_user_spend(flask_core, plain_user):
    uid = plain_user["_id"]
    ws = _seed_workspace(flask_core, uid)
    _seed_usage(flask_core, user_id=uid, workspace_id=ws["_id"], model="a/m",
                cost_usd=1.0, prompt_tokens=3, completion_tokens=2)
    now = datetime.utcnow()
    with flask_core.app_context():
        rows = UsageLogModel.aggregate_user_spend(
            ws["_id"], start=now - timedelta(days=1), end=now + timedelta(days=1)
        )
    assert len(rows) == 1
    assert str(rows[0]["user_id"]) == str(uid)
    assert rows[0]["total_tokens"] == 5
    assert rows[0]["total_cost"] == pytest.approx(1.0)


def test_aggregate_user_spend_invalid(flask_core):
    with flask_core.app_context():
        assert UsageLogModel.aggregate_user_spend("bad") == []


def test_aggregate_project_spend(flask_core, plain_user):
    uid = plain_user["_id"]
    ws = _seed_workspace(flask_core, uid)
    proj = _seed_project(flask_core, ws["_id"], uid)
    pid = _proj_id(proj)
    _seed_usage(flask_core, user_id=uid, workspace_id=ws["_id"], project_id=pid,
                model="a/m", cost_usd=3.0, prompt_tokens=2, completion_tokens=2)
    now = datetime.utcnow()
    with flask_core.app_context():
        rows = UsageLogModel.aggregate_project_spend(
            ws["_id"], start=now - timedelta(days=1), end=now + timedelta(days=1)
        )
    assert len(rows) == 1
    assert str(rows[0]["project_id"]) == str(pid)
    assert rows[0]["total_cost"] == pytest.approx(3.0)


def test_aggregate_project_spend_invalid(flask_core):
    with flask_core.app_context():
        assert UsageLogModel.aggregate_project_spend("bad") == []


def test_aggregate_model_spend(flask_core, plain_user):
    uid = plain_user["_id"]
    ws = _seed_workspace(flask_core, uid)
    _seed_usage(flask_core, user_id=uid, workspace_id=ws["_id"], model="x/y",
                cost_usd=2.0, prompt_tokens=1, completion_tokens=1)
    now = datetime.utcnow()
    with flask_core.app_context():
        rows = UsageLogModel.aggregate_model_spend(
            ws["_id"], start=now - timedelta(days=1), end=now + timedelta(days=1)
        )
    assert len(rows) == 1
    assert rows[0]["model"] == "x/y"
    assert rows[0]["total_cost"] == pytest.approx(2.0)


def test_aggregate_model_spend_invalid(flask_core):
    with flask_core.app_context():
        assert UsageLogModel.aggregate_model_spend("bad") == []


# ``aggregate_daily`` + ``total_messages_this_month`` were folded into the single
# ``overview_usage_bundle`` grouped pass (commit 2c066df). The bundle emits the
# identical per-day shape (``date``/``cost_usd``/``total_tokens``/``messages``)
# under ``daily`` plus the month-to-date count under ``messages_mtd`` — assert
# both against the successor.
def test_overview_usage_bundle_daily(flask_core, plain_user):
    uid = plain_user["_id"]
    ws = _seed_workspace(flask_core, uid)
    _seed_usage(flask_core, user_id=uid, workspace_id=ws["_id"], model="a/m",
                cost_usd=1.0, prompt_tokens=1, completion_tokens=1)
    with flask_core.app_context():
        rows = UsageLogModel.overview_usage_bundle(ws["_id"], days=30)["daily"]
    assert len(rows) == 1
    assert rows[0]["messages"] == 1
    assert rows[0]["cost_usd"] == pytest.approx(1.0)
    assert isinstance(rows[0]["date"], str)


def test_overview_usage_bundle_invalid(flask_core):
    with flask_core.app_context():
        assert UsageLogModel.overview_usage_bundle("bad") == {
            "daily": [], "messages_mtd": 0
        }


def test_overview_usage_bundle_messages_mtd(flask_core, plain_user):
    uid = plain_user["_id"]
    ws = _seed_workspace(flask_core, uid)
    _seed_usage(flask_core, user_id=uid, workspace_id=ws["_id"], model="a/m",
                cost_usd=1.0, prompt_tokens=1, completion_tokens=1)
    _seed_usage(flask_core, user_id=uid, workspace_id=ws["_id"], model="a/m",
                cost_usd=1.0, prompt_tokens=1, completion_tokens=1)
    with flask_core.app_context():
        assert UsageLogModel.overview_usage_bundle(ws["_id"])["messages_mtd"] == 2


# ===========================================================================
# LLMConfigModel — CRUD + visibility.
# ===========================================================================
def _mk_config(flask_core, owner_id, **kw):
    body = {"name": "Persona", "model_id": "openai/gpt-5", "model_name": "GPT-5",
            "owner_id": owner_id}
    body.update(kw)
    with flask_core.app_context():
        return LLMConfigModel.create(**body)


def test_config_create_defaults(flask_core, plain_user):
    cfg = _mk_config(flask_core, plain_user["_id"], name="Sum")
    assert "_id" in cfg
    assert cfg["visibility"] == "private"
    assert cfg["model_id"] == "openai/gpt-5"
    assert cfg["model_name"] == "openai/gpt-5"  # surfaces model for both keys
    assert cfg["owner_id"] == cfg["owner_user_id"]
    # Default parameters merged.
    assert cfg["parameters"]["temperature"] == 0.7
    # Default initials avatar.
    assert cfg["avatar"]["type"] == "initials"
    assert cfg["avatar"]["value"] == "SU"
    assert cfg["stats"]["uses_count"] == 0


def test_config_create_with_overrides(flask_core, plain_user):
    cfg = _mk_config(
        flask_core, plain_user["_id"], name="Custom",
        parameters={"temperature": 0.2}, tags=["a", "b"],
        avatar={"type": "emoji", "value": "🤖"},
        description="desc", system_prompt="be brief", visibility="public",
    )
    assert cfg["parameters"]["temperature"] == 0.2
    assert cfg["parameters"]["max_tokens"] == 2048  # default kept
    assert cfg["tags"] == ["a", "b"]
    assert cfg["avatar"]["value"] == "🤖"
    assert cfg["visibility"] == "public"


def test_config_create_empty_name_avatar_default(flask_core, plain_user):
    cfg = _mk_config(flask_core, plain_user["_id"], name="")
    assert cfg["avatar"]["value"] == "AI"


def test_config_find_by_id_and_invalid(flask_core, plain_user):
    cfg = _mk_config(flask_core, plain_user["_id"])
    with flask_core.app_context():
        found = LLMConfigModel.find_by_id(cfg["_id"])
        assert found["_id"] == cfg["_id"]
        assert LLMConfigModel.find_by_id("bad-uuid") is None
        assert LLMConfigModel.find_by_id(str(uuid.uuid4())) is None


def test_config_find_by_ids(flask_core, plain_user):
    c1 = _mk_config(flask_core, plain_user["_id"], name="One")
    c2 = _mk_config(flask_core, plain_user["_id"], name="Two")
    with flask_core.app_context():
        assert LLMConfigModel.find_by_ids([]) == []
        assert LLMConfigModel.find_by_ids(["bad", "also-bad"]) == []
        rows = LLMConfigModel.find_by_ids([c1["_id"], c2["_id"], "garbage"])
    assert {r["_id"] for r in rows} == {c1["_id"], c2["_id"]}


def test_config_find_by_owner(flask_core, plain_user):
    _mk_config(flask_core, plain_user["_id"], name="A")
    _mk_config(flask_core, plain_user["_id"], name="B")
    with flask_core.app_context():
        rows = LLMConfigModel.find_by_owner(plain_user["_id"])
        assert {r["name"] for r in rows} == {"A", "B"}
        assert LLMConfigModel.find_by_owner("bad") == []
        # Pagination branch.
        assert len(LLMConfigModel.find_by_owner(plain_user["_id"], skip=1, limit=1)) == 1


def test_config_find_templates(flask_core, plain_user):
    tmpl = _mk_config(flask_core, plain_user["_id"], name="T", visibility="template")
    _mk_config(flask_core, plain_user["_id"], name="P", visibility="private")
    with flask_core.app_context():
        rows = LLMConfigModel.find_templates()
    assert {r["_id"] for r in rows} == {tmpl["_id"]}


def test_config_find_visible_to(flask_core, plain_user, test_user):
    uid = plain_user["_id"]
    ws = _seed_workspace(flask_core, uid)
    proj = _seed_project(flask_core, ws["_id"], uid)
    pid = _proj_id(proj)
    own = _mk_config(flask_core, uid, name="Mine")
    pub = _mk_config(flask_core, test_user["_id"], name="Public", visibility="public")
    proj_cfg = _mk_config(flask_core, test_user["_id"], name="ProjCfg",
                          project_id=pid, workspace_id=ws["_id"], visibility="project")
    with flask_core.app_context():
        # No project: own + public/template only.
        rows = LLMConfigModel.find_visible_to(uid)
        ids = {r["_id"] for r in rows}
        assert own["_id"] in ids
        assert pub["_id"] in ids
        assert proj_cfg["_id"] not in ids
        # With project: project-scoped now visible too.
        rows2 = LLMConfigModel.find_visible_to(uid, project_id=pid)
        ids2 = {r["_id"] for r in rows2}
        assert proj_cfg["_id"] in ids2
        # Invalid project_id branch (coerce None -> not appended).
        rows3 = LLMConfigModel.find_visible_to(uid, project_id="bad")
        assert proj_cfg["_id"] not in {r["_id"] for r in rows3}


def test_config_update_and_aliases(flask_core, plain_user):
    cfg = _mk_config(flask_core, plain_user["_id"], name="Before")
    with flask_core.app_context():
        res = LLMConfigModel.update(cfg["_id"], {
            "name": "After", "model_id": "anthropic/claude", "model_name": "drop",
            "owner_id": plain_user["_id"], "id": "ignored", "_id": "ignored",
            "created_at": "ignored", "bogus_col": "ignored",
        })
        assert res.modified_count == 1
        found = LLMConfigModel.find_by_id(cfg["_id"])
    assert found["name"] == "After"
    assert found["model_id"] == "anthropic/claude"


def test_config_update_invalid_id(flask_core):
    with flask_core.app_context():
        res = LLMConfigModel.update("bad", {"name": "x"})
    assert res.modified_count == 0


def test_config_set_visibility(flask_core, plain_user):
    cfg = _mk_config(flask_core, plain_user["_id"])
    with flask_core.app_context():
        LLMConfigModel.set_visibility(cfg["_id"], "public")
        assert LLMConfigModel.find_by_id(cfg["_id"])["visibility"] == "public"


def test_config_increment_uses(flask_core, plain_user):
    cfg = _mk_config(flask_core, plain_user["_id"])
    with flask_core.app_context():
        res = LLMConfigModel.increment_uses(cfg["_id"])
        assert res.modified_count == 1
        found = LLMConfigModel.find_by_id(cfg["_id"])
    assert found["stats"]["uses_count"] == 1
    assert "last_used_at" in found["stats"]


def test_config_increment_uses_invalid_and_missing(flask_core):
    with flask_core.app_context():
        assert LLMConfigModel.increment_uses("bad").modified_count == 0
        assert LLMConfigModel.increment_uses(str(uuid.uuid4())).modified_count == 0


def test_config_increment_saves(flask_core, plain_user):
    cfg = _mk_config(flask_core, plain_user["_id"])
    with flask_core.app_context():
        res = LLMConfigModel.increment_saves(cfg["_id"])
        assert res.modified_count == 1
        found = LLMConfigModel.find_by_id(cfg["_id"])
    assert found["stats"]["saves_count"] == 1


def test_config_increment_saves_invalid_and_missing(flask_core):
    with flask_core.app_context():
        assert LLMConfigModel.increment_saves("bad").modified_count == 0
        assert LLMConfigModel.increment_saves(str(uuid.uuid4())).modified_count == 0


def test_config_delete(flask_core, plain_user):
    cfg = _mk_config(flask_core, plain_user["_id"])
    with flask_core.app_context():
        res = LLMConfigModel.delete(cfg["_id"])
        assert res.deleted_count == 1
        assert LLMConfigModel.find_by_id(cfg["_id"]) is None
        assert LLMConfigModel.delete("bad").deleted_count == 0


def test_config_duplicate(flask_core, plain_user, test_user):
    cfg = _mk_config(flask_core, plain_user["_id"], name="Orig", tags=["t"])
    with flask_core.app_context():
        dup = LLMConfigModel.duplicate(cfg["_id"], test_user["_id"], new_name="Copy")
        assert dup["name"] == "Copy"
        assert dup["_id"] != cfg["_id"]
        assert dup["visibility"] == "private"
        assert str(dup["owner_id"]) == str(test_user["_id"])
        # default new_name branch.
        dup2 = LLMConfigModel.duplicate(cfg["_id"], test_user["_id"])
        assert dup2["name"] == "Orig (copy)"
        # non-existent original -> None.
        assert LLMConfigModel.duplicate(str(uuid.uuid4()), test_user["_id"]) is None


def test_config_count_by_owner(flask_core, plain_user):
    _mk_config(flask_core, plain_user["_id"], name="A")
    _mk_config(flask_core, plain_user["_id"], name="B")
    with flask_core.app_context():
        assert LLMConfigModel.count_by_owner(plain_user["_id"]) == 2
        assert LLMConfigModel.count_by_owner("bad") == 0


def test_config_count_public(flask_core, plain_user):
    _mk_config(flask_core, plain_user["_id"], name="P1", visibility="public")
    _mk_config(flask_core, plain_user["_id"], name="P2", visibility="public")
    _mk_config(flask_core, plain_user["_id"], name="Priv")
    with flask_core.app_context():
        assert LLMConfigModel.count_public() == 2


def test_row_to_legacy_dict_aliases(flask_core, plain_user):
    cfg = _mk_config(flask_core, plain_user["_id"])
    with flask_core.app_context():
        row = LLMConfig(
            id=uuid.uuid4(), owner_user_id=_as_uuid(plain_user["_id"]),
            name="Direct", provider="openrouter", model="m/x",
            parameters={}, stats={}, tags=[], visibility="private",
        )
        d = _row_to_legacy_dict(row)
    assert d["owner_id"] == d["owner_user_id"]
    assert d["model_id"] == "m/x"
    assert d["model_name"] == "m/x"


# ===========================================================================
# FolderModel — CRUD + scoping.
# ===========================================================================
def test_folder_create_and_position(flask_core, plain_user):
    uid = plain_user["_id"]
    with flask_core.app_context():
        f1 = FolderModel.create(uid, "Root1")
        f2 = FolderModel.create(uid, "Root2")
    assert f1["position"] == 0
    assert f1["order"] == 0  # legacy alias
    assert f2["position"] == 1
    # Default color filled by serializer.
    assert f1["color"] == "#5c9aed"
    assert f1["icon"] is None


def test_folder_create_invalid_user(flask_core):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            FolderModel.create("bad-user", "X")


def test_folder_create_nested(flask_core, plain_user):
    uid = plain_user["_id"]
    with flask_core.app_context():
        root = FolderModel.create(uid, "Root")
        child = FolderModel.create(uid, "Child", parent_id=root["_id"])
    assert str(child["parent_id"]) == str(root["_id"])
    assert child["position"] == 0  # first child


def test_folder_find_by_id_and_invalid(flask_core, plain_user):
    uid = plain_user["_id"]
    with flask_core.app_context():
        f = FolderModel.create(uid, "F")
        assert FolderModel.find_by_id(f["_id"])["_id"] == f["_id"]
        assert FolderModel.find_by_id("bad") is None
        assert FolderModel.find_by_id(str(uuid.uuid4())) is None


def test_folder_find_by_user_roots_and_children(flask_core, plain_user):
    uid = plain_user["_id"]
    with flask_core.app_context():
        root = FolderModel.create(uid, "Root")
        child = FolderModel.create(uid, "Child", parent_id=root["_id"])
        roots = FolderModel.find_by_user(uid)
        assert {r["_id"] for r in roots} == {root["_id"]}
        kids = FolderModel.find_by_user(uid, parent_id=root["_id"])
        assert {r["_id"] for r in kids} == {child["_id"]}
        # invalid user / invalid parent.
        assert FolderModel.find_by_user("bad") == []
        assert FolderModel.find_by_user(uid, parent_id="bad") == []


def test_folder_find_by_user_project_scoping(flask_core, plain_user):
    uid = plain_user["_id"]
    ws = _seed_workspace(flask_core, uid)
    proj = _seed_project(flask_core, ws["_id"], uid)
    pid = _proj_id(proj)
    with flask_core.app_context():
        personal = FolderModel.create(uid, "Personal")
        scoped = FolderModel.create(uid, "Scoped", project_id=pid)
        # Sentinel -> personal only.
        null_rows = FolderModel.find_by_user(uid, project_id=NULL_PROJECT_SENTINEL)
        assert {r["_id"] for r in null_rows} == {personal["_id"]}
        # Explicit project.
        scoped_rows = FolderModel.find_by_user(uid, project_id=pid)
        assert {r["_id"] for r in scoped_rows} == {scoped["_id"]}
        # Invalid project_id -> [].
        assert FolderModel.find_by_user(uid, project_id="bad") == []


def test_folder_find_all_by_user(flask_core, plain_user):
    uid = plain_user["_id"]
    ws = _seed_workspace(flask_core, uid)
    proj = _seed_project(flask_core, ws["_id"], uid)
    pid = _proj_id(proj)
    with flask_core.app_context():
        root = FolderModel.create(uid, "Root")
        child = FolderModel.create(uid, "Child", parent_id=root["_id"])
        scoped = FolderModel.create(uid, "Scoped", project_id=pid)
        # Flat list returns root + child (both personal scope).
        flat = FolderModel.find_all_by_user(uid, project_id=NULL_PROJECT_SENTINEL)
        assert {r["_id"] for r in flat} == {root["_id"], child["_id"]}
        proj_flat = FolderModel.find_all_by_user(uid, project_id=pid)
        assert {r["_id"] for r in proj_flat} == {scoped["_id"]}
        assert FolderModel.find_all_by_user("bad") == []
        assert FolderModel.find_all_by_user(uid, project_id="bad") == []


def test_folder_update(flask_core, plain_user):
    uid = plain_user["_id"]
    with flask_core.app_context():
        f = FolderModel.create(uid, "Before")
        obj = FolderModel.update(f["_id"], {
            "name": "After", "order": 5, "color": "#fff", "icon": "star",
            "bogus": "ignored",
        })
        assert obj.name == "After"
        assert obj.position == 5
        # invalid id / missing.
        assert FolderModel.update("bad", {"name": "x"}) is None
        assert FolderModel.update(str(uuid.uuid4()), {"name": "x"}) is None


def test_folder_reorder(flask_core, plain_user):
    uid = plain_user["_id"]
    with flask_core.app_context():
        a = FolderModel.create(uid, "A")
        b = FolderModel.create(uid, "B")
        FolderModel.reorder(uid, [
            {"id": a["_id"], "order": 10},
            {"id": b["_id"], "order": 20},
            {"id": "bad-id", "order": 99},  # skipped
        ])
        assert FolderModel.find_by_id(a["_id"])["position"] == 10
        assert FolderModel.find_by_id(b["_id"])["position"] == 20
        # invalid user is a no-op.
        assert FolderModel.reorder("bad", [{"id": a["_id"], "order": 1}]) is None


def test_folder_delete(flask_core, plain_user):
    uid = plain_user["_id"]
    with flask_core.app_context():
        f = FolderModel.create(uid, "F")
        res = FolderModel.delete(f["_id"])
        assert res.rowcount == 1
        assert FolderModel.find_by_id(f["_id"]) is None
        assert FolderModel.delete("bad") is None


def test_folder_null_project_for_project(flask_core, plain_user):
    uid = plain_user["_id"]
    ws = _seed_workspace(flask_core, uid)
    proj = _seed_project(flask_core, ws["_id"], uid)
    pid = _proj_id(proj)
    with flask_core.app_context():
        f = FolderModel.create(uid, "F", project_id=pid)
        n = FolderModel.null_project_for_project(pid)
        assert n == 1
        assert FolderModel.find_by_id(f["_id"])["project_id"] is None
        assert FolderModel.null_project_for_project("bad") == 0


def test_folder_null_parent_for_children(flask_core, plain_user):
    uid = plain_user["_id"]
    with flask_core.app_context():
        root = FolderModel.create(uid, "Root")
        child = FolderModel.create(uid, "Child", parent_id=root["_id"])
        n = FolderModel.null_parent_for_children(root["_id"])
        assert n == 1
        assert FolderModel.find_by_id(child["_id"])["parent_id"] is None
        assert FolderModel.null_parent_for_children("bad") == 0


def test_folder_count_by_user(flask_core, plain_user):
    uid = plain_user["_id"]
    with flask_core.app_context():
        FolderModel.create(uid, "A")
        assert FolderModel.count_by_user(uid) == 1
        assert FolderModel.count_by_user("bad") == 0
