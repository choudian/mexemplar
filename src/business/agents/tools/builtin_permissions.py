"""Workspace and confirmation safety helpers for built-in Agent tools."""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.business.agents.tools.builtin_contracts import (
    PermissionDecision,
    runtime_workspace_root,
)
from src.execution.command_runner import CommandParseError, parse_command_argv
from src.utils.workspace import resolve_workspace_root, workspace_hash

_SUMMARY_SNIPPET_MAX = 80
_SUMMARY_TOTAL_MAX = 240

_SENSITIVE_PATTERNS = [
    re.compile(r"(?<!\w)sk-[A-Za-z0-9_\-]{8,}", re.IGNORECASE),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{12,}"),
]
_PARENT_PATH_SEGMENT_PATTERN = re.compile(r"(?:^|[\\/])\.\.(?:$|[\\/])")
_EMBEDDED_PARENT_PATH_SEGMENT_PATTERN = re.compile(r"(?<![\w.+-])\.\.(?![\w.+-])")

# Compact path options have no generic value delimiter. Keep this list to
# established path-taking forms so arbitrary data such as ``--label=foo..``
# is never guessed to be a traversal target.
_COMPACT_DASH_PATH_OPTION_PREFIXES = (
    "-idirafter",
    "-isystem",
    "-iquote",
    "-include",
    "-imacros",
    "-MF",
    "-MJ",
    "-MT",
    "-MQ",
    "-C",
    "-I",
    "-L",
    "-o",
    "-B",
    "-F",
)
_COMPACT_WINDOWS_PATH_OPTION_PREFIXES = (
    "/external:i",
    "/winsysroot",
    "/imsvc",
    "/ai",
    "/fu",
    "/fi",
    "/fo",
    "/fd",
    "/fe",
    "/fa",
    "/fp",
    "/fr",
    "/i",
)
_SEPARATED_DASH_PATH_OPTIONS = frozenset(
    {
        "-C",
        "-I",
        "-L",
        "-o",
        "-B",
        "-F",
        "-idirafter",
        "-isystem",
        "-iquote",
        "-include",
        "-imacros",
        "-MF",
        "-MJ",
        "--target",
        "--path",
        "--directory",
        "--output",
        "--prefix",
        "--root",
        "--cwd",
        "--file",
        "--config",
    }
)
_SEPARATED_CASE_INSENSITIVE_PATH_OPTIONS = frozenset(
    {"-path", "-literalpath", "-destination", "-filepath", "-workingdirectory"}
)
_SEPARATED_WINDOWS_PATH_OPTIONS = frozenset(
    {"/i", "/ai", "/fu", "/fi", "/fo", "/fd", "/fe", "/fa", "/fp", "/fr"}
)

_SYSTEM_ROOTS = [
    Path("C:/Windows"),
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
    Path("/etc"),
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
]

_RESOLVED_SYSTEM_ROOTS: list[Path] = [r.resolve(strict=False) for r in _SYSTEM_ROOTS]

