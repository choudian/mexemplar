"""
数据采集模块

负责采集屏幕截图、鼠标键盘事件、窗口信息等录制数据
"""

import time
import logging
from typing import List, Dict, Any, Optional, Callable, TYPE_CHECKING
from dataclasses import dataclass, field
from pathlib import Path
import mss
import mss.tools
# 延迟导入 pynput 以避免在无图形界面环境导入失败
if TYPE_CHECKING:
    from pynput import mouse, keyboard
from PIL import Image
import io
import base64
import psutil

logger = logging.getLogger(__name__)


@dataclass
class MouseEvent:
    """鼠标事件"""

    event_type: str  # 'click', 'move', 'scroll', 'press', 'release'
    x: int
    y: int
    button: Optional[str] = None  # 'left', 'right', 'middle'
    pressed: Optional[bool] = None
    scroll_dx: Optional[int] = None
    scroll_dy: Optional[int] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class KeyboardEvent:
    """键盘事件"""

    event_type: str  # 'press', 'release'
    key: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ScreenshotData:
    """截图数据"""

    image_data: bytes  # PNG格式的图片数据
    timestamp: float = field(default_factory=time.time)
    region: Optional[Dict[str, int]] = None  # {'left', 'top', 'width', 'height'}


@dataclass
class WindowInfo:
    """窗口信息"""

    window_title: str
    window_class: Optional[str] = None
    process_name: Optional[str] = None  # 进程名（如chrome.exe）
    app_name: Optional[str] = None  # 应用显示名称（如Google Chrome）
    app_path: Optional[str] = None  # 应用路径
    process_id: Optional[int] = None  # 进程ID
    cmdline: Optional[List[str]] = None  # 命令行参数
    hwnd: Optional[int] = None
    position: Optional[Dict[str, int]] = None  # {'x', 'y', 'width', 'height'}
    timestamp: float = field(default_factory=time.time)


@dataclass
class RecordingEvent:
    """录制事件（综合事件）"""

    event_type: str  # 'mouse', 'keyboard', 'screenshot', 'window_change'
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class ScreenCapture:
    """屏幕截图捕获"""

    def __init__(self, monitor: int = 1):
        """
        初始化屏幕捕获

        Args:
            monitor: 显示器编号，1为主显示器
        """
        self.monitor = monitor
        # 不在这里创建mss实例，而是在每次使用时创建（线程安全）

    def capture_full_screen(self) -> ScreenshotData:
        """捕获整个屏幕"""
        try:
            # 使用上下文管理器确保线程安全
            with mss.mss() as sct:
                screenshot = sct.grab(sct.monitors[self.monitor])
                img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

                # 转换为PNG格式的字节数据
                img_bytes = io.BytesIO()
                img.save(img_bytes, format="PNG", optimize=True)
                img_bytes.seek(0)

                region = {
                    "left": screenshot.left,
                    "top": screenshot.top,
                    "width": screenshot.width,
                    "height": screenshot.height,
                }

                return ScreenshotData(image_data=img_bytes.read(), region=region)
        except Exception as e:
            logger.error(f"屏幕截图失败: {e}")
            raise

    def capture_region(self, left: int, top: int, width: int, height: int) -> ScreenshotData:
        """
        捕获指定区域

        Args:
            left: 左边界
            top: 上边界
            width: 宽度
            height: 高度
        """
        try:
            monitor = {"left": left, "top": top, "width": width, "height": height}
            # 使用上下文管理器确保线程安全
            with mss.mss() as sct:
                screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

                img_bytes = io.BytesIO()
                img.save(img_bytes, format="PNG", optimize=True)
                img_bytes.seek(0)

                return ScreenshotData(image_data=img_bytes.read(), region=monitor)
        except Exception as e:
            logger.error(f"区域截图失败: {e}")
            raise

    def close(self):
        """关闭截图器（现在不需要，因为使用上下文管理器）"""
        pass


