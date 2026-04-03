"""
WebSocket 服务器管理器

提供自动启动、优雅停止、健康检查等功能
"""

import asyncio
import logging
import threading
import time
from typing import Optional, Callable
from .websocket_handler import WebSocketHandler

logger = logging.getLogger(__name__)


class WebSocketServerManager:
    """
    WebSocket 服务器管理器

    负责管理 WebSocket 服务器的生命周期，包括：
    - 自动启动
    - 端口冲突检测
    - 优雅停止
    - 健康检查
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8766,
        auto_start: bool = True,
        startup_timeout: float = 5.0,
    ):
        """
        初始化 WebSocket 服务器管理器

        Args:
            host: 监听地址
            port: 监听端口
            auto_start: 是否自动启动
            startup_timeout: 启动超时时间（秒）
        """
        self.host = host
        self.port = port
        self.startup_timeout = startup_timeout

        # WebSocket 处理器
        self.ws_handler: Optional[WebSocketHandler] = None

        # 事件循环和线程
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._server_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 状态管理
        self._is_running = False
        self._startup_failed = False
        self._startup_error: Optional[str] = None

        # 启动同步
        self._startup_lock = threading.Lock()
        self._startup_complete = threading.Condition(self._startup_lock)

        # 回调函数
        self._on_error: Optional[Callable] = None

        if auto_start:
            self.start()

    @property
    def is_running(self) -> bool:
        """服务器是否正在运行"""
        return self._is_running and self.ws_handler is not None

    @property
    def server_url(self) -> str:
        """获取服务器 URL"""
        return f"ws://{self.host}:{self.port}"

    def on_error(self, callback: Callable):
        """注册错误回调"""
        self._on_error = callback

    def start(self) -> bool:
        """
        启动 WebSocket 服务器（阻塞式，等待启动完成）

        Returns:
            是否启动成功
        """
        with self._startup_lock:
            # 检查是否已经启动
            if self._is_running:
                logger.warning(f"WebSocket 服务器已在运行: {self.server_url}")
                return True

            logger.info(f"启动 WebSocket 服务器: {self.server_url}")

            # 创建事件循环
            self._event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._event_loop)

            # 创建 WebSocket 处理器
            self.ws_handler = WebSocketHandler(host=self.host, port=self.port)

            # 启动服务器线程
            self._stop_event.clear()
            self._server_thread = threading.Thread(
                target=self._run_server,
                name="WebSocketServerThread",
                daemon=True,
            )
            self._server_thread.start()

            # 等待启动完成（带超时）
            start_time = time.time()
            with self._startup_complete:
                while not self._is_running and not self._startup_failed:
                    remaining = self.startup_timeout - (time.time() - start_time)
                    if remaining <= 0:
                        logger.error(f"WebSocket 服务器启动超时（{self.startup_timeout}秒）")
                        self._startup_failed = True
                        self._startup_error = "启动超时"
                        break

                    # 等待启动完成或超时
                    self._startup_complete.wait(timeout=min(1.0, remaining))

            # 检查启动结果
            if self._is_running:
                logger.info(f"✅ WebSocket 服务器启动成功: {self.server_url}")

                return True
            else:
                error_msg = self._startup_error or "未知错误"
                logger.error(f"❌ WebSocket 服务器启动失败: {error_msg}")

                # 调用错误回调
                if self._on_error:
                    try:
                        self._on_error(self, error_msg)
                    except Exception as e:
                        logger.error(f"执行错误回调失败: {e}", exc_info=True)

                return False

    def _run_server(self):
        """
        运行 WebSocket 服务器（在后台线程中）

        该方法在独立线程中运行，负责：
        1. 启动 WebSocket 服务器
        2. 运行事件循环
        3. 处理停止信号
        """
        try:
            # 在当前线程运行事件循环
            asyncio.set_event_loop(self._event_loop)

            # 启动服务器
            logger.info(f"WebSocket 服务器线程启动: {self.server_url}")

            # 使用 run_until_complete 启动服务器
            startup_task = self._event_loop.create_task(self.ws_handler.start())

            # 等待服务器启动完成
            def on_server_started():
                with self._startup_complete:
                    self._is_running = True
                    self._startup_complete.notify_all()
                    logger.info(f"WebSocket 服务器就绪: {self.server_url}")

            # 添加启动完成的回调
            startup_task.add_done_callback(lambda t: on_server_started())

            # 运行事件循环
            self._event_loop.run_forever()

        except OSError as e:
            error_msg = str(e)
            if "Address already in use" in error_msg or "10048" in error_msg:
                error_msg = f"端口 {self.port} 已被占用"
                logger.error(f"WebSocket 服务器启动失败: {error_msg}")
                logger.error(f"提示: 请检查是否有其他程序正在使用端口 {self.port}")
            else:
                logger.error(f"WebSocket 服务器启动失败: {e}", exc_info=True)

            with self._startup_complete:
                self._startup_failed = True
                self._startup_error = error_msg
                self._startup_complete.notify_all()

        except Exception as e:
            logger.error(f"WebSocket 服务器运行失败: {e}", exc_info=True)

            with self._startup_complete:
                self._startup_failed = True
                self._startup_error = str(e)
                self._startup_complete.notify_all()

        finally:
            logger.info("WebSocket 服务器线程退出")
            with self._startup_complete:
                self._is_running = False
                self._startup_complete.notify_all()

    def stop(self):
        """停止 WebSocket 服务器（优雅关闭）"""
        if not self._is_running:
            logger.warning("WebSocket 服务器未运行")
            return

        logger.info("停止 WebSocket 服务器...")

        # 设置停止标志
        self._stop_event.set()

        # 停止 WebSocket 处理器
        if self.ws_handler:
            # 在事件循环中停止服务器
            if self._event_loop and self._event_loop.is_running():
                # 如果事件循环正在运行，调度停止任务
                future = asyncio.run_coroutine_threadsafe(
                    self.ws_handler.stop(),
                    self._event_loop,
                )
                try:
                    # 等待停止完成（最多 5 秒）
                    future.result(timeout=5.0)
                except Exception as e:
                    logger.error(f"停止 WebSocket 处理器失败: {e}")
            else:
                # 如果事件循环未运行，直接停止
                try:
                    asyncio.run(self.ws_handler.stop())
                except Exception as e:
                    logger.error(f"停止 WebSocket 处理器失败: {e}")

        # 停止事件循环
        if self._event_loop:
            try:
                self._event_loop.call_soon_threadsafe(self._event_loop.stop)
            except Exception as e:
                logger.error(f"停止事件循环失败: {e}")

        # 等待线程结束
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=5.0)
            if self._server_thread.is_alive():
                logger.warning("WebSocket 服务器线程未能在 5 秒内停止")

        self._is_running = False
        logger.info("WebSocket 服务器已停止")

    def get_handler(self) -> Optional[WebSocketHandler]:
        """
        获取 WebSocket 处理器

        Returns:
            WebSocket 处理器，如果服务器未运行则返回 None
        """
        return self.ws_handler if self._is_running else None

    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        """上下文管理器退出"""
        self.stop()

    def __del__(self):
        """析构函数"""
        try:
            self.stop()
        except Exception:
            pass
