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

from src.execution.command_runner import parse_command_argv
from src.utils.agent_tool_health import record_process_cleanup

logger = logging.getLogger(__name__)


class ProcessLimitExceeded(RuntimeError):
    pass


class ProcessOperationError(RuntimeError):
    pass


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
    _duplicate_key: tuple[str, str, str] | None = field(default=None, repr=False)

    @property
    def duplicate_key(self) -> tuple[str, str, str]:
        if self._duplicate_key is None:
            object.__setattr__(
                self, "_duplicate_key",
                (self.session_id, str(self.cwd.resolve()), " ".join(self.command.split())),
            )
        return self._duplicate_key


class ProcessManager:
    def __init__(self) -> None:
        self._records: dict[str, ProcessRecord] = {}
        self._lock = threading.RLock()

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
        argv = parse_command_argv(command)
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
            record = ProcessRecord(
                process_id=f"proc_{uuid.uuid4().hex}",
                session_id=session_id,
                command=command,
                command_summary=command_summary,
                cwd=cwd_path,
                cwd_display=cwd_display,
                process=proc,
                allow_stdin=allow_stdin,
            )
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

        def reader() -> None:
            if stream is None:
                return
            try:
                for line in stream:
                    with self._lock:
                        chunks.append(line)
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
