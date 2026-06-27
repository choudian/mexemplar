"""Business service for user-level personal Todo items."""

from __future__ import annotations

from typing import Any

from src.data.models_sqlite import UserTodo
from src.data.repos import UserTodoRepository

TODO_STATUSES = {"pending", "in_progress", "done"}
TODO_PRIORITIES = {"low", "medium", "high", "urgent"}
STATUS_FILTERS = {"all", "open", "done", "pending", "in_progress"}
SORT_ORDERS = {"created_desc", "created_asc", "priority_desc", "priority_asc"}
TITLE_LIMIT = 200
DESCRIPTION_LIMIT = 2000
QUERY_LIMIT = 200


class UserTodoService:
    def __init__(self, repo: UserTodoRepository | None = None) -> None:
        self._repo = repo or UserTodoRepository()
        self._owns_repo = repo is None

    def close(self) -> None:
        if self._owns_repo:
            self._repo.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def create(
        self,
        *,
        title: str,
        description: str | None = "",
        priority: str = "medium",
    ) -> dict[str, Any]:
        row = self._repo.create(
            title=_normalize_title(title),
            description=_normalize_description(description),
            priority=_normalize_priority(priority),
        )
        return project_user_todo(row)

    def list_todos(
        self,
        *,
        status_filter: str = "all",
        sort: str = "created_desc",
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        normalized_limit = max(1, min(int(limit), 500))
        normalized_offset = max(0, int(offset))
        rows, total = self._repo.list_todos(
            status_filter=_normalize_status_filter(status_filter),
            sort=_normalize_sort(sort),
            query_text=_normalize_query(query),
            limit=normalized_limit,
            offset=normalized_offset,
        )
        return [project_user_todo(row) for row in rows], total

    def update(self, todo_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        if "title" in updates:
            normalized["title"] = _normalize_title(updates["title"])
        if "description" in updates:
            normalized["description"] = _normalize_description(updates["description"])
        if "priority" in updates:
            normalized["priority"] = _normalize_priority(updates["priority"])
        if "status" in updates:
            normalized["status"] = _normalize_status(updates["status"])
        if not normalized:
            row = self._repo.get(_normalize_id(todo_id))
        else:
            row = self._repo.update(_normalize_id(todo_id), normalized)
        if row is None:
            raise LookupError("todo not found")
        return project_user_todo(row)

    def complete(self, todo_id: str, *, done: bool = True) -> dict[str, Any]:
        return self.update(todo_id, {"status": "done" if done else "pending"})

    def delete(self, todo_id: str) -> None:
        if not self._repo.delete(_normalize_id(todo_id)):
            raise LookupError("todo not found")


def project_user_todo(row: UserTodo) -> dict[str, Any]:
    return {
        "todoId": row.todo_id,
        "title": row.title,
        "description": row.description or "",
        "status": row.status,
        "priority": row.priority,
        "sortOrder": row.sort_order,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
        "completedAt": row.completed_at,
    }


def _normalize_id(value: str) -> str:
    todo_id = str(value or "").strip()
    if not todo_id:
        raise ValueError("todo_id is required")
    return todo_id


def _normalize_title(value: Any) -> str:
    title = str(value or "").strip()
    if not title:
        raise ValueError("title is required")
    return title[:TITLE_LIMIT]


def _normalize_description(value: Any) -> str:
    description = str(value or "").strip()
    return description[:DESCRIPTION_LIMIT]


def _normalize_priority(value: Any) -> str:
    priority = str(value or "medium").strip().lower()
    if priority not in TODO_PRIORITIES:
        raise ValueError("priority must be low, medium, high, or urgent")
    return priority


def _normalize_status(value: Any) -> str:
    status = str(value or "pending").strip().lower()
    if status not in TODO_STATUSES:
        raise ValueError("status must be pending, in_progress, or done")
    return status


def _normalize_status_filter(value: Any) -> str:
    status_filter = str(value or "all").strip().lower()
    if status_filter not in STATUS_FILTERS:
        raise ValueError("status filter must be all, open, done, pending, or in_progress")
    return status_filter


def _normalize_sort(value: Any) -> str:
    sort = str(value or "created_desc").strip().lower()
    if sort not in SORT_ORDERS:
        raise ValueError("sort must be created_desc, created_asc, priority_desc, or priority_asc")
    return sort


def _normalize_query(value: Any) -> str:
    return str(value or "").strip()[:QUERY_LIMIT]
