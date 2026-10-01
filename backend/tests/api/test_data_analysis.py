"""Integration tests for the in-chat Data Analyzer mode (intent == 'data').

Exercises app/api/routers/chat.py ``_produce_data_analysis`` +
OpenRouterService.run_tool_loop end-to-end through the SSE bridge, with the
sandbox + dataset-prep layer MOCKED (those services are owned by another agent;
here we stub their frozen contracts):

* ``SandboxService.available`` / ``SandboxService.run`` — patched on the class.
* ``data_analysis_service.prepare_dataset`` — patched to a fake DatasetContext.
* ``OpenRouterService.chat_completion`` — stateful stub: returns ONE ``run_python``
  tool call (non-streaming round), then a no-tool final; the streamed narration
  yields plain chunks.

Asserts: the tool loop runs the sandbox, ``tool_call`` / ``tool_result`` SSE are
emitted, ``message_complete`` carries ``data_artifacts``, the artifacts/intent
are persisted to message metadata, the round cap is enforced, and the
fail-closed path fires when ``available()`` is False or no data file is present.
"""
import json

import pytest
import requests

from app.services.openrouter_service import OpenRouterService
import app.services.openrouter_service as ors_mod
import app.services.sandbox_service as sandbox_module
import app.services.data_analysis_service as data_module


# --------------------------------------------------------------------------- #
# Canned artifacts the fake sandbox emits.
# --------------------------------------------------------------------------- #
_FAKE_TABLE = {
    "type": "table",
    "name": "Top categories",
    "columns": [{"key": "cat", "label": "Category", "dtype": "object"},
                {"key": "rev", "label": "Revenue", "dtype": "float64"}],
    "rows": [{"cat": "A", "rev": 10.0}, {"cat": "B", "rev": 5.0}],
    "total_rows": 2,
}
_FAKE_CHART = {
    "type": "chart",
    "kind": "bar",
    "encoding": {"x": "cat", "y": "rev", "series": None},
    "data": [{"cat": "A", "rev": 10.0}, {"cat": "B", "rev": 5.0}],
    "title": "Revenue by category",
}

_FAKE_DATASET_CTX = {
    "workdir": "/tmp/fake-workdir",
    "files": [{"name": "sales.csv", "path": "/tmp/fake-workdir/data/sales.csv",
               "kind": "csv"}],
    "preview_markdown": "### sales.csv\n\n| cat | rev |\n|---|---|\n| A | 10 |",
    "manifest": [{"var": "df", "name": "sales.csv", "shape": [2, 2],
                  "columns": ["cat", "rev"], "dtypes": {"cat": "object", "rev": "float64"}}],
    "documents": [],
}


def _tool_call_response(call_id="call_1"):
    """A non-streaming completion that requests one run_python tool call."""
    return {
        "id": "gen-tool-1",
        "model": "test/model",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "run_python",
                        "arguments": json.dumps({
                            "code": "show_table(df); show_chart('bar', df, x='cat', y='rev')"
                        }),
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 50, "completion_tokens": 12},
    }


