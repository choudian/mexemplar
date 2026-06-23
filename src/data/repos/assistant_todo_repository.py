"""Repository for private task Todo checklist items."""

from __future__ import annotations

from src.data.models_sqlite import AssistantTodoItem
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository


class AssistantTodoRepository(BaseRepository):
    def list_for_task(self, task_id: str) -> list[AssistantTodoItem]:
        return (
            self.session.query(AssistantTodoItem)
            .filter(AssistantTodoItem.task_id == task_id)
            .order_by(AssistantTodoItem.sort_order, AssistantTodoItem.created_at)
            .all()
        )

    def list_for_executor(
        self,
        *,
        task_id: str,
        executor_type: str,
        executor_id: str,
    ) -> list[AssistantTodoItem]:
        return (
            self.session.query(AssistantTodoItem)
            .filter(
                AssistantTodoItem.task_id == task_id,
                AssistantTodoItem.executor_type == executor_type,
                AssistantTodoItem.executor_id == executor_id,
            )
            .order_by(AssistantTodoItem.sort_order, AssistantTodoItem.created_at)
            .all()
        )

    def replace_for_executor(
        self,
        *,
        task_id: str,
        executor_type: str,
        executor_id: str,
        items: list[dict],
    ) -> list[AssistantTodoItem]:
        """批量替换某 executor 的 todo（upsert + 删除不在列表中的旧项）。

        ``items`` 必须由调用方（service）预先归一化：每个 dict 含 ``todo_id`` / ``text``
        / ``status`` / ``sort_order``，且 status 已校验、sort_order 已是 int。Repository
        不再做 DTO 解析或业务校验，只负责持久化与 ``completed_at``（done 终态时间戳）维护。
        """
        self.ensure_immediate_transaction()
        existing = {
            item.todo_id: item
            for item in self.session.query(AssistantTodoItem)
            .filter(
                AssistantTodoItem.task_id == task_id,
                AssistantTodoItem.executor_type == executor_type,
                AssistantTodoItem.executor_id == executor_id,
            )
            .all()
        }
        keep_ids: set[str] = set()
        now = utc_now_naive()
        for item in items:
            todo_id = item["todo_id"]
            keep_ids.add(todo_id)
            status = item["status"]
            sort_order = item["sort_order"]
            text = item["text"]
            row = existing.get(todo_id)
            if row is None:
                row = AssistantTodoItem(
                    todo_id=todo_id,
                    task_id=task_id,
                    executor_type=executor_type,
                    executor_id=executor_id,
                    text=text,
                    status=status,
                    sort_order=sort_order,
                )
                self.session.add(row)
            else:
                row.text = text
                row.status = status
                row.sort_order = sort_order
                row.updated_at = now
            row.completed_at = now if status == "done" else None
        for todo_id, row in existing.items():
            if todo_id not in keep_ids:
                self.session.delete(row)
        self._commit()
        return self.list_for_task(task_id)
