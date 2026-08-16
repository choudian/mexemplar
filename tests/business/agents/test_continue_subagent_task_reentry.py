"""continue_subagent 续跑任务图节点后必须回流任务状态。

真机（2026-08-16 会话 ast_08d1c8100ab9）：图节点撞 50 轮迭代上限 → attempt 落 paused、
task 落 suspended/budget_exhausted。主助理照 prompt 与 reentry briefing 的建议调
continue_subagent 续跑，执行体真的跑完并交回 7982 字符结果，可 attempt 至今仍是 paused
（updated_at 停在暂停那一刻）——因为裸跑路径压根不碰 assistant_tasks/assistant_task_attempts。
汇总节点的 16 条 blocking 依赖里有一条指着它，GraphScheduler 的就绪判定要求前置
∈ completed_ids，于是整张图永久静止。

这里守的是两条：
1. 执行体背后挂着未终态 attempt 时，continue_subagent MUST NOT 裸跑，必须走带记账的
   正规续跑路径（task 因此离开 suspended）。
2. 主助理的追加指令 MUST 传达到续跑的执行体——正规续跑路径原本 user_input=None
   （不追发任务书），指令若被静默丢弃，主助理会以为自己已经纠偏。

反向：没有 attempt 的同步委派子代理保持原地同步续跑，不受影响。
"""

from unittest.mock import MagicMock, patch

import pytest

from src.business.agents.config import AgentType
from src.business.ai.llm_client import LLMResponse
from src.business.memory.context_manager import ContextManager
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from tests.conftest import MockLLMClient


@pytest.fixture
def orch(mock_config, in_memory_db):
    return AgentOrchestrator(MagicMock(), mock_config)


def _make_child_subagent(orch, parent_session_id, *, status="suspended"):
    """建一个归属 parent 的子代理会话（归属校验靠 delegation workflow_id）。"""
    workflow_id = orch._new_delegation_workflow_id(parent_session_id)
    child = orch._session_store.create_session(workflow_id, AgentType.EPHEMERAL_SUBAGENT)
    ContextManager(child, orch._config).update_session_status(status)
    return child


def _make_suspended_graph_node(
    child_session_id: str, *, lease_owner: str = "graph_scheduler"
) -> tuple[str, str]:
    """复现真机现场：task suspended/budget_exhausted + 其 attempt paused 且绑着 child。

    ``lease_owner`` 决定这是派发器建的任务节点（默认，真机那条就是 graph_scheduler）
    还是同步委派建的 attempt（``sync_delegation``）。

    返回 ``(task_id, graph_id)``。
    """
    from src.data.repos import AssistantTaskRepository
    from src.data.repos.assistant_task_attempt_repository import (
        AssistantTaskAttemptRepository,
    )
    from src.business.task_collaboration.service import TaskCollaborationService
    from src.utils.timezone import utc_now_naive

    # has_progress：续跑目标选取要求会话里有实际进展（任一 assistant 消息）。
    # 真机那个执行体跑满 50 轮，这里补一条等价的最小进展。
    from src.data.models_sqlite import Message
    from src.data.repos.message_repository import MessageRepository

    with MessageRepository() as messages:
        messages.create(
            Message(
                message_id=f"msg_test_{child_session_id[:8]}",
                session_id=child_session_id,
                sequence=1,
                role="assistant",
                content="已读完 skill_store，继续看 debug",
            )
        )

    graph_id = f"tg_test_{child_session_id[:8]}"
    with AssistantTaskRepository() as tasks:
        task_id = tasks.create_task(
            graph_id=graph_id,
            session_id="parent-graph-node",
            title="分析其余业务子模块",
            description="skill_store/debug/user_tasks/user_todos/tool_trial/utils",
            assignee_type="ephemeral_subagent",
            status="running",
            # 非空 capability_scope：续跑目标选取对空 scope 是 fail-closed（开新会话）
            capability_scope='{"builtin": []}',
        ).task_id
    with AssistantTaskAttemptRepository() as attempts:
        attempt = attempts.start_attempt(
            task_id=task_id,
            executor_type="ephemeral_subagent",
            executor_id=task_id,
            lease_owner=lease_owner,
            lease_expires_at=utc_now_naive(),
        )
        attempts.bind_session(task_id=task_id, executor_session_id=child_session_id)
        # 撞迭代上限 → attempt paused，checkpoint 存续跑会话 id
        attempts.pause_if_current(
            attempt_id=attempt.attempt_id,
            fence_token=attempt.fence_token,
            checkpoint_ref=f'{{"executor_session_id": "{child_session_id}"}}',
        )
    with TaskCollaborationService() as service:
        service.update_task_status(
            task_id=task_id,
            status="suspended",
            suspend_reason="budget_exhausted",
        )
    return task_id, graph_id


