import inspect
import json
import logging
import time

import pytest

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import (
    AgentConfig,
    AgentType,
    ResultType,
    ToolDefinition,
    ToolSignal,
)
from src.business.agents.hook_models import (
    PostHookResult,
    PreHookResult,
    ToolCallContext,
    freeze_tool_args,
)
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from src.business.agents.tools import builtin_general_tools as general_tools
from src.business.agents.tools import dynamic_tool_manager, programmer_tools
from src.business.agents.tools import recording_data_tools, trial_tools
from src.execution import tool_executor
from tests.conftest import MockLLMClient


def _schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": name,
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


def _config(**kwargs) -> AgentConfig:
    return AgentConfig(
        agent_type=AgentType.PM,
        system_prompt="You are a test agent.",
        max_iterations=10,
        **kwargs,
    )


def _run_batch(
    tools,
    tool_calls: list[ToolCallInfo],
    mock_config,
    session_id: str,
    config: AgentConfig | None = None,
):
    responses = [
        LLMResponse(content=None, tool_calls=tool_calls),
        LLMResponse(content="done", tool_calls=[]),
    ]
    loop = AgentLoop(config or _config(), MockLLMClient(responses), mock_config)
    result = loop.run(session_id=session_id, user_input="test", tools=tools)
    return loop, result


def _tool_results(loop: AgentLoop, session_id: str):
    ctx = loop._get_context_manager(session_id)
    return [m for m in ctx._msg_repo.get_context(session_id) if m.role == "tool"]


def _ctx(tool_name: str, args: dict | None = None) -> ToolCallContext:
    return ToolCallContext(
        tool_name=tool_name,
        args=freeze_tool_args(args or {}),
        session_id="direct",
        agent_type=AgentType.PM,
        iteration=1,
    )


def _tool_by_name(name: str) -> ToolDefinition:
    return next(td for td in general_tools.BUILTIN_GENERAL_TOOLS if td.name == name)


def test_no_hook_tool_remains_transparent(mock_config, in_memory_db):
    tools = [
        ToolDefinition(name="plain", schema=_schema("plain"), handler=lambda value: f"ok:{value}")
    ]
    loop, result = _run_batch(
        tools,
        [ToolCallInfo(id="c1", name="plain", args={"value": "x"})],
        mock_config,
        "hook-transparent",
    )

    assert result.result_type == ResultType.COMPLETED
    assert _tool_results(loop, "hook-transparent")[0].content == "ok:x"


def test_pre_hook_error_short_circuits_with_standardized_error(mock_config, in_memory_db):
    calls = {"handler": 0, "post": 0}

    def handler():
        calls["handler"] += 1
        return "should not run"

    def post_hook(ctx, result):
        calls["post"] += 1
        return None

    tools = [
        ToolDefinition(
            name="blocked",
            schema=_schema("blocked"),
            handler=handler,
            pre_hook=lambda ctx: PreHookResult(error="not allowed"),
            post_hook=post_hook,
        )
    ]
    loop, _ = _run_batch(
        tools,
        [ToolCallInfo(id="c1", name="blocked", args={})],
        mock_config,
        "hook-pre-reject",
    )
    payload = json.loads(_tool_results(loop, "hook-pre-reject")[0].content)

    assert calls == {"handler": 0, "post": 0}
    assert payload["error"] == "pre_hook_rejected"
    assert payload["message"] == "not allowed"


def test_post_hook_rewrites_result(mock_config, in_memory_db):
    tools = [
        ToolDefinition(
            name="rewrite",
            schema=_schema("rewrite"),
            handler=lambda: "original",
            post_hook=lambda ctx, result: PostHookResult(result=f"{result}:post"),
        )
    ]
    loop, _ = _run_batch(
        tools,
        [ToolCallInfo(id="c1", name="rewrite", args={})],
        mock_config,
        "hook-post-rewrite",
    )

    assert _tool_results(loop, "hook-post-rewrite")[0].content == "original:post"


def test_recursive_args_are_read_only_and_isolated(mock_config, in_memory_db):
    seen_args = {}

    def pre_hook(ctx):
        with pytest.raises(TypeError):
            ctx.args["top"] = "changed"
        with pytest.raises(TypeError):
            ctx.args["nested"]["value"] = "changed"
        with pytest.raises(TypeError):
            ctx.args["items"][0]["name"] = "changed"
        return None

    def handler(**kwargs):
        seen_args.update(kwargs)
        return json.dumps(kwargs)

    tools = [
        ToolDefinition(name="freeze", schema=_schema("freeze"), handler=handler, pre_hook=pre_hook)
    ]
    args = {"top": "original", "nested": {"value": "original"}, "items": [{"name": "a"}]}
    loop, _ = _run_batch(
        tools,
        [ToolCallInfo(id="c1", name="freeze", args=args)],
        mock_config,
        "hook-args-freeze",
    )

    assert seen_args == args
    assert json.loads(_tool_results(loop, "hook-args-freeze")[0].content) == args


