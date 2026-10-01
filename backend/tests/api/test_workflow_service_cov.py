"""Direct unit tests for WorkflowService (tests/api/test_workflow_service_cov.py).

Targets app/services/workflow_service.py line coverage. The sibling router test
(tests/api/test_workflow.py) exercises the HTTP surface; this file drives the
service methods directly inside ``with flask_core.app_context():`` so the node
executors (textInput, aiAgent, imageGen, ttsNode, videoGenNode, imageUpload),
the SHOWCASE short-circuit, the DLP scan-field loop, build_execution_graph,
get_node_inputs, execute_workflow / execute_single_node and get_workflow_runs
ACL branches all run.

External providers (OpenRouter) are mocked by monkeypatching the
``OpenRouterService`` static methods to return canned dicts. Personal-scope
workflows (workspace_id=None) make the DLP gate short-circuit, so no DLP LLM is
hit. Mirrors test_workflow.py seeding (WorkflowModel facade) + conftest fixtures.
"""
import uuid

import pytest

from app.services.workflow_service import (
    WorkflowService,
    SHOWCASE_NODE_TYPES,
    PLATFORM_LIMITS,
    _IMAGE_STYLE_SUFFIXES,
    _ASPECT_PROMPT_HINTS,
)


# ---------------------------------------------------------------------------
# Provider mocks (module-level helpers reused by many tests).
# ---------------------------------------------------------------------------
def _mock_image(monkeypatch, *, success=True, error=None):
    from app.services.openrouter_service import OpenRouterService

    def _gen(*a, **k):
        if success:
            return {"success": True, "image_data": "data:image/png;base64,QQ=="}
        return {"success": False, "error": error or "Image generation failed"}

    monkeypatch.setattr(OpenRouterService, "generate_image", staticmethod(_gen))


def _mock_speech(monkeypatch, *, success=True, error=None):
    from app.services.openrouter_service import OpenRouterService

    def _gen(*a, **k):
        if success:
            return {
                "success": True,
                "audio_bytes": b"\x00\x01\x02ABC",
                "mime": "audio/mpeg",
                "generation_id": "gen-aud-1",
            }
        return {"success": False, "error": error or "TTS generation failed"}

    monkeypatch.setattr(OpenRouterService, "generate_speech", staticmethod(_gen))


def _mock_video(monkeypatch, *, success=True, error=None):
    from app.services.openrouter_service import OpenRouterService

    def _gen(*a, **k):
        if success:
            return {
                "success": True,
                "local_path": "/tmp/vid.mp4",
                "video_url": "https://cdn.example.com/vid.mp4",
                "generation_id": "gen-vid-1",
                "duration_sec": 8,
                "resolution": "1080p",
            }
        return {"success": False, "error": error or "Video generation failed"}

    monkeypatch.setattr(OpenRouterService, "generate_video", staticmethod(_gen))


def _mock_chat(monkeypatch, *, content="LLM OUTPUT", error=None):
    from app.services.openrouter_service import OpenRouterService

    def _chat(*a, **k):
        if error is not None:
            return {"error": {"message": error}}
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_chat))


# ---------------------------------------------------------------------------
# Seeding helpers (mirror test_workflow.py).
# ---------------------------------------------------------------------------
def _seed_personal_workflow(flask_core, user_id, *, name="Flow", nodes=None, edges=None):
    from app.models.workflow import WorkflowModel

    with flask_core.app_context():
        wid = WorkflowModel.create(
            user_id=user_id, name=name, description="d",
            nodes=nodes or [], edges=edges or [],
        )
    return wid


def _seed_project(flask_core, owner_id):
    from app.models.project import ProjectModel
    from app.models.workspace import WorkspaceModel
    from app.models.workspace_member import WorkspaceMemberModel

    with flask_core.app_context():
        ws = WorkspaceModel.create(name="Team WS", owner_id=owner_id, type="team")
        WorkspaceMemberModel.add(ws["_id"], owner_id, role="owner", status="active")
        proj = ProjectModel.create(
            workspace_id=ws["_id"], name="Proj A", created_by=owner_id
        )
    return str(ws["_id"]), str(proj["_id"])


def _seed_project_workflow(flask_core, owner_id, project_id, workspace_id, *,
                           name="Proj Flow", nodes=None, edges=None):
    from app.models.workflow import WorkflowModel

    with flask_core.app_context():
        wid = WorkflowModel.create(
            user_id=owner_id, name=name, description="",
            nodes=nodes or [], edges=edges or [],
            project_id=project_id, workspace_id=workspace_id,
        )
    return wid


# ===========================================================================
# build_execution_graph
# ===========================================================================
def test_build_graph_linear_layers():
    nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]
    layers = WorkflowService.build_execution_graph(nodes, edges)
    assert layers == [["a"], ["b"], ["c"]]


