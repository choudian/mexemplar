"""浏览器截图钩子模块（Windows only）

在录制期间监听鼠标左键和 Enter 键，采集 before/after 截图写入独立队列文件。
"""

import base64
import heapq
import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional


logger = logging.getLogger(__name__)


@dataclass
class _CaptureTask:
    """截图任务（由 pynput 回调产生，由 _ScreenCapturer 消费）"""
    capture_id: str
    moment: Literal["before", "after"]
    source_trigger: str  # "mouse_left" | "enter"
    event_ts: float      # mousedown/keydown 时间戳


@dataclass
class _FrameSample:
    """一帧缓存截图（环形缓冲）"""

    timestamp: float
    data: bytes


class _FrameRingBuffer:
    """线程安全的内存环形帧缓冲（仅保留最近若干帧）"""

    def __init__(self, max_samples: int) -> None:
        self._samples: deque[_FrameSample] = deque(maxlen=max_samples)
        self._lock = threading.Lock()

    def append(self, sample: _FrameSample) -> None:
        with self._lock:
            self._samples.append(sample)

    def latest_before(self, ts: float, *, max_age: float) -> Optional[_FrameSample]:
        with self._lock:
            for sample in reversed(self._samples):
                if sample.timestamp <= ts:
                    if ts - sample.timestamp <= max_age:
                        return sample
                    return None
        return None

    def earliest_after(self, ts: float, *, max_lag: float) -> Optional[_FrameSample]:
        with self._lock:
            for sample in self._samples:
                if sample.timestamp >= ts:
                    if sample.timestamp - ts <= max_lag:
                        return sample
                    return None
        return None

    def latest_recent(self, *, max_age: float) -> Optional[_FrameSample]:
        now = time.time()
        with self._lock:
            if not self._samples:
                return None
            sample = self._samples[-1]
            if now - sample.timestamp <= max_age:
                return sample
        return None


class _CaptureTaskQueue:
    """Bounded capture queue with before-first backpressure semantics."""

    def __init__(self, *, maxsize: int, logger_: logging.Logger) -> None:
        self._items: deque[_CaptureTask] = deque()
        self._maxsize = maxsize
        self._logger = logger_
        self._condition = threading.Condition()

    def put(self, task: _CaptureTask) -> bool:
        with self._condition:
            if len(self._items) >= self._maxsize:
                items = list(self._items)
                before_index = next(
                    (index for index, queued in enumerate(items) if queued.moment == "before"),
                    None,
                )
                if before_index is None:
                    self._logger.warning(
                        "capture queue saturated, dropping incoming %s task",
                        task.moment,
                    )
                    return False

                del items[before_index]
                self._items.clear()
                self._items.extend(items)
                self._logger.warning("capture queue saturated, dropping oldest before task")

            self._items.append(task)
            self._condition.notify()
            return True

    def get(self, timeout: float) -> _CaptureTask:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while not self._items:
                if deadline is None:
                    self._condition.wait()
                    continue

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                self._condition.wait(timeout=remaining)

            return self._items.popleft()


class _CaptureIdGenerator:
    """为每次物理输入生成单调递增的 capture_id"""
    def __init__(self) -> None:
        self._counter = 0
        self._lock = threading.Lock()

    def next_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"cap_{self._counter:04d}"


class _QueueWriter:
    """加锁写 JSONL（screenshots queue）—— 委托给 append_jsonl"""
    def __init__(self, path: Path, logger_: logging.Logger) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._logger = logger_
        from src.utils.helpers import append_jsonl
        self._append = append_jsonl

    def write(self, record: dict) -> None:
        try:
            self._append(self._path, record, self._lock)
        except Exception as exc:
            self._logger.error(f"写入截图队列失败: {exc}")


