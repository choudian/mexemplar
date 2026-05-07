from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class UiaElementSummary:
    control_type: str | None = None
    name: str | None = None
    automation_id: str | None = None
    class_name: str | None = None
    framework_id: str | None = None
    is_enabled: bool | None = None
    is_offscreen: bool | None = None
    window_title: str | None = None
    degraded_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UiaQuerier:
    def __init__(self):
        self.degraded_reason: str | None = None
        self._query_lock = threading.Lock()

    def query_at(self, x: int, y: int, timeout_ms: int = 50) -> UiaElementSummary:
        if not self._query_lock.acquire(blocking=False):
            self.degraded_reason = "busy"
            return UiaElementSummary(degraded_reason=self.degraded_reason)
        result_queue: queue.Queue[UiaElementSummary] = queue.Queue(maxsize=1)
        worker = threading.Thread(
            target=self._query_worker,
            args=(x, y, result_queue),
            daemon=True,
            name=f"DesktopUIA-{x}-{y}",
        )
        worker.start()
        try:
            return result_queue.get(timeout=max(0.001, timeout_ms / 1000.0))
        except queue.Empty:
            self.degraded_reason = "timeout"
            worker.join(timeout=0.1)
            return UiaElementSummary(degraded_reason=self.degraded_reason)

    def close(self) -> None:
        return None

    def _query_worker(
        self,
        x: int,
        y: int,
        result_queue: queue.Queue[UiaElementSummary],
    ) -> None:
        try:
            result = self._query_at_sync(x, y)
        except Exception as exc:
            self.degraded_reason = type(exc).__name__
            result = UiaElementSummary(degraded_reason=self.degraded_reason)
        try:
            result_queue.put_nowait(result)
        except queue.Full:
            pass
        finally:
            self._query_lock.release()

    def _query_at_sync(self, x: int, y: int) -> UiaElementSummary:
        try:
            import uiautomation as auto

            element = auto.ControlFromPoint(x, y)
            window = element.GetTopLevelControl() if element else None
            return UiaElementSummary(
                control_type=getattr(element, "ControlTypeName", None),
                name=getattr(element, "Name", None),
                automation_id=getattr(element, "AutomationId", None),
                class_name=getattr(element, "ClassName", None),
                framework_id=getattr(element, "FrameworkId", None),
                is_enabled=getattr(element, "IsEnabled", None),
                is_offscreen=getattr(element, "IsOffscreen", None),
                window_title=getattr(window, "Name", None) if window else None,
            )
        except Exception as exc:
            self.degraded_reason = type(exc).__name__
            return UiaElementSummary(degraded_reason=self.degraded_reason)