def test_build_graph_parallel_layer():
    nodes = [{"id": "root"}, {"id": "x"}, {"id": "y"}]
    edges = [{"source": "root", "target": "x"}, {"source": "root", "target": "y"}]
    layers = WorkflowService.build_execution_graph(nodes, edges)
    assert layers[0] == ["root"]
    assert set(layers[1]) == {"x", "y"}


def test_build_graph_cycle_raises():
    nodes = [{"id": "a"}, {"id": "b"}]
    edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]
    with pytest.raises(ValueError, match="cycles"):
        WorkflowService.build_execution_graph(nodes, edges)


def test_build_graph_no_edges_all_layer0():
    nodes = [{"id": "a"}, {"id": "b"}]
    layers = WorkflowService.build_execution_graph(nodes, [])
    assert set(layers[0]) == {"a", "b"}
    assert len(layers) == 1


# ===========================================================================
# get_node_inputs — text, image, audio, video, missing source.
# ===========================================================================
def test_get_node_inputs_text_then_image_and_typed():
    edges = [
        {"source": "txt", "target": "tgt"},
        {"source": "img", "target": "tgt"},
        {"source": "aud", "target": "tgt"},
        {"source": "vid", "target": "tgt"},
        {"source": "missing", "target": "tgt"},
    ]
    node_results = {
        "txt": {"status": "completed", "text": "hello text"},
        "img": {"status": "completed", "image_data": "data:image/png;base64,AA=="},
        "aud": {"status": "completed", "audio_data_uri": "data:audio/mpeg;base64,BB=="},
        "vid": {"status": "completed", "video_url": "https://cdn/x.mp4"},
    }
    inputs = WorkflowService.get_node_inputs("tgt", edges, node_results)
    # text string, image string, then typed dicts for audio + video.
    assert "hello text" in inputs
    assert "data:image/png;base64,AA==" in inputs
    assert {"kind": "audio", "url": "data:audio/mpeg;base64,BB=="} in inputs
    assert {"kind": "video", "url": "https://cdn/x.mp4"} in inputs


def test_get_node_inputs_empty_string_text_counts():
    # 'text' present even when empty -> still appended (the `is not None` branch).
    edges = [{"source": "s", "target": "t"}]
    node_results = {"s": {"status": "completed", "text": ""}}
    inputs = WorkflowService.get_node_inputs("t", edges, node_results)
    assert inputs == [""]


def test_get_node_inputs_no_matching_edges():
    inputs = WorkflowService.get_node_inputs("t", [{"source": "a", "target": "other"}], {})
    assert inputs == []


# ===========================================================================
# execute_node — textInput / imageUpload (no provider calls).
# ===========================================================================
def test_execute_node_text_input(flask_core, plain_user):
    node = {"id": "t1", "type": "textInput", "data": {"text": "static value"}}
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, [], plain_user["_id"])
    assert res["text"] == "static value"
    assert res["node_id"] == "t1"


def test_execute_node_text_input_default_empty(flask_core, plain_user):
    node = {"id": "t1", "type": "textInput", "data": {}}
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, [], plain_user["_id"])
    assert res["text"] == ""


def test_execute_node_image_upload_ok(flask_core, plain_user):
    node = {"id": "u1", "type": "imageUpload",
            "data": {"imageUrl": "data:image/png;base64,ZZ=="}}
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, [], plain_user["_id"])
    assert res["image_data"] == "data:image/png;base64,ZZ=="
    assert res["node_id"] == "u1"


def test_execute_node_image_upload_missing_data(flask_core, plain_user):
    node = {"id": "u1", "type": "imageUpload", "data": {}}
    with flask_core.app_context():
        with pytest.raises(ValueError, match="no image data"):
            WorkflowService.execute_node(node, [], plain_user["_id"])


def test_execute_node_unknown_type(flask_core, plain_user):
    node = {"id": "x", "type": "bogusType", "data": {}}
    with flask_core.app_context():
        with pytest.raises(ValueError, match="Unknown node type"):
            WorkflowService.execute_node(node, [], plain_user["_id"])


def test_execute_node_showcase_raises_not_implemented(flask_core, plain_user):
    node_type = next(iter(SHOWCASE_NODE_TYPES))
    node = {"id": "s", "type": node_type, "data": {"label": "My Showcase"}}
    with flask_core.app_context():
        with pytest.raises(NotImplementedError) as exc:
            WorkflowService.execute_node(node, [], plain_user["_id"])
    assert "showcaseNodeNotImplemented" in str(exc.value)
    assert "My Showcase" in str(exc.value)