class _AfterScheduler:
    """heapq 调度 after 截图（避免每个 action 起 Timer 线程）"""
    def __init__(
        self,
        capture_queue: _CaptureTaskQueue,
    ) -> None:
        self._capture_queue = capture_queue
        self._heap: list[tuple[float, str, str, float]] = []  # (fire_time, capture_id, source_trigger, event_ts)
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="AfterScheduler")
        self._thread.start()

    def schedule(self, fire_time: float, capture_id: str, source_trigger: str, event_ts: float) -> None:
        with self._lock:
            heapq.heappush(self._heap, (fire_time, capture_id, source_trigger, event_ts))
        self._event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            now = time.time()
            with self._lock:
                while self._heap and self._heap[0][0] <= now:
                    _, cid, trigger, original_ts = heapq.heappop(self._heap)
                    self._capture_queue.put(
                        _CaptureTask(capture_id=cid, moment="after", source_trigger=trigger, event_ts=original_ts)
                    )

            if self._heap:
                wait = max(0, self._heap[0][0] - time.time())
                self._event.wait(timeout=min(wait, 0.1))
            else:
                self._event.wait(timeout=0.5)
            self._event.clear()

        # Flush remaining scheduled items after stop
        with self._lock:
            while self._heap:
                _, cid, trigger, original_ts = heapq.heappop(self._heap)
                self._capture_queue.put(
                    _CaptureTask(capture_id=cid, moment="after", source_trigger=trigger, event_ts=original_ts)
                )


class _BrowserHwndLocator:
    """根据 browser_pid 定位 Chromium 前台窗口 HWND"""
    def __init__(self, browser_pid: Optional[int], logger_: logging.Logger) -> None:
        self._browser_pid = browser_pid
        self._logger = logger_
        self._pid_cache: set[int] = set()
        self._candidate_hwnds: set[int] = set()
        self._pid_cache_ts: float = 0.0
        self._cache_ttl: float = 5.0

    def find_foreground_hwnd(self) -> Optional[int]:
        """返回当前前台且属于 browser 候选集的 HWND，否则 None"""
        if self._browser_pid is None:
            return None
        try:
            import ctypes
            from ctypes import wintypes

            self._refresh_candidates(ctypes, wintypes)

            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None

            if int(hwnd) not in self._candidate_hwnds:
                return None

            return hwnd
        except Exception as exc:
            self._logger.debug(f"查找前台 HWND 失败: {exc}")
            return None

    def _refresh_candidates(self, ctypes, wintypes) -> None:
        browser_pids = self._get_browser_pids()
        if not browser_pids:
            self._candidate_hwnds = set()
            return

        user32 = ctypes.windll.user32
        candidates = {
            hwnd for hwnd in self._candidate_hwnds if user32.IsWindow(hwnd)
        }

        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def _callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True

            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in browser_pids:
                return True

            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name, 256)
            if class_name.value == "Chrome_WidgetWin_1":
                candidates.add(int(hwnd))
            return True

        callback = enum_proc(_callback)
        user32.EnumWindows(callback, 0)
        self._candidate_hwnds = candidates

    def _get_browser_pids(self) -> set[int]:
        """获取 browser 进程树（带 5 秒缓存）"""
        now = time.time()
        if now - self._pid_cache_ts > self._cache_ttl:
            try:
                import psutil
                proc = psutil.Process(self._browser_pid)
                self._pid_cache = {self._browser_pid} | {
                    c.pid for c in proc.children(recursive=True)
                }
            except Exception:
                self._pid_cache = {self._browser_pid} if self._browser_pid else set()
            self._pid_cache_ts = now
        return self._pid_cache


