from __future__ import annotations

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
    assert undone["status"] == "pending"
    assert undone["completedAt"] is None


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