# ===========================================================================
# execute_node — imageGen.
# ===========================================================================
def test_execute_node_image_gen_explicit_prompt(flask_core, plain_user, monkeypatch):
    _mock_image(monkeypatch)
    node = {"id": "g1", "type": "imageGen",
            "data": {"model": "google/gemini-2.5-flash-image",
                     "prompt": "a red cube", "negativePrompt": "blur",
                     "aspect_ratio": "16:9", "style_preset": "photorealistic"}}
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, [], plain_user["_id"])
    assert res["image_data"].startswith("data:image/png")
    assert res["image_id"]
    assert res["node_id"] == "g1"


def test_execute_node_image_gen_missing_model(flask_core, plain_user, monkeypatch):
    _mock_image(monkeypatch)
    node = {"id": "g1", "type": "imageGen", "data": {"prompt": "x"}}
    with flask_core.app_context():
        with pytest.raises(ValueError, match="missing model"):
            WorkflowService.execute_node(node, [], plain_user["_id"])


def test_execute_node_image_gen_prompt_from_text_input(flask_core, plain_user, monkeypatch):
    _mock_image(monkeypatch)
    # No explicit prompt -> falls back to connected text inputs (filter out
    # image/http strings). aspect_ratio default '1:1' applies a hint.
    node = {"id": "g1", "type": "imageGen", "data": {"model": "m"}}
    inputs = ["paint a sunset", "data:image/png;base64,IMG", "http://x/y.png"]
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, inputs, plain_user["_id"])
    assert res["image_id"]


def test_execute_node_image_gen_no_prompt_anywhere(flask_core, plain_user, monkeypatch):
    _mock_image(monkeypatch)
    node = {"id": "g1", "type": "imageGen", "data": {"model": "m"}}
    with flask_core.app_context():
        with pytest.raises(ValueError, match="missing prompt"):
            WorkflowService.execute_node(node, [], plain_user["_id"])


def test_execute_node_image_gen_provider_failure(flask_core, plain_user, monkeypatch):
    _mock_image(monkeypatch, success=False, error="quota exceeded")
    node = {"id": "g1", "type": "imageGen", "data": {"model": "m", "prompt": "x"}}
    with flask_core.app_context():
        with pytest.raises(ValueError, match="quota exceeded"):
            WorkflowService.execute_node(node, [], plain_user["_id"])


# ===========================================================================
# execute_node — ttsNode.
# ===========================================================================
def test_execute_node_tts_explicit_text(flask_core, plain_user, monkeypatch):
    _mock_speech(monkeypatch)
    node = {"id": "tts1", "type": "ttsNode",
            "data": {"text": "speak this", "voice": "nova", "speed": "1.5"}}
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, [], plain_user["_id"])
    assert res["audio_data_uri"].startswith("data:audio/mpeg;base64,")
    assert res["audio_id"]
    assert res["duration_ms"] >= 0
    assert res["node_id"] == "tts1"


def test_execute_node_tts_text_from_inputs_and_bad_speed(flask_core, plain_user, monkeypatch):
    _mock_speech(monkeypatch)
    # No explicit text -> concat string inputs; speed unparseable -> 1.0.
    node = {"id": "tts1", "type": "ttsNode", "data": {"speed": "fast"}}
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, ["line one", "line two"], plain_user["_id"])
    assert res["audio_id"]


def test_execute_node_tts_no_text(flask_core, plain_user, monkeypatch):
    _mock_speech(monkeypatch)
    node = {"id": "tts1", "type": "ttsNode", "data": {}}
    with flask_core.app_context():
        with pytest.raises(ValueError, match="no text input"):
            WorkflowService.execute_node(node, [], plain_user["_id"])


def test_execute_node_tts_provider_failure(flask_core, plain_user, monkeypatch):
    _mock_speech(monkeypatch, success=False, error="tts down")
    node = {"id": "tts1", "type": "ttsNode", "data": {"text": "hi"}}
    with flask_core.app_context():
        with pytest.raises(ValueError, match="tts down"):
            WorkflowService.execute_node(node, [], plain_user["_id"])


# ===========================================================================
# execute_node — videoGenNode.
# ===========================================================================
def test_execute_node_video_explicit_prompt_with_http_frame(flask_core, plain_user, monkeypatch):
    _mock_video(monkeypatch)
    node = {"id": "v1", "type": "videoGenNode",
            "data": {"prompt": "a flying car", "duration": "5",
                     "resolution": "720p", "aspect_ratio": "9:16",
                     "generate_audio": False, "seed": "42"}}
    # An external https frame passes the SSRF guard.
    inputs = ["https://example.com/keyframe.png"]
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, inputs, plain_user["_id"])
    assert res["video_url"] == "https://cdn.example.com/vid.mp4"
    assert res["video_id"]
    assert res["node_id"] == "v1"