def test_pre_hook_exception_rejects_handler_and_logs(caplog, mock_config, in_memory_db):
    calls = {"handler": 0, "post": 0}

    def pre_hook(ctx):
        raise RuntimeError("pre failed")

    def handler():
        calls["handler"] += 1
        return "handler-result"

    def post_hook(ctx, result):
        calls["post"] += 1
        return PostHookResult(result="should not run")

    tools = [
        ToolDefinition(
            name="pre_exception",
            schema=_schema("pre_exception"),
            handler=handler,
            pre_hook=pre_hook,
            post_hook=post_hook,
        )
    ]
    caplog.set_level(logging.WARNING)
    loop, _ = _run_batch(
        tools,
        [ToolCallInfo(id="c1", name="pre_exception", args={})],
        mock_config,
        "hook-pre-exception",
    )

    payload = json.loads(_tool_results(loop, "hook-pre-exception")[0].content)

    assert calls == {"handler": 0, "post": 0}
    assert payload["error"] == "pre_hook_exception"
    assert "pre_hook" in caplog.text


def test_post_hook_exception_returns_original_and_logs_warning(caplog, mock_config, in_memory_db):
    calls = {"global_post": 0}

    def post_hook(ctx, result):
        raise RuntimeError("post failed")

    def global_post(ctx, result):
        calls["global_post"] += 1
        return PostHookResult(result="should not run")

    tools = [
        ToolDefinition(
            name="post_exception",
            schema=_schema("post_exception"),
            handler=lambda: "original",
            post_hook=post_hook,
        )
    ]
    caplog.set_level(logging.WARNING)
    loop, result = _run_batch(
        tools,
        [ToolCallInfo(id="c1", name="post_exception", args={})],
        mock_config,
        "hook-post-exception",
        config=_config(global_post_hooks=[global_post]),
    )

    assert result.result_type == ResultType.COMPLETED
    assert calls["global_post"] == 0
    assert _tool_results(loop, "hook-post-exception")[0].content == "original"
    assert "post_hook" in caplog.text


def test_later_post_hook_exception_discards_earlier_rewrite(caplog, mock_config, in_memory_db):
    def global_post(ctx, result):
        raise RuntimeError("global post failed")

    tools = [
        ToolDefinition(
            name="post_rewrite_then_exception",
            schema=_schema("post_rewrite_then_exception"),
            handler=lambda: "original",
            post_hook=lambda ctx, result: PostHookResult(result="rewritten"),
        )
    ]
    caplog.set_level(logging.WARNING)
    loop, _ = _run_batch(
        tools,
        [ToolCallInfo(id="c1", name="post_rewrite_then_exception", args={})],
        mock_config,
        "hook-post-rewrite-then-exception",
        config=_config(global_post_hooks=[global_post]),
    )

    assert _tool_results(loop, "hook-post-rewrite-then-exception")[0].content == "original"
    assert "post_hook" in caplog.text


def test_handler_exception_reaches_post_hook_and_preserves_failure_status(
    mock_config, in_memory_db
):
    seen = {}
    calls = {"second": 0}

    def failing_handler():
        raise RuntimeError("boom")

    def post_hook(ctx, result):
        seen["result"] = json.loads(result)
        return PostHookResult(result="masked error")

    def second_handler():
        calls["second"] += 1
        return "should not run"

    tools = [
        ToolDefinition(
            name="fail",
            schema=_schema("fail"),
            handler=failing_handler,
            post_hook=post_hook,
        ),
        ToolDefinition(name="second", schema=_schema("second"), handler=second_handler),
    ]
    loop, _ = _run_batch(
        tools,
        [
            ToolCallInfo(id="c1", name="fail", args={}),
            ToolCallInfo(id="c2", name="second", args={}),
        ],
        mock_config,
        "hook-handler-exception",
    )
    results = _tool_results(loop, "hook-handler-exception")

    assert seen["result"]["error"] == "handler_exception"
    assert results[0].content == "masked error"
    assert json.loads(results[1].content)["error"] == "not_executed"
    assert calls["second"] == 0


