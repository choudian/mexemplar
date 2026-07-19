"""调度工具 handler 的错误路径回归。"""

from __future__ import annotations

import json

from src.business.agents.tools.assistant_tools import (
    create_create_scheduled_task_handler,
)
from src.data.repos import user_todo_repository as todo_repo_module


def test_todo_prefetch_failure_does_not_create_an_unusable_confirmation(
    monkeypatch,
) -> None:
    class _FailingTodoRepository:
        def __enter__(self):
            raise RuntimeError("database temporarily unavailable")

        def __exit__(self, *_):
            return None

    class _ConfirmationManager:
        def create(self, _draft, _session_id):
            raise AssertionError("an empty todo draft must not reach confirmation")

    monkeypatch.setattr(
        todo_repo_module,
        "UserTodoRepository",
        _FailingTodoRepository,
    )
    handler = create_create_scheduled_task_handler(
        "ast_tool_error",
        confirmation_manager_factory=_ConfirmationManager,
    )

    result = json.loads(
        handler(
            source_type="todo",
            schedule_kind="one_shot",
            schedule_payload={"run_at": "2099-01-01T00:00:00"},
            todo_id="utodo_missing_db",
        )
    )

    assert result["success"] is False
    assert result["message"] == "创建定时任务时发生内部错误，请稍后重试。"
