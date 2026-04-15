from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, Optional, Set

from src.utils.helpers import append_jsonl

from .recorder import RecordingControlPort, RecordingMode, RecordingRuntimeState


class RecordingWebSocketCoordinator:
    def __init__(
        self,
        *,
        runtime_state_provider: Callable[[], RecordingRuntimeState],
        control_port: RecordingControlPort,
        queue_write_lock,
        logger: Optional[logging.Logger] = None,
        shared_server_getter: Optional[Callable[[], Any]] = None,
        shared_server_setter: Optional[Callable[[Any], None]] = None,
        ws_server_lock=None,
    ) -> None:
        self._runtime_state_provider = runtime_state_provider
        self._control_port = control_port
        self._queue_write_lock = queue_write_lock
        self._logger = logger or logging.getLogger(__name__)
        self._shared_server_getter = shared_server_getter or (lambda: None)
        self._shared_server_setter = shared_server_setter or (lambda _server: None)
        self._ws_server_lock = ws_server_lock
        self._ws_server = None

    @property
    def ws_server(self):
        return self._ws_server

    @ws_server.setter
    def ws_server(self, server) -> None:
        self._ws_server = server

    def ensure_ws_server(
        self,
        *,
        ws_server_factory: Callable[[], Any],
        message_handler: Callable[[Dict[str, Any]], None],
        control_handler: Callable[[Dict[str, Any], Any], None],
    ) -> None:
        with self._ws_server_lock:
            server = self._shared_server_getter()
            should_start = server is None or not server.is_running
            if should_start:
                server = ws_server_factory()
                self._shared_server_setter(server)

            self._ws_server = server
            self._ws_server.set_message_handler(message_handler)
            self._ws_server.set_control_handler(control_handler)

            if should_start:
                self._ws_server.start_in_thread()
                self._logger.info("[BrowserRecorder] WS 服务器已启动（App 生命周期级别）")

    def submit_control_message(self, data: Dict[str, Any], websocket) -> None:
        if not self._ws_server or not self._ws_server.loop:
            self._logger.warning("[BrowserRecorder] WS 事件循环未就绪，忽略 control 消息")
            return

        asyncio.run_coroutine_threadsafe(
            self.handle_control_message(data, websocket),
            self._ws_server.loop,
        )

    def handle_ws_message(self, message: Dict[str, Any]) -> None:
        if message.get("type") != "browser_action":
            return

        self.write_browser_action_to_queue(message)
        self._control_port.emit_browser_action(message)

    def write_browser_action_to_queue(self, message: Dict[str, Any]) -> None:
        runtime_state = self._runtime_state_provider()
        if not runtime_state.action_queue_path:
            return

        try:
            wrapped_message = {
                "type": "browser_action",
                "recording_id": runtime_state.recording_id,
                "action": message.get("action", {}),
                "timestamp": time.time(),
            }
            append_jsonl(
                runtime_state.action_queue_path,
                wrapped_message,
                self._queue_write_lock,
            )
            self._logger.debug(
                f"[WS] 事件已写入队列文件: {message.get('action', {}).get('action_type')}"
            )
        except Exception as exc:
            self._logger.error(f"写入队列文件失败: {exc}")

    async def handle_control_message(self, data: Dict[str, Any], websocket) -> None:
        action = data.get("action")
        runtime_state = self._runtime_state_provider()

        if action == "start":
            result = await self._control_port.begin_extension_recording(websocket)
            if self._ws_server:
                reply = {
                    "type": "recording_control_reply",
                    "status": result.status,
                }
                if result.recording_id:
                    reply["recording_id"] = result.recording_id
                if result.error:
                    reply["error"] = result.error
                await self._ws_server.send_to_client(websocket, reply)
            return

        if action == "stop":
            is_extension_recording = (
                runtime_state.is_recording
                and runtime_state.active_recording_mode == RecordingMode.EXTENSION_TRIGGERED
            )
            if not is_extension_recording:
                if self._ws_server:
                    reply = {"type": "recording_control_reply", "status": "stopped"}
                    if runtime_state.startup_in_progress or runtime_state.is_recording:
                        reply = {
                            "type": "recording_control_reply",
                            "status": "error",
                            "error": "当前录制由 Mexemplar App 控制，请在 App 中停止",
                        }
                    await self._ws_server.send_to_client(websocket, reply)
                return

            await self._control_port.finish_extension_recording(websocket)
            return

        if self._ws_server:
            await self._ws_server.send_to_client(
                websocket,
                {
                    "type": "recording_control_reply",
                    "status": "error",
                    "error": f"未知 action: {action}",
                },
            )

    def wait_for_target_ws_client(
        self,
        *,
        timeout: int = 20,
        existing_clients: Optional[Set[Any]] = None,
        expected_metadata: Optional[Dict[str, Any]] = None,
        time_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        start_time = time_fn()
        existing_clients = existing_clients or set()

        while time_fn() - start_time < timeout:
            if self._ws_server:
                client = None
                if expected_metadata:
                    client = self._ws_server.get_client_by_metadata(
                        expected_metadata,
                        exclude=existing_clients,
                    )
                if client is None and expected_metadata is None:
                    client = self._ws_server.get_latest_client(exclude=existing_clients)
                if client is not None:
                    return client
            sleep_fn(0.5)

        return None

    def send_ws_command(self, message: dict, websocket=None, description: str = "命令") -> None:
        if not self._ws_server or not self._ws_server.loop:
            return

        send_coro = (
            self._ws_server.send_to_client(websocket, message)
            if websocket is not None
            else self._ws_server.broadcast(message)
        )
        future = asyncio.run_coroutine_threadsafe(send_coro, self._ws_server.loop)
        try:
            future.result(timeout=5)
            target = "向目标客户端" if websocket else "广播"
            self._logger.info(f"已通过 WebSocket {target}发送{description}")
        except asyncio.TimeoutError:
            self._logger.error(f"[WS] 发送{description}超时")
        except Exception as exc:
            self._logger.error(f"[WS] 发送{description}失败: {exc}")

    def send_start_command_via_ws(
        self,
        recording_id: str,
        *,
        websocket=None,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        message = {
            "type": "control_start",
            "recording_id": recording_id,
            "timestamp": time_fn(),
        }
        self.send_ws_command(message, websocket=websocket, description="开始录制命令")

    def send_stop_command_via_ws(
        self,
        recording_id: Optional[str],
        *,
        websocket=None,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        message = {
            "type": "control_stop",
            "recording_id": recording_id,
            "timestamp": time_fn(),
        }
        self.send_ws_command(message, websocket=websocket, description="停止录制命令")

    def stop_ingress(self) -> None:
        """停止接收新的 WS/control 消息。"""
        if self._ws_server:
            try:
                self._ws_server.set_message_handler(None)
                self._ws_server.set_control_handler(None)
            except Exception as exc:
                self._logger.warning(f"停止 WS ingress 失败: {exc}")

    def stop_ws_server(self) -> None:
        """停止 WS 服务器并清理共享引用。"""
        if not self._ws_server:
            return
        try:
            with self._ws_server_lock:
                shared = self._shared_server_getter()
                if shared is self._ws_server:
                    self._ws_server.stop_sync()
                    self._shared_server_setter(None)
                    self._logger.info("WebSocket 服务器已停止")
        except Exception as exc:
            self._logger.warning(f"停止 WebSocket 服务器失败: {exc}")
        self._ws_server = None
