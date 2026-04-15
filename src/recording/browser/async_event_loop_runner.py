from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Optional


class AsyncEventLoopRunner:
    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._loop_ready = threading.Event()

    @property
    def event_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        return self._event_loop

    @event_loop.setter
    def event_loop(self, loop: Optional[asyncio.AbstractEventLoop]) -> None:
        self._event_loop = loop

    @property
    def loop_thread(self) -> Optional[threading.Thread]:
        return self._loop_thread

    @loop_thread.setter
    def loop_thread(self, thread: Optional[threading.Thread]) -> None:
        self._loop_thread = thread

    def ensure_started(self) -> None:
        if (
            self._event_loop is not None
            and not self._event_loop.is_closed()
            and self._loop_thread is not None
            and self._loop_thread.is_alive()
        ):
            return

        self._loop_ready.clear()

        def run_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._event_loop = loop
            self._loop_ready.set()
            try:
                loop.run_forever()
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
                self._event_loop = None

        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()

        if not self._loop_ready.wait(timeout=5):
            raise RuntimeError("等待后台事件循环就绪超时")

    def run(self, coro, timeout: float = 120) -> Any:
        self.ensure_started()
        future = asyncio.run_coroutine_threadsafe(coro, self._event_loop)
        return future.result(timeout=timeout)

    def stop(self, timeout: float = 5) -> None:
        loop = self._event_loop
        if loop is None or loop.is_closed():
            return

        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception as exc:
            self._logger.warning(f"停止事件循环失败: {exc}")
            return

        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=timeout)