def _final_text_response(text="Category A leads with $10 in revenue."):
    """A non-streaming completion with no tool calls (final answer)."""
    return {
        "id": "gen-final-1",
        "model": "test/model",
        "choices": [{
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 60, "completion_tokens": 9},
    }


def _stream_narration(text="Category A leads with $10 in revenue."):
    """A streaming generator yielding the narration in two chunks then done."""
    def _gen():
        mid = len(text) // 2
        yield {"choices": [{"delta": {"content": text[:mid]}}]}
        yield {"choices": [{"delta": {"content": text[mid:]}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 60, "completion_tokens": 9}}
        yield {"done": True}
    return _gen()


# --------------------------------------------------------------------------- #
# Sandbox + dataset patches.
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_sandbox(monkeypatch):
    """Patch SandboxService.available -> True and .run -> emits canned artifacts.

    Returns a list that records every ``run`` invocation's kwargs so tests can
    assert the sandbox actually executed (and how many times).
    """
    calls = []

    def _run(*, workdir, code, timeout_s=20, mem_mb=1024, stop_event=None):
        calls.append({"workdir": workdir, "code": code})
        return {
            "stdout": "   cat   rev\n0   A  10.0\n1   B   5.0",
            "stderr": "",
            "error": None,
            "artifacts": [dict(_FAKE_TABLE), dict(_FAKE_CHART)],
            "timed_out": False,
        }

    monkeypatch.setattr(sandbox_module.SandboxService, "available",
                        staticmethod(lambda: True))
    monkeypatch.setattr(sandbox_module.SandboxService, "run", staticmethod(_run))
    monkeypatch.setattr(data_module, "prepare_dataset",
                        lambda *, conversation_id, attachments, user_id=None, **_kw: dict(_FAKE_DATASET_CTX))
    return calls


@pytest.fixture
def fake_openrouter_one_round(monkeypatch):
    """chat_completion stub: 1 tool round (non-stream) then streamed narration.

    State machine on the ``stream`` kwarg + an internal counter:
      * 1st non-streaming call  -> tool_call response
      * subsequent non-streaming -> final text (loop exits)
      * streaming call           -> narration generator
    """
    state = {"nonstream_calls": 0}

    def _cc(*args, **kwargs):
        if kwargs.get("stream"):
            return _stream_narration()
        state["nonstream_calls"] += 1
        if state["nonstream_calls"] == 1:
            return _tool_call_response()
        return _final_text_response()

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_cc))
    monkeypatch.setattr(OpenRouterService, "generate_title",
                        staticmethod(lambda *a, **k: "Data chat"))
    return state


# --------------------------------------------------------------------------- #
# Seeding helpers (real facades inside an app_context).
# --------------------------------------------------------------------------- #
def _seed_config(flask_core, owner_id):
    from app.models.llm_config import LLMConfigModel

    with flask_core.app_context():
        return LLMConfigModel.create(
            name="Analyst Config",
            model_id="test/model",
            model_name="Test Model",
            owner_id=owner_id,
            system_prompt="You are a test bot.",
        )


def _data_attachment(extracted_text=None):
    att = {
        "type": "text/csv",
        "name": "sales.csv",
        "mime_type": "text/csv",
        "upload_id": "upload-sales-1",
        "url": "/api/uploads/upload-sales-1",
    }
    if extracted_text is not None:
        att["extracted_text"] = extracted_text
    return att


def _drain(resp):
    return "".join(resp.iter_text())


def _events(body):
    """Parse the SSE body into a list of (event, data_dict) tuples."""
    out = []
    for raw in body.split("\n\n"):
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        ev = next((ln[len("event:"):].strip() for ln in lines
                   if ln.startswith("event:")), None)
        dl = next((ln[len("data:"):].strip() for ln in lines
                   if ln.startswith("data:")), None)
        if ev and dl:
            try:
                out.append((ev, json.loads(dl)))
            except json.JSONDecodeError:
                out.append((ev, {}))
    return out


# --------------------------------------------------------------------------- #
# Happy path — full tool loop + narration.
# --------------------------------------------------------------------------- #
def test_data_intent_runs_tool_loop_and_emits_artifacts(
    client, auth_headers, test_user, flask_core, fake_sandbox, fake_openrouter_one_round
):
    config = _seed_config(flask_core, test_user["_id"])

    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": str(config["_id"]),
        "message": "What are the top categories by revenue?",
        "intent": "data",
        "attachments": [_data_attachment()],
    }) as resp:
        assert resp.status_code == 200, resp.read()
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = _drain(resp)

    evs = _events(body)
    kinds = [e for e, _ in evs]

    # Lifecycle + data-specific events all present.
    assert "message_start" in kinds
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    assert "message_chunk" in kinds
    assert "message_complete" in kinds

    # The sandbox actually executed exactly once (one tool round).
    assert len(fake_sandbox) == 1
    assert "show_chart" in fake_sandbox[0]["code"]

    # tool_call carries the step + code.
    tool_call = next(d for e, d in evs if e == "tool_call")
    assert tool_call["step"] == 1
    assert "show_table" in tool_call["code"]

    # tool_result carries stdout + the artifacts (table + chart).
    tool_result = next(d for e, d in evs if e == "tool_result")
    assert tool_result["step"] == 1
    assert tool_result["error"] is None
    arts = tool_result["artifacts"]
    assert {a["type"] for a in arts} == {"table", "chart"}

    # message_complete carries data_artifacts with steps + all artifacts.
    complete = next(d for e, d in evs if e == "message_complete")
    assert complete["intent"] == "data"
    da = complete["data_artifacts"]
    assert isinstance(da["steps"], list) and len(da["steps"]) == 1
    assert da["steps"][0]["step"] == 1
    assert len(da["artifacts"]) == 2

    # Narration reconstructs from chunks.
    chunks = [d["content"] for e, d in evs if e == "message_chunk"]
    assert "".join(chunks) == "Category A leads with $10 in revenue."


