"""
浏览器录制器模块（WebSocket 架构版本）

实现通过浏览器扩展与 Mexemplar 实时通信，并通过 Playwright 启动浏览器。
"""


import asyncio
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from src.data.unified_config import get_unified_config
from src.utils.events import emit
from src.utils.helpers import get_default_data_dir

from .accessibility_recorder import AccessibilityRecorder
from .browser import (
    AsyncEventLoopRunner,
    BrowserAction,
    ControlStartResult,
    DuckDBRecordingPersister,
    PlaywrightRecordingDriver,
    RecordingControlPort,
    RecordingMode,
    RecordingRuntimeState,
    RecordingWebSocketCoordinator,
)
from .proxy_recorder import ProxyRecorder

logger = logging.getLogger(__name__)

_ws_server_lock = threading.Lock()

try:
    from playwright.async_api import (
        Browser,
        BrowserContext,
        Page,
        async_playwright,
    )

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    Browser = BrowserContext = Page = Any
    async_playwright = None
    logger.warning("Playwright未安装，浏览器录制功能将不可用")


class _RecordingControlAdapter(RecordingControlPort):
    def __init__(self, recorder: "BrowserRecorder") -> None:
        self._recorder = recorder

    async def begin_extension_recording(self, websocket=None) -> ControlStartResult:
        return await self._recorder._begin_extension_recording(websocket)

    async def finish_extension_recording(self, websocket=None) -> Dict[str, Any]:
        return await self._recorder._finish_extension_recording(websocket)

    def emit_browser_action(self, message: Dict[str, Any]) -> None:
        self._recorder._emit_browser_action(message)


