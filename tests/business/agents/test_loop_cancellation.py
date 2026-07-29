"""014 US1: AgentLoop 协作式取消 + 深度取消 + orchestrator CANCELLED 处理（行为契约）。

覆盖：
- loop 在迭代开头命中 cancel_event → 不调 LLM、CANCELLED、会话 suspended。
- loop 在 LLM 返回后 / 工具批次前命中 → 不执行副作用工具、CANCELLED。
- 父子同线程链：子 loop 读到父 Event → 父子皆 suspended、CANCELLED。
- orchestrator：assistant 路径 CANCELLED 当正常终止（不发 agent_error）；
  _run_delegated_executor 把子 loop CANCELLED 当"已停止"非失败、记 paused 流转、发 subagent_paused。
"""

import json
import threading
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.business.agents import run_context
from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import (
    AgentConfig,
    AgentResult,
    AgentType,
    ResultType,
    ToolDefinition,
)
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from src.data.repositories import MessageRepository
from src.execution.process_manager import get_process_manager
from tests.conftest import MockLLMClient


def _noop_tool(handler=None) -> ToolDefinition:
    return ToolDefinition(
        name="noop",
        schema={"type": "object", "properties": {}},
        handler=handler or (lambda **kw: json.dumps({"ok": True})),
    )


def _tool_call_response() -> LLMResponse:
    return LLMResponse(content=None, tool_calls=[ToolCallInfo(id="c1", name="noop", args={})])


def _new_session(agent_type: AgentType) -> str:
    from src.business.orchestration.agent.agent_session_store import AgentSessionStore
    from src.data.repositories import (
        MessageRepository,
        SessionRepository,
        WorkflowTransitionRepository,
    )

    store = AgentSessionStore(
        session_repo=SessionRepository(),
        message_repo=MessageRepository(),
        transition_repo=WorkflowTransitionRepository(),
    )
    return store.create_session(f"wf-{uuid.uuid4().hex[:8]}", agent_type)


def _assistant_config(max_iterations=5) -> AgentConfig:
    return AgentConfig(
        agent_type=AgentType.ASSISTANT,
        system_prompt="a",
        max_iterations=max_iterations,
        text_as_user_input=True,
    )


@pytest.fixture(autouse=True)
def _clean_run_context():
    run_context.reset_for_tests()
    yield
    run_context.reset_for_tests()


