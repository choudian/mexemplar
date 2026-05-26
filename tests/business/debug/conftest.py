"""
tests/business/debug/ 共享 fixture。

提供：
- fake_clock：返回固定 ISO datetime 的 callable
- fake_credential_provider：返回固定 sentinel 值，用于 redaction 测试
- fake_trace_buffer：简化版 TraceBuffer，用于 control / service 测试
"""

import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable

import pytest


# ---------------------------------------------------------------------------
# Fake clock
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_clock() -> Callable[[], str]:
    """返回一个固定 ISO datetime 字符串的 callable。

    每次调用返回相同的值 ``"2026-05-24T12:00:00+00:00"``，
    测试中可借此断言时间戳不漂移。
    """

    fixed = "2026-05-24T12:00:00+00:00"

    def _clock() -> str:
        return fixed

    return _clock


# ---------------------------------------------------------------------------
# Fake credential provider
# ---------------------------------------------------------------------------

_SENTINEL_KEY = "sk-sentinel-████-redacted-████"


@pytest.fixture()
def fake_credential_provider() -> Callable[[str], str]:
    """返回固定 sentinel 的凭据 provider。

    无论传入什么 service/key 名称，始终返回 ``_SENTINEL_KEY``。
    用于验证 redaction 路径在脱敏时能拿到一个稳定的占位值。
    """

    def _provider(service_name: str, key_name: str) -> str:
        return _SENTINEL_KEY

    return _provider


@pytest.fixture()
def sentinel_value() -> str:
    """暴露 sentinel 常量，供断言使用。"""
    return _SENTINEL_KEY


# ---------------------------------------------------------------------------
# Fake trace buffer
# ---------------------------------------------------------------------------

class _FakeRecord:
    """最小化的 trace record 对象，仅保留 id / payload / epoch_id。"""

    __slots__ = ("record_id", "payload", "epoch_id", "timestamp")

    def __init__(self, payload: str, epoch_id: str, timestamp: str) -> None:
        self.record_id: str = uuid.uuid4().hex[:12]
        self.payload: str = payload
        self.epoch_id: str = epoch_id
        self.timestamp: str = timestamp


class FakeTraceBuffer:
    """简化版 TraceBuffer，用于 control / service 级别的单元测试。

    提供 ``add`` / ``records`` / ``purge`` / ``size`` 接口，
    但不做真实的字节预算淘汰 —— 那部分由 ``test_trace_buffer.py`` 覆盖。
    """

    def __init__(self, *, max_records: int = 200) -> None:
        self._records: deque[_FakeRecord] = deque(maxlen=max_records)
        self._current_epoch: str | None = None
        self._clock: Callable[[], str] = lambda: datetime.now(timezone.utc).isoformat()

    def set_clock(self, clock: Callable[[], str]) -> None:
        self._clock = clock

    def set_epoch(self, epoch_id: str | None) -> None:
        self._current_epoch = epoch_id

    def add(self, payload: str) -> _FakeRecord | None:
        if self._current_epoch is None:
            return None
        rec = _FakeRecord(
            payload=payload,
            epoch_id=self._current_epoch,
            timestamp=self._clock(),
        )
        self._records.append(rec)
        return rec

    @property
    def records(self) -> list[_FakeRecord]:
        return list(self._records)

    def purge(self) -> int:
        count = len(self._records)
        self._records.clear()
        return count

    @property
    def size(self) -> int:
        return len(self._records)


@pytest.fixture()
def fake_trace_buffer() -> FakeTraceBuffer:
    """返回一个空白的 FakeTraceBuffer 实例。"""
    return FakeTraceBuffer()