class BrowserRecorder:
    _shared_ws_server = None

    def __init__(self, config=None, storage_path: Optional[Path] = None):
        if config is not None:
            logger.warning(
                "[BrowserRecorder] config 参数已废弃，所有配置现在通过 get_unified_config() 访问"
            )

        self._unified_config = get_unified_config()
        self._is_recording = False
        self._recording_id: Optional[str] = None
        self._recording_start_time: Optional[float] = None
        self._queue_write_lock = threading.Lock()
        self._active_recording_mode = RecordingMode.BROWSER
        self._recording_startup_in_progress = False
        self.on_action: Optional[Callable[[BrowserAction], None]] = None
        self._action_queue_path: Optional[Path] = None
        self._use_duckdb = True
        self._screenshot_hook = None
        self._last_browser_action_ts: float = 0.0
        self._screenshot_queue_path: Optional[Path] = None

        if storage_path is None:
            storage_path = get_default_data_dir() / "recordings"
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self._proxy_recorder = ProxyRecorder()
        self._accessibility_recorder = AccessibilityRecorder()
        self._loop_runner = AsyncEventLoopRunner(logger=logger)
        self._playwright_driver = PlaywrightRecordingDriver(
            storage_path=self.storage_path,
            unified_config=self._unified_config,
            logger=logger,
        )
        self._duckdb_persister = DuckDBRecordingPersister(logger=logger)
        self._ws_coordinator = RecordingWebSocketCoordinator(
            runtime_state_provider=self._get_runtime_state,
            control_port=_RecordingControlAdapter(self),
            queue_write_lock=self._queue_write_lock,
            logger=logger,
            shared_server_getter=lambda: BrowserRecorder._shared_ws_server,
            shared_server_setter=self._set_shared_ws_server,
            ws_server_lock=_ws_server_lock,
        )

    @classmethod
    def _set_shared_ws_server(cls, server) -> None:
        cls._shared_ws_server = server

    @property
    def _event_loop(self):
        return self._loop_runner.event_loop

    @_event_loop.setter
    def _event_loop(self, loop) -> None:
        self._loop_runner.event_loop = loop

    @property
    def _browser(self):
        return self._playwright_driver.browser

    @_browser.setter
    def _browser(self, value) -> None:
        self._playwright_driver.browser = value

    @property
    def _context(self):
        return self._playwright_driver.context

    @_context.setter
    def _context(self, value) -> None:
        self._playwright_driver.context = value

    @property
    def _page(self):
        return self._playwright_driver.page

    @_page.setter
    def _page(self, value) -> None:
        self._playwright_driver.page = value

    @property
    def _playwright_ws_client(self):
        return self._playwright_driver.playwright_ws_client

    @_playwright_ws_client.setter
    def _playwright_ws_client(self, value) -> None:
        self._playwright_driver.playwright_ws_client = value

    @property
    def _playwright_launch_token(self):
        return self._playwright_driver.playwright_launch_token

    @_playwright_launch_token.setter
    def _playwright_launch_token(self, value) -> None:
        self._playwright_driver.playwright_launch_token = value

    @property
    def _ws_server(self):
        return self._ws_coordinator.ws_server

    @_ws_server.setter
    def _ws_server(self, server) -> None:
        self._ws_coordinator.ws_server = server

    @property
    def page(self) -> Optional[Page]:
        return self._page

    @property
    def playwright_driver(self) -> PlaywrightRecordingDriver:
        """暴露底层 Playwright 录制驱动。"""
        return self._playwright_driver

    @property
    def _is_extension_recording(self) -> bool:
        return (
            self._is_recording and self._active_recording_mode == RecordingMode.EXTENSION_TRIGGERED
        )

    def _get_runtime_state(self) -> RecordingRuntimeState:
        return RecordingRuntimeState(
            recording_id=self._recording_id,
            action_queue_path=self._action_queue_path,
            active_recording_mode=self._active_recording_mode,
            startup_in_progress=self._recording_startup_in_progress,
            playwright_ws_client=self._playwright_ws_client,
            is_recording=self._is_recording,
        )

    def _get_queue_paths(self, recording_id: str):
        from .queue_paths import (
            get_recording_actions_queue_path,
            get_recording_screenshots_queue_path,
        )

        return get_recording_actions_queue_path(recording_id), get_recording_screenshots_queue_path(
            recording_id
        )

    def _stop_sub_recorders(self) -> None:
        for recorder, name in [
            (self._proxy_recorder, "代理"),
            (self._accessibility_recorder, "Accessibility"),
        ]:
            try:
                recorder.stop()
            except Exception as exc:
                logger.warning(f"停止{name}录制器失败: {exc}")

    def _reset_recording_state(self) -> None:
        self._recording_id = None
        self._recording_start_time = None
        self._action_queue_path = None
        self._screenshot_queue_path = None
        self._screenshot_hook = None
        self._last_browser_action_ts = 0.0
        self._is_recording = False
        self._playwright_ws_client = None
        self._active_recording_mode = RecordingMode.BROWSER

    def cleanup(self):
        try:
            self._ws_coordinator.stop_ingress()

            if self._screenshot_hook:
                try:
                    self._screenshot_hook.stop()
                except Exception as exc:
                    logger.warning(f"停止截图钩子失败: {exc}")
                self._screenshot_hook = None

            if self._is_extension_recording:
                try:
                    self._stop_sub_recorders()
                finally:
                    self._reset_recording_state()

            if self._event_loop and not self._event_loop.is_closed():
                try:
                    self._run_async(self._close_browser(), timeout=10)
                except Exception as exc:
                    logger.warning(f"关闭浏览器失败: {exc}")

            try:
                self._cleanup_playwright_extension_bundle()
            except Exception as exc:
                logger.warning(f"清理扩展目录失败: {exc}")

            try:
                self._playwright_driver.cleanup_user_data_dir()
            except Exception as exc:
                logger.warning(f"清理用户数据目录失败: {exc}")

            self._ws_coordinator.stop_ws_server()

            try:
                self._duckdb_persister.close()
            except Exception as exc:
                logger.warning(f"关闭数据库连接失败: {exc}")

            try:
                self._loop_runner.stop()
            except Exception as exc:
                logger.warning(f"停止事件循环失败: {exc}")

            logger.info("资源清理完成")
        except Exception as exc:
            logger.error(f"清理资源时出错: {exc}", exc_info=True)

    def _run_async(self, coro, timeout: float = 120):
        return self._loop_runner.run(coro, timeout=timeout)

    async def _launch_browser_with_subprocess(self, start_url: Optional[str] = None) -> bool:
        return await self._playwright_driver.launch_browser_with_subprocess(
            start_url=start_url,
            recording_id=self._recording_id,
            playwright_available=PLAYWRIGHT_AVAILABLE,
            async_playwright_factory=async_playwright,
            prepare_extension_bundle=self._prepare_playwright_extension_bundle,
            validate_extension_path=self._validate_extension_path,
            classify_extension_targets=self._classify_extension_targets,
            sleep_coro=asyncio.sleep,
        )

    def _prepare_playwright_extension_bundle(self, extension_source_path: Path) -> Path:
        return self._playwright_driver.prepare_playwright_extension_bundle(
            extension_source_path,
            recording_id=self._recording_id,
        )

    def _cleanup_playwright_extension_bundle(self) -> None:
        self._playwright_driver.cleanup_playwright_extension_bundle()

    @staticmethod
    def _classify_extension_targets(
        all_targets: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        return PlaywrightRecordingDriver.classify_extension_targets(all_targets)

    @staticmethod
    def _validate_extension_path(extension_path: str) -> str:
        return PlaywrightRecordingDriver.validate_extension_path(extension_path)

    @staticmethod
    @contextmanager
    def _suppress_playwright_logs():
        with PlaywrightRecordingDriver.suppress_playwright_logs():
            yield

    async def _close_browser(self):
        await self._playwright_driver.close_browser(suppress_logs=self._suppress_playwright_logs)

    def _create_ws_server(self):
        from .websocket_server import WebSocketServer

        return WebSocketServer(
            host=self._unified_config.get_websocket_host(),
            port=self._unified_config.get_websocket_port(),
        )

    def _ensure_ws_server(self):
        self._ws_coordinator.ensure_ws_server(
            ws_server_factory=self._create_ws_server,
            message_handler=self._handle_ws_message,
            control_handler=self._submit_control_message,
        )

    def arm_extension_triggered_mode(self) -> None:
        self._ensure_ws_server()

    def _submit_control_message(self, data: Dict[str, Any], websocket) -> None:
        self._ws_coordinator.submit_control_message(data, websocket)

    def _handle_ws_message(self, message: Dict[str, Any]):
        self._ws_coordinator.handle_ws_message(message)

    def _emit_browser_action(self, message: Dict[str, Any]) -> None:
        self._last_browser_action_ts = time.time()
        if not self.on_action:
            return

        action_payload = message.get("action", {})
        action = BrowserAction(
            action_type=action_payload.get("action_type"),
            timestamp=action_payload.get("timestamp", time.time()),
            dom_element=action_payload.get("dom_element"),
            network_requests=action_payload.get("network_requests", []),
            url=action_payload.get("url"),
            parameters=action_payload.get("parameters", {}),
        )
        self.on_action(action)

    async def _begin_extension_recording(self, websocket=None) -> ControlStartResult:
        del websocket

        if self._recording_startup_in_progress:
            return ControlStartResult(
                status="error",
                error="浏览器录制正在启动中，请稍后重试",
            )

        if self._is_recording:
            return ControlStartResult(
                status="error",
                error="已有录制进行中，请先停止当前录制",
            )

        recording_id = str(uuid.uuid4())
        queue_file, self._screenshot_queue_path = self._get_queue_paths(recording_id)
        start_time = time.time()

        try:
            self._accessibility_recorder.start(
                recording_id,
                queue_file,
                queue_write_lock=self._queue_write_lock,
            )
            proxy_started = self._proxy_recorder.start(
                recording_id,
                queue_file,
                queue_write_lock=self._queue_write_lock,
            )
            if not proxy_started:
                raise RuntimeError("代理录制启动失败")
        except Exception as exc:
            logger.warning(f"[BrowserRecorder] 扩展触发录制启动失败: {exc}")
            self._stop_sub_recorders()
            self._reset_recording_state()
            return ControlStartResult(
                status="error",
                error="扩展录制启动失败，请检查代理和辅助录制器状态",
            )

        self._recording_id = recording_id
        self._recording_start_time = start_time
        self._action_queue_path = queue_file
        self._is_recording = True
        self._active_recording_mode = RecordingMode.EXTENSION_TRIGGERED

        emit(
            "recording_started",
            event_data={
                "session_id": recording_id,
                "recording_mode": RecordingMode.EXTENSION_TRIGGERED,
                "start_time": start_time,
            },
        )
        logger.info(f"[BrowserRecorder] 扩展触发录制已开始: {recording_id}")
        return ControlStartResult(status="started", recording_id=recording_id)

    async def _handle_control_message(self, data: Dict[str, Any], websocket) -> None:
        await self._ws_coordinator.handle_control_message(data, websocket)

    async def _finish_extension_recording(self, websocket=None) -> Dict[str, Any]:
        if not self._is_extension_recording:
            return {
                "recording_id": self._recording_id,
                "queue_file": str(self._action_queue_path) if self._action_queue_path else None,
                "action_count": 0,
                "start_time": self._recording_start_time,
                "end_time": time.time(),
                "recording_mode": RecordingMode.EXTENSION_TRIGGERED,
            }

        start_time = self._recording_start_time
        recording_id = self._recording_id
        queue_file = self._action_queue_path or self._get_queue_paths(recording_id)[0]
        end_time = time.time()

        self._stop_sub_recorders()

        if websocket is None and self._ws_server:
            self._send_stop_command_via_ws()
        elif websocket is not None and self._ws_server:
            await self._ws_server.send_to_client(
                websocket,
                {"type": "recording_control_reply", "status": "stopped"},
            )

        action_count = 0
        save_ok = True
        if self._use_duckdb:
            try:
                action_count = self._save_to_duckdb(end_time) or 0
            except Exception as exc:
                logger.error(f"保存扩展触发录制到 DuckDB 失败: {exc}")
                save_ok = False

        if save_ok:
            from src.recording.queue_paths import delete_queue_file
            for qpath in [queue_file, self._screenshot_queue_path]:
                delete_queue_file(qpath)

        emit(
            "recording_stopped",
            event_data={
                "recording_id": recording_id,
                "recording_mode": RecordingMode.EXTENSION_TRIGGERED,
            },
        )
        emit(
            "recording_completed",
            event_data={
                "recording_id": recording_id,
                "recording_mode": RecordingMode.EXTENSION_TRIGGERED,
                "start_time": start_time,
                "end_time": end_time,
                "queue_file": str(queue_file),
                "action_count": action_count,
                "metadata": {},
            },
        )

        self._reset_recording_state()
        logger.info(f"[BrowserRecorder] 扩展触发录制已停止: {recording_id}")
        return {
            "recording_id": recording_id,
            "queue_file": str(queue_file),
            "action_count": action_count,
            "start_time": start_time,
            "end_time": end_time,
            "recording_mode": RecordingMode.EXTENSION_TRIGGERED,
        }

    async def _stop_extension_triggered_recording(self, websocket=None) -> Dict[str, Any]:
        return await self._finish_extension_recording(websocket)

    def _wait_for_target_ws_client(
        self,
        timeout: int = 20,
        existing_clients: Optional[Set[Any]] = None,
        expected_metadata: Optional[Dict[str, Any]] = None,
    ):
        return self._ws_coordinator.wait_for_target_ws_client(
            timeout=timeout,
            existing_clients=existing_clients,
            expected_metadata=expected_metadata,
            time_fn=time.time,
            sleep_fn=time.sleep,
        )

    def _send_start_command_via_ws(self, recording_id: str, websocket=None):
        self._ws_coordinator.send_start_command_via_ws(
            recording_id,
            websocket=websocket,
            time_fn=time.time,
        )

    def _send_stop_command_via_ws(self, websocket=None):
        self._ws_coordinator.send_stop_command_via_ws(
            self._recording_id,
            websocket=websocket,
            time_fn=time.time,
        )

    def start_recording(
        self, start_url: Optional[str] = None, recording_id: Optional[str] = None
    ) -> bool:
        return self._run_async(self._async_start_recording(start_url, recording_id))

    async def _async_start_recording(
        self, start_url: Optional[str] = None, recording_id: Optional[str] = None
    ) -> bool:
        if self._is_recording or self._recording_startup_in_progress:
            logger.warning("录制已在进行中或正在启动")
            return False

        self._recording_startup_in_progress = True
        startup_succeeded = False
        try:
            self._recording_id = recording_id or str(uuid.uuid4())
            self._recording_start_time = time.time()
            self._last_browser_action_ts = time.time()
            self._playwright_ws_client = None

            logger.info(f"开始浏览器录制，会话ID: {self._recording_id}")

            self._action_queue_path, self._screenshot_queue_path = self._get_queue_paths(self._recording_id)

            if not self._ws_server or not self._ws_server.is_running:
                logger.warning("[BrowserRecorder] WS 服务器未运行，尝试启动...")
            self._ensure_ws_server()
            existing_clients = set(self._ws_server.clients) if self._ws_server else set()

            logger.info("启动浏览器并加载扩展...")
            if not await self._launch_browser_with_subprocess(start_url):
                logger.error("启动浏览器失败")
                return False

            logger.info("等待浏览器扩展连接 WebSocket...")
            target_ws_client = self._wait_for_target_ws_client(
                timeout=20,
                existing_clients=existing_clients,
                expected_metadata=(
                    {"launch_token": self._playwright_launch_token}
                    if self._playwright_launch_token
                    else None
                ),
            )
            if not target_ws_client:
                self._playwright_ws_client = None
                logger.error("WebSocket 连接超时")
                logger.error("请检查：")
                logger.error("  1. Python WebSocket 服务器是否正常运行")
                logger.error("  2. 浏览器扩展是否正确加载")
                logger.error("  3. 防火墙是否阻止了连接")
                return False

            self._playwright_ws_client = target_ws_client
            logger.info("WebSocket 连接成功")

            logger.info("等待标签页加载完成...")
            await asyncio.sleep(2)

            logger.info(f"发送开始录制命令: {self._recording_id}")
            self._send_start_command_via_ws(
                self._recording_id,
                websocket=self._playwright_ws_client,
            )

            self._is_recording = True
            self._active_recording_mode = RecordingMode.BROWSER
            startup_succeeded = True

            # 启动截图钩子
            browser_pid = self._playwright_driver.resolve_browser_pid()
            from .browser_screenshot_hook import BrowserScreenshotHook
            self._screenshot_hook = BrowserScreenshotHook(
                recording_id=self._recording_id,
                screenshots_queue_file=self._screenshot_queue_path,
                browser_pid=browser_pid,
                jpeg_quality=self._unified_config.get("recording.screenshot_quality", 85),
                after_delay=self._unified_config.get("recording.screenshot_delay_after_action", 0.2),
                logger=logger,
            )
            if not self._screenshot_hook.start():
                self._screenshot_hook = None
                logger.warning("截图钩子未启动（非 Windows 或依赖缺失），录制继续但不采集截图")

            logger.info("浏览器录制已启动 (WebSocket 模式)")
            logger.info(f"   - recording_id: {self._recording_id}")
            logger.info(f"   - 队列文件: {self._action_queue_path}")
            logger.info(
                f"   - WebSocket: ws://{self._unified_config.get_websocket_host()}:"
                f"{self._unified_config.get_websocket_port()}"
            )
            return True
        finally:
            self._recording_startup_in_progress = False
            if not startup_succeeded and not self._is_recording:
                self._reset_recording_state()
                if self._context is None:
                    self._cleanup_playwright_extension_bundle()

    def stop_recording(self) -> Dict[str, Any]:
        return self._run_async(self._async_stop_recording())

    async def _async_stop_recording(self) -> Dict[str, Any]:
        if self._is_extension_recording:
            return await self._stop_extension_triggered_recording()

        if not self._is_recording:
            return {
                "recording_id": self._recording_id,
                "queue_file": None,
                "action_count": 0,
                "start_time": self._recording_start_time,
                "end_time": time.time(),
                "recording_mode": self._active_recording_mode,
            }

        logger.info("停止浏览器录制")
        end_time = time.time()

        # 保存结果字段（在 reset 之前读取）
        result_recording_id = self._recording_id
        result_queue_path = self._action_queue_path
        result_screenshot_path = self._screenshot_queue_path
        result_start_time = self._recording_start_time
        result_recording_mode = self._active_recording_mode

        # 发送停止录制命令 → drain → 停止截图钩子 → 关闭浏览器 → 保存 → 清理

        try:
            logger.info("发送停止录制命令...")
            self._send_stop_command_via_ws(websocket=self._playwright_ws_client)
        except Exception as exc:
            logger.warning(f"发送停止命令失败: {exc}")

        await self._wait_for_stop_drain()

        try:
            if self._ws_server:
                self._ws_server.set_message_handler(None)
                self._ws_server.set_control_handler(None)
        except Exception as exc:
            logger.warning(f"停止 WS ingress 失败: {exc}")

        if self._screenshot_hook:
            try:
                self._screenshot_hook.stop()
            except Exception as exc:
                logger.warning(f"停止截图钩子失败: {exc}")
            self._screenshot_hook = None

        try:
            logger.info("关闭浏览器...")
            await self._close_browser()
        except Exception as exc:
            logger.warning(f"关闭浏览器失败: {exc}")

        try:
            self._cleanup_playwright_extension_bundle()
        except Exception as exc:
            logger.warning(f"清理扩展目录失败: {exc}")

        action_count = 0
        save_ok = True
        if self._use_duckdb:
            try:
                logger.info("开始保存录制数据到 DuckDB...")
                action_count = self._save_to_duckdb(end_time)
                logger.info("DuckDB 保存完成")
            except Exception as exc:
                logger.error(f"保存到 DuckDB 失败: {exc}")
                save_ok = False

        if save_ok:
            from src.recording.queue_paths import delete_queue_file
            for qpath in [result_queue_path, result_screenshot_path]:
                delete_queue_file(qpath)

        try:
            self._playwright_driver.cleanup_user_data_dir()
        except Exception as exc:
            logger.warning(f"清理用户数据目录失败: {exc}")

        self._reset_recording_state()

        logger.info("浏览器录制已停止 (WebSocket 模式)")
        logger.info(f"   - recording_id: {result_recording_id}")
        logger.info(f"   - 队列文件: {result_queue_path}")
        logger.info(f"   - 事件数量: {action_count}")

        return {
            "recording_id": result_recording_id,
            "queue_file": str(result_queue_path) if result_queue_path else None,
            "action_count": action_count,
            "start_time": result_start_time,
            "end_time": end_time,
            "recording_mode": result_recording_mode,
        }

    async def _wait_for_stop_drain(self) -> None:
        """等待最后一拍 action 到达（WS ingress 仍开启）。"""
        drain_timeout = 1.0
        quiet_window = 0.25
        start = time.time()
        while time.time() - start < drain_timeout:
            if time.time() - self._last_browser_action_ts >= quiet_window:
                return
            await asyncio.sleep(0.05)
        logger.warning("stop drain 超时（1s），可能有晚到的 action 未入队")

    def _save_to_duckdb(self, end_time: float) -> int:
        return self._duckdb_persister.save_to_duckdb(
            recording_id=self._recording_id,
            recording_start_time=self._recording_start_time,
            action_queue_path=self._action_queue_path,
            active_recording_mode=self._active_recording_mode,
            end_time=end_time,
        )

    def is_recording(self) -> bool:
        return self._is_recording
