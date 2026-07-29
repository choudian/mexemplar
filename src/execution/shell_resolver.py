"""Shell 二进制发现——给 exec 工具的命令串找一个 shell 解释器。

对齐 claude code（Git Bash）/ codex（PowerShell/cmd）的 shell 模式：命令串作为单一 argv
喂给 shell 二进制（``bash -c`` / ``cmd /c``），由 shell 解释管道/重定向/连接符，执行层
不再用字符黑名单硬拒。

发现链：配置显式 → Windows 常见 Git for Windows 路径 → PATH 中 git.exe 旁的 bash
→ 非 WSL 的 PATH bash → ``cmd.exe``（Windows）/ PATH bash → ``/bin/sh``（POSIX）
回退。**不禁 exec**——回退时 ``logger.warning``：cmd / sh 配合权限层（元字符走确认
不短路、OS 路径硬拒）仍可兜底。
"""

from __future__ import annotations

import logging
import os
import shutil
from functools import lru_cache
from pathlib import Path, PureWindowsPath

logger = logging.getLogger(__name__)

# Windows 上 Git for Windows 的常见 bash 安装路径（按优先级）
_WINDOWS_BASH_CANDIDATES = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
    rf"{os.environ.get('LOCALAPPDATA', '')}\\Programs\\Git\\bin\\bash.exe",
)


def _is_windows_wsl_bash(path: str) -> bool:
    """识别 Windows 自带的 WSL bash 启动器，而不是 Git for Windows bash。"""
    normalized = str(PureWindowsPath(path)).replace("/", "\\").casefold().rstrip("\\")
    return normalized.endswith(
        (
            r"\windows\system32\bash.exe",
            r"\windows\sysnative\bash.exe",
            r"\microsoft\windowsapps\bash.exe",
        )
    )


def _find_bash_beside_git(git_path: str | None) -> str | None:
    """从 PATH 上的 git.exe 反查非默认安装位置中的 Git Bash。"""
    if not git_path:
        return None
    git_dir = Path(git_path).parent
    install_root = git_dir.parent if git_dir.name.casefold() in {"cmd", "bin"} else git_dir
    for candidate in (
        install_root / "bin" / "bash.exe",
        install_root / "usr" / "bin" / "bash.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


@lru_cache(maxsize=1)
def resolve_shell(*, configured: str | None = None) -> str:
    """返回 shell 二进制绝对路径。

    优先级：configured 显式（不存在抛 RuntimeError）→ Windows 常见 Git for Windows
    路径 → PATH 中 git.exe 旁的 bash → PATH 上非 WSL 的 bash → cmd.exe（Windows）/
    PATH bash → /bin/sh（POSIX）回退。回退（非 bash）时 logger.warning。
    """
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path)
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        raise RuntimeError(f"配置的 shell 路径不存在: {configured}")

    if os.name == "nt":
        # Windows 的 System32 bash.exe 是 WSL 启动器。先找 Git for Windows 的已知
        # 安装位置，避免打包 sidecar 继承系统 PATH 时误把命令送进 WSL。
        for candidate in _WINDOWS_BASH_CANDIDATES:
            if candidate and Path(candidate).is_file():
                return candidate

        bash_beside_git = _find_bash_beside_git(shutil.which("git"))
        if bash_beside_git:
            return bash_beside_git

        bash_on_path = shutil.which("bash")
        if bash_on_path and not _is_windows_wsl_bash(bash_on_path):
            return bash_on_path

        # 未找到可用的 Git Bash；宁可退回 cmd，也不能把 Windows 路径/命令交给 WSL。
        cmd = shutil.which("cmd") or r"C:\Windows\System32\cmd.exe"
        logger.warning(
            "[shell_resolver] 未找到 Git Bash，exec 回退到 cmd.exe（%s）。"
            "建议安装 Git for Windows 或配置 agent_tools.process.shell_path。",
            cmd,
        )
        return cmd

    bash_on_path = shutil.which("bash")
    if bash_on_path:
        return bash_on_path

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