def test_legal_tool_signal_skips_post_hook(mock_config, in_memory_db):
    calls = {"post": 0}

    def post_hook(ctx, result):
        calls["post"] += 1
        return None

    tools = [
        ToolDefinition(
            name="submit",
            schema=_schema("submit"),
            handler=lambda: ToolSignal(ResultType.NEEDS_USER_INPUT, "need input"),
            is_interrupting=True,
            post_hook=post_hook,
        )
    ]
    loop = AgentLoop(
        _config(text_as_user_input=False),
        MockLLMClient(
            [LLMResponse(content=None, tool_calls=[ToolCallInfo(id="c1", name="submit", args={})])]
        ),
        mock_config,
    )
    result = loop.run(session_id="hook-signal", user_input="test", tools=tools)

    assert result.result_type == ResultType.NEEDS_USER_INPUT
    assert calls["post"] == 0


def test_ordinary_tool_signal_contract_violation_cascades_not_executed(mock_config, in_memory_db):
    calls = {"second": 0}
    tools = [
        ToolDefinition(
            name="bad_signal",
            schema=_schema("bad_signal"),
            handler=lambda: ToolSignal(ResultType.COMPLETED, "bad"),
        ),
        ToolDefinition(
            name="second",
            schema=_schema("second"),
            handler=lambda: calls.__setitem__("second", calls["second"] + 1) or "ok",
        ),
    ]
    loop, _ = _run_batch(
        tools,
        [
            ToolCallInfo(id="c1", name="bad_signal", args={}),
            ToolCallInfo(id="c2", name="second", args={}),
        ],
        mock_config,
        "hook-contract-violation",
    )
    results = _tool_results(loop, "hook-contract-violation")

    assert json.loads(results[0].content)["error"] == "handler_contract_violation"
    assert json.loads(results[1].content)["error"] == "not_executed"
    assert calls["second"] == 0


def test_callable_same_name_handler_hook_and_interrupt_metadata_refresh_each_iteration(
    mock_config, in_memory_db
):
    factory_calls = {"count": 0}

    def tool_factory():
        factory_calls["count"] += 1
        if factory_calls["count"] == 1:
            return [
                ToolDefinition(
                    name="dynamic",
                    schema=_schema("dynamic"),
                    handler=lambda: "first",
                    post_hook=lambda ctx, result: PostHookResult(result="first-post"),
                )
            ]
        if factory_calls["count"] == 2:
            return [
                ToolDefinition(
                    name="dynamic",
                    schema=_schema("dynamic"),
                    handler=lambda: "second",
                    post_hook=lambda ctx, result: PostHookResult(result="second-post"),
                )
            ]
        return [
            ToolDefinition(
                name="dynamic",
                schema=_schema("dynamic"),
                handler=lambda: ToolSignal(ResultType.COMPLETED, "done"),
                is_interrupting=True,
            )
        ]

    responses = [
        LLMResponse(content=None, tool_calls=[ToolCallInfo(id="c1", name="dynamic", args={})]),
        LLMResponse(content=None, tool_calls=[ToolCallInfo(id="c2", name="dynamic", args={})]),
        LLMResponse(content=None, tool_calls=[ToolCallInfo(id="c3", name="dynamic", args={})]),
    ]
    loop = AgentLoop(_config(text_as_user_input=False), MockLLMClient(responses), mock_config)
    result = loop.run(session_id="hook-callable-refresh", user_input="test", tools=tool_factory)
    results = _tool_results(loop, "hook-callable-refresh")

    assert result.result_type == ResultType.COMPLETED
    assert results[0].content == "first-post"
    assert results[1].content == "second-post"
    assert results[2].content == "done"


def test_tool_level_noop_hook_overhead_smoke(mock_config, in_memory_db):
    plain = ToolDefinition(name="noop", schema=_schema("noop"), handler=lambda: "ok")
    hooked = ToolDefinition(
        name="noop",
        schema=_schema("noop"),
        handler=lambda: "ok",
        pre_hook=lambda ctx: None,
        post_hook=lambda ctx, result: None,
    )
    plain_loop = AgentLoop(_config(), MockLLMClient([]), mock_config)
    hooked_loop = AgentLoop(
        _config(global_pre_hooks=[lambda ctx: None], global_post_hooks=[lambda ctx, result: None]),
        MockLLMClient([]),
        mock_config,
    )
    call = ToolCallInfo(id="c1", name="noop", args={})

    start = time.perf_counter()
    for _ in range(300):
        plain_loop._execute_tool_call(call, plain, "perf", 1)
    plain_avg = (time.perf_counter() - start) / 300

    start = time.perf_counter()
    for _ in range(300):
        hooked_loop._execute_tool_call(call, hooked, "perf", 1)
    hooked_avg = (time.perf_counter() - start) / 300

    assert hooked_avg - plain_avg < 0.005


