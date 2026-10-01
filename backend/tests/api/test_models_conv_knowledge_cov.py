"""Direct facade coverage for the conversation + knowledge-item model layers.

Mirrors tests/api/test_models_meetings_cov.py (pure facade tests, real ORM,
``flask_core.app_context()`` bridge, legacy ``_id`` alias) and the seeding
helpers in tests/api/test_conversations.py / test_knowledge.py. No HTTP — every
call runs inside an app_context against the isolated ``unichat_*_test`` DB; no
external upstream is touched.

Targets the uncovered ranges in:
  - app/models/conversation.py  (ConversationModel + _coerce_uuid + _serialize_*)
  - app/models/knowledge_item.py (KnowledgeItemModel + _as_uuid)
"""
import uuid

import pytest
from bson import ObjectId

from app.models.conversation import (
    ConversationModel,
    Conversation,
    ConversationBranch,
    NULL_PROJECT_SENTINEL,
    _coerce_uuid,
    _serialize_conversation,
    _branch_map_for,
)
from app.models.knowledge_item import (
    KnowledgeItemModel,
    KnowledgeItem,
    _as_uuid,
    NULL_PROJECT_SENTINEL as KI_NULL_SENTINEL,
)


# ===========================================================================
# Helpers.
# ===========================================================================
def _mk_conv(flask_core, user_id, **kwargs):
    with flask_core.app_context():
        return ConversationModel.create(str(user_id), kwargs.pop("config_id", "quick:x"),
                                        **kwargs)


def _mk_ki(flask_core, user_id, **kwargs):
    kwargs.setdefault("source_type", "chat")
    with flask_core.app_context():
        return KnowledgeItemModel.create(str(user_id), **kwargs)


def _mk_project(flask_core, owner_id, workspace_id):
    """Create a real project row so project_id FKs resolve."""
    from app.models.project import ProjectModel
    with flask_core.app_context():
        return ProjectModel.create(
            workspace_id=str(workspace_id), name="Proj", created_by=str(owner_id)
        )


def _mk_workspace(flask_core, owner_id):
    from app.models.workspace import WorkspaceModel
    with flask_core.app_context():
        return WorkspaceModel.create(name="WS", owner_id=str(owner_id))


# ===========================================================================
# _coerce_uuid (conversation helper).
# ===========================================================================
def test_coerce_uuid_none_and_empty():
    assert _coerce_uuid(None) is None
    assert _coerce_uuid("") is None
    assert _coerce_uuid(b"") is None


def test_coerce_uuid_passthrough_instance():
    u = uuid.uuid4()
    assert _coerce_uuid(u) is u


def test_coerce_uuid_from_string():
    u = uuid.uuid4()
    assert _coerce_uuid(str(u)) == u


def test_coerce_uuid_from_bytes():
    u = uuid.uuid4()
    assert _coerce_uuid(str(u).encode("utf-8")) == u


def test_coerce_uuid_garbage_returns_none():
    # ObjectId-hex strings can't address Postgres rows -> None.
    assert _coerce_uuid("not-a-uuid") is None
    assert _coerce_uuid(str(ObjectId())) is None


def test_coerce_uuid_non_str_non_uuid_returns_none():
    assert _coerce_uuid(12345) is None


# ===========================================================================
# _serialize_conversation / _branch_map_for direct branches.
# ===========================================================================
def test_serialize_conversation_none_returns_none():
    assert _serialize_conversation(None) is None


def test_serialize_conversation_default_main_branch(flask_core, test_user):
    """A conv with only its seeded 'main' branch serializes the branch row."""
    conv = _mk_conv(flask_core, test_user["_id"], title="C")
    cid = uuid.UUID(conv["_id"])
    with flask_core.app_context():
        from app.api.core import db
        obj = db.session.get(Conversation, cid)
        out = _serialize_conversation(obj)  # branch_map=None -> per-row SELECT
    assert out["_id"] == conv["_id"]
    assert out["branches"][0]["id"] == "main"


def test_serialize_conversation_synthetic_main_when_no_rows(flask_core, test_user):
    """With branch_map supplying an empty bucket, the synthetic 'main' fallback
    fires (the ``or [...]`` branch)."""
    conv = _mk_conv(flask_core, test_user["_id"], title="C")
    cid = uuid.UUID(conv["_id"])
    with flask_core.app_context():
        from app.api.core import db
        obj = db.session.get(Conversation, cid)
        out = _serialize_conversation(obj, branch_map={})  # empty bucket
    assert out["branches"][0]["id"] == "main"
    assert out["branches"][0]["name"] == "Main"


def test_branch_map_for_empty_inputs():
    with_none = _branch_map_for([])
    assert with_none == {}


