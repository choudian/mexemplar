"""
Intent 确认完整流程集成测试

测试范围：
1. 端到端流程测试（录制 → 分析 → 确认 → 生成）
2. WebSocket 通信测试（前后端集成）
3. 多轮对话测试
4. 状态机测试
5. 异常处理测试
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
from typing import Dict, Any

from src.business.intent.intent_confirmer import IntentConfirmer, ConfirmationState
from src.business.intent.intent_analyzer import IntentAnalyzer
from src.business.intent.intent_repository import IntentRepository
from src.business.intent.intent_models import Intent as IntentDBModel, IntentStatus
from src.business.ai.prompts.intent_analysis_models import (
    Intent as IntentAnalysisModel,
    IntentAnalysisResult,
    CoreOperation,
    SuggestedParameter,
    ParameterType,
    IntentConfirmationTurn,
)
from src.communication.websocket_handler import WebSocketHandler
from src.communication.websocket_client import WebSocketClient
from src.communication.message_types import (
    MessageType,
    WebSocketMessage,
    IntentConfirmationData,
)
from src.data.database import DatabaseManager


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def db_manager():
    """创建测试数据库管理器"""
    db_manager = DatabaseManager(":memory:")  # 使用内存数据库

    # 初始化数据库
    db_manager.initialize()

    yield db_manager

    # 清理
    db_manager.close()


@pytest.fixture
def intent_repository(db_manager):
    """创建意图仓库"""
    return IntentRepository(db_manager)


@pytest.fixture
def mock_llm_client():
    """模拟 LLM 客户端"""
    client = Mock()
    client.chat = AsyncMock()

    # 默认响应
    client.chat.return_value = {
        "core_operations": [
            {"operation": "打开网站", "action_index": 0, "importance": 1.0},
            {"operation": "输入用户名和密码", "action_index": 1, "importance": 1.0},
            {"operation": "点击登录按钮", "action_index": 2, "importance": 1.0},
        ],
        "target": "示例网站",
        "business_scenario": "auth - 用户登录",
        "expected_results": ["成功登录系统"],
        "confidence": 0.85,
        "reasoning": "基于录制数据分析，用户执行了登录操作",
    }

    return client


@pytest.fixture
def intent_analyzer(mock_llm_client):
    """创建意图分析器"""
    return IntentAnalyzer(llm_client=mock_llm_client)


@pytest.fixture
async def websocket_handler():
    """创建 WebSocket 处理器（使用测试端口）"""
    handler = WebSocketHandler(host="127.0.0.1", port=8766)

    # 启动服务器
    await handler.start()

    yield handler

    # 停止服务器
    await handler.stop()


@pytest.fixture
def intent_confirmer(intent_analyzer, intent_repository, websocket_handler):
    """创建意图确认器"""
    return IntentConfirmer(
        analyzer=intent_analyzer,
        repository=intent_repository,
        ws_handler=websocket_handler,
    )


@pytest.fixture
def sample_recording_data():
    """示例录制数据"""
    return {
        "recording_id": "test-recording-001",
        "actions": [
            {
                "action_type": "goto",
                "url": "https://example.com",
                "timestamp": 1234567890.0,
            },
            {
                "action_type": "input",
                "selector": "#username",
                "value": "testuser",
                "timestamp": 1234567891.0,
            },
            {
                "action_type": "input",
                "selector": "#password",
                "value": "********",
                "timestamp": 1234567892.0,
            },
            {
                "action_type": "click",
                "selector": "#login-button",
                "timestamp": 1234567893.0,
            },
        ],
        "metadata": {
            "start_time": 1234567890.0,
            "end_time": 1234567895.0,
            "recording_mode": "browser",
        },
    }


@pytest.fixture
def sample_analysis_result():
    """示例分析结果"""
    return IntentAnalysisResult(
        core_operations=[
            CoreOperation(
                operation="打开网站 https://example.com",
                action_index=0,
                importance=1.0,
                parameters={"url": "https://example.com"},
            ),
            CoreOperation(
                operation="输入用户名",
                action_index=1,
                importance=1.0,
                parameters={"selector": "#username"},
            ),
            CoreOperation(
                operation="输入密码",
                action_index=2,
                importance=1.0,
                parameters={"selector": "#password"},
            ),
            CoreOperation(
                operation="点击登录按钮",
                action_index=3,
                importance=1.0,
                parameters={"selector": "#login-button"},
            ),
        ],
        target="Example 网站",
        business_scenario="auth - 用户登录",
        expected_results=[
            "成功登录到系统",
            "显示用户个人中心",
        ],
        suggested_parameters=[
            SuggestedParameter(
                name="username",
                type=ParameterType.TEXT,
                description="用户名",
                required=True,
            ),
            SuggestedParameter(
                name="password",
                type=ParameterType.TEXT,
                description="密码",
                required=True,
            ),
        ],
        confidence=0.85,
        reasoning="用户在示例网站上执行了登录操作，包括输入用户名、密码和点击登录按钮",
        recording_id="test-recording-001",
        status="pending_confirmation",
    )


# ============================================================================
# 测试场景 1：简单意图确认
# ============================================================================


class TestScenario1_SimpleConfirmation:
    """测试场景 1：简单意图确认

    流程：
    1. 录制完成
    2. 启动意图分析
    3. 发送确认请求
    4. 用户确认
    5. 保存确认结果
    """

    @pytest.mark.asyncio
    async def test_simple_confirmation_flow(
        self, intent_confirmer, intent_repository, sample_analysis_result, websocket_handler
    ):
        """测试简单确认流程"""
        # 1. 创建意图
        intent = IntentAnalysisModel(
            intent_id="test-intent-001",
            recording_id="test-recording-001",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        # 2. 保存到数据库
        db_intent = IntentDBModel(
            intent_id=intent.intent_id,
            recording_id=intent.recording_id,
            core_operations=[op.operation for op in intent.analysis_result.core_operations],
            target=intent.analysis_result.target,
            business_scenario=intent.analysis_result.business_scenario,
            expected_results=intent.analysis_result.expected_results,
            status=IntentStatus.PENDING_CONFIRMATION,
            confirmed_operations=[],
            user_message=None,
            analysis_confidence=intent.analysis_result.confidence,
            llm_model_used=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            confirmed_at=None,
        )
        intent_repository.create(db_intent)

        # 3. 创建确认会话
        intent_confirmer.active_sessions[intent.intent_id] = ConfirmationState(intent)

        # 4. 模拟用户确认
        confirmed_operations = [
            "打开网站 https://example.com",
            "输入用户名",
            "输入密码",
            "点击登录按钮",
        ]

        # 5. 确认意图
        result = await intent_confirmer.confirm_intent(intent.intent_id, confirmed_operations)

        # 6. 验证
        assert result.intent_id == intent.intent_id
        assert result.status == "confirmed"
        assert result.confirmed_at is not None

        # 验证数据库已更新
        saved_intent = intent_repository.get_by_id(intent.intent_id)
        assert saved_intent.status == IntentStatus.CONFIRMED
        assert saved_intent.confirmed_operations == confirmed_operations
        assert saved_intent.confirmed_at is not None

        # 验证会话已清理
        assert intent.intent_id not in intent_confirmer.active_sessions

    @pytest.mark.asyncio
    async def test_simple_confirmation_with_websocket_message(
        self, intent_confirmer, intent_repository, sample_analysis_result
    ):
        """测试通过 WebSocket 消息确认意图"""
        # 1. 创建并保存意图
        intent = IntentAnalysisModel(
            intent_id="test-intent-002",
            recording_id="test-recording-002",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        db_intent = IntentDBModel(
            intent_id=intent.intent_id,
            recording_id=intent.recording_id,
            core_operations=[op.operation for op in intent.analysis_result.core_operations],
            target=intent.analysis_result.target,
            business_scenario=intent.analysis_result.business_scenario,
            expected_results=intent.analysis_result.expected_results,
            status=IntentStatus.PENDING_CONFIRMATION,
            confirmed_operations=[],
            user_message=None,
            analysis_confidence=intent.analysis_result.confidence,
            llm_model_used=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            confirmed_at=None,
        )
        intent_repository.create(db_intent)
        intent_confirmer.active_sessions[intent.intent_id] = ConfirmationState(intent)

        # 2. 创建确认消息
        msg = WebSocketMessage(
            type=MessageType.CONFIRM_INTENT,
            data={
                "intent_id": intent.intent_id,
                "action": "confirm",
                "confirmed_operations": [
                    "打开网站 https://example.com",
                    "输入用户名",
                    "输入密码",
                    "点击登录按钮",
                ],
            },
        )

        # 3. 处理消息
        result = await intent_confirmer._handle_confirm_intent(msg)

        # 4. 验证
        assert result["status"] == "confirmed"
        assert result["intent_id"] == intent.intent_id

        # 验证数据库
        saved_intent = intent_repository.get_by_id(intent.intent_id)
        assert saved_intent.status == IntentStatus.CONFIRMED


# ============================================================================
# 测试场景 2：多轮对话优化
# ============================================================================


class TestScenario2_MultiTurnRefinement:
    """测试场景 2：多轮对话优化

    流程：
    1. 意图分析完成
    2. 用户反馈问题
    3. AI 优化意图
    4. 更新 UI
    5. 用户确认
    """

    @pytest.mark.asyncio
    async def test_multi_turn_refinement(
        self, intent_confirmer, intent_analyzer, intent_repository, sample_analysis_result
    ):
        """测试多轮对话优化"""
        # 1. 创建意图
        intent = IntentAnalysisModel(
            intent_id="test-intent-003",
            recording_id="test-recording-003",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        intent_confirmer.active_sessions[intent.intent_id] = ConfirmationState(intent)

        # 2. 第一次反馈
        feedback_1 = "请把'输入用户名'改为'输入邮箱'"

        # 模拟分析器优化
        refined_result_1 = IntentAnalysisResult(
            core_operations=[
                CoreOperation(operation="打开网站 https://example.com", action_index=0),
                CoreOperation(operation="输入邮箱", action_index=1),  # 修改
                CoreOperation(operation="输入密码", action_index=2),
                CoreOperation(operation="点击登录按钮", action_index=3),
            ],
            target="Example 网站",
            business_scenario="auth - 用户登录",
            expected_results=["成功登录到系统"],
            suggested_parameters=[],
            confidence=0.88,
            reasoning="根据用户反馈，将输入用户名改为输入邮箱",
            recording_id="test-recording-003",
            status="pending_confirmation",
        )

        intent_analyzer.refine_intent = AsyncMock(return_value=refined_result_1)
        intent_analyzer.add_confirmation_turn = AsyncMock(
            return_value=IntentConfirmationTurn(
                turn_id="turn-1",
                intent_id=intent.intent_id,
                user_feedback=feedback_1,
                assistant_response=refined_result_1.reasoning,
                updated_intent=refined_result_1,
                timestamp=time.time(),
            )
        )

        # 处理反馈
        result_1 = await intent_confirmer.process_user_feedback(intent.intent_id, feedback_1)

        # 验证第一轮
        assert result_1.intent_id == intent.intent_id
        assert result_1.analysis_result.core_operations[1].operation == "输入邮箱"
        assert result_1.analysis_result.confidence == 0.88

        session = intent_confirmer.active_sessions[intent.intent_id]
        assert session.current_turn == 1
        assert session.state == "refining"

        # 3. 第二次反馈
        feedback_2 = "请添加'验证邮箱格式'这个步骤"

        refined_result_2 = IntentAnalysisResult(
            core_operations=[
                CoreOperation(operation="打开网站 https://example.com", action_index=0),
                CoreOperation(operation="输入邮箱", action_index=1),
                CoreOperation(operation="验证邮箱格式", action_index=2),  # 新增
                CoreOperation(operation="输入密码", action_index=3),
                CoreOperation(operation="点击登录按钮", action_index=4),
            ],
            target="Example 网站",
            business_scenario="auth - 用户登录",
            expected_results=["成功登录到系统"],
            suggested_parameters=[],
            confidence=0.92,
            reasoning="根据用户反馈，添加邮箱格式验证步骤",
            recording_id="test-recording-003",
            status="pending_confirmation",
        )

        intent_analyzer.refine_intent = AsyncMock(return_value=refined_result_2)
        intent_analyzer.add_confirmation_turn = AsyncMock(
            return_value=IntentConfirmationTurn(
                turn_id="turn-2",
                intent_id=intent.intent_id,
                user_feedback=feedback_2,
                assistant_response=refined_result_2.reasoning,
                updated_intent=refined_result_2,
                timestamp=time.time(),
            )
        )

        # 处理第二次反馈
        result_2 = await intent_confirmer.process_user_feedback(intent.intent_id, feedback_2)

        # 验证第二轮
        assert result_2.analysis_result.core_operations[2].operation == "验证邮箱格式"
        assert result_2.analysis_result.confidence == 0.92

        session = intent_confirmer.active_sessions[intent.intent_id]
        assert session.current_turn == 2

        # 4. 最终确认
        confirmed_operations = [
            "打开网站 https://example.com",
            "输入邮箱",
            "验证邮箱格式",
            "输入密码",
            "点击登录按钮",
        ]

        final_result = await intent_confirmer.confirm_intent(intent.intent_id, confirmed_operations)

        # 验证最终结果
        assert final_result.status == "confirmed"
        assert len(final_result.analysis_result.core_operations) == 5

    @pytest.mark.asyncio
    async def test_max_turns_limit(self, intent_confirmer, sample_analysis_result):
        """测试超过最大对话轮数"""
        intent = IntentAnalysisModel(
            intent_id="test-intent-004",
            recording_id="test-recording-004",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=3,  # 设置最大 3 轮
            created_at=time.time(),
            updated_at=time.time(),
        )

        intent_confirmer.active_sessions[intent.intent_id] = ConfirmationState(intent)

        # 推进到最大轮数
        session = intent_confirmer.active_sessions[intent.intent_id]
        for _ in range(3):
            session.advance_turn()

        # 尝试第 4 次对话，应该失败
        with pytest.raises(ValueError, match="已达到最大对话轮数"):
            await intent_confirmer.process_user_feedback(intent.intent_id, "测试反馈")


# ============================================================================
# 测试场景 3：取消确认
# ============================================================================


class TestScenario3_Cancellation:
    """测试场景 3：取消确认"""

    @pytest.mark.asyncio
    async def test_cancel_confirmation(
        self, intent_confirmer, intent_repository, sample_analysis_result
    ):
        """测试取消确认"""
        # 1. 创建意图
        intent = IntentAnalysisModel(
            intent_id="test-intent-005",
            recording_id="test-recording-005",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        db_intent = IntentDBModel(
            intent_id=intent.intent_id,
            recording_id=intent.recording_id,
            core_operations=[op.operation for op in intent.analysis_result.core_operations],
            target=intent.analysis_result.target,
            business_scenario=intent.analysis_result.business_scenario,
            expected_results=intent.analysis_result.expected_results,
            status=IntentStatus.PENDING_CONFIRMATION,
            confirmed_operations=[],
            user_message=None,
            analysis_confidence=intent.analysis_result.confidence,
            llm_model_used=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            confirmed_at=None,
        )
        intent_repository.create(db_intent)
        intent_confirmer.active_sessions[intent.intent_id] = ConfirmationState(intent)

        # 2. 取消确认
        result = await intent_confirmer.cancel_confirmation(intent.intent_id)

        # 3. 验证
        assert result.intent_id == intent.intent_id
        assert result.status == "cancelled"

        # 验证数据库
        saved_intent = intent_repository.get_by_id(intent.intent_id)
        assert saved_intent.status == IntentStatus.CANCELLED

        # 验证会话已清理
        assert intent.intent_id not in intent_confirmer.active_sessions

    @pytest.mark.asyncio
    async def test_cancel_via_websocket_message(
        self, intent_confirmer, intent_repository, sample_analysis_result
    ):
        """测试通过 WebSocket 消息取消确认"""
        # 1. 创建意图
        intent = IntentAnalysisModel(
            intent_id="test-intent-006",
            recording_id="test-recording-006",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        intent_confirmer.active_sessions[intent.intent_id] = ConfirmationState(intent)

        # 2. 发送取消消息
        msg = WebSocketMessage(
            type=MessageType.CONFIRM_INTENT,
            data={
                "intent_id": intent.intent_id,
                "action": "cancel",
            },
        )

        # 3. 处理消息
        result = await intent_confirmer._handle_confirm_intent(msg)

        # 4. 验证
        assert result["status"] == "cancelled"
        assert result["intent_id"] == intent.intent_id


# ============================================================================
# WebSocket 通信测试
# ============================================================================


class TestWebSocketCommunication:
    """WebSocket 通信测试"""

    @pytest.mark.asyncio
    async def test_broadcast_confirmation_request(
        self, intent_confirmer, websocket_handler, sample_analysis_result
    ):
        """测试广播确认请求"""
        # 创建意图
        intent = IntentAnalysisModel(
            intent_id="test-intent-007",
            recording_id="test-recording-007",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        # 发送确认请求
        await intent_confirmer._send_confirmation_request(intent)

        # 验证 broadcast 被调用
        websocket_handler.broadcast.assert_called_once()

        # 获取调用参数
        call_args = websocket_handler.broadcast.call_args
        msg = call_args[0][0]

        assert msg.type == MessageType.CONFIRM_INTENT
        assert msg.data["intent_id"] == intent.intent_id
        assert "core_operations" in msg.data
        assert "target" in msg.data
        assert "business_scenario" in msg.data

    @pytest.mark.asyncio
    async def test_broadcast_intent_update(
        self, intent_confirmer, websocket_handler, sample_analysis_result
    ):
        """测试广播意图更新"""
        intent = IntentAnalysisModel(
            intent_id="test-intent-008",
            recording_id="test-recording-008",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        turn = IntentConfirmationTurn(
            turn_id="turn-1",
            intent_id=intent.intent_id,
            user_feedback="测试反馈",
            assistant_response="已更新",
            updated_intent=sample_analysis_result,
            timestamp=time.time(),
        )

        # 发送更新
        await intent_confirmer._send_intent_update(intent, turn)

        # 验证
        websocket_handler.broadcast.assert_called_once()

        call_args = websocket_handler.broadcast.call_args
        msg = call_args[0][0]

        assert msg.type == MessageType.INTENT_UPDATED
        assert msg.data["intent_id"] == intent.intent_id
        assert "turn_number" in msg.data

    @pytest.mark.asyncio
    async def test_broadcast_confirmation_success(
        self, intent_confirmer, websocket_handler, sample_analysis_result
    ):
        """测试广播确认成功"""
        intent = IntentAnalysisModel(
            intent_id="test-intent-009",
            recording_id="test-recording-009",
            analysis_result=sample_analysis_result,
            status="confirmed",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
            confirmed_at=time.time(),
        )

        # 发送确认成功
        await intent_confirmer._send_confirmation_success(intent)

        # 验证
        websocket_handler.broadcast.assert_called_once()

        call_args = websocket_handler.broadcast.call_args
        msg = call_args[0][0]

        assert msg.type == MessageType.INTENT_CONFIRMED
        assert msg.data["intent_id"] == intent.intent_id
        assert msg.data["status"] == "confirmed"


# ============================================================================
# 状态机测试
# ============================================================================


class TestConfirmationStateMachine:
    """确认状态机测试"""

    def test_state_transitions(self, sample_analysis_result):
        """测试状态转换"""
        intent = IntentAnalysisModel(
            intent_id="test-intent-010",
            recording_id="test-recording-010",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        state = ConfirmationState(intent)

        # 初始状态
        assert state.state == "pending_confirmation"
        assert state.can_continue() is True

        # 转换到 refining
        state.start_refining()
        assert state.state == "refining"
        assert state.can_continue() is True

        # 推进轮次
        state.advance_turn()
        assert state.current_turn == 1
        assert state.can_continue() is True

        # 转换到 confirmed
        state.confirm()
        assert state.state == "confirmed"
        assert state.can_continue() is False

    def test_max_turns_enforcement(self, sample_analysis_result):
        """测试最大轮数强制执行"""
        intent = IntentAnalysisModel(
            intent_id="test-intent-011",
            recording_id="test-recording-011",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=3,
            created_at=time.time(),
            updated_at=time.time(),
        )

        state = ConfirmationState(intent)

        # 推进到最大轮数
        for i in range(3):
            assert state.can_continue() is True
            state.advance_turn()
            assert state.current_turn == i + 1

        # 达到最大轮数后不能再继续
        assert state.can_continue() is False
        assert state.current_turn == 3

        # 尝试推进会失败
        result = state.advance_turn()
        assert result is False
        assert state.current_turn == 3


# ============================================================================
# 异常处理测试
# ============================================================================


class TestErrorHandling:
    """异常处理测试"""

    @pytest.mark.asyncio
    async def test_confirm_nonexistent_intent(self, intent_confirmer):
        """测试确认不存在的意图"""
        with pytest.raises(ValueError, match="未找到意图"):
            await intent_confirmer.confirm_intent("nonexistent-intent-id")

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_intent(self, intent_confirmer):
        """测试取消不存在的意图"""
        with pytest.raises(ValueError, match="未找到活跃的确认会话"):
            await intent_confirmer.cancel_confirmation("nonexistent-intent-id")

    @pytest.mark.asyncio
    async def test_feedback_for_nonexistent_session(self, intent_confirmer):
        """测试对不存在的会话发送反馈"""
        with pytest.raises(ValueError, match="未找到活跃的确认会话"):
            await intent_confirmer.process_user_feedback("nonexistent-intent-id", "测试")

    @pytest.mark.asyncio
    async def test_handle_invalid_message_action(self, intent_confirmer, sample_analysis_result):
        """测试处理无效的消息动作"""
        intent = IntentAnalysisModel(
            intent_id="test-intent-012",
            recording_id="test-recording-012",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        intent_confirmer.active_sessions[intent.intent_id] = ConfirmationState(intent)

        msg = WebSocketMessage(
            type=MessageType.CONFIRM_INTENT,
            data={
                "intent_id": intent.intent_id,
                "action": "invalid_action",  # 无效动作
            },
        )

        with pytest.raises(ValueError, match="未知的 action"):
            await intent_confirmer._handle_confirm_intent(msg)

    @pytest.mark.asyncio
    async def test_refine_without_feedback(self, intent_confirmer, sample_analysis_result):
        """测试优化时缺少反馈"""
        intent = IntentAnalysisModel(
            intent_id="test-intent-013",
            recording_id="test-recording-013",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        intent_confirmer.active_sessions[intent.intent_id] = ConfirmationState(intent)

        msg = WebSocketMessage(
            type=MessageType.CONFIRM_INTENT,
            data={
                "intent_id": intent.intent_id,
                "action": "refine",
                # 缺少 feedback 字段
            },
        )

        with pytest.raises(ValueError, match="缺少 feedback"):
            await intent_confirmer._handle_confirm_intent(msg)


# ============================================================================
# 数据持久化测试
# ============================================================================


class TestDataPersistence:
    """数据持久化测试"""

    @pytest.mark.asyncio
    async def test_save_and_load_intent(
        self, intent_confirmer, intent_repository, sample_analysis_result
    ):
        """测试保存和加载意图"""
        # 1. 创建意图
        intent = IntentAnalysisModel(
            intent_id="test-intent-014",
            recording_id="test-recording-014",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        # 2. 转换为数据库模型并保存
        db_intent = intent_confirmer._business_to_db_model(intent)
        intent_repository.create(db_intent)

        # 3. 从数据库加载
        loaded_intent = intent_repository.get_by_id(intent.intent_id)

        # 4. 转换回业务模型
        business_intent = intent_confirmer._db_to_business_model(loaded_intent)

        # 5. 验证
        assert business_intent.intent_id == intent.intent_id
        assert business_intent.recording_id == intent.recording_id
        assert len(business_intent.analysis_result.core_operations) == len(
            intent.analysis_result.core_operations
        )
        assert business_intent.analysis_result.target == intent.analysis_result.target
        assert business_intent.analysis_result.business_scenario == intent.analysis_result.business_scenario

    @pytest.mark.asyncio
    async def test_update_intent_status(
        self, intent_confirmer, intent_repository, sample_analysis_result
    ):
        """测试更新意图状态"""
        # 1. 创建并保存意图
        intent = IntentAnalysisModel(
            intent_id="test-intent-015",
            recording_id="test-recording-015",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        db_intent = intent_confirmer._business_to_db_model(intent)
        intent_repository.create(db_intent)

        # 2. 更新状态
        intent.status = "confirmed"
        intent.confirmed_at = time.time()

        db_intent_updated = intent_confirmer._business_to_db_model(intent)
        db_intent_updated.status = IntentStatus.CONFIRMED
        db_intent_updated.confirmed_at = datetime.fromtimestamp(intent.confirmed_at)
        intent_repository.update(db_intent_updated)

        # 3. 验证更新
        updated_intent = intent_repository.get_by_id(intent.intent_id)
        assert updated_intent.status == IntentStatus.CONFIRMED
        assert updated_intent.confirmed_at is not None


# ============================================================================
# 会话管理测试
# ============================================================================


class TestSessionManagement:
    """会话管理测试"""

    def test_get_active_session_count(self, intent_confirmer, sample_analysis_result):
        """测试获取活跃会话数量"""
        assert intent_confirmer.get_active_session_count() == 0

        # 添加会话
        intent1 = IntentAnalysisModel(
            intent_id="test-intent-016",
            recording_id="test-recording-016",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        intent2 = IntentAnalysisModel(
            intent_id="test-intent-017",
            recording_id="test-recording-017",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        intent_confirmer.active_sessions["test-intent-016"] = ConfirmationState(intent1)
        intent_confirmer.active_sessions["test-intent-017"] = ConfirmationState(intent2)

        assert intent_confirmer.get_active_session_count() == 2

    def test_cleanup_stale_sessions(self, intent_confirmer, sample_analysis_result):
        """测试清理超时会话"""
        # 创建会话
        intent1 = IntentAnalysisModel(
            intent_id="test-intent-018",
            recording_id="test-recording-018",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        intent2 = IntentAnalysisModel(
            intent_id="test-intent-019",
            recording_id="test-recording-019",
            analysis_result=sample_analysis_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        session1 = ConfirmationState(intent1)
        session2 = ConfirmationState(intent2)

        intent_confirmer.active_sessions["test-intent-018"] = session1
        intent_confirmer.active_sessions["test-intent-019"] = session2

        # 修改第一个会话的活动时间（使其超时）
        session1.last_activity = time.time() - 4000  # 超过默认 3600 秒

        # 清理
        intent_confirmer.cleanup_stale_sessions()

        # 验证
        assert intent_confirmer.get_active_session_count() == 1
        assert "test-intent-018" not in intent_confirmer.active_sessions
        assert "test-intent-019" in intent_confirmer.active_sessions
