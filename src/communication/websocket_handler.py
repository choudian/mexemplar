"""
WebSocket 通信处理器

提供心跳机制、断线重连、消息确认等功能
"""

import asyncio
import json
import logging
from typing import Dict, Any, Callable, Set
from datetime import datetime
import websockets
from websockets.server import WebSocketServerProtocol

from .message_types import WebSocketMessage, MessageType

logger = logging.getLogger(__name__)


class WebSocketHandler:
    """
    WebSocket 处理器

    负责管理 WebSocket 连接、消息路由、心跳机制等
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8766):
        """
        初始化 WebSocket 处理器

        Args:
            host: 监听地址
            port: 监听端口
        """
        self.host = host
        self.port = port
        self.server = None
        self.clients: Set[WebSocketServerProtocol] = set()

        # 消息处理器注册表
        self.message_handlers: Dict[MessageType, Callable] = {}

        # 心跳配置
        self.ping_interval = 30  # 秒
        self._ping_task = None

        # 待确认的消息队列（request_id -> 消息）
        self.pending_acks: Dict[str, WebSocketMessage] = {}

    def register_handler(self, msg_type: MessageType, handler: Callable[[WebSocketMessage], Any]):
        """
        注册消息处理器

        Args:
            msg_type: 消息类型
            handler: 处理函数，接收 WebSocketMessage，返回响应数据
        """
        self.message_handlers[msg_type] = handler
        logger.info(f"注册消息处理器: {msg_type}")

    async def handle_client(self, websocket: WebSocketServerProtocol, path: str):
        """
        处理客户端连接

        Args:
            websocket: WebSocket 连接
            path: 连接路径
        """
        client_id = id(websocket)
        logger.info(f"新客户端连接: {client_id}")

        # 添加到客户端集合
        self.clients.add(websocket)

        try:
            # 发送连接成功消息
            await self.send_to_client(
                websocket,
                WebSocketMessage(
                    type=MessageType.CONNECT,
                    data={"client_id": str(client_id), "status": "connected"},
                ),
            )

            # 消息处理循环
            async for message in websocket:
                await self.process_message(websocket, message)

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"客户端断开连接: {client_id}")
        except Exception as e:
            logger.error(f"处理客户端消息时出错: {e}", exc_info=True)
        finally:
            # 清理
            self.clients.discard(websocket)
            logger.info(f"客户端清理完成: {client_id}")

    async def process_message(self, websocket: WebSocketServerProtocol, raw_message: str):
        """
        处理收到的消息

        Args:
            websocket: WebSocket 连接
            raw_message: 原始消息字符串
        """
        try:
            # 解析消息
            msg = WebSocketMessage.from_json(raw_message)
            logger.debug(f"收到消息: {msg.type} from {id(websocket)}")

            # 处理 PING 消息
            if msg.type == MessageType.PING:
                await self.send_to_client(
                    websocket,
                    WebSocketMessage(
                        type=MessageType.PONG,
                        data={"timestamp": msg.timestamp},
                    ),
                )
                return

            # 处理 PONG 消息
            if msg.type == MessageType.PONG:
                logger.debug("收到 PONG 响应")
                return

            # 处理 ACK 消息
            if msg.type == MessageType.ACK:
                request_id = msg.data.get("request_id")
                if request_id in self.pending_acks:
                    del self.pending_acks[request_id]
                    logger.debug(f"消息已确认: {request_id}")
                return

            # 路由到对应的处理器
            handler = self.message_handlers.get(msg.type)
            if handler:
                try:
                    # 调用处理器
                    response_data = await self._call_handler(handler, msg)

                    # 发送响应
                    response = WebSocketMessage.create_response(msg, response_data)
                    await self.send_to_client(websocket, response)

                except Exception as e:
                    logger.error(f"处理器执行失败: {msg.type}, error: {e}")
                    error_msg = WebSocketMessage.create_error(msg, str(e))
                    await self.send_to_client(websocket, error_msg)
            else:
                logger.warning(f"未找到处理器: {msg.type}")
                error_msg = WebSocketMessage.create_error(msg, f"未知的消息类型: {msg.type}")
                await self.send_to_client(websocket, error_msg)

        except json.JSONDecodeError as e:
            logger.error(f"消息解析失败: {e}")
            await self.send_error(websocket, f"消息格式错误: {e}")
        except Exception as e:
            logger.error(f"处理消息时出错: {e}", exc_info=True)
            await self.send_error(websocket, f"处理消息失败: {e}")

    async def _call_handler(self, handler: Callable, msg: WebSocketMessage) -> Dict[str, Any]:
        """
        调用消息处理器

        Args:
            handler: 处理函数
            msg: 消息对象

        Returns:
            响应数据
        """
        # 检查是否是协程函数
        if asyncio.iscoroutinefunction(handler):
            result = await handler(msg)
        else:
            result = handler(msg)

        # 确保返回字典
        if not isinstance(result, dict):
            logger.warning(f"处理器返回非字典类型: {type(result)}")
            result = {"result": result}

        return result

    async def send_to_client(
        self,
        websocket: WebSocketServerProtocol,
        msg: WebSocketMessage,
        require_ack: bool = False,
    ):
        """
        发送消息给客户端

        Args:
            websocket: WebSocket 连接
            msg: 消息对象
            require_ack: 是否需要确认
        """
        try:
            message_str = msg.to_json()
            await websocket.send(message_str)
            logger.debug(f"发送消息: {msg.type} to {id(websocket)}")

            # 如果需要确认，添加到待确认队列
            if require_ack and msg.request_id:
                self.pending_acks[msg.request_id] = msg

        except websockets.exceptions.ConnectionClosed:
            logger.warning(f"客户端已断开，无法发送消息: {id(websocket)}")
            raise
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            raise

    async def broadcast(self, msg: WebSocketMessage):
        """
        广播消息给所有客户端

        Args:
            msg: 消息对象
        """
        if not self.clients:
            logger.warning("没有连接的客户端")
            return

        # 创建任务列表
        tasks = [self.send_to_client(client, msg) for client in self.clients.copy()]

        # 并发发送
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 统计成功/失败
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        fail_count = len(results) - success_count

        logger.info(f"广播消息完成: {msg.type}, " f"成功: {success_count}, 失败: {fail_count}")

    async def send_error(self, websocket: WebSocketServerProtocol, error_message: str):
        """
        发送错误消息

        Args:
            websocket: WebSocket 连接
            error_message: 错误信息
        """
        error_msg = WebSocketMessage(
            type=MessageType.ERROR,
            data={"error": error_message},
            status="error",
            error=error_message,
        )
        await self.send_to_client(websocket, error_msg)

    async def start_ping_task(self):
        """启动心跳任务"""

        async def ping_loop():
            while self.server:
                try:
                    ping_msg = WebSocketMessage(
                        type=MessageType.PING,
                        data={"timestamp": datetime.now().timestamp()},
                    )
                    await self.broadcast(ping_msg)
                    await asyncio.sleep(self.ping_interval)
                except Exception as e:
                    logger.error(f"心跳任务出错: {e}")
                    break

        self._ping_task = asyncio.create_task(ping_loop())
        logger.info(f"心跳任务已启动，间隔: {self.ping_interval}秒")

    async def stop_ping_task(self):
        """停止心跳任务"""
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            logger.info("心跳任务已停止")

    async def start(self):
        """启动 WebSocket 服务器"""
        logger.info(f"启动 WebSocket 服务器: {self.host}:{self.port}")

        # 启动心跳任务
        await self.start_ping_task()

        # 启动服务器
        self.server = await websockets.serve(
            self.handle_client,
            self.host,
            self.port,
            ping_interval=None,  # 我们自己实现心跳
            ping_timeout=None,
        )

        logger.info(f"✅ WebSocket 服务器已启动: ws://{self.host}:{self.port}")

    async def stop(self):
        """停止 WebSocket 服务器"""
        logger.info("停止 WebSocket 服务器")

        # 停止心跳任务
        await self.stop_ping_task()

        # 关闭服务器
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("WebSocket 服务器已停止")

    def get_client_count(self) -> int:
        """获取当前连接的客户端数量"""
        return len(self.clients)