def test_data_intent_persists_metadata(
    client, auth_headers, test_user, flask_core, fake_sandbox, fake_openrouter_one_round
):
    """The assistant row must persist metadata.intent='data' + data_artifacts."""
    from app.models.message import MessageModel

    config = _seed_config(flask_core, test_user["_id"])

    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": str(config["_id"]),
        "message": "Top categories?",
        "intent": "data",
        "attachments": [_data_attachment()],
    }) as resp:
        body = _drain(resp)

    complete = next(d for e, d in _events(body) if e == "message_complete")
    conv_id = complete["conversation_id"]

    with flask_core.app_context():
        msgs = MessageModel.find_by_conversation(conv_id)
    assistant = [m for m in msgs if m["role"] == "assistant"][-1]
    meta = assistant.get("metadata") or {}
    assert meta.get("intent") == "data"
    da = meta.get("data_artifacts")
    assert da is not None
    assert len(da["artifacts"]) == 2
    assert da["steps"][0]["code"].startswith("show_table")
    # Final narration text persisted as the message content.
    assert assistant["content"] == "Category A leads with $10 in revenue."


def test_data_intent_suppresses_tabular_tsv_injection(
    client, auth_headers, test_user, flask_core, fake_sandbox, monkeypatch
):
    """The data file's extracted TSV text must NOT reach the model — it gets the
    compact preview + the sandbox reads the real bytes. Capture every messages
    payload handed to chat_completion and assert the marker never appears."""
    config = _seed_config(flask_core, test_user["_id"])
    marker = "TSV_MARKER_SHOULD_NEVER_REACH_MODEL_0xCAFE"

    seen_payloads = []
    state = {"nonstream": 0}

    def _cc(*args, **kwargs):
        # Record everything the model would see (messages + system prompt).
        seen_payloads.append(json.dumps({
            "messages": kwargs.get("messages"),
            "system_prompt": kwargs.get("system_prompt"),
        }))
        if kwargs.get("stream"):
            return _stream_narration()
        state["nonstream"] += 1
        if state["nonstream"] == 1:
            return _tool_call_response()
        return _final_text_response()

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_cc))
    monkeypatch.setattr(OpenRouterService, "generate_title",
                        staticmethod(lambda *a, **k: "Data chat"))

    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": str(config["_id"]),
        "message": "Top categories?",
        "intent": "data",
        "attachments": [_data_attachment(extracted_text=marker)],
    }) as resp:
        assert resp.status_code == 200, resp.read()
        _drain(resp)

    assert seen_payloads, "chat_completion was never called"
    combined = "\n".join(seen_payloads)
    # The raw extracted TSV text must be absent from every model-bound payload...
    assert marker not in combined
    # ...while the compact dataset preview IS injected (via the system prompt).
    assert "sales.csv" in combined


