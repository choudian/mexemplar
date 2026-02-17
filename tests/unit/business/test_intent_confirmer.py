"""
意图确认器单元测试
"""

import pytest
from unittest.mock import Mock, AsyncMock
from datetime import datetime

from src.business.intent.intent_confirmer import IntentConfirmer, ConfirmationState
from src.business.ai.prompts.intent_analysis_models import (
    Intent as IntentAnalysisModel,
    IntentAnalysisResult,
    CoreOperation,
    SuggestedParameter,
    ParameterType,
)
from src.business.intent.intent_models import Intent as IntentDBModel, IntentStatus
from src.communication.websocket_handler import WebSocketHandler
from src.communication.message_types import MessageType, WebSocketMessage


@pytest.fixture
def mock_analyzer():
    """模拟意图分析器"""
    analyzer = Mock()
    analyzer.create_intent_from_recording = AsyncMock()
    analyzer.refine_intent = AsyncMock()
    analyzer.add_confirmation_turn = AsyncMock()
    return analyzer


@pytest.fixture
def mock_repository():
    """模拟意图仓库"""
    repo = Mock()
    repo.create = Mock()
    repo.get_by_id = Mock()
    repo.get_by_recording_id = Mock()
    repo.update = Mock()
    repo.delete = Mock()
    return repo


@pytest.fixture
def mock_ws_handler():
    """模拟 WebSocket 处理器"""
    handler = Mock(spec=WebSocketHandler)
    handler.register_handler = Mock()
    handler.broadcast = AsyncMock()
    return handler


@pytest.fixture
def sample_analysis_result():
    """示例分析结果"""
    return IntentAnalysisResult(
        core_operations=[
            CoreOperation(
                operation="打开网站",
                action_index=0,
                importance=1.0,
            ),
            CoreOperation(
                operation="输入用户名和密码",
                action_index=1,
                importance=1.0,
            ),
            CoreOperation(
                operation="点击登录按钮",
                action_index=2,
                importance=1.0,
            ),
        ],
        target="示例网站",
        business_scenario="auth - 用户登录",
        expected_results=["成功登录系统"],
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
        reasoning="用户在网站上执行了登录操作",
        recording_id="test-recording-1",
        status="pending_confirmation",
    )


@pytest.fixture
def sample_intent(sample_analysis_result):
    """示例意图"""
    return IntentAnalysisModel(
        intent_id="test-intent-1",
        recording_id="test-recording-1",
        analysis_result=sample_analysis_result,
        status="pending_confirmation",
        max_turns=5,
        created_at=1234567890.0,
        updated_at=1234567890.0,
    )


class TestConfirmationState:
    """测试确认状态机"""

    def test_initial_state(self, sample_intent):
        """测试初始状态"""
        state = ConfirmationState(sample_intent)

        assert state.intent == sample_intent
        assert state.current_turn == 0
        assert state.max_turns == 5
        assert state.state == "pending_confirmation"
        assert state.can_continue() is True

    def test_advance_turn(self, sample_intent):
        """测试推进对话轮次"""
        state = ConfirmationState(sample_intent)

        # 推进 5 轮（允许推进到第 5 轮，但第 5 轮后不能再继续）
        for i in range(5):
            can_continue_before = state.can_continue()
            advanced = state.advance_turn()

            # 前 4 轮可以继续
            if i < 4:
                assert can_continue_before is True
                assert advanced is True
                assert state.current_turn == i + 1
            # 第 5 轮：推进前可以继续，推进后不能再继续
            else:
                assert can_continue_before is True  # 推进前还可以继续
                assert advanced is True  # 这次推进还是成功的
                assert state.current_turn == 5

        # 第 5 轮后不能再继续
        assert state.current_turn == 5
        assert state.can_continue() is False

        # 尝试第 6 次推进会失败
        can_continue_before = state.can_continue()
        advanced = state.advance_turn()
        assert can_continue_before is False
        assert advanced is False
        assert state.current_turn == 5  # 没有增加

    def test_confirm(self, sample_intent):
        """测试确认意图"""
        state = ConfirmationState(sample_intent)

        state.confirm()
        assert state.state == "confirmed"
        assert state.can_continue() is False

    def test_cancel(self, sample_intent):
        """测试取消意图"""
        state = ConfirmationState(sample_intent)

        state.cancel()
        assert state.state == "cancelled"
        assert state.can_continue() is False

    def test_start_refining(self, sample_intent):
        """测试开始优化流程"""
        state = ConfirmationState(sample_intent)

        state.start_refining()
        assert state.state == "refining"
        assert state.can_continue() is True


