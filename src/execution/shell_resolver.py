"""Shell 二进制发现——给 exec 工具的命令串找一个 shell 解释器。

对齐 claude code（Git Bash）/ codex（PowerShell/cmd）的 shell 模式：命令串作为单一 argv
喂给 shell 二进制（``bash -c`` / ``cmd /c``），由 shell 解释管道/重定向/连接符，执行层
不再用字符黑名单硬拒。

发现链：配置显式 → ``shutil.which("bash")`` → Windows 常见 Git for Windows 路径 →
``cmd.exe``（Windows）/ ``/bin/sh``（POSIX）回退。**不禁 exec**——回退时 ``logger.warning``：
cmd / sh 配合权限层（元字符走确认不短路、OS 路径硬拒）仍可兜底。
"""

from __future__ import annotations

import logging
import os
import shutil
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Windows 上 Git for Windows 的常见 bash 安装路径（按优先级）
_WINDOWS_BASH_CANDIDATES = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
    rf"{os.environ.get('LOCALAPPDATA', '')}\\Programs\\Git\\bin\\bash.exe",
)


@lru_cache(maxsize=1)
def resolve_shell(*, configured: str | None = None) -> str:
    """返回 shell 二进制绝对路径。

    优先级：configured 显式（不存在抛 RuntimeError）→ PATH 上的 bash → Windows 常见
    Git for Windows 路径 → cmd.exe（Windows）/ /bin/sh（POSIX）回退。回退（非 bash）
    时 logger.warning。
    """
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path)
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        raise RuntimeError(f"配置的 shell 路径不存在: {configured}")

    # 1) PATH 上的 bash（Git Bash 通常在 PATH）
    bash_on_path = shutil.which("bash")
    if bash_on_path:
        return bash_on_path

    if os.name == "nt":
        # 2) Windows 常见 Git for Windows 路径
        for candidate in _WINDOWS_BASH_CANDIDATES:
            if candidate and Path(candidate).is_file():
                return candidate
        # 3) 回退 cmd.exe
        cmd = shutil.which("cmd") or r"C:\Windows\System32\cmd.exe"
        logger.warning(
            "[shell_resolver] 未找到 Git Bash，exec 回退到 cmd.exe（%s）。"
            "建议安装 Git for Windows 或配置 agent_tools.process.shell_path。",
            cmd,
        )
        return cmd

    # POSIX 回退 /bin/sh
    sh = shutil.which("sh") or "/bin/sh"
    logger.warning("[shell_resolver] 未找到 bash，exec 回退到 %s。", sh)
    return sh


def shell_kind(shell_path: str) -> str:
    """返回 shell 种类标签（用于选 invocation 形式）：bash/sh/cmd/pwsh。"""
    name = Path(shell_path).name.lower()
    if "bash" in name:
        return "bash"
    if name in ("sh", "sh.exe"):
        return "sh"
    if "cmd" in name:
        return "cmd"
    if "pwsh" in name or "powershell" in name:
        return "pwsh"
    return "sh"  # 默认 posix 语义


def shell_argv(shell_path: str, command: str) -> list[str]:
    """构造 shell 包装 argv：``[shell, flag, command]``，命令串作单一 argv 防二次拆分。"""
    kind = shell_kind(shell_path)
    if kind == "cmd":
        return [shell_path, "/c", command]
    if kind == "pwsh":
        return [shell_path, "-Command", command]
    # bash / sh
    return [shell_path, "-c", command]
