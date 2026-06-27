"""Repository for user-level personal Todo items."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, or_

from src.data.models_sqlite import UserTodo
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id


class UserTodoRepository(BaseRepository):
    def create(
        self,
        *,
        title: str,
        description: str | None,
        priority: str,
        sort_order: int = 0,
    ) -> UserTodo:
        now = utc_now_naive()
        row = UserTodo(
            todo_id=generate_id("utodo"),
            title=title,
            description=description,
            status="pending",
            priority=priority,
            sort_order=sort_order,
            created_at=now,
            updated_at=now,
        )
        return self._add_and_flush(row)

    def get(self, todo_id: str) -> UserTodo | None:
        return self.session.get(UserTodo, todo_id)

    def list_todos(
        self,
        *,
        status_filter: str = "all",
        sort: str = "created_desc",
        query_text: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[UserTodo], int]:
        query = self.session.query(UserTodo)
        if status_filter == "open":
            query = query.filter(UserTodo.status.in_(("pending", "in_progress")))
        elif status_filter != "all":
            query = query.filter(UserTodo.status == status_filter)
        search = query_text.strip()
        if search:
            pattern = f"%{search}%"
            query = query.filter(
                or_(UserTodo.title.ilike(pattern), UserTodo.description.ilike(pattern))
            )
        total = query.count()
        query = self._apply_sort(query, sort)
        items = query.offset(offset).limit(limit).all()
        return items, total

    def update(self, todo_id: str, updates: dict[str, Any]) -> UserTodo | None:
        row = self.get(todo_id)
        if row is None:
            return None
        now = utc_now_naive()
        if "title" in updates:
            row.title = updates["title"]
        if "description" in updates:
            row.description = updates["description"]
        if "priority" in updates:
            row.priority = updates["priority"]
        if "status" in updates:
            next_status = updates["status"]
            row.status = next_status
            if next_status == "done":
                row.completed_at = row.completed_at or now
            else:
                row.completed_at = None
        row.updated_at = now
        return self._update_and_flush(row)

    def delete(self, todo_id: str) -> bool:
        row = self.get(todo_id)
        if row is None:
            return False
        self.session.delete(row)
        self._commit()
        return True

    @staticmethod
    def _apply_sort(query, sort: str):
        priority_rank = case(
            (UserTodo.priority == "urgent", 4),
            (UserTodo.priority == "high", 3),
            (UserTodo.priority == "medium", 2),
            (UserTodo.priority == "low", 1),
            else_=0,
        )
        if sort == "created_asc":
            return query.order_by(UserTodo.created_at.asc(), UserTodo.todo_id.asc())
        if sort == "priority_asc":
            return query.order_by(priority_rank.asc(), UserTodo.created_at.desc())
        if sort == "priority_desc":
            return query.order_by(priority_rank.desc(), UserTodo.created_at.desc())
        return query.order_by(UserTodo.created_at.desc(), UserTodo.todo_id.desc())