class MouseKeyboardMonitor:
    """鼠标键盘监控器"""

    def __init__(
        self,
        on_mouse_event: Optional[Callable[[MouseEvent], None]] = None,
        on_keyboard_event: Optional[Callable[[KeyboardEvent], None]] = None,
    ):
        """
        初始化监控器

        Args:
            on_mouse_event: 鼠标事件回调函数
            on_keyboard_event: 键盘事件回调函数
        """
        self.on_mouse_event = on_mouse_event
        self.on_keyboard_event = on_keyboard_event
        self.mouse_listener = None  # type: Optional[Any]
        self.keyboard_listener = None  # type: Optional[Any]
        self._is_running = False

    def _on_mouse_click(self, x, y, button, pressed):
        """鼠标点击事件处理"""
        if self.on_mouse_event:
            event = MouseEvent(
                event_type="click",
                x=x,
                y=y,
                button=str(button).split(".")[-1] if button else None,
                pressed=pressed,
            )
            self.on_mouse_event(event)

    def _on_mouse_move(self, x, y):
        """鼠标移动事件处理"""
        if self.on_mouse_event:
            event = MouseEvent(event_type="move", x=x, y=y)
            self.on_mouse_event(event)

    def _on_mouse_scroll(self, x, y, dx, dy):
        """鼠标滚轮事件处理"""
        if self.on_mouse_event:
            event = MouseEvent(event_type="scroll", x=x, y=y, scroll_dx=dx, scroll_dy=dy)
            self.on_mouse_event(event)

    def _on_key_press(self, key):
        """按键按下事件处理"""
        if self.on_keyboard_event:
            try:
                key_str = key.char if hasattr(key, "char") and key.char else str(key)
            except Exception:
                key_str = str(key)

            event = KeyboardEvent(event_type="press", key=key_str)
            self.on_keyboard_event(event)

    def _on_key_release(self, key):
        """按键释放事件处理"""
        if self.on_keyboard_event:
            try:
                key_str = key.char if hasattr(key, "char") and key.char else str(key)
            except Exception:
                key_str = str(key)

            event = KeyboardEvent(event_type="release", key=key_str)
            self.on_keyboard_event(event)

    def start(self):
        """开始监控"""
        if self._is_running:
            return

        self._is_running = True

        # 延迟导入 pynput 以避免在无图形界面环境导入失败
        from pynput import mouse, keyboard

        # 启动鼠标监听器
        self.mouse_listener = mouse.Listener(
            on_click=self._on_mouse_click,
            on_move=self._on_mouse_move,
            on_scroll=self._on_mouse_scroll,
        )
        self.mouse_listener.start()

        # 启动键盘监听器
        self.keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press, on_release=self._on_key_release
        )
        self.keyboard_listener.start()

        logger.info("鼠标键盘监控已启动")

    def stop(self):
        """停止监控"""
        if not self._is_running:
            return

        self._is_running = False

        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None

        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None

        logger.info("鼠标键盘监控已停止")

    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self._is_running