class TestLoopCancellation:
    def test_executor_exit_cleans_background_processes_for_its_session(
        self, mock_config, in_memory_db, tmp_path
    ):
        sid = _new_session(AgentType.EPHEMERAL_SUBAGENT)
        manager = get_process_manager()
        script = tmp_path / "background-owned.py"
        script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        process_id = None

        def start_background():
            nonlocal process_id
            record, _ = manager.start(
                session_id=sid,
                command=f'"{sys.executable}" "{script.name}"',
                cwd=tmp_path,
                cwd_display=".",
                command_summary="background-owned.py",
            )
            process_id = record.process_id
            return json.dumps({"processId": process_id})

        llm = MockLLMClient(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[ToolCallInfo(id="bg1", name="background", args={})],
                ),
                LLMResponse(content="done", tool_calls=[]),
            ]
        )
        loop = AgentLoop(
            AgentConfig(
                agent_type=AgentType.EPHEMERAL_SUBAGENT,
                system_prompt="sub",
                max_iterations=5,
            ),
            llm,
            mock_config,
        )

        result = loop.run(
            sid,
            user_input="go",
            tools=[
                ToolDefinition(
                    name="background",
                    schema={"type": "object", "properties": {}},
                    handler=start_background,
                    has_side_effects=True,
                )
            ],
        )

        assert result.result_type == ResultType.COMPLETED
        assert process_id is not None
        assert manager.poll(process_id)["status"] == "terminated"

    def test_paused_executor_cleans_background_processes_for_its_session(
        self, mock_config, in_memory_db, tmp_path
    ):
        sid = _new_session(AgentType.EPHEMERAL_SUBAGENT)
        manager = get_process_manager()
        script = tmp_path / "background-before-pause.py"
        script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        process_id = None

        def start_background():
            nonlocal process_id
            record, _ = manager.start(
                session_id=sid,
                command=f'"{sys.executable}" "{script.name}"',
                cwd=tmp_path,
                cwd_display=".",
                command_summary="background-before-pause.py",
            )
            process_id = record.process_id
            return json.dumps({"processId": process_id})

        loop = AgentLoop(
            AgentConfig(
                agent_type=AgentType.EPHEMERAL_SUBAGENT,
                system_prompt="sub",
                max_iterations=1,
                resumable_on_failure=True,
            ),
            MockLLMClient(
                [
                    LLMResponse(
                        content=None,
                        tool_calls=[ToolCallInfo(id="bg-pause", name="background", args={})],
                    )
                ]
            ),
            mock_config,
        )

        result = loop.run(
            sid,
            user_input="go",
            tools=[
                ToolDefinition(
                    name="background",
                    schema={"type": "object", "properties": {}},
                    handler=start_background,
                    has_side_effects=True,
                )
            ],
        )

        assert result.result_type == ResultType.PAUSED
        assert process_id is not None
        assert manager.poll(process_id)["status"] == "terminated"

    def test_cancel_interrupts_inflight_llm_request(self, mock_config, in_memory_db):
        sid = _new_session(AgentType.ASSISTANT)
        run_context.begin(sid)
        entered = threading.Event()
        released = threading.Event()

        class BlockingLLM:
            def chat_with_tools(self, messages, tools, *, cancel_token=None, **kwargs):
                assert cancel_token is run_context.get_current().cancel_token
                entered.set()
                remove = cancel_token.add_callback(lambda _reason: released.set())
                try:
                    assert released.wait(timeout=2)
                    raise RuntimeError("provider request interrupted")
                finally:
                    remove()

        def cancel() -> None:
            assert entered.wait(timeout=2)
            run_context.request_cancel(sid)

        canceller = threading.Thread(target=cancel, daemon=True)
        canceller.start()
        loop = AgentLoop(_assistant_config(), BlockingLLM(), mock_config)

        result = loop.run(sid, user_input="go", tools=[_noop_tool()])

        canceller.join(timeout=2)
        assert result.result_type == ResultType.CANCELLED
        assert not canceller.is_alive()

    def test_cancel_at_iteration_start_skips_llm(self, mock_config, in_memory_db):
        sid = _new_session(AgentType.ASSISTANT)
        run_context.begin(sid)
        run_context.request_cancel(sid)  # 第一轮迭代前即停止
        llm = MagicMock()
        loop = AgentLoop(_assistant_config(), llm, mock_config)
        result = loop.run(sid, user_input="go", tools=[_noop_tool()])
        assert result.result_type == ResultType.CANCELLED
        assert loop._get_context_manager(sid).get_session_status() == "suspended"
        llm.chat_with_tools.assert_not_called()

    def test_cancel_after_llm_before_tool_batch(self, mock_config, in_memory_db):
        sid = _new_session(AgentType.ASSISTANT)
        run_context.begin(sid)
        ran = {"count": 0}

        def handler(**kw):
            ran["count"] += 1
            return json.dumps({"ok": True})

        llm = MagicMock()

        def chat(messages, tools, **kw):
            run_context.request_cancel(sid)  # 模拟"LLM 返回后用户点停止"
            return _tool_call_response()

        llm.chat_with_tools.side_effect = chat
        loop = AgentLoop(_assistant_config(), llm, mock_config)
        result = loop.run(sid, user_input="go", tools=[_noop_tool(handler)])
        assert result.result_type == ResultType.CANCELLED
        assert ran["count"] == 0  # 取消在工具批次前，副作用工具未执行
        assert loop._get_context_manager(sid).get_session_status() == "suspended"

    def test_cancelled_current_tool_is_paired_and_later_calls_stay_pending(
        self, mock_config, in_memory_db
    ):
        sid = _new_session(AgentType.EPHEMERAL_SUBAGENT)
        run_context.begin(sid)
        entered = threading.Event()
        released = threading.Event()
        third_ran = False

        def first_handler():
            return json.dumps({"step": 1})

        def cancellable_handler():
            token = run_context.get_current().cancel_token
            remove = token.add_callback(lambda _reason: released.set())
            entered.set()
            try:
                assert released.wait(timeout=2)
                return json.dumps({"step": 2, "result": "must be replaced"})
            finally:
                remove()

        def third_handler():
            nonlocal third_ran
            third_ran = True
            return json.dumps({"step": 3})

        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(id="c1", name="first", args={}),
                ToolCallInfo(id="c2", name="second", args={}),
                ToolCallInfo(id="c3", name="third", args={}),
            ],
        )
        llm = MockLLMClient([response])
        tools = [
            ToolDefinition(
                name="first",
                schema={"type": "object", "properties": {}},
                handler=first_handler,
                has_side_effects=True,
            ),
            ToolDefinition(
                name="second",
                schema={"type": "object", "properties": {}},
                handler=cancellable_handler,
                has_side_effects=True,
            ),
            ToolDefinition(
                name="third",
                schema={"type": "object", "properties": {}},
                handler=third_handler,
                has_side_effects=True,
            ),
        ]

        canceller = threading.Thread(
            target=lambda: (
                entered.wait(timeout=2),
                run_context.request_cancel(sid),
            ),
            daemon=True,
        )
        canceller.start()
        loop = AgentLoop(
            AgentConfig(
                agent_type=AgentType.EPHEMERAL_SUBAGENT,
                system_prompt="sub",
                max_iterations=5,
                resumable_on_failure=True,
            ),
            llm,
            mock_config,
        )

        result = loop.run(sid, user_input="go", tools=tools)

        canceller.join(timeout=2)
        ctx = loop._get_context_manager(sid)
        messages = MessageRepository().get_all(sid)
        by_call_id = {
            message.tool_call_id: json.loads(message.content)
            for message in messages
            if message.role == "tool"
        }
        assert result.result_type == ResultType.CANCELLED
        assert by_call_id["c1"] == {"step": 1}
        assert by_call_id["c2"] == {
            "outcome": "interrupted",
            "note": "被中断，副作用状态未知",
        }
        assert "c3" not in by_call_id
        assert [item["id"] for item in ctx.get_pending_tool_calls()] == ["c3"]
        assert third_ran is False

    def test_deep_cancel_parent_and_child_both_suspended(self, mock_config, in_memory_db):
        parent_sid = _new_session(AgentType.ASSISTANT)
        child_sid = _new_session(AgentType.EPHEMERAL_SUBAGENT)
        run_context.begin(parent_sid)

        child_config = AgentConfig(
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            system_prompt="c",
            max_iterations=5,
            resumable_on_failure=True,
        )
        child_llm = MagicMock()

        def child_chat(messages, tools, **kw):
            # 子 loop 运行期间用户点停止（set 的是父的 Event，子经 ContextVar 同一 Event）
            run_context.request_cancel(parent_sid)
            return _tool_call_response()

        child_llm.chat_with_tools.side_effect = child_chat
        child_loop = AgentLoop(child_config, child_llm, mock_config)

        def delegate_handler(**kw):
            res = child_loop.run(child_sid, "subtask", tools=[_noop_tool()])
            return json.dumps({"child_result_type": res.result_type.value})

        delegate_tool = ToolDefinition(
            name="delegate",
            schema={"type": "object", "properties": {}},
            handler=delegate_handler,
        )
        parent_llm = MagicMock()
        parent_llm.chat_with_tools.return_value = LLMResponse(
            content=None, tool_calls=[ToolCallInfo(id="d1", name="delegate", args={})]
        )
        parent_loop = AgentLoop(_assistant_config(), parent_llm, mock_config)
        result = parent_loop.run(parent_sid, user_input="go", tools=[delegate_tool])

        assert result.result_type == ResultType.CANCELLED
        assert parent_loop._get_context_manager(parent_sid).get_session_status() == "suspended"
        # 子 loop 同线程读到父 Event，在工具批次前退出 → 子也 suspended（无"主停子未停"）
        assert child_loop._get_context_manager(child_sid).get_session_status() == "suspended"

    def test_non_assistant_flow_never_cancels(self, mock_config, in_memory_db):
        """非助理流程从不 begin 运行上下文 → 取消检查恒 False，行为零变化。"""
        sid = _new_session(AgentType.PM)
        # 故意对该会话发停止信号，但从未 begin → 不应被取消
        run_context.request_cancel(sid)
        llm = MockLLMClient([LLMResponse(content="hi", tool_calls=[])])
        config = AgentConfig(
            agent_type=AgentType.PM, system_prompt="pm", max_iterations=5, text_as_user_input=True
        )
        loop = AgentLoop(config, llm, mock_config)
        result = loop.run(sid, user_input="go", tools=[_noop_tool()])
        assert result.result_type == ResultType.NEEDS_USER_INPUT


