"""Repository for TaskAttempt side-effect idempotency records."""

from __future__ import annotations

from src.data.models_sqlite import AssistantTaskOperation
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id


class AssistantTaskOperationRepository(BaseRepository):
    def record_planned(
        self,
        *,
        task_id: str,
        attempt_id: str,
        operation_key: str,
        operation_type: str,
        safe_summary: str,
        idempotency_scope: str = "unknown",
        operation_id: str | None = None,
    ) -> AssistantTaskOperation:
        self.ensure_immediate_transaction()
        row = AssistantTaskOperation(
            operation_id=operation_id or generate_id("op"),
            task_id=task_id,
            attempt_id=attempt_id,
            operation_key=operation_key,
            operation_type=operation_type,
            idempotency_scope=idempotency_scope,
            status="planned",
            safe_summary=safe_summary,
        )
        return self._add_and_flush(row)

    def get_by_key(self, task_id: str, operation_key: str) -> AssistantTaskOperation | None:
        return (
            self.session.query(AssistantTaskOperation)
            .filter(
                AssistantTaskOperation.task_id == task_id,
                AssistantTaskOperation.operation_key == operation_key,
                AssistantTaskOperation.status != "failed",
            )
            .first()
        )

    def update_status(
        self,
        operation_id: str,
        status: str,
        *,
        result_ref: str | None = None,
    ) -> AssistantTaskOperation | None:
        self.ensure_immediate_transaction()
        row = self.session.get(AssistantTaskOperation, operation_id)
        if row is None:
            return None
        row.status = status
        if result_ref is not None:
            row.result_ref = result_ref
        row.updated_at = utc_now_naive()
        if status == "completed":
            row.completed_at = row.updated_at
        return self._update_and_flush(row)

    def scan_in_progress(self) -> list[AssistantTaskOperation]:
        """断电恢复：所有 ``in_progress`` 副作用记录。

        ``run_side_effect`` 是同步的——在 attempt worker 线程里执行，``in_progress`` 表示
        ``execute()`` 正在跑。断电只可能发生在执行期间，那时 operation 卡在 in_progress。
        它所属的 attempt 已被断电扫描标 fenced（终态），这个 in_progress 没人会来完成。
        不清的后果：in_progress 行撑着 ``uq_assistant_task_operations_non_failed_key``
        partial unique index（排除 failed），挡住同 operation_key 的重入重试。
        """
        return (
            self.session.query(AssistantTaskOperation)
            .filter(AssistantTaskOperation.status == "in_progress")
            .order_by(AssistantTaskOperation.created_at)
            .all()
        )
