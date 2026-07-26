"""Current-process background command registry for Agent built-ins."""

from __future__ import annotations

import atexit
import logging
import os
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.execution.shell_resolver import resolve_shell, shell_argv
from src.utils.agent_tool_health import record_process_cleanup

logger = logging.getLogger(__name__)


class ProcessLimitExceeded(RuntimeError):
    pass


class ProcessOperationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessEvent:
    """A coarse-grained signal about a background process.

    Three types: state_changed / stalled / log_chunked. Payload never carries
    stdout/stderr content; use process_logs to read the real output.
    """

    sequence: int
    type: str
    payload: dict[str, Any]


@dataclass
class ProcessRecord:
    process_id: str
    session_id: str
    command: str
    command_summary: str
    cwd: Path
    cwd_display: str
    process: subprocess.Popen
    allow_stdin: bool = False
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    exit_code: int | None = None
    stdout_chunks: deque[str] = field(default_factory=lambda: deque(maxlen=512))
    stderr_chunks: deque[str] = field(default_factory=lambda: deque(maxlen=512))
    closed: bool = False
    # Event push (022 process-event-push). Fields are initialised after construction
    # by ProcessManager.start; defaults here keep dataclass instantiation safe.
    events: deque = field(default_factory=lambda: deque(maxlen=64))
    event_sequence: int = 0
    event_condition: threading.Condition | None = None
    last_output_at: float = field(default_factory=time.time)
    last_chunk_announce: int = 0
    total_output_chars: int = 0
    last_stalled_announce_output_at: float | None = None
    _chunk_threshold_chars: int = 4096
    _duplicate_key: tuple[str, str, str] | None = field(default=None, repr=False)

    @property
    def duplicate_key(self) -> tuple[str, str, str]:
        if self._duplicate_key is None:
            object.__setattr__(
                self,
                "_duplicate_key",
                (self.session_id, str(self.cwd.resolve()), " ".join(self.command.split())),
            )
        return self._duplicate_key