@pytest.fixture
def orch(mock_config, in_memory_db):
    return AgentOrchestrator(MagicMock(), mock_config)


def _patch_loop(orch, run_result):
    patches = [
        patch("src.business.orchestration.agent.orchestrator.AgentLoop"),
        patch.object(orch, "_build_delegated_executor_tools", return_value=[]),
        patch.object(orch, "_resolve_user_tool_ids", return_value=set()),
        patch.object(orch, "_dispatch_task_via_unified_model", return_value=None),
    ]
    started = [p.start() for p in patches]
    started[0].return_value.run.return_value = run_result
    return patches, started[0]


class TestOrchestratorCancelled:
    def test_run_agent_assistant_cancelled_is_not_error(self, orch, events_collector):
        sid = _new_session(AgentType.ASSISTANT)
        mock_loop = MagicMock()
        mock_loop.run.return_value = AgentResult(result_type=ResultType.CANCELLED)
        with (
            patch.object(orch, "_get_loop", return_value=mock_loop),
            patch.object(orch, "_build_tools", return_value=[]),
            patch.object(orch._prompt_builder, "format_assistant_prompt", return_value="sys"),
            patch.object(orch, "_seal_assistant_segment_at_memory_limit", return_value=None),
        ):
            result = orch.run_agent(AgentType.ASSISTANT, "hi", session_id=sid)
        assert result.result_type == ResultType.CANCELLED
        assert "agent_error" not in events_collector

    def test_delegated_executor_child_cancelled_returns_resumable_handle(self, orch):
        parent = "parent-cancel"
        captured = {}

        from src.utils.events import connect

        def _on_paused(sender, **kw):
            captured["paused"] = kw

        connect("assistant_subagent_paused", _on_paused, weak=False)

        patches, _ = _patch_loop(orch, AgentResult(result_type=ResultType.CANCELLED))
        try:
            with patch.object(orch, "_extract_latest_assistant_text", return_value="部分结果"):
                res = orch._delegate_to_subagent(
                    parent_session_id=parent, task_description="跑个长任务"
                )
        finally:
            for p in patches:
                p.stop()

        assert res["success"] is False
        assert res["paused"] is True
        assert res["cancelled"] is True
        assert res["subagent_id"]
        assert "continue_subagent" in res["message"]
        assert res["result_type"] == ResultType.CANCELLED.value
        # 发出了 subagent 暂停生命周期事件（归属父会话）
        assert captured.get("paused", {}).get("status") == "suspended"
        # 记录了 paused 流转，供权威子任务列表重建
        transitions = orch._transition_repo.get_by_workflow(res["workflow_id"])
        assert any(
            getattr(t, "event_type", "") == "assistant_delegation_paused" for t in transitions
        )
