"""022 process-event-push: ProcessManager 事件机制单元测试.

覆盖任务 T006 / T008 / T009 / T015 / T018 / T019 / T021。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path


from src.execution.process_manager import ProcessManager, ProcessRecord


def _start(
    pm: ProcessManager,
    *,
    tmp_path: Path,
    name: str,
    code: str,
    session_id: str = "test-022",
) -> ProcessRecord:
    script = tmp_path / name
    script.write_text(code, encoding="utf-8")
    cmd = f'"{sys.executable}" "{script.name}"'
    record, _dup = pm.start(
        session_id=session_id,
        command=cmd,
        cwd=str(tmp_path),
        cwd_display=str(tmp_path),
        command_summary=name,
    )
    return record


def _wait_until_done(record: ProcessRecord, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if record.process.poll() is not None:
            return
        time.sleep(0.02)
    raise TimeoutError(f"process {record.process_id} did not exit within {timeout}s")


# ===== T006 / T021 ===== _emit_event_locked + ring buffer =====


def test_emit_event_locked_assigns_monotonic_sequence(tmp_path):
    pm = ProcessManager()
    record = _start(pm, tmp_path=tmp_path, name="quick.py", code="pass\n")
    _wait_until_done(record)
    with pm._lock:
        pm._emit_event_locked(record, "log_chunked", {"totalChars": 1, "deltaChars": 1})
        pm._emit_event_locked(record, "log_chunked", {"totalChars": 2, "deltaChars": 1})
        pm._emit_event_locked(record, "log_chunked", {"totalChars": 3, "deltaChars": 1})
    sequences = [e.sequence for e in record.events]
    assert sequences == sorted(sequences)
    assert sequences[0] < sequences[-1]


def test_emit_event_locked_ring_buffer_overwrites_oldest(tmp_path):
    pm = ProcessManager()
    record = _start(pm, tmp_path=tmp_path, name="quick2.py", code="pass\n")
    _wait_until_done(record)
    # Shrink the deque to a small fixed capacity for deterministic overwrite.
    from collections import deque

    record.events = deque(record.events, maxlen=3)
    with pm._lock:
        for i in range(10):
            pm._emit_event_locked(record, "log_chunked", {"totalChars": i, "deltaChars": 1})
    assert len(record.events) == 3
    sequences = [e.sequence for e in record.events]
    # event_sequence keeps going monotonically even when old events get overwritten.
    assert record.event_sequence >= 10
    assert sequences[-1] == record.event_sequence
    assert sequences == sorted(sequences)


def test_wait_returns_cursor_too_old_when_old_sincecursor_used(tmp_path):
    pm = ProcessManager()
    record = _start(pm, tmp_path=tmp_path, name="quick3.py", code="pass\n")
    _wait_until_done(record)
    from collections import deque

    record.events = deque(maxlen=3)
    with pm._lock:
        for _ in range(8):
            pm._emit_event_locked(record, "log_chunked", {"totalChars": 1, "deltaChars": 1})
    # Now the oldest sequence in deque is 6; sinceCursor=1 is far below it.
    result = pm.wait_for_event(record.process_id, since_cursor=1, timeout_ms=500)
    assert result["cursorTooOld"] is True
    assert "cursor" in result and result["cursor"] >= record.events[-1].sequence
    # Subsequent wait with the returned cursor must not flag cursorTooOld again
    # when no new events were appended.
    next_cursor = result["cursor"]
    result2 = pm.wait_for_event(record.process_id, since_cursor=next_cursor, timeout_ms=300)
    assert result2["cursorTooOld"] is False


def test_empty_deque_cursor_equals_event_sequence(tmp_path):
    pm = ProcessManager()
    record = _start(pm, tmp_path=tmp_path, name="quick4.py", code="pass\n")
    _wait_until_done(record)
    # Manually drain the deque by consuming via wait then clearing.
    with pm._lock:
        pm._emit_event_locked(record, "log_chunked", {"totalChars": 1, "deltaChars": 1})
    first = pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=500)
    cursor_after_consume = first["cursor"]
    # Drain manually (simulate post-consume state); deque still has events from
    # last_chunk but wait returns events filtered > cursor so empty.
    second = pm.wait_for_event(record.process_id, since_cursor=cursor_after_consume, timeout_ms=300)
    assert second["events"] == []
    # cursor on empty-return must equal latest sequence (== event_sequence here).
    assert second["cursor"] == record.event_sequence


# ===== T008 ===== state_changed on running -> terminal =====


def test_state_changed_emitted_on_running_to_completed(tmp_path):
    pm = ProcessManager()
    record = _start(pm, tmp_path=tmp_path, name="ok.py", code="import sys; sys.exit(0)\n")
    result = pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=5000)
    types = [e["type"] for e in result["events"]]
    assert "state_changed" in types
    sc = [e for e in result["events"] if e["type"] == "state_changed"][-1]
    assert sc["status"] == "completed"
    assert sc["exitCode"] == 0
    assert result["status"] == "completed"
    assert result["exitCode"] == 0


def test_state_changed_emitted_on_running_to_failed(tmp_path):
    pm = ProcessManager()
    record = _start(pm, tmp_path=tmp_path, name="bad.py", code="import sys; sys.exit(1)\n")
    result = pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=5000)
    sc = [e for e in result["events"] if e["type"] == "state_changed"][-1]
    assert sc["status"] == "failed"
    assert sc["exitCode"] == 1
    assert result["status"] == "failed"


# ===== T009 ===== wait blocking / wakeup / timeout =====


def test_wait_returns_immediately_when_event_already_in_deque(tmp_path):
    pm = ProcessManager()
    record = _start(pm, tmp_path=tmp_path, name="quick5.py", code="import sys; sys.exit(0)\n")
    _wait_until_done(record)
    # First wait collects state_changed.
    first = pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=2000)
    assert any(e["type"] == "state_changed" for e in first["events"])


def test_wait_blocks_until_timeout_when_no_event(tmp_path):
    pm = ProcessManager()
    record = _start(
        pm,
        tmp_path=tmp_path,
        name="long.py",
        code="import time; time.sleep(3)\n",
    )
    try:
        t0 = time.time()
        result = pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=300)
        elapsed = time.time() - t0
        assert result["events"] == []
        assert result["status"] == "running"
        # Should have waited approximately the timeout (allow generous bounds).
        assert 0.25 <= elapsed <= 1.5, f"elapsed={elapsed}"
    finally:
        pm.stop(record.process_id, force=True)


def test_wait_wakes_up_on_new_event_within_200ms(tmp_path):
    """SC-001: wait wakes up < 200 ms after a state change is emitted."""
    pm = ProcessManager()
    record = _start(
        pm,
        tmp_path=tmp_path,
        name="trigger.py",
        code="import time; time.sleep(3)\n",
    )

    wake_ts = []
    fire_ts = []

    def wait_call() -> None:
        wake_ts.append(time.time())
        result = pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=5000)
        wake_ts.append(time.time())
        wake_ts.append(result)

    thread = threading.Thread(target=wait_call, daemon=True)
    thread.start()
    time.sleep(0.1)  # ensure wait is parked
    # Trigger a manual state_changed emit to simulate process completion latency.
    with pm._lock:
        record.status = "completed"
        record.exit_code = 0
        pm._emit_event_locked(record, "state_changed", {"status": "completed", "exitCode": 0})
    fire_ts.append(time.time())
    thread.join(timeout=2.0)
    pm.stop(record.process_id, force=True)
    assert not thread.is_alive()
    # wake_ts is [start_ts, end_ts, result_dict]
    elapsed_ms = (wake_ts[1] - fire_ts[0]) * 1000
    assert elapsed_ms < 200, f"wake delay {elapsed_ms}ms exceeded 200ms"
    result = wake_ts[2]
    assert any(e["type"] == "state_changed" for e in result["events"])


# ===== T015 ===== log_chunked threshold =====


def test_log_chunked_emitted_when_threshold_exceeded(tmp_path, monkeypatch):
    pm = ProcessManager()
    # Force a small chunk threshold so the test is fast and deterministic.
    monkeypatch.setattr(
        pm,
        "_load_event_config",
        lambda: (64, 10000, 100),
    )
    record = _start(
        pm,
        tmp_path=tmp_path,
        name="loud.py",
        code=(
            "import sys, time\n"
            "for _ in range(20):\n"
            "    sys.stdout.write('x'*50)\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(0.01)\n"
            "time.sleep(0.3)\n"
        ),
    )
    try:
        result = pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=3000)
        chunked = [e for e in result["events"] if e["type"] == "log_chunked"]
        assert chunked, f"expected at least one log_chunked, got: {result['events']}"
        first = chunked[0]
        assert first["totalChars"] >= 100
        assert first["deltaChars"] >= 100
    finally:
        pm.stop(record.process_id, force=True)


def test_log_chunked_baseline_resets_after_emit(tmp_path, monkeypatch):
    pm = ProcessManager()
    monkeypatch.setattr(pm, "_load_event_config", lambda: (64, 10000, 100))
    # Use newline-terminated chunks so the reader sees discrete lines.
    record = _start(
        pm,
        tmp_path=tmp_path,
        name="loud2.py",
        code=(
            "import sys, time\n"
            "for _ in range(40):\n"
            "    sys.stdout.write('y'*150 + '\\n')\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(0.005)\n"
            "time.sleep(0.3)\n"
        ),
    )
    try:
        first = pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=3000)
        chunked1 = [e for e in first["events"] if e["type"] == "log_chunked"]
        assert chunked1, f"first wait should see log_chunked, got: {first['events']}"
        first_event = chunked1[0]
        assert first_event["deltaChars"] >= 100
        assert first_event["deltaChars"] < 1000  # not the cumulative total

        # Continue waiting with the returned cursor; baseline must reset so the
        # NEXT chunk past threshold triggers a new event.
        cursor = first["cursor"]
        second = pm.wait_for_event(record.process_id, since_cursor=cursor, timeout_ms=3000)
        chunked2 = [e for e in second["events"] if e["type"] == "log_chunked"]
        assert chunked2, f"second wait should see another log_chunked, got: {second['events']}"
        second_event = chunked2[0]
        assert second_event["deltaChars"] >= 100
        # Running total must keep growing across emits.
        assert second_event["totalChars"] > first_event["totalChars"]
    finally:
        pm.stop(record.process_id, force=True)


def test_log_chunked_does_not_carry_payload(tmp_path, monkeypatch):
    pm = ProcessManager()
    monkeypatch.setattr(pm, "_load_event_config", lambda: (64, 10000, 100))
    record = _start(
        pm,
        tmp_path=tmp_path,
        name="loud3.py",
        code=(
            "import sys, time\n"
            "for _ in range(20):\n"
            "    sys.stdout.write('SECRET-LOG-LINE-' + str(_) + '\\n')\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(0.01)\n"
            "time.sleep(0.3)\n"
        ),
    )
    try:
        result = pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=3000)
        chunked = [e for e in result["events"] if e["type"] == "log_chunked"]
        assert chunked
        for c in chunked:
            allowed_keys = {"sequence", "type", "totalChars", "deltaChars"}
            assert set(c.keys()) <= allowed_keys, f"unexpected keys: {set(c.keys())}"
            for v in c.values():
                assert "SECRET" not in str(v)
    finally:
        pm.stop(record.process_id, force=True)


# ===== T018 / T019 ===== stalled lazy / not-repeated / never-output =====


def test_stalled_emitted_when_idle_exceeds_threshold(tmp_path, monkeypatch):
    pm = ProcessManager()
    # 100 ms stalled threshold => fast test.
    monkeypatch.setattr(pm, "_load_event_config", lambda: (64, 100, 4096))
    record = _start(
        pm,
        tmp_path=tmp_path,
        name="quiet.py",
        code="import time; time.sleep(2)\n",
    )
    try:
        time.sleep(0.3)  # exceed stalled threshold
        result = pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=300)
        stalled = [e for e in result["events"] if e["type"] == "stalled"]
        assert stalled, f"expected stalled, got: {result['events']}"
        assert stalled[0]["idleMs"] >= 100
    finally:
        pm.stop(record.process_id, force=True)


def test_stalled_not_repeated_within_same_silence_window(tmp_path, monkeypatch):
    pm = ProcessManager()
    monkeypatch.setattr(pm, "_load_event_config", lambda: (64, 100, 4096))
    record = _start(
        pm,
        tmp_path=tmp_path,
        name="quiet2.py",
        code="import time; time.sleep(2)\n",
    )
    try:
        time.sleep(0.3)
        first = pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=300)
        first_stalled = [e for e in first["events"] if e["type"] == "stalled"]
        assert first_stalled
        cursor = first["cursor"]
        # Immediately wait again — without new output, no second stalled.
        second = pm.wait_for_event(record.process_id, since_cursor=cursor, timeout_ms=300)
        second_stalled = [e for e in second["events"] if e["type"] == "stalled"]
        assert not second_stalled
    finally:
        pm.stop(record.process_id, force=True)


def test_stalled_emitted_for_process_that_never_outputs(tmp_path, monkeypatch):
    pm = ProcessManager()
    monkeypatch.setattr(pm, "_load_event_config", lambda: (64, 100, 4096))
    record = _start(
        pm,
        tmp_path=tmp_path,
        name="silent.py",
        code="import time; time.sleep(2)\n",
    )
    try:
        time.sleep(0.3)
        # never any chunk; last_output_at was initialised to started_at.
        result = pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=300)
        stalled = [e for e in result["events"] if e["type"] == "stalled"]
        assert stalled, "stalled should fire even for processes that never wrote"
    finally:
        pm.stop(record.process_id, force=True)


def test_stalled_only_when_running(tmp_path, monkeypatch):
    pm = ProcessManager()
    monkeypatch.setattr(pm, "_load_event_config", lambda: (64, 50, 4096))
    record = _start(pm, tmp_path=tmp_path, name="end.py", code="import sys; sys.exit(0)\n")
    _wait_until_done(record)
    # Process is no longer running; stalled judgement must skip.
    time.sleep(0.1)
    result = pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=300)
    stalled = [e for e in result["events"] if e["type"] == "stalled"]
    assert not stalled


def test_cleanup_session_stops_only_owned_background_processes(tmp_path):
    pm = ProcessManager()
    owned = _start(
        pm,
        tmp_path=tmp_path,
        name="owned.py",
        code="import time; time.sleep(30)\n",
        session_id="executor-a",
    )
    other = _start(
        pm,
        tmp_path=tmp_path,
        name="other.py",
        code="import time; time.sleep(30)\n",
        session_id="executor-b",
    )
    try:
        result = pm.cleanup_session("executor-a")

        assert result == {"stopped": 1, "failures": 0}
        assert pm.poll(owned.process_id)["status"] == "terminated"
        assert pm.poll(other.process_id)["status"] == "running"
    finally:
        pm.stop(other.process_id, force=True)