SAFE_EXEC_COMMANDS = frozenset(
    {
        "python --version",
        "python3 --version",
        "pip list",
        "pip3 list",
        "whoami",
        "hostname",
        "tasklist",
        "ps",
    }
)
_SHELL_HOST_NAMES = frozenset(
    {
        "bash",
        "cmd",
        "cmd.exe",
        "cscript",
        "cscript.exe",
        "dash",
        "fish",
        "ksh",
        "powershell",
        "powershell.exe",
        "pwsh",
        "sh",
        "wscript",
        "wscript.exe",
        "wsl",
        "zsh",
    }
)
_ALL_ARGUMENT_DATA_EXECUTABLES = frozenset({"echo", "echo.exe", "printf"})
_PATTERN_EXECUTABLES = frozenset(
    {
        "egrep",
        "fgrep",
        "findstr",
        "findstr.exe",
        "grep",
        "grep.exe",
        "rg",
        "rg.exe",
        "ripgrep",
    }
)
_PATTERN_VALUE_FLAGS = frozenset({"-e", "--regexp"})
_PATTERN_FILE_FLAGS = frozenset({"-f", "--file"})
_GREP_EXECUTABLES = frozenset({"egrep", "fgrep", "grep", "grep.exe"})
_RG_EXECUTABLES = frozenset({"rg", "rg.exe", "ripgrep"})
_GREP_AUX_VALUE_FLAGS = frozenset(
    {
        "-A",
        "--after-context",
        "-B",
        "--before-context",
        "-C",
        "--context",
        "-m",
        "--max-count",
        "-d",
        "--directories",
        "-D",
        "--devices",
        "--exclude",
        "--exclude-from",
        "--exclude-dir",
        "--include",
        "--label",
        "--binary-files",
    }
)
_RG_AUX_VALUE_FLAGS = frozenset(
    {
        "-A",
        "--after-context",
        "-B",
        "--before-context",
        "-C",
        "--context",
        "-m",
        "--max-count",
        "-g",
        "--glob",
        "-t",
        "--type",
        "-T",
        "--type-not",
        "-j",
        "--threads",
        "--max-depth",
        "--encoding",
        "--engine",
        "--sort",
        "--sortr",
        "--type-add",
        "--type-clear",
        "-r",
        "--replace",
        "--pre",
        "--pre-glob",
        "--path-separator",
    }
)
_INLINE_CODE_FLAGS = {
    "node": {"-e", "--eval", "-p", "--print"},
    "node.exe": {"-e", "--eval", "-p", "--print"},
    "perl": {"-e"},
    "perl.exe": {"-e"},
    "php": {"-r"},
    "php.exe": {"-r"},
    "py": {"-c"},
    "py.exe": {"-c"},
    "python": {"-c"},
    "python.exe": {"-c"},
    "python3": {"-c"},
    "python3.exe": {"-c"},
    "ruby": {"-e"},
    "ruby.exe": {"-e"},
}

_confirmed_external_reads: set[tuple[str, str, str]] = set()
_confirmed_external_reads_lock = threading.Lock()
# workspace 外写的本会话确认缓存（镜像读：pre_hook 确认后 mark，permission_for_path 后续返回 confirmed）。
# 文件级粒度（与读一致）；allow_all 关时每个外部文件首次写走确认，确认后本会话同文件不再问。
_confirmed_external_writes: set[tuple[str, str, str]] = set()
_confirmed_external_writes_lock = threading.Lock()


@dataclass(frozen=True)
class PathClassification:
    requested: str
    resolved: Path
    workspace_root: Path
    display_path: str
    scope: str
    hidden: bool
    system: bool
    linked_external: bool

    @property
    def inside_workspace(self) -> bool:
        return self.scope == "workspace"


@dataclass(frozen=True)
class PermissionCheck:
    classification: PathClassification
    decision: PermissionDecision
    error_code: str | None = None
    message: str | None = None

    @property
    def allowed(self) -> bool:
        return self.decision.decision in {"allowed", "confirmed"}


def _resolve_candidate(path: str | Path, workspace_root: Path) -> tuple[Path, Path]:
    raw = Path(path).expanduser()
    lexical = raw if raw.is_absolute() else workspace_root / raw
    try:
        resolved = lexical.resolve(strict=False)
    except OSError:
        resolved = lexical.absolute()
    return lexical, resolved


def _is_hidden(path: Path, workspace_root: Path) -> bool:
    try:
        rel_parts = path.relative_to(workspace_root).parts
    except ValueError:
        rel_parts = path.parts
    return any(part.startswith(".") and part not in {".", ".."} for part in rel_parts)


def _is_system_path(path: Path) -> bool:
    for root in _RESOLVED_SYSTEM_ROOTS:
        try:
            if path.is_relative_to(root):
                return True
        except OSError:
            continue
    return False


def _has_symlink_component(path: Path, stop_at: Path) -> bool:
    current = path
    candidates: list[Path] = []
    while current != current.parent:
        candidates.append(current)
        if current == stop_at:
            break
        current = current.parent
    return any(candidate.exists() and candidate.is_symlink() for candidate in candidates)


def display_path(path: Path, workspace_root: Path) -> str:
    try:
        return path.relative_to(workspace_root).as_posix() or "."
    except ValueError:
        return str(path)


