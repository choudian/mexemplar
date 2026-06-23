from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from src.business.task_collaboration.dispatcher import TaskDispatcher
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos import (
    AssistantTaskAdjudicationRepository,
    AssistantTaskAttemptRepository,
    AssistantTaskOperationRepository,
    AssistantTaskRepository,
)


def test_duplicate_non_failed_operation_key_is_rejected() -> None:
    AssistantTaskRepository().create_task(
        graph_id="tg_dup",
        session_id="ast_dup",
        task_id="tsk_dup",
        title="task",
        description="task",
    )
    repo = AssistantTaskOperationRepository()
    repo.record_planned(
        task_id="tsk_dup",
        attempt_id="att_dup",
        operation_key="send:email",
        operation_type="email",
        safe_summary="发送邮件",
    )

    with pytest.raises(IntegrityError):
        repo.record_planned(
            task_id="tsk_dup",
            attempt_id="att_dup_2",
            operation_key="send:email",
            operation_type="email",
            safe_summary="重复发送邮件",
        )
    repo.session.rollback()


def test_side_effect_failure_marks_operation_failed_and_unblocks_retry(monkeypatch) -> None:
    class _Config:
        def get_assistant_tasks_dispatch_max_workers(self) -> int:
            return 2

        def get_assistant_tasks_attempt_lease_seconds(self) -> int:
            return 60

    monkeypatch.setattr(
        "src.business.task_collaboration.dispatcher.get_unified_config",
        lambda: _Config(),
    )
    AssistantTaskRepository().create_task(
        graph_id="tg_se_fail",
        session_id="ast_se_fail",
        task_id="tsk_se_fail",
        title="task",
        description="task",
    )
    dispatcher = TaskDispatcher()

    def boom() -> str:
        raise RuntimeError("side effect blew up")

    with pytest.raises(RuntimeError):
        dispatcher.run_side_effect(
            task_id="tsk_se_fail",
            attempt_id="att_se_fail",
            operation_key="charge:card",
            operation_type="payment",
            safe_summary="扣款",
            execute=boom,
        )

    # 失败的 operation 标 failed，被 get_by_key/唯一索引排除，不再永久卡在 in_progress
    assert (
        AssistantTaskOperationRepository().get_by_key("tsk_se_fail", "charge:card") is None
    )

    # 同 operation_key 可重新登记并完成（修复前会撞唯一约束 IntegrityError、无法重试）
    retry = dispatcher.run_side_effect(
        task_id="tsk_se_fail",
        attempt_id="att_se_fail",
        operation_key="charge:card",
        operation_type="payment",
        safe_summary="扣款",
        execute=lambda: "charged",
    )
    assert retry == "charged"
    stored = AssistantTaskOperationRepository().get_by_key("tsk_se_fail", "charge:card")
    assert stored is not None
    assert stored.status == "completed"


def test_unsafe_retry_creates_adjudication_instead_of_auto_replay() -> None:
    AssistantTaskRepository().create_task(
        graph_id="tg_unsafe",
        session_id="ast_unsafe",
        task_id="tsk_unsafe",
        title="task",
        description="task",
    )

    adjudication = TaskCollaborationService().create_parent_adjudication(
        task_id="tsk_unsafe",
        delivered_status="stuck",
        safe_summary="存在未知副作用，不能自动重试。",
    )

    assert adjudication is not None
    assert AssistantTaskAdjudicationRepository().get_pending_for_task("tsk_unsafe") is not None


def test_stale_fenced_success_is_rejected_without_success_event(monkeypatch) -> None:
    class _Config:
        def get_assistant_tasks_dispatch_max_workers(self) -> int:
            return 2

        def get_assistant_tasks_attempt_lease_seconds(self) -> int:
            return 60

    monkeypatch.setattr(
        "src.business.task_collaboration.dispatcher.get_unified_config",
        lambda: _Config(),
    )
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(session_id="ast_stale", title="root", description="root")
    root = AssistantTaskRepository().list_graph_tasks(graph_id)[0]
    child_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_stale",
        parent_task_id=root.task_id,
        title="child",
        description="child",
    )
    attempt_repo = AssistantTaskAttemptRepository()
    attempt = attempt_repo.start_attempt(
        task_id=child_id,
        executor_type="ephemeral_subagent",
        executor_id="sub_1",
        lease_owner="worker_1",
        lease_expires_at=datetime.now() + timedelta(minutes=5),
    )
    assert attempt is not None
    stale_token = attempt.fence_token
    attempt_repo.fence(attempt.attempt_id)

    result = TaskDispatcher()._record_attempt_outcome(
        attempt_id=attempt.attempt_id,
        fence_token=stale_token,
        delivered_status="done",
        safe_summary="任务已回传结果，等待上级检查。",
        result_ref="too late",
    )

    assert result["lateResult"] is True
    assert AssistantTaskAdjudicationRepository().get_pending_for_task(child_id) is None
