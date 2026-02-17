"""
IntentConfirmer 边界条件测试

测试各种边界条件和异常场景
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
import asyncio
import time

from src.business.intent.intent_confirmer import IntentConfirmer, ConfirmationState
from src.business.intent.intent_models import Intent, IntentStatus
from src.business.ai.prompts.intent_analysis_models import (
    Intent as IntentAnalysisModel,
    IntentAnalysisResult,
)
from src.communication.message_types import WebSocketMessage


class TestConfirmationStateEdgeCases:
    """ConfirmationState 状态机边界测试"""

    def test_initial_state_with_empty_intent(self):
        """测试空意图的初始状态"""
        empty_intent = IntentAnalysisModel(
            core_operations="",
            target="",
            business_scenario="",
            expected_results="",
        )
        state = ConfirmationState(empty_intent)

        assert state.current_turn == 0
        assert state.state == "pending_confirmation"
        assert state.max_turns == 5

    def test_max_turns_boundary(self):
        """测试达到最大轮次"""
        intent = IntentAnalysisModel(
            core_operations="测试操作",
            target="测试目标",
            business_scenario="测试场景",
            expected_results="测试结果",
        )
        state = ConfirmationState(intent)
        state.max_turns = 3  # 设置较小的最大轮次

        # 推进到最大轮次
        assert state.advance_turn()  # turn 1
        assert state.advance_turn()  # turn 2
        assert state.advance_turn()  # turn 3
        assert not state.advance_turn()  # turn 4 - 应该失败

        assert state.current_turn == 3
        assert not state.can_continue()

    def test_zero_max_turns(self):
        """测试最大轮次为 0 的情况"""
        intent = IntentAnalysisModel(
            core_operations="测试",
            target="测试",
            business_scenario="测试",
            expected_results="测试",
        )
        state = ConfirmationState(intent)
        state.max_turns = 0

        assert not state.can_continue()
        assert not state.advance_turn()

    def test_state_transitions_from_cancelled(self):
        """测试从取消状态不能继续"""
        intent = IntentAnalysisModel(
            core_operations="测试",
            target="测试",
            business_scenario="测试",
            expected_results="测试",
        )
        state = ConfirmationState(intent)
        state.cancel()

        assert not state.can_continue()
        assert not state.advance_turn()

    def test_state_transitions_from_confirmed(self):
        """测试从确认状态不能继续"""
        intent = IntentAnalysisModel(
            core_operations="测试",
            target="测试",
            business_scenario="测试",
            expected_results="测试",
        )
        state = ConfirmationState(intent)
        state.confirm()

        assert not state.can_continue()
        assert not state.advance_turn()

    def test_refining_state_allows_continuation(self):
        """测试优化状态允许继续"""
        intent = IntentAnalysisModel(
            core_operations="测试",
            target="测试",
            business_scenario="测试",
            expected_results="测试",
        )
        state = ConfirmationState(intent)
        state.start_refining()

        assert state.can_continue()
        assert state.advance_turn()


class TestIntentConfirmerEdgeCases:
    """IntentConfirmer 边界条件测试"""

    @pytest.fixture
    def confirmer(self):
        """创建 IntentConfirmer 实例"""
        mock_analyzer = Mock()
        mock_repository = Mock()
        mock_ws_handler = Mock()

        confirmer = IntentConfirmer(
            analyzer=mock_analyzer,
            repository=mock_repository,
            ws_handler=mock_ws_handler,
        )
        return confirmer

    @pytest.mark.asyncio
    async def test_start_confirmation_with_empty_recording_id(self, confirmer):
        """测试空录制 ID"""
        # Mock 分析器返回 None（录制不存在）
        confirmer.analyzer.analyze_intent = AsyncMock(return_value=None)

        result = await confirmer.start_confirmation("")

        assert result is None

    @pytest.mark.asyncio
    async def test_start_confirmation_with_invalid_recording_id(self, confirmer):
        """测试无效的录制 ID"""
        confirmer.analyzer.analyze_intent = AsyncMock(return_value=None)

        result = await confirmer.start_confirmation("non_existent_id")

        assert result is None

    @pytest.mark.asyncio
    async def test_start_confirmation_with_llm_timeout(self, confirmer):
        """测试 LLM API 超时"""
        # Mock 分析器抛出超时异常
        confirmer.analyzer.analyze_intent = AsyncMock(
            side_effect=asyncio.TimeoutError("LLM API timeout")
        )

        with pytest.raises(asyncio.TimeoutError):
            await confirmer.start_confirmation("test_recording_id")

    @pytest.mark.asyncio
    async def test_start_confirmation_with_llm_error(self, confirmer):
        """测试 LLM API 返回错误"""
        # Mock 分析器抛出通用异常
        confirmer.analyzer.analyze_intent = AsyncMock(
            side_effect=Exception("LLM API error")
        )

        with pytest.raises(Exception):
            await confirmer.start_confirmation("test_recording_id")

    @pytest.mark.asyncio
    async def test_process_user_feedback_with_empty_message(self, confirmer):
        """测试空用户消息"""
        # 创建一个活跃会话
        intent = IntentAnalysisModel(
            core_operations="测试操作",
            target="测试目标",
            business_scenario="测试场景",
            expected_results="测试结果",
        )
        state = ConfirmationState(intent)
        confirmer.active_sessions["test_intent_id"] = state

        # 处理空消息
        result = await confirmer.process_user_feedback(
            "test_intent_id", "", "confirm"
        )

        # 应该返回原始意图（因为没有修改）
        assert result == intent

    @pytest.mark.asyncio
    async def test_process_user_feedback_with_non_existent_session(self, confirmer):
        """测试不存在的会话 ID"""
        result = await confirmer.process_user_feedback(
            "non_existent_id", "测试消息", "refine"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_process_user_feedback_exceeds_max_turns(self, confirmer):
        """测试超过最大轮次"""
        intent = IntentAnalysisModel(
            core_operations="测试操作",
            target="测试目标",
            business_scenario="测试场景",
            expected_results="测试结果",
        )
        state = ConfirmationState(intent)
        state.max_turns = 1
        state.current_turn = 1  # 已经达到最大轮次

        confirmer.active_sessions["test_intent_id"] = state

        # 尝试继续优化（应该失败）
        result = await confirmer.process_user_feedback(
            "test_intent_id", "继续优化", "refine"
        )

        # 应该返回当前意图，但不能继续
        assert result == intent
        assert not state.can_continue()

    @pytest.mark.asyncio
    async def test_concurrent_confirmation_sessions(self, confirmer):
        """测试并发确认会话"""
        # Mock 分析器返回不同的意图
        intent1 = IntentAnalysisModel(
            core_operations="操作1",
            target="目标1",
            business_scenario="场景1",
            expected_results="结果1",
        )
        intent2 = IntentAnalysisModel(
            core_operations="操作2",
            target="目标2",
            business_scenario="场景2",
            expected_results="结果2",
        )

        confirmer.analyzer.analyze_intent = AsyncMock(side_effect=[intent1, intent2])

        # 并发启动两个确认会话
        results = await asyncio.gather(
            confirmer.start_confirmation("recording1"),
            confirmer.start_confirmation("recording2"),
        )

        assert len(results) == 2
        assert results[0].core_operations == "操作1"
        assert results[1].core_operations == "操作2"
        assert len(confirmer.active_sessions) == 2

    def test_cleanup_stale_sessions_with_empty_sessions(self, confirmer):
        """测试清理空的会话列表"""
        confirmer.active_sessions = {}

        cleaned = confirmer.cleanup_stale_sessions(max_age_seconds=3600)

        assert cleaned == 0
        assert len(confirmer.active_sessions) == 0

    def test_cleanup_stale_sessions_with_no_stale_sessions(self, confirmer):
        """测试没有过期会话的情况"""
        intent = IntentAnalysisModel(
            core_operations="测试",
            target="测试",
            business_scenario="测试",
            expected_results="测试",
        )
        state = ConfirmationState(intent)
        state.last_activity = time.time()  # 刚刚活动

        confirmer.active_sessions["test_id"] = state

        cleaned = confirmer.cleanup_stale_sessions(max_age_seconds=3600)

        assert cleaned == 0
        assert len(confirmer.active_sessions) == 1

    def test_cleanup_stale_sessions_with_all_stale(self, confirmer):
        """测试所有会话都过期的情况"""
        import time

        intent = IntentAnalysisModel(
            core_operations="测试",
            target="测试",
            business_scenario="测试",
            expected_results="测试",
        )
        state = ConfirmationState(intent)
        state.last_activity = time.time() - 7200  # 2 小时前

        confirmer.active_sessions["test_id"] = state

        cleaned = confirmer.cleanup_stale_sessions(max_age_seconds=3600)

        assert cleaned == 1
        assert len(confirmer.active_sessions) == 0

    def test_get_active_session_count_with_empty_sessions(self, confirmer):
        """测试获取空会话数量"""
        confirmer.active_sessions = {}

        count = confirmer.get_active_session_count()

        assert count == 0

    def test_get_active_session_count_with_multiple_sessions(self, confirmer):
        """测试获取多个会话数量"""
        for i in range(5):
            intent = IntentAnalysisModel(
                core_operations=f"操作{i}",
                target=f"目标{i}",
                business_scenario=f"场景{i}",
                expected_results=f"结果{i}",
            )
            state = ConfirmationState(intent)
            confirmer.active_sessions[f"intent_{i}"] = state

        count = confirmer.get_active_session_count()

        assert count == 5

    @pytest.mark.asyncio
    async def test_handle_confirm_intent_with_invalid_action(self, confirmer):
        """测试无效的操作类型"""
        intent = IntentAnalysisModel(
            core_operations="测试",
            target="测试",
            business_scenario="测试",
            expected_results="测试",
        )
        state = ConfirmationState(intent)
        confirmer.active_sessions["test_intent_id"] = state

        # 无效的操作
        message = WebSocketMessage(
            type="confirm_intent",
            data={"intent_id": "test_intent_id", "action": "invalid_action"},
        )

        # 应该不抛出异常，但也不改变状态
        await confirmer._handle_confirm_intent(message)

        assert state.state == "pending_confirmation"

    @pytest.mark.asyncio
    async def test_handle_confirm_intent_with_missing_intent_id(self, confirmer):
        """测试缺少 intent_id 的消息"""
        message = WebSocketMessage(
            type="confirm_intent",
            data={"action": "confirm"},  # 缺少 intent_id
        )

        # 应该不抛出异常
        await confirmer._handle_confirm_intent(message)

        assert len(confirmer.active_sessions) == 0
