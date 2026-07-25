"""执行体启动时把自己的会话绑定到当前 active attempt。

派活先于执行体创建，``executor_id`` 对临时子代理只能填任务 id 顶替，于是"此刻谁在
干这活"在库里不存在。绑定发生在 agent loop 启动前——必须早于执行体的第一次工具调用，
否则 ``ask_parent`` / ``todo_update`` 的归属校验仍然查无此人。
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.business.agents.config import AgentResult, ResultType
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from src.data.repos import AssistantTaskAttemptRepository, AssistantTaskRepository
from src.utils.timezone import utc_now_naive


@pytest.fixture
def orch(mock_config, in_memory_db):
    return AgentOrchestrator(MagicMock(), mock_config)


def _patch_loop(orch):
    """返回 (patches, loop_class_mock)，调用方可在 loop_class_mock 上挂 side_effect。"""
    patches = [
        patch("src.business.orchestration.agent.orchestrator.AgentLoop"),
        patch.object(orch, "_build_delegated_executor_tools", return_value=[]),
        patch.object(orch, "_resolve_user_tool_ids", return_value=set()),
    ]
    started = [p.start() for p in patches]
    loop_cls = started[0]
    loop_cls.return_value.run.return_value = AgentResult(result_type=ResultType.COMPLETED)
    return patches, loop_cls


def _task_with_active_attempt(task_id: str = "tsk_wire") -> str:
    AssistantTaskRepository().create_task(
        graph_id="tg_wire",
        session_id="ast_wire",
        task_id=task_id,
        title="wire",
        description="wire",
        owner_session_id="ast_wire",
        status="running",
    )
    AssistantTaskAttemptRepository().start_attempt(
        task_id=task_id,
        executor_type="ephemeral_subagent",
        executor_id=task_id,
        lease_owner="graph_scheduler",
        lease_expires_at=utc_now_naive() + timedelta(minutes=2),
    )
    return task_id


def test_ephemeral_executor_binds_its_session_to_the_active_attempt(orch) -> None:
    task_id = _task_with_active_attempt()
    patches, _ = _patch_loop(orch)
    try:
        result = orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
            parent_session_id="ast_wire",
            task="做点事",
            current_task_id=task_id,
        )
    finally:
        for p in patches:
            p.stop()

    bound = AssistantTaskAttemptRepository().active_attempt_session(task_id)
    assert bound is not None
    assert bound == result["executor_session_id"]


def test_binding_happens_before_the_agent_loop_starts(orch) -> None:
    """绑定必须早于第一次工具调用，否则执行体一开口就被守卫拒掉。"""
    task_id = _task_with_active_attempt("tsk_wire_order")
    seen: dict[str, str | None] = {}

    patches, loop_cls = _patch_loop(orch)

    def _capture_binding_at_loop_start(*_args, **_kwargs):
        seen["at_loop_start"] = AssistantTaskAttemptRepository().active_attempt_session(task_id)
        return AgentResult(result_type=ResultType.COMPLETED)

    loop_cls.return_value.run.side_effect = _capture_binding_at_loop_start
    try:
        orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
            parent_session_id="ast_wire",
            task="做点事",
            current_task_id=task_id,
        )
    finally:
        for p in patches:
            p.stop()

    assert seen["at_loop_start"] is not None


def test_sync_delegation_without_task_does_not_touch_attempts(orch) -> None:
    """普通同步委派没有 task，绑定必须整体跳过，不能误伤别的任务。"""
    task_id = _task_with_active_attempt("tsk_untouched")
    patches, _ = _patch_loop(orch)
    try:
        orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
            parent_session_id="ast_wire",
            task="随手一件小事",
        )
    finally:
        for p in patches:
            p.stop()

    assert AssistantTaskAttemptRepository().active_attempt_session(task_id) is None
