from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from src.business.debug.models import LLMTraceRecord
from src.business.debug.service import DebugInspectorService


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


def _transition(
    transition_id: str,
    event_type: str,
    *,
    from_session_id: str | None = "from_session",
    to_session_id: str | None = "to_session",
    payload: dict | None = None,
):
    return SimpleNamespace(
        transition_id=transition_id,
        workflow_id="wf_matrix",
        from_session_id=from_session_id,
        to_session_id=to_session_id,
        event_type=event_type,
        payload=json.dumps(payload or {}, ensure_ascii=False) if payload is not None else None,
        created_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
    )


MATRIX_TRANSITIONS = [
    _transition(
        "tr_pm_programmer",
        "requirement_confirmed",
        from_session_id="pm_1",
        to_session_id="programmer_1",
        payload={"reason": "PM handoff"},
    ),
    _transition(
        "tr_review_retry",
        "review_failed",
        from_session_id="reviewer",
        to_session_id="programmer_1",
        payload={"retry_count": 1, "feedback": "retry"},
    ),
    _transition(
        "tr_review_passed",
        "review_passed",
        from_session_id="reviewer",
        to_session_id=None,
        payload={"summary": "accepted"},
    ),
    _transition(
        "tr_tool_saved",
        "tool_saved",
        from_session_id="programmer_1",
        to_session_id=None,
        payload={"tool_id": "tool_1", "from_triage": False},
    ),
    _transition(
        "tr_trial_triage",
        "trial_failed",
        from_session_id="trial_1",
        to_session_id="pm_1",
        payload={"reason": "trial failure triage"},
    ),
    _transition(
        "tr_ephemeral_start",
        "assistant_delegation_started",
        from_session_id="assistant_1",
        to_session_id="ephemeral_1",
        payload={"agent_type": "ephemeral_subagent"},
    ),
    _transition(
        "tr_specialist_start",
        "assistant_delegation_started",
        from_session_id="assistant_1",
        to_session_id="specialist_1",
        payload={"agent_type": "specialist"},
    ),
    _transition(
        "tr_executor_return",
        "assistant_delegation_completed",
        from_session_id="ephemeral_1",
        to_session_id="assistant_1",
        payload={"success": True, "result_type": "completed"},
    ),
    _transition(
        "tr_unlinked",
        "agent_error",
        from_session_id="trial_1",
        to_session_id=None,
        payload={"error": "safe summary"},
    ),
]


class FakeWorkflowTransitionRepository:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def list_flow_summaries(self, **_kwargs):
        return [
            {
                "workflowId": "wf_matrix",
                "transitionCount": len(MATRIX_TRANSITIONS),
                "lastEventType": MATRIX_TRANSITIONS[-1].event_type,
                "lastCreatedAt": MATRIX_TRANSITIONS[-1].created_at,
                "linkedTraceCount": 0,
            }
        ]

    def get_by_workflow(self, workflow_id: str):
        return MATRIX_TRANSITIONS if workflow_id == "wf_matrix" else []


@pytest.fixture()
def service(monkeypatch: pytest.MonkeyPatch) -> DebugInspectorService:
    config = FakeConfig()
    monkeypatch.setattr("src.business.debug.service.get_unified_config", lambda: config)
    monkeypatch.setattr(
        "src.business.debug.service.WorkflowTransitionRepository",
        FakeWorkflowTransitionRepository,
    )
    return DebugInspectorService()


def test_agent_flow_projects_teaching_and_assistant_transition_matrix(
    service: DebugInspectorService,
) -> None:
    status = service.arm(warning_acknowledged=True)
    assert service.buffer is not None
    service.buffer.add_record(
        LLMTraceRecord(
            trace_id="trace_pm",
            retention_epoch=status["retentionEpoch"],
            workflow_id="wf_matrix",
            session_id="pm_1",
            source="agent_loop",
        )
    )
    service.buffer.add_record(
        LLMTraceRecord(
            trace_id="trace_executor_llm",
            retention_epoch=status["retentionEpoch"],
            workflow_id="wf_matrix",
            session_id="ephemeral_1",
            source="agent_loop",
        )
    )
    service.capture_delegation_detail(
        transition_id="tr_executor_return",
        workflow_id="wf_matrix",
        input_detail={"task": "do it"},
        output_detail={"resultText": "done"},
    )

    detail = service.get_flow_detail("wf_matrix")
    by_id = {item["transitionId"]: item for item in detail["transitions"]}

    assert by_id["tr_pm_programmer"]["status"] == "handoff"
    assert by_id["tr_review_retry"]["status"] == "retry"
    assert by_id["tr_review_passed"]["status"] == "accepted"
    assert by_id["tr_tool_saved"]["status"] == "published"
    assert by_id["tr_trial_triage"]["status"] == "failed"
    assert by_id["tr_ephemeral_start"]["detail"] is None
    assert by_id["tr_ephemeral_start"]["detailProvenance"] == "unavailable"
    assert by_id["tr_specialist_start"]["detail"] is None
    assert by_id["tr_specialist_start"]["detailProvenance"] == "unavailable"
    assert by_id["tr_executor_return"]["detail"]["input"]["task"] == "do it"
    assert by_id["tr_executor_return"]["detail"]["output"]["resultText"] == "done"
    assert by_id["tr_pm_programmer"]["traceIds"] == ["trace_pm"]
    assert by_id["tr_executor_return"]["traceIds"] == ["trace_executor_llm"]
    assert by_id["tr_unlinked"]["linkStatus"] == "unlinked"
    assert by_id["tr_executor_return"]["detailProvenance"] == "ephemeral_debug_capture"
    assert by_id["tr_executor_return"]["detailAvailability"] == "full_text"
    assert all(item["method"] != "delegation_detail" for item in service.list_traces()["items"])
    assert service.list_flows()["items"][0]["linkedTraceCount"] == 2
