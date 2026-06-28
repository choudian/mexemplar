from __future__ import annotations

import time

import pytest

from src.business.user_todos.service import TITLE_LIMIT, UserTodoService


def test_user_todo_lifecycle_filters_and_priority_sort() -> None:
    service = UserTodoService()
    urgent = service.create(title="紧急事项", priority="urgent")
    low = service.create(title="低优先级事项", priority="low")
    done = service.create(title="已完成事项", priority="high")

    service.complete(done["todoId"])

    open_items, open_total = service.list_todos(status_filter="open", sort="priority_desc")
    done_items, done_total = service.list_todos(status_filter="done")

    assert open_total == 2
    assert [item["todoId"] for item in open_items] == [urgent["todoId"], low["todoId"]]
    assert done_total == 1
    assert done_items[0]["todoId"] == done["todoId"]
    assert done_items[0]["completedAt"] is not None


def test_complete_is_idempotent_and_can_be_undone() -> None:
    service = UserTodoService()
    todo = service.create(title="写周报")

    first = service.complete(todo["todoId"])
    second = service.complete(todo["todoId"])
    undone = service.complete(todo["todoId"], done=False)

    assert first["status"] == "done"
    assert second["status"] == "done"
    assert second["completedAt"] == first["completedAt"]
    # 撤销完成应回到 in_progress（保留"进行中"语义），不再丢失为 pending
    assert undone["status"] == "in_progress"
    assert undone["completedAt"] is None


def test_undo_complete_from_pending_stays_pending() -> None:
    service = UserTodoService()
    todo = service.create(title="新任务")

    undone = service.complete(todo["todoId"], done=False)

    # 已经是 pending 时撤销完成不应改变状态，也不应 bump updated_at（no-op 不写入）
    assert undone["status"] == "pending"
    assert undone["updatedAt"] == todo["updatedAt"]


def test_update_validates_and_truncates_title() -> None:
    service = UserTodoService()
    todo = service.create(title="初始标题")

    updated = service.update(todo["todoId"], {"title": "x" * (TITLE_LIMIT + 20)})

    assert len(updated["title"]) == TITLE_LIMIT
    with pytest.raises(ValueError):
        service.update(todo["todoId"], {"priority": "impossible"})


def test_delete_removes_user_todo() -> None:
    service = UserTodoService()
    todo = service.create(title="临时事项")

    service.delete(todo["todoId"])

    items, total = service.list_todos(status_filter="all")
    assert items == []
    assert total == 0
    with pytest.raises(LookupError):
        service.delete(todo["todoId"])


def test_empty_update_still_bumps_updated_at() -> None:
    service = UserTodoService()
    todo = service.create(title="初始事项")
    original_updated = todo["updatedAt"]

    time.sleep(0.01)

    result = service.update(todo["todoId"], {})
    assert result["updatedAt"] is not None
    assert result["updatedAt"] != original_updated


def test_undo_complete_from_in_progress_stays_in_progress() -> None:
    service = UserTodoService()
    created = service.create(title="进行中任务")
    in_progress = service.update(created["todoId"], {"status": "in_progress"})

    undone = service.complete(created["todoId"], done=False)

    # 已经是 in_progress 时撤销完成保持 in_progress，且不 bump updated_at（no-op）
    assert undone["status"] == "in_progress"
    assert undone["updatedAt"] == in_progress["updatedAt"]


def test_search_treats_like_wildcards_as_literals() -> None:
    service = UserTodoService()
    service.create(title="50% 折扣")
    service.create(title="task_1")
    service.create(title="普通任务")

    # % 与 _ 必须按字面匹配，不被当作 SQL LIKE 通配符（覆盖 ilike + escape 契约）
    pct, pct_total = service.list_todos(query="50% 折扣")
    assert pct_total == 1
    assert pct[0]["title"] == "50% 折扣"

    und, und_total = service.list_todos(query="task_1")
    assert und_total == 1
    assert und[0]["title"] == "task_1"
