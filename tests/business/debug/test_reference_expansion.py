from __future__ import annotations

from typing import Any

import pytest

from src.business.debug.service import DebugInspectorService


class FakeConfig:
    def __init__(self, max_response_bytes: int = 1_048_576) -> None:
        self.values: dict[str, Any] = {}
        self.max_response_bytes = max_response_bytes

    def set(
        self, key: str, value: Any, persist: str = "database", value_type: str = "string"
    ) -> None:
        self.values[key] = value

    def get_debug_trace_enabled(self) -> bool:
        return bool(self.values.get("debug.trace.enabled", False))

    def get_debug_trace_max_records(self) -> int:
        return 200

    def get_debug_trace_max_record_bytes(self) -> int:
        return 1_048_576

    def get_debug_trace_max_total_bytes(self) -> int:
        return 16_777_216

    def get_debug_reference_max_response_bytes(self) -> int:
        return self.max_response_bytes


@pytest.fixture()
def fake_config(monkeypatch: pytest.MonkeyPatch) -> FakeConfig:
    config = FakeConfig(max_response_bytes=10)
    monkeypatch.setattr("src.business.debug.service.get_unified_config", lambda: config)
    return config


def test_reference_expansion_requires_enabled_trace(fake_config: FakeConfig) -> None:
    service = DebugInspectorService()

    with pytest.raises(LookupError, match="debug_disabled"):
        service.expand_reference("msg_1", loader_fn=lambda _ref: "content")


def test_reference_expansion_redacts_and_truncates_to_response_budget(
    fake_config: FakeConfig,
) -> None:
    service = DebugInspectorService()
    service.register_secret("secret")
    service.arm(warning_acknowledged=True)

    result = service.expand_reference(
        "msg_1",
        loader_fn=lambda _ref: "secret-very-long-reference",
    )

    assert result["referenceId"] == "msg_1"
    assert result["available"] is True
    assert result["truncated"] is True
    assert "secret" not in result["content"]
    assert len(result["content"].encode("utf-8")) <= fake_config.max_response_bytes


def test_reference_expansion_not_found_is_explicit(fake_config: FakeConfig) -> None:
    service = DebugInspectorService()
    service.arm(warning_acknowledged=True)

    with pytest.raises(LookupError, match="reference_not_found"):
        service.expand_reference("missing", loader_fn=lambda _ref: None)


def test_reference_loader_value_error_maps_to_not_found(fake_config: FakeConfig) -> None:
    service = DebugInspectorService()
    service.arm(warning_acknowledged=True)

    def missing(_ref: str) -> str:
        raise ValueError("消息不存在")

    with pytest.raises(LookupError, match="reference_not_found"):
        service.expand_reference("missing", loader_fn=missing)
