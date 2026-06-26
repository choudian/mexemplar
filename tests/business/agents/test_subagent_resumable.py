"""013: 子代理可唤回机制（resumable / re-dispatchable subagent）行为契约测试。

覆盖：
- agent_loop: resumable_on_failure 在「迭代超限」与「LLM 调用最终失败」两路转 PAUSED；
  默认 Agent 行为不回归（仍 MAX_ITERATIONS_REACHED / ERROR）。
- orchestrator: 委派返回 subagent_id、PAUSED 句柄；_continue_subagent 续跑/再次暂停/归属校验；
  _inspect_subagent 概览且不触发 LLM。
- prompt: assistant system prompt 含子代理暂停处理指引。
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import (
    AgentConfig,
    AgentResult,
    AgentType,
    ResultType,
    ToolDefinition,
)
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from src.business.memory.context_manager import ContextManager
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from tests.conftest import MockLLMClient


def _noop_tool() -> ToolDefinition:
    return ToolDefinition(
        name="noop",
        schema={"type": "object", "properties": {}},
        handler=lambda **kw: json.dumps({"ok": True}),
    )


def _tool_call_response() -> LLMResponse:
    """每轮都调 noop（不结束），用于把循环顶到迭代上限。"""
    return LLMResponse(content=None, tool_calls=[ToolCallInfo(id="c1", name="noop", args={})])


def _new_session(agent_type: AgentType) -> str:
    """在 in-memory DB 建一个真实 session 行，返回 id（让 update_session_status 可生效）。"""
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


# ============================================================================
# agent_loop 层：PAUSED 终止语义
# ============================================================================


class TestAgentLoopPause:
    def test_iteration_limit_pauses_when_resumable(self, mock_config, in_memory_db):
        """resumable_on_failure=True 撞 max_iterations → PAUSED，会话置 suspended。"""
        config = AgentConfig(
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            system_prompt="sub",
            max_iterations=2,
            resumable_on_failure=True,
        )
        sid = _new_session(AgentType.EPHEMERAL_SUBAGENT)
        llm = MockLLMClient([_tool_call_response() for _ in range(4)])
        loop = AgentLoop(config, llm, mock_config)
        result = loop.run(sid, user_input="go", tools=[_noop_tool()])
        assert result.result_type == ResultType.PAUSED
        assert loop._get_context_manager(sid).get_session_status() == "suspended"

    def test_iteration_limit_default_still_max_reached(self, mock_config, in_memory_db):
        """默认（resumable_on_failure=False）撞 max_iterations → 仍 MAX_ITERATIONS_REACHED（回归保护）。"""
        config = AgentConfig(
            agent_type=AgentType.PM,
            system_prompt="pm",
            max_iterations=2,
        )
        sid = _new_session(AgentType.PM)
        llm = MockLLMClient([_tool_call_response() for _ in range(4)])
        loop = AgentLoop(config, llm, mock_config)
        result = loop.run(sid, user_input="go", tools=[_noop_tool()])
        assert result.result_type == ResultType.MAX_ITERATIONS_REACHED

    def test_llm_failure_pauses_when_resumable(self, mock_config, in_memory_db):
        """resumable_on_failure=True + LLM 调用经重试仍失败（账单/网络）→ PAUSED，而非 ERROR。"""
        mock_config.get_ai_retry_max_retries.return_value = 0
        mock_config.get_ai_retry_delay.return_value = 0
        config = AgentConfig(
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            system_prompt="sub",
            max_iterations=5,
            resumable_on_failure=True,
        )
        sid = _new_session(AgentType.EPHEMERAL_SUBAGENT)
        llm = MagicMock()
        llm.chat_with_tools.side_effect = RuntimeError("Error code: 429 billing limit reached")
        loop = AgentLoop(config, llm, mock_config)
        with patch("src.business.agents.agent_loop.time.sleep"):
            result = loop.run(sid, user_input="go", tools=[_noop_tool()])
        assert result.result_type == ResultType.PAUSED
        assert loop._get_context_manager(sid).get_session_status() == "suspended"

    def test_llm_failure_nonrecoverable_still_error_when_resumable(self, mock_config, in_memory_db):
        """resumable_on_failure=True 但失败不可恢复（400/校验等）→ 仍 ERROR，不误转 PAUSED。

        spec Assumptions 把可唤回失败限定为账户配额/网络类；不可恢复错误等多久都不会好，
        转可唤回暂停会误导主代理"等外部恢复"。
        """
        mock_config.get_ai_retry_max_retries.return_value = 0
        mock_config.get_ai_retry_delay.return_value = 0
        config = AgentConfig(
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            system_prompt="sub",
            max_iterations=5,
            resumable_on_failure=True,
        )
        sid = _new_session(AgentType.EPHEMERAL_SUBAGENT)
        llm = MagicMock()
        llm.chat_with_tools.side_effect = RuntimeError(
            "Error code: 400 - invalid request: messages malformed"
        )
        loop = AgentLoop(config, llm, mock_config)
        with patch("src.business.agents.agent_loop.time.sleep"):
            result = loop.run(sid, user_input="go", tools=[_noop_tool()])
        assert result.result_type == ResultType.ERROR
        assert loop._get_context_manager(sid).get_session_status() == "failed"

    def test_400_error_with_connection_text_is_not_recoverable(self, mock_config, in_memory_db):
        """错误消息里的普通 connection 文案不能把 400 永久错误误判为可恢复。"""
        mock_config.get_ai_retry_max_retries.return_value = 0
        mock_config.get_ai_retry_delay.return_value = 0
        config = AgentConfig(
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            system_prompt="sub",
            max_iterations=5,
            resumable_on_failure=True,
        )
        sid = _new_session(AgentType.EPHEMERAL_SUBAGENT)
        llm = MagicMock()
        llm.chat_with_tools.side_effect = RuntimeError(
            "Error code: 400 - invalid request: connection field is malformed"
        )
        loop = AgentLoop(config, llm, mock_config)
        with patch("src.business.agents.agent_loop.time.sleep"):
            result = loop.run(sid, user_input="go", tools=[_noop_tool()])
        assert result.result_type == ResultType.ERROR
        assert loop._get_context_manager(sid).get_session_status() == "failed"

    def test_llm_failure_default_still_error(self, mock_config, in_memory_db):
        """默认 + LLM 调用最终失败 → 仍 ERROR（回归保护）。"""
        mock_config.get_ai_retry_max_retries.return_value = 0
        mock_config.get_ai_retry_delay.return_value = 0
        config = AgentConfig(
            agent_type=AgentType.PM,
            system_prompt="pm",
            max_iterations=5,
        )
        sid = _new_session(AgentType.PM)
        llm = MagicMock()
        llm.chat_with_tools.side_effect = RuntimeError("boom")
        loop = AgentLoop(config, llm, mock_config)
        with patch("src.business.agents.agent_loop.time.sleep"):
            result = loop.run(sid, user_input="go", tools=[_noop_tool()])
        assert result.result_type == ResultType.ERROR


# ============================================================================
# orchestrator 层：委派句柄、续跑、查看、归属校验
# ============================================================================


@pytest.fixture
def orch(mock_config, in_memory_db):
    return AgentOrchestrator(MagicMock(), mock_config)


def _make_child_subagent(orch, parent_session_id, *, status="suspended"):
    """在 in-memory DB 里造一个归属 parent 的临时子代理 session，返回其 id。"""
    workflow_id = orch._new_delegation_workflow_id(parent_session_id)
    child = orch._session_store.create_session(workflow_id, AgentType.EPHEMERAL_SUBAGENT)
    if status != "active":
        ContextManager(child, orch._config).update_session_status(status)
    return child


def _patch_loop(orch, run_result):
    """patch orchestrator 内的 AgentLoop + 工具构建，让续跑不真跑 LLM。"""
    mock_loop_cls = patch("src.business.orchestration.agent.orchestrator.AgentLoop")
    patches = [
        mock_loop_cls,
        patch.object(orch, "_build_delegated_executor_tools", return_value=[]),
        patch.object(orch, "_resolve_user_tool_ids", return_value=set()),
    ]
    started = [p.start() for p in patches]
    started[0].return_value.run.return_value = run_result
    return patches, started[0]


class TestDelegateReturnsHandle:
    def test_delegate_returns_subagent_id_on_complete(self, orch):
        """委派完成 → 返回里带 subagent_id（= executor_session_id），供后续 inspect/continue。"""
        patches, mock_loop_cls = _patch_loop(orch, AgentResult(result_type=ResultType.COMPLETED))
        try:
            with (
                patch.object(orch, "_extract_latest_assistant_text", return_value="done"),
                patch.object(orch, "_record_delegation_signal"),
            ):
                res = orch._delegate_to_subagent(
                    parent_session_id="parent-D", task_description="做点事"
                )
        finally:
            for p in patches:
                p.stop()
        assert res["success"] is True
        assert res["subagent_id"]
        assert res["subagent_id"] == res["executor_session_id"]

    def test_delegate_paused_returns_handle(self, orch):
        """委派撞 PAUSED → paused=True 且带 subagent_id 句柄。"""
        patches, _ = _patch_loop(
            orch,
            AgentResult(result_type=ResultType.PAUSED, error="已达迭代上限（50 轮）"),
        )
        try:
            with patch.object(orch, "_extract_latest_assistant_text", return_value=""):
                res = orch._delegate_to_subagent(
                    parent_session_id="parent-E", task_description="复杂任务"
                )
        finally:
            for p in patches:
                p.stop()
        assert res.get("paused") is True
        assert res["subagent_id"]
        assert res["result_type"] == ResultType.PAUSED.value


class TestInspectSubagent:
    def test_inspect_returns_overview_without_llm(self, orch):
        parent = "parent-A"
        child = _make_child_subagent(orch, parent)
        ctx = ContextManager(child, orch._config)
        ctx.save_message(role="system", content="sub")
        ctx.save_user_message("task")
        ctx.save_assistant_message(
            content=None,
            tool_calls=json.dumps(
                [{"id": "c1", "name": "noop", "args": {}}, {"id": "c2", "name": "noop", "args": {}}]
            ),
        )
        ctx.save_assistant_message(content="进展中", tool_calls=None)

        res = orch._inspect_subagent(parent_session_id=parent, subagent_id=child)
        assert res["success"] is True
        assert res["assistant_turns"] == 2
        assert res["tool_call_counts"]["noop"] == 2
        assert res["status"] == "suspended"
        assert res["last_output"] == "进展中"
        orch._llm.chat_with_tools.assert_not_called()

    def test_inspect_flags_repeated_calls_when_spinning(self, orch):
        """同一工具用几乎相同的参数反复调用 → repeated_calls 标出该工具及重复次数。"""
        parent = "parent-spin"
        child = _make_child_subagent(orch, parent)
        ctx = ContextManager(child, orch._config)
        ctx.save_user_message("task")
        for _ in range(3):
            ctx.save_assistant_message(
                content=None,
                tool_calls=json.dumps(
                    [{"id": "c", "name": "web_fetch", "args": {"url": "https://x.com"}}]
                ),
            )

        res = orch._inspect_subagent(parent_session_id=parent, subagent_id=child)
        assert res["success"] is True
        repeated = {item["tool"]: item["count"] for item in res["repeated_calls"]}
        assert repeated.get("web_fetch") == 3

    def test_inspect_no_repeated_calls_when_args_differ(self, orch):
        """同一工具但每次参数不同（抓不同 URL）→ 视为正常推进，repeated_calls 不含该工具。"""
        parent = "parent-progress"
        child = _make_child_subagent(orch, parent)
        ctx = ContextManager(child, orch._config)
        ctx.save_user_message("task")
        for i in range(3):
            ctx.save_assistant_message(
                content=None,
                tool_calls=json.dumps(
                    [{"id": "c", "name": "web_fetch", "args": {"url": f"https://x.com/{i}"}}]
                ),
            )

        res = orch._inspect_subagent(parent_session_id=parent, subagent_id=child)
        assert res["success"] is True
        tools_flagged = {item["tool"] for item in res["repeated_calls"]}
        assert "web_fetch" not in tools_flagged

    def test_inspect_rejects_foreign_session(self, orch):
        foreign = _make_child_subagent(orch, "other-parent-XYZ")
        res = orch._inspect_subagent(parent_session_id="parent-A", subagent_id=foreign)
        assert res["success"] is False

    def test_inspect_rejects_async_task_id_with_guidance(self, orch):
        """主助理误把异步委派的 taskId 传给 inspect_subagent 时返回明确指引，而非含糊'未找到'。

        见 test_continue_subagent_014.py 的 continue 对应用例：tsk_/tg_ 前缀的 id 属于任务图
        命名空间，不是可唤回子代理 session，inspect 同样不应让主助理误判子代理状态。
        """
        res = orch._inspect_subagent(
            parent_session_id="parent-A", subagent_id="tsk_ceb1618f709e4244"
        )
        assert res["success"] is False
        assert "任务ID" in res["error"]
        assert "回流" in res["error"]
        assert "decide_task_adjudication" in res["error"]

    def test_inspect_rejects_old_prefix_collision_without_transition(self, orch):
        from src.data.models_sqlite import Session
        from src.data.repositories import SessionRepository

        parent_a = "123456789012-A"
        parent_b = "123456789012-B"
        repo = SessionRepository()
        repo.create(
            Session(
                session_id=parent_a,
                workflow_id="assistant-a",
                agent_type=AgentType.ASSISTANT,
                status="active",
            )
        )
        repo.create(
            Session(
                session_id=parent_b,
                workflow_id="assistant-b",
                agent_type=AgentType.ASSISTANT,
                status="active",
            )
        )
        workflow_id = f"dlg_{parent_a[:12]}_{uuid.uuid4().hex[:16]}"
        child = orch._session_store.create_session(workflow_id, AgentType.EPHEMERAL_SUBAGENT)
        ContextManager(child, orch._config).update_session_status("suspended")

        res = orch._inspect_subagent(parent_session_id=parent_b, subagent_id=child)

        assert res["success"] is False

    def test_inspect_accepts_unique_legacy_prefix_without_transition(self, orch):
        from src.data.models_sqlite import Session
        from src.data.repositories import SessionRepository

        parent = "legacyparent-001"
        repo = SessionRepository()
        repo.create(
            Session(
                session_id=parent,
                workflow_id="assistant-legacy",
                agent_type=AgentType.ASSISTANT,
                status="active",
            )
        )
        workflow_id = f"dlg_{parent[:12]}_{uuid.uuid4().hex[:16]}"
        child = orch._session_store.create_session(workflow_id, AgentType.EPHEMERAL_SUBAGENT)
        ContextManager(child, orch._config).update_session_status("suspended")

        res = orch._inspect_subagent(parent_session_id=parent, subagent_id=child)

        assert res["success"] is True

    def test_inspect_rejects_when_transition_lookup_fails(self, orch):
        parent = "parent-lookup-error"
        child = _make_child_subagent(orch, parent)
        orch._transition_repo.get_by_workflow = MagicMock(side_effect=RuntimeError("db locked"))

        res = orch._inspect_subagent(parent_session_id=parent, subagent_id=child)

        assert res["success"] is False

    def test_delegation_parent_hash_rejects_missing_parent_id(self):
        with pytest.raises(ValueError, match="parent_session_id"):
            AgentOrchestrator._delegation_parent_hash(None)


class TestContinueSubagent:
    def test_continue_completed_with_instruction(self, orch):
        parent = "parent-B"
        child = _make_child_subagent(orch, parent)
        patches, mock_loop_cls = _patch_loop(orch, AgentResult(result_type=ResultType.COMPLETED))
        try:
            with patch.object(orch, "_extract_latest_assistant_text", return_value="done"):
                res = orch._continue_subagent(
                    parent_session_id=parent, subagent_id=child, instruction="补齐剩下的"
                )
        finally:
            for p in patches:
                p.stop()
        assert res["success"] is True
        assert res["result_text"] == "done"
        run_args = mock_loop_cls.return_value.run.call_args[0]
        assert run_args[0] == child
        assert run_args[1] == "补齐剩下的"  # instruction 作为续跑输入

    def test_continue_repause_keeps_handle(self, orch):
        parent = "parent-C"
        child = _make_child_subagent(orch, parent)
        patches, _ = _patch_loop(
            orch,
            AgentResult(result_type=ResultType.PAUSED, error="已达迭代上限（20 轮）"),
        )
        try:
            with patch.object(orch, "_extract_latest_assistant_text", return_value=""):
                res = orch._continue_subagent(parent_session_id=parent, subagent_id=child)
        finally:
            for p in patches:
                p.stop()
        assert res["success"] is False
        assert res["paused"] is True
        assert res["subagent_id"] == child

    def test_continue_completed_without_instruction_asks_for_instruction(self, orch):
        """已完成子代理不带 instruction 唤回 → 明确提示需带 instruction，且不触发模型调用。"""
        parent = "parent-F"
        child = _make_child_subagent(orch, parent, status="completed")
        ctx = ContextManager(child, orch._config)
        ctx.save_message(role="system", content="sub")
        ctx.save_user_message("原任务")
        ctx.save_assistant_message(content="最终答案（部分达标）", tool_calls=None)

        with (
            patch.object(orch, "_build_delegated_executor_tools", return_value=[]),
            patch.object(orch, "_resolve_user_tool_ids", return_value=set()),
        ):
            res = orch._continue_subagent(parent_session_id=parent, subagent_id=child)

        assert res["success"] is False
        assert res["result_type"] == ResultType.NEEDS_USER_INPUT.value
        assert "instruction" in res["message"]
        orch._llm.chat_with_tools.assert_not_called()

    def test_continue_rejects_foreign_session(self, orch):
        foreign = _make_child_subagent(orch, "other-parent-ZZZ")
        res = orch._continue_subagent(parent_session_id="parent-B", subagent_id=foreign)
        assert res["success"] is False

    def test_continue_rejects_unknown_id(self, orch):
        res = orch._continue_subagent(parent_session_id="parent-B", subagent_id="nonexistent")
        assert res["success"] is False


# ============================================================================
# prompt 层：引导段存在
# ============================================================================


def test_assistant_prompt_has_pause_guidance():
    from src.business.agents.prompts.assistant_prompt import format_assistant_prompt

    prompt = format_assistant_prompt()
    assert "inspect_subagent" in prompt
    assert "continue_subagent" in prompt
    assert "暂停" in prompt
