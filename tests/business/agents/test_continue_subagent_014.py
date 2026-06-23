"""014 US5: "继续任务"续跑路径——目标子任务 suspended→active 续跑、归属/并发校验（FR-030a）。

核心续跑机制由 013 提供；本测试聚焦 014 验收：续跑确实让暂停子任务离开 suspended 并完成，
非己出会话与运行中（active）并发续跑被拒绝。
"""

from unittest.mock import MagicMock, patch

import pytest

from src.business.agents.config import AgentResult, AgentType, ResultType
from src.business.agents.observability import AssistantObservability
from src.business.ai.llm_client import LLMResponse
from src.business.memory.context_manager import ContextManager
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from tests.conftest import MockLLMClient


@pytest.fixture
def orch(mock_config, in_memory_db):
    return AgentOrchestrator(MagicMock(), mock_config)


def _make_child_subagent(orch, parent_session_id, *, status="suspended"):
    workflow_id = orch._new_delegation_workflow_id(parent_session_id)
    child = orch._session_store.create_session(workflow_id, AgentType.EPHEMERAL_SUBAGENT)
    if status != "active":
        ContextManager(child, orch._config).update_session_status(status)
    return child


def test_continue_suspended_subagent_runs_to_completion(orch, mock_config):
    parent = "parent-cont-014"
    child = _make_child_subagent(orch, parent, status="suspended")
    # 真实 loop + mock LLM：续跑一轮即给最终结果 → 子会话离开 suspended 并完成
    orch._llm = MockLLMClient([LLMResponse(content="续跑完成", tool_calls=[])])
    with (
        patch.object(orch, "_build_delegated_executor_tools", return_value=[]),
        patch.object(orch, "_resolve_user_tool_ids", return_value=set()),
    ):
        res = orch._continue_subagent(
            parent_session_id=parent, subagent_id=child, instruction="接着做"
        )
    assert res["success"] is True
    assert res["result_text"] == "续跑完成"
    # 子会话已离开 suspended（FR-030a：suspended→active→completed）
    assert ContextManager(child, mock_config).get_session_status() == "completed"


def test_continue_cancelled_subagent_returns_paused_handle(orch):
    parent = "parent-cont-cancelled-014"
    child = _make_child_subagent(orch, parent, status="suspended")
    captured = {}

    from src.utils.events import connect

    connect(
        "assistant_subagent_paused",
        lambda sender, **kw: captured.setdefault("paused", kw),
        weak=False,
    )

    with (
        patch("src.business.orchestration.agent.orchestrator.AgentLoop") as loop_cls,
        patch.object(orch, "_build_delegated_executor_tools", return_value=[]),
        patch.object(orch, "_resolve_user_tool_ids", return_value=set()),
    ):
        loop_cls.return_value.run.return_value = AgentResult(result_type=ResultType.CANCELLED)
        res = orch._continue_subagent(
            parent_session_id=parent,
            subagent_id=child,
            instruction="接着做",
        )

    assert res["success"] is False
    assert res["paused"] is True
    assert res["cancelled"] is True
    assert res["result_type"] == ResultType.CANCELLED.value
    assert captured.get("paused", {}).get("status") == "suspended"
    transitions = orch._transition_repo.get_by_workflow(
        orch._session_store.get_session(child).workflow_id
    )
    assert any(getattr(t, "event_type", "") == "assistant_delegation_paused" for t in transitions)


def test_assistant_continue_intent_invokes_continue_subagent_tool(orch, mock_config):
    parent = orch._session_store.create_session("wf-parent-assistant", AgentType.ASSISTANT)
    child = _make_child_subagent(orch, parent, status="suspended")
    orch._llm = MockLLMClient(
        [
            LLMResponse(content="续跑完成", tool_calls=[]),
            LLMResponse(content="已继续该子任务。", tool_calls=[]),
        ]
    )

    with (
        patch.object(orch, "_build_delegated_executor_tools", return_value=[]),
        patch.object(orch, "_resolve_user_tool_ids", return_value=set()),
        patch.object(orch._prompt_builder, "format_assistant_prompt", return_value="assistant"),
        patch.object(orch, "_seal_assistant_segment_at_memory_limit", return_value=None),
    ):
        orch.run_agent(
            AgentType.ASSISTANT,
            "请继续任务",
            session_id=parent,
            assistant_continue_intent={"subagent_id": child, "instruction": "接着做"},
        )

    assert ContextManager(child, mock_config).get_session_status() == "completed"
    transcript = AssistantObservability().build_transcript(parent)
    assert any(
        step.kind == "tool_call" and step.tool_name == "continue_subagent"
        for step in transcript.steps
    )
    assert any(
        step.kind == "tool_result" and step.tool_name == "continue_subagent"
        for step in transcript.steps
    )


def test_continue_rejects_active_concurrent(orch):
    parent = "parent-active-014"
    child = _make_child_subagent(orch, parent, status="active")
    res = orch._continue_subagent(parent_session_id=parent, subagent_id=child, instruction="x")
    assert res["success"] is False
    assert "运行中" in res["error"]


def test_continue_rejects_foreign_session(orch):
    foreign = _make_child_subagent(orch, "other-parent-014")
    res = orch._continue_subagent(parent_session_id="parent-mine", subagent_id=foreign)
    assert res["success"] is False


def test_continue_subagent_binds_subagent_id_as_executor_id(orch, mock_config):
    """continue 路径必须把 subagent_id 作为 executor_id 传给委派工具集。

    首次委派路径已传 ``executor_id=session_id``；continue 路径若漏传，``ask_parent`` /
    ``meeting_send_message`` 的 sender_id 会退回 'ephemeral_subagent' 类型占位符，
    暂停子代理续跑后发会议消息会因 ``_is_participant`` 校验 PermissionError 硬失败，
    ask_parent 的提问也无法关联到具体子代理 session。
    """
    parent = "parent-cont-exec-014"
    child = _make_child_subagent(orch, parent, status="suspended")
    orch._llm = MockLLMClient([LLMResponse(content="续跑完成", tool_calls=[])])

    captured: dict = {}

    def _capture(*args, **kwargs):
        captured.update(kwargs)
        return []

    with (
        patch.object(orch, "_build_delegated_executor_tools", side_effect=_capture),
        patch.object(orch, "_resolve_user_tool_ids", return_value=set()),
    ):
        orch._continue_subagent(
            parent_session_id=parent, subagent_id=child, instruction="接着做"
        )

    assert captured.get("executor_id") == child