def test_execute_node_video_prompt_from_text_inputs_bad_duration_seed(flask_core, plain_user, monkeypatch):
    _mock_video(monkeypatch)
    # No explicit prompt -> concat non-image text inputs; bad duration/seed
    # fall back to defaults. A data:image frame skips the SSRF guard.
    node = {"id": "v1", "type": "videoGenNode",
            "data": {"duration": "x", "seed": "nope"}}
    inputs = ["data:image/png;base64,FR==", "describe the scene"]
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, inputs, plain_user["_id"])
    assert res["video_id"]


def test_execute_node_video_typed_image_dict_frame(flask_core, plain_user, monkeypatch):
    _mock_video(monkeypatch)
    node = {"id": "v1", "type": "videoGenNode", "data": {"prompt": "scene"}}
    inputs = [{"kind": "image", "url": "https://example.com/k.png"}]
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, inputs, plain_user["_id"])
    assert res["video_id"]


def test_execute_node_video_blocked_frame_url(flask_core, plain_user, monkeypatch):
    _mock_video(monkeypatch)
    node = {"id": "v1", "type": "videoGenNode", "data": {"prompt": "scene"}}
    # http (not https) localhost -> validate_external_https blocks -> ValueError.
    inputs = ["http://localhost/internal.png"]
    with flask_core.app_context():
        with pytest.raises(ValueError, match="frame_url_blocked"):
            WorkflowService.execute_node(node, inputs, plain_user["_id"])


def test_execute_node_video_no_prompt(flask_core, plain_user, monkeypatch):
    _mock_video(monkeypatch)
    node = {"id": "v1", "type": "videoGenNode", "data": {}}
    with flask_core.app_context():
        with pytest.raises(ValueError, match="no prompt"):
            WorkflowService.execute_node(node, [], plain_user["_id"])


def test_execute_node_video_provider_failure(flask_core, plain_user, monkeypatch):
    _mock_video(monkeypatch, success=False, error="render failed")
    node = {"id": "v1", "type": "videoGenNode", "data": {"prompt": "x"}}
    with flask_core.app_context():
        with pytest.raises(ValueError, match="render failed"):
            WorkflowService.execute_node(node, [], plain_user["_id"])


# ===========================================================================
# execute_node — aiAgent (single + multi-variant + platform limit + errors).
# ===========================================================================
def test_execute_node_ai_agent_single(flask_core, plain_user, monkeypatch):
    _mock_chat(monkeypatch, content="generated copy")
    node = {"id": "ai1", "type": "aiAgent",
            "data": {"model": "openai/gpt-5", "system_prompt": "be terse",
                     "user_prompt_template": "Write about {{input}}"}}
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, ["cats"], plain_user["_id"])
    assert res["text"] == "generated copy"
    assert "text_variants" not in res
    assert res["node_id"] == "ai1"


def test_execute_node_ai_agent_missing_model(flask_core, plain_user, monkeypatch):
    _mock_chat(monkeypatch)
    node = {"id": "ai1", "type": "aiAgent", "data": {}}
    with flask_core.app_context():
        with pytest.raises(ValueError, match="missing model"):
            WorkflowService.execute_node(node, [], plain_user["_id"])


def test_execute_node_ai_agent_llm_error(flask_core, plain_user, monkeypatch):
    _mock_chat(monkeypatch, error="model offline")
    node = {"id": "ai1", "type": "aiAgent", "data": {"model": "m"}}
    with flask_core.app_context():
        with pytest.raises(ValueError, match="model offline"):
            WorkflowService.execute_node(node, [], plain_user["_id"])


def test_execute_node_ai_agent_platform_limit_truncates(flask_core, plain_user, monkeypatch):
    long_text = "x" * 1000
    _mock_chat(monkeypatch, content=long_text)
    # twitter limit = 280; output 1000 > 280*1.1 -> truncated to 280.
    node = {"id": "ai1", "type": "aiAgent",
            "data": {"model": "m", "platform_preset": "Twitter"}}
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, [], plain_user["_id"])
    assert len(res["text"]) == PLATFORM_LIMITS["twitter"]


def test_execute_node_ai_agent_multi_variant(flask_core, plain_user, monkeypatch):
    _mock_chat(monkeypatch, content="variant text")
    node = {"id": "ai1", "type": "aiAgent",
            "data": {"model": "m", "variants": 3, "temperature": 0.5}}
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, ["seed"], plain_user["_id"])
    assert res["text"] == "variant text"
    assert res["text_variants"] == ["variant text", "variant text", "variant text"]


def test_execute_node_ai_agent_variants_clamped_bad_value(flask_core, plain_user, monkeypatch):
    _mock_chat(monkeypatch, content="ok")
    # variants 'oops' -> caught (TypeError/ValueError) -> 1. (temperature is NOT
    # guarded in source — `float()` would raise verbatim — so use a valid one.)
    node = {"id": "ai1", "type": "aiAgent",
            "data": {"model": "m", "variants": "oops", "temperature": 0.5}}
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, [], plain_user["_id"])
    assert res["text"] == "ok"