# --------------------------------------------------------------------------- #
# Fail-closed paths.
# --------------------------------------------------------------------------- #
def test_data_intent_sandbox_unavailable_graceful(
    client, auth_headers, test_user, flask_core, monkeypatch
):
    """available()==False -> graceful assistant message, no crash, no tool call."""
    config = _seed_config(flask_core, test_user["_id"])

    monkeypatch.setattr(sandbox_module.SandboxService, "available",
                        staticmethod(lambda: False))
    # run must NOT be called; make it explode if it is.
    monkeypatch.setattr(sandbox_module.SandboxService, "run",
                        staticmethod(lambda **k: pytest.fail("sandbox.run called")))
    monkeypatch.setattr(OpenRouterService, "chat_completion",
                        staticmethod(lambda *a, **k: pytest.fail("LLM called")))
    monkeypatch.setattr(OpenRouterService, "generate_title",
                        staticmethod(lambda *a, **k: "Data chat"))

    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": str(config["_id"]),
        "message": "Analyze this",
        "intent": "data",
        "attachments": [_data_attachment()],
    }) as resp:
        assert resp.status_code == 200, resp.read()
        body = _drain(resp)

    evs = _events(body)
    kinds = [e for e, _ in evs]
    assert "tool_call" not in kinds
    complete = next(d for e, d in evs if e == "message_complete")
    assert "unavailable" in complete["content"].lower()


def test_data_intent_no_data_file_graceful(
    client, auth_headers, test_user, flask_core, monkeypatch
):
    """prepare_dataset()==None -> graceful 'no data file' message, no tool call."""
    config = _seed_config(flask_core, test_user["_id"])

    monkeypatch.setattr(sandbox_module.SandboxService, "available",
                        staticmethod(lambda: True))
    monkeypatch.setattr(sandbox_module.SandboxService, "run",
                        staticmethod(lambda **k: pytest.fail("sandbox.run called")))
    monkeypatch.setattr(data_module, "prepare_dataset",
                        lambda *, conversation_id, attachments, user_id=None, **_kw: None)
    monkeypatch.setattr(OpenRouterService, "chat_completion",
                        staticmethod(lambda *a, **k: pytest.fail("LLM called")))
    monkeypatch.setattr(OpenRouterService, "generate_title",
                        staticmethod(lambda *a, **k: "Data chat"))

    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": str(config["_id"]),
        "message": "Analyze (no file attached)",
        "intent": "data",
        "attachments": [],
    }) as resp:
        assert resp.status_code == 200, resp.read()
        body = _drain(resp)

    complete = next(d for e, d in _events(body) if e == "message_complete")
    assert "data file" in complete["content"].lower()


# --------------------------------------------------------------------------- #
# run_tool_loop unit-level: round cap + tool execution + message shape.
# --------------------------------------------------------------------------- #
def test_run_tool_loop_executes_tool_and_returns_final(monkeypatch):
    """One tool round then a final answer; executor runs, history is well-formed."""
    state = {"calls": 0}
    executed = []

    def _cc(*args, **kwargs):
        state["calls"] += 1
        if state["calls"] == 1:
            return _tool_call_response("call_xyz")
        return _final_text_response("done")

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_cc))

    def _exec(name, args):
        executed.append((name, args))
        return "stdout ok\n\nEmitted 1 chart (bar), 1 table (2 rows)."

    result = OpenRouterService.run_tool_loop(
        model="test/model",
        messages=[{"role": "user", "content": "go"}],
        tools=[{"type": "function", "function": {"name": "run_python"}}],
        tool_executor=_exec,
        system_prompt="SYS",
        max_rounds=6,
        user_id="u1",
        workspace_id=None,
        project_id=None,
    )

    assert result["rounds"] == 1
    assert result["capped"] is False
    assert result["error"] is None
    assert executed == [("run_python", {
        "code": "show_table(df); show_chart('bar', df, x='cat', y='rev')"
    })]
    # The returned history has the system prompt, the user turn, the assistant
    # tool-call turn, and the role:'tool' reply with the matching tool_call_id.
    msgs = result["messages"]
    assert msgs[0] == {"role": "system", "content": "SYS"}
    tool_msg = next(m for m in msgs if m.get("role") == "tool")
    assert tool_msg["tool_call_id"] == "call_xyz"
    assert tool_msg["name"] == "run_python"
    assistant_tc = next(m for m in msgs
                        if m.get("role") == "assistant" and m.get("tool_calls"))
    assert assistant_tc["tool_calls"][0]["id"] == "call_xyz"


