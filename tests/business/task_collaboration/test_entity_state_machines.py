from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos import (
    AssistantTaskAttemptRepository,
    AssistantTaskOperationRepository,
    AssistantTaskRepository,
)


def _task(task_id: str) -> str:
    AssistantTaskRepository().create_task(
        graph_id="tg_sm",
        session_id="ast_sm",
        task_id=task_id,
        title="task",
        description="task",
        owner_session_id="ast_sm",
        status="running",
    )
    return task_id


def _lease(seconds: int = 60) -> datetime:
    return datetime.now() + timedelta(seconds=seconds)


def _start(task_id: str):
    return AssistantTaskAttemptRepository().start_attempt(
        task_id=task_id,
        executor_type="ephemeral_subagent",
        executor_id="exec",
        lease_owner="worker",
        lease_expires_at=_lease(),
    )


def test_attempt_capacity_is_one_active_per_task() -> None:
    _task("tsk_cap")
    first = _start("tsk_cap")
    second = _start("tsk_cap")
    assert first is not None
    assert second is None  # 同一任务同时只允许一个活跃 attempt


@pytest.mark.parametrize("terminal", ["succeeded", "failed"])
def test_attempt_terminal_transition_frees_capacity(terminal: str) -> None:
    task_id = _task(f"tsk_term_{terminal}")
    repo = AssistantTaskAttemptRepository()
    attempt = _start(task_id)
    if terminal == "succeeded":
        done = repo.complete_if_current(
            attempt_id=attempt.attempt_id, fence_token=attempt.fence_token, result_ref="r"
        )
    else:
        done = repo.fail_if_current(
            attempt_id=attempt.attempt_id, fence_token=attempt.fence_token, error_category="internal"
        )
    assert done.status == terminal
    # 终态后容量释放：可再起新 attempt
    assert _start(task_id) is not None


def test_fenced_attempt_rejects_complete_and_fail() -> None:
    task_id = _task("tsk_fenced")
    repo = AssistantTaskAttemptRepository()
    attempt = _start(task_id)
    stale_token = attempt.fence_token
    repo.fence(attempt.attempt_id)

    assert (
        repo.complete_if_current(
            attempt_id=attempt.attempt_id, fence_token=stale_token, result_ref="r"
        )
        is None
    )
    assert (
        repo.fail_if_current(
            attempt_id=attempt.attempt_id, fence_token=stale_token, error_category="x"
        )
        is None
    )


def test_operation_lifecycle_planned_in_progress_completed() -> None:
    _task("tsk_op")
    repo = AssistantTaskOperationRepository()
    op = repo.record_planned(
        task_id="tsk_op",
        attempt_id="att_op",
        operation_key="k1",
        operation_type="t",
        safe_summary="s",
    )
    assert op.status == "planned"
    assert repo.update_status(op.operation_id, "in_progress").status == "in_progress"
    assert repo.update_status(op.operation_id, "completed", result_ref="r").status == "completed"


def test_operation_failed_status_is_excluded_from_idempotency_lookup() -> None:
    _task("tsk_op_fail")
    repo = AssistantTaskOperationRepository()
    op = repo.record_planned(
        task_id="tsk_op_fail",
        attempt_id="att_op_fail",
        operation_key="kf",
        operation_type="t",
        safe_summary="s",
    )
    repo.update_status(op.operation_id, "failed")
    # failed operation 不再阻塞同 key 重试：get_by_key 过滤 failed
    assert repo.get_by_key("tsk_op_fail", "kf") is None


def test_adjudication_single_pending_per_task() -> None:
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(session_id="ast_adj", title="root", description="root")
    root = AssistantTaskRepository().list_graph_tasks(graph_id)[0]

    first = service.create_parent_adjudication(
        task_id=root.task_id, delivered_status="stuck", safe_summary="s1"
    )
    second = service.create_parent_adjudication(
        task_id=root.task_id, delivered_status="done", safe_summary="s2"
    )

    # 单任务同时只能有一个 pending 裁定：第二次返回既有那条
    assert first.adjudication_id == second.adjudication_id


def test_suspend_reason_rejected_for_non_suspended_transition() -> None:
    """suspend_reason 只允许在转 suspended 时提供；转其他状态时必须为 None。"""
    from src.business.task_collaboration.models import validate_task_transition, TaskStatus

    with pytest.raises(ValueError, match="suspend_reason is only valid"):
        validate_task_transition(
            TaskStatus.PENDING_DISPATCH,
            TaskStatus.RUNNING,
            suspend_reason="waiting_system",
        )


def test_suspend_requires_reason() -> None:
    """转 suspended 时必须提供 suspend_reason。"""
    from src.business.task_collaboration.models import validate_task_transition, TaskStatus

    with pytest.raises(ValueError, match="suspend_reason"):
        validate_task_transition(
            TaskStatus.RUNNING,
            TaskStatus.SUSPENDED,
        )