def test_execute_node_ai_agent_brand_brief_injection(flask_core, plain_user, monkeypatch):
    """aiAgent with an owned knowledge folder injects the brand brief into the
    system prompt (B1 path)."""
    from app.models.knowledge_folder import KnowledgeFolderModel
    from app.models.knowledge_item import KnowledgeItemModel
    from app.services.openrouter_service import OpenRouterService

    captured = {}

    def _chat(*a, **k):
        captured["system_prompt"] = k.get("system_prompt")
        return {"choices": [{"message": {"content": "done"}}]}

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_chat))

    with flask_core.app_context():
        folder = KnowledgeFolderModel.create(user_id=plain_user["_id"], name="Brand")
        KnowledgeItemModel.create(
            user_id=plain_user["_id"], source_type="manual",
            content="Our tagline is Zoom.", title="Tagline",
            folder_id=str(folder["_id"]),
        )
    node = {"id": "ai1", "type": "aiAgent",
            "data": {"model": "m", "system_prompt": "base",
                     "knowledge_folder_id": str(folder["_id"])}}
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, [], plain_user["_id"])
    assert res["text"] == "done"
    assert "BRAND_BRIEF" in (captured.get("system_prompt") or "")
    assert "Zoom" in captured["system_prompt"]


def test_execute_node_ai_agent_brand_brief_unauthorized_skips(flask_core, plain_user,
                                                              test_user, monkeypatch):
    """Folder owned by a different user (no shared project) -> injection skipped,
    node still runs."""
    from app.models.knowledge_folder import KnowledgeFolderModel
    from app.services.openrouter_service import OpenRouterService

    captured = {}

    def _chat(*a, **k):
        captured["system_prompt"] = k.get("system_prompt")
        return {"choices": [{"message": {"content": "done"}}]}

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_chat))

    with flask_core.app_context():
        folder = KnowledgeFolderModel.create(user_id=test_user["_id"], name="Other")
    node = {"id": "ai1", "type": "aiAgent",
            "data": {"model": "m", "system_prompt": "base",
                     "knowledge_folder_id": str(folder["_id"])}}
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, [], plain_user["_id"])
    assert res["text"] == "done"
    assert "BRAND_BRIEF" not in (captured.get("system_prompt") or "")


def test_execute_node_ai_agent_brand_brief_folder_missing(flask_core, plain_user, monkeypatch):
    """knowledge_folder_id pointing at a nonexistent folder -> skip, still run."""
    _mock_chat(monkeypatch, content="done")
    node = {"id": "ai1", "type": "aiAgent",
            "data": {"model": "m", "knowledge_folder_id": str(uuid.uuid4())}}
    with flask_core.app_context():
        res = WorkflowService.execute_node(node, [], plain_user["_id"])
    assert res["text"] == "done"


# ===========================================================================
# _execute_node_in_thread — success + failure result_dict population.
# ===========================================================================
def test_execute_node_in_thread_success(flask_core, plain_user):
    from app.api.core import db

    node = {"id": "t1", "type": "textInput", "data": {"text": "thread text"}}
    result_dict = {}
    with flask_core.app_context():
        # _execute_node_in_thread opens its own db.session_scope() internally.
        WorkflowService._execute_node_in_thread(
            node, [], plain_user["_id"], result_dict, "t1"
        )
    assert result_dict["t1"]["status"] == "completed"
    assert result_dict["t1"]["text"] == "thread text"


def test_execute_node_in_thread_failure(flask_core, plain_user):
    node = {"id": "u1", "type": "imageUpload", "data": {}}  # missing imageUrl
    result_dict = {}
    with flask_core.app_context():
        WorkflowService._execute_node_in_thread(
            node, [], plain_user["_id"], result_dict, "u1"
        )
    assert result_dict["u1"]["status"] == "failed"
    assert "error" in result_dict["u1"]


def test_execute_node_in_thread_carries_media_fields(flask_core, plain_user, monkeypatch):
    _mock_video(monkeypatch)
    node = {"id": "v1", "type": "videoGenNode", "data": {"prompt": "scene"}}
    result_dict = {}
    with flask_core.app_context():
        WorkflowService._execute_node_in_thread(
            node, [], plain_user["_id"], result_dict, "v1"
        )
    entry = result_dict["v1"]
    assert entry["status"] == "completed"
    assert entry["video_url"]
    assert entry["video_id"]
    assert entry["resolution"]


