from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from src.business.debug.models import LLMTraceRecord
from src.business.debug.service import DebugInspectorService


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


class FakeWorkflowTransitionRepository:
    transition = SimpleNamespace(
        transition_id="tr_1",
        workflow_id="wf_1",
        from_session_id="pm_1",
        to_session_id="programmer_1",
        event_type="requirement_confirmed",
        payload='{"reason":"handoff secret-token","requirements":{"goal":"ship"}}',
        created_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
    )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def list_flow_summaries(self, **_kwargs):
        return [
            {
                "workflowId": "wf_1",
                "transitionCount": 1,
                "lastEventType": "requirement_confirmed",
                "lastCreatedAt": self.transition.created_at,
                "linkedTraceCount": 0,
            }
        ]

    def get_by_workflow(self, workflow_id: str):
        return [self.transition] if workflow_id == "wf_1" else []


@pytest.fixture()
def service_with_flow_repo(monkeypatch: pytest.MonkeyPatch) -> DebugInspectorService:
    config = FakeConfig()
    monkeypatch.setattr("src.business.debug.service.get_unified_config", lambda: config)
    monkeypatch.setattr(
        "src.business.debug.service.WorkflowTransitionRepository",
        FakeWorkflowTransitionRepository,
    )
    service = DebugInspectorService()
    service.register_secret("secret-token")
    return service


def test_flow_projection_requires_enabled_trace(
    service_with_flow_repo: DebugInspectorService,
) -> None:
    with pytest.raises(LookupError, match="debug_disabled"):
        service_with_flow_repo.list_flows()


def test_flow_summary_counts_linked_traces(service_with_flow_repo: DebugInspectorService) -> None:
    status = service_with_flow_repo.arm(warning_acknowledged=True)
    assert service_with_flow_repo.buffer is not None
    service_with_flow_repo.buffer.add_record(
        LLMTraceRecord(
            trace_id="trace_1",
            retention_epoch=status["retentionEpoch"],
            workflow_id="wf_1",
            session_id="pm_1",
            input_messages="prompt",
        )
    )

    result = service_with_flow_repo.list_flows()

    assert result["items"][0]["workflowId"] == "wf_1"
    assert result["items"][0]["linkedTraceCount"] == 1


def test_flow_detail_projects_persisted_transition_with_redaction_and_link_status(
    service_with_flow_repo: DebugInspectorService,
) -> None:
    status = service_with_flow_repo.arm(warning_acknowledged=True)
    assert service_with_flow_repo.buffer is not None
    service_with_flow_repo.buffer.add_record(
        LLMTraceRecord(
            trace_id="trace_1",
            retention_epoch=status["retentionEpoch"],
            workflow_id="wf_1",
            linked_transition_ids=["tr_1"],
            input_messages="prompt",
        )
    )

    detail = service_with_flow_repo.get_flow_detail("wf_1")

    [transition] = detail["transitions"]
    assert transition["eventType"] == "requirement_confirmed"
    assert transition["status"] == "handoff"
    assert transition["detailProvenance"] == "persisted_transition"
    assert transition["linkStatus"] == "linked"
    assert transition["traceIds"] == ["trace_1"]
    assert transition["detail"]["reason"] == "handoff ***REDACTED***"


def test_new_ephemeral_detail_evicts_older_trace_under_shared_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = FakeConfig()
    config.get_debug_trace_max_total_bytes = lambda: 64  # type: ignore[method-assign]
    monkeypatch.setattr("src.business.debug.service.get_unified_config", lambda: config)
    monkeypatch.setattr(
        "src.business.debug.service.WorkflowTransitionRepository",
        FakeWorkflowTransitionRepository,
    )
    service = DebugInspectorService()
    status = service.arm(warning_acknowledged=True)
    assert service.buffer is not None
    assert service.buffer.add_record(
        LLMTraceRecord(
            trace_id="trace_full",
            retention_epoch=status["retentionEpoch"],
            input_messages="x" * 64,
        )
    )

    service.capture_delegation_detail(
        transition_id="tr_1",
        workflow_id="wf_1",
        input_detail={"task": "delegate this"},
    )

    [transition] = service.get_flow_detail("wf_1")["transitions"]
    assert transition["detailProvenance"] == "ephemeral_debug_capture"
    assert transition["detailAvailability"] == "full_text"
    assert transition["detail"]["input"]["task"] == "delegate this"
    assert service.buffer.get_record("trace_full") is None
