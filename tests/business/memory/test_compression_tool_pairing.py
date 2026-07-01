"""
边界调整测试：验证 _adjust_boundary_for_tool_pairs 正确处理跨越压缩/保留边界的 tool 组。
"""

from unittest.mock import MagicMock

import pytest

from src.business.memory.compression_handler import CompressionHandler
from src.data.repositories import MessageRepository
from tests.data.chat_history_test_helpers import create_assistant_session, seed_message


@pytest.fixture
def handler():
    """创建 CompressionHandler 实例，禁用压缩触发。"""
    config = MagicMock()
    config.get_memory_compression_keep_recent.return_value = 3
    config.get_memory_compression_trigger_strategy.return_value = "count"
    config.get_memory_compression_count_threshold.return_value = 100
    return CompressionHandler(config)


class TestAdjustBoundaryForToolPairs:
    """_adjust_boundary_for_tool_pairs 单元测试。"""

    def test_no_tool_groups_in_compress(self, handler, make_message):
        """压缩区无 tool 组 → 边界不调整。"""
        compress_msgs = [
            make_message(role="user", content="hello"),
            make_message(role="assistant", content="hi"),
        ]
        keep_msgs = [
            make_message(role="user", content="next"),
            make_message(role="assistant", content="ok"),
        ]
        result_c, result_k = handler._adjust_boundary_for_tool_pairs(compress_msgs, keep_msgs)
        assert result_c is compress_msgs
        assert result_k is keep_msgs

    def test_tool_group_fully_in_compress(self, handler, make_message):
        """tool 组完全在压缩区 → 不调整（正常压缩）。"""
        compress_msgs = [
            make_message(role="user", content="hello"),
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
        keep_msgs = [
            make_message(role="user", content="next"),
        ]
        result_c, result_k = handler._adjust_boundary_for_tool_pairs(compress_msgs, keep_msgs)
        assert len(result_c) == len(compress_msgs)
        assert len(result_k) == len(keep_msgs)

    def test_tool_group_straddles_boundary(self, handler, make_message):
        """assistant 在压缩区、部分 tool result 在保留区 → 整组移入保留区。"""
        compress_msgs = [
            make_message(role="user", content="hello"),
            make_message(
                role="assistant",
                content=None,
                tool_calls=[
                    {"id": "call_1", "name": "tool_a", "args": {}},
                    {"id": "call_2", "name": "tool_b", "args": {}},
                ],
            ),
            make_message(
                role="tool",
                content="result_1",
                tool_call_id="call_1",
                tool_name="tool_a",
            ),
        ]
        keep_msgs = [
            make_message(
                role="tool",
                content="result_2",
                tool_call_id="call_2",
                tool_name="tool_b",
            ),
            make_message(role="assistant", content="summary"),
        ]

        result_c, result_k = handler._adjust_boundary_for_tool_pairs(compress_msgs, keep_msgs)

        # assistant + 1 个 tool result 从压缩区移到保留区
        assert len(result_c) == 1  # 只有 user "hello"
        assert len(result_k) == 4  # assistant + tool_1 + tool_2 + summary

        # 验证保留区顺序：被移入的边界组在前，原有 keep 在后
        assert result_k[0].role == "assistant"
        assert result_k[0].tool_calls is not None
        assert result_k[1].tool_call_id == "call_1"
        assert result_k[2].tool_call_id == "call_2"
        assert result_k[3].role == "assistant"
        assert result_k[3].content == "summary"

    def test_tool_group_assistant_in_compress_all_results_in_keep(self, handler, make_message):
        """assistant 在压缩区、全部 tool result 在保留区 → 整组移入保留区。"""
        compress_msgs = [
            make_message(role="user", content="hello"),
            make_message(
                role="assistant",
                content=None,
                tool_calls=[{"id": "call_1", "name": "tool_a", "args": {}}],
            ),
        ]
        keep_msgs = [
            make_message(
                role="tool",
                content="result_1",
                tool_call_id="call_1",
                tool_name="tool_a",
            ),
            make_message(role="assistant", content="done"),
        ]

        result_c, result_k = handler._adjust_boundary_for_tool_pairs(compress_msgs, keep_msgs)

        assert len(result_c) == 1  # 只有 user "hello"
        assert len(result_k) == 3  # assistant + tool_1 + done

    def test_multiple_tool_groups_only_last_straddles(self, handler, make_message):
        """多个 tool 组，仅最后一个跨越 → 只调整最后一个。"""
        compress_msgs = [
            make_message(role="user", content="hello"),
            # 第一组：完全在压缩区
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
            # 第二组：assistant 在压缩区，tool result 跨越
            make_message(
                role="assistant",
                content=None,
                tool_calls=[{"id": "call_2", "name": "tool_b", "args": {}}],
            ),
        ]
        keep_msgs = [
            make_message(
                role="tool",
                content="result_2",
                tool_call_id="call_2",
                tool_name="tool_b",
            ),
            make_message(role="assistant", content="summary"),
        ]

        result_c, result_k = handler._adjust_boundary_for_tool_pairs(compress_msgs, keep_msgs)

        # 第一组不动，第二组移入保留区
        assert len(result_c) == 3  # user + call_1 assistant + call_1 result
        assert len(result_k) == 3  # call_2 assistant + call_2 result + summary


class TestCompressEmptyAfterAdjustment:
    """边界调整后压缩区为空的处理。"""

    def test_empty_compress_after_adjustment(self, handler, make_message, mock_msg_repo):
        """调整后压缩区为空 → compress 返回原始消息（不调 LLM，不持久化）。"""
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
        ]

        result = handler.compress("test-session", messages, mock_msg_repo)

        # 不调 LLM，不持久化，直接返回 system + keep_msgs
        assert len(result) == 3
        assert result[0].role == "system"
        mock_msg_repo.create.assert_not_called()
        mock_msg_repo.mark_archived.assert_not_called()


