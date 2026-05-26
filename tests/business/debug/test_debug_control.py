from __future__ import annotations

from typing import Any

import pytest

from src.business.debug.models import LLMTraceRecord
from src.business.debug.service import DebugInspectorService


class FakeConfig:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.set_calls: list[tuple[str, Any, str]] = []

    def set(self, key: str, value: Any, persist: str = "database", value_type: str = "string") -> None:
        self.values[key] = value
        self.set_calls.append((key, value, persist))

    def get_debug_trace_enabled(self) -> bool:
        return bool(self.values.get("debug.trace.enabled", False))

    def get_debug_trace_max_records(self) -> int:
        return 3

    def get_debug_trace_max_record_bytes(self) -> int:
        return 128

    def get_debug_trace_max_total_bytes(self) -> int:
        return 256


@pytest.fixture()
def fake_config(monkeypatch: pytest.MonkeyPatch) -> FakeConfig:
    config = FakeConfig()
    monkeypatch.setattr("src.business.debug.service.get_unified_config", lambda: config)
    return config


def test_arm_requires_warning_acknowledgement(fake_config: FakeConfig) -> None:
    service = DebugInspectorService()

    with pytest.raises(ValueError, match="debug_warning_required"):
        service.arm(warning_acknowledged=False)

    assert fake_config.set_calls == []
    assert service.buffer is None


def test_arm_creates_runtime_epoch_and_status(fake_config: FakeConfig) -> None:
    service = DebugInspectorService()

    status = service.arm(warning_acknowledged=True)

    assert status["enabled"] is True
    assert status["armedAt"] is not None
    assert status["retentionEpoch"]
    assert service.buffer is not None
    assert fake_config.set_calls == [("debug.trace.enabled", True, "runtime")]


def test_stop_invalidates_epoch_and_purges_records(fake_config: FakeConfig) -> None:
    service = DebugInspectorService()
    status = service.arm(warning_acknowledged=True)
    epoch = status["retentionEpoch"]
    assert service.buffer is not None
    assert service.buffer.add_record(
        LLMTraceRecord(retention_epoch=epoch, input_messages="raw text")
    )

    stopped = service.stop()

    assert stopped["enabled"] is False
    assert stopped["retentionEpoch"] is None
    assert service.buffer is None
    assert service.current_epoch is None
    assert fake_config.set_calls[-1] == ("debug.trace.enabled", False, "runtime")


def test_clear_keeps_enabled_but_starts_empty_epoch(fake_config: FakeConfig) -> None:
    service = DebugInspectorService()
    status = service.arm(warning_acknowledged=True)
    first_epoch = status["retentionEpoch"]
    assert service.buffer is not None
    assert service.buffer.add_record(
        LLMTraceRecord(retention_epoch=first_epoch, input_messages="raw text")
    )

    service.clear()

    assert service.is_enabled() is True
    assert service.current_epoch
    assert service.current_epoch != first_epoch
    assert service.buffer is not None
    assert service.buffer.get_record_count() == 0


def test_reenable_after_stop_creates_new_empty_epoch(fake_config: FakeConfig) -> None:
    service = DebugInspectorService()
    first_epoch = service.arm(warning_acknowledged=True)["retentionEpoch"]
    service.stop()

    second_epoch = service.arm(warning_acknowledged=True)["retentionEpoch"]

    assert second_epoch != first_epoch
    assert service.buffer is not None
    assert service.buffer.get_record_count() == 0


def test_stop_cleanup_failure_still_makes_old_epoch_unreadable(fake_config: FakeConfig) -> None:
    service = DebugInspectorService()
    epoch = service.arm(warning_acknowledged=True)["retentionEpoch"]
    old_buffer = service.buffer
    assert old_buffer is not None

    def fail_invalidate() -> None:
        raise RuntimeError("cleanup failed")

    old_buffer.invalidate_epoch = fail_invalidate  # type: ignore[method-assign]

    stopped = service.stop()

    assert stopped["enabled"] is False
    assert service.buffer is None
    assert service.current_epoch is None
    assert old_buffer.get_records(epoch=epoch) == []
    assert old_buffer._budget.get_retained_bytes() == 0  # type: ignore[attr-defined]


def test_stale_enabled_config_without_active_epoch_does_not_open_raw_facade(
    fake_config: FakeConfig,
) -> None:
    fake_config.values["debug.trace.enabled"] = True
    service = DebugInspectorService()

    assert service.get_status()["enabled"] is False
    with pytest.raises(LookupError, match="debug_disabled"):
        service.list_flows()
    with pytest.raises(LookupError, match="debug_disabled"):
        service.expand_reference("ref-1", loader_fn=lambda _reference_id: "raw")
