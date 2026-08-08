"""Repository for user-level Tasks («用户交办的一件事»).

与 ``assistant_tasks``（执行层）分开存储。状态只回答"这件事还办不办"，
不传染执行层的停顿/卡住。
"""

from __future__ import annotations

from src.data.models_sqlite import UserTask
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id


class UserTaskRepository(BaseRepository):
    def create(
        self,
        *,
        session_id: str,
        title: str,
        description: str | None = None,
    ) -> UserTask:
        now = utc_now_naive()
        row = UserTask(
            task_id=generate_id("utsk"),
            session_id=session_id,
            title=title,
            description=description,
            status="active",
            created_at=now,
            updated_at=now,
        )
        return self._add_and_flush(row)

    def get(self, task_id: str) -> UserTask | None:
        return self.session.get(UserTask, task_id)

    def list_for_session(
        self,
        session_id: str,
        *,
        status_filter: str = "all",
    ) -> list[UserTask]:
        query = self.session.query(UserTask).filter(UserTask.session_id == session_id)
        if status_filter == "open":
            query = query.filter(UserTask.status.in_(("active", "cooling")))
        elif status_filter != "all":
            query = query.filter(UserTask.status == status_filter)
        return query.order_by(UserTask.created_at.desc()).all()

    def update_status(self, task_id: str, status: str) -> UserTask | None:
        row = self.get(task_id)
        if row is None:
            return None
        now = utc_now_naive()
        row.status = status
        if status == "done":
            row.completed_at = row.completed_at or now
        elif status in ("active", "cooling"):
            # 从终态回退时清掉终态时间戳
            row.completed_at = None
        row.updated_at = now
        return self._update_and_flush(row)

    def update(
        self,
        task_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> UserTask | None:
        """更新任务的 title 和/或 description。只更新非 None 字段。"""
        row = self.get(task_id)
        if row is None:
            return None
        if title is not None:
            row.title = title
        if description is not None:
            row.description = description
        row.updated_at = utc_now_naive()
        return self._update_and_flush(row)
