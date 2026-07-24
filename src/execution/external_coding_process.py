"""Execution-layer process runner for external coding CLI tools."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import psutil

from src.utils.sensitive_text import redact_sensitive_text

_SAFE_EXTERNAL_REF_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,200}$")
_ABSOLUTE_PATH_RE = re.compile(r"(?:^|[\s:\"'=])(?:@?[A-Za-z]:[\\/]|@?/|\\\\[^\\\s]+[\\/])")
_TERMINATION_UNCONFIRMED_MESSAGE = "external coding process tree termination is unconfirmed"
_TERMINAL_PROCESS_STATUSES = frozenset({"succeeded", "failed", "interrupted"})
_DANGEROUS_GIT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bgit(?:\.exe)?\b[^\r\n;&|]*\bpush\b"), "git push"),
    (
        re.compile(r"(?i)\bgit(?:\.exe)?\b[^\r\n;&|]*\breset\b[^\r\n;&|]*--hard\b"),
        "git reset --hard",
    ),
    (re.compile(r"(?i)\bgit(?:\.exe)?\b[^\r\n;&|]*\bclean\b"), "git clean"),
    (re.compile(r"(?i)\bgit(?:\.exe)?\b[^\r\n;&|]*\bmerge\b"), "git merge"),
    (re.compile(r"(?i)\bgit(?:\.exe)?\b[^\r\n;&|]*\brebase\b"), "git rebase"),
    (
        re.compile(r"(?i)\bgit(?:\.exe)?\b[^\r\n;&|]*\bbranch\b[^\r\n;&|]*\s-D\b"),
        "git branch -D",
    ),
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessIdentity:
    """PID plus creation time, the minimum restart-safe process identity."""

    pid: int
    create_time: float | None


@dataclass(frozen=True)
class ExternalProcessStart:
    identity: ProcessIdentity
    command_summary: str

    @property
    def pid(self) -> int:
        return self.identity.pid

    @property
    def process_create_time(self) -> float | None:
        return self.identity.create_time


class ExternalProcessStartError(RuntimeError):
    """Initialization failed after spawn and the process could not be stopped."""

    def __init__(self, *, identity: ProcessIdentity) -> None:
        super().__init__("spawned external coding process requires managed shutdown")
        self.identity = identity

    @property
    def pid(self) -> int:
        return self.identity.pid

    @property
    def process_create_time(self) -> float | None:
        return self.identity.create_time


class ExternalProcessTerminationOutcome(str, Enum):
    """Typed proof returned by process stop operations."""

    CONFIRMED_STOPPED = "confirmed_stopped"
    CONFIRMED_EXITED = "confirmed_exited"
    UNCONFIRMED = "unconfirmed"

    @property
    def confirmed(self) -> bool:
        return self in {self.CONFIRMED_STOPPED, self.CONFIRMED_EXITED}


@dataclass(frozen=True)
class ExternalProcessSnapshot:
    status: str
    pid: int | None = None
    process_create_time: float | None = None
    termination_unconfirmed: bool = False
    exit_code: int | None = None
    external_session_ref: str | None = None
    error_category: str | None = None
    error_message: str | None = None
    log_tail: str | None = None

    def __post_init__(self) -> None:
        if self.status == "running" and not self.termination_unconfirmed:
            raise ValueError("running process snapshots must retain unconfirmed ownership")
        if self.status in _TERMINAL_PROCESS_STATUSES and self.termination_unconfirmed:
            raise ValueError("terminal process snapshots cannot retain unconfirmed ownership")
        if self.process_create_time is not None and self.pid is None:
            raise ValueError("process snapshot creation time requires a PID")


@dataclass
class _ManagedProcess:
    process: subprocess.Popen[bytes]
    process_create_time: float | None
    interactive: bool
    log_path: Path
    status_path: Path
    timeout_seconds: int
    max_log_bytes: int
    stop_reason: str | None = None
    monitor: threading.Thread | None = None
    output_reader: threading.Thread | None = None
    output_reader_cancel: threading.Event | None = None
    recovery_terminal_payload: dict[str, Any] | None = None
    termination_unconfirmed: bool = False
    termination_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


@dataclass(frozen=True)
class _ProcessRegistryKey:
    """In-process ownership key that cannot collide on PID reuse."""

    identity: ProcessIdentity
    status_path: str
    instance_token: int


class _ProcessRegistryConflict(RuntimeError):
    """A stale owner already holds the PID allocated to a new process."""


@dataclass(frozen=True)
class _OutputReadFailure:
    """Safe cross-thread signal that stdout could not be read completely."""

    exception_type: str


class _BoundedLog:
    def __init__(self, path: Path, max_bytes: int) -> None:
        self._path = path
        self._max_bytes = max(1024, int(max_bytes))
        self._chunks: deque[bytes] = deque()
        self._size = 0

    def append(self, text: str) -> None:
        chunk = _redact_log_text(text).encode("utf-8", errors="replace")
        if len(chunk) > self._max_bytes:
            chunk = chunk[-self._max_bytes :]
        self._chunks.append(chunk)
        self._size += len(chunk)
        while self._size > self._max_bytes and self._chunks:
            overflow = self._size - self._max_bytes
            first = self._chunks[0]
            if len(first) <= overflow:
                self._size -= len(self._chunks.popleft())
            else:
                self._chunks[0] = first[overflow:]
                self._size -= overflow
        self.flush()

    def flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_bytes(b"".join(self._chunks))

    def text(self) -> str:
        return b"".join(self._chunks).decode("utf-8", errors="replace")


class ExternalCodingProcessRunner:
    """Run, monitor and stop external CLIs without business-layer knowledge."""

    _registry: dict[_ProcessRegistryKey, _ManagedProcess] = {}
    _registry_lock = threading.RLock()

    def start(
        self,
        *,
        command: list[str],
        cwd: Path,
        log_path: Path,
        timeout_seconds: int,
        max_log_bytes: int,
        interactive: bool = False,
    ) -> ExternalProcessStart:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("", encoding="utf-8")
        resolved_command = _resolve_executable(command)
        command_summary = safe_external_command_summary(command)
        bounded_timeout = max(1, int(timeout_seconds))
        bounded_log_bytes = max(1024, int(max_log_bytes))
        popen_kwargs: dict[str, Any] = {}
        if interactive and os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        process = subprocess.Popen(
            resolved_command,
            cwd=str(cwd),
            stdin=None if interactive else subprocess.DEVNULL,
            stdout=None if interactive else subprocess.PIPE,
            stderr=None if interactive else subprocess.STDOUT,
            text=False,
            bufsize=0,
            **popen_kwargs,
        )
        managed: _ManagedProcess | None = None
        try:
            managed = _ManagedProcess(
                process=process,
                process_create_time=_process_create_time(process.pid),
                interactive=interactive,
                log_path=log_path,
                status_path=_status_path(log_path),
                timeout_seconds=bounded_timeout,
                max_log_bytes=bounded_log_bytes,
            )
            if not self._register_managed(managed):
                raise _ProcessRegistryConflict(
                    "external coding process PID is already owned by another attempt"
                )
            _write_status(
                managed.status_path,
                _status_payload(
                    _managed_identity(managed),
                    status="running",
                    started_at=_utc_now(),
                ),
            )
            monitor = threading.Thread(
                target=self._run_monitor_guarded,
                args=(managed,),
                name=f"external-coding-{process.pid}",
                daemon=True,
            )
            monitor.start()
            managed.monitor = monitor
        except Exception as exc:
            stopped = (
                _terminate_managed_process(managed)
                if managed is not None
                else _terminate_process(process)
            )
            if not stopped:
                # Keep the process discoverable by poll/stop.  The adapter
                # returns its PID as a running attempt instead of losing
                # ownership of a process that survived compensation.
                if managed is not None:
                    self._retain_managed(managed)
                    try:
                        _write_termination_unconfirmed(managed)
                    except Exception as marker_exc:
                        logger.critical(
                            "external coding startup ownership marker failed (%s)",
                            type(marker_exc).__name__,
                        )
                raise ExternalProcessStartError(
                    identity=(
                        _managed_identity(managed)
                        if managed is not None
                        else ProcessIdentity(process.pid, None)
                    )
                ) from exc
            if managed is not None:
                self._remove_managed(managed)
            if managed is not None:
                try:
                    managed.status_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        if managed is None:
            raise RuntimeError("external coding process ownership was not initialized")
        return ExternalProcessStart(
            identity=_managed_identity(managed),
            command_summary=command_summary,
        )

    def poll(
        self,
        *,
        pid: int | None,
        log_path: Path,
        process_create_time: float | None = None,
        termination_unconfirmed: bool = False,
    ) -> ExternalProcessSnapshot:
        managed = None
        if pid:
            managed = self._lookup_managed(
                pid=int(pid),
                process_create_time=process_create_time,
                status_path=_status_path(log_path),
            )
        if managed is not None and managed.process.poll() is not None and managed.monitor:
            managed.monitor.join(timeout=0.2)

        if (
            managed is not None
            and managed.process.poll() is not None
            and managed.recovery_terminal_payload is not None
        ):
            recovery_payload = managed.recovery_terminal_payload
            try:
                _write_status(managed.status_path, recovery_payload)
            except Exception as exc:
                logger.warning(
                    "external coding recovered terminal status retry failed (%s)",
                    type(exc).__name__,
                )
                return _uncertain_process_snapshot(
                    identity=_managed_identity(managed),
                    fallback_pid=managed.process.pid,
                    fallback_create_time=managed.process_create_time,
                    payload=recovery_payload,
                    log_path=log_path,
                    message="external coding recovered terminal status could not be persisted",
                )
            self._remove_managed(managed)
            return _terminal_process_snapshot(
                payload=recovery_payload,
                managed=managed,
                requested_pid=pid,
                requested_create_time=process_create_time,
                termination_unconfirmed=termination_unconfirmed,
                identity=_managed_identity(managed),
                fallback_pid=managed.process.pid,
                fallback_create_time=managed.process_create_time,
                log_path=log_path,
            )

        payload = _read_status(_status_path(log_path))
        status = str(payload.get("status") or "failed") if payload is not None else None
        identity = _resolve_process_identity(
            pid=pid,
            process_create_time=process_create_time,
            payload=payload,
            managed=managed,
        )
        resolved_pid = identity.pid if identity is not None else pid
        resolved_create_time = identity.create_time if identity is not None else process_create_time

        if payload is not None and status in _TERMINAL_PROCESS_STATUSES:
            return _terminal_process_snapshot(
                payload=payload,
                managed=managed,
                requested_pid=pid,
                requested_create_time=process_create_time,
                termination_unconfirmed=termination_unconfirmed,
                identity=identity,
                fallback_pid=resolved_pid,
                fallback_create_time=resolved_create_time,
                log_path=log_path,
            )

        marker_unconfirmed = bool(
            (managed is not None and managed.termination_unconfirmed)
            or (payload is not None and payload.get("terminationUnconfirmed") is True)
        )
        if marker_unconfirmed:
            return _uncertain_process_snapshot(
                identity=identity,
                fallback_pid=resolved_pid,
                fallback_create_time=resolved_create_time,
                payload=payload,
                log_path=log_path,
                message=_TERMINATION_UNCONFIRMED_MESSAGE,
            )

        if managed is not None and managed.process.poll() is not None:
            monitor_alive = managed.monitor is not None and managed.monitor.is_alive()
            if monitor_alive:
                return ExternalProcessSnapshot(
                    status="running",
                    pid=managed.process.pid,
                    process_create_time=managed.process_create_time,
                    termination_unconfirmed=True,
                    external_session_ref=(
                        _safe_external_ref(payload.get("externalSessionRef")) if payload else None
                    ),
                    log_tail=_read_log_tail(log_path),
                )
            # The monitor can finish between the first status read and the
            # is_alive check. Re-read after observing its terminal state so a
            # just-committed timeout/stop result is not replaced by a fake
            # "exited before status" failure.
            latest_payload = _read_status(_status_path(log_path))
            if (
                latest_payload is not None
                and str(latest_payload.get("status")) in _TERMINAL_PROCESS_STATUSES
            ):
                return _terminal_process_snapshot(
                    payload=latest_payload,
                    managed=managed,
                    requested_pid=pid,
                    requested_create_time=process_create_time,
                    termination_unconfirmed=termination_unconfirmed,
                    identity=_managed_identity(managed),
                    fallback_pid=managed.process.pid,
                    fallback_create_time=managed.process_create_time,
                    log_path=log_path,
                )
            return ExternalProcessSnapshot(
                status="failed",
                pid=managed.process.pid,
                process_create_time=managed.process_create_time,
                termination_unconfirmed=False,
                error_category="process_error",
                error_message="external coding process exited before status was recorded",
                log_tail=_read_log_tail(log_path),
            )

        if identity is not None and _pid_matches_identity(identity):
            return ExternalProcessSnapshot(
                status="running",
                pid=identity.pid,
                process_create_time=identity.create_time,
                termination_unconfirmed=True,
                external_session_ref=(
                    _safe_external_ref(payload.get("externalSessionRef")) if payload else None
                ),
                log_tail=_read_log_tail(log_path),
            )

        if termination_unconfirmed:
            return _uncertain_process_snapshot(
                identity=identity,
                fallback_pid=resolved_pid,
                fallback_create_time=resolved_create_time,
                payload=payload,
                log_path=log_path,
                message="external coding process ownership could not be determined",
            )

        return ExternalProcessSnapshot(
            status="failed",
            pid=resolved_pid,
            process_create_time=resolved_create_time,
            termination_unconfirmed=False,
            error_category="process_error",
            error_message=(
                "external coding process ended without status metadata"
                if payload is None
                else "external coding process exited before status was recorded"
            ),
            log_tail=_read_log_tail(log_path),
        )

    def stop(
        self,
        *,
        pid: int | None,
        log_path: Path,
        reason: str,
        process_create_time: float | None = None,
        termination_unconfirmed: bool = False,
    ) -> ExternalProcessTerminationOutcome:
        payload = _read_status(_status_path(log_path))
        payload_pid = _safe_int(payload.get("pid")) if payload is not None else None
        pid = pid or payload_pid
        if not pid:
            return ExternalProcessTerminationOutcome.UNCONFIRMED
        managed = self._lookup_managed(
            pid=int(pid),
            process_create_time=process_create_time,
            status_path=_status_path(log_path),
        )
        if managed is not None:
            managed.stop_reason = _safe_string(reason, 120) or "stopped by Exemplar"
        if managed is not None:
            if managed.process.poll() is not None:
                if managed.monitor:
                    managed.monitor.join(timeout=2.0)
                payload = _read_status(managed.status_path)
                if (
                    not managed.termination_unconfirmed
                    and payload is not None
                    and str(payload.get("status")) in _TERMINAL_PROCESS_STATUSES
                    and _payload_matches_requested_identity(
                        payload,
                        pid=managed.process.pid,
                        process_create_time=managed.process_create_time,
                    )
                ):
                    return ExternalProcessTerminationOutcome.CONFIRMED_EXITED
                return ExternalProcessTerminationOutcome.UNCONFIRMED
            stopped = _terminate_managed_process(managed)
            if managed.monitor:
                managed.monitor.join(timeout=2.0)
            if not stopped or managed.termination_unconfirmed:
                try:
                    _write_termination_unconfirmed(managed)
                except Exception as marker_exc:
                    logger.critical(
                        "external coding stop ownership marker failed (%s)",
                        type(marker_exc).__name__,
                    )
                return ExternalProcessTerminationOutcome.UNCONFIRMED
            if managed.monitor is None or not managed.monitor.is_alive():
                _write_confirmed_stop(managed)
                self._remove_managed(managed)
            return ExternalProcessTerminationOutcome.CONFIRMED_STOPPED
        # A status file is not a durable ownership authority. After restart,
        # PID-only state must never be used to accept a terminal result or to
        # terminate a potentially reused process.
        if process_create_time is None:
            return ExternalProcessTerminationOutcome.UNCONFIRMED
        if payload is not None and str(payload.get("status")) in _TERMINAL_PROCESS_STATUSES:
            if not _payload_matches_requested_identity(
                payload,
                pid=int(pid),
                process_create_time=process_create_time,
                require_create_time=True,
            ):
                return ExternalProcessTerminationOutcome.UNCONFIRMED
            return ExternalProcessTerminationOutcome.CONFIRMED_EXITED
        identity = _resolve_process_identity(
            pid=int(pid),
            process_create_time=process_create_time,
            payload=payload,
        )
        if identity is None or not _pid_matches_identity(identity):
            return ExternalProcessTerminationOutcome.UNCONFIRMED
        stopped = _terminate_pid_tree(int(pid))
        if stopped:
            _write_status(
                _status_path(log_path),
                _status_payload(
                    identity,
                    status="interrupted",
                    finished_at=_utc_now(),
                    error_category="unknown",
                    error_message=_safe_string(reason, 120) or "stopped by Exemplar",
                ),
            )
            return ExternalProcessTerminationOutcome.CONFIRMED_STOPPED
        _write_unmanaged_termination_unconfirmed(
            _status_path(log_path),
            identity=identity,
            payload=payload,
        )
        return ExternalProcessTerminationOutcome.UNCONFIRMED

    @classmethod
    def _run_monitor_guarded(cls, managed: _ManagedProcess) -> None:
        """Keep process ownership recoverable when any monitor operation fails."""
        try:
            cls._monitor(managed)
        except BaseException as exc:
            logger.error(
                "external coding process monitor failed (%s)",
                type(exc).__name__,
            )
            cls._recover_monitor_failure(managed)

    @classmethod
    def _recover_monitor_failure(cls, managed: _ManagedProcess) -> None:
        try:
            stopped = _terminate_managed_process(managed)
        except BaseException as exc:
            logger.critical(
                "external coding monitor recovery termination failed (%s)",
                type(exc).__name__,
            )
            with managed.termination_lock:
                managed.termination_unconfirmed = True
            stopped = False

        _stop_output_reader(managed)

        if not stopped:
            try:
                _write_termination_unconfirmed(managed)
            except BaseException as exc:
                # The durable attempt row remains running with its ownership
                # guard set. Keep the in-memory registry entry as a second path.
                logger.critical(
                    "external coding monitor recovery marker failed (%s)",
                    type(exc).__name__,
                )
            return

        payload = _status_payload(
            _managed_identity(managed),
            status="failed",
            exit_code=_safe_int(managed.process.poll()),
            finished_at=_utc_now(),
            error_category="process_error",
            error_message="external coding process monitor failed",
        )
        managed.recovery_terminal_payload = payload
        try:
            _write_status(managed.status_path, payload)
        except BaseException as exc:
            # Retain the registry entry so an in-process poll can reconstruct
            # the terminal state; the database guard remains fail-closed after
            # restart if even that recovery path is unavailable.
            logger.critical(
                "external coding monitor terminal status write failed (%s)",
                type(exc).__name__,
            )
            return
        cls._remove_managed(managed)

    @classmethod
    def _monitor(cls, managed: _ManagedProcess) -> None:
        if managed.interactive:
            cls._monitor_interactive(managed)
            return
        output_queue: queue.Queue[bytes | _OutputReadFailure | None] = queue.Queue(maxsize=64)
        reader_cancel = threading.Event()
        reader = threading.Thread(
            target=_read_stream,
            args=(managed.process.stdout, output_queue, reader_cancel),
            name=f"external-coding-output-{managed.process.pid}",
            daemon=True,
        )
        managed.output_reader = reader
        managed.output_reader_cancel = reader_cancel
        reader.start()
        bounded_log = _BoundedLog(managed.log_path, managed.max_log_bytes)
        started = time.monotonic()
        line_buffer = ""
        external_ref: str | None = None
        dangerous_action: str | None = None
        timed_out = False
        stream_ended = False
        termination_requested = False

        while not stream_ended:
            try:
                chunk = output_queue.get(timeout=0.1)
            except queue.Empty:
                chunk = b""
            if chunk is None:
                stream_ended = True
            elif isinstance(chunk, _OutputReadFailure):
                logger.error(
                    "external coding output reader failed (%s)",
                    chunk.exception_type,
                )
                raise RuntimeError("external coding output reader failed")
            elif chunk:
                text = chunk.decode("utf-8", errors="replace")
                bounded_log.append(text)
                line_buffer += text
                if len(line_buffer) > 131_072:
                    line_buffer = line_buffer[-65_536:]
                lines = line_buffer.splitlines(keepends=True)
                if lines and not lines[-1].endswith(("\n", "\r")):
                    line_buffer = lines.pop()
                else:
                    line_buffer = ""
                for line in lines:
                    discovered_ref, discovered_action = _inspect_json_event(line)
                    if discovered_ref and not external_ref:
                        external_ref = discovered_ref
                        _write_running_status(managed, external_ref)
                    if discovered_action:
                        dangerous_action = discovered_action
                        break
            if dangerous_action:
                termination_requested = True
                break
            if managed.stop_reason:
                termination_requested = True
                break
            if time.monotonic() - started >= managed.timeout_seconds:
                timed_out = True
                termination_requested = True
                break
        if line_buffer:
            discovered_ref, discovered_action = _inspect_json_event(line_buffer)
            external_ref = external_ref or discovered_ref
            dangerous_action = dangerous_action or discovered_action
            termination_requested = termination_requested or bool(discovered_action)
        if termination_requested:
            if not _terminate_managed_process(managed):
                _stop_output_reader(managed)
                _write_termination_unconfirmed(managed, external_ref=external_ref)
                return
        try:
            exit_code = managed.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if not _terminate_managed_process(managed):
                _stop_output_reader(managed)
                _write_termination_unconfirmed(managed, external_ref=external_ref)
                return
            exit_code = _safe_int(managed.process.poll())
        _stop_output_reader(managed)
        bounded_log.flush()

        if dangerous_action:
            status = "interrupted"
            category = "protocol_violation"
            message = f"blocked high-risk git operation: {dangerous_action}"
        elif timed_out:
            status = "interrupted"
            category = "process_error"
            message = "external coding process timed out"
        elif managed.stop_reason:
            status = "interrupted"
            category = "unknown"
            message = managed.stop_reason
        elif exit_code == 0:
            status = "succeeded"
            category = None
            message = None
        else:
            status = "failed"
            category, message = _classify_failure(bounded_log.text())

        payload = _status_payload(
            _managed_identity(managed),
            status=status,
            exit_code=exit_code,
            finished_at=_utc_now(),
            external_session_ref=external_ref,
            error_category=category,
            error_message=message,
        )
        _write_status(managed.status_path, payload)
        cls._remove_managed(managed)

    @classmethod
    def _monitor_interactive(cls, managed: _ManagedProcess) -> None:
        started = time.monotonic()
        timed_out = False
        termination_requested = False
        while managed.process.poll() is None:
            if managed.stop_reason:
                termination_requested = True
                break
            if time.monotonic() - started >= managed.timeout_seconds:
                timed_out = True
                termination_requested = True
                break
            time.sleep(0.1)
        if termination_requested and not _terminate_managed_process(managed):
            _write_termination_unconfirmed(managed)
            return
        try:
            exit_code = managed.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if not _terminate_managed_process(managed):
                _write_termination_unconfirmed(managed)
                return
            exit_code = _safe_int(managed.process.poll())

        if timed_out:
            status = "interrupted"
            category = "process_error"
            message = "external coding process timed out"
        elif managed.stop_reason:
            status = "interrupted"
            category = "unknown"
            message = managed.stop_reason
        elif exit_code == 0:
            status = "succeeded"
            category = None
            message = None
        else:
            status = "failed"
            category = "process_error"
            message = "interactive external coding process exited with an error"

        _write_status(
            managed.status_path,
            _status_payload(
                _managed_identity(managed),
                status=status,
                exit_code=exit_code,
                finished_at=_utc_now(),
                error_category=category,
                error_message=message,
            ),
        )
        cls._remove_managed(managed)

    @classmethod
    def _register_managed(cls, managed: _ManagedProcess) -> bool:
        """Register a new owner only when its PID has no other owner."""
        with cls._registry_lock:
            if any(
                current is not managed and current.process.pid == managed.process.pid
                for current in cls._registry.values()
            ):
                return False
            cls._registry[_managed_registry_key(managed)] = managed
            return True

    @classmethod
    def _retain_managed(cls, managed: _ManagedProcess) -> None:
        """Retain an unconfirmed process without overwriting any prior owner."""
        with cls._registry_lock:
            cls._registry[_managed_registry_key(managed)] = managed

    @classmethod
    def _lookup_managed(
        cls,
        *,
        pid: int,
        process_create_time: float | None,
        status_path: Path,
    ) -> _ManagedProcess | None:
        expected_status_path = _normalized_path(status_path)
        with cls._registry_lock:
            candidates = [
                managed
                for managed in cls._registry.values()
                if managed.process.pid == int(pid)
                and _normalized_path(managed.status_path) == expected_status_path
                and _create_times_match(
                    managed.process_create_time,
                    process_create_time,
                    allow_missing_requested=True,
                )
            ]
        return candidates[0] if len(candidates) == 1 else None

    @classmethod
    def _remove_managed(cls, managed: _ManagedProcess) -> None:
        """CAS removal: an old monitor can never remove a newer owner."""
        key = _managed_registry_key(managed)
        with cls._registry_lock:
            if cls._registry.get(key) is managed:
                cls._registry.pop(key, None)


def _read_stream(
    stream,
    output_queue: queue.Queue[bytes | _OutputReadFailure | None],
    cancel: threading.Event,
) -> None:
    try:
        if stream is not None:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                if not _put_output_chunk(output_queue, chunk, cancel):
                    return
    except BaseException as exc:
        _put_output_chunk(
            output_queue,
            _OutputReadFailure(type(exc).__name__),
            cancel,
        )
    finally:
        _put_output_chunk(output_queue, None, cancel)


def _put_output_chunk(
    output_queue: queue.Queue[bytes | _OutputReadFailure | None],
    chunk: bytes | _OutputReadFailure | None,
    cancel: threading.Event,
) -> bool:
    while not cancel.is_set():
        try:
            output_queue.put(chunk, timeout=0.1)
            return True
        except queue.Full:
            continue
    return False


def _stop_output_reader(managed: _ManagedProcess) -> None:
    cancel = managed.output_reader_cancel
    reader = managed.output_reader
    if cancel is not None:
        cancel.set()
    if reader is not None and managed.process.poll() is not None:
        reader.join(timeout=2.0)


def _inspect_json_event(line: str) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(line)
    except (TypeError, ValueError):
        return None, None
    external_ref = _find_external_ref(payload)
    for command in _find_command_values(payload):
        dangerous = _dangerous_git_action(command)
        if dangerous:
            return external_ref, dangerous
    return external_ref, None


def _find_external_ref(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            if normalized in {
                "session_id",
                "sessionid",
                "thread_id",
                "threadid",
                "conversation_id",
            }:
                safe = _safe_external_ref(item)
                if safe:
                    return safe
        for item in value.values():
            found = _find_external_ref(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_external_ref(item)
            if found:
                return found
    return None


def _find_command_values(value: Any) -> list[str]:
    commands: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            if normalized in {"command", "cmd", "shell_command"}:
                if isinstance(item, str):
                    commands.append(item)
                elif isinstance(item, list):
                    commands.append(" ".join(str(part) for part in item))
            elif isinstance(item, (dict, list)):
                commands.extend(_find_command_values(item))
    elif isinstance(value, list):
        for item in value:
            commands.extend(_find_command_values(item))
    return commands


def _dangerous_git_action(command: str) -> str | None:
    normalized = str(command).strip()
    for pattern, label in _DANGEROUS_GIT_PATTERNS:
        if pattern.search(normalized):
            return label
    return None


def _classify_failure(log_text: str) -> tuple[str, str]:
    """把 CLI 日志归类成可行动的失败原因。

    分类结果直接决定派活方的下一步：``model_unavailable`` 会让它换工具或降档，
    而真正的原因若是端点不可达，换多少次工具都没用。所以匹配必须够具体——
    日志里包含我们自己拼的命令行，裸词会命中参数名而不是错误信息。
    """
    lowered = log_text.lower()
    if any(marker in lowered for marker in ("quota", "rate limit", "usage limit")):
        return "quota_exhausted", "external coding quota is exhausted"
    # 认证判定排在模型之前：CLI 常把网络层 403 显示成 "Failed to authenticate"，
    # 让它先被更模糊的规则接走会指向完全错误的补救方向。
    if any(
        marker in lowered
        for marker in (
            "unauthorized",
            "not logged in",
            "login required",
            "failed to authenticate",
            "authentication_failed",
            "authentication failed",
        )
    ):
        return "login_required", "external coding login is required"
    # 用短语而非裸 "effort"：``--effort`` 出现在每条 Claude 命令里，
    # 裸词几乎能命中任何一次失败，把真实原因盖掉。
    if any(
        marker in lowered
        for marker in (
            "model unavailable",
            "unsupported model",
            "unsupported effort",
            "invalid effort",
            "unknown model",
        )
    ):
        return "model_unavailable", "requested external coding model or effort is unavailable"
    if any(marker in lowered for marker in ("connection", "network", "dns", "timed out")):
        return "network", "external coding process encountered a network error"
    return "process_error", "external coding process exited with an error"


def _terminate_managed_process(managed: _ManagedProcess) -> bool:
    """Terminate a managed tree without losing a prior unconfirmed outcome."""
    with managed.termination_lock:
        if managed.termination_unconfirmed and managed.process.poll() is not None:
            return False
        confirmed = _terminate_process(managed.process)
        managed.termination_unconfirmed = not confirmed
        return confirmed


def _terminate_process(process: subprocess.Popen[bytes]) -> bool:
    """Stop a spawned process tree and confirm every observed member exited."""
    if process.poll() is not None:
        return True
    try:
        parent = psutil.Process(process.pid)
        descendants = parent.children(recursive=True)
        stopped = _terminate_psutil_processes([*descendants, parent])
        try:
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return stopped and process.poll() is not None
    except psutil.NoSuchProcess:
        try:
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return process.poll() is not None
    except psutil.Error:
        try:
            process.terminate()
            process.wait(timeout=2)
            # The parent stopped, but process-tree enumeration failed, so the
            # tree as a whole cannot be certified as gone.
            return False
        except OSError:
            return False
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=2)
                return False
            except (OSError, subprocess.TimeoutExpired):
                return False


def _terminate_pid_tree(pid: int) -> bool:
    try:
        process = psutil.Process(pid)
    except psutil.NoSuchProcess:
        # This path is only used after a restart. If the parent vanished
        # between identity verification and tree enumeration, descendants
        # cannot be proven gone.
        return False
    except psutil.Error:
        return False
    try:
        descendants = process.children(recursive=True)
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return False
    return _terminate_psutil_processes([*descendants, process])


def _terminate_psutil_processes(processes: list[psutil.Process]) -> bool:
    """Terminate, then kill, and finally verify a fixed process set is gone."""
    for item in processes:
        try:
            item.terminate()
        except psutil.Error:
            pass
    try:
        _, alive = psutil.wait_procs(processes, timeout=2)
    except psutil.Error:
        return False
    for item in alive:
        try:
            item.kill()
        except psutil.Error:
            pass
    if not alive:
        return True
    try:
        _, still_alive = psutil.wait_procs(alive, timeout=2)
    except psutil.Error:
        return False
    return not still_alive


def _process_create_time(pid: int) -> float | None:
    try:
        return float(psutil.Process(int(pid)).create_time())
    except (psutil.Error, TypeError, ValueError):
        return None


def _managed_identity(managed: _ManagedProcess) -> ProcessIdentity:
    return ProcessIdentity(managed.process.pid, managed.process_create_time)


def _managed_registry_key(managed: _ManagedProcess) -> _ProcessRegistryKey:
    return _ProcessRegistryKey(
        identity=_managed_identity(managed),
        status_path=_normalized_path(managed.status_path),
        instance_token=id(managed),
    )


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _create_times_match(
    actual: float | None,
    requested: float | None,
    *,
    allow_missing_requested: bool = False,
) -> bool:
    if requested is None and allow_missing_requested:
        return True
    if actual is None or requested is None:
        return actual is None and requested is None
    return abs(float(actual) - float(requested)) < 0.01


def _payload_identity(payload: dict[str, Any] | None) -> ProcessIdentity | None:
    if payload is None:
        return None
    pid = _safe_int(payload.get("pid"))
    create_time = _safe_float(payload.get("processCreateTime"))
    if pid is None or create_time is None:
        return None
    return ProcessIdentity(pid, create_time)


def _resolve_process_identity(
    *,
    pid: int | None,
    process_create_time: float | None,
    payload: dict[str, Any] | None,
    managed: _ManagedProcess | None = None,
) -> ProcessIdentity | None:
    """Combine ownership sources, rejecting conflicts instead of guessing."""
    if managed is not None:
        managed_identity = _managed_identity(managed)
        if pid is not None and managed_identity.pid != int(pid):
            return None
        if process_create_time is not None and not _create_times_match(
            managed_identity.create_time,
            process_create_time,
        ):
            return None
        return managed_identity

    # A status payload cannot fill a missing durable creation time for an
    # already-known PID. Doing so would turn untrusted/stale metadata into a
    # new ownership authority and allow the next poll to accept it.
    if pid is not None and process_create_time is None:
        return None

    persisted = (
        ProcessIdentity(int(pid), float(process_create_time))
        if pid is not None and process_create_time is not None
        else None
    )
    from_payload = _payload_identity(payload)
    if persisted is not None and from_payload is not None:
        if persisted.pid != from_payload.pid:
            return None
        if abs(float(persisted.create_time) - float(from_payload.create_time)) >= 0.01:
            return None
        return persisted
    if persisted is not None:
        payload_pid = _safe_int(payload.get("pid")) if payload is not None else None
        return persisted if payload_pid in {None, persisted.pid} else None
    if from_payload is not None:
        return from_payload if pid in {None, from_payload.pid} else None
    return None


def _pid_matches_identity(identity: ProcessIdentity) -> bool:
    """PID alone is never sufficient for ownership after a restart."""
    if identity.create_time is None:
        return False
    actual_created = _process_create_time(identity.pid)
    return actual_created is not None and abs(actual_created - identity.create_time) < 0.01


def _payload_matches_requested_identity(
    payload: dict[str, Any],
    *,
    pid: int,
    process_create_time: float | None,
    require_create_time: bool = False,
) -> bool:
    payload_pid = _safe_int(payload.get("pid"))
    if payload_pid != int(pid):
        return False
    if process_create_time is None:
        return not require_create_time
    payload_create_time = _safe_float(payload.get("processCreateTime"))
    return _create_times_match(payload_create_time, process_create_time)


def _terminal_process_snapshot(
    *,
    payload: dict[str, Any],
    managed: _ManagedProcess | None,
    requested_pid: int | None,
    requested_create_time: float | None,
    termination_unconfirmed: bool,
    identity: ProcessIdentity | None,
    fallback_pid: int | None,
    fallback_create_time: float | None,
    log_path: Path,
) -> ExternalProcessSnapshot:
    """Accept terminal metadata only when it belongs to the durable owner."""
    expected_identity: ProcessIdentity | None = None
    if managed is not None:
        expected_identity = _managed_identity(managed)
    elif requested_pid is not None:
        expected_identity = ProcessIdentity(
            int(requested_pid),
            float(requested_create_time) if requested_create_time is not None else None,
        )

    requires_identity = bool(
        managed is not None
        or requested_pid is not None
        or requested_create_time is not None
        or termination_unconfirmed
    )
    verified = not requires_identity
    if expected_identity is not None:
        verified = _payload_matches_requested_identity(
            payload,
            pid=expected_identity.pid,
            process_create_time=expected_identity.create_time,
            require_create_time=managed is None,
        )

    if not verified:
        return _uncertain_process_snapshot(
            identity=identity,
            fallback_pid=fallback_pid,
            fallback_create_time=fallback_create_time,
            payload=payload,
            log_path=log_path,
            message="external coding process status identity could not be verified",
        )
    return _snapshot_from_status_payload(
        payload,
        fallback_pid=fallback_pid,
        fallback_create_time=fallback_create_time,
        log_path=log_path,
    )


def _snapshot_from_status_payload(
    payload: dict[str, Any],
    *,
    fallback_pid: int | None,
    fallback_create_time: float | None,
    log_path: Path,
) -> ExternalProcessSnapshot:
    return ExternalProcessSnapshot(
        status=str(payload.get("status") or "failed"),
        pid=_safe_int(payload.get("pid")) or fallback_pid,
        process_create_time=(
            _safe_float(payload.get("processCreateTime"))
            if payload.get("processCreateTime") is not None
            else fallback_create_time
        ),
        termination_unconfirmed=False,
        exit_code=_safe_int(payload.get("exitCode")),
        external_session_ref=_safe_external_ref(payload.get("externalSessionRef")),
        error_category=_safe_string(payload.get("errorCategory"), 80),
        error_message=_safe_string(payload.get("errorMessage"), 300),
        log_tail=_read_log_tail(log_path),
    )


def _uncertain_process_snapshot(
    *,
    identity: ProcessIdentity | None,
    fallback_pid: int | None,
    fallback_create_time: float | None,
    payload: dict[str, Any] | None,
    log_path: Path,
    message: str,
) -> ExternalProcessSnapshot:
    return ExternalProcessSnapshot(
        status="running",
        pid=identity.pid if identity is not None else fallback_pid,
        process_create_time=(
            identity.create_time if identity is not None else fallback_create_time
        ),
        termination_unconfirmed=True,
        external_session_ref=(
            _safe_external_ref(payload.get("externalSessionRef")) if payload else None
        ),
        error_category="process_error",
        error_message=message,
        log_tail=_read_log_tail(log_path),
    )


def _status_payload(
    identity: ProcessIdentity,
    *,
    status: str,
    exit_code: int | None = None,
    external_session_ref: str | None = None,
    error_category: str | None = None,
    error_message: str | None = None,
    termination_unconfirmed: bool = False,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    """Build the allowlisted private process-control status payload."""
    payload: dict[str, Any] = {
        "status": status,
        "pid": identity.pid,
        "processCreateTime": identity.create_time,
        "exitCode": exit_code,
        "externalSessionRef": _safe_external_ref(external_session_ref),
        "errorCategory": _safe_string(error_category, 80),
        "errorMessage": _safe_string(error_message, 300),
        "startedAt": started_at,
        "finishedAt": finished_at,
    }
    if termination_unconfirmed:
        payload["terminationUnconfirmed"] = True
    return payload


def _write_running_status(managed: _ManagedProcess, external_ref: str) -> None:
    _write_status(
        managed.status_path,
        _status_payload(
            _managed_identity(managed),
            status="running",
            external_session_ref=external_ref,
        ),
    )


def _write_termination_unconfirmed(
    managed: _ManagedProcess,
    *,
    external_ref: str | None = None,
) -> None:
    """Persist fail-closed ownership when the full tree cannot be certified gone."""
    with managed.termination_lock:
        if not managed.termination_unconfirmed:
            return
        existing = _read_status(managed.status_path) or {}
        _write_status(
            managed.status_path,
            _status_payload(
                _managed_identity(managed),
                status="running",
                external_session_ref=(
                    external_ref or _safe_external_ref(existing.get("externalSessionRef"))
                ),
                termination_unconfirmed=True,
                error_category="process_error",
                error_message=_TERMINATION_UNCONFIRMED_MESSAGE,
            ),
        )


def _write_unmanaged_termination_unconfirmed(
    status_path: Path,
    *,
    identity: ProcessIdentity,
    payload: dict[str, Any] | None,
) -> None:
    existing = payload or {}
    _write_status(
        status_path,
        _status_payload(
            identity,
            status="running",
            external_session_ref=_safe_external_ref(existing.get("externalSessionRef")),
            termination_unconfirmed=True,
            error_category="process_error",
            error_message=_TERMINATION_UNCONFIRMED_MESSAGE,
        ),
    )


def _write_confirmed_stop(managed: _ManagedProcess) -> None:
    _write_status(
        managed.status_path,
        _status_payload(
            _managed_identity(managed),
            status="interrupted",
            finished_at=_utc_now(),
            error_category="unknown",
            error_message=managed.stop_reason or "stopped by Exemplar",
        ),
    )


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    safe_payload = {key: value for key, value in payload.items() if value is not None}
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(safe_payload, ensure_ascii=True, sort_keys=True)
    temporary = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    for _ in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            time.sleep(0.02)
    path.write_text(encoded, encoding="utf-8")
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass


def _read_status(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _status_path(log_path: Path) -> Path:
    if log_path.parent.name == "logs":
        session_dir = log_path.parent.parent
        return session_dir.parent / ".control" / session_dir.name / f"{log_path.name}.status.json"
    return log_path.with_suffix(f"{log_path.suffix}.status.json")


def _read_log_tail(log_path: Path, max_chars: int = 16_000) -> str | None:
    try:
        with log_path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - max_chars * 4))
            data = handle.read(max_chars * 4)
    except OSError:
        return None
    return data.decode("utf-8", errors="replace")[-max_chars:] or None


def _redact_log_text(value: str) -> str:
    return redact_sensitive_text(value, redact_emails=True)


def safe_external_command_summary(command: list[str]) -> str:
    """Return the path-, prompt-, and secret-safe command projection."""
    parts: list[str] = []
    hide_next = False
    for arg in command[:12]:
        if hide_next:
            parts.append("<prompt>")
            hide_next = False
            continue
        parts.append(_safe_arg(arg))
        if arg in {"-p", "--prompt"}:
            hide_next = True
    if len(command) > 12:
        parts.append("...")
    return " ".join(parts)


def _safe_command_summary(command: list[str]) -> str:
    """Backward-compatible internal alias for existing callers and tests."""
    return safe_external_command_summary(command)


def _safe_arg(value: str) -> str:
    raw = str(value)
    if "\n" in raw or len(raw) > 240:
        return "<prompt>"
    if _ABSOLUTE_PATH_RE.search(raw):
        return "<path>"
    lowered = raw.lower()
    if any(marker in lowered for marker in ("token", "key", "secret", "password")):
        return "<redacted>"
    return _redact_log_text(raw[:200])


def _resolve_executable(command: list[str]) -> list[str]:
    """Resolve PATH/PATHEXT shims without invoking a shell."""
    if not command:
        return []
    resolved = shutil.which(str(command[0]))
    if not resolved:
        return list(command)
    return [resolved, *command[1:]]


def _safe_external_ref(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw if _SAFE_EXTERNAL_REF_RE.fullmatch(raw) else None


def _safe_string(value: Any, max_chars: int) -> str | None:
    if value is None:
        return None
    return _redact_log_text(str(value).strip())[:max_chars] or None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
