"""Safe execution adapters for external coding quota probes."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SafeQuotaSnapshot:
    """Normalized, secret-free quota data returned to the business layer."""

    source: str
    usage_percents: tuple[int, ...]
    reset_epochs: tuple[int, ...] = ()
    reached: bool = False
    confidence: float = 0.0


class ExternalCodingQuotaRunner:
    """Query supported CLIs while discarding their raw account responses."""

    def probe_claude(self, command: str, *, timeout_seconds: int) -> SafeQuotaSnapshot | None:
        executable = _resolve_command(command)
        if executable is None:
            return None
        try:
            result = subprocess.run(
                [
                    executable,
                    "--safe-mode",
                    "-p",
                    "/usage",
                    "--output-format",
                    "json",
                    "--max-budget-usd",
                    "0.0001",
                ],
                cwd=str(Path.home()),
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=timeout_seconds,
                check=False,
                **_hidden_process_kwargs(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return _parse_claude_usage_output(result.stdout)

    def probe_codex(self, command: str, *, timeout_seconds: int) -> SafeQuotaSnapshot | None:
        executable = _resolve_command(command)
        if executable is None:
            return None
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                [executable, "app-server", "--stdio"],
                cwd=str(Path.home()),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **_hidden_process_kwargs(),
            )
            if process.stdin is None or process.stdout is None:
                return None
            output: queue.Queue[str] = queue.Queue()
            threading.Thread(
                target=_read_lines,
                args=(process.stdout, output),
                daemon=True,
                name="external-coding-codex-quota-reader",
            ).start()
            deadline = time.monotonic() + timeout_seconds
            _send_request(
                process,
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "mexemplar-external-coding",
                            "version": "1.0",
                        }
                    },
                },
            )
            if _wait_for_response(output, request_id=1, deadline=deadline) is None:
                return None
            _send_request(
                process,
                {"id": 2, "method": "account/rateLimits/read", "params": {}},
            )
            response = _wait_for_response(output, request_id=2, deadline=deadline)
            return _parse_codex_rate_limits_response(response)
        except (OSError, ValueError, TypeError):
            return None
        finally:
            _stop_process(process)


def _resolve_command(command: str) -> str | None:
    value = (command or "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_file():
        return str(path.resolve())
    return shutil.which(value)


def _hidden_process_kwargs() -> dict[str, int]:
    if os.name != "nt":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def _parse_claude_usage_output(raw_output: str) -> SafeQuotaSnapshot | None:
    payload: dict[str, Any] | None = None
    for line in reversed((raw_output or "").splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("type") == "result":
            payload = candidate
            break
    if payload is None or payload.get("is_error") is True:
        return None
    text = payload.get("result")
    if not isinstance(text, str):
        return None
    percentages = tuple(
        _bounded_percent(match)
        for match in re.findall(
            r"Current (?:session|week[^:]*):\s*(\d{1,3})%\s+used",
            text,
            flags=re.IGNORECASE,
        )
    )
    if not percentages:
        return None
    lowered = text.lower()
    return SafeQuotaSnapshot(
        source="claude_usage_command",
        usage_percents=percentages,
        reached="limit reached" in lowered or any(value >= 100 for value in percentages),
        confidence=0.9,
    )


def _parse_codex_rate_limits_response(response: dict[str, Any] | None) -> SafeQuotaSnapshot | None:
    if not isinstance(response, dict):
        return None
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    by_id = result.get("rateLimitsByLimitId")
    snapshot = by_id.get("codex") if isinstance(by_id, dict) else None
    if not isinstance(snapshot, dict):
        snapshot = result.get("rateLimits")
    if not isinstance(snapshot, dict):
        return None

    percentages: list[int] = []
    reset_epochs: list[int] = []
    for key in ("primary", "secondary"):
        window = snapshot.get(key)
        if not isinstance(window, dict):
            continue
        used_percent = window.get("usedPercent")
        if isinstance(used_percent, (int, float)):
            percentages.append(_bounded_percent(used_percent))
        resets_at = window.get("resetsAt")
        if isinstance(resets_at, (int, float)) and resets_at > 0:
            reset_epochs.append(int(resets_at))
    if not percentages:
        return None
    return SafeQuotaSnapshot(
        source="codex_app_server",
        usage_percents=tuple(percentages),
        reset_epochs=tuple(reset_epochs),
        reached=bool(snapshot.get("rateLimitReachedType"))
        or any(value >= 100 for value in percentages),
        confidence=0.95,
    )


def _bounded_percent(value: Any) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 0


def _read_lines(stream, output: queue.Queue[str]) -> None:
    for line in stream:
        output.put(line)


def _send_request(process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    if process.stdin is None:
        raise ValueError("quota probe stdin is unavailable")
    process.stdin.write(json.dumps(payload, ensure_ascii=True) + "\n")
    process.stdin.flush()


def _wait_for_response(
    output: queue.Queue[str], *, request_id: int, deadline: float
) -> dict[str, Any] | None:
    while time.monotonic() < deadline:
        remaining = max(0.01, deadline - time.monotonic())
        try:
            line = output.get(timeout=min(0.25, remaining))
        except queue.Empty:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("id") == request_id:
            return payload
    return None


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
