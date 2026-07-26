"""Synchronous command execution boundary for Agent built-ins.

走 shell 模式（``bash -c`` / ``cmd /c`` 包装命令串），对齐 claude code/codex——执行层
不拒管道/重定向/连接符，安全靠上游权限层（``builtin_permissions`` 分级审批）。超时走
psutil 递归终止整棵进程树（shell 是中间父，只杀直接子会留孙进程继续跑）。
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from src.execution.process_tree_utils import terminate_process_tree
from src.execution.shell_resolver import resolve_shell, shell_argv


class CommandParseError(ValueError):
    """Raised when a command has invalid quoting or an empty executable."""


def parse_command_argv(command: str) -> list[str]:
    """宽松 tokenize——只拒空命令和引号畸形，不再因 shell 元字符抛异常。

    供 ``command_path_policy_violation`` 的 inline-code/``..`` 穿越守卫用；shell 元字符
    不再单独设卡，命令经 shell 执行，注入防护靠 inline-code/``..`` 守卫 + OS 系统路径
    拒绝 + 默认确认链（OS 沙箱兜底为后续工作）。
    """
    raw = str(command or "").strip()
    if not raw:
        raise CommandParseError("Command must not be empty.")
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
    shell_path: str | None = None,
) -> CommandRunResult:
    started = time.perf_counter()
    resolved_shell = resolve_shell(configured=shell_path)
    argv = shell_argv(resolved_shell, command)
    proc = subprocess.Popen(
        argv,
        shell=False,
        cwd=str(cwd),
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = proc.communicate(
            input=stdin, timeout=max(0.001, timeout_ms / 1000),
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        return CommandRunResult(
            status="completed" if proc.returncode == 0 else "failed",
            exit_code=proc.returncode,
            stdout=stdout or "",
            stderr=stderr or "",
            duration_ms=duration_ms,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        # shell 是中间父进程，必须递归终止整棵树（否则真实命令变孤儿继续跑）
        terminate_process_tree(proc)
        duration_ms = int((time.perf_counter() - started) * 1000)
        return CommandRunResult(
            status="timed_out",
            exit_code=None,
            stdout=_coerce_output(exc.stdout),
            stderr=_coerce_output(exc.stderr),
            duration_ms=duration_ms,
            timed_out=True,
        )