def test_run_tool_loop_does_not_force_require_parameters(monkeypatch):
    """Regression (2026-06-11): forcing ``provider:{require_parameters:true}``
    makes OpenRouter route only to endpoints supporting EVERY param we send
    (top_p / frequency_penalty / presence_penalty) — none qualify for the
    Gemini/Anthropic endpoints, so it 404s and the whole analysis fails
    instantly. The loop MUST NOT force it."""
    captured = []

    def _cc(*args, **kwargs):
        captured.append(kwargs)
        return _final_text_response("done")

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_cc))

    OpenRouterService.run_tool_loop(
        model="test/model",
        messages=[{"role": "user", "content": "go"}],
        tools=[{"type": "function", "function": {"name": "run_python"}}],
        tool_executor=lambda name, args: "ok",
        system_prompt="SYS",
        max_rounds=6,
    )

    assert captured, "chat_completion was never called"
    for kw in captured:
        prov = kw.get("provider")
        assert not (isinstance(prov, dict) and prov.get("require_parameters")), (
            "run_tool_loop must NOT force provider.require_parameters (404s)"
        )


def test_run_tool_loop_enforces_round_cap(monkeypatch):
    """A model that calls tools forever stops at max_rounds with capped=True."""
    call_count = {"n": 0}

    def _always_tool(*args, **kwargs):
        call_count["n"] += 1
        return _tool_call_response(f"call_{call_count['n']}")

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_always_tool))

    runs = {"n": 0}

    def _exec(name, args):
        runs["n"] += 1
        return "ok"

    result = OpenRouterService.run_tool_loop(
        model="test/model",
        messages=[{"role": "user", "content": "go"}],
        tools=[{"type": "function", "function": {"name": "run_python"}}],
        tool_executor=_exec,
        max_rounds=3,
        user_id="u1",
        workspace_id=None,
        project_id=None,
    )

    assert result["capped"] is True
    assert result["rounds"] == 3
    assert runs["n"] == 3  # executor ran exactly max_rounds times
    assert result["finish_reason"] == "tool_calls"


def test_data_intent_round_cap_enforced_in_stream(
    client, auth_headers, test_user, flask_core, monkeypatch
):
    """End-to-end: a never-stopping model is capped; the sandbox runs at most
    DATA_PY_MAX_ROUNDS times and the stream still completes with a narration."""
    from app.settings import settings as app_settings

    config = _seed_config(flask_core, test_user["_id"])

    # Force a small cap so the test is fast + deterministic. settings supports a
    # per-instance override dict; monkeypatch restores it after the test.
    monkeypatch.setitem(app_settings._overrides, "DATA_PY_MAX_ROUNDS", 2)

    run_calls = {"n": 0}

    def _run(*, workdir, code, timeout_s=20, mem_mb=1024, stop_event=None):
        run_calls["n"] += 1
        return {"stdout": "ok", "stderr": "", "error": None,
                "artifacts": [dict(_FAKE_TABLE)], "timed_out": False}

    monkeypatch.setattr(sandbox_module.SandboxService, "available",
                        staticmethod(lambda: True))
    monkeypatch.setattr(sandbox_module.SandboxService, "run", staticmethod(_run))
    monkeypatch.setattr(data_module, "prepare_dataset",
                        lambda *, conversation_id, attachments, user_id=None, **_kw: dict(_FAKE_DATASET_CTX))

    nonstream = {"n": 0}

    def _cc(*args, **kwargs):
        if kwargs.get("stream"):
            return _stream_narration("capped wrap-up")
        nonstream["n"] += 1
        # Always request another tool call -> exercises the cap.
        return _tool_call_response(f"call_{nonstream['n']}")

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_cc))
    monkeypatch.setattr(OpenRouterService, "generate_title",
                        staticmethod(lambda *a, **k: "Data chat"))

    with client.stream("POST", "/api/chat/stream", headers=auth_headers, json={
        "config_id": str(config["_id"]),
        "message": "loop forever",
        "intent": "data",
        "attachments": [_data_attachment()],
    }) as resp:
        assert resp.status_code == 200, resp.read()
        body = _drain(resp)

    # Sandbox ran exactly the capped number of rounds (2), never unbounded.
    assert run_calls["n"] == 2
    evs = _events(body)
    complete = next(d for e, d in evs if e == "message_complete")
    assert complete["intent"] == "data"
    # 2 tool rounds recorded in the persisted steps.
    assert len(complete["data_artifacts"]["steps"]) == 2


