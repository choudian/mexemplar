"""
032 T001: delegation_context resolver 单元测试

覆盖:
- use_llm_messages_snapshot 生命周期(设置/退出清除/嵌套还原)
- resolve_context_message_indexes 合法展开(逐字、1-based、role 标记)与 system 拒绝
- fail-closed:越界、非正整数、非法类型、空数组、无快照、超上限(不截断)
- 重复下标整体拒绝
- 上限从 get_unified_config 读取
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from src.business.agents.delegation_context import (
    DelegationContextError,
    get_llm_messages_snapshot,
    resolve_context_message_indexes,
    use_llm_messages_snapshot,
)

SNAPSHOT = [
    {"role": "system", "content": "你是助理。"},
    {"role": "user", "content": "给我出一个部署方案"},
    {"role": "assistant", "content": "方案全文：第一步…第二步…第三步…"},
    {"role": "user", "content": "把这个方案写到 docs/plan.md"},
]


def _patch_max_chars(value: int):
    config = MagicMock()
    config.get_agent_tools_delegation_context_expansion_max_chars.return_value = value
    return patch(
        "src.business.agents.delegation_context.get_unified_config",
        return_value=config,
    )


class TestSnapshotLifecycle:
    def test_snapshot_visible_inside_and_cleared_outside(self):
        assert get_llm_messages_snapshot() is None
        with use_llm_messages_snapshot(SNAPSHOT):
            snapshot = get_llm_messages_snapshot()
            assert snapshot is not None
            assert [(message.role, message.content) for message in snapshot] == [
                (message["role"], message["content"]) for message in SNAPSHOT
            ]
        assert get_llm_messages_snapshot() is None

    def test_snapshot_is_stable_if_source_messages_are_mutated(self):
        source = [{"role": "assistant", "content": "原始方案"}]

        with use_llm_messages_snapshot(source), _patch_max_chars(30000):
            source[0]["role"] = "system"
            source[0]["content"] = "被改写的内容"
            block = resolve_context_message_indexes([1])

        assert "assistant" in block
        assert "原始方案" in block
        assert "被改写的内容" not in block

    def test_nested_snapshot_restores_outer(self):
        inner = [{"role": "user", "content": "inner"}]
        with use_llm_messages_snapshot(SNAPSHOT):
            outer = get_llm_messages_snapshot()
            with use_llm_messages_snapshot(inner):
                snapshot = get_llm_messages_snapshot()
                assert snapshot is not None
                assert [(message.role, message.content) for message in snapshot] == [
                    ("user", "inner")
                ]
            assert get_llm_messages_snapshot() is outer

    def test_parallel_threads_keep_snapshots_isolated(self):
        barrier = threading.Barrier(2)

        def resolve_in_thread(label: str):
            snapshot = [{"role": "user", "content": label}]
            with use_llm_messages_snapshot(snapshot):
                barrier.wait(timeout=5)
                block = resolve_context_message_indexes([1])
                barrier.wait(timeout=5)
                current = get_llm_messages_snapshot()
                assert current is not None
                assert [(message.role, message.content) for message in current] == [("user", label)]
            return block, get_llm_messages_snapshot()

        with _patch_max_chars(30000), ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(resolve_in_thread, "session-A")
            second = executor.submit(resolve_in_thread, "session-B")
            first_block, first_after = first.result(timeout=5)
            second_block, second_after = second.result(timeout=5)

        assert "session-A" in first_block and "session-B" not in first_block
        assert "session-B" in second_block and "session-A" not in second_block
        assert first_after is None
        assert second_after is None
        assert get_llm_messages_snapshot() is None


class TestResolveValid:
    def test_expands_verbatim_with_role_markers(self):
        assistant_content = "line  \nend\t "
        tool_content = '{"status":"ok"}\n  '
        snapshot = [
            {"role": "assistant", "content": assistant_content},
            {"role": "tool", "content": tool_content},
        ]

        with use_llm_messages_snapshot(snapshot), _patch_max_chars(30000):
            block = resolve_context_message_indexes([1, 2])

        assert block == (
            "【主对话相关原文】\n"
            f"--- 消息 #1（assistant）---\n{assistant_content}\n"
            f"--- 消息 #2（tool）---\n{tool_content}"
        )

    def test_system_message_reference_rejected(self):
        """system prompt 可能含父 Agent 的能力目录，不得下放给执行体。"""
        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars(30000):
            with pytest.raises(DelegationContextError) as exc_info:
                resolve_context_message_indexes([1])
        assert "system" in str(exc_info.value)
        assert "能力目录" in str(exc_info.value)

    def test_duplicate_indexes_rejected(self):
        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars(30000):
            with pytest.raises(DelegationContextError) as exc_info:
                resolve_context_message_indexes([3, 2, 3])
        assert "重复" in str(exc_info.value)

    def test_snapshot_not_mutated(self):
        snapshot = [dict(m) for m in SNAPSHOT]
        original = [dict(m) for m in snapshot]
        with use_llm_messages_snapshot(snapshot), _patch_max_chars(30000):
            resolve_context_message_indexes([2, 4])
        assert snapshot == original

    def test_none_content_expands_as_empty(self):
        snapshot = [{"role": "assistant", "content": None}]
        with use_llm_messages_snapshot(snapshot), _patch_max_chars(30000):
            block = resolve_context_message_indexes([1])
        assert "--- 消息 #1（assistant）---" in block


class TestResolveFailClosed:
    def test_out_of_range_rejected(self):
        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars(30000):
            with pytest.raises(DelegationContextError) as exc_info:
                resolve_context_message_indexes([5])
        assert "1" in str(exc_info.value) and "4" in str(exc_info.value)

    @pytest.mark.parametrize("bad", [[0], [-1], ["2"], [True], [1.0], [2.5], "not-a-list", 3])
    def test_non_positive_or_non_int_rejected(self, bad):
        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars(30000):
            with pytest.raises(DelegationContextError):
                resolve_context_message_indexes(bad)

    def test_empty_array_rejected(self):
        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars(30000):
            with pytest.raises(DelegationContextError):
                resolve_context_message_indexes([])

    @pytest.mark.parametrize("bad", [[], ["2"], [2, 2]])
    def test_invalid_value_errors_include_legal_range(self, bad):
        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars(30000):
            with pytest.raises(DelegationContextError) as exc_info:
                resolve_context_message_indexes(bad)
        assert "1..4" in str(exc_info.value)

    def test_no_snapshot_rejected_with_guidance(self):
        assert get_llm_messages_snapshot() is None
        with _patch_max_chars(30000):
            with pytest.raises(DelegationContextError) as exc_info:
                resolve_context_message_indexes([1])
        assert "execution_context" in str(exc_info.value)

    def test_over_limit_rejected_not_truncated(self):
        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars(10):
            with pytest.raises(DelegationContextError) as exc_info:
                resolve_context_message_indexes([3])
        assert "10" in str(exc_info.value)

    def test_partial_expansion_never_returned_on_mixed_validity(self):
        """混合合法与非法下标时整体拒绝,不部分展开"""
        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars(30000):
            with pytest.raises(DelegationContextError):
                resolve_context_message_indexes([2, 99])
