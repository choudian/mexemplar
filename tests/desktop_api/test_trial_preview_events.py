from __future__ import annotations

import asyncio
import queue
import threading
from datetime import datetime, timedelta, timezone

from src.desktop_api.events import event_queue, install_blinker_event_adapter
from src.desktop_api.ui_events import trial_preview_manager
from src.utils.events import emit_collect


def setup_function() -> None:
    event_queue.reset_for_tests()


def _emit_preview(holder: dict[str, object], *, timeout_seconds: float = 1.0) -> None:
    holder["responses"] = emit_collect(
        "desktop_trial_preview_ready",
        sender=None,
        workflow_id="rec_preview",
        trial_id="trial_1",
        code="print('full code must stay backend-only')",
        code_preview="print('safe preview')",
        timeout_seconds=timeout_seconds,
    )


def test_trial_preview_approval_returns_true(desktop_api_client) -> None:
    install_blinker_event_adapter()
    holder: dict[str, object] = {}
    worker = threading.Thread(target=_emit_preview, args=(holder,))
    worker.start()

    event = event_queue.queue.get(timeout=1)
    assert event.type == "trial.preview_requested"
    assert "code" not in event.payload
    request_id = str(event.payload["requestId"])

    response = desktop_api_client.post(
        f"/api/teaching/trial-preview/{request_id}/decision",
        json={"decision": "approve"},
    )

    worker.join(timeout=2)
    resolved = event_queue.queue.get(timeout=1)
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert resolved.type == "trial.preview_resolved"
    assert resolved.payload["requestId"] == request_id
    assert resolved.payload["status"] == "approved"
    assert holder["responses"][0][1] is True


def test_trial_preview_denial_returns_false(desktop_api_client) -> None:
    install_blinker_event_adapter()
    holder: dict[str, object] = {}
    worker = threading.Thread(target=_emit_preview, args=(holder,))
    worker.start()
    event = event_queue.queue.get(timeout=1)

    response = desktop_api_client.post(
        f"/api/teaching/trial-preview/{event.payload['requestId']}/decision",
        json={"decision": "deny"},
    )

    worker.join(timeout=2)
    resolved = event_queue.queue.get(timeout=1)
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert resolved.type == "trial.preview_resolved"
    assert resolved.payload["status"] == "denied"
    assert holder["responses"][0][1] is False


def test_trial_preview_timeout_fails_closed() -> None:
    install_blinker_event_adapter()
    holder: dict[str, object] = {}
    worker = threading.Thread(
        target=_emit_preview, args=(holder,), kwargs={"timeout_seconds": 0.05}
    )
    worker.start()

    requested = event_queue.queue.get(timeout=1)
    resolved = event_queue.queue.get(timeout=1)
    worker.join(timeout=1)

    assert requested.type == "trial.preview_requested"
    assert resolved.type == "trial.preview_resolved"
    assert resolved.payload["status"] == "timeout"
    assert holder["responses"][0][1] is False


def test_trial_preview_late_decision_publishes_expired_resolution(
    desktop_api_client,
) -> None:
    install_blinker_event_adapter()
    holder: dict[str, object] = {}
    worker = threading.Thread(
        target=_emit_preview, args=(holder,), kwargs={"timeout_seconds": 10.0}
    )
    worker.start()

    requested = event_queue.queue.get(timeout=1)
    request_id = str(requested.payload["requestId"])
    with trial_preview_manager._lock:
        trial_preview_manager._records[request_id].expires_at = datetime.now(
            timezone.utc
        ) - timedelta(seconds=1)

    response = desktop_api_client.post(
        f"/api/teaching/trial-preview/{request_id}/decision",
        json={"decision": "approve"},
    )

    worker.join(timeout=2)
    resolved = event_queue.queue.get(timeout=1)
    assert response.status_code == 200
    assert response.json()["accepted"] is False
    assert response.json()["status"] == "expired"
    assert resolved.type == "trial.preview_resolved"
    assert resolved.payload["requestId"] == request_id
    assert resolved.payload["status"] == "expired"
    assert resolved.payload["decision"] == "deny"
    assert holder["responses"][0][1] is False