class _ScreenCapturer:
    """工作线程：从队列拉取 CaptureTask → 截图 → 写队列文件"""
    def __init__(
        self,
        capture_queue: _CaptureTaskQueue,
        queue_writer: _QueueWriter,
        hwnd_locator: _BrowserHwndLocator,
        recording_id: str,
        jpeg_quality: int,
        logger_: logging.Logger,
        after_delay: float,
        dpi_strategy: str = "unaware",
    ) -> None:
        self._queue = capture_queue
        self._writer = queue_writer
        self._locator = hwnd_locator
        self._recording_id = recording_id
        self._quality = jpeg_quality
        self._logger = logger_
        self._dpi_strategy = dpi_strategy
        self._after_delay = after_delay
        self._thread: Optional[threading.Thread] = None
        self._sampler_thread: Optional[threading.Thread] = None
        self._sampler_interval = 0.1
        self._stop_event = threading.Event()
        self._pending_tasks: list[_CaptureTask] = []
        self._mss = None  # lazily created, reused across captures
        self._frame_buffer = _FrameRingBuffer(max_samples=64)  # ~6.4s @ 100ms

    def set_dpi_strategy(self, dpi_strategy: str) -> None:
        self._dpi_strategy = dpi_strategy

    def start(self) -> None:
        self._sampler_thread = threading.Thread(
            target=self._run_sampler,
            daemon=True,
            name="FrameSampler",
        )
        self._thread = threading.Thread(target=self._run, daemon=True, name="ScreenCapturer")
        self._sampler_thread.start()
        self._thread.start()

    def stop(self, *, flush_timeout: float = 3.0) -> None:
        self._stop_event.set()
        if self._sampler_thread:
            self._sampler_thread.join(timeout=flush_timeout)
        if self._thread:
            self._thread.join(timeout=flush_timeout)
            if self._thread.is_alive():
                self._logger.warning(f"ScreenCapturer flush 超时，丢弃 {len(self._pending_tasks)} 个未完成任务")
        if self._mss:
            try:
                self._mss.close()
            except Exception:
                pass
            self._mss = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                task = self._queue.get(timeout=0.1)
                self._pending_tasks.append(task)
            except queue.Empty:
                continue

            # 处理所有已入队的任务
            remaining = []
            for t in self._pending_tasks:
                if self._stop_event.is_set() and t.moment == "after":
                    # stopping 时保留 after 到 flush 阶段，before 立即处理
                    remaining.append(t)
                    continue
                self._process_task(t)
            self._pending_tasks = remaining

        # flush 残留
        for t in self._pending_tasks:
            self._process_task(t)
        self._pending_tasks.clear()

    def _run_sampler(self) -> None:
        """后台低频采样到内存环形缓冲，供 before/after 按时刻取帧。"""
        while not self._stop_event.is_set():
            try:
                hwnd = self._locator.find_foreground_hwnd()
                if hwnd is not None:
                    capture_result = self._capture_window(hwnd)
                    if capture_result is not None:
                        img_bytes, captured_at = capture_result
                        self._frame_buffer.append(_FrameSample(timestamp=captured_at, data=img_bytes))
            except Exception as exc:
                self._logger.debug(f"帧采样失败: {exc}")
            time.sleep(self._sampler_interval)

    def _process_task(self, task: _CaptureTask) -> None:
        record = {
            "recording_id": self._recording_id,
            "capture_id": task.capture_id,
            "moment": task.moment,
            "source_trigger": task.source_trigger,
            "input_started_at": task.event_ts,
            "input_completed_at": None,
            "captured_at": None,
            "data_b64": None,
            "media_type": None,
            "skipped_reason": None,
        }

        buffered = self._select_buffered_frame(task)
        if buffered is not None:
            record["captured_at"] = buffered.timestamp
            record["data_b64"] = base64.b64encode(buffered.data).decode("ascii")
            record["media_type"] = "image/jpeg"
            self._writer.write(record)
            return

        hwnd = self._locator.find_foreground_hwnd()
        if hwnd is None:
            record["captured_at"] = time.time()
            record["skipped_reason"] = "not_foreground"
            self._writer.write(record)
            return

        try:
            capture_result = self._capture_window(hwnd)
            if capture_result is None:
                record["captured_at"] = time.time()
                record["skipped_reason"] = "capture_failed"
                self._writer.write(record)
                return

            img_bytes, captured_at = capture_result
            record["captured_at"] = captured_at
            record["data_b64"] = base64.b64encode(img_bytes).decode("ascii")
            record["media_type"] = "image/jpeg"
            self._writer.write(record)
        except Exception as exc:
            self._logger.debug(f"截图处理失败: {exc}")
            record["captured_at"] = time.time()
            record["skipped_reason"] = "capture_failed"
            self._writer.write(record)

    def _select_buffered_frame(self, task: _CaptureTask) -> Optional[_FrameSample]:
        if task.moment == "before":
            return self._frame_buffer.latest_before(task.event_ts, max_age=1.0)

        # after: 优先取“点击后”最接近的一帧；若暂时没有，取近期最新帧兜底
        after_anchor = task.event_ts + max(0.05, self._after_delay * 0.5)
        candidate = self._frame_buffer.earliest_after(after_anchor, max_lag=2.0)
        if candidate is not None:
            return candidate
        return self._frame_buffer.latest_recent(max_age=2.0)

    def _capture_window(self, hwnd: int) -> Optional[tuple[bytes, float]]:
        """截取指定窗口，返回 (jpeg_bytes, captured_at) 或 None"""
        try:
            import ctypes
            from ctypes import wintypes
            import mss
            from PIL import Image
        except ImportError:
            return None

        try:
            # 获取窗口矩形
            rect = wintypes.RECT()
            # 优先 DwmGetWindowAttribute
            try:
                ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)
                )
            except Exception:
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))

            scale = 1.0
            if self._dpi_strategy != "per_monitor":
                try:
                    dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
                    scale = dpi / 96.0
                except Exception:
                    scale = 1.0

            left = int(rect.left * scale) if scale != 1.0 else rect.left
            top = int(rect.top * scale) if scale != 1.0 else rect.top
            right = int(rect.right * scale) if scale != 1.0 else rect.right
            bottom = int(rect.bottom * scale) if scale != 1.0 else rect.bottom

            # 求交 virtual screen
            if self._mss is None:
                self._mss = mss.mss()
            sct = self._mss
            mon = sct.monitors[0]  # virtual screen
            vl, vt = mon["left"], mon["top"]
            vr, vb = vl + mon["width"], vt + mon["height"]

            cl = max(left, vl)
            ct = max(top, vt)
            cr = min(right, vr)
            cb = min(bottom, vb)

            if cr <= cl or cb <= ct:
                return None  # 空矩形

            # mss 使用 virtual screen 坐标（物理像素）
            screenshot = sct.grab({"left": cl, "top": ct, "width": cr - cl, "height": cb - ct})
            captured_at = time.time()

            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            import io
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=self._quality)
            return buf.getvalue(), captured_at
        except Exception as exc:
            self._logger.debug(f"窗口截图失败 (hwnd={hwnd}): {exc}")
            return None