class WindowInfoCollector:
    """窗口信息采集器"""

    def __init__(self):
        """初始化窗口信息采集器"""
        try:
            import win32gui
            import win32process
            import win32api

            self.win32gui = win32gui
            self.win32process = win32process
            self.win32api = win32api
            self._win32_available = True
        except ImportError:
            logger.warning("win32gui不可用，窗口信息采集功能受限")
            self._win32_available = False

    def get_active_window_info(self) -> Optional[WindowInfo]:
        """获取当前活动窗口信息"""
        if not self._win32_available:
            return None

        try:
            hwnd = self.win32gui.GetForegroundWindow()
            if hwnd == 0:
                return None

            # 获取窗口标题
            window_title = self.win32gui.GetWindowText(hwnd)

            # 获取窗口类名
            window_class = self.win32gui.GetClassName(hwnd)

            # 获取窗口位置
            rect = self.win32gui.GetWindowRect(hwnd)
            position = {
                "x": rect[0],
                "y": rect[1],
                "width": rect[2] - rect[0],
                "height": rect[3] - rect[1],
            }

            # 获取进程ID
            try:
                _, pid = self.win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                pid = None

            # 使用psutil获取详细进程信息
            app_name = None
            app_path = None
            process_name = None
            cmdline = None

            if pid:
                try:
                    process = psutil.Process(pid)

                    # 获取进程名
                    process_name = process.name()

                    # 获取应用路径
                    try:
                        app_path = process.exe()
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        app_path = None

                    # 获取命令行参数
                    try:
                        cmdline = process.cmdline()
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        cmdline = None

                    # 获取应用显示名称
                    app_name = self._get_app_display_name(process, app_path)

                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.warning(f"无法获取进程信息 (PID: {pid}): {e}")
                    # 降级处理：使用win32process获取进程名
                    try:
                        handle = self.win32process.OpenProcess(0x0410, False, pid)
                        exe_path = self.win32process.GetModuleFileNameEx(handle, 0)
                        process_name = exe_path.split("\\")[-1] if exe_path else None
                        app_path = exe_path
                        app_name = (
                            process_name.replace(".exe", "").title() if process_name else None
                        )
                    except Exception:
                        pass

            return WindowInfo(
                window_title=window_title,
                window_class=window_class,
                process_name=process_name,
                app_name=app_name,
                app_path=app_path,
                process_id=pid,
                cmdline=cmdline,
                hwnd=hwnd,
                position=position,
            )
        except Exception as e:
            logger.error(f"获取窗口信息失败: {e}")
            return None

    def _get_app_display_name(self, process: psutil.Process, exe_path: Optional[str] = None) -> str:
        """获取应用显示名称"""
        try:
            if not exe_path:
                try:
                    exe_path = process.exe()
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    return process.name()

            if not exe_path:
                return process.name()

            # 方法1: 从文件版本信息获取FileDescription
            if self._win32_available:
                try:
                    file_info = self.win32api.GetFileVersionInfo(exe_path, "\\")
                    lang_codepage = file_info.get("FileInfo", {})
                    for lang, codepage in lang_codepage.items():
                        try:
                            string_file_info = (
                                file_info.get("StringFileInfo", {}).get(lang, {}).get(codepage, {})
                            )
                            if "FileDescription" in string_file_info:
                                description = string_file_info["FileDescription"]
                                if description and description.strip():
                                    return description
                        except Exception:
                            continue
                except Exception:
                    pass

            # 方法2: 从进程名推断（fallback）
            name = process.name().replace(".exe", "").replace(".EXE", "")
            # 简单的名称映射（可扩展）
            name_map = {
                "chrome": "Google Chrome",
                "msedge": "Microsoft Edge",
                "firefox": "Mozilla Firefox",
                "notepad": "记事本",
                "explorer": "文件资源管理器",
                "code": "Visual Studio Code",
                "cursor": "Cursor",
                "winword": "Microsoft Word",
                "excel": "Microsoft Excel",
                "powerpnt": "Microsoft PowerPoint",
            }
            return name_map.get(name.lower(), name.title())
        except Exception as e:
            logger.warning(f"获取应用显示名称失败: {e}")
            return process.name()