def classify_path(
    path: str | Path,
    *,
    workspace_root: Path | str | None = None,
) -> PathClassification:
    # workspace_root 未显式传入时，用当前 tool runtime context 的 root（注入值）；
    # ContextVar 未设时 runtime_workspace_root() 回退 cwd，与历史行为一致。这让
    # pre_hook（不传 root）与 handler（显式传 root）用同一个 workspace，否则注入的
    # workspace 重定向在 pre_hook 层失效（FR-014a 承重假设）。
    root = (
        runtime_workspace_root()
        if workspace_root is None
        else resolve_workspace_root(workspace_root)
    )
    lexical, resolved = _resolve_candidate(path, root)
    lexical_inside = lexical.resolve(strict=False).is_relative_to(root)
    resolved_inside = resolved.is_relative_to(root)
    linked_external = lexical_inside and not resolved_inside
    system = _is_system_path(resolved)
    hidden = _is_hidden(resolved, root)
    if resolved_inside:
        scope = "workspace"
    elif linked_external:
        scope = "linked_external"
    elif system:
        scope = "system"
    elif hidden:
        scope = "hidden"
    else:
        scope = "external"
    if _has_symlink_component(lexical, root) and not resolved_inside:
        scope = "linked_external"
        linked_external = True
    return PathClassification(
        requested=str(path),
        resolved=resolved,
        workspace_root=root,
        display_path=display_path(resolved, root),
        scope=scope,
        hidden=hidden,
        system=system,
        linked_external=linked_external,
    )


def mark_external_read_confirmed(
    path: str | Path,
    workspace_root: Path | str | None = None,
    *,
    session_id: str | None = None,
) -> None:
    cls = classify_path(path, workspace_root=workspace_root)
    with _confirmed_external_reads_lock:
        _confirmed_external_reads.add(_external_read_key(cls, session_id=session_id))


def clear_external_read_confirmations_for_tests() -> None:
    with _confirmed_external_reads_lock:
        _confirmed_external_reads.clear()


def _external_read_key(
    cls: PathClassification, *, session_id: str | None = None
) -> tuple[str, str, str]:
    sid = (session_id or "_default_agent_session").strip() or "_default_agent_session"
    return (sid, workspace_hash(cls.workspace_root), str(cls.resolved))


def _is_external_read_confirmed(cls: PathClassification, *, session_id: str | None = None) -> bool:
    with _confirmed_external_reads_lock:
        return _external_read_key(cls, session_id=session_id) in _confirmed_external_reads


def mark_external_write_confirmed(
    path: str | Path,
    workspace_root: Path | str | None = None,
    *,
    session_id: str | None = None,
) -> None:
    cls = classify_path(path, workspace_root=workspace_root)
    with _confirmed_external_writes_lock:
        _confirmed_external_writes.add(_external_write_key(cls, session_id=session_id))


def clear_external_write_confirmations_for_tests() -> None:
    with _confirmed_external_writes_lock:
        _confirmed_external_writes.clear()


def _external_write_key(
    cls: PathClassification, *, session_id: str | None = None
) -> tuple[str, str, str]:
    sid = (session_id or "_default_agent_session").strip() or "_default_agent_session"
    return (sid, workspace_hash(cls.workspace_root), str(cls.resolved))


def _is_external_write_confirmed(cls: PathClassification, *, session_id: str | None = None) -> bool:
    with _confirmed_external_writes_lock:
        return _external_write_key(cls, session_id=session_id) in _confirmed_external_writes


