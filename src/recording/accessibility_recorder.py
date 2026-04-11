"""
Accessibility 录制器模块。

使用 Windows UIAutomation 事件钩子捕获用户交互（点击、输入、窗口切换），
写入 browser_action JSONL 队列文件。
"""

from __future__ import annotations

import json
import logging
import platform
import threading
import time
from pathlib import Path
from typing import Optional

from src.utils.helpers import append_jsonl

logger = logging.getLogger(__name__)

# comtypes 默认 DEBUG 级别会疯狂刷日志（每个 COM Release 一行），直接关掉
logging.getLogger("comtypes").setLevel(logging.WARNING)

PLATFORM_SUPPORTED = platform.system() == "Windows"

EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_OBJECT_VALUECHANGE = 0x800E
EVENT_OBJECT_INVOKED = 0x8013
WINEVENT_OUTOFCONTEXT = 0x0000

if PLATFORM_SUPPORTED:
    import ctypes
    import ctypes.wintypes

    try:
        import uiautomation as auto
    except ImportError:
        auto = None
        logger.warning("uiautomation 未安装，Accessibility 录制功能不可用")


class AccessibilityRecorder:
    """Windows UIA 交互录制器。"""

    def __init__(self) -> None:
        self._recording_id: Optional[str] = None
        self._queue_file: Optional[Path] = None
        self._queue_write_lock: Optional[threading.Lock] = None
        self._hooks: list = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._current_url: str = ""
        self._callback_ref = None

    def start(self, recording_id: str, queue_file: Path, queue_write_lock: Optional[threading.Lock] = None) -> None:
        """启动 UIA 事件监听。"""
        if not PLATFORM_SUPPORTED:
            logger.warning("[Accessibility] 非 Windows 平台，跳过 UIA 录制")
            return

        self._recording_id = recording_id
        self._queue_file = Path(queue_file)
        self._queue_write_lock = queue_write_lock
        self._queue_file.parent.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        self._install_hooks()
        logger.info(f"[Accessibility] 已启动: {recording_id}")

    def stop(self) -> None:
        """停止 UIA 事件监听。"""
        if not PLATFORM_SUPPORTED:
            return

        self._remove_hooks()
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None
        logger.info("[Accessibility] 已停止")

    def _install_hooks(self) -> None:
        """安装 WinEvent hook 并启动消息泵。"""
        user32 = ctypes.windll.user32
        ole32 = ctypes.windll.ole32

        WINEVENTPROC = ctypes.CFUNCTYPE(
            None,
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.HWND,
            ctypes.wintypes.LONG,
            ctypes.wintypes.LONG,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
        )

        def hook_callback(hook, event, hwnd, id_object, id_child, thread_id, event_time):
            del hook, thread_id, event_time
            try:
                self._on_win_event(event, hwnd, id_object, id_child)
            except Exception as exc:
                logger.debug(f"[Accessibility] 事件回调异常: {exc}")

        self._callback_ref = WINEVENTPROC(hook_callback)

        def run_message_pump() -> None:
            ole32.CoInitialize(0)
            try:
                for event_id in (EVENT_OBJECT_INVOKED, EVENT_OBJECT_VALUECHANGE, EVENT_SYSTEM_FOREGROUND):
                    hook = user32.SetWinEventHook(
                        event_id,
                        event_id,
                        0,
                        self._callback_ref,
                        0,
                        0,
                        WINEVENT_OUTOFCONTEXT,
                    )
                    if hook:
                        self._hooks.append(hook)

                msg = ctypes.wintypes.MSG()
                while not self._stop_event.is_set():
                    if user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))
                    else:
                        time.sleep(0.01)
            finally:
                for hook in self._hooks:
                    user32.UnhookWinEvent(hook)
                self._hooks.clear()
                ole32.CoUninitialize()

        self._thread = threading.Thread(target=run_message_pump, daemon=True)
        self._thread.start()

    def _remove_hooks(self) -> None:
        self._stop_event.set()

    def _on_win_event(self, event: int, hwnd: int, id_object: int, id_child: int) -> None:
        del id_object, id_child
        try:
            if auto is None:
                return

            control = auto.ControlFromHandle(hwnd)
            if not control:
                return

            process_name = getattr(control, "ProcessName", "") or ""
            if "chrome" not in process_name.lower():
                return

            element_name = getattr(control, "Name", "") or ""
            element_role = getattr(control, "ControlTypeName", "") or ""

            if event == EVENT_OBJECT_INVOKED:
                self._update_url_from_chrome(control)
                self._write_event("click", element_name, element_role, self._current_url)
            elif event == EVENT_OBJECT_VALUECHANGE:
                value = self._get_control_value(control)
                url_changed = self._update_url_from_chrome(control)
                if self._should_skip_value_change(control, element_name, element_role, value, url_changed):
                    return
                self._write_event("fill", element_name, element_role, self._current_url, value=value)
            elif event == EVENT_SYSTEM_FOREGROUND:
                self._update_url_from_chrome(control)
        except Exception as exc:
            logger.debug(f"[Accessibility] 处理事件异常: {exc}")

    def _get_control_value(self, control) -> str:
        """尽量读取 UIA 控件当前值。"""
        try:
            value_pattern = control.GetValuePattern()
            value = getattr(value_pattern, "Value", "")
            if isinstance(value, str) and value:
                return value
        except Exception:
            pass
        value = getattr(control, "Value", "") or ""
        return value if isinstance(value, str) else ""

    def _is_address_bar_control(self, control, element_name: str, element_role: str) -> bool:
        """基于 UIA 元数据识别 Chrome 地址栏。"""
        automation_id = getattr(control, "AutomationId", "") or ""
        hints = " ".join([automation_id, element_name, element_role]).lower()
        return "address" in hints or "omnibox" in hints

    def _should_skip_value_change(
        self,
        control,
        element_name: str,
        element_role: str,
        value: str,
        url_changed: bool,
    ) -> bool:
        """忽略由地址栏导航导致的 value change，避免误记为 fill。"""
        if self._is_address_bar_control(control, element_name, element_role):
            return True

        if not url_changed:
            return False

        if value.startswith(("http://", "https://")):
            return True

        return not value and "edit" not in element_role.lower()

    def _update_url_from_chrome(self, control) -> bool:
        """尝试从 Chrome 地址栏提取当前 URL。"""
        try:
            url = self._get_control_value(control)
            if url and url.startswith(("http://", "https://")):
                previous_url = self._current_url
                self._current_url = url
                return url != previous_url
        except Exception as exc:
            logger.debug(f"[Accessibility] 获取 Chrome URL 失败: {exc}")
        return False

    def _write_event(
        self,
        action_type: str,
        element_name: str,
        element_role: str,
        url: str,
        value: str = "",
    ) -> None:
        """写入 browser_action JSONL。"""
        if not self._queue_file or not self._recording_id:
            return

        now = time.time()
        record = {
            "type": "browser_action",
            "recording_id": self._recording_id,
            "action": {
                "action_type": action_type,
                "url": url,
                "timestamp": now,
                "dom_element": {
                    "text_content": element_name,
                    "role": element_role,
                    "element_selector": "",
                },
                "parameters": {"value": value} if value else {},
                "network_requests": [],
            },
            "timestamp": now,
        }

        try:
            append_jsonl(self._queue_file, record, self._queue_write_lock)
        except Exception as exc:
            logger.error(f"[Accessibility] 写入失败: {exc}")
