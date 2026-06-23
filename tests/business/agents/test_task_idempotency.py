from __future__ import annotations

from datetime import datetime, timedelta

from src.business.task_collaboration.dispatcher import TaskDispatcher
from src.data.repos import (
    AssistantTaskAttemptRepository,
    AssistantTaskOperationRepository,
    AssistantTaskRepository,
)


class _Config:
    def get_assistant_tasks_dispatch_max_workers(self) -> int:
        return 2

    def get_assistant_tasks_attempt_lease_seconds(self) -> int:
        return 60


def test_operation_record_marks_side_effect_completed_before_safe_resume() -> None:
    AssistantTaskRepository().create_task(
        graph_id="tg_ops",
        session_id="ast_ops",
        task_id="tsk_ops",
        title="task",
        description="task",
    )
    attempt = AssistantTaskAttemptRepository().start_attempt(
        task_id="tsk_ops",
        executor_type="ephemeral_subagent",
        executor_id="sub_1",
        lease_owner="worker_1",
        lease_expires_at=datetime.now() + timedelta(minutes=5),
        attempt_id="att_ops",
    )
    assert attempt is not None

    repo = AssistantTaskOperationRepository()
    operation = repo.record_planned(
        task_id="tsk_ops",
        attempt_id="att_ops",
        operation_key="write:report",
        operation_type="file_write",
        safe_summary="写入报告",
        idempotency_scope="task",
    )
    repo.update_status(operation.operation_id, "completed", result_ref="ref_report")

    stored = repo.get_by_key("tsk_ops", "write:report")
    assert stored is not None
    assert stored.status == "completed"
    assert stored.result_ref == "ref_report"


def test_dispatcher_records_side_effect_before_and_after_success(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.dispatcher.get_unified_config",
        lambda: _Config(),
    )
    AssistantTaskRepository().create_task(
        graph_id="tg_dispatch_ops",
        session_id="ast_dispatch_ops",
        task_id="tsk_dispatch_ops",
        title="task",
        description="task",
    )
    attempt = AssistantTaskAttemptRepository().start_attempt(
        task_id="tsk_dispatch_ops",
        executor_type="ephemeral_subagent",
        executor_id="sub_1",
        lease_owner="worker_1",
        lease_expires_at=datetime.now() + timedelta(minutes=5),
        attempt_id="att_dispatch_ops",
    )
    assert attempt is not None

    seen_statuses: list[str] = []

    def execute() -> str:
        current = AssistantTaskOperationRepository().get_by_key(
            "tsk_dispatch_ops",
            "send:mail",
        )
        seen_statuses.append(current.status if current is not None else "missing")
        return "sent"

    result = TaskDispatcher().run_side_effect(
        task_id="tsk_dispatch_ops",
        attempt_id="att_dispatch_ops",
        operation_key="send:mail",
        operation_type="email",
        safe_summary="发送邮件",
        execute=execute,
        idempotency_scope="task",
    )

    stored = AssistantTaskOperationRepository().get_by_key("tsk_dispatch_ops", "send:mail")
    assert result == "sent"
    assert seen_statuses == ["in_progress"]
    assert stored is not None
    assert stored.status == "completed"
    assert stored.result_ref == "sent"
