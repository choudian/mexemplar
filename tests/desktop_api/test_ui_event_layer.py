from __future__ import annotations

import queue

import pytest

from src.desktop_api.events import event_queue, install_blinker_event_adapter
from src.desktop_api.ui_events import (
    UiEventValidationError,
    exported_registry_examples,
    registered_event_types,
    validate_ui_event_payload,
)
from src.utils.events import emit


def drain_events() -> None:
    while True:
        try:
            event_queue.queue.get_nowait()
        except queue.Empty:
            return


def setup_function() -> None:
    event_queue.reset_for_tests()
    drain_events()


def test_registered_event_examples_pass_payload_validation() -> None:
    for event_type, example in exported_registry_examples().items():
        validate_ui_event_payload(event_type, example)


def test_unregistered_direct_publication_is_rejected() -> None:
    with pytest.raises(UiEventValidationError):
        event_queue.publish_nowait("backend.event", {"message": "raw"})


def test_unsafe_payload_is_rejected_before_publication() -> None:
    with pytest.raises(UiEventValidationError):
        event_queue.publish_nowait("assistant.progress", {"message": "MEXEMPLAR_DESKTOP_TOKEN=secret"})
    with pytest.raises(UiEventValidationError):
        event_queue.publish_nowait("assistant.progress", {"token": "secret"})


def test_trial_preview_code_preview_still_gets_safety_validation() -> None:
    payload = {
        "requestId": "preview_unsafe",
        "workflowId": "rec_unsafe",
        "trialId": "trial_unsafe",
        "summary": "桌面试用需要确认。",
        "codePreview": "MEXEMPLAR_DESKTOP_TOKEN=secret",
        "riskSummary": "将控制本机桌面。",
        "expires_at": "2026-05-16T00:00:30Z",
        "status": "pending",
    }

    with pytest.raises(UiEventValidationError):
        event_queue.publish_nowait("trial.preview_requested", payload, {"workflowId": "rec_unsafe"})


def test_trial_preview_code_preview_rejects_direct_overlong_payload() -> None:
    payload = {
        "requestId": "preview_long",
        "workflowId": "rec_long",
        "trialId": "trial_long",
        "summary": "桌面试用需要确认。",
        "codePreview": "x" * 1201,
        "riskSummary": "将控制本机桌面。",
        "expires_at": "2026-05-16T00:00:30Z",
        "status": "pending",
    }

    with pytest.raises(UiEventValidationError):
        event_queue.publish_nowait("trial.preview_requested", payload, {"workflowId": "rec_long"})


def test_workflow_scoped_events_require_matching_workflow_scope() -> None:
    payload = {
        "requestId": "preview_scope",
        "workflowId": "rec_scope",
        "trialId": "trial_scope",
        "summary": "桌面试用需要确认。",
        "codePreview": "print('safe preview')",
        "riskSummary": "将控制本机桌面。",
        "expires_at": "2026-05-16T00:00:30Z",
        "status": "pending",
    }

    with pytest.raises(UiEventValidationError):
        event_queue.publish_nowait("trial.preview_requested", payload, {})
    with pytest.raises(UiEventValidationError):
        event_queue.publish_nowait(
            "trial.preview_requested",
            payload,
            {"workflowId": "other_workflow"},
        )


def test_internal_events_project_to_semantic_ui_events(desktop_api_client) -> None:
    install_blinker_event_adapter()

    emit("recording_started", sender=None, workflow_id="rec_1", recording_mode="desktop")
    emit("requirement_confirmed", sender=None, workflow_id="rec_1")
    emit("trial_success", sender=None, workflow_id="rec_1", published=True, success_count=3)

    events = [event_queue.queue.get_nowait() for _ in range(6)]
    assert [event.type for event in events] == [
        "recording.progress",
        "teaching.stage_changed",
        "teaching.stage_changed",
        "teaching.progress",
        "trial.progress",
        "teaching.stage_changed",
    ]
    assert events[0].scope == {"workflowId": "rec_1"}
    assert events[1].payload["stage"] == "recording"
    assert events[2].payload["stage"] == "learning"
    assert events[4].payload["published"] is True
    assert all("sourceEvent" not in event.payload for event in events)


def test_internal_projection_filters_scope_to_public_event_contract(
    desktop_api_client,
) -> None:
    install_blinker_event_adapter()

    emit(
        "trial_success",
        sender=None,
        workflow_id="rec_1",
        session_id="ast_1",
        tool_id="tool_1",
        published=False,
        success_count=1,
    )
    emit(
        "tool_saved",
        sender=None,
        workflow_id="rec_1",
        session_id="ast_1",
        tool_id="tool_1",
    )

    trial_event = event_queue.queue.get_nowait()
    skills_event = event_queue.queue.get_nowait()
    assert trial_event.type == "trial.progress"
    assert trial_event.scope == {"workflowId": "rec_1", "toolId": "tool_1"}
    assert skills_event.type == "skills.changed"
    assert skills_event.scope == {"toolId": "tool_1"}


def test_trial_failed_does_not_project_raw_failure_message_to_user(
    desktop_api_client,
) -> None:
    install_blinker_event_adapter()

    emit("trial_failed", sender=None, workflow_id="rec_1", tool_id="tool_1", error="internal traceback")

    event = event_queue.queue.get_nowait()
    assert event_queue.queue.empty()
    assert event.type == "teaching.stage_changed"
    assert event.scope == {"workflowId": "rec_1"}
    assert event.payload["stage"] == "failed"
    assert event.payload["failureStage"] == "trial"
    assert "headline" not in event.payload
    assert "internal traceback" not in str(event.payload)


def test_catalog_settings_and_assistant_events_project_to_registered_ui_events(
    desktop_api_client,
) -> None:
    install_blinker_event_adapter()

    emit("skills_changed", sender=None, tool_id="tool_1")
    emit("composition_review_needed", sender=None, composition_id="comp_1")
    emit("settings_changed", sender=None, keys=["theme"])
    emit(
        "agent_needs_user_input",
        sender=None,
        session_id="ast_1",
        question="Need more detail",
    )

    events = [event_queue.queue.get_nowait() for _ in range(4)]
    assert [event.type for event in events] == [
        "skills.changed",
        "compositions.changed",
        "settings.changed",
        "assistant.progress",
    ]
    assert events[0].payload == {"reason": "catalog_invalidated", "toolId": "tool_1"}
    assert events[1].payload == {
        "reason": "catalog_invalidated",
        "compositionId": "comp_1",
    }
    assert events[2].payload == {"reason": "settings_invalidated", "keys": ["theme"]}
    assert events[3].scope == {"sessionId": "ast_1"}
    assert events[3].payload["question"] == "Need more detail"
    assert all("sourceEvent" not in event.payload for event in events)


def test_registry_contains_contract_event_types() -> None:
    expected = {
        "assistant.message",
        "recording.progress",
        "teaching.stage_changed",
        "trial.preview_requested",
        "backend.resync_required",
    }

    assert expected.issubset(set(registered_event_types()))
