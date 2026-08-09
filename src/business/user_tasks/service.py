"""Business service for user-level Tasks («用户交办的一件事»).

用户任务层的身份/数据层服务。状态只回答"这件事还办不办"，
与执行层（``assistant_tasks``）分开存储。
"""

from __future__ import annotations

from typing import Any

from src.data.models_sqlite import UserTask
from src.data.repos import UserTaskRepository

USER_TASK_STATUSES = {"active", "cooling", "done", "dropped"}
TITLE_LIMIT = 200
DESCRIPTION_LIMIT = 4000


class UserTaskService:
    def __init__(self, repo: UserTaskRepository | None = None) -> None:
        self._repo = repo or UserTaskRepository()
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
        session_id: str,
        title: str,
        description: str | None = "",
    ) -> dict[str, Any]:
        row = self._repo.create(
            session_id=_normalize_session_id(session_id),
            title=_normalize_title(title),
            description=_normalize_description(description),
        )
        return project_user_task(row)

    def get(self, task_id: str) -> dict[str, Any] | None:
        row = self._repo.get(_normalize_id(task_id))
        return project_user_task(row) if row else None

    def list_for_session(
        self,
        *,
        session_id: str,
        status_filter: str = "all",
    ) -> list[dict[str, Any]]:
        rows = self._repo.list_for_session(
            _normalize_session_id(session_id), status_filter=status_filter
        )
        return [project_user_task(row) for row in rows]

    def update_status(self, task_id: str, status: str) -> dict[str, Any]:
        normalized_id = _normalize_id(task_id)
        normalized_status = _normalize_status(status)
        row = self._repo.update_status(normalized_id, normalized_status)
        if row is None:
            raise LookupError(f"user task not found: {normalized_id}")
        return project_user_task(row)

    def update(
        self,
        task_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """更新任务的 title 和/或 description。任务建得早、title 可以含糊，
        澄清需求后调此方法改成准确描述。"""
        normalized_id = _normalize_id(task_id)
        normalized_title = _normalize_title(title) if title is not None else None
        normalized_desc = _normalize_description(description) if description is not None else None
        row = self._repo.update(
            normalized_id,
            title=normalized_title,
            description=normalized_desc,
        )
        if row is None:
            raise LookupError(f"user task not found: {normalized_id}")
        return project_user_task(row)

    def status_distribution(self, task_id: str) -> dict[str, int]:
        """返回用户任务下所有执行节点的状态分布（供界面画分布条）。

        聚合由 ``AssistantTaskRepository.status_distribution_for_user_task`` 完成，
        本方法只做 Service 层入口 + 传参——路由层调这里，不直连 Repository。
        """
        from src.data.repos import AssistantTaskRepository

        with AssistantTaskRepository() as tasks:
            return tasks.status_distribution_for_user_task(task_id)


def project_user_task(row: UserTask) -> dict[str, Any]:
    return {
        "taskId": row.task_id,
        "sessionId": row.session_id,
        "title": row.title,
        "description": row.description or "",
        "status": row.status,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
        "completedAt": row.completed_at,
    }


def _normalize_id(value: str) -> str:
    task_id = str(value or "").strip()
    if not task_id:
        raise ValueError("task_id is required")
    return task_id


def _normalize_session_id(value: str) -> str:
    session_id = str(value or "").strip()
    if not session_id:
        raise ValueError("session_id is required")
    return session_id


def _normalize_title(value: Any) -> str:
    title = str(value or "").strip()
    if not title:
        raise ValueError("title is required")
    if len(title) > TITLE_LIMIT:
        raise ValueError(f"title exceeds {TITLE_LIMIT} characters")
    return title


def _normalize_description(value: Any) -> str:
    description = str(value or "").strip()
    if len(description) > DESCRIPTION_LIMIT:
        raise ValueError(f"description exceeds {DESCRIPTION_LIMIT} characters")
    return description


def _normalize_status(value: str) -> str:
    status = str(value or "").strip()
    if status not in USER_TASK_STATUSES:
        raise ValueError(f"invalid status: {status}")
    return status
