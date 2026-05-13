from __future__ import annotations

import queue

from src.desktop_api.events import event_queue, install_blinker_event_adapter
from src.utils import events as backend_events
from src.utils.events import emit


def drain_events() -> None:
    while True:
        try:
            event_queue.queue.get_nowait()
        except queue.Empty:
            return


def test_recording_teaching_and_trial_events_map_to_frontend_types(desktop_api_client):
    drain_events()
    install_blinker_event_adapter()

    emit("recording_started", sender=None, workflow_id="rec_1", recording_mode="desktop")
    emit("requirement_confirmed", sender=None, workflow_id="rec_1")
    emit("trial_success", sender=None, workflow_id="rec_1", published=False)

    events = [event_queue.queue.get_nowait() for _ in range(3)]
    assert [event.type for event in events] == [
        "recording.progress",
        "teaching.progress",
        "trial.progress",
    ]
    assert events[0].scope == {"workflowId": "rec_1"}
    assert events[2].payload["published"] is False


def test_teaching_failure_event_maps_to_teaching_progress(desktop_api_client):
    drain_events()
    install_blinker_event_adapter()

    emit(
        "teaching_failure_updated",
        sender=None,
        workflow_id="rec_2",
        failed_stage="programmer",
    )

    event = event_queue.queue.get_nowait()
    assert event.type == "teaching.progress"
    assert event.scope == {"workflowId": "rec_2"}
    assert event.payload["failed_stage"] == "programmer"


def test_direct_desktop_recording_signal_uses_connected_event_name(desktop_api_client):
    drain_events()
    install_blinker_event_adapter()

    backend_events.desktop_action_count_changed.send(
        None,
        recording_id="rec_direct",
        action_count=5,
    )

    event = event_queue.queue.get_nowait()
    assert event.type == "recording.progress"
    assert event.scope == {"workflowId": "rec_direct"}
    assert event.payload["action_count"] == 5
