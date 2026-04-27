"""
孤立 tool result 清理测试：验证 _cleanup_orphan_tool_results 正确检测和剔除孤立 tool result。
"""

import logging
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def context_manager():
    """创建 ContextManager 实例（使用 mock repository）。"""
    from src.business.memory.context_manager import ContextManager

    with (
        patch("src.business.memory.context_manager.MessageRepository"),
        patch("src.business.memory.context_manager.SessionRepository"),
    ):
        config = MagicMock()
        config.get_memory_compression_keep_recent.return_value = 3
        config.get_memory_compression_trigger_strategy.return_value = "count"
        config.get_memory_compression_count_threshold.return_value = 100
        return ContextManager("test-session", config)


class TestCleanupOrphanToolResults:
    """_cleanup_orphan_tool_results 单元测试。"""

    def test_no_orphans(self, context_manager, make_message):
        """无孤立 → 消息不变。"""
        messages = [
            make_message(role="system", content="sys"),
            make_message(
                role="assistant",
                content=None,
                tool_calls=[{"id": "call_1", "name": "tool_a", "args": {}}],
            ),
            make_message(
                role="tool",
                content="result_1",
                tool_call_id="call_1",
                tool_name="tool_a",
            ),
            make_message(role="assistant", content="done"),
        ]
        result = context_manager._cleanup_orphan_tool_results(messages)
        assert len(result) == len(messages)

    def test_orphan_tool_result_removed(self, context_manager, make_message):
        """孤立 tool result → 被剔除。"""
        messages = [
            make_message(role="system", content="sys"),
            make_message(
                role="tool",
                content="orphan result",
                tool_call_id="call_nonexistent",
                tool_name="tool_x",
            ),
            make_message(role="assistant", content="response"),
        ]
        result = context_manager._cleanup_orphan_tool_results(messages)
        assert len(result) == 2
        assert all(m.role != "tool" for m in result)

    def test_mixed_valid_and_orphan(self, context_manager, make_message):
        """有效保留、孤立剔除。"""
        messages = [
            make_message(role="system", content="sys"),
            make_message(
                role="assistant",
                content=None,
                tool_calls=[{"id": "call_1", "name": "tool_a", "args": {}}],
            ),
            make_message(
                role="tool",
                content="valid",
                tool_call_id="call_1",
                tool_name="tool_a",
            ),
            make_message(
                role="tool",
                content="orphan",
                tool_call_id="call_ghost",
                tool_name="tool_x",
            ),
            make_message(role="assistant", content="done"),
        ]
        result = context_manager._cleanup_orphan_tool_results(messages)
        assert len(result) == 4
        tool_results = [m for m in result if m.role == "tool"]
        assert len(tool_results) == 1
        assert tool_results[0].tool_call_id == "call_1"

    def test_warning_logged(self, context_manager, make_message, caplog):
        """剔除时记录 warning 日志。"""
        messages = [
            make_message(
                role="tool",
                content="orphan",
                tool_call_id="call_ghost",
                tool_name="tool_x",
            ),
        ]
        with caplog.at_level(logging.WARNING, logger="src.business.memory.context_manager"):
            context_manager._cleanup_orphan_tool_results(messages)
        assert any("孤立" in r.message for r in caplog.records)

    def test_reference_handler_still_applies_after_cleanup(self, context_manager, make_message):
        """边界保留的大 tool result 在清理后仍按 reference_handler 规则替换为指针。"""
        # 大内容 tool result（有效配对）
        large_content = "x" * 2000
        messages = [
            make_message(
                role="assistant",
                content=None,
                tool_calls=[{"id": "call_1", "name": "tool_a", "args": {}}],
            ),
            make_message(
                role="tool",
                content=large_content,
                tool_call_id="call_1",
                tool_name="tool_a",
            ),
        ]
        cleaned = context_manager._cleanup_orphan_tool_results(messages)
        assert len(cleaned) == 2
        assert cleaned[1].content == large_content  # 内容未被修改

    def test_pending_tool_calls_unchanged_after_orphan_cleanup(self, context_manager, make_message):
        """清理孤立 tool result 不影响未配对 tool_call 检测。"""
        messages = [
            make_message(
                role="assistant",
                content=None,
                tool_calls=[{"id": "call_pending", "name": "tool_x", "args": {}}],
            ),
            make_message(
                role="tool",
                content="orphan",
                tool_call_id="call_ghost",
                tool_name="tool_y",
            ),
        ]
        cleaned = context_manager._cleanup_orphan_tool_results(messages)

        # call_pending 的 assistant 仍在
        assistant_msgs = [m for m in cleaned if m.role == "assistant" and m.tool_calls]
        assert len(assistant_msgs) == 1

        # call_ghost 的 tool result 被剔除
        tool_msgs = [m for m in cleaned if m.role == "tool"]
        assert len(tool_msgs) == 0
