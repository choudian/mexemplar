from __future__ import annotations

import json
import threading

import pytest

from src.business.agents.tools.assistant_tools import create_todo_update_handler
from src.business.task_collaboration.todos import TaskTodoService
from src.data.repos import AssistantTaskRepository, AssistantTodoRepository
from src.utils.events import clear_all, connect


def _assigned_task(task_id: str = "tsk_todo"):
    return AssistantTaskRepository().create_task(
        graph_id="tg_todo",
        session_id="ast_todo",
        task_id=task_id,
        title="long task",
        description="long task",
        owner_session_id="ast_todo",
        assignee_type="specialist",
        assignee_id="sp_1",
        status="running",
    )


def test_todo_persists_ordering_and_distinct_statuses() -> None:
    task = _assigned_task()
    service = TaskTodoService()

    items = service.update_todos(
        task_id=task.task_id,
        executor_type="specialist",
        executor_id="sp_1",
        items=[
            {"todoId": "todo_2", "text": "second", "status": "doing", "sortOrder": 2},
            {"todoId": "todo_1", "text": "first", "status": "done", "sortOrder": 1},
        ],
    )
    reloaded = TaskTodoService().list_todos(task.task_id)

    assert [item["todoId"] for item in items] == ["todo_1", "todo_2"]
    assert [item["status"] for item in reloaded] == ["done", "doing"]
    assert AssistantTaskRepository().get_task(task.task_id).status == "running"


def test_todo_update_requires_assigned_executor_ownership() -> None:
    task = _assigned_task("tsk_owned")

    with pytest.raises(PermissionError):
        TaskTodoService().update_todos(
            task_id=task.task_id,
            executor_type="specialist",
            executor_id="sp_other",
            items=[{"todoId": "todo_1", "text": "step", "status": "todo", "sortOrder": 1}],
        )

    assert AssistantTodoRepository().list_for_task(task.task_id) == []


def test_todo_update_tool_handler_returns_safe_projection() -> None:
    task = _assigned_task("tsk_tool_todo")
    handler = create_todo_update_handler(executor_type="specialist", executor_id="sp_1")

    result = json.loads(
        handler(
            taskId=task.task_id,
            items=[
                {"todoId": "todo_1", "text": "collect invoices", "status": "done", "sortOrder": 1}
            ],
        )
    )

    assert result["success"] is True
    assert result["taskId"] == task.task_id
    assert result["items"][0]["status"] == "done"


def test_todo_update_emits_granular_change_types() -> None:
    clear_all()
    captured: list[dict] = []
    connect("assistant_todo_changed", lambda sender, **kw: captured.append(kw), weak=False)
    task = _assigned_task("tsk_todo_events")
    try:
        TaskTodoService().update_todos(
            task_id=task.task_id,
            executor_type="specialist",
            executor_id="sp_1",
            items=[
                {"todoId": "todo_1", "text": "first", "status": "todo", "sortOrder": 1},
                {"todoId": "todo_2", "text": "second", "status": "todo", "sortOrder": 2},
                {"todoId": "todo_3", "text": "third", "status": "todo", "sortOrder": 3},
            ],
        )
        assert [event["change_type"] for event in captured] == [
            "created",
            "created",
            "created",
        ]

        captured.clear()
        TaskTodoService().update_todos(
            task_id=task.task_id,
            executor_type="specialist",
            executor_id="sp_1",
            items=[
                {"todoId": "todo_2", "text": "second", "status": "todo", "sortOrder": 1},
                {"todoId": "todo_1", "text": "first changed", "status": "doing", "sortOrder": 2},
            ],
        )

        changes = {event["todo_id"]: event["change_type"] for event in captured}
        assert changes == {
            "todo_1": "updated",
            "todo_2": "reordered",
            "todo_3": "deleted",
        }
    finally:
        clear_all()


def test_concurrent_update_todos_serializes_replaces_without_blending(monkeypatch) -> None:
    # 回归保护：TaskTodoService._write_lock 串行化并发 update_todos 的 read-modify-write。
    # CPython GIL + SQLite 单写者已把单进程内该窗口压得很小，故在 replace_for_executor 的
    # read-existing 之后、commit 之前（utc_now_naive 调用点）注入让步，确定性放大窗口：
    # 无锁时两线程都读到旧 existing → 各自 upsert → 混合态 {keep,a,b}（lost update）；
    # 加锁后另一线程被挡在临界区外，串行 → 最终为某一调用的全量集合。
    import time

    from src.data.repos import assistant_todo_repository as todo_repo_mod

    task = _assigned_task("tsk_concurrent")
    keep = {"todoId": "keep", "text": "keep", "status": "todo", "sortOrder": 1}
    TaskTodoService().update_todos(
        task_id=task.task_id,
        executor_type="specialist",
        executor_id="sp_1",
        items=[keep],
    )

    let_count = {"n": 0}
    real_now = todo_repo_mod.utc_now_naive

    def yielding_now():
        if let_count["n"] < 4:
            let_count["n"] += 1
            time.sleep(0.05)
        return real_now()

    monkeypatch.setattr(todo_repo_mod, "utc_now_naive", yielding_now)

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def replace_all(extra: dict) -> None:
        try:
            barrier.wait(timeout=5)
            TaskTodoService().update_todos(
                task_id=task.task_id,
                executor_type="specialist",
                executor_id="sp_1",
                items=[keep, extra],
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(
        target=replace_all,
        args=({"todoId": "a", "text": "a", "status": "todo", "sortOrder": 2},),
    )
    t2 = threading.Thread(
        target=replace_all,
        args=({"todoId": "b", "text": "b", "status": "todo", "sortOrder": 2},),
    )
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert errors == []
    final = {item["todoId"] for item in TaskTodoService().list_todos(task.task_id)}
    assert final == {"keep", "a"} or final == {"keep", "b"}