class TestIntentConfirmer:
    """测试意图确认器"""

    @pytest.fixture
    def confirmer(self, mock_analyzer, mock_repository, mock_ws_handler):
        """创建确认器实例"""
        return IntentConfirmer(
            analyzer=mock_analyzer,
            repository=mock_repository,
            ws_handler=mock_ws_handler,
        )

    def test_initialization(self, confirmer, mock_ws_handler):
        """测试初始化"""
        assert confirmer.analyzer is not None
        assert confirmer.repository is not None
        assert confirmer.ws_handler is not None
        assert confirmer.active_sessions == {}

        # 检查是否注册了处理器
        mock_ws_handler.register_handler.assert_called_once_with(
            MessageType.CONFIRM_INTENT, confirmer._handle_confirm_intent
        )

    @pytest.mark.asyncio
    async def test_start_confirmation_new_intent(
        self, confirmer, mock_analyzer, mock_repository, mock_ws_handler, sample_intent
    ):
        """测试启动新意图的确认流程"""
        recording_id = "test-recording-1"

        # 模拟不存在已确认的意图
        mock_repository.get_by_recording_id.return_value = None

        # 模拟分析器返回意图
        mock_analyzer.create_intent_from_recording.return_value = sample_intent

        # 模拟仓库创建成功
        mock_repository.create.return_value = None

        # 执行
        result = await confirmer.start_confirmation(recording_id)

        # 验证
        assert result.intent_id == sample_intent.intent_id
        assert result.recording_id == recording_id
        assert result.status == "pending_confirmation"

        # 验证会话已创建
        assert result.intent_id in confirmer.active_sessions

        # 验证数据库操作
        mock_repository.get_by_recording_id.assert_called_once_with(recording_id)
        mock_repository.create.assert_called_once()

        # 验证 WebSocket 广播
        mock_ws_handler.broadcast.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_confirmation_already_confirmed(
        self, confirmer, mock_repository, sample_intent
    ):
        """测试启动已确认意图的确认流程"""
        recording_id = "test-recording-1"

        # 模拟已存在已确认的意图
        db_intent = IntentDBModel(
            intent_id=sample_intent.intent_id,
            recording_id=recording_id,
            core_operations=[op.operation for op in sample_intent.analysis_result.core_operations],
            target=sample_intent.analysis_result.target,
            business_scenario=sample_intent.analysis_result.business_scenario,
            expected_results=sample_intent.analysis_result.expected_results,
            status=IntentStatus.CONFIRMED,
            confirmed_operations=[
                op.operation for op in sample_intent.analysis_result.core_operations
            ],
            user_message=None,
            analysis_confidence=sample_intent.analysis_result.confidence,
            llm_model_used=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            confirmed_at=datetime.now(),
        )
        mock_repository.get_by_recording_id.return_value = db_intent

        # 执行
        result = await confirmer.start_confirmation(recording_id)

        # 验证返回了已确认的意图
        assert result.intent_id == sample_intent.intent_id
        assert result.status == "confirmed"

    @pytest.mark.asyncio
    async def test_process_user_feedback(
        self,
        confirmer,
        mock_analyzer,
        mock_repository,
        mock_ws_handler,
        sample_intent,
        sample_analysis_result,
    ):
        """测试处理用户反馈"""
        intent_id = sample_intent.intent_id
        feedback = "请将第二个操作改为输入邮箱"

        # 创建活跃会话
        confirmer.active_sessions[intent_id] = ConfirmationState(sample_intent)

        # 模拟优化后的结果
        refined_result = IntentAnalysisResult(
            core_operations=[
                CoreOperation(operation="打开网站", action_index=0),
                CoreOperation(operation="输入邮箱", action_index=1),
                CoreOperation(operation="点击登录按钮", action_index=2),
            ],
            target="示例网站",
            business_scenario="auth - 用户登录",
            expected_results=["成功登录系统"],
            suggested_parameters=[],
            confidence=0.90,
            reasoning="根据用户反馈修改了第二个操作",
            recording_id=sample_intent.recording_id,
            status="pending_confirmation",
        )
        mock_analyzer.refine_intent.return_value = refined_result

        # 模拟添加确认轮次
        mock_analyzer.add_confirmation_turn.return_value = Mock(
            user_feedback=feedback,
            assistant_response=refined_result.reasoning,
            updated_intent=refined_result,
        )

        # 执行
        result = await confirmer.process_user_feedback(intent_id, feedback)

        # 验证
        assert result.intent_id == intent_id
        assert result.analysis_result.confidence == 0.90

        # 验证会话状态
        session = confirmer.active_sessions[intent_id]
        assert session.current_turn == 1
        assert session.state == "refining"

        # 验证分析器调用
        mock_analyzer.refine_intent.assert_called_once()
        mock_analyzer.add_confirmation_turn.assert_called_once()

        # 验证数据库更新
        mock_repository.update.assert_called_once()

        # 验证 WebSocket 广播
        mock_ws_handler.broadcast.assert_called()

    @pytest.mark.asyncio
    async def test_process_user_feedback_max_turns_exceeded(self, confirmer, sample_intent):
        """测试处理用户反馈时超过最大轮数"""
        intent_id = sample_intent.intent_id

        # 创建已达到最大轮数的会话
        session = ConfirmationState(sample_intent)
        for _ in range(5):
            session.advance_turn()
        confirmer.active_sessions[intent_id] = session

        # 执行并验证异常
        with pytest.raises(ValueError, match="已达到最大对话轮数"):
            await confirmer.process_user_feedback(intent_id, "测试反馈")

    @pytest.mark.asyncio
    async def test_confirm_intent(self, confirmer, mock_repository, mock_ws_handler, sample_intent):
        """测试确认意图"""
        intent_id = sample_intent.intent_id
        confirmed_operations = ["打开网站", "输入邮箱", "点击登录按钮"]

        # 创建活跃会话
        confirmer.active_sessions[intent_id] = ConfirmationState(sample_intent)

        # 执行
        result = await confirmer.confirm_intent(intent_id, confirmed_operations)

        # 验证
        assert result.intent_id == intent_id
        assert result.status == "confirmed"
        assert result.confirmed_at is not None

        # 验证会话已清理
        assert intent_id not in confirmer.active_sessions

        # 验证数据库更新
        mock_repository.update.assert_called_once()

        # 验证 WebSocket 广播
        mock_ws_handler.broadcast.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_confirmation(
        self, confirmer, mock_repository, mock_ws_handler, sample_intent
    ):
        """测试取消确认"""
        intent_id = sample_intent.intent_id

        # 创建活跃会话
        confirmer.active_sessions[intent_id] = ConfirmationState(sample_intent)

        # 执行
        result = await confirmer.cancel_confirmation(intent_id)

        # 验证
        assert result.intent_id == intent_id
        assert result.status == "cancelled"

        # 验证会话已清理
        assert intent_id not in confirmer.active_sessions

        # 验证数据库更新
        mock_repository.update.assert_called_once()

        # 验证 WebSocket 广播
        mock_ws_handler.broadcast.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_confirm_intent_confirm_action(
        self, confirmer, mock_repository, mock_ws_handler, sample_intent
    ):
        """测试处理确认意图消息 - confirm 动作"""
        intent_id = sample_intent.intent_id

        # 创建活跃会话
        confirmer.active_sessions[intent_id] = ConfirmationState(sample_intent)

        # 创建消息
        msg = WebSocketMessage(
            type=MessageType.CONFIRM_INTENT,
            data={
                "intent_id": intent_id,
                "action": "confirm",
                "confirmed_operations": ["操作1", "操作2"],
            },
        )

        # 执行
        result = await confirmer._handle_confirm_intent(msg)

        # 验证
        assert result["status"] == "confirmed"
        assert result["intent_id"] == intent_id

    @pytest.mark.asyncio
    async def test_handle_confirm_intent_cancel_action(
        self, confirmer, mock_repository, mock_ws_handler, sample_intent
    ):
        """测试处理确认意图消息 - cancel 动作"""
        intent_id = sample_intent.intent_id

        # 创建活跃会话
        confirmer.active_sessions[intent_id] = ConfirmationState(sample_intent)

        # 创建消息
        msg = WebSocketMessage(
            type=MessageType.CONFIRM_INTENT,
            data={
                "intent_id": intent_id,
                "action": "cancel",
            },
        )

        # 执行
        result = await confirmer._handle_confirm_intent(msg)

        # 验证
        assert result["status"] == "cancelled"
        assert result["intent_id"] == intent_id

    @pytest.mark.asyncio
    async def test_handle_confirm_intent_refine_action(
        self, confirmer, mock_analyzer, mock_ws_handler, sample_intent
    ):
        """测试处理确认意图消息 - refine 动作"""
        intent_id = sample_intent.intent_id
        feedback = "请优化分析结果"

        # 创建活跃会话
        confirmer.active_sessions[intent_id] = ConfirmationState(sample_intent)

        # 模拟优化结果
        refined_result = sample_intent.analysis_result
        refined_result.confidence = 0.95
        mock_analyzer.refine_intent.return_value = refined_result
        mock_analyzer.add_confirmation_turn.return_value = Mock(
            user_feedback=feedback,
            assistant_response="已优化",
            updated_intent=refined_result,
        )

        # 创建消息
        msg = WebSocketMessage(
            type=MessageType.CONFIRM_INTENT,
            data={
                "intent_id": intent_id,
                "action": "refine",
                "feedback": feedback,
            },
        )

        # 执行
        result = await confirmer._handle_confirm_intent(msg)

        # 验证
        assert result["status"] == "refined"
        assert result["intent_id"] == intent_id
        assert "updated_intent" in result

    def test_get_active_session_count(self, confirmer, sample_intent):
        """测试获取活跃会话数量"""
        assert confirmer.get_active_session_count() == 0

        # 添加会话
        confirmer.active_sessions["intent-1"] = ConfirmationState(sample_intent)
        confirmer.active_sessions["intent-2"] = ConfirmationState(sample_intent)

        assert confirmer.get_active_session_count() == 2

    def test_cleanup_stale_sessions(self, confirmer, sample_intent):
        """测试清理超时会话"""
        import time

        # 创建会话
        session1 = ConfirmationState(sample_intent)
        session2 = ConfirmationState(sample_intent)

        confirmer.active_sessions["intent-1"] = session1
        confirmer.active_sessions["intent-2"] = session2

        # 修改第一个会话的活动时间（使其超时）
        session1.last_activity = time.time() - 4000  # 超过 3600 秒

        # 清理
        confirmer.cleanup_stale_sessions(timeout=3600)

        # 验证
        assert confirmer.get_active_session_count() == 1
        assert "intent-1" not in confirmer.active_sessions
        assert "intent-2" in confirmer.active_sessions

    def test_build_conversation_history(self, confirmer, sample_intent):
        """测试构建对话历史"""
        from src.business.ai.prompts.intent_analysis_models import IntentConfirmationTurn

        # 添加对话轮次
        turn1 = IntentConfirmationTurn(
            turn_id="turn-1",
            intent_id=sample_intent.intent_id,
            user_feedback="用户反馈1",
            assistant_response="助手回复1",
            updated_intent=sample_intent.analysis_result,
            timestamp=1234567890.0,
        )
        turn2 = IntentConfirmationTurn(
            turn_id="turn-2",
            intent_id=sample_intent.intent_id,
            user_feedback="用户反馈2",
            assistant_response="助手回复2",
            updated_intent=sample_intent.analysis_result,
            timestamp=1234567891.0,
        )
        sample_intent.confirmation_turns = [turn1, turn2]

        # 构建历史
        history = confirmer._build_conversation_history(sample_intent)

        # 验证
        assert len(history) == 4  # 2 轮对话，每轮 2 条消息
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "用户反馈1"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "助手回复1"
        assert history[2]["role"] == "user"
        assert history[2]["content"] == "用户反馈2"
        assert history[3]["role"] == "assistant"
        assert history[3]["content"] == "助手回复2"