class BrowserScreenshotHook:
    """浏览器截图钩子：监听鼠标左键 / Enter，采集 before/after 截图"""

    def __init__(
        self,
        *,
        recording_id: str,
        screenshots_queue_file: Path,
        browser_pid: Optional[int] = None,
        jpeg_quality: int = 85,
        after_delay: float = 0.2,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._recording_id = recording_id
        self._queue_file = screenshots_queue_file
        self._browser_pid = browser_pid
        self._jpeg_quality = jpeg_quality
        self._after_delay = after_delay
        self._logger = logger or logging.getLogger(__name__)
        self._dpi_strategy = "unaware"

        self._capture_queue = _CaptureTaskQueue(maxsize=50, logger_=self._logger)
        self._id_gen = _CaptureIdGenerator()
        self._queue_writer = _QueueWriter(self._queue_file, self._logger)
        self._hwnd_locator = _BrowserHwndLocator(self._browser_pid, self._logger)
        self._capturer = _ScreenCapturer(
            self._capture_queue, self._queue_writer, self._hwnd_locator,
            self._recording_id, self._jpeg_quality, self._logger,
            self._after_delay,
        )
        self._after_scheduler = _AfterScheduler(
            self._capture_queue,
        )

        self._mouse_listener = None
        self._keyboard_listener = None
        self._started = False

    def start(self) -> bool:
        """启动钩子。返回 True 表示成功，False 表示降级（不影响录制主路径）。"""
        import sys
        if sys.platform != "win32":
            self._logger.debug("非 Windows 平台，跳过截图钩子")
            return False

        try:
            from pynput import mouse, keyboard
        except ImportError:
            self._logger.warning("pynput 未安装，跳过截图钩子")
            return False

        try:
            self._capturer.start()
            self._after_scheduler.start()
            self._dpi_strategy = self._detect_dpi_strategy()
            self._capturer.set_dpi_strategy(self._dpi_strategy)

            self._mouse_listener = mouse.Listener(
                on_click=self._on_mouse_click,
            )
            self._keyboard_listener = keyboard.Listener(
                on_press=self._on_key_press,
            )

            self._mouse_listener.start()
            self._keyboard_listener.start()
            self._started = True
            self._logger.info("BrowserScreenshotHook 已启动")
            return True
        except Exception as exc:
            self._logger.warning(f"截图钩子启动失败（降级）: {exc}")
            self.stop()
            return False

    def stop(self, *, flush_timeout: float = 3.0) -> None:
        """停止钩子，flush 残留 after 截图"""
        if not self._started:
            return

        self._logger.debug("正在停止 BrowserScreenshotHook...")

        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._keyboard_listener:
            self._keyboard_listener.stop()

        self._after_scheduler.stop()
        self._capturer.stop(flush_timeout=flush_timeout)
        self._started = False
        self._logger.info("BrowserScreenshotHook 已停止")

    def _on_mouse_click(self, x, y, button, pressed) -> None:
        """鼠标点击回调（在 pynput 内部线程执行）"""
        from pynput.mouse import Button
        del x, y
        if button != Button.left or not pressed:
            return

        capture_id = self._id_gen.next_id()
        event_ts = time.time()

        self._capture_queue.put(
            _CaptureTask(capture_id=capture_id, moment="before", source_trigger="mouse_left", event_ts=event_ts)
        )
        self._after_scheduler.schedule(
            fire_time=event_ts + self._after_delay,
            capture_id=capture_id,
            source_trigger="mouse_left",
            event_ts=event_ts,
        )

    def _on_key_press(self, key) -> None:
        """按键回调（在 pynput 内部线程执行）"""
        if not self._is_enter_key(key):
            return

        capture_id = self._id_gen.next_id()
        event_ts = time.time()

        # keydown → before（pynput 在 press 时调用，不是 release）
        self._capture_queue.put(
            _CaptureTask(capture_id=capture_id, moment="before", source_trigger="enter", event_ts=event_ts)
        )
        # schedule after
        self._after_scheduler.schedule(
            fire_time=event_ts + self._after_delay,
            capture_id=capture_id,
            source_trigger="enter",
            event_ts=event_ts,
        )

    @staticmethod
    def _is_enter_key(key) -> bool:
        """Best-effort Enter detection across pynput key representations."""
        try:
            from pynput.keyboard import Key

            if key == Key.enter:
                return True
        except Exception:
            pass

        if getattr(key, "vk", None) == 13:
            return True

        if getattr(key, "char", None) in ("\r", "\n"):
            return True

        return False

    def _detect_dpi_strategy(self) -> str:
        """Read the current process DPI awareness without modifying it."""
        try:
            import ctypes

            user32 = ctypes.windll.user32
            context = user32.GetThreadDpiAwarenessContext()
            awareness = user32.GetAwarenessFromDpiAwarenessContext(context)
            if awareness >= 2:
                return "per_monitor"
            if awareness == 1:
                return "system"
        except Exception:
            pass

        try:
            import ctypes

            awareness = ctypes.c_int()
            ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(awareness))
            if awareness.value >= 2:
                return "per_monitor"
            if awareness.value == 1:
                return "system"
        except Exception:
            pass

        return "unaware"