def test_trial_preview_disconnect_fails_closed() -> None:
    install_blinker_event_adapter()
    holder: dict[str, object] = {}
    worker = threading.Thread(target=_emit_preview, args=(holder,))

    async def read_request_and_disconnect() -> None:
        stream = event_queue.stream()
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        worker.start()
        event = await asyncio.wait_for(pending, timeout=1)
        assert event.type == "trial.preview_requested"
        await stream.aclose()

    asyncio.run(read_request_and_disconnect())
    worker.join(timeout=2)

    requested = event_queue.queue.get(timeout=1)
    resolved = event_queue.queue.get(timeout=1)
    assert requested.type == "trial.preview_requested"
    assert resolved.type == "trial.preview_resolved"
    assert resolved.payload["status"] == "disconnect"
    assert holder["responses"][0][1] is False


def test_trial_preview_subscriber_overflow_fails_closed() -> None:
    install_blinker_event_adapter()
    holder: dict[str, object] = {}
    slow = event_queue._subscribe(last_seen_sequence=None, event_session_id=None)
    worker = threading.Thread(target=_emit_preview, args=(holder,))
    worker.start()

    requested = event_queue.queue.get(timeout=1)
    assert requested.type == "trial.preview_requested"
    for index in range(120):
        event_queue.publish_nowait(
            "settings.changed", {"reason": "settings_invalidate", "keys": [str(index)]}
        )

    worker.join(timeout=2)
    terminal = None
    for _ in range(140):
        event = event_queue.queue.get(timeout=1)
        if event.type == "trial.preview_resolved":
            terminal = event
            break

    assert slow.close_after_next_event is True
    assert terminal is not None
    assert terminal.payload["status"] == "overflow"
    assert holder["responses"][0][1] is False


def test_trial_preview_shutdown_fails_closed() -> None:
    install_blinker_event_adapter()
    holder: dict[str, object] = {}
    worker = threading.Thread(target=_emit_preview, args=(holder,))
    worker.start()

    requested = event_queue.queue.get(timeout=1)
    assert requested.type == "trial.preview_requested"
    event_queue.shutdown()
    worker.join(timeout=2)
    resolved = event_queue.queue.get(timeout=1)

    assert resolved.type == "trial.preview_resolved"
    assert resolved.payload["status"] == "shutdown"
    assert holder["responses"][0][1] is False


def test_trial_preview_duplicate_or_conflicting_decisions_do_not_change_result(
    desktop_api_client,
) -> None:
    install_blinker_event_adapter()
    holder: dict[str, object] = {}
    worker = threading.Thread(target=_emit_preview, args=(holder,))
    worker.start()
    event = event_queue.queue.get(timeout=1)
    request_id = str(event.payload["requestId"])

    first = desktop_api_client.post(
        f"/api/teaching/trial-preview/{request_id}/decision",
        json={"decision": "approve"},
    )
    second = desktop_api_client.post(
        f"/api/teaching/trial-preview/{request_id}/decision",
        json={"decision": "deny"},
    )

    worker.join(timeout=2)
    assert first.json()["accepted"] is True
    assert second.json()["accepted"] is False
    assert second.json()["status"] == "conflict"
    assert holder["responses"][0][1] is True


def test_trial_preview_unsafe_preview_fails_closed_without_public_event() -> None:
    install_blinker_event_adapter()

    responses = emit_collect(
        "desktop_trial_preview_ready",
        sender=None,
        workflow_id="rec_preview",
        trial_id="trial_unsafe",
        code_preview="MEXEMPLAR_DESKTOP_TOKEN=secret",
        timeout_seconds=0.05,
    )

    assert responses[0][1] is False
    try:
        event_queue.queue.get_nowait()
    except queue.Empty:
        pass
    else:
        raise AssertionError("unsafe preview request must not publish a public UI event")