class DataCollector:
    """数据采集器（综合类）"""

    def __init__(self, config=None):
        """
        初始化数据采集器

        Args:
            config: RecordingConfig配置对象（已废弃，保留向后兼容）

        注意：
            - config 参数已废弃，仅保留向后兼容
            - 所有配置现在通过 get_unified_config() 访问
        """
        # ⭐ 重构：不再直接实例化 RecordingConfig
        # 保留 config 参数以保持向后兼容，但不使用它
        # 所有配置访问都通过 get_unified_config()
        if config is not None:
            logger.warning(
                "[DataCollector] config 参数已废弃，所有配置现在通过 get_unified_config() 访问"
            )

        # 使用统一配置管理器
        from src.data.unified_config import get_unified_config

        self._unified_config = get_unified_config()

        self.screen_capture = ScreenCapture()
        self.monitor = MouseKeyboardMonitor(
            on_mouse_event=self._on_mouse_event, on_keyboard_event=self._on_keyboard_event
        )
        self.window_collector = WindowInfoCollector()

        # 初始化浏览器URL捕获器
        try:
            from .browser_url_capturer import BrowserURLCapturer

            self.url_capturer = BrowserURLCapturer()
        except Exception as e:
            logger.warning(f"无法初始化浏览器URL捕获器: {e}")
            self.url_capturer = None

        self.events: List[RecordingEvent] = []
        self.current_window: Optional[WindowInfo] = None
        self._is_collecting = False
        self.window_monitor_thread: Optional[Any] = None
        self.last_window_hwnd: Optional[int] = None
        self.screenshots_dir: Optional[Path] = None
        self.screenshot_counter: int = 0
        self.video_recorder: Optional[Any] = None
        self.video_recording_thread: Optional[Any] = None

    def _on_mouse_event(self, event: MouseEvent):
        """鼠标事件回调"""
        if not self._is_collecting:
            return

        # 过滤鼠标移动事件（除非配置允许）
        record_mouse_move = self._unified_config.get("recording.record_mouse_move", default=False)
        if event.event_type == "move" and not record_mouse_move:
            return

        # 只记录关键操作：点击、滚轮
        if event.event_type not in ["click", "scroll"]:
            return

        # 对于点击操作，记录操作前后截图
        if event.event_type == "click" and event.pressed:
            self._record_action_with_screenshots(
                "mouse",
                {
                    "event_type": event.event_type,
                    "x": event.x,
                    "y": event.y,
                    "button": event.button,
                    "pressed": event.pressed,
                    "scroll_dx": event.scroll_dx,
                    "scroll_dy": event.scroll_dy,
                },
                event.timestamp,
            )
        else:
            # 滚轮等操作只记录事件，不截图
            recording_event = RecordingEvent(
                event_type="mouse",
                data={
                    "event_type": event.event_type,
                    "x": event.x,
                    "y": event.y,
                    "button": event.button,
                    "pressed": event.pressed,
                    "scroll_dx": event.scroll_dx,
                    "scroll_dy": event.scroll_dy,
                },
                timestamp=event.timestamp,
            )
            self.events.append(recording_event)

    def _on_keyboard_event(self, event: KeyboardEvent):
        """键盘事件回调"""
        if not self._is_collecting:
            return

        # 对于按键按下事件，记录操作前后截图
        if event.event_type == "press":
            self._record_action_with_screenshots(
                "keyboard",
                {
                    "event_type": event.event_type,
                    "key": event.key,
                },
                event.timestamp,
            )
        else:
            # 按键释放只记录事件，不截图
            recording_event = RecordingEvent(
                event_type="keyboard",
                data={
                    "event_type": event.event_type,
                    "key": event.key,
                },
                timestamp=event.timestamp,
            )
            self.events.append(recording_event)

    def start_collecting(
        self, screenshots_dir: Optional[Path] = None, video_path: Optional[Path] = None
    ):
        """
        开始采集

        Args:
            screenshots_dir: 截图保存目录，如果为None则不保存截图文件
            video_path: 视频文件保存路径，如果为None且配置启用则自动创建
        """
        if self._is_collecting:
            return

        self._is_collecting = True
        self.events.clear()
        self.screenshot_counter = 0
        self.screenshots_dir = screenshots_dir
        if self.screenshots_dir:
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        # 初始化视频录制器
        enable_video_recording = self._unified_config.get(
            "recording.enable_video_recording", default=True
        )
        if enable_video_recording:
            if video_path is None and screenshots_dir:
                # 自动创建视频文件路径（在截图目录的父目录）
                video_path = screenshots_dir.parent / "video.mp4"

            if video_path:
                from .video_recorder import VideoRecorder

                video_fps = self._unified_config.get("recording.video_fps", default=15)
                video_quality = self._unified_config.get("recording.video_quality", default=85)
                self.video_recorder = VideoRecorder(
                    output_path=video_path, fps=video_fps, quality=video_quality
                )

                # 获取屏幕尺寸（使用独立的mss实例）
                with mss.mss() as temp_sct:
                    monitor = temp_sct.monitors[1]
                    width = monitor["width"]
                    height = monitor["height"]

                self.video_recorder.start(width, height)

                # 启动视频录制线程
                import threading

                self.video_recording_thread = threading.Thread(
                    target=self._video_recording_worker, daemon=True
                )
                self.video_recording_thread.start()

        self.monitor.start()

        # 记录初始窗口信息
        self.current_window = self.window_collector.get_active_window_info()
        if self.current_window:
            self.last_window_hwnd = self.current_window.hwnd
            recording_event = RecordingEvent(
                event_type="window_change",
                data={
                    "window_title": self.current_window.window_title,
                    "window_class": self.current_window.window_class,
                    "process_name": self.current_window.process_name,
                    "app_name": self.current_window.app_name,
                    "app_path": self.current_window.app_path,
                    "process_id": self.current_window.process_id,
                    "hwnd": self.current_window.hwnd,
                    "position": self.current_window.position,
                },
                timestamp=self.current_window.timestamp,
            )
            self.events.append(recording_event)

        # 启动窗口监听线程
        import threading

        self.window_monitor_thread = threading.Thread(
            target=self._window_monitor_worker, daemon=True
        )
        self.window_monitor_thread.start()

        logger.info("数据采集已启动")

    def stop_collecting(self):
        """停止采集"""
        if not self._is_collecting:
            return

        self._is_collecting = False
        self.monitor.stop()

        # 停止视频录制
        if self.video_recorder:
            self.video_recorder.stop()
            self.video_recorder = None

        # 窗口监听线程会在检查到_is_collecting为False时自动退出
        self.last_window_hwnd = None

        logger.info("数据采集已停止")

    def _video_recording_worker(self):
        """视频录制线程"""
        video_fps = self._unified_config.get("recording.video_fps", default=15)
        frame_interval = 1.0 / video_fps
        try:
            while self._is_collecting and self.video_recorder:
                try:
                    self.video_recorder.record_frame()
                    time.sleep(frame_interval)
                except Exception as e:
                    logger.error(f"视频录制线程错误: {e}")
                    break
        finally:
            # 在线程结束时清理mss实例
            if self.video_recorder and self.video_recorder.sct:
                try:
                    self.video_recorder.sct.close()
                except:
                    pass
                self.video_recorder.sct = None

    def _window_monitor_worker(self):
        """窗口监听线程"""
        while self._is_collecting:
            try:
                current_window = self.window_collector.get_active_window_info()
                if current_window and current_window.hwnd != self.last_window_hwnd:
                    # 记录窗口切换
                    self._record_window_change(current_window)
                    self.last_window_hwnd = current_window.hwnd
                    self.current_window = current_window
            except Exception as e:
                logger.error(f"窗口监听错误: {e}")
            time.sleep(0.1)  # 100ms检查一次

    def _record_window_change(self, window_info: WindowInfo):
        """记录窗口切换事件（带操作前后截图）"""
        # 窗口切换时也记录操作前后截图
        self._record_action_with_screenshots(
            "window_change",
            {
                "window_title": window_info.window_title,
                "window_class": window_info.window_class,
                "process_name": window_info.process_name,
                "app_name": window_info.app_name,
                "app_path": window_info.app_path,
                "process_id": window_info.process_id,
                "hwnd": window_info.hwnd,
                "position": window_info.position,
            },
            window_info.timestamp,
        )
        logger.info(
            f"窗口切换: {window_info.app_name or window_info.process_name} - {window_info.window_title}"
        )

    def _is_browser(self, window_info: Optional[WindowInfo]) -> bool:
        """判断当前窗口是否是浏览器"""
        if not window_info:
            return False
        process_name = (window_info.process_name or "").lower()
        app_name = (window_info.app_name or "").lower()
        return (
            "chrome" in process_name
            or "chrome" in app_name
            or "edge" in process_name
            or "edge" in app_name
            or "firefox" in process_name
            or "firefox" in app_name
        )

    def _record_action_with_screenshots(
        self, action_type: str, action_data: Dict[str, Any], timestamp: float
    ):
        """记录操作并附带操作前后截图"""
        # 操作前截图
        before_screenshot = self.capture_screenshot()
        screenshot_id_before = None
        if before_screenshot:
            screenshot_id_before = self._save_screenshot(before_screenshot, "before")

        # 等待UI更新
        screenshot_delay = self._unified_config.get(
            "recording.screenshot_delay_after_action", default=0.2
        )
        time.sleep(screenshot_delay)

        # 操作后截图
        after_screenshot = self.capture_screenshot()
        screenshot_id_after = None
        if after_screenshot:
            screenshot_id_after = self._save_screenshot(after_screenshot, "after")

        # 记录操作事件（包含截图引用和应用信息）
        action_data_with_screenshots = {
            **action_data,
            "screenshot_before": screenshot_id_before,
            "screenshot_after": screenshot_id_after,
        }

        # 添加当前应用信息
        if self.current_window:
            action_data_with_screenshots["app_name"] = self.current_window.app_name
            action_data_with_screenshots["app_path"] = self.current_window.app_path
            action_data_with_screenshots["process_name"] = self.current_window.process_name
            action_data_with_screenshots["process_id"] = self.current_window.process_id
            action_data_with_screenshots["window_title"] = self.current_window.window_title

            # 如果是浏览器操作，尝试捕获URL
            if self.url_capturer and self._is_browser(self.current_window):
                try:
                    # 对于键盘输入，在操作后捕获URL（用户输入地址后）
                    if action_type == "keyboard":
                        # 稍微延迟，等待浏览器地址栏更新
                        time.sleep(0.3)
                        url = self.url_capturer.get_browser_url(
                            self.current_window.process_id, self.current_window.process_name
                        )
                        if url:
                            action_data_with_screenshots["url"] = url
                    # 对于点击操作，也尝试捕获URL（如果是点击链接）
                    elif action_type == "mouse":
                        x = action_data.get("x")
                        y = action_data.get("y")
                        if x is not None and y is not None:
                            # 稍微延迟，等待页面导航
                            time.sleep(0.5)
                            url = self.url_capturer.get_browser_url(
                                self.current_window.process_id, self.current_window.process_name
                            )
                            if url:
                                action_data_with_screenshots["url"] = url
                except Exception as e:
                    logger.debug(f"捕获浏览器URL失败: {e}")

        recording_event = RecordingEvent(
            event_type=action_type, data=action_data_with_screenshots, timestamp=timestamp
        )
        self.events.append(recording_event)

    def _save_screenshot(self, screenshot: ScreenshotData, prefix: str) -> Optional[str]:
        """保存截图到文件系统"""
        if not self.screenshots_dir:
            return None

        try:
            self.screenshot_counter += 1
            filename = f"{prefix}_{self.screenshot_counter:04d}.png"
            file_path = self.screenshots_dir / filename

            with open(file_path, "wb") as f:
                f.write(screenshot.image_data)

            return str(file_path)
        except Exception as e:
            logger.error(f"保存截图失败: {e}")
            return None

    def capture_screenshot(self) -> Optional[ScreenshotData]:
        """捕获屏幕截图"""
        if not self._is_collecting:
            return None

        try:
            screenshot = self.screen_capture.capture_full_screen()

            # 记录截图事件
            recording_event = RecordingEvent(
                event_type="screenshot",
                data={
                    "image_base64": base64.b64encode(screenshot.image_data).decode("utf-8"),
                    "region": screenshot.region,
                },
                timestamp=screenshot.timestamp,
            )
            self.events.append(recording_event)

            return screenshot
        except Exception as e:
            logger.error(f"捕获截图失败: {e}")
            return None

    def get_events(self) -> List[RecordingEvent]:
        """获取采集的事件列表"""
        return self.events.copy()

    def clear_events(self):
        """清空事件列表"""
        self.events.clear()

    def is_collecting(self) -> bool:
        """检查是否正在采集"""
        return self._is_collecting

    def close(self):
        """关闭采集器"""
        self.stop_collecting()
        self.screen_capture.close()
        if self.video_recorder:
            self.video_recorder.stop()