def test_builtin_general_pre_hooks_reject_before_handler(
    monkeypatch, tmp_path, mock_config, in_memory_db
):
    called = {"handler": 0}

    def handler(**kwargs):
        called["handler"] += 1
        return "should not run"

    missing_file = tmp_path / "missing.txt"
    missing_dir = tmp_path / "missing-dir"
    cases = [
        ("read_file", general_tools.read_file_pre_hook, {"path": str(missing_file)}),
        ("edit_file", general_tools.edit_file_pre_hook, {"path": str(missing_file)}),
        ("list_dir", general_tools.list_dir_pre_hook, {"path": str(missing_dir)}),
    ]
    for name, pre_hook, args in cases:
        tool = ToolDefinition(name=name, schema=_schema(name), handler=handler, pre_hook=pre_hook)
        loop, _ = _run_batch(
            [tool],
            [ToolCallInfo(id=f"{name}-call", name=name, args=args)],
            mock_config,
            f"hook-{name}-reject",
        )
        payload = json.loads(_tool_results(loop, f"hook-{name}-reject")[0].content)
        assert payload["error"] == "pre_hook_rejected"

    monkeypatch.setattr(general_tools, "_ask_user_confirm", lambda message, **_kw: False)
    exec_tool = ToolDefinition(
        name="exec",
        schema=_schema("exec"),
        handler=handler,
        pre_hook=general_tools.exec_pre_hook,
    )
    loop, _ = _run_batch(
        [exec_tool],
        [ToolCallInfo(id="exec-call", name="exec", args={"command": "python -c 1"})],
        mock_config,
        "hook-exec-confirm-reject",
    )
    assert (
        json.loads(_tool_results(loop, "hook-exec-confirm-reject")[0].content)["error"]
        == "pre_hook_rejected"
    )
    assert called["handler"] == 0


def test_builtin_general_confirm_pre_hook_denial_and_approval(
    monkeypatch, tmp_path, mock_config, in_memory_db
):
    target = tmp_path / "out.txt"
    write_tool = _tool_by_name("write_file")

    monkeypatch.setattr(general_tools, "_ask_user_confirm", lambda message, **_kw: False)
    loop, _ = _run_batch(
        [write_tool],
        [
            ToolCallInfo(
                id="c1",
                name="write_file",
                args={
                    "path": str(target),
                    "content": "no",
                },
            )
        ],
        mock_config,
        "hook-confirm-denied",
    )
    assert not target.exists()
    assert (
        json.loads(_tool_results(loop, "hook-confirm-denied")[0].content)["error"]
        == "pre_hook_rejected"
    )

    confirmations = []

    def confirm(message, **_kw):
        confirmations.append(message)
        return True

    monkeypatch.setattr(general_tools, "_ask_user_confirm", confirm)
    loop, _ = _run_batch(
        [write_tool],
        [
            ToolCallInfo(
                id="c2",
                name="write_file",
                args={
                    "path": str(target),
                    "content": "yes",
                },
            )
        ],
        mock_config,
        "hook-confirm-approved",
    )

    assert target.read_text(encoding="utf-8") == "yes"
    assert json.loads(_tool_results(loop, "hook-confirm-approved")[0].content)["success"] is True
    assert len(confirmations) == 1