def test_continue_subagent_on_graph_node_leaves_suspended(orch, mock_config):
    """核心回归：续跑图节点的执行体后，任务必须离开 suspended。

    真机 bug：任务永远停在 suspended，下游 blocking 依赖永不满足。
    """
    from src.business.task_collaboration.service import TaskCollaborationService

    parent = "parent-graph-reentry"
    child = _make_child_subagent(orch, parent, status="suspended")
    task_id, _graph_id = _make_suspended_graph_node(child)

    # 记账（建 attempt + 翻状态）在提交线程池之前完成，这里只验证记账，
    # 不让 worker 真的起——in-memory DB 是 StaticPool 单连接，跨线程不可靠。
    dispatcher = orch._get_task_dispatcher()
    with patch.object(dispatcher, "_submit_worker", return_value=MagicMock()):
        res = orch._continue_subagent(
            parent_session_id=parent,
            subagent_id=child,
            instruction="直接产出最终报告，不要再搜索",
            extra_iterations=20,
        )

    assert res["success"] is True, res
    # 受理即返回，不阻塞等 child 跑完（任务图委派的既有硬约束）
    assert res.get("taskId") == task_id

    with TaskCollaborationService() as service:
        task = service.get_task(task_id)
    assert task.status != "suspended", (
        f"续跑后任务仍停在 suspended（真机 bug）：status={task.status} "
        f"suspend_reason={task.suspend_reason}"
    )


def test_continue_subagent_on_graph_node_carries_instruction(orch):
    """主助理的追加指令必须落进续跑句柄，不能静默丢弃。

    正规续跑路径 user_input=None（不追发任务书），指令若丢了，主助理会以为
    自己已经纠偏——真机那条指令正是让执行体停止调研、直接产出报告的关键。
    """
    from src.data.repos.assistant_task_attempt_repository import (
        AssistantTaskAttemptRepository,
    )

    parent = "parent-graph-instruction"
    child = _make_child_subagent(orch, parent, status="suspended")
    task_id, _graph_id = _make_suspended_graph_node(child)

    dispatcher = orch._get_task_dispatcher()
    with patch.object(dispatcher, "_submit_worker", return_value=MagicMock()):
        orch._continue_subagent(
            parent_session_id=parent,
            subagent_id=child,
            instruction="直接产出最终报告，不要再搜索",
            extra_iterations=20,
        )

    # 承载本轮续跑的是新建的 attempt（旧的那条仍停在 paused 作历史）。
    # 它此刻还没绑 executor_session_id——绑定发生在执行体真正启动时，
    # 所以按 task 取它当前在跑的 attempt。
    with AssistantTaskAttemptRepository() as attempts:
        resumed = attempts._active_attempt_for_task(task_id)
    assert resumed is not None, "续跑未建承载本轮的 attempt"
    assert "直接产出最终报告" in (resumed.checkpoint_ref or ""), (
        f"追加指令未进入续跑句柄：{resumed.checkpoint_ref}"
    )


def test_continue_subagent_sync_delegation_attempt_still_runs_inline(orch, mock_config):
    """反向保护：同步委派建的 attempt（sync_delegation）不得被转成异步受理。

    delegate_to_subagent 当场返回 paused 的那条路径上，主助理等的就是即时结果；
    它的 attempt 由 _finalize_sync_attempt 自己收尾，不归 dispatcher 管。
    """
    parent = "parent-sync-delegation"
    child = _make_child_subagent(orch, parent, status="suspended")
    _make_suspended_graph_node(child, lease_owner="sync_delegation")

    orch._llm_override = MockLLMClient([LLMResponse(content="续跑完成", tool_calls=[])])
    with (
        patch.object(orch, "_build_delegated_executor_tools", return_value=[]),
        patch.object(orch, "_resolve_user_tool_ids", return_value=set()),
    ):
        res = orch._continue_subagent(
            parent_session_id=parent, subagent_id=child, instruction="接着做"
        )

    assert res["success"] is True
    assert res["result_text"] == "续跑完成"
    assert res.get("taskId") is None, "同步委派被误转成异步受理"


def test_continue_subagent_without_attempt_still_runs_inline(orch, mock_config):
    """反向保护：纯同步委派的子代理（背后没有 attempt）保持原地同步续跑。"""
    parent = "parent-inline"
    child = _make_child_subagent(orch, parent, status="suspended")

    orch._llm_override = MockLLMClient([LLMResponse(content="续跑完成", tool_calls=[])])
    with (
        patch.object(orch, "_build_delegated_executor_tools", return_value=[]),
        patch.object(orch, "_resolve_user_tool_ids", return_value=set()),
    ):
        res = orch._continue_subagent(
            parent_session_id=parent, subagent_id=child, instruction="接着做"
        )

    assert res["success"] is True
    assert res["result_text"] == "续跑完成"
    assert res.get("taskId") is None
    assert ContextManager(child, mock_config).get_session_status() == "completed"
