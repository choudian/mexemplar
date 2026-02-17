"""
WebSocket 端到端通信测试

测试前后端 WebSocket 通信的完整流程
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock
from datetime import datetime

from src.communication.websocket_handler import WebSocketHandler
from src.communication.websocket_client import WebSocketClient
from src.communication.message_types import MessageType, WebSocketMessage
from src.business.intent.intent_confirmer import IntentConfirmer
from src.business.intent.intent_analyzer import IntentAnalyzer
from src.business.intent.intent_repository import IntentRepository
from src.business.ai.prompts.intent_analysis_models import (
    IntentAnalysisResult,
    CoreOperation,
    Intent as IntentAnalysisModel,
)
from src.data.database import DatabaseManager


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def db_manager():
    """创建测试数据库"""
    return DatabaseManager(":memory:")


@pytest.fixture
def intent_repository(db_manager):
    """创建意图仓库"""
    return IntentRepository(db_manager)


@pytest.fixture
def mock_llm_client():
    """模拟 LLM 客户端"""
    client = Mock()
    client.chat = AsyncMock()
    return client


@pytest.fixture
def intent_analyzer(mock_llm_client):
    """创建意图分析器"""
    return IntentAnalyzer(llm_client=mock_llm_client)


@pytest.fixture
async def websocket_server(intent_analyzer, intent_repository):
    """创建完整的 WebSocket 服务器（带确认器）"""
    handler = WebSocketHandler(host="127.0.0.1", port=8767)

    # 创建确认器
    confirmer = IntentConfirmer(
        analyzer=intent_analyzer,
        repository=intent_repository,
        ws_handler=handler,
    )

    # 注册处理器
    handler.register_handler(MessageType.CONFIRM_INTENT, confirmer._handle_confirm_intent)

    # 启动服务器
    await handler.start()

    yield handler, confirmer

    # 停止服务器
    await handler.stop()


@pytest.fixture
async def websocket_client():
    """创建 WebSocket 客户端"""
    client = WebSocketClient(uri="ws://127.0.0.1:8767")
    client.start()

    # 等待连接
    await asyncio.sleep(0.5)

    yield client

    # 停止客户端
    client.stop()


# ============================================================================
# 连接测试
# ============================================================================


class TestWebSocketConnection:
    """WebSocket 连接测试"""

    @pytest.mark.asyncio
    async def test_server_start_and_stop(self):
        """测试服务器启动和停止"""
        handler = WebSocketHandler(host="127.0.0.1", port=8768)

        # 启动
        await handler.start()
        assert handler.server is not None

        # 停止
        await handler.stop()
        assert handler.server is None

    @pytest.mark.asyncio
    async def test_client_connect_and_disconnect(self, websocket_server):
        """测试客户端连接和断开"""
        handler, _ = websocket_server

        client = WebSocketClient(uri="ws://127.0.0.1:8767")
        client.start()

        # 等待连接
        await asyncio.sleep(0.5)

        # 验证连接
        assert handler.get_client_count() == 1

        # 断开
        client.stop()

        # 等待断开
        await asyncio.sleep(0.5)

        # 验证断开
        assert handler.get_client_count() == 0

    @pytest.mark.asyncio
    async def test_multiple_clients(self, websocket_server):
        """测试多个客户端连接"""
        handler, _ = websocket_server

        clients = []
        for i in range(3):
            client = WebSocketClient(uri="ws://127.0.0.1:8767")
            client.start()
            clients.append(client)
            await asyncio.sleep(0.2)

        # 验证连接
        assert handler.get_client_count() == 3

        # 清理
        for client in clients:
            client.stop()
        await asyncio.sleep(0.5)

        assert handler.get_client_count() == 0


# ============================================================================
# 消息通信测试
# ============================================================================


class TestWebSocketMessaging:
    """WebSocket 消息通信测试"""

    @pytest.mark.asyncio
    async def test_ping_pong(self, websocket_server, websocket_client):
        """测试心跳机制"""
        handler, _ = websocket_server

        # 收到消息的 Future
        received_message = asyncio.Future()

        def on_pong(msg: WebSocketMessage):
            if msg.type == MessageType.PONG:
                received_message.set_result(msg)

        websocket_client.register_handler(MessageType.PONG, on_pong)

        # 发送 PING
        ping_msg = WebSocketMessage(
            type=MessageType.PING,
            data={"timestamp": time.time()},
        )
        await websocket_client.send(ping_msg)

        # 等待 PONG
        try:
            await asyncio.wait_for(received_message, timeout=2.0)
            assert True
        except asyncio.TimeoutError:
            pytest.fail("未收到 PONG 响应")

    @pytest.mark.asyncio
    async def test_broadcast_message(self, websocket_server):
        """测试广播消息"""
        handler, _ = websocket_server

        # 创建多个客户端
        clients = []
        received_counts = []

        for i in range(3):
            client = WebSocketClient(uri="ws://127.0.0.1:8767")
            client.start()

            # 创建 Future 来跟踪接收
            future = asyncio.Future()
            received_counts.append(future)

            def on_message(msg, future=future):
                if not future.done():
                    future.set_result(msg)

            client.register_handler(MessageType.INTENT_ANALYZED, on_message)
            clients.append(client)

        await asyncio.sleep(0.5)

        # 广播消息
        broadcast_msg = WebSocketMessage(
            type=MessageType.INTENT_ANALYZED,
            data={
                "intent_id": "test-intent",
                "core_operations": ["操作1", "操作2"],
            },
        )
        await handler.broadcast(broadcast_msg)

        # 等待所有客户端接收
        for future in received_counts:
            try:
                await asyncio.wait_for(future, timeout=2.0)
            except asyncio.TimeoutError:
                pytest.fail("客户端未收到广播消息")

        # 清理
        for client in clients:
            client.stop()

    @pytest.mark.asyncio
    async def test_request_response(self, websocket_server, websocket_client):
        """测试请求-响应模式"""
        handler, confirmer = websocket_server

        # 创建测试意图
        sample_result = IntentAnalysisResult(
            core_operations=[
                CoreOperation(operation="打开网站", action_index=0),
                CoreOperation(operation="输入用户名", action_index=1),
            ],
            target="测试网站",
            business_scenario="测试场景",
            expected_results=[],
            suggested_parameters=[],
            confidence=0.85,
            reasoning="测试",
            recording_id="test-001",
            status="pending_confirmation",
        )

        intent = IntentAnalysisModel(
            intent_id="test-intent-req-001",
            recording_id="test-recording-001",
            analysis_result=sample_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        confirmer.active_sessions[intent.intent_id] = Mock(intent=intent)

        # 发送请求
        request_msg = WebSocketMessage.create_request(
            MessageType.CONFIRM_INTENT,
            {
                "intent_id": intent.intent_id,
                "action": "confirm",
                "confirmed_operations": ["打开网站", "输入用户名"],
            },
        )

        await websocket_client.send(request_msg)

        # 等待响应
        # 注意：这需要客户端有处理响应的机制
        await asyncio.sleep(0.5)


# ============================================================================
# 消息处理器测试
# ============================================================================


class TestMessageHandlers:
    """消息处理器测试"""

    @pytest.mark.asyncio
    async def test_register_custom_handler(self, websocket_server, websocket_client):
        """测试注册自定义处理器"""
        handler, _ = websocket_server

        # 收到消息的 Future
        received_future = asyncio.Future()

        async def custom_handler(msg: WebSocketMessage):
            received_future.set_result(msg)
            return {"status": "processed"}

        # 注册处理器
        handler.register_handler(MessageType.ANALYZE_INTENT, custom_handler)

        # 客户端发送消息
        test_msg = WebSocketMessage.create_request(
            MessageType.ANALYZE_INTENT,
            {"test_data": "value"},
        )

        await websocket_client.send(test_msg)

        # 等待处理器被调用
        try:
            received_msg = await asyncio.wait_for(received_future, timeout=2.0)
            assert received_msg.data["test_data"] == "value"
        except asyncio.TimeoutError:
            pytest.fail("处理器未被调用")

    @pytest.mark.asyncio
    async def test_handler_exception(self, websocket_server, websocket_client):
        """测试处理器异常处理"""
        handler, _ = websocket_server

        # 创建会抛出异常的处理器
        async def failing_handler(msg: WebSocketMessage):
            raise ValueError("测试异常")

        handler.register_handler(MessageType.ANALYZE_INTENT, failing_handler)

        # 客户端发送消息
        test_msg = WebSocketMessage.create_request(
            MessageType.ANALYZE_INTENT,
            {"test": "data"},
        )

        # 发送（不应该抛出异常）
        await websocket_client.send(test_msg)

        # 等待一下，确保服务器处理完成
        await asyncio.sleep(0.5)


# ============================================================================
# 意图确认集成测试
# ============================================================================


class TestIntentConfirmationE2E:
    """意图确认端到端测试"""

    @pytest.mark.asyncio
    async def test_full_confirmation_flow(self, websocket_server, websocket_client):
        """测试完整的确认流程"""
        handler, confirmer = websocket_server

        # 1. 创建意图
        sample_result = IntentAnalysisResult(
            core_operations=[
                CoreOperation(operation="操作1", action_index=0),
                CoreOperation(operation="操作2", action_index=1),
            ],
            target="测试目标",
            business_scenario="测试场景",
            expected_results=[],
            suggested_parameters=[],
            confidence=0.85,
            reasoning="测试",
            recording_id="test-001",
            status="pending_confirmation",
        )

        intent = IntentAnalysisModel(
            intent_id="test-e2e-001",
            recording_id="test-recording-e2e-001",
            analysis_result=sample_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        confirmer.active_sessions[intent.intent_id] = Mock(
            intent=intent,
            state="pending_confirmation",
            current_turn=0,
            max_turns=5,
        )

        # 2. 客户端监听确认成功消息
        confirmed_future = asyncio.Future()

        def on_confirmed(msg: WebSocketMessage):
            if msg.type == MessageType.INTENT_CONFIRMED:
                confirmed_future.set_result(msg)

        websocket_client.register_handler(MessageType.INTENT_CONFIRMED, on_confirmed)

        # 3. 发送确认请求
        confirm_msg = WebSocketMessage.create_request(
            MessageType.CONFIRM_INTENT,
            {
                "intent_id": intent.intent_id,
                "action": "confirm",
                "confirmed_operations": ["操作1", "操作2"],
            },
        )

        await websocket_client.send(confirm_msg)

        # 4. 等待确认成功
        try:
            confirmed_msg = await asyncio.wait_for(confirmed_future, timeout=2.0)
            assert confirmed_msg.data["intent_id"] == intent.intent_id
            assert confirmed_msg.data["status"] == "confirmed"
        except asyncio.TimeoutError:
            pytest.fail("未收到确认成功消息")

    @pytest.mark.asyncio
    async def test_multi_turn_refinement_flow(self, websocket_server, websocket_client):
        """测试多轮优化流程"""
        handler, confirmer = websocket_server

        # 1. 创建意图
        sample_result = IntentAnalysisResult(
            core_operations=[
                CoreOperation(operation="操作1", action_index=0),
                CoreOperation(operation="操作2", action_index=1),
            ],
            target="测试目标",
            business_scenario="测试场景",
            expected_results=[],
            suggested_parameters=[],
            confidence=0.85,
            reasoning="测试",
            recording_id="test-001",
            status="pending_confirmation",
        )

        intent = IntentAnalysisModel(
            intent_id="test-e2e-002",
            recording_id="test-recording-e2e-002",
            analysis_result=sample_result,
            status="pending_confirmation",
            max_turns=5,
            created_at=time.time(),
            updated_at=time.time(),
        )

        # 创建会话状态
        session_state = Mock(
            intent=intent,
            state="pending_confirmation",
            current_turn=0,
            max_turns=5,
        )

        # 模拟推进方法
        session_state.advance_turn = Mock(return_value=True)

        confirmer.active_sessions[intent.intent_id] = session_state

        # 2. 监听更新消息
        updated_future = asyncio.Future()

        def on_updated(msg: WebSocketMessage):
            if msg.type == MessageType.INTENT_UPDATED:
                updated_future.set_result(msg)

        websocket_client.register_handler(MessageType.INTENT_UPDATED, on_updated)

        # 3. 发送优化请求
        refine_msg = WebSocketMessage.create_request(
            MessageType.CONFIRM_INTENT,
            {
                "intent_id": intent.intent_id,
                "action": "refine",
                "feedback": "请优化操作2",
            },
        )

        await websocket_client.send(refine_msg)

        # 4. 等待更新（注意：这需要实际的 refine_intent 实现）
        # 这里我们只是验证消息能够发送
        await asyncio.sleep(0.5)


# ============================================================================
# 错误处理测试
# ============================================================================


class TestErrorHandling:
    """错误处理测试"""

    @pytest.mark.asyncio
    async def test_invalid_json(self, websocket_server):
        """测试无效 JSON"""
        handler, _ = websocket_server

        # 创建客户端连接
        client = WebSocketClient(uri="ws://127.0.0.1:8767")
        client.start()
        await asyncio.sleep(0.5)

        # 获取 WebSocket 连接
        websocket = list(handler.clients)[0]

        # 发送无效 JSON
        try:
            await websocket.send("invalid json {{{")
            # 等待处理
            await asyncio.sleep(0.5)
            # 服务器应该仍然正常工作
            assert handler.get_client_count() == 1
        except Exception as e:
            pytest.fail(f"发送无效 JSON 导致异常: {e}")
        finally:
            client.stop()

    @pytest.mark.asyncio
    async def test_unknown_message_type(self, websocket_server, websocket_client):
        """测试未知消息类型"""
        handler, _ = websocket_server

        # 创建未知类型的消息
        unknown_msg = WebSocketMessage(
            type="unknown_type",  # 无效类型
            data={"test": "data"},
        )

        # 发送（不应该抛出异常）
        await websocket_client.send(unknown_msg)

        # 等待处理
        await asyncio.sleep(0.5)

        # 服务器应该仍然正常工作
        assert handler.get_client_count() >= 1

    @pytest.mark.asyncio
    async def test_handler_with_missing_data(self, websocket_server, websocket_client):
        """测试缺少必要数据的消息"""
        handler, confirmer = websocket_server

        # 发送缺少 intent_id 的确认消息
        invalid_msg = WebSocketMessage.create_request(
            MessageType.CONFIRM_INTENT,
            {
                "action": "confirm",
                # 缺少 intent_id
            },
        )

        # 发送（应该收到错误响应）
        await websocket_client.send(invalid_msg)

        # 等待处理
        await asyncio.sleep(0.5)


# ============================================================================
# 性能测试
# ============================================================================


class TestPerformance:
    """性能测试"""

    @pytest.mark.asyncio
    async def test_concurrent_messages(self, websocket_server, websocket_client):
        """测试并发消息处理"""
        handler, _ = websocket_server

        # 创建计数器
        received_count = asyncio.Future()
        counter = [0]

        async def counting_handler(msg: WebSocketMessage):
            counter[0] += 1
            if counter[0] >= 10:
                received_count.set_result(counter[0])
            return {"count": counter[0]}

        handler.register_handler(MessageType.PING, counting_handler)

        # 并发发送 10 条消息
        tasks = []
        for i in range(10):
            msg = WebSocketMessage(
                type=MessageType.PING,
                data={"index": i},
            )
            tasks.append(websocket_client.send(msg))

        await asyncio.gather(*tasks)

        # 等待所有消息被处理
        try:
            final_count = await asyncio.wait_for(received_count, timeout=5.0)
            assert final_count == 10
        except asyncio.TimeoutError:
            pytest.fail(f"只有 {counter[0]}/10 条消息被处理")

    @pytest.mark.asyncio
    async def test_message_latency(self, websocket_server, websocket_client):
        """测试消息延迟"""
        handler, _ = websocket_server

        # 创建处理器
        response_received = asyncio.Future()

        async def echo_handler(msg: WebSocketMessage):
            response_received.set_result(time.time())
            return {"echo": msg.data}

        handler.register_handler(MessageType.PING, echo_handler)

        # 发送消息并记录时间
        send_time = time.time()

        msg = WebSocketMessage(
            type=MessageType.PING,
            data={"test": "latency"},
        )

        await websocket_client.send(msg)

        # 等待响应
        try:
            receive_time = await asyncio.wait_for(response_received, timeout=2.0)
            latency = receive_time - send_time

            # 延迟应该小于 1 秒
            assert latency < 1.0, f"延迟过高: {latency:.3f}s"
        except asyncio.TimeoutError:
            pytest.fail("未收到响应")
