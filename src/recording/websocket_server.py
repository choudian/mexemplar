"""
WebSocket 服务器模块

用于与浏览器扩展进行实时通信，替代 Native Messaging 和 CDP 降级模式。
"""

import asyncio
import json
import logging
import time
from typing import Callable, Optional, Set, Dict, Any
from websockets.server import WebSocketServerProtocol, serve

from src.data.unified_config import get_unified_config

logger = logging.getLogger(__name__)


class WebSocketServer:
    """WebSocket 服务器，用于与浏览器扩展通信"""

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        """
        初始化 WebSocket 服务器

        Args:
            host: 监听地址（如果为 None 则从配置读取）
            port: 监听端口（如果为 None 则从配置读取）
        """
        # ⭐ 从统一配置读取默认值
        config = get_unified_config()
        self.host = host or config.get_websocket_host()
        self.port = port or config.get_websocket_port()
        self.clients: Set[WebSocketServerProtocol] = set()
        self.message_handler: Optional[Callable] = None
        self._is_running = False
        self._loop = None  # 事件循环引用
        self._serve_future = None  # 用于取消 serve 阻塞

        # 统计信息
        self.stats = {"connections": 0, "messages_received": 0, "messages_sent": 0, "errors": 0}

        # ⭐ 注册配置变化观察者
        config.register_observer(
            self._on_config_changed, keys=["recording.websocket.host", "recording.websocket.port"]
        )
        logger.info("[WS] 已注册配置变化观察者")

    async def handle_client(self, websocket: WebSocketServerProtocol):
        """
        处理客户端连接

        Args:
            websocket: WebSocket 客户端连接
        """
        self.clients.add(websocket)
        self.stats["connections"] += 1

        client_addr = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"[WS] 客户端已连接: {client_addr} (总数: {len(self.clients)})")

        try:
            # 接收消息循环
            async for message in websocket:
                try:
                    data = json.loads(message)
                    self.stats["messages_received"] += 1

                    # ⭐ 调试日志：打印所有收到的消息
                    msg_type = data.get("type")
                    logger.debug(f"[WS] 🔔 收到消息: {msg_type} from {client_addr}")

                    # 如果是 browser_action，打印详细信息
                    if msg_type == "browser_action":
                        action_data = data.get("action", {})
                        action_type = action_data.get("action_type", "unknown")
                        url = action_data.get("url", "no-url")
                        logger.debug(f"[WS] 📌 浏览器事件: {action_type} @ {url}")

                        # 打印完整的消息（前500字符）
                        message_str = json.dumps(data, ensure_ascii=False)
                        logger.debug(f"[WS] 📦 消息内容: {message_str[:500]}...")

                    # 1. 处理消息（回调）
                    await self.process_message(data, websocket)

                    # 2. 如果是 browser_action，写入队列文件
                    if msg_type == "browser_action" and self.message_handler:
                        self.message_handler(data)

                except json.JSONDecodeError as e:
                    logger.error(f"[WS] JSON 解析失败: {e}")
                    self.stats["errors"] += 1

                except Exception as e:
                    logger.error(f"[WS] 处理消息失败: {e}")
                    self.stats["errors"] += 1

        except Exception as e:
            logger.warning(f"[WS] 客户端连接异常: {e}")

        finally:
            self.clients.remove(websocket)
            logger.info(f"[WS] 客户端断开: {client_addr} (剩余: {len(self.clients)})")

    async def process_message(self, message: Dict[str, Any], websocket: WebSocketServerProtocol):
        """
        处理接收到的消息

        Args:
            message: 消息数据
            websocket: WebSocket 连接
        """
        msg_type = message.get("type")

        if msg_type == "ping":
            # 心跳请求，回复 pong
            await self.send_to_client(websocket, {"type": "pong", "timestamp": time.time()})

        elif msg_type == "pong":
            # 心跳响应
            logger.debug("[WS] 收到心跳响应")

        elif msg_type == "browser_action":
            # 浏览器事件（已由 message_handler 处理）
            pass

        else:
            logger.debug(f"[WS] 未知消息类型: {msg_type}")

    async def send_to_client(self, websocket: WebSocketServerProtocol, message: Dict[str, Any]):
        """
        发送消息到指定客户端

        Args:
            websocket: WebSocket 连接
            message: 消息数据
        """
        try:
            await websocket.send(json.dumps(message))
            self.stats["messages_sent"] += 1
        except Exception as e:
            logger.error(f"[WS] 发送消息失败: {e}")
            self.stats["errors"] += 1

    async def broadcast(self, message: Dict[str, Any]):
        """
        广播消息到所有客户端

        Args:
            message: 消息数据
        """
        msg_type = message.get("type")
        logger.debug(f"[WS] broadcast 被调用，消息类型: {msg_type}")
        logger.debug(f"[WS] 当前连接的客户端数: {len(self.clients)}")

        if not self.clients:
            logger.warning("[WS] ⚠️ 没有连接的客户端，跳过广播")
            return

        message_str = json.dumps(message)
        logger.debug(f"[WS] 📤 消息内容: {message_str}")

        tasks = []

        for idx, client in enumerate(self.clients, 1):
            logger.debug(
                f"[WS] 准备发送到客户端 {idx}/{len(self.clients)}: {client.remote_address}"
            )
            tasks.append(self._safe_send(client, message_str))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            logger.debug(f"[WS] 所有发送任务完成，结果: {results}")

        logger.debug(f"[WS] ✅ 广播完成: {msg_type} -> {len(self.clients)} 个客户端")

    async def _safe_send(self, websocket: WebSocketServerProtocol, message_str: str):
        """
        安全地发送消息（捕获异常）

        Args:
            websocket: WebSocket 连接
            message_str: 消息字符串
        """
        try:
            await websocket.send(message_str)
            self.stats["messages_sent"] += 1
            logger.debug(f"[WS] ✅ 消息已发送到 {websocket.remote_address}")
        except Exception as e:
            logger.error(f"[WS] ❌ 发送失败: {e}")
            logger.error(f"[WS] 消息内容: {message_str[:200]}...")
            self.stats["errors"] += 1

    def _on_config_changed(self, key: str, old_value: Any, new_value: Any):
        """
        配置变化回调

        当 WebSocket 配置变化时：
        1. 先通知所有连接的扩展配置将变化
        2. 然后重启服务器

        Args:
            key: 配置键
            old_value: 旧值
            new_value: 新值
        """
        logger.info(f"[WS] 检测到配置变化: {key} = {new_value}")

        # 读取新配置
        config = get_unified_config()
        new_host = config.get_websocket_host()
        new_port = config.get_websocket_port()

        # 检查是否需要重启
        if new_host != self.host or new_port != self.port:
            logger.info(
                f"[WS] WebSocket 地址变化: ws://{self.host}:{self.port} -> ws://{new_host}:{new_port}"
            )
            logger.info("[WS] 正在重启服务器...")

            # ⭐ 关键：在重启前先通知所有客户端
            new_url = f"ws://{new_host}:{new_port}"
            self._notify_config_change(new_url)

            # 给客户端一点时间处理通知（1 秒）
            import time

            time.sleep(1)

            # 在事件循环中调度重启任务
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._restart_server(new_host, new_port), self._loop
                )
            else:
                logger.warning("[WS] 事件循环未运行，无法自动重启服务器")
                logger.warning("[WS] 请手动重启应用以应用新配置")

            # 更新本地配置
            self.host = new_host
            self.port = new_port
        else:
            logger.info("[WS] WebSocket 地址未变化，无需重启")

    def _notify_config_change(self, new_websocket_url: str):
        """
        通知所有连接的客户端配置将变化

        Args:
            new_websocket_url: 新的 WebSocket URL
        """
        logger.info(f"[WS] 通知所有客户端配置变化: {new_websocket_url}")

        message = {
            "type": "config_change",
            "new_websocket_url": new_websocket_url,
            "timestamp": time.time(),
        }

        # 在后台线程中发送消息（同步转异步）
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(message), self._loop)
        else:
            logger.warning("[WS] 无法通知客户端：事件循环未运行")

    async def _restart_server(self, new_host: str, new_port: int):
        """
        重启 WebSocket 服务器

        Args:
            new_host: 新的主机地址
            new_port: 新的端口
        """
        logger.info(f"[WS] 开始重启服务器到 ws://{new_host}:{new_port}")

        # 1. 停止现有服务器
        try:
            await self.stop()
            logger.info("[WS] 旧服务器已停止")
        except Exception as e:
            logger.error(f"[WS] 停止服务器失败: {e}")

        # 2. 启动新服务器
        try:
            await self.start()
            logger.info(f"[WS] 服务器已重启: ws://{new_host}:{new_port}")
        except Exception as e:
            logger.error(f"[WS] 重启服务器失败: {e}")

    def set_message_handler(self, handler: Callable[[Dict[str, Any]], None]):
        """
        设置消息处理器（用于写入队列文件等）

        Args:
            handler: 消息处理函数
        """
        self.message_handler = handler

    async def start(self):
        """启动 WebSocket 服务器（阻塞）"""
        self._is_running = True

        logger.info(f"[WS] 服务器已启动: ws://{self.host}:{self.port}")

        # ⭐ 从配置读取最大消息大小（默认 50 MB）
        config = get_unified_config()
        max_size = config.get_websocket_max_message_size()

        logger.info(f"[WS] 最大消息大小: {max_size / 1024 / 1024:.1f} MB")

        # ⭐ 端口占用重试：如果上一次录制的 WS 服务器未正常关闭，等待端口释放
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with serve(self.handle_client, self.host, self.port, max_size=max_size):
                    # 服务器持续运行，直到 _serve_future 被取消
                    self._serve_future = asyncio.get_event_loop().create_future()
                    try:
                        await self._serve_future
                    except asyncio.CancelledError:
                        logger.info("[WS] 服务器收到停止信号")
                return  # 正常退出
            except OSError as e:
                if e.errno == 10048 and attempt < max_retries - 1:  # WSAEADDRINUSE on Windows
                    logger.warning(f"[WS] 端口 {self.port} 被占用，等待释放... (重试 {attempt + 1}/{max_retries})")
                    await asyncio.sleep(2)
                else:
                    self._is_running = False
                    raise

    def start_in_thread(self):
        """在后台线程中启动服务器"""
        import threading

        # 使用事件同步，确保 _loop 已经设置
        loop_ready = threading.Event()

        def run_server():
            # 创建新的事件循环并保存引用
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            # 通知主线程，事件循环已准备就绪
            loop_ready.set()
            try:
                self._loop.run_until_complete(self.start())
            except RuntimeError:
                # stop_sync() 会先取消 Future 再停止循环，此处 RuntimeError 是预期行为
                pass

        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()

        # 等待事件循环准备就绪（最多 5 秒）
        if loop_ready.wait(timeout=5):
            logger.info("[WS] 服务器已在后台线程启动（事件循环已就绪）")
        else:
            logger.error("[WS] 等待事件循环超时！")

    async def stop(self):
        """停止 WebSocket 服务器"""
        logger.info("[WS] 正在停止服务器...")
        self._is_running = False

        # 取消 serve 阻塞的 Future，使 async with serve() 退出
        if self._serve_future and not self._serve_future.done():
            self._serve_future.cancel()

        # 关闭所有客户端连接
        for client in self.clients:
            try:
                await client.close()
            except Exception:
                pass

        self.clients.clear()
        logger.info("[WS] 服务器已停止")

    def stop_sync(self):
        """同步停止 WebSocket 服务器（从非异步上下文调用）"""
        self._is_running = False
        if self._loop and not self._loop.is_closed():
            # 在 WS 的事件循环中调度 stop
            future = asyncio.run_coroutine_threadsafe(self.stop(), self._loop)
            try:
                future.result(timeout=5)
            except Exception as e:
                logger.warning(f"[WS] 同步停止时出错: {e}")
            # 停止事件循环，使后台线程退出
            self._loop.call_soon_threadsafe(self._loop.stop)
        else:
            logger.debug("[WS] 无事件循环可停止")

    @property
    def is_running(self) -> bool:
        """检查服务器是否运行"""
        return self._is_running

    @property
    def has_clients(self) -> bool:
        """检查是否有客户端连接"""
        return len(self.clients) > 0
