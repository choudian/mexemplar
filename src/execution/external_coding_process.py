"""Execution-layer process runner for external coding CLI tools."""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from src.utils.sensitive_text import redact_sensitive_text

_SAFE_EXTERNAL_REF_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,200}$")
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^@?[A-Za-z]:[\\/]")
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


@dataclass(frozen=True)
class ExternalProcessStart:
    pid: int
    command_summary: str


@dataclass(frozen=True)
class ExternalProcessSnapshot:
    status: str
    pid: int | None = None
    exit_code: int | None = None
    external_session_ref: str | None = None
    error_category: str | None = None
    error_message: str | None = None
    log_tail: str | None = None


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

    _registry: dict[int, _ManagedProcess] = {}
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
        popen_kwargs: dict[str, Any] = {}
        if interactive and os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdin=None if interactive else subprocess.DEVNULL,
            stdout=None if interactive else subprocess.PIPE,
            stderr=None if interactive else subprocess.STDOUT,
            text=False,
            bufsize=0,
            **popen_kwargs,
        )
        managed = _ManagedProcess(
            process=process,
            process_create_time=_process_create_time(process.pid),
            interactive=interactive,
            log_path=log_path,
            status_path=_status_path(log_path),
            timeout_seconds=max(1, int(timeout_seconds)),
            max_log_bytes=max(1024, int(max_log_bytes)),
        )
        with self._registry_lock:
            self._registry[process.pid] = managed
        _write_status(
            managed.status_path,
            {
                "status": "running",
                "pid": process.pid,
                "processCreateTime": managed.process_create_time,
                "startedAt": _utc_now(),
            },
        )
        monitor = threading.Thread(
            target=self._monitor,
            args=(managed,),
            name=f"external-coding-{process.pid}",
            daemon=True,
        )
        managed.monitor = monitor
        monitor.start()
        return ExternalProcessStart(
            pid=process.pid,
            command_summary=_safe_command_summary(command),
        )

    def poll(self, *, pid: int | None, log_path: Path) -> ExternalProcessSnapshot:
        managed = None
        if pid:
            with self._registry_lock:
                managed = self._registry.get(int(pid))
        if managed is not None and managed.process.poll() is not None and managed.monitor:
            managed.monitor.join(timeout=0.2)

        payload = _read_status(_status_path(log_path))
        if payload is None:
            if pid and _pid_matches_status(pid, payload=None):
                return ExternalProcessSnapshot(status="running", pid=pid)
            return ExternalProcessSnapshot(
                status="failed",
                pid=pid,
                error_category="process_error",
                error_message="external coding process ended without status metadata",
                log_tail=_read_log_tail(log_path),
            )

        status = str(payload.get("status") or "failed")
        if status == "running" and pid and not _pid_matches_status(pid, payload=payload):
            if managed is not None and managed.monitor:
                managed.monitor.join(timeout=0.5)
                if managed.monitor.is_alive():
                    return ExternalProcessSnapshot(
                        status="running",
                        pid=pid,
                        external_session_ref=_safe_external_ref(payload.get("externalSessionRef")),
                        log_tail=_read_log_tail(log_path),
                    )
                payload = _read_status(_status_path(log_path)) or payload
                status = str(payload.get("status") or "failed")
            if status == "running":
                status = "failed"
                payload = {
                    **payload,
                    "errorCategory": "process_error",
                    "errorMessage": "external coding process exited before status was recorded",
                }
        return ExternalProcessSnapshot(
            status=status,
            pid=_safe_int(payload.get("pid")) or pid,
            exit_code=_safe_int(payload.get("exitCode")),
            external_session_ref=_safe_external_ref(payload.get("externalSessionRef")),
            error_category=_safe_string(payload.get("errorCategory"), 80),
            error_message=_safe_string(payload.get("errorMessage"), 300),
            log_tail=_read_log_tail(log_path),
        )

    def stop(
        self,
        *,
        pid: int | None,
        log_path: Path,
        reason: str,
    ) -> bool:
        if not pid:
            return False
        with self._registry_lock:
            managed = self._registry.get(int(pid))
            if managed is not None:
                managed.stop_reason = _safe_string(reason, 120) or "stopped by Exemplar"
        if managed is not None:
            _terminate_process(managed.process)
            if managed.monitor:
                managed.monitor.join(timeout=2.0)
            return managed.process.poll() is not None
        payload = _read_status(_status_path(log_path))
        if not _pid_matches_status(int(pid), payload=payload):
            return False
        stopped = _terminate_pid_tree(int(pid))
        if stopped:
            _write_status(
                _status_path(log_path),
                {
                    "status": "interrupted",
                    "pid": int(pid),
                    "finishedAt": _utc_now(),
                    "errorCategory": "unknown",
                    "errorMessage": _safe_string(reason, 120) or "stopped by Exemplar",
                },
            )
        return stopped

    @classmethod
    def _monitor(cls, managed: _ManagedProcess) -> None:
        if managed.interactive:
            cls._monitor_interactive(managed)
            return
        output_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=64)
        reader = threading.Thread(
            target=_read_stream,
            args=(managed.process.stdout, output_queue),
            name=f"external-coding-output-{managed.process.pid}",
            daemon=True,
        )
        reader.start()
        bounded_log = _BoundedLog(managed.log_path, managed.max_log_bytes)
        started = time.monotonic()
        line_buffer = ""
        external_ref: str | None = None
        dangerous_action: str | None = None
        timed_out = False
        stream_ended = False

        while not stream_ended:
            try:
                chunk = output_queue.get(timeout=0.1)
            except queue.Empty:
                chunk = b""
            if chunk is None:
                stream_ended = True
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
                _terminate_process(managed.process)
                break
            if managed.stop_reason:
                _terminate_process(managed.process)
                break
            if time.monotonic() - started >= managed.timeout_seconds:
                timed_out = True
                _terminate_process(managed.process)
                break
            if managed.process.poll() is not None and output_queue.empty():
                stream_ended = True

        if line_buffer:
            discovered_ref, discovered_action = _inspect_json_event(line_buffer)
            external_ref = external_ref or discovered_ref
            dangerous_action = dangerous_action or discovered_action
        _terminate_if_requested(managed, timed_out=timed_out, dangerous_action=dangerous_action)
        try:
            exit_code = managed.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            managed.process.kill()
            exit_code = managed.process.wait(timeout=5)
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

        payload: dict[str, Any] = {
            "status": status,
            "pid": managed.process.pid,
            "processCreateTime": managed.process_create_time,
            "exitCode": exit_code,
            "finishedAt": _utc_now(),
        }
        if external_ref:
            payload["externalSessionRef"] = external_ref
        if category:
            payload["errorCategory"] = category
        if message:
            payload["errorMessage"] = message
        _write_status(managed.status_path, payload)
        with cls._registry_lock:
            cls._registry.pop(managed.process.pid, None)

    @classmethod
    def _monitor_interactive(cls, managed: _ManagedProcess) -> None:
        started = time.monotonic()
        timed_out = False
        while managed.process.poll() is None:
            if managed.stop_reason:
                _terminate_process(managed.process)
                break
            if time.monotonic() - started >= managed.timeout_seconds:
                timed_out = True
                _terminate_process(managed.process)
                break
            time.sleep(0.1)
        try:
            exit_code = managed.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            managed.process.kill()
            exit_code = managed.process.wait(timeout=5)

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
            {
                "status": status,
                "pid": managed.process.pid,
                "processCreateTime": managed.process_create_time,
                "exitCode": exit_code,
                "finishedAt": _utc_now(),
                "errorCategory": category,
                "errorMessage": message,
            },
        )
        with cls._registry_lock:
            cls._registry.pop(managed.process.pid, None)


