"""Bridge root task graph failures to Assistant run failure cards."""

from __future__ import annotations

from src.business.task_collaboration.events import emit_root_failed
from src.business.task_collaboration.models import TaskStatus
from src.business.services.assistant_failure_service import AssistantFailureService
from src.data.repos import AssistantTaskRepository


class TaskFailureBridge:
    def __init__(
        self,
        task_repo: AssistantTaskRepository | None = None,
        failure_service: AssistantFailureService | None = None,
    ) -> None:
        self._tasks = task_repo or AssistantTaskRepository()
        self._failure_service = failure_service or AssistantFailureService()

    def bridge_root_failure(self, *, task_id: str, safe_summary: str) -> object | None:
        task = self._tasks.get_task(task_id)
        if task is None or task.parent_task_id is not None or task.status != TaskStatus.FAILED:
            return None
        if task.user_message_sequence is None:
            return None
        summary = self._failure_service.record_task_root_failure(
            session_id=task.session_id,
            message_sequence=task.user_message_sequence,
            safe_summary=safe_summary,
        )
        emit_root_failed(
            self,
            session_id=task.session_id,
            graph_id=task.graph_id,
            task_id=task.task_id,
            status=task.status,
            safe_explanation=summary.message,
        )
        return summary