class TestReCompressAbsorbsBoundaryGroup:
    """二次压缩场景：上一轮保留的 tool 组在二次压缩时正常压缩。"""

    def test_re_compress_absorbs_previous_boundary_group(self, handler, make_message):
        """上一轮保留的边界 tool 组在二次压缩时完全在压缩区内部 → 正常压缩，不重复保留。"""
        # 模拟二次压缩场景：tool 组完全在压缩区
        compress_msgs = [
            make_message(role="user", content="q1"),
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
            make_message(role="assistant", content="summary"),
        ]
        keep_msgs = [
            make_message(role="user", content="q2"),
        ]

        result_c, result_k = handler._adjust_boundary_for_tool_pairs(compress_msgs, keep_msgs)

        # tool 组完全在压缩区，不调整
        assert len(result_c) == len(compress_msgs)
        assert len(result_k) == len(keep_msgs)


class _FakeCompressionLLM:
    def chat(self, _prompt: str) -> str:
        return "### 当前进展\n- 已完成 call_1 的工具读取。"


class TestCompressPersistence:
    """压缩持久化回归测试。"""

    def test_compress_does_not_archive_new_summary_message(self):
        """摘要复用起始 sequence 时，归档原始范围不能把新摘要一起归档。"""
        session_id = create_assistant_session("ast_compress_self_archive")
        seed_message(session_id, sequence=1, role="system", content="sys")
        seed_message(session_id, sequence=2, role="user", content="请读取资料")
        seed_message(
            session_id,
            sequence=3,
            role="assistant",
            content=None,
            tool_calls='[{"id":"call_1","name":"web_fetch","args":{"url":"https://example.test"}}]',
        )
        seed_message(
            session_id,
            sequence=4,
            role="tool",
            content="x" * 2000,
            tool_call_id="call_1",
        )
        seed_message(session_id, sequence=5, role="assistant", content="读取完成")
        seed_message(session_id, sequence=6, role="user", content="继续")

        config = MagicMock()
        config.get_memory_compression_keep_recent.return_value = 1
        config.get_memory_compression_trigger_strategy.return_value = "count"
        config.get_memory_compression_count_threshold.return_value = 2
        handler = CompressionHandler(config)
        handler._llm_client = _FakeCompressionLLM()
        repo = MessageRepository()

        handler.compress(session_id, repo.get_context(session_id), repo)

        context = repo.get_context(session_id)
        summaries = [
            msg for msg in context if msg.role == "summary" and msg.message_type == "compressed"
        ]
        assert len(summaries) == 1
        assert summaries[0].sequence == 2
        assert summaries[0].is_archived is False
        assert [msg.sequence for msg in context] == [1, 2, 6]

        original_archived = {
            msg.sequence
            for msg in repo.get_all(session_id)
            if msg.message_type == "normal" and 2 <= msg.sequence <= 5 and msg.is_archived
        }
        assert original_archived == {2, 3, 4, 5}