def permission_for_path(
    path: str | Path,
    *,
    operation: str,
    workspace_root: Path | str | None = None,
    allow_hidden: bool = False,
    session_id: str | None = None,
) -> PermissionCheck:
    cls = classify_path(path, workspace_root=workspace_root)
    op = operation.lower()
    if cls.system:
        return PermissionCheck(
            cls,
            PermissionDecision(
                scope="system",
                risk="denied",
                decision="denied",
                summary=f"Denied {op}: {cls.display_path}",
                reason="path_hidden_or_system",
            ),
            "path_hidden_or_system",
            "Path is hidden or system-protected.",
        )

    read_only_ops = {"read", "search"}
    mutation_ops = {"write", "edit", "delete", "patch"}

    if cls.inside_workspace:
        if cls.hidden and not allow_hidden:
            return PermissionCheck(
                cls,
                PermissionDecision(
                    scope="hidden",
                    risk="denied",
                    decision="denied",
                    summary=f"Denied {op}: {cls.display_path}",
                    reason="path_hidden_or_system",
                ),
                "path_hidden_or_system",
                "Path is hidden or system-protected.",
            )
        risk = (
            "read_only"
            if op in read_only_ops
            else "workspace_mutation" if op in mutation_ops else "elevated"
        )
        if op in mutation_ops:
            denial = _self_improvement_mutation_denial(
                cls.resolved,
                workspace_root=cls.workspace_root,
                operation=op,
            )
            if denial:
                return PermissionCheck(
                    cls,
                    PermissionDecision(
                        scope="workspace",
                        risk="denied",
                        decision="denied",
                        summary=f"Denied {op}: {cls.display_path}",
                        reason="self_improvement_workspace_guard",
                    ),
                    "path_denied_by_self_improvement_guard",
                    denial,
                )
        return PermissionCheck(
            cls,
            PermissionDecision(
                scope="workspace",
                risk=risk,
                decision="allowed",
                summary=f"{op}: {cls.display_path}",
                reason="inside_workspace",
            ),
        )

    if op == "read":
        if _is_external_read_confirmed(cls, session_id=session_id):
            return PermissionCheck(
                cls,
                PermissionDecision(
                    scope=cls.scope,
                    risk="elevated",
                    decision="confirmed",
                    summary=build_external_read_summary(cls),
                    reason="outside_workspace_read_confirmed",
                ),
            )
        return PermissionCheck(
            cls,
            PermissionDecision(
                scope=cls.scope,
                risk="elevated",
                decision="confirmation_required",
                summary=build_external_read_summary(cls),
                reason="outside_workspace_read_requires_confirmation",
            ),
            "path_outside_workspace",
            "Outside-workspace read requires high-risk confirmation.",
        )

    # workspace 外的写/编辑/patch 默认走确认链（像读一样），由 pre_hook 的
    # confirmation_required 分支接入 _confirm_or_reject：allow_all 开则短路放行并记审计，
    # 关则弹确认卡让用户逐次决定。OS 系统路径已在上面 cls.system 分支硬拒；
    # execute 仍硬拒（落到下方 denied）。
    if op in mutation_ops:
        if _is_external_write_confirmed(cls, session_id=session_id):
            return PermissionCheck(
                cls,
                PermissionDecision(
                    scope=cls.scope,
                    risk="elevated",
                    decision="confirmed",
                    summary=f"{op}: {cls.display_path} (outside workspace, confirmed this session)",
                    reason="outside_workspace_write_confirmed",
                ),
            )
        return PermissionCheck(
            cls,
            PermissionDecision(
                scope=cls.scope,
                risk="elevated",
                decision="confirmation_required",
                summary=f"{op}: {cls.display_path} (outside workspace)",
                reason="outside_workspace_write_requires_confirmation",
            ),
            "path_outside_workspace",
            "Outside-workspace mutation requires confirmation.",
        )

    return PermissionCheck(
        cls,
        PermissionDecision(
            scope=cls.scope,
            risk="denied",
            decision="denied",
            summary=f"Denied {op}: {cls.display_path}",
            reason="outside_workspace_side_effect_denied",
        ),
        "path_outside_workspace" if op != "execute" else "command_rejected",
        "Outside-workspace mutation or execution is denied.",
    )


def _truncate_summary(summary: str, max_len: int = _SUMMARY_TOTAL_MAX) -> str:
    normalized = " ".join(str(summary).split())
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 3] + "..."


