"""Business service for executor-private task Todo checklists."""

from __future__ import annotations

import threading

from src.business.task_collaboration.models import TodoStatus, safe_public_preview
from src.business.task_collaboration.ownership import executor_session_owns_task
from src.business.task_collaboration.service import emit_todo_changed
from src.business.task_collaboration.unit_of_work import AtomicTaskService
from src.data.repos import (
    AssistantTaskAttemptRepository,
    AssistantTaskRepository,
    AssistantTodoRepository,
)
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
        attempt_repo: AssistantTaskAttemptRepository | None = None,
    ) -> None:
        self._init_repos(
            tasks=(AssistantTaskRepository, task_repo),
            todos=(AssistantTodoRepository, todo_repo),
            attempts=(AssistantTaskAttemptRepository, attempt_repo),
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
        executor_session_id: str | None = None,
    ) -> list[dict]:
        task = self._tasks.get_task(task_id)
        if task is None or (session_id is not None and task.session_id != session_id):
            raise LookupError("task not found")
        if executor_type not in {"ephemeral_subagent", "specialist"}:
            raise ValueError("todo executor must be an assistant executor")
        # 权威依据是执行记录当前绑定的会话；显式指派路径保留原判定（见 ownership.py）。
        if not executor_session_owns_task(self._attempts, task_id, executor_session_id):
            if task.assignee_type != executor_type or task.assignee_id != executor_id:
                raise PermissionError("todo updates require assigned executor ownership")
        normalized = [
            _normalize_item(item, index, task_id) for index, item in enumerate(items)
        ]
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
                    creator_session_id=executor_session_id,
                )
                after = {row.todo_id: row for row in rows}
                for item in normalized:
                    row = after.get(item["todo_id"])
                    if row is None:
                        continue
                    previous = before.get(row.todo_id)
                    if previous is None:
                        emitted_changes.append((row.todo_id, "created", row.status, row.sort_order))
                    elif previous["text"] != row.text or previous["status"] != row.status:
                        emitted_changes.append((row.todo_id, "updated", row.status, row.sort_order))
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

    def create_todos(
        self,
        *,
        task_id: str,
        executor_type: str,
        executor_id: str,
        items: list[dict],
        session_id: str | None = None,
        executor_session_id: str | None = None,
    ) -> list[dict]:
        """列出新的 todo。标识由系统分配，随返回值交给执行体。

        追加语义：不动已有条目。执行体列清单是「加几件事」，不是「宣布现在
        只剩这几件」。
        """
        task = self._authorize(
            task_id=task_id,
            executor_type=executor_type,
            executor_id=executor_id,
            session_id=session_id,
            executor_session_id=executor_session_id,
        )
        base = len(
            self._todos.list_for_executor(
                task_id=task_id, executor_type=executor_type, executor_id=executor_id
            )
        )
        normalized = [
            {
                "todo_id": generate_id("todo"),
                "text": safe_public_preview(item.get("text"), key="text", max_chars=300),
                "status": TodoStatus(str(item.get("status") or "todo")).value,
                "sort_order": int(
                    item.get("sortOrder") or item.get("sort_order") or base + index + 1
                ),
            }
            for index, item in enumerate(items)
        ]
        with self._write_lock:
            with self._atomic():
                rows = self._todos.append_for_executor(
                    task_id=task_id,
                    executor_type=executor_type,
                    executor_id=executor_id,
                    items=normalized,
                    creator_session_id=executor_session_id,
                )
        for item in normalized:
            emit_todo_changed(
                self,
                session_id=task.session_id,
                task_id=task.task_id,
                todo_id=item["todo_id"],
                change_type="created",
                status=item["status"],
                sort_order=item["sort_order"],
            )
        return [_project_todo(row) for row in rows]

    def update_todo(
        self,
        *,
        task_id: str,
        todo_id: str,
        executor_type: str,
        executor_id: str,
        session_id: str | None = None,
        executor_session_id: str | None = None,
        text: str | None = None,
        status: str | None = None,
        sort_order: int | None = None,
    ) -> dict:
        """按 id 改一条的字段。只更新显式给出的，其余保持原值。

        ``todo_id`` 必须是本工具分配过的——找不到就报错，不静默新建：那会让
        执行体误以为改成功了，而清单里其实多出一条重复的。
        """
        task = self._authorize(
            task_id=task_id,
            executor_type=executor_type,
            executor_id=executor_id,
            session_id=session_id,
            executor_session_id=executor_session_id,
        )
        fields: dict = {}
        if text is not None:
            fields["text"] = safe_public_preview(text, key="text", max_chars=300)
        if status is not None:
            fields["status"] = TodoStatus(str(status)).value
        if sort_order is not None:
            fields["sort_order"] = int(sort_order)
        if not fields:
            raise ValueError("nothing to update")
        with self._write_lock:
            with self._atomic():
                row = self._todos.update_one(
                    todo_id=todo_id,
                    task_id=task_id,
                    executor_type=executor_type,
                    executor_id=executor_id,
                    fields=fields,
                )
        if row is None:
            raise LookupError("todo not found")
        change_type = "reordered" if set(fields) == {"sort_order"} else "updated"
        emit_todo_changed(
            self,
            session_id=task.session_id,
            task_id=task.task_id,
            todo_id=row.todo_id,
            change_type=change_type,
            status=row.status,
            sort_order=row.sort_order,
        )
        return _project_todo(row)

    def _authorize(
        self,
        *,
        task_id: str,
        executor_type: str,
        executor_id: str,
        session_id: str | None,
        executor_session_id: str | None,
    ):
        """任务归属 + 执行体归属校验（三个写入入口共用）。"""
        task = self._tasks.get_task(task_id)
        if task is None or (session_id is not None and task.session_id != session_id):
            raise LookupError("task not found")
        if executor_type not in {"ephemeral_subagent", "specialist"}:
            raise ValueError("todo executor must be an assistant executor")
        if not executor_session_owns_task(self._attempts, task_id, executor_session_id):
            if task.assignee_type != executor_type or task.assignee_id != executor_id:
                raise PermissionError("todo updates require assigned executor ownership")
        return task


_TODO_ID_PREFIX = "todo_"


def _is_system_issued_id(raw_id: str) -> bool:
    """判断这个 id 是不是系统发出去的。

    ``todo_id`` 是全表主键，身份由系统分配（``generate_id("todo")``）。工具契约
    要求执行体首次留空、更新时原样回传，但那只是模型软约束——它照样可能自己
    编号。实测就是每个任务都从 "1" 开始编，第二个建清单的任务写第一条即撞上
    前一个任务的 "1"，``UNIQUE constraint failed`` 让整批回滚，那个任务一条
    todo 都存不下（2026-08-11 实跑）。

    所以落库层只认自己发过的格式；执行体自编的号一律当"没给 id"，另发一个新的。
    代价是它那次更新会被当成新条目——但这只影响它没按契约回传的那批，比整批
    写不进去强得多，而且下一次它拿到的就是系统 id 了。
    """
    return raw_id.startswith(_TODO_ID_PREFIX)


def _normalize_item(item: dict, index: int, task_id: str) -> dict:
    status = TodoStatus(str(item.get("status") or "todo")).value
    raw_id = str(item.get("todoId") or item.get("todo_id") or "").strip()
    todo_id = raw_id if _is_system_issued_id(raw_id) else generate_id("todo")
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