def _read_stream(stream, output_queue: queue.Queue[bytes | None]) -> None:
    try:
        if stream is not None:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                output_queue.put(chunk)
    finally:
        output_queue.put(None)


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
    lowered = log_text.lower()
    if any(marker in lowered for marker in ("quota", "rate limit", "usage limit")):
        return "quota_exhausted", "external coding quota is exhausted"
    if any(marker in lowered for marker in ("unauthorized", "not logged in", "login required")):
        return "login_required", "external coding login is required"
    if any(marker in lowered for marker in ("model unavailable", "unsupported model", "effort")):
        return "model_unavailable", "requested external coding model or effort is unavailable"
    if any(marker in lowered for marker in ("connection", "network", "dns", "timed out")):
        return "network", "external coding process encountered a network error"
    return "process_error", "external coding process exited with an error"


def _terminate_if_requested(
    managed: _ManagedProcess,
    *,
    timed_out: bool,
    dangerous_action: str | None,
) -> None:
    if timed_out or dangerous_action or managed.stop_reason:
        _terminate_process(managed.process)


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        parent = psutil.Process(process.pid)
        descendants = parent.children(recursive=True)
        for child in descendants:
            try:
                child.terminate()
            except psutil.Error:
                pass
        try:
            parent.terminate()
        except psutil.Error:
            pass
        _, alive = psutil.wait_procs([*descendants, parent], timeout=2)
        for item in alive:
            try:
                item.kill()
            except psutil.Error:
                pass
    except psutil.Error:
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass


def _terminate_pid_tree(pid: int) -> bool:
    try:
        process = psutil.Process(pid)
    except psutil.Error:
        return False
    descendants = process.children(recursive=True)
    for item in [*descendants, process]:
        try:
            item.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs([*descendants, process], timeout=2)
    for item in alive:
        try:
            item.kill()
        except psutil.Error:
            pass
    return True


def _process_create_time(pid: int) -> float | None:
    try:
        return float(psutil.Process(int(pid)).create_time())
    except (psutil.Error, TypeError, ValueError):
        return None


def _pid_matches_status(pid: int, payload: dict[str, Any] | None) -> bool:
    """Match a persisted process identity; PID alone is never enough after restart."""
    if payload is None:
        with ExternalCodingProcessRunner._registry_lock:
            managed = ExternalCodingProcessRunner._registry.get(int(pid))
        return managed is not None and managed.process.poll() is None
    expected_pid = _safe_int(payload.get("pid"))
    expected_created = payload.get("processCreateTime")
    if expected_pid != int(pid) or not isinstance(expected_created, (int, float)):
        return False
    actual_created = _process_create_time(pid)
    return actual_created is not None and abs(actual_created - float(expected_created)) < 0.01


def _write_running_status(managed: _ManagedProcess, external_ref: str) -> None:
    _write_status(
        managed.status_path,
        {
            "status": "running",
            "pid": managed.process.pid,
            "processCreateTime": managed.process_create_time,
            "externalSessionRef": external_ref,
        },
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


def _safe_command_summary(command: list[str]) -> str:
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


def _safe_arg(value: str) -> str:
    raw = str(value)
    if "\n" in raw or len(raw) > 240:
        return "<prompt>"
    if _WINDOWS_ABSOLUTE_PATH_RE.match(raw) or raw.startswith(("@/", "/")):
        return "<path>"
    lowered = raw.lower()
    if any(marker in lowered for marker in ("token", "key", "secret", "password")):
        return "<redacted>"
    return _redact_log_text(raw[:200])


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


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
