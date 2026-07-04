"""proposal_workspace — git worktree 生命周期管理。

为改进提案的自动实施提供隔离工作区：每个提案一个独立 git worktree + 特性分支，
执行体在其中改源码、跑测试，主工作区不受影响。

布局：``<repo_root>/.worktrees/improvement/<proposal_id>``
分支：``improvement/<proposal_id>`` from HEAD

安全边界（spec edge case）：
- 目标路径已存在（脏残留）→ 拒绝复用，抛 ProposalWorkspaceDirty
- git 命令失败 → 抛 ProposalWorkspaceError，由桥接转 mark_failed

本模块同时承载 FR-014 的两条爆炸半径硬门卫（fail-closed），由 ``builtin_permissions``
在执行体工具权限层调用：
- ``check_improvement_workspace_mutation``：(a) 只允许隔离 worktree 内的源码/测试/文档
  改动，拒绝改写 self_improvement / task_collaboration / agents / orchestration /
  desktop_api / src-tauri / guardrail 测试 / legacy 与启动入口 / secret / 配置 / DB / 依赖产物。
- ``check_improvement_exec_command``：(b) exec 限定测试/lint/format-check/typecheck 用途，
  拒绝网络、包安装、破坏型 git、merge/rebase/reset/push 等非测试型命令。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from src.utils.proposal_policy import (
    IMPROVEMENT_DIR,
    WORKTREES_DIR,
    improvement_worktree_branch_name,
    is_improvement_workspace_root as _is_improvement_workspace_root,
)

logger = logging.getLogger(__name__)

_SOURCE_EXTENSIONS = frozenset(
    {
        ".bat",
        ".css",
        ".html",
        ".js",
        ".jsx",
        ".json",
        ".md",
        ".ps1",
        ".py",
        ".rs",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)

_NON_SOURCE_DIRS = frozenset(
    {
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        WORKTREES_DIR,
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "playwright-report",
        "target",
        "test-results",
        "venv",
    }
)

_NON_SOURCE_SUFFIXES = frozenset(
    {
        ".db",
        ".duckdb",
        ".exe",
        ".ico",
        ".jpeg",
        ".jpg",
        ".log",
        ".mp4",
        ".png",
        ".sqlite",
        ".webp",
    }
)

_FORBIDDEN_CORE_PREFIXES = frozenset(
    {
        "src/business/self_improvement/",
        "src/business/task_collaboration/",
        "src/business/agents/",
        "src/business/orchestration/",
        "src/desktop_api/",
        "tests/guardrails/",
        "src-tauri/",
    }
)

_FORBIDDEN_CORE_FILES = frozenset(
    {
        "mexemplar_gui.bat",
        "mexemplar_gui.py",
        "src/desktop_api/app.py",
        "src/main.py",
        "start.bat",
    }
)

# Secret/凭证文件：proposal 执行体不得改写，CLAUDE.md 明确 secret 存 app_settings。
_SECRET_BEARING_FILES = frozenset(
    {
        "app_settings.json",
        "settings.json",
        "secrets.json",
        "credentials.json",
        "local.settings.json",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
    }
)

_SECRET_BEARING_SUFFIXES = frozenset(
    {
        ".key",
        ".pem",
        ".p12",
        ".pfx",
        ".crt",
        ".cer",
        ".keystore",
    }
)

_DENIED_EXECUTABLES = frozenset(
    {
        "curl",
        "curl.exe",
        "del",
        "git",
        "git.exe",
        "iwr",
        "irm",
        "pip",
        "pip.exe",
        "pip3",
        "pip3.exe",
        "rm",
        "rmdir",
        "wget",
        "wget.exe",
    }
)

_PACKAGE_MANAGER_WORDS = frozenset(
    {
        "npm",
        "npm.cmd",
        "npm.exe",
        "pip",
        "pip.exe",
        "pip3",
        "pip3.exe",
        "pnpm",
        "pnpm.cmd",
        "pnpm.exe",
        "yarn",
        "yarn.cmd",
        "yarn.exe",
    }
)
_PACKAGE_INSTALL_WORDS = frozenset({"add", "ci", "i", "install"})

_TEST_EXEC_HINTS = frozenset(
    {
        "black",
        "check",
        "clippy",
        "eslint",
        "flake8",
        "lint",
        "mypy",
        "pytest",
        "ruff",
        "test",
        "tests",
        "tsc",
        "typecheck",
        "vitest",
    }
)
_MUTATING_FIX_FLAGS = frozenset({"--fix", "--fix-only", "--unsafe-fixes", "--write"})
_BLACK_CHECK_FLAGS = frozenset({"--check", "--diff"})
_RUFF_FORMAT_CHECK_FLAGS = frozenset({"--check", "--diff"})
_FIXABLE_LINTERS = frozenset({"eslint", "ruff"})


class ProposalWorkspaceError(Exception):
    """git worktree 操作失败。"""


class ProposalWorkspaceDirty(ProposalWorkspaceError):
    """目标 worktree 路径已存在（脏残留），拒绝复用。"""


def resolve_repo_root() -> Path:
    """定位当前仓库根目录（在 worktree 内即该 worktree 根）。

    从当前文件向上查找含 ``.git`` 的目录；若未命中则用
    ``git rev-parse --show-toplevel`` 兜底（在 worktree 内返回该 worktree 根，
    而非主仓库根——本函数需要的是创建 ``.worktrees/improvement/<id>`` 的基准目录）。
    """
    # 当前文件在 src/business/self_improvement/ 下：
    # parents[0]=self_improvement, [1]=business, [2]=src, [3]=仓库根
    candidate = Path(__file__).resolve().parents[3]
    if (candidate / ".git").exists():
        return candidate
    # fallback: git rev-parse
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return Path(result.stdout.strip())
    except subprocess.TimeoutExpired as exc:
        raise ProposalWorkspaceError("git rev-parse --show-toplevel 超时 (>{10}s)") from exc
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ProposalWorkspaceError(f"无法定位仓库根: {exc}") from exc


def _worktree_dir(repo_root: Path, proposal_id: str) -> Path:
    """计算 worktree 目录路径。使用 proposal_policy 的目录常量。"""
    return repo_root / WORKTREES_DIR / IMPROVEMENT_DIR / proposal_id


def _branch_name(proposal_id: str) -> str:
    """计算特性分支名。委托给 proposal_policy 的唯一真实来源。"""
    return improvement_worktree_branch_name(proposal_id)


# 向后兼容别名：外部调用方仍可从 proposal_workspace 导入。
is_improvement_workspace_root = _is_improvement_workspace_root


def check_improvement_workspace_mutation(
    path: Path | str,
    *,
    workspace_root: Path | str,
    operation: str,
) -> str | None:
    """Return a denial reason for unsafe writes inside proposal worktrees.

    The normal Agent workspace policy already rejects outside-workspace paths.
    This guard narrows self-improvement worktrees further: proposal executors may
    edit source/test/docs in their isolated branch, but not project governance,
    self-improvement orchestration, task-collaboration scheduling, startup
    paths, runtime data, caches, dependency folders, or binary artifacts.
    """
    if operation.lower() not in {"write", "edit", "delete", "patch"}:
        return None
    if not is_improvement_workspace_root(workspace_root):
        return None

    root = Path(workspace_root).expanduser().resolve(strict=False)
    target = Path(path).expanduser().resolve(strict=False)
    try:
        relative = target.relative_to(root).as_posix()
    except ValueError:
        return "self-improvement proposals may only mutate their isolated worktree."

    normalized = relative.lower()
    if normalized in _FORBIDDEN_CORE_FILES or any(
        normalized.startswith(prefix) for prefix in _FORBIDDEN_CORE_PREFIXES
    ):
        return (
            "self-improvement proposals may not modify self-improvement, "
            "task-collaboration, agent/orchestration, desktop API, Tauri, "
            "guardrail test, or startup core paths."
        )

    parts = [part.lower() for part in Path(relative).parts]
    if any(part in _NON_SOURCE_DIRS for part in parts):
        return (
            "self-improvement proposals may not mutate generated, dependency, cache, or VCS paths."
        )

    name = Path(relative).name.lower()
    suffix = Path(relative).suffix.lower()
    if (
        name.startswith(".env")
        or name == "config.json"
        or name in _SECRET_BEARING_FILES
        or suffix in _SECRET_BEARING_SUFFIXES
    ):
        return (
            "self-improvement proposals may not mutate local config, env, or secret-bearing files."
        )
    if suffix in _NON_SOURCE_SUFFIXES:
        return "self-improvement proposals may only mutate source, test, or documentation files."
    if suffix and suffix not in _SOURCE_EXTENSIONS:
        return "self-improvement proposals may only mutate recognized source, test, or documentation files."
    return None


def check_improvement_exec_command(
    command: str,
    *,
    workspace_root: Path | str,
    base_dir: Path | str | None = None,
) -> str | None:
    """Return a denial reason for unsafe exec inside proposal worktrees."""
    if not is_improvement_workspace_root(workspace_root):
        return None

    from src.execution.command_runner import CommandParseError, parse_command_argv

    try:
        tokens = parse_command_argv(command)
    except CommandParseError as exc:
        return str(exc)
    if not tokens:
        return "empty commands are not allowed in self-improvement worktrees."

    lowered = [token.lower() for token in tokens]
    executable = Path(lowered[0]).name
    if executable in _DENIED_EXECUTABLES:
        return "self-improvement proposal exec is limited to test, lint, and type-check commands."

    if _contains_denied_exec_pattern(lowered):
        return "network, package installation, destructive git, and merge commands are denied."

    command_words = {_command_word(token) for token in lowered}
    if not command_words.intersection(_TEST_EXEC_HINTS):
        return "self-improvement proposal exec must be test, lint, format-check, or type-check oriented."
    if "black" in command_words and not command_words.intersection(_BLACK_CHECK_FLAGS):
        return "black is only allowed in non-mutating --check or --diff mode."
    if "ruff" in command_words and command_words.intersection(_MUTATING_FIX_FLAGS):
        return "ruff fix modes are not allowed in self-improvement proposal exec."
    if "ruff" in command_words and "format" in command_words:
        if not command_words.intersection(_RUFF_FORMAT_CHECK_FLAGS):
            return "ruff format is only allowed in non-mutating --check or --diff mode."
    if command_words.intersection(_FIXABLE_LINTERS) and command_words.intersection(
        _MUTATING_FIX_FLAGS
    ):
        return "lint fix/write modes are not allowed in self-improvement proposal exec."

    # Path containment is enforced by the generic built-in command policy.  This
    # function intentionally leaves base_dir unused beyond the signature so the
    # caller can pass the same context as other workspace policies.
    _ = base_dir
    return None


def _command_word(token: str) -> str:
    name = Path(token).name.lower()
    for suffix in (".exe", ".cmd"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _contains_denied_exec_pattern(tokens: list[str]) -> bool:
    words = [_command_word(token) for token in tokens]
    if any(
        word in _DENIED_EXECUTABLES and _looks_like_command_token(token)
        for token, word in zip(tokens, words)
    ):
        return True
    if any("://" in token for token in tokens):
        return True
    for index, word in enumerate(words):
        if (
            word in _PACKAGE_MANAGER_WORDS
            and _looks_like_command_token(tokens[index])
            and any(later in _PACKAGE_INSTALL_WORDS for later in words[index + 1 :])
        ):
            return True
    return False


def _looks_like_command_token(token: str) -> bool:
    return not any(separator in token for separator in ("/", "\\", ":"))


def create_worktree(proposal_id: str) -> tuple[Path, str]:
    """为提案创建隔离 git worktree + 特性分支。

    Returns:
        (worktree 绝对路径, 分支名)

    Raises:
        ProposalWorkspaceDirty: 目标路径已存在
        ProposalWorkspaceError: git 命令失败
    """
    repo_root = resolve_repo_root()
    wt_dir = _worktree_dir(repo_root, proposal_id)
    branch = _branch_name(proposal_id)

    # 脏残留检查
    if wt_dir.exists():
        raise ProposalWorkspaceDirty("worktree 路径已存在，拒绝复用")

    # 确保父目录存在
    wt_dir.parent.mkdir(parents=True, exist_ok=True)

    # git worktree add -b <branch> <path> HEAD
    cmd = [
        "git",
        "-C",
        str(repo_root),
        "worktree",
        "add",
        "-b",
        branch,
        str(wt_dir),
        "HEAD",
    ]
    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        raise ProposalWorkspaceError(
            f"git worktree add 失败 (rc={exc.returncode}): "
            f"{exc.stderr.strip() or exc.stdout.strip()}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProposalWorkspaceError("git worktree add 超时 (>{30}s)") from exc
    except FileNotFoundError as exc:
        raise ProposalWorkspaceError("git 命令不可用") from exc

    logger.info(
        "Created improvement worktree: proposal=%s branch=%s",
        proposal_id,
        branch,
    )
    return wt_dir.resolve(), branch


def remove_worktree(worktree_path: Path | str) -> None:
    """移除 git worktree 及其特性分支（容错：目录不存在仍清理残留分支）。

    用于提案拒绝/失败后的清理（FR-016 / T027）。分支清理与目录清理解耦:
    即便前次调用已删掉目录（git worktree remove 成功）但分支删除未完成,
    本次调用仍会清理 ``improvement/<proposal_id>`` 孤儿分支,避免长期运行后
    分支无界膨胀。
    """
    wt_path = Path(worktree_path).resolve()
    proposal_id = _proposal_id_from_worktree_path(wt_path)
    repo_root = resolve_repo_root()

    # 目录清理:仅当目录存在时执行。目录不存在（前次清理已删）则跳过本块,
    # 但下面的分支清理仍会执行,避免孤儿分支泄漏。
    if wt_path.exists():
        # git worktree remove --force <path>
        try:
            subprocess.run(
                ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(wt_path)],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "git worktree remove 失败 (rc=%d): %s; 尝试强制清理目录",
                exc.returncode,
                exc.stderr.strip(),
            )
        except subprocess.TimeoutExpired:
            logger.warning("git worktree remove 超时 (>%ds); 尝试强制清理目录", 15)
        except FileNotFoundError as exc:
            raise ProposalWorkspaceError("git 命令不可用，无法可靠移除 worktree") from exc

        if wt_path.exists():
            try:
                shutil.rmtree(wt_path)
            except OSError as exc:
                raise ProposalWorkspaceError("无法删除 worktree 目录") from exc
        if wt_path.exists():
            raise ProposalWorkspaceError("worktree 目录仍然存在")
    else:
        logger.info("Worktree directory already removed: proposal=%s", proposal_id or "unknown")

    # 分支清理:无论目录状态都尝试（解耦）,避免孤儿分支永久泄漏。
    if proposal_id:
        branch = _branch_name(proposal_id)
        try:
            subprocess.run(
                ["git", "-C", str(repo_root), "branch", "-D", "--", branch],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            logger.info("Deleted improvement branch: %s", branch)
        except subprocess.CalledProcessError as exc:
            if _branch_exists(repo_root, branch):
                raise ProposalWorkspaceError(f"无法删除 improvement 分支: {branch}") from exc
            logger.debug("Branch %s already removed or not found", branch)
        except subprocess.TimeoutExpired:
            if _branch_exists(repo_root, branch):
                raise ProposalWorkspaceError(
                    f"git branch -D 超时;无法清理 improvement 分支: {branch}"
                )
            logger.debug("Branch %s cleanup timed out but already removed", branch)
        except FileNotFoundError as exc:
            raise ProposalWorkspaceError("git 命令不可用，无法确认分支清理") from exc

    logger.info("Removed improvement worktree: proposal=%s", proposal_id or "unknown")


def _proposal_id_from_worktree_path(path: Path) -> str | None:
    # path.parts 对 Path 总返回 tuple,不会抛;收窄掉宽 except 以免掩盖意外 bug(026 M4)。
    parts = path.parts
    improvement_index = len(parts) - 2
    if (
        improvement_index >= 1
        and parts[improvement_index].lower() == IMPROVEMENT_DIR
        and parts[improvement_index - 1].lower() == WORKTREES_DIR
    ):
        return parts[improvement_index + 1]
    return None


def _branch_exists(repo_root: Path, branch: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", "--", branch],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
