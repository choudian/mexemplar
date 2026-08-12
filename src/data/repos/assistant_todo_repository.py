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
        creator_session_id: str | None = None,
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
                    # 只在新增时写：续跑后换会话接手，更新不该冲掉创建来源
                    creator_session_id=creator_session_id,
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

    def append_for_executor(
        self,
        *,
        task_id: str,
        executor_type: str,
        executor_id: str,
        items: list[dict],
        creator_session_id: str | None = None,
    ) -> list[AssistantTodoItem]:
        """追加新条目，不动已有的。

        与 ``replace_for_executor`` 的区别：不删除未提及的条目。执行体列清单是
        「加几件事」，不是「宣布现在只剩这几件」——用替换语义时它漏带一条就等于
        删除，而漏带和有意删除在数据上无法区分。

        ``items`` 已由 service 归一化（含 ``todo_id`` / ``text`` / ``status`` /
        ``sort_order``），此处只负责持久化。
        """
        self.ensure_immediate_transaction()
        now = utc_now_naive()
        for item in items:
            self.session.add(
                AssistantTodoItem(
                    todo_id=item["todo_id"],
                    task_id=task_id,
                    executor_type=executor_type,
                    executor_id=executor_id,
                    creator_session_id=creator_session_id,
                    text=item["text"],
                    status=item["status"],
                    sort_order=item["sort_order"],
                    completed_at=now if item["status"] == "done" else None,
                )
            )
        self._commit()
        return self.list_for_task(task_id)

    def update_one(
        self,
        *,
        todo_id: str,
        task_id: str,
        executor_type: str,
        executor_id: str,
        fields: dict,
    ) -> AssistantTodoItem | None:
        """按 id 改一条的字段。找不到返回 None（由 service 转成明确错误）。

        ``fields`` 只含调用方显式给出的键（``text`` / ``status`` / ``sort_order``），
        缺省的字段保持原值——这正是「按 id 更新其它字段」的语义。
        """
        self.ensure_immediate_transaction()
        row = (
            self.session.query(AssistantTodoItem)
            .filter(
                AssistantTodoItem.todo_id == todo_id,
                AssistantTodoItem.task_id == task_id,
                AssistantTodoItem.executor_type == executor_type,
                AssistantTodoItem.executor_id == executor_id,
            )
            .one_or_none()
        )
        if row is None:
            return None
        if "text" in fields:
            row.text = fields["text"]
        if "sort_order" in fields:
            row.sort_order = fields["sort_order"]
        if "status" in fields:
            row.status = fields["status"]
            row.completed_at = utc_now_naive() if fields["status"] == "done" else None
        row.updated_at = utc_now_naive()
        self._commit()
        return row
