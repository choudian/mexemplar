from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.desktop_api.app import SESSION_HEADER, create_app
from src.desktop_api.ui_events import UiEventValidationError, validate_ui_event_payload

ROOT = Path(__file__).resolve().parents[2]


class FakeConfig:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

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
        return 1_048_576


@pytest.fixture()
def debug_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from src.business.debug import service as service_module

    config = FakeConfig()
    monkeypatch.setattr(service_module, "_debug_service", None)
    monkeypatch.setattr(service_module, "get_unified_config", lambda: config)
    token = "debug-token"
    return TestClient(create_app(token), headers={SESSION_HEADER: token})


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "running", "prompt": "raw model prompt"},
        {"status": "running", "traceId": "trace_1"},
        {"status": "running", "handoffPayload": {"task": "raw delegated task"}},
        {"status": "running", "mediaUrl": "data:image/png;base64,AAAA"},
        {"status": "running", "correlationId": "internal-correlation"},
    ],
)
def test_public_ui_events_reject_diagnostic_only_payload_fields(payload: dict[str, Any]) -> None:
    with pytest.raises(UiEventValidationError):
        validate_ui_event_payload("assistant.progress", payload)


def test_public_ui_events_reject_diagnostic_media_values_on_allowed_keys() -> None:
    with pytest.raises(UiEventValidationError):
        validate_ui_event_payload(
            "trial.progress",
            {"status": "running", "result": "snapshot=data:image/png;base64,AAAA"},
        )


def test_debug_raw_endpoints_are_no_store_and_not_addressed_with_raw_query(
    debug_client: TestClient,
) -> None:
    debug_client.put(
        "/api/debug/control",
        json={"enabled": True, "warningAcknowledged": True},
    )

    for path in ("/api/debug/traces", "/api/debug/flows"):
        response = debug_client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"

    api_source = (ROOT / "frontend/src/api/debug.ts").read_text(encoding="utf-8")
    assert "prompt=" not in api_source
    assert "raw=" not in api_source
    assert "inputMessages=" not in api_source
    assert "outputContent=" not in api_source


def test_debug_frontend_keeps_raw_state_memory_only() -> None:
    debug_sources = [
        ROOT / "frontend/src/api/debug.ts",
        *Path(ROOT / "frontend/src/screens/debug").glob("*.tsx"),
        ROOT / "frontend/src/app/AppShell.tsx",
        ROOT / "frontend/src/app/routes.tsx",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in debug_sources)

    assert "localStorage" not in combined
    assert "sessionStorage" not in combined
    assert "indexedDB" not in combined
    assert "document.cookie" not in combined


def test_assistant_delegation_logs_use_safe_summaries() -> None:
    source = (ROOT / "src/business/agents/tools/assistant_tools.py").read_text(encoding="utf-8")

    assert "task=%s" not in source
    assert "task[:100]" not in source
    assert "task_description[:100]" not in source
    assert "task_chars" in source

    loop_source = (ROOT / "src/business/agents/agent_loop.py").read_text(encoding="utf-8")
    for raw_log_fragment in (
        "question[:50]",
        "content[:50]",
        "user_input[:50]",
        "-> {result}",
        "str(result)[:100]",
        '-> %s", tool_call.name, exc',
    ):
        assert raw_log_fragment not in loop_source
    assert "result_chars=%s" in loop_source
