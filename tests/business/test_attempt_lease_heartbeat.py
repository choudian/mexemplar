"""A running executor must keep its lease, and only while it is running.

The lease was written once and never renewed, so recovery fenced anything that
outlived it and dispatched a replacement — while the original executor was still
working. Against a two-minute lease, one external coding session produced a new
attempt (and a new CLI process) every two minutes for an hour and a half.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from src.utils.timezone import utc_now_naive

from src.business.task_collaboration.attempt_heartbeat import AttemptHeartbeat


class _Recorder:
    """Stands in for the repository's conditional UPDATE."""

    def __init__(self, *, accept: bool = True):
        self.calls: list[tuple[str, datetime]] = []
        self._accept = accept
        self._seen = threading.Event()

    def __call__(self, attempt_id: str, *, lease_expires_at: datetime) -> bool:
        self.calls.append((attempt_id, lease_expires_at))
        self._seen.set()
        return self._accept

    def wait_for_first(self, timeout: float = 3.0) -> bool:
        return self._seen.wait(timeout)


def _heartbeat(renew, lease_seconds: int = 3) -> AttemptHeartbeat:
    return AttemptHeartbeat("att_test", lease_seconds=lease_seconds, renew=renew)


def test_renewal_interval_leaves_room_for_a_missed_tick():
    # Renewing at the last moment means one slow renewal loses the lease.
    beat = _heartbeat(lambda *_a, **_k: True, lease_seconds=120)

    assert beat.interval_seconds < 120
    assert beat.interval_seconds <= 60


def test_interval_never_degenerates_to_a_busy_loop():
    beat = _heartbeat(lambda *_a, **_k: True, lease_seconds=1)

    assert beat.interval_seconds >= 1.0


def test_lease_is_pushed_forward_while_the_executor_runs():
    recorder = _Recorder()
    beat = _heartbeat(recorder, lease_seconds=3)

    beat.start()
    try:
        assert recorder.wait_for_first(), "heartbeat never renewed"
    finally:
        beat.stop()

    attempt_id, expires_at = recorder.calls[0]
    assert attempt_id == "att_test"
    # The new expiry must be in the future, or renewing achieves nothing.
    assert expires_at > utc_now_naive() + timedelta(seconds=1)


def test_renewal_stops_as_soon_as_the_executor_finishes():
    # A lease outliving its executor is exactly what recovery exists to catch.
    recorder = _Recorder()
    beat = _heartbeat(recorder, lease_seconds=3)

    beat.start()
    recorder.wait_for_first()
    beat.stop()

    seen = len(recorder.calls)
    time.sleep(1.5)
    assert len(recorder.calls) == seen


def test_context_manager_stops_even_when_the_executor_raises():
    recorder = _Recorder()
    beat = _heartbeat(recorder, lease_seconds=3)

    try:
        with beat:
            recorder.wait_for_first()
            raise RuntimeError("executor blew up")
    except RuntimeError:
        pass

    seen = len(recorder.calls)
    time.sleep(1.5)
    assert len(recorder.calls) == seen


def test_a_declined_renewal_ends_the_heartbeat():
    # Declined means the attempt is no longer active — fenced or finished
    # elsewhere. Continuing would fight recovery for ownership.
    recorder = _Recorder(accept=False)
    beat = _heartbeat(recorder, lease_seconds=3)

    beat.start()
    try:
        assert recorder.wait_for_first()
        time.sleep(1.5)
        assert len(recorder.calls) == 1
    finally:
        beat.stop()


def test_a_failing_renewal_does_not_take_down_the_executor_thread():
    calls: list[int] = []

    def _explode(_attempt_id, *, lease_expires_at):
        calls.append(1)
        raise RuntimeError("database unavailable")

    beat = _heartbeat(_explode, lease_seconds=3)
    beat.start()
    try:
        # Keeps retrying; if every attempt fails the lease simply expires and
        # recovery takes over, which is correct for an executor we cannot vouch for.
        time.sleep(2.5)
        assert len(calls) >= 1
    finally:
        beat.stop()


def test_stop_is_safe_without_a_start():
    beat = _heartbeat(_Recorder())

    beat.stop()  # must not raise


def test_double_start_does_not_spawn_a_second_thread():
    recorder = _Recorder()
    beat = _heartbeat(recorder, lease_seconds=3)

    beat.start()
    first = beat._thread
    beat.start()
    try:
        assert beat._thread is first
    finally:
        beat.stop()