def redact_fragment(value: object, max_len: int = _SUMMARY_SNIPPET_MAX) -> str:
    text = " ".join(str(value).replace("\r", "\n").split())
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub(lambda match: _redacted_token(match.group()), text)
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _redacted_token(value: str) -> str:
    lower = value.lower()
    if lower.startswith("sk-"):
        return "sk-***"
    for prefix in ("api_key", "api-key", "token", "password", "secret", "bearer"):
        if prefix in lower[:16]:
            if " " in value:
                return value.split()[0] + " ***"
            if "=" in value:
                return value.split("=", 1)[0] + "=***"
            if ":" in value:
                return value.split(":", 1)[0] + ":***"
            return prefix + "=***"
    return "***"


def build_external_read_summary(cls: PathClassification) -> str:
    return _truncate_summary(
        f"Read outside workspace: {redact_fragment(cls.display_path, 140)}; "
        "reason: exceptional inspection"
    )


def build_write_summary(path: Path, *, baseline_id: str | None = None) -> str:
    cls = classify_path(path)
    baseline = (baseline_id or "missing")[:18]
    return _truncate_summary(
        f"Mutate workspace file: {redact_fragment(cls.display_path, 140)}; "
        f"operation: replace; baseline: {baseline}"
    )


def build_edit_summary(
    path: Path, old_text: str, new_text: str, *, baseline_id: str | None = None
) -> str:
    cls = classify_path(path)
    old_preview = redact_fragment(old_text)
    new_preview = redact_fragment(new_text)
    baseline = (baseline_id or "missing")[:18]
    return _truncate_summary(
        f"Mutate workspace file: {redact_fragment(cls.display_path, 100)}; "
        f"operation: edit; baseline: {baseline}; old: {old_preview}; new: {new_preview}"
    )


def build_exec_summary(command: str) -> str:
    lines = str(command).splitlines()
    first_line = lines[0] if lines else ""
    return _truncate_summary(
        f"Run elevated command from workspace: {redact_fragment(first_line, 120)}"
    )


def is_safe_exec_command(command: str) -> bool:
    try:
        argv = parse_command_argv(command)
    except CommandParseError:
        return False
    normalized = " ".join(value.lower() for value in argv)
    return normalized in SAFE_EXEC_COMMANDS


def _contains_parent_path_segment(value: str) -> bool:
    text = str(value).strip("'\"")
    return _PARENT_PATH_SEGMENT_PATTERN.search(text) is not None


def _explicit_option_values(token: str) -> tuple[str, ...]:
    text = str(token)
    if not text.startswith("-") and not (os.name == "nt" and text.startswith("/")):
        return ()
    return tuple(part.strip("'\"") for part in re.split(r"[=:,]", text)[1:] if part)


def _compact_path_option_value(token: str, *, executable: str) -> str | None:
    text = str(token)
    if executable in _PATTERN_EXECUTABLES:
        if text.startswith("-f") and len(text) > 2:
            return text[2:].strip("'\"")
        return None
    for prefix in _COMPACT_DASH_PATH_OPTION_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix):
            return text[len(prefix) :].strip("'\"")
    if os.name != "nt":
        return None
    lowered = text.lower()
    for prefix in _COMPACT_WINDOWS_PATH_OPTION_PREFIXES:
        if lowered.startswith(prefix) and len(text) > len(prefix):
            return text[len(prefix) :].strip("'\"")
    return None


def _is_separated_path_option(token: str | None, *, executable: str) -> bool:
    if not token:
        return False
    if executable in _PATTERN_EXECUTABLES:
        return token in _PATTERN_FILE_FLAGS
    if token in _SEPARATED_DASH_PATH_OPTIONS:
        return True
    lowered = token.lower()
    if lowered in _SEPARATED_CASE_INSENSITIVE_PATH_OPTIONS:
        return True
    return os.name == "nt" and lowered in _SEPARATED_WINDOWS_PATH_OPTIONS


def _is_inline_pattern_option(token: str, *, executable: str) -> bool:
    if executable not in _PATTERN_EXECUTABLES:
        return False
    lowered = token.lower()
    if executable.startswith("findstr"):
        return lowered.startswith("/c:")
    return lowered.startswith("--regexp=") or (lowered.startswith("-e") and lowered != "-e")


def _pattern_aux_value_flags(executable: str) -> frozenset[str]:
    if executable in _GREP_EXECUTABLES:
        return _GREP_AUX_VALUE_FLAGS
    if executable in _RG_EXECUTABLES:
        return _RG_AUX_VALUE_FLAGS
    return frozenset()


