"""
WebSocketHandler 单元测试
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from src.communication.message_types import MessageType, WebSocketMessage
from src.communication.websocket_handler import WebSocketHandler


@pytest.fixture
def websocket_handler():
    """创建 WebSocketHandler 实例"""
    return WebSocketHandler(host="127.0.0.1", port=8766)


class TestWebSocketHandler:
    """WebSocketHandler 测试"""

    def test_initialization(self, websocket_handler):
        """测试初始化"""
        assert websocket_handler.host == "127.0.0.1"
        assert websocket_handler.port == 8766
        assert websocket_handler.server is None
        assert len(websocket_handler.clients) == 0
        assert len(websocket_handler.message_handlers) == 0

    def test_register_handler(self, websocket_handler):
        """测试注册消息处理器"""
        async def mock_handler(msg):
            return {"result": "ok"}

        websocket_handler.register_handler(MessageType.ANALYZE_INTENT, mock_handler)

        assert MessageType.ANALYZE_INTENT in websocket_handler.message_handlers
        assert (
            websocket_handler.message_handlers[MessageType.ANALYZE_INTENT]
            == mock_handler
        )

    @pytest.mark.asyncio
    async def test_call_handler_async(self, websocket_handler):
        """测试调用异步处理器"""
        async def async_handler(msg):
            await asyncio.sleep(0.01)
            return {"result": "async"}

        msg = WebSocketMessage(type=MessageType.ANALYZE_INTENT, data={})

        result = await websocket_handler._call_handler(async_handler, msg)

        assert result == {"result": "async"}

    @pytest.mark.asyncio
    async def test_call_handler_sync(self, websocket_handler):
        """测试调用同步处理器"""
        def sync_handler(msg):
            return {"result": "sync"}

        msg = WebSocketMessage(type=MessageType.ANALYZE_INTENT, data={})

        result = await websocket_handler._call_handler(sync_handler, msg)

        assert result == {"result": "sync"}

    @pytest.mark.asyncio
    async def test_call_handler_non_dict_return(self, websocket_handler):
        """测试处理器返回非字典类型"""
        def bad_handler(msg):
            return "string_result"

        msg = WebSocketMessage(type=MessageType.ANALYZE_INTENT, data={})

        result = await websocket_handler._call_handler(bad_handler, msg)

        assert result == {"result": "string_result"}

    @pytest.mark.asyncio
    async def test_send_to_client(self, websocket_handler):
        """测试发送消息给客户端"""
        # Mock WebSocket 连接
        mock_websocket = Mock()
        mock_websocket.send = AsyncMock()

        msg = WebSocketMessage(
            type=MessageType.ANALYZE_INTENT,
            data={"test": "data"},
        )

        await websocket_handler.send_to_client(mock_websocket, msg)

        mock_websocket.send.assert_called_once()
        # 验证发送的是 JSON 字符串
        sent_data = mock_websocket.send.call_args[0][0]
        assert '"type": "analyze_intent"' in sent_data

    @pytest.mark.asyncio
    async def test_send_to_client_with_ack(self, websocket_handler):
        """测试发送需要确认的消息"""
        mock_websocket = Mock()
        mock_websocket.send = AsyncMock()

        msg = WebSocketMessage(
            type=MessageType.ANALYZE_INTENT,
            data={"test": "data"},
            request_id="req-001",
        )

        await websocket_handler.send_to_client(mock_websocket, msg, require_ack=True)

        # 验证消息在待确认队列中
        assert "req-001" in websocket_handler.pending_acks

    @pytest.mark.asyncio
    async def test_send_error(self, websocket_handler):
        """测试发送错误消息"""
        mock_websocket = Mock()
        mock_websocket.send = AsyncMock()

        await websocket_handler.send_error(mock_websocket, "测试错误")

        mock_websocket.send.assert_called_once()
        sent_data = mock_websocket.send.call_args[0][0]
        assert '"type": "error"' in sent_data
        assert '"测试错误"' in sent_data

    @pytest.mark.asyncio
    async def test_broadcast_empty_clients(self, websocket_handler):
        """测试广播消息（无客户端）"""
        msg = WebSocketMessage(type=MessageType.PING, data={})

        # 不应该抛出异常
        await websocket_handler.broadcast(msg)

    @pytest.mark.asyncio
    async def test_broadcast_multiple_clients(self, websocket_handler):
        """测试广播消息给多个客户端"""
        # 创建多个 mock 客户端
        client1 = Mock()
        client1.send = AsyncMock()
        client2 = Mock()
        client2.send = AsyncMock()

        # 添加到客户端集合
        websocket_handler.clients.add(client1)
        websocket_handler.clients.add(client2)

        msg = WebSocketMessage(type=MessageType.PING, data={})

        await websocket_handler.broadcast(msg)

        # 验证两个客户端都收到了消息
        assert client1.send.called
        assert client2.send.called

    def test_get_client_count(self, websocket_handler):
        """测试获取客户端数量"""
        assert websocket_handler.get_client_count() == 0

        # 添加 mock 客户端
        client = Mock()
        websocket_handler.clients.add(client)

        assert websocket_handler.get_client_count() == 1

    def test_get_pending_ack_count(self, websocket_handler):
        """测试获取待确认消息数量"""
        assert websocket_handler.get_pending_ack_count() == 0

        # 添加待确认消息
        msg = WebSocketMessage(
            type=MessageType.ANALYZE_INTENT,
            data={},
            request_id="req-001",
        )
        websocket_handler.pending_acks["req-001"] = msg

        assert websocket_handler.get_pending_ack_count() == 1

    @pytest.mark.asyncio
    async def test_process_message_ping(self, websocket_handler):
        """测试处理 PING 消息"""
        mock_websocket = Mock()
        mock_websocket.send = AsyncMock()

        ping_msg = WebSocketMessage(type=MessageType.PING, data={})
        raw_message = ping_msg.to_json()

        await websocket_handler.process_message(mock_websocket, raw_message)

        # 验证发送了 PONG 响应
        assert mock_websocket.send.called
        sent_data = mock_websocket.send.call_args[0][0]
        assert '"type": "pong"' in sent_data

    @pytest.mark.asyncio
    async def test_process_message_with_handler(self, websocket_handler):
        """测试处理有处理器的消息"""
        # 注册处理器
        async def test_handler(msg):
            return {"result": "processed"}

        websocket_handler.register_handler(MessageType.ANALYZE_INTENT, test_handler)

        # Mock WebSocket
        mock_websocket = Mock()
        mock_websocket.send = AsyncMock()

        # 创建请求消息
        request_msg = WebSocketMessage.create_request(
            MessageType.ANALYZE_INTENT,
            {"test": "data"},
        )
        raw_message = request_msg.to_json()

        await websocket_handler.process_message(mock_websocket, raw_message)

        # 验证发送了响应
        assert mock_websocket.send.called
        # 验证响应匹配请求的 request_id
        sent_data = mock_websocket.send.call_args[0][0]
        assert f'"request_id": "{request_msg.request_id}"' in sent_data
        assert '"status": "success"' in sent_data

    @pytest.mark.asyncio
    async def test_process_message_no_handler(self, websocket_handler):
        """测试处理没有处理器的消息"""
        mock_websocket = Mock()
        mock_websocket.send = AsyncMock()

        msg = WebSocketMessage(type=MessageType.ANALYZE_INTENT, data={})
        raw_message = msg.to_json()

        await websocket_handler.process_message(mock_websocket, raw_message)

        # 验证发送了错误消息
        assert mock_websocket.send.called
        sent_data = mock_websocket.send.call_args[0][0]
        assert '"type": "error"' in sent_data

    @pytest.mark.asyncio
    async def test_process_message_invalid_json(self, websocket_handler):
        """测试处理无效的 JSON"""
        mock_websocket = Mock()
        mock_websocket.send = AsyncMock()

        await websocket_handler.process_message(mock_websocket, "invalid json")

        # 验证发送了错误消息
        assert mock_websocket.send.called

    @pytest.mark.asyncio
    async def test_start_ping_task(self, websocket_handler):
        """测试启动心跳任务"""
        await websocket_handler.start_ping_task()

        assert websocket_handler._ping_task is not None

        # 清理
        await websocket_handler.stop_ping_task()

    @pytest.mark.asyncio
    async def test_stop_ping_task(self, websocket_handler):
        """测试停止心跳任务"""
        await websocket_handler.start_ping_task()
        assert websocket_handler._ping_task is not None

        await websocket_handler.stop_ping_task()

        # 任务应该已取消
        assert websocket_handler._ping_task.done()
