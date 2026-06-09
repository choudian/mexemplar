"""Synchronous command execution boundary for Agent built-ins."""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class CommandParseError(ValueError):
    """Raised when a command requires shell parsing or has invalid quoting."""


_SHELL_CONTROL_TOKENS = ("\r", "\n", "\x00", ";", "|", "&", "`", ">", "<")


def contains_shell_control_syntax(command: str) -> bool:
    return any(token in str(command) for token in _SHELL_CONTROL_TOKENS)


def parse_command_argv(command: str) -> list[str]:
    raw = str(command or "").strip()
    if not raw:
        raise CommandParseError("Command must not be empty.")
    if contains_shell_control_syntax(raw):
        raise CommandParseError("Shell control syntax is not supported.")
    try:
        argv = shlex.split(raw, posix=os.name != "nt")
    except ValueError as exc:
        raise CommandParseError("Command quoting is invalid.") from exc
    normalized = [_strip_wrapping_quotes(value) for value in argv]
    if not normalized or not normalized[0]:
        raise CommandParseError("Command executable must not be empty.")
    return normalized


def _strip_wrapping_quotes(value: str) -> str:
    text = str(value).strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    return text


@dataclass(frozen=True)
class CommandRunResult:
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


def _coerce_output(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def run_command(
    command: str,
    *,
    cwd: str | Path,
    timeout_ms: int,
    stdin: str | None = None,
) -> CommandRunResult:
    started = time.perf_counter()
    argv = parse_command_argv(command)
    try:
        completed = subprocess.run(
            argv,
            shell=False,
            cwd=str(cwd),
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(0.001, timeout_ms / 1000),
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        return CommandRunResult(
            status="completed" if completed.returncode == 0 else "failed",
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_ms=duration_ms,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return CommandRunResult(
            status="timed_out",
            exit_code=None,
            stdout=_coerce_output(exc.stdout),
            stderr=_coerce_output(exc.stderr),
            duration_ms=duration_ms,
            timed_out=True,
        )
