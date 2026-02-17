"""
WebSocket 客户端

用于 UI 与后端 WebSocket 服务器通信
"""

import asyncio
import json
import logging
from typing import Optional, Callable, Dict, Any
from datetime import datetime
import websockets
from websockets.client import WebSocketClientProtocol

from .message_types import WebSocketMessage, MessageType

logger = logging.getLogger(__name__)


class WebSocketClient:
    """
    WebSocket 客户端

    负责连接到 WebSocket 服务器，处理消息收发
    """

    def __init__(self, uri: str = "ws://127.0.0.1:8766"):
        """
        初始化 WebSocket 客户端

        Args:
            uri: WebSocket 服务器 URI
        """
        self.uri = uri
        self.websocket: Optional[WebSocketClientProtocol] = None
        self._connected = False
        self._reconnect_enabled = True
        self._reconnect_interval = 5  # 秒

        # 消息处理器注册表
        self.message_handlers: Dict[MessageType, Callable] = {}

        # 心跳配置
        self._ping_interval = 30  # 秒
        self._ping_task = None
        self._receive_task = None

        # 事件循环（在独立线程中运行）
        self._loop = None
        self._thread = None

    def register_handler(
        self, msg_type: MessageType, handler: Callable[[WebSocketMessage], Any]
    ):
        """
        注册消息处理器

        Args:
            msg_type: 消息类型
            handler: 处理函数，接收 WebSocketMessage
        """
        self.message_handlers[msg_type] = handler
        logger.info(f"注册消息处理器: {msg_type}")

    def unregister_handler(self, msg_type: MessageType):
        """
        取消注册消息处理器

        Args:
            msg_type: 消息类型
        """
        if msg_type in self.message_handlers:
            del self.message_handlers[msg_type]
            logger.info(f"取消注册消息处理器: {msg_type}")

    async def connect(self) -> bool:
        """
        连接到 WebSocket 服务器

        Returns:
            bool: 是否连接成功
        """
        try:
            logger.info(f"连接到 WebSocket 服务器: {self.uri}")
            self.websocket = await websockets.connect(self.uri)
            self._connected = True
            logger.info("✅ WebSocket 连接成功")

            # 启动心跳任务
            self._ping_task = asyncio.create_task(self._ping_loop())

            # 启动接收任务
            self._receive_task = asyncio.create_task(self._receive_loop())

            return True

        except Exception as e:
            logger.error(f"WebSocket 连接失败: {e}")
            self._connected = False
            return False

    async def disconnect(self):
        """断开 WebSocket 连接"""
        logger.info("断开 WebSocket 连接")

        self._reconnect_enabled = False
        self._connected = False

        # 取消任务
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        # 关闭连接
        if self.websocket:
            await self.websocket.close()
            self.websocket = None

        logger.info("WebSocket 已断开")

    async def _ping_loop(self):
        """心跳循环"""
        try:
            while self._connected and self.websocket:
                await asyncio.sleep(self._ping_interval)

                if not self._connected or not self.websocket:
                    break

                ping_msg = WebSocketMessage(
                    type=MessageType.PING,
                    data={"timestamp": datetime.now().timestamp()},
                )
                await self.send(ping_msg)

        except asyncio.CancelledError:
            logger.debug("心跳任务已取消")
        except Exception as e:
            logger.error(f"心跳任务出错: {e}")

    async def _receive_loop(self):
        """接收消息循环"""
        try:
            async for message in self.websocket:
                await self._process_message(message)

        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket 连接已关闭")
            self._connected = False

        except asyncio.CancelledError:
            logger.debug("接收任务已取消")
        except Exception as e:
            logger.error(f"接收消息出错: {e}")
            self._connected = False

    async def _process_message(self, raw_message: str):
        """
        处理收到的消息

        Args:
            raw_message: 原始消息字符串
        """
        try:
            # 解析消息
            msg = WebSocketMessage.from_json(raw_message)
            logger.debug(f"收到消息: {msg.type}")

            # 处理 PING 消息
            if msg.type == MessageType.PING:
                pong_msg = WebSocketMessage(
                    type=MessageType.PONG,
                    data={"timestamp": msg.timestamp},
                )
                await self.send(pong_msg)
                return

            # 处理 PONG 消息
            if msg.type == MessageType.PONG:
                logger.debug("收到 PONG 响应")
                return

            # 路由到对应的处理器
            handler = self.message_handlers.get(msg.type)
            if handler:
                try:
                    # 调用处理器
                    if asyncio.iscoroutinefunction(handler):
                        await handler(msg)
                    else:
                        handler(msg)

                except Exception as e:
                    logger.error(f"处理器执行失败: {msg.type}, error: {e}")
            else:
                logger.warning(f"未找到处理器: {msg.type}")

        except json.JSONDecodeError as e:
            logger.error(f"消息解析失败: {e}")
        except Exception as e:
            logger.error(f"处理消息时出错: {e}")

    async def send(self, msg: WebSocketMessage):
        """
        发送消息

        Args:
            msg: 消息对象
        """
        if not self._connected or not self.websocket:
            logger.warning("WebSocket 未连接，无法发送消息")
            return

        try:
            message_str = msg.to_json()
            await self.websocket.send(message_str)
            logger.debug(f"发送消息: {msg.type}")

        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            self._connected = False

    async def send_request(
        self, msg_type: MessageType, data: Dict[str, Any]
    ) -> str:
        """
        发送请求消息

        Args:
            msg_type: 消息类型
            data: 消息数据

        Returns:
            str: 请求 ID
        """
        msg = WebSocketMessage.create_request(msg_type, data)
        await self.send(msg)
        return msg.request_id

    def is_connected(self) -> bool:
        """
        检查是否已连接

        Returns:
            bool: 是否已连接
        """
        return self._connected

    # ===== 同步接口（用于在主线程中调用）=====

    def start(self):
        """启动 WebSocket 客户端（在后台线程中运行）"""
        import threading

        def run_loop():
            """运行事件循环"""
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            # 连接到服务器
            self._loop.run_until_complete(self.connect())

            # 运行事件循环
            self._loop.run_forever()

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()
        logger.info("WebSocket 客户端已启动（后台线程）")

    def stop(self):
        """停止 WebSocket 客户端"""
        if self._loop:
            # 停止事件循环
            self._loop.call_soon_threadsafe(self._loop.stop)

            # 断开连接
            asyncio.run_coroutine_threadsafe(self.disconnect(), self._loop)

        if self._thread:
            self._thread.join(timeout=5)

        logger.info("WebSocket 客户端已停止")

    def send_sync(self, msg: WebSocketMessage):
        """
        同步发送消息（线程安全）

        Args:
            msg: 消息对象
        """
        if self._loop and self._connected:
            asyncio.run_coroutine_threadsafe(self.send(msg), self._loop)

    def send_request_sync(
        self, msg_type: MessageType, data: Dict[str, Any]
    ) -> Optional[str]:
        """
        同步发送请求消息（线程安全）

        Args:
            msg_type: 消息类型
            data: 消息数据

        Returns:
            Optional[str]: 请求 ID
        """
        if self._loop and self._connected:
            msg = WebSocketMessage.create_request(msg_type, data)
            asyncio.run_coroutine_threadsafe(self.send(msg), self._loop)
            return msg.request_id
        return None
