"""
tests/business/memory/ 共享 fixture。

提供 mock Message 工厂函数和 mock MessageRepository。
"""

import json
import uuid
from unittest.mock import MagicMock

import pytest

from src.data.models_sqlite import Message


@pytest.fixture
def make_message():
    """创建 Message 对象的工厂函数。

    Args:
        role: 消息角色（system/user/assistant/tool）
        content: 消息内容
        sequence: 序列号（默认自增）
        tool_calls: tool_calls JSON 字符串或 list[dict]（assistant 角色）
        tool_call_id: 工具调用 ID（tool 角色）
        tool_name: 工具名称（tool 角色）
        message_id: 自定义 message_id（默认自动生成）
    """

    _seq = [0]

    def _factory(
        role: str,
        content: str | None = None,
        sequence: int | None = None,
        tool_calls: str | list | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        message_id: str | None = None,
    ) -> Message:
        if sequence is not None:
            _seq[0] = max(_seq[0], sequence)
        else:
            _seq[0] += 1
            sequence = _seq[0]

        if isinstance(tool_calls, list):
            tool_calls = json.dumps(tool_calls)

        return Message(
            message_id=message_id or f"msg-{uuid.uuid4().hex[:8]}",
            session_id="test-session",
            sequence=sequence,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )

    return _factory


@pytest.fixture
def mock_msg_repo():
    """返回一个 mock MessageRepository，所有方法无操作。"""
    repo = MagicMock()
    repo.create.return_value = None
    repo.mark_archived.return_value = None
    repo.get_context.return_value = []
    return repo
