"""Shared forceful-cancellation primitives for Agent I/O and process execution."""

from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class CancelReason(str, Enum):
    """Cancellation reason controls how an in-flight side effect is handled."""

    USER_CANCEL = "user-cancel"
    SIBLING_ERROR = "sibling_error"


CancelCallback = Callable[[CancelReason], None]


class CancelToken:
    """Event-compatible cancellation signal with first-decision-wins callbacks."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason: CancelReason | None = None
        self._callbacks: dict[int, CancelCallback] = {}
        self._next_callback_id = 0

    @property
    def reason(self) -> CancelReason | None:
        with self._lock:
            return self._reason

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout=timeout)

    def set(self) -> None:
        """``threading.Event`` compatibility; legacy callers mean user cancellation."""
        self.cancel(CancelReason.USER_CANCEL)

    def cancel(self, reason: CancelReason = CancelReason.USER_CANCEL) -> bool:
        resolved = CancelReason(reason)
        with self._lock:
            if self._reason is not None:
                return False
            self._reason = resolved
            self._event.set()
            callbacks = tuple(self._callbacks.values())
            self._callbacks.clear()
        for callback in callbacks:
            self._invoke_callback(callback, resolved)
        return True

    def add_callback(self, callback: CancelCallback) -> Callable[[], None]:
        """Register a callback and return an idempotent unregister function."""
        with self._lock:
            reason = self._reason
            if reason is None:
                self._next_callback_id += 1
                callback_id = self._next_callback_id
                self._callbacks[callback_id] = callback
            else:
                callback_id = None
        if reason is not None:
            self._invoke_callback(callback, reason)

        def remove() -> None:
            if callback_id is None:
                return
            with self._lock:
                self._callbacks.pop(callback_id, None)

        return remove

    @staticmethod
    def _invoke_callback(callback: CancelCallback, reason: CancelReason) -> None:
        try:
            callback(reason)
        except Exception:
            logger.warning(
                "[cancellation] callback failed: reason=%s",
                reason.value,
                exc_info=True,
            )


def should_abort_http(reason: CancelReason | None) -> bool:
    return reason in {
        CancelReason.USER_CANCEL,
        CancelReason.SIBLING_ERROR,
    }


def should_terminate_command(reason: CancelReason | None) -> bool:
    return reason in {CancelReason.USER_CANCEL, CancelReason.SIBLING_ERROR}


def should_persist_interrupted_tool(reason: CancelReason | None) -> bool:
    return reason in {CancelReason.USER_CANCEL, CancelReason.SIBLING_ERROR}
