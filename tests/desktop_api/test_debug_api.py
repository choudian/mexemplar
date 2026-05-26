from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.business.debug.models import LLMTraceRecord
from src.desktop_api.app import SESSION_HEADER, create_app


class FakeConfig:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def set(self, key: str, value: Any, persist: str = "database", value_type: str = "string") -> None:
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
        return 1_048_576


@pytest.fixture()
def debug_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from src.business.debug import service as service_module

    config = FakeConfig()
    monkeypatch.setattr(service_module, "_debug_service", None)
    monkeypatch.setattr(service_module, "get_unified_config", lambda: config)
    token = "debug-token"
    return TestClient(create_app(token), headers={SESSION_HEADER: token})


def test_debug_control_requires_session_token() -> None:
    response = TestClient(create_app("expected")).get("/api/debug/control")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "desktop_api_unauthorized"


def test_control_status_is_available_while_disabled(debug_client: TestClient) -> None:
    response = debug_client.get("/api/debug/control")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["retentionEpoch"] is None
    assert "调试记录可能包含原始用户文本" in payload["warning"]


def test_arm_requires_warning_acknowledgement(debug_client: TestClient) -> None:
    response = debug_client.put(
        "/api/debug/control",
        json={"enabled": True, "warningAcknowledged": False},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "debug_warning_required"


def test_raw_trace_endpoints_fail_closed_when_disabled(debug_client: TestClient) -> None:
    response = debug_client.get("/api/debug/traces")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "debug_disabled"
    assert response.headers["cache-control"] == "no-store"

    cleared = debug_client.delete("/api/debug/traces")

    assert cleared.status_code == 404
    assert cleared.json()["error"]["code"] == "debug_disabled"
    assert cleared.headers["cache-control"] == "no-store"


def test_arm_list_detail_and_clear_trace_with_no_store(debug_client: TestClient) -> None:
    from src.business.debug.service import get_debug_service

    armed = debug_client.put(
        "/api/debug/control",
        json={"enabled": True, "warningAcknowledged": True},
    )
    assert armed.status_code == 200
    epoch = armed.json()["retentionEpoch"]

    service = get_debug_service()
    assert service.buffer is not None
    service.buffer.add_record(
        LLMTraceRecord(
            trace_id="trace-1",
            retention_epoch=epoch,
            source="agent_loop",
            session_id="session-1",
            input_messages='[{"role":"user","content":"hello"}]',
            output_content="world",
        )
    )

    listed = debug_client.get("/api/debug/traces")
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "no-store"
    assert listed.json()["items"][0]["traceId"] == "trace-1"

    detail = debug_client.get("/api/debug/traces/trace-1")
    assert detail.status_code == 200
    assert detail.headers["cache-control"] == "no-store"
    assert detail.json()["inputMessages"] == [{"role": "user", "content": "hello"}]
    assert detail.json()["outputContent"] == "world"

    cleared = debug_client.delete("/api/debug/traces")
    assert cleared.status_code == 204
    assert cleared.headers["cache-control"] == "no-store"

    assert debug_client.get("/api/debug/traces/trace-1").status_code == 404


def test_stop_disables_and_purges_raw_access(debug_client: TestClient) -> None:
    debug_client.put(
        "/api/debug/control",
        json={"enabled": True, "warningAcknowledged": True},
    )

    stopped = debug_client.put("/api/debug/control", json={"enabled": False})

    assert stopped.status_code == 200
    assert stopped.json()["enabled"] is False
    assert debug_client.get("/api/debug/traces").json()["error"]["code"] == "debug_disabled"


def test_runtime_token_and_rotated_secrets_are_redacted_at_response_boundary(
    debug_client: TestClient,
) -> None:
    from src.business.debug.service import get_debug_service

    armed = debug_client.put(
        "/api/debug/control",
        json={"enabled": True, "warningAcknowledged": True},
    )
    epoch = armed.json()["retentionEpoch"]
    service = get_debug_service()
    assert service.buffer is not None
    service.buffer.add_record(
        LLMTraceRecord(
            trace_id="trace-secret",
            retention_epoch=epoch,
            input_messages='{"content":"debug-token rotated-secret"}',
            input_tools='{"token":"rotated-secret"}',
            output_tool_calls='[{"args":"debug-token"}]',
            output_content="rotated-secret",
        )
    )
    service.register_secret("rotated-secret")

    detail = debug_client.get("/api/debug/traces/trace-secret").text

    assert "debug-token" not in detail
    assert "rotated-secret" not in detail
    assert "***REDACTED***" in detail