# --------------------------------------------------------------------------- #
# Regenerate parity — a data-intent turn re-runs the flow (non-streamed JSON).
# --------------------------------------------------------------------------- #
def test_regenerate_data_intent_reruns_flow(
    client, auth_headers, test_user, flask_core, fake_sandbox, monkeypatch
):
    from app.models.conversation import ConversationModel
    from app.models.message import MessageModel

    config = _seed_config(flask_core, test_user["_id"])
    with flask_core.app_context():
        conv = ConversationModel.create(
            user_id=test_user["_id"], config_id=str(config["_id"]), title="Data chat",
        )
        conv_id = str(conv["_id"])
        # User turn carrying the data attachment + an assistant turn stamped
        # intent='data' (the target to regenerate).
        MessageModel.create_user_message(
            conversation_id=conv_id, content="Top categories?",
            attachments=[_data_attachment()],
        )
        assistant = MessageModel.create_assistant_message(
            conversation_id=conv_id, content="old answer", model_id="test/model",
        )
        MessageModel.merge_metadata(str(assistant["_id"]), {"intent": "data"})

    # Non-streaming loop: tool round then final answer (regenerate is JSON).
    state = {"n": 0}

    def _cc(*args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return _tool_call_response("call_regen")
        return _final_text_response("regenerated analysis")

    monkeypatch.setattr(OpenRouterService, "chat_completion", staticmethod(_cc))

    resp = client.post(
        f"/api/chat/regenerate/{assistant['_id']}", headers=auth_headers, json={},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    msg = body["message"]
    assert msg["content"] == "regenerated analysis"
    meta = msg.get("metadata") or {}
    assert meta.get("intent") == "data"
    assert len(meta["data_artifacts"]["artifacts"]) == 2
    # The sandbox ran for the regeneration.
    assert len(fake_sandbox) == 1


# --------------------------------------------------------------------------- #
# run_tool_loop usage accounting — each round writes a real usage_logs row.
# Verified WITHOUT mocking chat_completion: we mock the HTTP boundary
# (_session.request) so _record_usage runs for real and writes to the _test DB.
# Locks the per-round attribution + the helper-thread session-scope contract.
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, *, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data
        self.headers = {}
        self.content = b""

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.exceptions.HTTPError(f"HTTP {self.status_code}")
            err.response = self
            raise err


def _count_usage_rows(flask_core):
    from app.api.core import db
    from app.models.usage_log import UsageLog
    with flask_core.app_context():
        return db.session.query(UsageLog).count()


def test_run_tool_loop_records_usage_per_round(flask_core, test_user, monkeypatch):
    from app.settings import settings as app_settings

    monkeypatch.setitem(app_settings._overrides, "OPENROUTER_API_KEY", "test-key")
    # Keep the deprecation memo from touching the registry/DB on hot calls.
    monkeypatch.setattr(ors_mod, "_expiration_for", lambda model: None)

    state = {"n": 0}

    def _fake_request(method, url, **kw):
        state["n"] += 1
        if state["n"] == 1:
            body = _tool_call_response("call_u1")
        else:
            body = _final_text_response("final")
        # Each response carries its own usage so _record_usage writes a row.
        return _FakeResp(json_data=body)

    monkeypatch.setattr(ors_mod._session, "request", _fake_request)

    executed = []
    before = _count_usage_rows(flask_core)

    with flask_core.app_context():
        result = OpenRouterService.run_tool_loop(
            model="anthropic/claude-sonnet-4.5",
            messages=[{"role": "user", "content": "go"}],
            tools=[{"type": "function", "function": {"name": "run_python"}}],
            tool_executor=lambda name, args: executed.append(name) or "ok",
            system_prompt="SYS",
            max_rounds=6,
            user_id=test_user["_id"],
            workspace_id=None,
            project_id=None,
            origin="web",
        )

    assert result["rounds"] == 1
    assert executed == ["run_python"]
    # Two non-streaming completions (tool round + final) -> two usage rows.
    assert _count_usage_rows(flask_core) - before == 2
