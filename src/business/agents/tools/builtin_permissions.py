"""Workspace and confirmation safety helpers for built-in Agent tools."""

from __future__ import annotations

import hashlib
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.business.agents.tools.builtin_contracts import PermissionDecision
from src.execution.command_runner import CommandParseError, parse_command_argv

_SUMMARY_SNIPPET_MAX = 80
_SUMMARY_TOTAL_MAX = 240

_SENSITIVE_PATTERNS = [
    re.compile(r"(?<!\w)sk-[A-Za-z0-9_\-]{8,}", re.IGNORECASE),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{12,}"),
]

_SYSTEM_ROOTS = [
    Path("C:/Windows"),
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
    Path("/etc"),
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
]

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


def workspace_hash(workspace_root: Path | str | None = None) -> str:
    root = resolve_workspace_root(workspace_root)
    return hashlib.sha256(str(root).encode("utf-8", errors="replace")).hexdigest()


def resolve_workspace_root(workspace_root: Path | str | None = None) -> Path:
    return Path(workspace_root or Path.cwd()).expanduser().resolve()


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
    for root in _SYSTEM_ROOTS:
        try:
            if path.is_relative_to(root.resolve(strict=False)):
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
    root = resolve_workspace_root(workspace_root)
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
    if cls.system or (cls.hidden and not allow_hidden):
        return PermissionCheck(
            cls,
            PermissionDecision(
                scope="system" if cls.system else "hidden",
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
        risk = (
            "read_only"
            if op in read_only_ops
            else "workspace_mutation" if op in mutation_ops else "elevated"
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
    first_line = str(command).splitlines()[0] if str(command).splitlines() else ""
    return _truncate_summary(
        f"Run elevated command in workspace: {redact_fragment(first_line, 120)}"
    )


def is_safe_exec_command(command: str) -> bool:
    try:
        argv = parse_command_argv(command)
    except CommandParseError:
        return False
    normalized = " ".join(value.lower() for value in argv)
    return normalized in SAFE_EXEC_COMMANDS


def _looks_like_path_argument(token: str) -> bool:
    if not token:
        return False
    if token.startswith("-"):
        return False
    # Windows single-letter switches such as /b are not path targets.
    if token.startswith("/") and len(token) <= 3 and token[1:].isalnum():
        return False
    return token.startswith((".", "~", "/", "\\")) or "/" in token or "\\" in token or ":" in token


def _path_candidate_from_argument(token: str) -> str | None:
    value = str(token).strip()
    if not value:
        return None
    if "=" in value and value.startswith("-"):
        value = value.split("=", 1)[1]
    if not _looks_like_path_argument(value):
        return None
    return value


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
    if executable in _SHELL_HOST_NAMES:
        return _command_policy_rejection(
            root=root,
            message="Shell host commands are not supported by the workspace-safe exec tool.",
            reason="shell_host_denied",
        )
    denied_flags = _INLINE_CODE_FLAGS.get(executable, set())
    if any(token.lower() in denied_flags for token in tokens[1:]):
        return _command_policy_rejection(
            root=root,
            message="Inline interpreter code is not supported by the workspace-safe exec tool.",
            reason="inline_code_denied",
        )
    for index, token in enumerate(tokens):
        candidate_value = _path_candidate_from_argument(token)
        if candidate_value is None:
            continue
        raw = Path(candidate_value).expanduser()
        candidate = raw if raw.is_absolute() else base / raw
        if index == 0:
            try:
                if candidate.resolve() == Path(sys.executable).resolve():
                    continue
            except OSError:
                pass
        check = permission_for_path(candidate, operation="read", workspace_root=root)
        if not check.classification.inside_workspace:
            return PermissionCheck(
                check.classification,
                PermissionDecision(
                    scope=check.decision.scope,
                    risk="denied",
                    decision="denied",
                    summary=f"Denied exec path target: {check.classification.display_path}",
                    reason="exec_path_target_outside_workspace",
                ),
                "command_rejected",
                "Command path arguments outside the workspace are denied.",
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