def test_builtin_general_confirm_pre_hooks_fail_closed_on_confirm_error(
    monkeypatch, tmp_path, mock_config, in_memory_db
):
    class FailingSignal:
        def emit(self, request_id, message):
            raise RuntimeError("signal is gone")

    with general_tools._confirm_lock:
        general_tools._pending_confirms.clear()
    monkeypatch.setattr(general_tools, "_confirm_signal", FailingSignal())

    write_target = tmp_path / "write.txt"
    write_tool = _tool_by_name("write_file")
    loop, _ = _run_batch(
        [write_tool],
        [
            ToolCallInfo(
                id="write-call",
                name="write_file",
                args={"path": str(write_target), "content": "should not write"},
            )
        ],
        mock_config,
        "hook-confirm-error-write",
    )
    assert not write_target.exists()
    assert (
        json.loads(_tool_results(loop, "hook-confirm-error-write")[0].content)["error"]
        == "pre_hook_rejected"
    )

    edit_target = tmp_path / "edit.txt"
    edit_target.write_text("before", encoding="utf-8")
    edit_tool = _tool_by_name("edit_file")
    loop, _ = _run_batch(
        [edit_tool],
        [
            ToolCallInfo(
                id="edit-call",
                name="edit_file",
                args={
                    "path": str(edit_target),
                    "old_text": "before",
                    "new_text": "after",
                },
            )
        ],
        mock_config,
        "hook-confirm-error-edit",
    )
    assert edit_target.read_text(encoding="utf-8") == "before"
    assert (
        json.loads(_tool_results(loop, "hook-confirm-error-edit")[0].content)["error"]
        == "pre_hook_rejected"
    )

    called = {"handler": 0}

    def exec_handler(**kwargs):
        called["handler"] += 1
        return "should not run"

    exec_tool = ToolDefinition(
        name="exec",
        schema=_schema("exec"),
        handler=exec_handler,
        pre_hook=general_tools.exec_pre_hook,
    )
    loop, _ = _run_batch(
        [exec_tool],
        [ToolCallInfo(id="exec-call", name="exec", args={"command": "python -c 1"})],
        mock_config,
        "hook-confirm-error-exec",
    )
    assert called["handler"] == 0
    assert (
        json.loads(_tool_results(loop, "hook-confirm-error-exec")[0].content)["error"]
        == "pre_hook_rejected"
    )
    with general_tools._confirm_lock:
        assert general_tools._pending_confirms == {}


def test_recording_query_and_analyze_image_pre_hooks(mock_config, in_memory_db):
    query_tool = next(
        td for td in recording_data_tools.create_recording_tools("rid") if td.name == "query_data"
    )
    image_tool = next(
        td
        for td in recording_data_tools.create_recording_tools("rid")
        if td.name == "analyze_image"
    )

    blocked = query_tool.pre_hook(_ctx("query_data", {"sql": "SELECT * FROM x; DROP TABLE y"}))
    harmless_comment = query_tool.pre_hook(_ctx("query_data", {"sql": "SELECT 1 -- harmless"}))
    harmless_semicolon = query_tool.pre_hook(_ctx("query_data", {"sql": "SELECT ';' AS value"}))
    too_many = image_tool.pre_hook(
        _ctx("analyze_image", {"action_index": [1, 2, 3, 4, 5, 6], "question": "what"})
    )

    assert blocked is not None and blocked.error
    assert harmless_comment is None
    assert harmless_semicolon is None
    assert too_many is not None and "最多分析" in too_many.error


def test_trial_run_command_pre_hook_limits_per_create_trial_tools_call(
    monkeypatch, mock_config, in_memory_db
):
    commands = []

    def fake_run(command):
        commands.append(command)
        return {"success": True, "stdout": command, "stderr": ""}

    monkeypatch.setattr(trial_tools, "run_command_in_venv", fake_run)
    calls = [
        ToolCallInfo(id=f"c{i}", name="run_command", args={"command": f"cmd-{i}"})
        for i in range(1, 7)
    ]
    loop, _ = _run_batch(
        trial_tools.create_trial_tools("wf"),
        calls,
        mock_config,
        "hook-trial-limit",
    )
    results = _tool_results(loop, "hook-trial-limit")

    assert commands == [f"cmd-{i}" for i in range(1, 6)]
    assert json.loads(results[5].content)["error"] == "pre_hook_rejected"

    _run_batch(
        trial_tools.create_trial_tools("wf"),
        [ToolCallInfo(id="fresh", name="run_command", args={"command": "fresh"})],
        mock_config,
        "hook-trial-fresh",
    )
    assert commands[-1] == "fresh"


def test_migrated_handler_bodies_no_longer_contain_gate_logic():
    assert "_ask_user_confirm" not in inspect.getsource(general_tools.write_file_handler)
    assert "_ask_user_confirm" not in inspect.getsource(general_tools.edit_file_handler)
    assert "_ask_user_confirm" not in inspect.getsource(general_tools.exec_handler)
    assert "EXEC_SAFE_COMMANDS" not in inspect.getsource(general_tools.exec_handler)
    assert "_MAX_ACTION_INDICES" not in inspect.getsource(recording_data_tools._analyze_image)
    assert "rewrite(sql)" in inspect.getsource(recording_data_tools._query_data)