def _bare_parent_data_indexes(tokens: list[str], *, executable: str) -> set[int]:
    if executable in _ALL_ARGUMENT_DATA_EXECUTABLES:
        return set(range(1, len(tokens)))
    if executable not in _PATTERN_EXECUTABLES:
        return set()

    indexes: set[int] = set()
    option_syntax = True
    has_flag_pattern = False
    positional_pattern_seen = False
    aux_value_flags = _pattern_aux_value_flags(executable)
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            option_syntax = False
            index += 1
            continue
        if option_syntax and token in _PATTERN_VALUE_FLAGS and index + 1 < len(tokens):
            indexes.add(index + 1)
            has_flag_pattern = True
            index += 2
            continue
        if option_syntax and _is_inline_pattern_option(token, executable=executable):
            indexes.add(index)
            has_flag_pattern = True
            index += 1
            continue
        if option_syntax and token in _PATTERN_FILE_FLAGS and index + 1 < len(tokens):
            has_flag_pattern = True
            index += 2
            continue
        if option_syntax and (
            (token.startswith("-f") and token != "-f") or token.startswith("--file=")
        ):
            has_flag_pattern = True
            index += 1
            continue
        if option_syntax and token in aux_value_flags and index + 1 < len(tokens):
            index += 2
            continue
        if option_syntax and (
            token.startswith("-") or (executable.startswith("findstr") and token.startswith("/"))
        ):
            index += 1
            continue
        if not has_flag_pattern and not positional_pattern_seen:
            indexes.add(index)
            positional_pattern_seen = True
        index += 1
    return indexes


def _command_contains_parent_path_traversal(
    tokens: list[str],
    *,
    executable: str,
) -> bool:
    option_syntax = True
    previous_token: str | None = None
    shell_host = executable in _SHELL_HOST_NAMES
    data_indexes = _bare_parent_data_indexes(tokens, executable=executable)
    # shlex removes wrapping quotes. Only a bare ``..`` in a known
    # data/pattern argument position is exempt from path interpretation.
    for index, token in enumerate(tokens):
        if token == "--":
            option_syntax = False
            previous_token = token
            continue

        path_option_context = option_syntax and _is_separated_path_option(
            previous_token,
            executable=executable,
        )
        is_data_argument = index in data_indexes and not path_option_context
        if not is_data_argument and _contains_parent_path_segment(token):
            return True
        if shell_host and _EMBEDDED_PARENT_PATH_SEGMENT_PATTERN.search(token) is not None:
            return True

        if option_syntax and not is_data_argument:
            for value in _explicit_option_values(token):
                if _contains_parent_path_segment(value):
                    return True
            compact_value = _compact_path_option_value(
                token,
                executable=executable,
            )
            if compact_value is not None and _contains_parent_path_segment(compact_value):
                return True
        previous_token = token
    return False


def _command_policy_rejection(
    *,
    root: Path,
    message: str,
    reason: str,
) -> PermissionCheck:
    cls = classify_path(root, workspace_root=root)
    return PermissionCheck(
        cls,
        PermissionDecision(
            scope="workspace",
            risk="denied",
            decision="denied",
            summary="Denied command before execution.",
            reason=reason,
        ),
        "command_rejected",
        message,
    )


def _looks_like_improvement_workspace_root(workspace_root: Path | str) -> bool:
    """Fail-closed fallback for improvement workspace detection.

    Delegates to ``src.utils.proposal_policy.is_improvement_workspace_root``
    (low-level, no business-layer imports).  On import failure, falls back
    to a conservative inline check so that proposal worktree mutations are
    still rejected even when the policy module is unavailable.
    """
    try:
        from src.utils.proposal_policy import is_improvement_workspace_root as _check

        return _check(workspace_root)
    except Exception:
        # Fail-closed fallback: inline check with hardcoded stable directory
        # names (source of truth: proposal_policy.WORKTREES_DIR / IMPROVEMENT_DIR).
        try:
            root = Path(workspace_root).expanduser().resolve(strict=False)
        except Exception:
            return False
        return (
            root.parent.name.lower() == "improvement"
            and root.parent.parent.name.lower() == ".worktrees"
        )


