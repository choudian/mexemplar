from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FrameSample:
    timestamp: float
    image_path: Path | None = None
    image_data: object | None = None
    monitor_index: int = 0


class FrameRingBuffer:
    def __init__(self, fps: int = 15, capacity: int = 30):
        self.fps = fps
        self.capacity = capacity
        self._lock = threading.RLock()
        self._frames_by_monitor: dict[int, deque[FrameSample]] = defaultdict(
            lambda: deque(maxlen=capacity)
        )

    def append(self, frame: FrameSample) -> None:
        with self._lock:
            self._frames_by_monitor[int(frame.monitor_index)].append(frame)

    def frames_for_action(
        self,
        action_timestamp: float,
        *,
        monitor_index: int | None = None,
        start_time: float | None = None,
    ) -> list[FrameSample]:
        start = start_time if start_time is not None else action_timestamp - 1.0
        end = action_timestamp + 2.0
        with self._lock:
            if monitor_index is None:
                frames = [
                    frame
                    for monitor_frames in self._frames_by_monitor.values()
                    for frame in monitor_frames
                ]
            else:
                frames = list(self._frames_by_monitor.get(int(monitor_index), ()))
        return sorted(
            [frame for frame in frames if start <= frame.timestamp <= end],
            key=lambda frame: frame.timestamp,
        )

    def clear(self) -> None:
        with self._lock:
            self._frames_by_monitor.clear()