# ===========================================================================
# _dlp_scan_nodes — unknown type raises; showcase skip; empty fields skip.
# ===========================================================================
def test_dlp_scan_unknown_node_type_raises(flask_core, plain_user):
    nodes = [{"id": "x", "type": "mysteryNode", "data": {"text": "hi"}}]
    with flask_core.app_context():
        with pytest.raises(NotImplementedError, match="unknown workflow node type"):
            WorkflowService._dlp_scan_nodes(
                nodes=nodes, workflow_id=str(uuid.uuid4()),
                workflow_workspace_id=None, workflow_project_id=None,
                user_id=plain_user["_id"], dlp_confirmed=False,
            )


def test_dlp_scan_showcase_and_empty_fields_pass(flask_core, plain_user):
    nodes = [
        {"id": "s", "type": next(iter(SHOWCASE_NODE_TYPES)), "data": {}},
        {"id": "u", "type": "imageUpload", "data": {"imageUrl": "x"}},  # empty field tuple
        {"id": "t", "type": "textInput", "data": {}},  # empty text -> skip
    ]
    with flask_core.app_context():
        # No raise; personal-scope (workspace None) means gate short-circuits.
        WorkflowService._dlp_scan_nodes(
            nodes=nodes, workflow_id=str(uuid.uuid4()),
            workflow_workspace_id=None, workflow_project_id=None,
            user_id=plain_user["_id"], dlp_confirmed=False,
        )


def test_dlp_scan_text_field_personal_scope_noop(flask_core, plain_user):
    # workspace_id None -> gate returns None for every field; no exception.
    nodes = [{"id": "t", "type": "textInput", "data": {"text": "scan me"}}]
    with flask_core.app_context():
        WorkflowService._dlp_scan_nodes(
            nodes=nodes, workflow_id=str(uuid.uuid4()),
            workflow_workspace_id=None, workflow_project_id=None,
            user_id=plain_user["_id"], dlp_confirmed=False,
        )


def test_dlp_scan_ai_agent_brand_brief_branch(flask_core, plain_user):
    """aiAgent with an owned non-empty folder reaches the brand-brief pre-scan
    dlp_gate call (no-op under personal scope)."""
    from app.models.knowledge_folder import KnowledgeFolderModel
    from app.models.knowledge_item import KnowledgeItemModel

    with flask_core.app_context():
        folder = KnowledgeFolderModel.create(user_id=plain_user["_id"], name="BB")
        KnowledgeItemModel.create(
            user_id=plain_user["_id"], source_type="manual",
            content="secret", title="T", folder_id=str(folder["_id"]),
        )
    nodes = [{"id": "ai", "type": "aiAgent",
              "data": {"user_prompt_template": "{{input}}",
                       "knowledge_folder_id": str(folder["_id"])}}]
    with flask_core.app_context():
        WorkflowService._dlp_scan_nodes(
            nodes=nodes, workflow_id=str(uuid.uuid4()),
            workflow_workspace_id=None, workflow_project_id=None,
            user_id=plain_user["_id"], dlp_confirmed=False,
        )


def test_dlp_scan_ai_agent_brand_brief_unauthorized_continue(flask_core, plain_user,
                                                             test_user):
    from app.models.knowledge_folder import KnowledgeFolderModel

    with flask_core.app_context():
        folder = KnowledgeFolderModel.create(user_id=test_user["_id"], name="X")
    nodes = [{"id": "ai", "type": "aiAgent",
              "data": {"knowledge_folder_id": str(folder["_id"])}}]
    with flask_core.app_context():
        # Unauthorized -> continue branch (no raise).
        WorkflowService._dlp_scan_nodes(
            nodes=nodes, workflow_id=str(uuid.uuid4()),
            workflow_workspace_id=None, workflow_project_id=None,
            user_id=plain_user["_id"], dlp_confirmed=False,
        )


# ===========================================================================
# execute_workflow — happy path, validation, partial, failure node.
# ===========================================================================
def test_execute_workflow_not_found(flask_core, plain_user):
    with flask_core.app_context():
        with pytest.raises(ValueError, match="Workflow not found"):
            WorkflowService.execute_workflow(str(uuid.uuid4()), plain_user["_id"])


def test_execute_workflow_no_nodes(flask_core, plain_user):
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=[])
    with flask_core.app_context():
        with pytest.raises(ValueError, match="no nodes"):
            WorkflowService.execute_workflow(wid, plain_user["_id"])


def test_execute_workflow_text_happy(flask_core, plain_user):
    nodes = [{"id": "t1", "type": "textInput", "data": {"text": "out"}}]
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=nodes, edges=[])
    with flask_core.app_context():
        res = WorkflowService.execute_workflow(wid, plain_user["_id"])
    assert res["status"] == "completed"
    assert res["run_id"]
    assert res["node_results"]["t1"]["text"] == "out"
    assert res["run"]