# Returned when the proposal guard itself is unavailable inside a proposal
# worktree. FR-014/SC-003 require fail-closed: a proposal executor must not
# slip outside the blast radius just because the guard raised.
_SELF_IMPROVEMENT_GUARD_UNAVAILABLE_REASON = (
    "self-improvement workspace guard is unavailable; proposal worktree "
    "mutations are denied until the guard can be evaluated."
)

# Mutation operations covered by check_improvement_workspace_mutation. The
# fail-closed fallback only applies to these so reads keep working when the
# guard raises.
_SELF_IMPROVEMENT_MUTATION_OPS = frozenset({"write", "edit", "delete", "patch"})


def _self_improvement_mutation_denial(
    path: Path,
    *,
    workspace_root: Path,
    operation: str,
) -> str | None:
    try:
        from src.business.self_improvement.proposal_workspace import (
            check_improvement_workspace_mutation,
        )

        return check_improvement_workspace_mutation(
            path,
            workspace_root=workspace_root,
            operation=operation,
        )
    except Exception:
        # Fail closed for proposal worktrees: if the guard itself is
        # unavailable (import failure, partial reload, ...), a proposal
        # executor must not escape the FR-014 blast radius. Normal workspaces
        # are unaffected — the inline check is False for them, and non-mutation
        # operations are never gated by this guard.
        if (
            _looks_like_improvement_workspace_root(workspace_root)
            and operation.lower() in _SELF_IMPROVEMENT_MUTATION_OPS
        ):
            return _SELF_IMPROVEMENT_GUARD_UNAVAILABLE_REASON
        return None


def _self_improvement_exec_denial(
    command: str,
    *,
    workspace_root: Path,
    base_dir: Path,
) -> str | None:
    try:
        from src.business.self_improvement.proposal_workspace import (
            check_improvement_exec_command,
        )

        return check_improvement_exec_command(
            command,
            workspace_root=workspace_root,
            base_dir=base_dir,
        )
    except Exception:
        # Fail closed for proposal worktrees (see mutation denial above). Exec
        # is always potentially dangerous, so any failure inside a proposal
        # worktree is denied; normal workspaces are unaffected.
        if _looks_like_improvement_workspace_root(workspace_root):
            return _SELF_IMPROVEMENT_GUARD_UNAVAILABLE_REASON
        return None


def command_path_policy_violation(
    command: str,
    *,
    workspace_root: Path | str | None = None,
    base_dir: Path | str | None = None,
) -> PermissionCheck | None:
    root = resolve_workspace_root(workspace_root)
    base = Path(base_dir).expanduser().resolve() if base_dir is not None else root
    try:
        tokens = parse_command_argv(command)
    except CommandParseError as exc:
        return _command_policy_rejection(
            root=root,
            message=str(exc),
            reason="shell_syntax_or_parse_error",
        )
    executable = Path(tokens[0]).name.lower()
    denied_flags = _INLINE_CODE_FLAGS.get(executable, set())
    if any(token.lower() in denied_flags for token in tokens[1:]):
        return _command_policy_rejection(
            root=root,
            message="Inline interpreter code is not supported by the workspace-safe exec tool.",
            reason="inline_code_denied",
        )
    if _command_contains_parent_path_traversal(
        tokens,
        executable=executable,
    ):
        return _command_policy_rejection(
            root=root,
            message="Parent-directory traversal is not supported by the exec tool.",
            reason="exec_path_traversal_denied",
        )
    improvement_denial = _self_improvement_exec_denial(
        command,
        workspace_root=root,
        base_dir=base,
    )
    if improvement_denial:
        return _command_policy_rejection(
            root=root,
            message=improvement_denial,
            reason="self_improvement_exec_guard",
        )
    return None


def ensure_all_inside_workspace(
    paths: Iterable[str | Path], workspace_root: Path | str | None = None
) -> PermissionCheck | None:
    for path in paths:
        check = permission_for_path(path, operation="patch", workspace_root=workspace_root)
        if not check.allowed:
            return check
    return None