class ProcessManager:
    def __init__(self) -> None:
        self._records: dict[str, ProcessRecord] = {}
        self._lock = threading.RLock()

    def _load_event_config(self) -> tuple[int, int, int]:
        """Read 022 event config; isolated for monkeypatch friendliness."""
        from src.data.unified_config import get_unified_config

        cfg = get_unified_config()
        return (
            cfg.get_agent_tools_process_event_buffer_size(),
            cfg.get_agent_tools_process_stalled_threshold_ms(),
            cfg.get_agent_tools_process_chunk_threshold_chars(),
        )

    def start(
        self,
        *,
        session_id: str,
        command: str,
        cwd: str | Path,
        cwd_display: str,
        command_summary: str,
        allow_stdin: bool = False,
        max_processes: int = 16,
    ) -> tuple[ProcessRecord, bool]:
        cwd_path = Path(cwd).resolve()
        normalized = (session_id, str(cwd_path), " ".join(command.split()))
        argv = shell_argv(resolve_shell(), command)
        with self._lock:
            running_count = 0
            for record in self._records.values():
                self._refresh_locked(record)
                if record.duplicate_key == normalized and record.status == "running":
                    return record, True
                if record.session_id == session_id and record.status == "running":
                    running_count += 1
            if running_count >= max(1, int(max_processes)):
                raise ProcessLimitExceeded(
                    f"Background process limit reached for session ({running_count})."
                )
            popen_kwargs: dict[str, Any] = {}
            if os.name == "nt":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                popen_kwargs["start_new_session"] = True
            proc = subprocess.Popen(
                argv,
                shell=False,
                cwd=str(cwd_path),
                stdin=subprocess.PIPE if allow_stdin else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **popen_kwargs,
            )
            try:
                buffer_size, _stalled_ms, chunk_threshold = self._load_event_config()
            except Exception:
                # Config layer not initialised in some edge-case test contexts;
                # fall back to dataclass defaults rather than crash start().
                buffer_size, chunk_threshold = 64, 4096
            record = ProcessRecord(
                process_id=f"proc_{uuid.uuid4().hex}",
                session_id=session_id,
                command=command,
                command_summary=command_summary,
                cwd=cwd_path,
                cwd_display=cwd_display,
                process=proc,
                allow_stdin=allow_stdin,
                events=deque(maxlen=max(1, int(buffer_size))),
            )
            # 022: bind event condition to the manager's lock so wait/emit share it.
            record.event_condition = threading.Condition(self._lock)
            record.last_output_at = record.started_at
            record._chunk_threshold_chars = max(1, int(chunk_threshold))
            self._records[record.process_id] = record
            self._start_reader(record, "stdout")
            self._start_reader(record, "stderr")
            return record, False

    def list(
        self, *, session_id: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._records.values())
            for record in records:
                self._refresh_locked(record)
            return [
                self._summary(record)
                for record in records
                if (session_id is None or record.session_id == session_id)
                and (status is None or record.status == status)
                and not record.closed
            ]

    def get(self, process_id: str) -> ProcessRecord | None:
        with self._lock:
            record = self._records.get(process_id)
            if record is not None:
                self._refresh_locked(record)
            return record

    def poll(self, process_id: str) -> dict[str, Any] | None:
        record = self.get(process_id)
        return self._summary(record) if record is not None else None

    def logs(
        self, process_id: str, *, stream: str = "combined", tail_chars: int = 4000
    ) -> str | None:
        record = self.get(process_id)
        if record is None:
            return None
        with self._lock:
            stdout = "".join(record.stdout_chunks)
            stderr = "".join(record.stderr_chunks)
        if stream == "stdout":
            text = stdout
        elif stream == "stderr":
            text = stderr
        else:
            text = stdout + stderr
        return text[-max(1, tail_chars) :]

    def wait(self, process_id: str, *, timeout_ms: int) -> dict[str, Any] | None:
        record = self.get(process_id)
        if record is None:
            return None
        try:
            record.process.wait(timeout=max(0.001, timeout_ms / 1000))
        except subprocess.TimeoutExpired:
            pass
        with self._lock:
            self._refresh_locked(record)
            return self._summary(record)

    def stop(self, process_id: str, *, force: bool = False) -> dict[str, Any] | None:
        record = self.get(process_id)
        if record is None:
            return None
        was_running = record.status == "running"
        if record.status == "running":
            self._terminate_tree(record, force=force)
            try:
                record.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._terminate_tree(record, force=True)
                try:
                    record.process.wait(timeout=2)
                except subprocess.TimeoutExpired as exc:
                    raise ProcessOperationError("Process did not stop within the timeout.") from exc
        with self._lock:
            if was_running:
                record.exit_code = record.process.poll()
                record.finished_at = record.finished_at or time.time()
                record.status = "terminated"
                # 022: explicit terminate path emits state_changed too.
                self._emit_event_locked(
                    record,
                    "state_changed",
                    {"status": record.status, "exitCode": record.exit_code},
                )
            else:
                self._refresh_locked(record)
            return self._summary(record)

    def send_input(self, process_id: str, text: str) -> bool | None:
        record = self.get(process_id)
        if record is None:
            return None
        if not record.allow_stdin or record.process.stdin is None or record.status != "running":
            return False
        try:
            record.process.stdin.write(text)
            record.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise ProcessOperationError("Process stdin write failed.") from exc
        return True

    def close(self, process_id: str) -> dict[str, Any] | None:
        record = self.get(process_id)
        if record is None:
            return None
        if record.status == "running":
            return self._summary(record)
        with self._lock:
            record.closed = True
            record.status = "closed"
            return self._summary(record)

    def cleanup(self) -> dict[str, int]:
        with self._lock:
            records = list(self._records.values())
        stopped = 0
        failures = 0
        for record in records:
            if record.status == "running":
                try:
                    self.stop(record.process_id, force=True)
                    stopped += 1
                except Exception:
                    failures += 1
                    logger.warning(
                        "[agent_tools] background process cleanup failed: process_id=%s",
                        record.process_id,
                        exc_info=True,
                    )
        result = {"stopped": stopped, "failures": failures}
        record_process_cleanup(result)
        return result

    # ===== 022 process-event-push =====

    def _emit_event_locked(
        self, record: ProcessRecord, event_type: str, payload: dict[str, Any]
    ) -> None:
        """Append a ProcessEvent and notify any wait_for_event waiters.

        Caller MUST already hold self._lock.
        """
        record.event_sequence += 1
        event = ProcessEvent(
            sequence=record.event_sequence,
            type=event_type,
            payload=dict(payload),
        )
        record.events.append(event)
        if record.event_condition is not None:
            record.event_condition.notify_all()

    def wait_for_event(
        self,
        process_id: str,
        *,
        since_cursor: int | None,
        timeout_ms: int,
    ) -> dict[str, Any] | None:
        """Block until a new event arrives past since_cursor, or timeout.

        Returns None when the process is missing (caller maps to process_missing).
        Otherwise returns:
          {
            "events":       [event dicts, sequence > since_cursor, ascending],
            "cursor":       int (next sinceCursor; monotonically non-decreasing),
            "status":       str,
            "exitCode":     int | None,
            "cursorTooOld": bool,
          }
        """
        cursor = 0 if since_cursor is None else max(0, int(since_cursor))
        deadline = time.time() + max(0.0, timeout_ms / 1000)
        with self._lock:
            record = self._records.get(process_id)
            if record is None:
                return None
            stalled_ms = 0
            try:
                _bufsize, stalled_ms, _chunk = self._load_event_config()
            except Exception:
                stalled_ms = 10000
            while True:
                # First always refresh terminal status; this may emit state_changed.
                self._refresh_locked_with_emit(record)
                # Lazy stalled judgement before deque scan (T020).
                self._maybe_emit_stalled_locked(record, stalled_ms)
                # Filter deque against cursor.
                events_after = [e for e in record.events if e.sequence > cursor]
                oldest_seq = record.events[0].sequence if record.events else None
                cursor_too_old = oldest_seq is not None and cursor > 0 and cursor < oldest_seq - 1
                # If we have anything to return (events or terminal status), return.
                if events_after:
                    new_cursor = events_after[-1].sequence
                    return self._build_wait_result(record, events_after, new_cursor, cursor_too_old)
                if record.status != "running":
                    # Process already done: don't block.
                    new_cursor = self._compute_cursor(record)
                    return self._build_wait_result(record, [], new_cursor, cursor_too_old)
                if cursor_too_old:
                    new_cursor = self._compute_cursor(record)
                    return self._build_wait_result(record, [], new_cursor, True)
                # Wait on condition until timeout.
                remaining = deadline - time.time()
                if remaining <= 0:
                    new_cursor = self._compute_cursor(record)
                    return self._build_wait_result(record, [], new_cursor, False)
                if record.event_condition is None:
                    # Defensive: fall through to timeout if not initialised.
                    new_cursor = self._compute_cursor(record)
                    return self._build_wait_result(record, [], new_cursor, False)
                record.event_condition.wait(timeout=remaining)
                # Loop and re-evaluate.

    def _refresh_locked_with_emit(self, record: ProcessRecord) -> None:
        """Like _refresh_locked but emits state_changed on terminal transition.

        Caller MUST already hold self._lock.
        """
        prev_status = record.status
        self._refresh_locked(record)
        if prev_status == "running" and record.status in {"completed", "failed"}:
            self._emit_event_locked(
                record,
                "state_changed",
                {"status": record.status, "exitCode": record.exit_code},
            )

    def _maybe_emit_stalled_locked(self, record: ProcessRecord, stalled_ms: int) -> None:
        """Lazy stalled judgement; called from wait_for_event entry.

        Caller MUST already hold self._lock.
        """
        if record.status != "running":
            return
        if stalled_ms <= 0:
            return
        idle_ms = int((time.time() - record.last_output_at) * 1000)
        if idle_ms < stalled_ms:
            return
        if record.last_stalled_announce_output_at == record.last_output_at:
            return
        self._emit_event_locked(record, "stalled", {"idleMs": idle_ms})
        record.last_stalled_announce_output_at = record.last_output_at

    def _compute_cursor(self, record: ProcessRecord) -> int:
        """Cursor to return when there are no new events to deliver.

        - When deque has events: latest event's sequence
        - When deque is empty: record.event_sequence (i.e. 'no events newer than my watermark')
        """
        if record.events:
            return record.events[-1].sequence
        return record.event_sequence

    def _build_wait_result(
        self,
        record: ProcessRecord,
        events_after: list,
        cursor: int,
        cursor_too_old: bool,
    ) -> dict[str, Any]:
        return {
            "events": [{"sequence": e.sequence, "type": e.type, **e.payload} for e in events_after],
            "cursor": int(cursor),
            "status": record.status,
            "exitCode": record.exit_code,
            "cursorTooOld": bool(cursor_too_old),
        }

    # ===== end 022 =====

    def _terminate_tree(self, record: ProcessRecord, *, force: bool) -> bool:
        if os.name == "nt":
            cmd = ["taskkill", "/PID", str(record.process.pid), "/T"]
            if force:
                cmd.append("/F")
            try:
                completed = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
                if completed.returncode == 0:
                    return True
            except (OSError, subprocess.TimeoutExpired):
                pass
        else:
            try:
                sig = signal.SIGKILL if force else signal.SIGTERM
                os.killpg(os.getpgid(record.process.pid), sig)
                return True
            except OSError:
                pass
        try:
            if force:
                record.process.kill()
            else:
                record.process.terminate()
            return True
        except OSError:
            return False

    def _start_reader(self, record: ProcessRecord, stream_name: str) -> None:
        stream = getattr(record.process, stream_name)
        chunks = record.stdout_chunks if stream_name == "stdout" else record.stderr_chunks
        threshold = record._chunk_threshold_chars

        def reader() -> None:
            if stream is None:
                return
            try:
                for line in stream:
                    with self._lock:
                        chunks.append(line)
                        # 022: track output statistics for log_chunked / stalled.
                        record.total_output_chars += len(line)
                        record.last_output_at = time.time()
                        if record.total_output_chars - record.last_chunk_announce >= threshold:
                            delta = record.total_output_chars - record.last_chunk_announce
                            record.last_chunk_announce = record.total_output_chars
                            self._emit_event_locked(
                                record,
                                "log_chunked",
                                {
                                    "totalChars": record.total_output_chars,
                                    "deltaChars": delta,
                                },
                            )
            except (OSError, ValueError):
                return

        thread = threading.Thread(
            target=reader, name=f"agent-{stream_name}-{record.process_id}", daemon=True
        )
        thread.start()

    def _refresh_locked(self, record: ProcessRecord) -> None:
        if record.status in {"closed", "terminated"}:
            return
        code = record.process.poll()
        if code is None:
            record.status = "running"
            return
        record.exit_code = code
        record.finished_at = record.finished_at or time.time()
        record.status = "completed" if code == 0 else "failed"

    def _summary(self, record: ProcessRecord) -> dict[str, Any]:
        duration_ms = int(((record.finished_at or time.time()) - record.started_at) * 1000)
        return {
            "processId": record.process_id,
            "status": record.status,
            "exitCode": record.exit_code,
            "commandSummary": record.command_summary,
            "cwd": record.cwd_display,
            "durationMs": duration_ms,
            "startedAt": record.started_at,
            "finishedAt": record.finished_at,
        }


_PROCESS_MANAGER = ProcessManager()
atexit.register(_PROCESS_MANAGER.cleanup)


def get_process_manager() -> ProcessManager:
    return _PROCESS_MANAGER
