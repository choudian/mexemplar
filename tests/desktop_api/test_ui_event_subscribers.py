from __future__ import annotations

from src.desktop_api.events import event_queue


def setup_function() -> None:
    event_queue.reset_for_tests()


def test_two_subscribers_receive_same_event_without_stealing() -> None:
    sub_a = event_queue._subscribe(last_seen_sequence=None, event_session_id=None)
    sub_b = event_queue._subscribe(last_seen_sequence=None, event_session_id=None)

    for index in range(20):
        event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": [str(index)]})

    events_a = [sub_a.queue.get_nowait() for _ in range(20)]
    events_b = [sub_b.queue.get_nowait() for _ in range(20)]
    assert [event.sequence for event in events_a] == [event.sequence for event in events_b]
    assert all(event.type == "settings.changed" for event in events_a)


def test_slow_subscriber_overflow_gets_resync_without_blocking_healthy_subscriber() -> None:
    slow = event_queue._subscribe(last_seen_sequence=None, event_session_id=None)
    healthy = event_queue._subscribe(last_seen_sequence=None, event_session_id=None)
    healthy_events = []

    for index in range(105):
        event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": [str(index)]})
        while not healthy.queue.empty():
            healthy_events.append(healthy.queue.get_nowait())

    assert slow.queue.get_nowait().type == "backend.resync_required"
    assert len(healthy_events) == 105
    assert all(event.type == "settings.changed" for event in healthy_events)
    assert healthy_events[-1].payload["keys"] == ["104"]


def test_private_resync_does_not_create_replay_gap_for_healthy_subscriber() -> None:
    slow = event_queue._subscribe(last_seen_sequence=None, event_session_id=None)
    healthy = event_queue._subscribe(last_seen_sequence=None, event_session_id=None)

    for index in range(101):
        event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": [str(index)]})
    last_seen = healthy.queue.get_nowait()
    while not healthy.queue.empty():
        last_seen = healthy.queue.get_nowait()
    assert slow.queue.get_nowait().type == "backend.resync_required"

    next_event = event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": ["next"]})
    reconnect = event_queue._subscribe(
        last_seen_sequence=last_seen.sequence,
        event_session_id=last_seen.sessionId,
    )

    replayed = reconnect.queue.get_nowait()
    assert replayed.type == "settings.changed"
    assert replayed.sequence == next_event.sequence
    assert replayed.payload["keys"] == ["next"]


def test_reconnect_replays_buffered_same_session_events() -> None:
    first = event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": ["a"]})
    second = event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": ["b"]})

    sub = event_queue._subscribe(last_seen_sequence=first.sequence, event_session_id=first.sessionId)

    replayed = sub.queue.get_nowait()
    assert replayed.sequence == second.sequence
    assert replayed.payload["keys"] == ["b"]


def test_reconnect_gap_requests_resync() -> None:
    first = event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": ["first"]})
    for index in range(300):
        event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": [str(index)]})

    sub = event_queue._subscribe(last_seen_sequence=first.sequence, event_session_id=first.sessionId)

    event = sub.queue.get_nowait()
    assert event.type == "backend.resync_required"
    assert event.payload["reason"] == "replay_gap"


def test_reconnect_replay_larger_than_subscriber_queue_requests_resync() -> None:
    first = event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": ["first"]})
    for index in range(150):
        event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": [str(index)]})

    sub = event_queue._subscribe(last_seen_sequence=first.sequence, event_session_id=first.sessionId)

    event = sub.queue.get_nowait()
    assert event.type == "backend.resync_required"
    assert event.payload["reason"] == "replay_overflow"


def test_reconnect_without_event_session_requests_resync() -> None:
    first = event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": ["first"]})

    sub = event_queue._subscribe(last_seen_sequence=first.sequence, event_session_id=None)

    event = sub.queue.get_nowait()
    assert event.type == "backend.resync_required"
    assert event.payload["reason"] == "invalid_cursor"


def test_resync_control_events_have_unique_sequence_without_replay_gap() -> None:
    first = event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": ["first"]})

    invalid_cursor = event_queue._subscribe(last_seen_sequence=first.sequence, event_session_id=None)
    resync = invalid_cursor.queue.get_nowait()
    assert resync.type == "backend.resync_required"
    assert resync.sequence > first.sequence

    second = event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": ["second"]})
    assert second.sequence > resync.sequence

    reconnect = event_queue._subscribe(last_seen_sequence=first.sequence, event_session_id=first.sessionId)
    replayed = reconnect.queue.get_nowait()
    assert replayed.type == "settings.changed"
    assert replayed.sequence == second.sequence
