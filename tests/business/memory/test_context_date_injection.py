from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.business.memory.context_manager import ContextManager


@pytest.fixture
def context_manager(mock_config):
    with (
        patch("src.business.memory.context_manager.MessageRepository"),
        patch("src.business.memory.context_manager.SessionRepository"),
    ):
        manager = ContextManager("test-session", mock_config)
    manager._compression_handler.should_compress = MagicMock(return_value=False)
    return manager


def _with_created_at(message, created_at: datetime):
    message.created_at = created_at
    return message


def test_assemble_context_injects_first_and_cross_day_user_dates(
    context_manager,
    make_message,
):
    messages = [
        _with_created_at(
            make_message(role="system", content="system"),
            datetime(2026, 6, 13, 8, 0),
        ),
        _with_created_at(
            make_message(role="user", content="查一下本月项目"),
            datetime(2026, 6, 13, 9, 0),
        ),
        _with_created_at(
            make_message(role="assistant", content="好的"),
            datetime(2026, 6, 13, 9, 1),
        ),
        _with_created_at(
            make_message(role="user", content="继续"),
            datetime(2026, 6, 13, 16, 0),
        ),
        _with_created_at(
            make_message(role="program", content="内部通知"),
            datetime(2026, 6, 14, 8, 0),
        ),
        _with_created_at(
            make_message(role="user", content="今天有什么变化"),
            datetime(2026, 6, 14, 9, 0),
        ),
        _with_created_at(
            make_message(role="user", content="再看看"),
            datetime(2026, 6, 14, 10, 0),
        ),
    ]
    context_manager._msg_repo.get_context.return_value = messages

    with patch(
        "src.business.memory.context_manager.to_local",
        side_effect=lambda value: value,
    ):
        result = context_manager.assemble_context()

    assert [item["content"] for item in result] == [
        "system",
        "[2026-06-13] 查一下本月项目",
        "好的",
        "继续",
        "内部通知",
        "[2026-06-14] 今天有什么变化",
        "再看看",
    ]


def test_date_injection_does_not_mutate_persisted_messages(
    context_manager,
    make_message,
):
    user_message = _with_created_at(
        make_message(role="user", content="用户原话"),
        datetime(2026, 6, 13, 9, 0),
    )
    context_manager._msg_repo.get_context.return_value = [user_message]

    with patch(
        "src.business.memory.context_manager.to_local",
        side_effect=lambda value: value,
    ):
        first_result = context_manager.assemble_context()
        second_result = context_manager.assemble_context()

    assert first_result[0]["content"] == "[2026-06-13] 用户原话"
    assert second_result[0]["content"] == "[2026-06-13] 用户原话"
    assert user_message.content == "用户原话"


def test_date_injection_ignores_user_mapped_internal_roles(
    context_manager,
    make_message,
):
    messages = [
        _with_created_at(
            make_message(role="summary", content="压缩摘要"),
            datetime(2026, 6, 12, 8, 0),
        ),
        _with_created_at(
            make_message(role="agent", content="代理交接"),
            datetime(2026, 6, 13, 8, 0),
        ),
        _with_created_at(
            make_message(role="user", content="真实用户消息"),
            datetime(2026, 6, 13, 9, 0),
        ),
    ]
    context_manager._msg_repo.get_context.return_value = messages

    with patch(
        "src.business.memory.context_manager.to_local",
        side_effect=lambda value: value,
    ):
        result = context_manager.assemble_context()

    assert result == [
        {"role": "user", "content": "压缩摘要"},
        {"role": "user", "content": "代理交接"},
        {"role": "user", "content": "[2026-06-13] 真实用户消息"},
    ]