def test_execute_workflow_two_node_chain(flask_core, plain_user, monkeypatch):
    _mock_chat(monkeypatch, content="agent reply")
    nodes = [
        {"id": "t1", "type": "textInput", "data": {"text": "topic"}},
        {"id": "ai1", "type": "aiAgent",
         "data": {"model": "m", "user_prompt_template": "{{input}}"}},
    ]
    edges = [{"source": "t1", "target": "ai1"}]
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=nodes, edges=edges)
    with flask_core.app_context():
        res = WorkflowService.execute_workflow(wid, plain_user["_id"])
    assert res["status"] == "completed"
    assert res["node_results"]["ai1"]["text"] == "agent reply"


def test_execute_workflow_node_failure_marks_failed(flask_core, plain_user):
    # imageUpload with no data fails inside the thread -> workflow 'failed'.
    nodes = [{"id": "u1", "type": "imageUpload", "data": {}}]
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=nodes, edges=[])
    with flask_core.app_context():
        res = WorkflowService.execute_workflow(wid, plain_user["_id"])
    assert res["status"] == "failed"
    assert "failed" in res["error"]
    assert res["run_id"]


def test_execute_workflow_partial_mode_violates_db_constraint(flask_core, plain_user):
    # NOTE: possible bug — the execute-from router path calls execute_workflow
    # with execution_mode="partial" (workflow.py:327), but the DB CHECK
    # constraint ck_workflow_runs_execution_mode only permits {full, single,
    # from}. WorkflowRunModel.create() runs BEFORE the partial-filter try-block
    # (workflow_service.py:964), so a raw sqlalchemy IntegrityError (Check
    # Violation) propagates un-wrapped — it is NOT caught/converted to the
    # documented ValueError("Workflow execution failed: ..."). The whole
    # partial-filter branch (lines 976-999) is therefore unreachable at runtime.
    from sqlalchemy.exc import IntegrityError

    nodes = [
        {"id": "t1", "type": "textInput", "data": {"text": "a"}},
        {"id": "t2", "type": "textInput", "data": {"text": "b"}},
    ]
    edges = [{"source": "t1", "target": "t2"}]
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=nodes, edges=edges)
    with flask_core.app_context():
        with pytest.raises(IntegrityError):
            WorkflowService.execute_workflow(
                wid, plain_user["_id"], execution_mode="partial", start_node_id="t2"
            )


def test_execute_workflow_cycle_wrapped_failure(flask_core, plain_user):
    nodes = [{"id": "a", "type": "textInput", "data": {"text": "x"}},
             {"id": "b", "type": "textInput", "data": {"text": "y"}}]
    edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=nodes, edges=edges)
    with flask_core.app_context():
        with pytest.raises(ValueError, match="Workflow execution failed"):
            WorkflowService.execute_workflow(wid, plain_user["_id"])


# ===========================================================================
# execute_single_node — happy, input gathering branches, failure capture.
# ===========================================================================
def test_execute_single_node_text(flask_core, plain_user):
    nodes = [{"id": "t1", "type": "textInput", "data": {"text": "single"}}]
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=nodes, edges=[])
    with flask_core.app_context():
        res = WorkflowService.execute_single_node(wid, "t1", plain_user["_id"])
    assert res["status"] == "completed"
    assert res["text"] == "single"


def test_execute_single_node_not_found_workflow(flask_core, plain_user):
    with flask_core.app_context():
        with pytest.raises(ValueError, match="Workflow not found"):
            WorkflowService.execute_single_node(str(uuid.uuid4()), "n", plain_user["_id"])


def test_execute_single_node_node_missing(flask_core, plain_user):
    nodes = [{"id": "t1", "type": "textInput", "data": {"text": "x"}}]
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=nodes, edges=[])
    with flask_core.app_context():
        with pytest.raises(ValueError, match="not found in workflow"):
            WorkflowService.execute_single_node(wid, "nope", plain_user["_id"])


def test_execute_single_node_gathers_inputs_from_predecessors(flask_core, plain_user, monkeypatch):
    _mock_chat(monkeypatch, content="combined")
    # ai node pulls textInput's existing static text via the edge.
    nodes = [
        {"id": "t1", "type": "textInput", "data": {"text": "existing source text"}},
        {"id": "ai1", "type": "aiAgent",
         "data": {"model": "m", "user_prompt_template": "{{input}}"}},
    ]
    edges = [{"source": "t1", "target": "ai1"}]
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=nodes, edges=edges)
    with flask_core.app_context():
        res = WorkflowService.execute_single_node(wid, "ai1", plain_user["_id"])
    assert res["status"] == "completed"
    assert res["text"] == "combined"


