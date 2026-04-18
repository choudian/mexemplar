from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from PyQt6.QtTest import QTest

from src.utils.events import _signals


class WaitHelper:
    _PROFILE_DEFAULT_TIMEOUT = {
        "mock": 15_000,
        "real": 60_000,
    }

    def __init__(self, timeout_profile: str = "mock") -> None:
        self.timeout_profile = timeout_profile
        self._handlers: list[Callable] = []

    def wait_signal(self, signal_name: str, timeout_ms: Optional[int] = None) -> Optional[dict]:
        received = threading.Event()
        payload: dict = {}

        def handler(sender, **kwargs):
            payload.update(kwargs)
            received.set()

        self._handlers.append(handler)
        signal = _signals.signal(signal_name)
        signal.connect(handler, weak=False)

        try:
            deadline = time.time() + self._resolve_timeout(timeout_ms) / 1000
            while time.time() < deadline:
                if received.is_set():
                    return payload
                QTest.qWait(50)
            return None
        finally:
            signal.disconnect(handler)

    def wait_until(
        self,
        predicate: Callable[[], bool],
        timeout_ms: int = 10_000,
        interval_ms: int = 100,
    ) -> bool:
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            if predicate():
                return True
            QTest.qWait(interval_ms)
        return False

    @staticmethod
    def sleep(ms: int) -> None:
        QTest.qWait(ms)

    def _resolve_timeout(self, timeout_ms: Optional[int]) -> int:
        if timeout_ms is not None:
            return timeout_ms
        return self._PROFILE_DEFAULT_TIMEOUT.get(self.timeout_profile, 15_000)