def test_non_migration_boundaries_remain_outside_hook_system():
    assert programmer_tools.syntax_check.pre_hook is None
    recording_tools = recording_data_tools.create_recording_tools("rid")
    execute_code = next(td for td in recording_tools if td.name == "execute_code")
    assert execute_code.pre_hook is None
    assert "run_command_in_venv" in dir(tool_executor)
    assert "return ToolDefinition" in inspect.getsource(dynamic_tool_manager.DynamicToolManager)


def test_global_pre_and_post_hooks_run_after_tool_hooks_in_order(mock_config, in_memory_db):
    events = []

    def tool_pre(ctx):
        events.append("tool_pre")
        return None

    def global_pre(ctx):
        events.append("global_pre")
        return None

    def tool_post(ctx, result):
        events.append("tool_post")
        return None

    def global_post(ctx, result):
        events.append("global_post")
        return None

    tools = [
        ToolDefinition(
            name="ordered",
            schema=_schema("ordered"),
            handler=lambda: events.append("handler") or "ok",
            pre_hook=tool_pre,
            post_hook=tool_post,
        )
    ]
    _run_batch(
        tools,
        [ToolCallInfo(id="c1", name="ordered", args={})],
        mock_config,
        "hook-global-order",
        config=_config(global_pre_hooks=[global_pre], global_post_hooks=[global_post]),
    )

    assert events == ["tool_pre", "global_pre", "handler", "tool_post", "global_post"]


def test_global_scope_context_fields_and_short_circuit(mock_config, in_memory_db):
    seen = {}
    calls = {"global_pre": 0}

    def global_pre(ctx):
        calls["global_pre"] += 1
        seen.update(
            {
                "tool_name": ctx.tool_name,
                "args": dict(ctx.args),
                "session_id": ctx.session_id,
                "agent_type": ctx.agent_type,
                "iteration": ctx.iteration,
            }
        )
        return None

    tools = [
        ToolDefinition(name="observed", schema=_schema("observed"), handler=lambda value: "ok"),
        ToolDefinition(
            name="blocked",
            schema=_schema("blocked"),
            handler=lambda: "should not run",
            pre_hook=lambda ctx: PreHookResult(error="blocked"),
        ),
    ]
    _run_batch(
        tools,
        [ToolCallInfo(id="c1", name="observed", args={"value": "x"})],
        mock_config,
        "hook-global-context",
        config=_config(global_pre_hooks=[global_pre]),
    )
    _run_batch(
        tools,
        [ToolCallInfo(id="c2", name="blocked", args={})],
        mock_config,
        "hook-global-short",
        config=_config(global_pre_hooks=[global_pre]),
    )

    assert seen == {
        "tool_name": "observed",
        "args": {"value": "x"},
        "session_id": "hook-global-context",
        "agent_type": AgentType.PM,
        "iteration": 1,
    }
    assert calls["global_pre"] == 1


def test_global_hooks_do_not_apply_to_invalid_mixed_batches_or_injected_tools(
    mock_config, in_memory_db
):
    calls = {"global": 0, "ordinary": 0, "interrupt": 0}

    def global_pre(ctx):
        calls["global"] += 1
        return None

    tools = [
        ToolDefinition(
            name="ordinary",
            schema=_schema("ordinary"),
            handler=lambda: calls.__setitem__("ordinary", calls["ordinary"] + 1) or "ok",
        ),
        ToolDefinition(
            name="interrupt",
            schema=_schema("interrupt"),
            handler=lambda: calls.__setitem__("interrupt", calls["interrupt"] + 1)
            or ToolSignal(ResultType.COMPLETED, "done"),
            is_interrupting=True,
        ),
    ]
    _run_batch(
        tools,
        [
            ToolCallInfo(id="c1", name="ordinary", args={}),
            ToolCallInfo(id="c2", name="interrupt", args={}),
        ],
        mock_config,
        "hook-invalid-no-global",
        config=_config(global_pre_hooks=[global_pre]),
    )
    _run_batch(
        [],
        [ToolCallInfo(id="c3", name="load_reference", args={"reference_id": "missing"})],
        mock_config,
        "hook-injected-no-global",
        config=_config(global_pre_hooks=[global_pre]),
    )

    assert calls == {"global": 0, "ordinary": 0, "interrupt": 0}


def test_full_chain_noop_hook_overhead_and_mounting_cost(mock_config, in_memory_db):
    def global_pre(ctx):
        return None

    config = _config(global_pre_hooks=[global_pre])

    assert len(inspect.getsource(global_pre).splitlines()) <= 30
    assert len(config.global_pre_hooks) == 1