def test_execute_single_node_image_predecessor_missing_data_raises(flask_core, plain_user, monkeypatch):
    _mock_image(monkeypatch)
    # imageGen target depends on imageUpload predecessor that has NO image ->
    # the input-gather loop raises ValueError -> wrapped into failed result.
    nodes = [
        {"id": "u1", "type": "imageUpload", "data": {}},  # no imageUrl
        {"id": "g1", "type": "imageGen", "data": {"model": "m", "prompt": "p"}},
    ]
    edges = [{"source": "u1", "target": "g1"}]
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=nodes, edges=edges)
    with flask_core.app_context():
        with pytest.raises(ValueError, match="has no image"):
            WorkflowService.execute_single_node(wid, "g1", plain_user["_id"])


def test_execute_single_node_aiagent_predecessor_no_text_raises(flask_core, plain_user, monkeypatch):
    _mock_chat(monkeypatch, content="x")
    nodes = [
        {"id": "ai0", "type": "aiAgent", "data": {"model": "m"}},  # no generatedText
        {"id": "ai1", "type": "aiAgent",
         "data": {"model": "m", "user_prompt_template": "{{input}}"}},
    ]
    edges = [{"source": "ai0", "target": "ai1"}]
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=nodes, edges=edges)
    with flask_core.app_context():
        with pytest.raises(ValueError, match="no generated text"):
            WorkflowService.execute_single_node(wid, "ai1", plain_user["_id"])


def test_execute_single_node_tts_predecessor_audio_dict(flask_core, plain_user, monkeypatch):
    _mock_video(monkeypatch)
    # videoGen target pulls a typed audio dict from a ttsNode predecessor that
    # has existing audioDataUri (exercises the ttsNode source branch).
    nodes = [
        {"id": "tts1", "type": "ttsNode",
         "data": {"audioDataUri": "data:audio/mpeg;base64,QQ=="}},
        {"id": "v1", "type": "videoGenNode", "data": {"prompt": "scene"}},
    ]
    edges = [{"source": "tts1", "target": "v1"}]
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=nodes, edges=edges)
    with flask_core.app_context():
        res = WorkflowService.execute_single_node(wid, "v1", plain_user["_id"])
    assert res["status"] == "completed"
    assert res["video_id"]


def test_execute_single_node_failure_returns_failed(flask_core, plain_user):
    # imageGen with no model -> execute_node raises -> caught -> failed dict.
    nodes = [{"id": "g1", "type": "imageGen", "data": {"prompt": "p"}}]
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=nodes, edges=[])
    with flask_core.app_context():
        res = WorkflowService.execute_single_node(wid, "g1", plain_user["_id"])
    assert res["status"] == "failed"
    assert res["node_id"] == "g1"
    assert "error" in res


# ===========================================================================
# get_workflow_runs — personal + project ACL branches.
# ===========================================================================
def test_get_workflow_runs_not_found(flask_core, plain_user):
    with flask_core.app_context():
        with pytest.raises(ValueError, match="Workflow not found"):
            WorkflowService.get_workflow_runs(str(uuid.uuid4()), plain_user["_id"])


def test_get_workflow_runs_personal_empty(flask_core, plain_user):
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=[])
    with flask_core.app_context():
        runs = WorkflowService.get_workflow_runs(wid, plain_user["_id"])
    assert runs == []


def test_get_workflow_runs_personal_unauthorized(flask_core, plain_user, test_user):
    wid = _seed_personal_workflow(flask_core, test_user["_id"], nodes=[])
    with flask_core.app_context():
        with pytest.raises(ValueError, match="Unauthorized access"):
            WorkflowService.get_workflow_runs(wid, plain_user["_id"])


def test_get_workflow_runs_personal_after_execute(flask_core, plain_user):
    nodes = [{"id": "t1", "type": "textInput", "data": {"text": "x"}}]
    wid = _seed_personal_workflow(flask_core, plain_user["_id"], nodes=nodes, edges=[])
    with flask_core.app_context():
        WorkflowService.execute_workflow(wid, plain_user["_id"])
        runs = WorkflowService.get_workflow_runs(wid, plain_user["_id"])
    assert len(runs) >= 1


def test_get_workflow_runs_project_owner_ok(flask_core, test_user):
    ws_id, proj_id = _seed_project(flask_core, test_user["_id"])
    wid = _seed_project_workflow(flask_core, test_user["_id"], proj_id, ws_id, nodes=[])
    with flask_core.app_context():
        # Owner has implicit editor on the project -> ACL passes -> [] runs.
        runs = WorkflowService.get_workflow_runs(wid, test_user["_id"])
    assert runs == []


def test_get_workflow_runs_project_no_access_denied(flask_core, test_user, plain_user):
    ws_id, proj_id = _seed_project(flask_core, test_user["_id"])
    wid = _seed_project_workflow(flask_core, test_user["_id"], proj_id, ws_id, nodes=[])
    with flask_core.app_context():
        with pytest.raises(ValueError, match="Unauthorized access"):
            WorkflowService.get_workflow_runs(wid, plain_user["_id"])