def test_branch_map_for_all_none_filtered():
    assert _branch_map_for([None, None]) == {}


def test_branch_map_for_populated(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"])
    cid = uuid.UUID(conv["_id"])
    with flask_core.app_context():
        bucket = _branch_map_for([cid])
    assert cid in bucket
    assert bucket[cid][0].branch_key == "main"


# ===========================================================================
# ConversationModel.create.
# ===========================================================================
def test_conv_create_happy(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"], title="Hello")
    assert conv["title"] == "Hello"
    assert conv["message_count"] == 0
    assert conv["active_branch"] == "main"
    assert conv["token_count"] == {"input": 0, "output": 0, "total": 0}
    assert conv["branches"][0]["id"] == "main"


def test_conv_create_bad_user_raises(flask_core):
    with flask_core.app_context():
        with pytest.raises(ValueError):
            ConversationModel.create("not-a-uuid", "quick:x")


def test_conv_create_with_folder_and_project(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    conv = _mk_conv(flask_core, test_user["_id"], project_id=proj["_id"])
    assert conv["project_id"] == str(proj["_id"])


def test_conv_create_none_config_id(flask_core, test_user):
    with flask_core.app_context():
        conv = ConversationModel.create(str(test_user["_id"]), None)
    assert conv["config_id"] is None


# ===========================================================================
# ConversationModel.find_by_id.
# ===========================================================================
def test_conv_find_by_id_happy(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"], title="FindMe")
    with flask_core.app_context():
        row = ConversationModel.find_by_id(conv["_id"])
    assert row["title"] == "FindMe"


def test_conv_find_by_id_bad_uuid(flask_core):
    with flask_core.app_context():
        assert ConversationModel.find_by_id("bad") is None


def test_conv_find_by_id_missing(flask_core):
    with flask_core.app_context():
        assert ConversationModel.find_by_id(str(uuid.uuid4())) is None


# ===========================================================================
# ConversationModel.find_by_user — all filter branches.
# ===========================================================================
def test_conv_find_by_user_basic(flask_core, test_user):
    _mk_conv(flask_core, test_user["_id"], title="One")
    _mk_conv(flask_core, test_user["_id"], title="Two")
    with flask_core.app_context():
        rows = ConversationModel.find_by_user(str(test_user["_id"]))
    assert {r["title"] for r in rows} == {"One", "Two"}


def test_conv_find_by_user_bad_owner(flask_core):
    with flask_core.app_context():
        assert ConversationModel.find_by_user("bad") == []


def test_conv_find_by_user_archived_filter(flask_core, test_user):
    active = _mk_conv(flask_core, test_user["_id"], title="Active")
    arch = _mk_conv(flask_core, test_user["_id"], title="Archived")
    with flask_core.app_context():
        ConversationModel.toggle_archive(arch["_id"], True)
        active_rows = ConversationModel.find_by_user(str(test_user["_id"]), archived=False)
        arch_rows = ConversationModel.find_by_user(str(test_user["_id"]), archived=True)
    assert {r["title"] for r in active_rows} == {"Active"}
    assert {r["title"] for r in arch_rows} == {"Archived"}


def test_conv_find_by_user_folder_filter_bad_uuid(flask_core, test_user):
    _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert ConversationModel.find_by_user(str(test_user["_id"]), folder_id="bad") == []


def test_conv_find_by_user_search(flask_core, test_user):
    _mk_conv(flask_core, test_user["_id"], title="Roadmap Q3")
    _mk_conv(flask_core, test_user["_id"], title="Budget")
    with flask_core.app_context():
        hits = ConversationModel.find_by_user(str(test_user["_id"]), search="Roadmap")
    assert len(hits) == 1 and hits[0]["title"] == "Roadmap Q3"


def test_conv_find_by_user_null_project_sentinel(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    _mk_conv(flask_core, test_user["_id"], title="Personal")  # no project
    _mk_conv(flask_core, test_user["_id"], title="Scoped", project_id=proj["_id"])
    with flask_core.app_context():
        rows = ConversationModel.find_by_user(
            str(test_user["_id"]), project_id=NULL_PROJECT_SENTINEL
        )
    assert {r["title"] for r in rows} == {"Personal"}


def test_conv_find_by_user_exact_project(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    _mk_conv(flask_core, test_user["_id"], title="Personal")
    _mk_conv(flask_core, test_user["_id"], title="Scoped", project_id=proj["_id"])
    with flask_core.app_context():
        rows = ConversationModel.find_by_user(str(test_user["_id"]), project_id=str(proj["_id"]))
    assert {r["title"] for r in rows} == {"Scoped"}


def test_conv_find_by_user_bad_project_uuid(flask_core, test_user):
    _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert ConversationModel.find_by_user(str(test_user["_id"]), project_id="garbage") == []


# ===========================================================================
# ConversationModel.update + thin wrappers.
# ===========================================================================
def test_conv_update_happy(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"], title="Old")
    with flask_core.app_context():
        obj = ConversationModel.update(conv["_id"], {"title": "New", "summary": "s"})
        assert obj is not None
        row = ConversationModel.find_by_id(conv["_id"])
    assert row["title"] == "New"
    assert row["summary"] == "s"


def test_conv_update_coerces_folder_project(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        ConversationModel.update(conv["_id"], {"project_id": str(proj["_id"])})
        row = ConversationModel.find_by_id(conv["_id"])
    assert row["project_id"] == str(proj["_id"])


def test_conv_update_bad_uuid(flask_core):
    with flask_core.app_context():
        assert ConversationModel.update("bad", {"title": "x"}) is None


def test_conv_update_missing(flask_core):
    with flask_core.app_context():
        assert ConversationModel.update(str(uuid.uuid4()), {"title": "x"}) is None


def test_conv_update_title_wrapper(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"], title="A")
    with flask_core.app_context():
        ConversationModel.update_title(conv["_id"], "B")
        assert ConversationModel.find_by_id(conv["_id"])["title"] == "B"


def test_conv_move_to_project_wrapper(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        ConversationModel.move_to_project(conv["_id"], str(proj["_id"]))
        assert ConversationModel.find_by_id(conv["_id"])["project_id"] == str(proj["_id"])


# ===========================================================================
# null_project_for_project / null_folder_for_folder.
# ===========================================================================
def test_conv_null_project_for_project(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    c = _mk_conv(flask_core, test_user["_id"], project_id=proj["_id"])
    with flask_core.app_context():
        n = ConversationModel.null_project_for_project(str(proj["_id"]))
        assert n == 1
        assert ConversationModel.find_by_id(c["_id"])["project_id"] is None


def test_conv_null_project_bad_uuid(flask_core):
    with flask_core.app_context():
        assert ConversationModel.null_project_for_project("bad") == 0


def test_conv_null_folder_for_folder_bad_uuid(flask_core):
    with flask_core.app_context():
        assert ConversationModel.null_folder_for_folder("bad") == 0


# ===========================================================================
# set_message_count.
# ===========================================================================
def test_conv_set_message_count(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        n = ConversationModel.set_message_count(conv["_id"], 7)
        assert n == 1
        assert ConversationModel.find_by_id(conv["_id"])["message_count"] == 7


def test_conv_set_message_count_bad_uuid(flask_core):
    with flask_core.app_context():
        assert ConversationModel.set_message_count("bad", 3) == 0


# ===========================================================================
# toggle_archive.
# ===========================================================================
def test_conv_toggle_archive(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        ConversationModel.toggle_archive(conv["_id"], True)
        row = ConversationModel.find_by_id(conv["_id"])
    assert row["is_archived"] is True


# ===========================================================================
# increment_message_count.
# ===========================================================================
def test_conv_increment_message_count(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        ConversationModel.increment_message_count(conv["_id"], input_tokens=10, output_tokens=5)
        row = ConversationModel.find_by_id(conv["_id"])
    assert row["message_count"] == 1
    assert row["token_count"] == {"input": 10, "output": 5, "total": 15}


def test_conv_increment_message_count_bad_uuid(flask_core):
    with flask_core.app_context():
        assert ConversationModel.increment_message_count("bad") is None


# ===========================================================================
# delete.
# ===========================================================================
def test_conv_delete(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        ConversationModel.delete(conv["_id"])
        assert ConversationModel.find_by_id(conv["_id"]) is None


def test_conv_delete_bad_uuid(flask_core):
    with flask_core.app_context():
        assert ConversationModel.delete("bad") is None


# ===========================================================================
# count_by_user — tri-state + count_active_and_archived.
# ===========================================================================
def test_conv_count_by_user(flask_core, test_user):
    _mk_conv(flask_core, test_user["_id"])
    _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert ConversationModel.count_by_user(str(test_user["_id"])) == 2


def test_conv_count_by_user_bad_owner(flask_core):
    with flask_core.app_context():
        assert ConversationModel.count_by_user("bad") == 0


def test_conv_count_by_user_null_sentinel(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    _mk_conv(flask_core, test_user["_id"])  # personal
    _mk_conv(flask_core, test_user["_id"], project_id=proj["_id"])
    with flask_core.app_context():
        assert ConversationModel.count_by_user(
            str(test_user["_id"]), project_id=NULL_PROJECT_SENTINEL
        ) == 1


def test_conv_count_by_user_exact_project(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    _mk_conv(flask_core, test_user["_id"], project_id=proj["_id"])
    with flask_core.app_context():
        assert ConversationModel.count_by_user(
            str(test_user["_id"]), project_id=str(proj["_id"])
        ) == 1


def test_conv_count_by_user_bad_project_uuid(flask_core, test_user):
    _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert ConversationModel.count_by_user(str(test_user["_id"]), project_id="bad") == 0


def test_conv_count_active_and_archived(flask_core, test_user):
    a = _mk_conv(flask_core, test_user["_id"])
    _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        ConversationModel.toggle_archive(a["_id"], True)
        active, archived = ConversationModel.count_active_and_archived_by_user(
            str(test_user["_id"])
        )
    assert active == 1
    assert archived == 1


def test_conv_count_active_and_archived_bad_owner(flask_core):
    with flask_core.app_context():
        assert ConversationModel.count_active_and_archived_by_user("bad") == (0, 0)


# ===========================================================================
# get_by_user_for_admin.
# ===========================================================================
def test_conv_get_by_user_for_admin(flask_core, test_user):
    _mk_conv(flask_core, test_user["_id"], title="AdminView")
    with flask_core.app_context():
        rows = ConversationModel.get_by_user_for_admin(str(test_user["_id"]))
    assert rows[0]["title"] == "AdminView"


def test_conv_get_by_user_for_admin_bad_owner(flask_core):
    with flask_core.app_context():
        assert ConversationModel.get_by_user_for_admin("bad") == []


# ===========================================================================
# Branch operations.
# ===========================================================================
def test_conv_add_branch_and_get(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        ok = ConversationModel.add_branch(conv["_id"], {
            "id": "feature-x", "name": "Feature X", "parent_branch": "main",
        })
        assert ok is True
        br = ConversationModel.get_branch(conv["_id"], "feature-x")
    assert br["id"] == "feature-x"
    assert br["name"] == "Feature X"
    assert br["parent_branch"] == "main"


def test_conv_add_branch_default_name(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        ok = ConversationModel.add_branch(conv["_id"], {"id": "abcdef0123456789"})
        assert ok is True
        br = ConversationModel.get_branch(conv["_id"], "abcdef0123456789")
    assert br["name"] == "Branch abcdef01"


def test_conv_add_branch_bad_uuid(flask_core):
    with flask_core.app_context():
        assert ConversationModel.add_branch("bad", {"id": "x"}) is False


def test_conv_add_branch_duplicate_rolls_back(flask_core, test_user):
    """Re-adding 'main' violates the unique constraint -> except branch -> False."""
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert ConversationModel.add_branch(conv["_id"], {"id": "main"}) is False


def test_conv_add_branch_with_branch_point(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"])
    msg_id = str(uuid.uuid4())
    with flask_core.app_context():
        ok = ConversationModel.add_branch(conv["_id"], {
            "id": "bp", "branch_point_message_id": msg_id,
        })
        assert ok is True
        br = ConversationModel.get_branch(conv["_id"], "bp")
    assert br["branch_point_message_id"] == msg_id


def test_conv_set_active_branch(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        ConversationModel.add_branch(conv["_id"], {"id": "b2"})
        assert ConversationModel.set_active_branch(conv["_id"], "b2") is True
        assert ConversationModel.find_by_id(conv["_id"])["active_branch"] == "b2"


def test_conv_set_active_branch_bad_uuid(flask_core):
    with flask_core.app_context():
        assert ConversationModel.set_active_branch("bad", "b") is False


def test_conv_remove_branch_resets_active(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        ConversationModel.add_branch(conv["_id"], {"id": "tmp"})
        ConversationModel.set_active_branch(conv["_id"], "tmp")
        assert ConversationModel.remove_branch(conv["_id"], "tmp") is True
        # active_branch falls back to 'main'.
        assert ConversationModel.find_by_id(conv["_id"])["active_branch"] == "main"


def test_conv_remove_branch_main_forbidden(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert ConversationModel.remove_branch(conv["_id"], "main") is False


def test_conv_remove_branch_bad_uuid(flask_core):
    with flask_core.app_context():
        assert ConversationModel.remove_branch("bad", "x") is False


def test_conv_remove_branch_missing_conv(flask_core):
    with flask_core.app_context():
        assert ConversationModel.remove_branch(str(uuid.uuid4()), "x") is False


def test_conv_update_branch_name(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        ConversationModel.add_branch(conv["_id"], {"id": "rn", "name": "Old"})
        assert ConversationModel.update_branch_name(conv["_id"], "rn", "Renamed") is True
        assert ConversationModel.get_branch(conv["_id"], "rn")["name"] == "Renamed"


def test_conv_update_branch_name_bad_uuid(flask_core):
    with flask_core.app_context():
        assert ConversationModel.update_branch_name("bad", "x", "y") is False


def test_conv_get_branch_bad_uuid(flask_core):
    with flask_core.app_context():
        assert ConversationModel.get_branch("bad", "main") is None


def test_conv_get_branch_missing(flask_core, test_user):
    conv = _mk_conv(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert ConversationModel.get_branch(conv["_id"], "nope") is None


# ===========================================================================
# KnowledgeItem _as_uuid helper.
# ===========================================================================
def test_ki_as_uuid_none():
    assert _as_uuid(None) is None


def test_ki_as_uuid_instance():
    u = uuid.uuid4()
    assert _as_uuid(u) is u


def test_ki_as_uuid_objectid_returns_none():
    assert _as_uuid(ObjectId()) is None


def test_ki_as_uuid_from_string():
    u = uuid.uuid4()
    assert _as_uuid(str(u)) == u


def test_ki_as_uuid_garbage_returns_none():
    assert _as_uuid("not-a-uuid") is None


def test_ki_null_sentinel_constant():
    assert KI_NULL_SENTINEL == "__null__"


# ===========================================================================
# KnowledgeItemModel.create — every source_type branch.
# ===========================================================================
def test_ki_create_chat_source_ref(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"], source_type="chat",
                  source_id="conv-1", message_id="msg-1", title="Chat KI",
                  content="body", tags=["t1"])
    assert item["title"] == "Chat KI"
    assert item["source_ref"]["conversation_id"] == "conv-1"
    assert item["source_ref"]["message_id"] == "msg-1"
    assert item["is_favorite"] is False
    assert item["tags"] == ["t1"]


def test_ki_create_workflow_source_ref(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"], source_type="workflow",
                  workflow_id="wf-9", node_id="node-2")
    assert item["source_ref"]["workflow_id"] == "wf-9"
    assert item["source_ref"]["node_id"] == "node-2"


def test_ki_create_routine_source_ref(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"], source_type="routine", source_id="rt-3")
    assert item["source_ref"]["routine_id"] == "rt-3"


def test_ki_create_meeting_source_ref(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"], source_type="meeting", source_id="mt-4",
                  metadata={"artifact_kind": "summary"})
    assert item["source_ref"]["meeting_id"] == "mt-4"
    assert item["source_ref"]["artifact_kind"] == "summary"


def test_ki_create_other_source_ref(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"], source_type="arena", source_id="ses-5",
                  message_id="m-5")
    assert item["source_ref"]["session_id"] == "ses-5"
    assert item["source_ref"]["message_id"] == "m-5"


def test_ki_create_with_project_and_workspace(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    item = _mk_ki(flask_core, test_user["_id"], project_id=proj["_id"],
                  workspace_id=ws["_id"])
    assert item["project_id"] == str(proj["_id"])
    assert item["workspace_id"] == str(ws["_id"])


# ===========================================================================
# KnowledgeItemModel.find_by_user.
# ===========================================================================
def test_ki_find_by_user_basic(flask_core, test_user):
    _mk_ki(flask_core, test_user["_id"], title="K1")
    _mk_ki(flask_core, test_user["_id"], title="K2")
    with flask_core.app_context():
        items, total = KnowledgeItemModel.find_by_user(str(test_user["_id"]))
    assert total == 2
    assert {i["title"] for i in items} == {"K1", "K2"}


def test_ki_find_by_user_bad_owner(flask_core):
    with flask_core.app_context():
        assert KnowledgeItemModel.find_by_user("bad") == ([], 0)


def test_ki_find_by_user_tag_filter(flask_core, test_user):
    _mk_ki(flask_core, test_user["_id"], title="Tagged", tags=["python"])
    _mk_ki(flask_core, test_user["_id"], title="Untagged", tags=[])
    with flask_core.app_context():
        items, total = KnowledgeItemModel.find_by_user(str(test_user["_id"]), tag="python")
    assert total == 1 and items[0]["title"] == "Tagged"


def test_ki_find_by_user_folder_root(flask_core, test_user):
    _mk_ki(flask_core, test_user["_id"], title="Root item")  # folder_id None
    with flask_core.app_context():
        items, total = KnowledgeItemModel.find_by_user(str(test_user["_id"]), folder_id="root")
    assert total == 1


def test_ki_find_by_user_folder_specific(flask_core, test_user):
    fid = str(uuid.uuid4())  # no real folder row needed for None match path; use bad-uuid filter
    _mk_ki(flask_core, test_user["_id"], title="X")
    with flask_core.app_context():
        # A random folder id matches nothing.
        items, total = KnowledgeItemModel.find_by_user(str(test_user["_id"]), folder_id=fid)
    assert total == 0


def test_ki_find_by_user_null_project(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    _mk_ki(flask_core, test_user["_id"], title="Personal")
    _mk_ki(flask_core, test_user["_id"], title="Scoped", project_id=proj["_id"],
           workspace_id=ws["_id"])
    with flask_core.app_context():
        items, total = KnowledgeItemModel.find_by_user(
            str(test_user["_id"]), project_id="null"
        )
    assert total == 1 and items[0]["title"] == "Personal"


def test_ki_find_by_user_exact_project(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    _mk_ki(flask_core, test_user["_id"], title="Scoped", project_id=proj["_id"],
           workspace_id=ws["_id"])
    with flask_core.app_context():
        items, total = KnowledgeItemModel.find_by_user(
            str(test_user["_id"]), project_id=str(proj["_id"])
        )
    assert total == 1 and items[0]["title"] == "Scoped"


# ===========================================================================
# KnowledgeItemModel.find_by_id.
# ===========================================================================
def test_ki_find_by_id_happy(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"], title="FindKI")
    with flask_core.app_context():
        row = KnowledgeItemModel.find_by_id(item["_id"])
    assert row["title"] == "FindKI"


def test_ki_find_by_id_bad_uuid(flask_core):
    with flask_core.app_context():
        assert KnowledgeItemModel.find_by_id("bad") is None


def test_ki_find_by_id_missing(flask_core):
    with flask_core.app_context():
        assert KnowledgeItemModel.find_by_id(str(uuid.uuid4())) is None


# ===========================================================================
# KnowledgeItemModel.update.
# ===========================================================================
def test_ki_update_happy(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"], title="Before")
    with flask_core.app_context():
        ok = KnowledgeItemModel.update(item["_id"], str(test_user["_id"]),
                                       {"title": "After", "notes": "n", "tags": ["a"]})
        assert ok is True
        row = KnowledgeItemModel.find_by_id(item["_id"])
    assert row["title"] == "After"
    assert row["notes"] == "n"
    assert row["tags"] == ["a"]


def test_ki_update_project_reassign_raises(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"])
    with flask_core.app_context():
        with pytest.raises(ValueError) as exc:
            KnowledgeItemModel.update(item["_id"], str(test_user["_id"]),
                                      {"project_id": str(uuid.uuid4())})
    assert "cannot_reassign_project" in str(exc.value)


def test_ki_update_bad_ids(flask_core, test_user):
    with flask_core.app_context():
        assert KnowledgeItemModel.update("bad", str(test_user["_id"]), {"title": "x"}) is False
        assert KnowledgeItemModel.update(str(uuid.uuid4()), "bad", {"title": "x"}) is False


def test_ki_update_no_allowed_fields(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"])
    with flask_core.app_context():
        # Only disallowed keys -> clean empty -> False.
        assert KnowledgeItemModel.update(item["_id"], str(test_user["_id"]),
                                         {"bogus": "v"}) is False


def test_ki_update_clears_folder(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"])
    with flask_core.app_context():
        # folder_id None branch in the clean loop.
        assert KnowledgeItemModel.update(item["_id"], str(test_user["_id"]),
                                         {"folder_id": None, "title": "T"}) is True


# ===========================================================================
# KnowledgeItemModel.delete.
# ===========================================================================
def test_ki_delete_happy(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert KnowledgeItemModel.delete(item["_id"], str(test_user["_id"])) is True
        assert KnowledgeItemModel.find_by_id(item["_id"]) is None


def test_ki_delete_wrong_owner(flask_core, test_user, admin_user):
    item = _mk_ki(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert KnowledgeItemModel.delete(item["_id"], str(admin_user["_id"])) is False


def test_ki_delete_bad_ids(flask_core, test_user):
    with flask_core.app_context():
        assert KnowledgeItemModel.delete("bad", str(test_user["_id"])) is False
        assert KnowledgeItemModel.delete(str(uuid.uuid4()), "bad") is False


# ===========================================================================
# KnowledgeItemModel.search.
# ===========================================================================
def test_ki_search_happy(flask_core, test_user):
    _mk_ki(flask_core, test_user["_id"], title="Kubernetes Notes", content="cluster")
    _mk_ki(flask_core, test_user["_id"], title="Cooking", content="pasta")
    with flask_core.app_context():
        items, total = KnowledgeItemModel.search(str(test_user["_id"]), "cluster")
    assert total == 1 and items[0]["title"] == "Kubernetes Notes"


def test_ki_search_empty_query(flask_core, test_user):
    with flask_core.app_context():
        assert KnowledgeItemModel.search(str(test_user["_id"]), "") == ([], 0)


def test_ki_search_bad_owner(flask_core):
    with flask_core.app_context():
        assert KnowledgeItemModel.search("bad", "q") == ([], 0)


# ===========================================================================
# KnowledgeItemModel.search_scoped.
# ===========================================================================
def test_ki_search_scoped_personal_and_accessible(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    _mk_ki(flask_core, test_user["_id"], title="Personal match", content="needle")
    _mk_ki(flask_core, test_user["_id"], title="Scoped match", content="needle",
           project_id=proj["_id"], workspace_id=ws["_id"])
    with flask_core.app_context():
        items, total = KnowledgeItemModel.search_scoped(
            str(test_user["_id"]), "needle", [str(proj["_id"])]
        )
    assert total == 2


def test_ki_search_scoped_no_accessible_only_personal(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    _mk_ki(flask_core, test_user["_id"], title="Personal", content="needle")
    _mk_ki(flask_core, test_user["_id"], title="Scoped", content="needle",
           project_id=proj["_id"], workspace_id=ws["_id"])
    with flask_core.app_context():
        items, total = KnowledgeItemModel.search_scoped(
            str(test_user["_id"]), "needle", []
        )
    assert total == 1 and items[0]["title"] == "Personal"


def test_ki_search_scoped_null_sentinel(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    _mk_ki(flask_core, test_user["_id"], title="Personal", content="needle")
    _mk_ki(flask_core, test_user["_id"], title="Scoped", content="needle",
           project_id=proj["_id"], workspace_id=ws["_id"])
    with flask_core.app_context():
        items, total = KnowledgeItemModel.search_scoped(
            str(test_user["_id"]), "needle", [str(proj["_id"])],
            project_id=KI_NULL_SENTINEL,
        )
    assert total == 1 and items[0]["title"] == "Personal"


def test_ki_search_scoped_exact_project(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    _mk_ki(flask_core, test_user["_id"], title="Personal", content="needle")
    _mk_ki(flask_core, test_user["_id"], title="Scoped", content="needle",
           project_id=proj["_id"], workspace_id=ws["_id"])
    with flask_core.app_context():
        items, total = KnowledgeItemModel.search_scoped(
            str(test_user["_id"]), "needle", [str(proj["_id"])],
            project_id=str(proj["_id"]),
        )
    assert total == 1 and items[0]["title"] == "Scoped"


def test_ki_search_scoped_bad_project_uuid(flask_core, test_user):
    _mk_ki(flask_core, test_user["_id"], content="needle")
    with flask_core.app_context():
        assert KnowledgeItemModel.search_scoped(
            str(test_user["_id"]), "needle", [], project_id="garbage"
        ) == ([], 0)


def test_ki_search_scoped_empty_query(flask_core, test_user):
    with flask_core.app_context():
        assert KnowledgeItemModel.search_scoped(str(test_user["_id"]), "", []) == ([], 0)


def test_ki_search_scoped_bad_owner(flask_core):
    with flask_core.app_context():
        assert KnowledgeItemModel.search_scoped("bad", "q", []) == ([], 0)


# ===========================================================================
# Tag helpers: distinct_tags / get_user_tags.
# ===========================================================================
def test_ki_distinct_tags(flask_core, test_user):
    _mk_ki(flask_core, test_user["_id"], tags=["b", "a"])
    _mk_ki(flask_core, test_user["_id"], tags=["a", "c"])
    with flask_core.app_context():
        tags = KnowledgeItemModel.get_user_tags(str(test_user["_id"]))
    assert tags == ["a", "b", "c"]


def test_ki_distinct_tags_bad_owner(flask_core):
    with flask_core.app_context():
        assert KnowledgeItemModel.distinct_tags("bad") == []


# ===========================================================================
# count_by_user / count_by_folder / counts_by_folder.
# ===========================================================================
def test_ki_count_by_user(flask_core, test_user):
    _mk_ki(flask_core, test_user["_id"])
    _mk_ki(flask_core, test_user["_id"])
    with flask_core.app_context():
        assert KnowledgeItemModel.count_by_user(str(test_user["_id"])) == 2


def test_ki_count_by_user_bad_owner(flask_core):
    with flask_core.app_context():
        assert KnowledgeItemModel.count_by_user("bad") == 0


def test_ki_count_by_folder_root(flask_core, test_user):
    _mk_ki(flask_core, test_user["_id"])  # unfiled -> root
    with flask_core.app_context():
        assert KnowledgeItemModel.count_by_folder(str(test_user["_id"]), "root") == 1
        assert KnowledgeItemModel.count_by_folder(str(test_user["_id"]), None) == 1


def test_ki_count_by_folder_specific(flask_core, test_user):
    _mk_ki(flask_core, test_user["_id"])
    with flask_core.app_context():
        # Random folder matches nothing.
        assert KnowledgeItemModel.count_by_folder(
            str(test_user["_id"]), str(uuid.uuid4())
        ) == 0


def test_ki_count_by_folder_bad_owner(flask_core):
    with flask_core.app_context():
        assert KnowledgeItemModel.count_by_folder("bad") == 0


def test_ki_counts_by_folder_empty(flask_core, test_user):
    _mk_ki(flask_core, test_user["_id"])  # only unfiled rows -> no folder buckets
    with flask_core.app_context():
        assert KnowledgeItemModel.counts_by_folder(str(test_user["_id"])) == {}


def test_ki_counts_by_folder_bad_owner(flask_core):
    with flask_core.app_context():
        assert KnowledgeItemModel.counts_by_folder("bad") == {}


# ===========================================================================
# move_to_folder.
# ===========================================================================
def test_ki_move_to_folder_clear(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"])
    with flask_core.app_context():
        n = KnowledgeItemModel.move_to_folder([item["_id"]], str(test_user["_id"]),
                                              folder_id=None)
    assert n == 1


def test_ki_move_to_folder_sync_project(flask_core, test_user):
    ws = _mk_workspace(flask_core, test_user["_id"])
    proj = _mk_project(flask_core, test_user["_id"], ws["_id"])
    item = _mk_ki(flask_core, test_user["_id"])
    with flask_core.app_context():
        n = KnowledgeItemModel.move_to_folder(
            [item["_id"]], str(test_user["_id"]), folder_id=None,
            sync_project=True, project_id=str(proj["_id"]), workspace_id=str(ws["_id"]),
        )
        assert n == 1
        row = KnowledgeItemModel.find_by_id(item["_id"])
    assert row["project_id"] == str(proj["_id"])
    assert row["workspace_id"] == str(ws["_id"])


def test_ki_move_to_folder_bad_owner(flask_core):
    with flask_core.app_context():
        assert KnowledgeItemModel.move_to_folder(["x"], "bad") == 0


def test_ki_move_to_folder_no_valid_ids(flask_core, test_user):
    with flask_core.app_context():
        assert KnowledgeItemModel.move_to_folder(["bad-id"], str(test_user["_id"])) == 0
        assert KnowledgeItemModel.move_to_folder(None, str(test_user["_id"])) == 0


# ===========================================================================
# Tag mutators: _load / add_tags / remove_tags / replace_tags.
# ===========================================================================
def test_ki_add_tags(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"], tags=["a"])
    with flask_core.app_context():
        assert KnowledgeItemModel.add_tags(item["_id"], ["b", "a"],
                                           user_id=str(test_user["_id"])) is True
        row = KnowledgeItemModel.find_by_id(item["_id"])
    # de-dup, insertion order preserved.
    assert row["tags"] == ["a", "b"]


def test_ki_add_tags_missing_row(flask_core, test_user):
    with flask_core.app_context():
        assert KnowledgeItemModel.add_tags("bad", ["x"],
                                           user_id=str(test_user["_id"])) is False


def test_ki_remove_tags(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"], tags=["a", "b", "c"])
    with flask_core.app_context():
        assert KnowledgeItemModel.remove_tags(item["_id"], ["b"]) is True
        row = KnowledgeItemModel.find_by_id(item["_id"])
    assert row["tags"] == ["a", "c"]


def test_ki_remove_tags_missing_row(flask_core):
    with flask_core.app_context():
        assert KnowledgeItemModel.remove_tags(str(uuid.uuid4()), ["x"]) is False


def test_ki_replace_tags(flask_core, test_user):
    item = _mk_ki(flask_core, test_user["_id"], tags=["old"])
    with flask_core.app_context():
        assert KnowledgeItemModel.replace_tags(item["_id"], ["new", "new", "two"]) is True
        row = KnowledgeItemModel.find_by_id(item["_id"])
    assert row["tags"] == ["new", "two"]


def test_ki_replace_tags_missing_row(flask_core):
    with flask_core.app_context():
        assert KnowledgeItemModel.replace_tags("bad", ["x"]) is False


def test_ki_load_bad_uuid(flask_core):
    with flask_core.app_context():
        assert KnowledgeItemModel._load("bad") is None
