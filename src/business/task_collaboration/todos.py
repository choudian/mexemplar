"""Business service for executor-private task Todo checklists."""

from __future__ import annotations

import threading

from src.business.task_collaboration.models import TodoStatus, safe_public_preview
from src.business.task_collaboration.service import emit_todo_changed
from src.business.task_collaboration.unit_of_work import AtomicTaskService
from src.data.repos import AssistantTaskRepository, AssistantTodoRepository
from src.data.repos.base_repository import generate_id


class TaskTodoService(AtomicTaskService):
    # 写串行锁：service 是 per-call 实例化，锁须是类字段才跨实例共享。包住 update_todos
    # 的 read-modify-write + _atomic 出口 commit，串行化并发全量替换防 lost update（共享
    # session 下 repo 的 _commit 只 flush，真正 commit 在 _atomic 出口，故锁必须覆盖到
    # _atomic 出口，而非仅 replace_for_executor）。
    _write_lock = threading.Lock()

    def __init__(
        self,
        task_repo: AssistantTaskRepository | None = None,
        todo_repo: AssistantTodoRepository | None = None,
    ) -> None:
        self._init_repos(
            tasks=(AssistantTaskRepository, task_repo),
            todos=(AssistantTodoRepository, todo_repo),
        )

    def list_todos(self, task_id: str, *, session_id: str | None = None) -> list[dict]:
        task = self._tasks.get_task(task_id)
        if task is None or (session_id is not None and task.session_id != session_id):
            # 传入 session_id（REST 入口）时必须校验任务归属，避免跨会话读他人 Todo；
            # 不传（执行者工具入口）时归属由下方 executor 校验把关。
            raise LookupError("task not found")
        return [_project_todo(row) for row in self._todos.list_for_task(task_id)]

    def update_todos(
        self,
        *,
        task_id: str,
        executor_type: str,
        executor_id: str,
        items: list[dict],
        session_id: str | None = None,
    ) -> list[dict]:
        task = self._tasks.get_task(task_id)
        if task is None or (session_id is not None and task.session_id != session_id):
            raise LookupError("task not found")
        if executor_type not in {"ephemeral_subagent", "specialist"}:
            raise ValueError("todo executor must be an assistant executor")
        if task.assignee_type != executor_type or task.assignee_id != executor_id:
            raise PermissionError("todo updates require assigned executor ownership")
        normalized = [_normalize_item(item, index) for index, item in enumerate(items)]
        emitted_changes: list[tuple[str, str, str, int]] = []
        with self._write_lock:
            with self._atomic():
                before = {
                    row.todo_id: {
                        "text": row.text,
                        "status": row.status,
                        "sort_order": row.sort_order,
                    }
                    for row in self._todos.list_for_executor(
                        task_id=task_id,
                        executor_type=executor_type,
                        executor_id=executor_id,
                    )
                }
                rows = self._todos.replace_for_executor(
                    task_id=task_id,
                    executor_type=executor_type,
                    executor_id=executor_id,
                    items=normalized,
                )
                after = {row.todo_id: row for row in rows}
                for item in normalized:
                    row = after.get(item["todo_id"])
                    if row is None:
                        continue
                    previous = before.get(row.todo_id)
                    if previous is None:
                        emitted_changes.append(
                            (row.todo_id, "created", row.status, row.sort_order)
                        )
                    elif previous["text"] != row.text or previous["status"] != row.status:
                        emitted_changes.append(
                            (row.todo_id, "updated", row.status, row.sort_order)
                        )
                    elif previous["sort_order"] != row.sort_order:
                        emitted_changes.append(
                            (row.todo_id, "reordered", row.status, row.sort_order)
                        )
                for todo_id, previous in before.items():
                    if todo_id not in after:
                        emitted_changes.append(
                            (
                                todo_id,
                                "deleted",
                                str(previous["status"]),
                                int(previous["sort_order"]),
                            )
                        )
        projected = [_project_todo(row) for row in rows]
        for todo_id, change_type, status, sort_order in emitted_changes:
            emit_todo_changed(
                self,
                session_id=task.session_id,
                task_id=task.task_id,
                todo_id=todo_id,
                change_type=change_type,
                status=status,
                sort_order=sort_order,
            )
        return projected


def _normalize_item(item: dict, index: int) -> dict:
    status = TodoStatus(str(item.get("status") or "todo")).value
    todo_id = str(item.get("todoId") or item.get("todo_id") or "").strip() or generate_id("todo")
    return {
        "todo_id": todo_id,
        "text": safe_public_preview(item.get("text"), key="text", max_chars=300),
        "status": status,
        "sort_order": int(item.get("sortOrder") or item.get("sort_order") or index + 1),
    }


def _project_todo(row) -> dict:
    return {
        "todoId": row.todo_id,
        "text": safe_public_preview(row.text, key="text", max_chars=300),
        "status": row.status,
        "sortOrder": row.sort_order,
    }
