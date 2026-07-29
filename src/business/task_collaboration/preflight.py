"""Task graph deterministic preflight checks.

This module intentionally has no repository, scheduler, or LLM dependencies.  The
first preflight rule only compares absolute paths written in node descriptions with
the workspace root assigned to that executor.  Callers decide what to do with the
returned risks; this module never approves or rejects a graph.
"""

from __future__ import annotations

import ntpath
import posixpath
import re
from dataclasses import dataclass
from typing import Iterable, Literal


_UNQUOTED_PATH_HARD_DELIMITERS = r"""`"'<>|?*，。；：！？、（）()【】\[\]{},;!"""
_UNQUOTED_PATH_TERMINATOR = rf"""(?=$|[\r\n\t{_UNQUOTED_PATH_HARD_DELIMITERS}]|\.(?=\s|$))"""
_QUOTED_ABSOLUTE_PATH_RE = re.compile(
    r"""
    (?:
        `(?P<backtick>(?:[A-Za-z]:[\\/]|\\\\|/)[^`\r\n]+)`
        |
        "(?P<double>(?:[A-Za-z]:[\\/]|\\\\|/)[^"\r\n]+)"
        |
        '(?P<single>(?:[A-Za-z]:[\\/]|\\\\|/)[^'\r\n]+)'
    )
    """,
    re.VERBOSE,
)
_ABSOLUTE_PATH_RE = re.compile(
    rf"""
    (?P<windows>
        (?<![A-Za-z0-9_])
        (?:
            [A-Za-z]:[\\/]
            [^{_UNQUOTED_PATH_HARD_DELIMITERS}\r\n\t]*?
            |
            \\\\[^\\/{_UNQUOTED_PATH_HARD_DELIMITERS}\r\n\t]+[\\/]
            [^\\/{_UNQUOTED_PATH_HARD_DELIMITERS}\r\n\t]+
            (?:[\\/][^{_UNQUOTED_PATH_HARD_DELIMITERS}\r\n\t]+)*?
        )
    )
    {_UNQUOTED_PATH_TERMINATOR}
    |
    (?P<posix>
        (?<![A-Za-z0-9_:/\\])
        /
        [^{_UNQUOTED_PATH_HARD_DELIMITERS}/\r\n\t]
        [^{_UNQUOTED_PATH_HARD_DELIMITERS}\r\n\t]*?
    )
    {_UNQUOTED_PATH_TERMINATOR}
    """,
    re.VERBOSE,
)
_TRAILING_SENTENCE_PUNCTUATION = ".,;!:"


@dataclass(frozen=True)
class TaskNodePathContext:
    """The description and executor workspace needed by the path-only preflight."""

    node_id: str
    description: str
    workspace_root: str


@dataclass(frozen=True)
class TaskGraphPreflightRisk:
    """Advisory risk found before a task graph starts."""

    code: Literal["absolute_path_outside_workspace"]
    severity: Literal["high"]
    node_id: str
    absolute_path: str
    workspace_root: str
    message: str


def _path_style(path: str) -> Literal["windows", "posix"] | None:
    if ntpath.isabs(path) and (ntpath.splitdrive(path)[0] or path.startswith("\\\\")):
        return "windows"
    if posixpath.isabs(path):
        return "posix"
    return None


def _normalized(path: str, style: Literal["windows", "posix"]) -> str:
    path_module = ntpath if style == "windows" else posixpath
    normalized = path_module.normpath(path)
    return path_module.normcase(normalized) if style == "windows" else normalized


def _segments(path: str, style: Literal["windows", "posix"]) -> list[str]:
    """Split a normalized absolute path into comparable segments."""
    normalized = _normalized(path, style)
    if style == "windows":
        drive, rest = ntpath.splitdrive(normalized)
        parts = [part for part in rest.replace("/", "\\").split("\\") if part]
        return ([drive] if drive else []) + parts
    return [part for part in normalized.split("/") if part]


def _is_confidently_outside_workspace(candidate: str, workspace_root: str) -> bool:
    """Report a risk only when the candidate genuinely diverges from the root.

    An unquoted path inside prose is ambiguous: ``E:\\ws 下的文件`` may be the path
    ``E:\\ws`` followed by prose, or a directory whose name contains a space.  No
    extraction rule resolves that, so a candidate that merely truncates the root's
    segment (``C:\\Program`` for ``C:\\Program Files``) or extends it (``E:\\ws 下的
    文件`` for ``E:\\ws``) counts as unknown rather than outside.

    These risks are advisory.  A false alarm on an in-workspace node teaches
    readers to ignore the whole check, which costs more than a missed warning.
    """
    candidate_style = _path_style(candidate)
    root_style = _path_style(workspace_root)
    if candidate_style is None or root_style is None:
        raise ValueError("workspace_root must be absolute")
    if candidate_style != root_style:
        return True

    candidate_segments = _segments(candidate, candidate_style)
    root_segments = _segments(workspace_root, root_style)

    for index, root_segment in enumerate(root_segments):
        if index >= len(candidate_segments):
            # The candidate stops above the root: an ancestor, not an outsider.
            return False
        candidate_segment = candidate_segments[index]
        if candidate_segment == root_segment:
            continue
        if index == len(candidate_segments) - 1 and (
            candidate_segment.startswith(root_segment) or root_segment.startswith(candidate_segment)
        ):
            return False
        return True
    return False


def _absolute_paths(description: str) -> Iterable[str]:
    text = str(description or "")
    matches: list[tuple[int, str]] = []
    quoted_spans: list[tuple[int, int]] = []
    for match in _QUOTED_ABSOLUTE_PATH_RE.finditer(text):
        candidate = next(
            value
            for value in (
                match.group("backtick"),
                match.group("double"),
                match.group("single"),
            )
            if value is not None
        )
        quoted_spans.append(match.span())
        matches.append((match.start(), candidate))

    for match in _ABSOLUTE_PATH_RE.finditer(text):
        if any(
            match.start() < quoted_end and match.end() > quoted_start
            for quoted_start, quoted_end in quoted_spans
        ):
            continue
        matches.append((match.start(), match.group(0)))

    for _, raw_candidate in sorted(matches, key=lambda item: item[0]):
        candidate = raw_candidate.rstrip().rstrip(_TRAILING_SENTENCE_PUNCTUATION).rstrip()
        if candidate:
            yield candidate


def find_outside_workspace_path_risks(
    nodes: Iterable[TaskNodePathContext],
) -> list[TaskGraphPreflightRisk]:
    """Return advisory risks for absolute paths outside each executor workspace.

    Only node descriptions are inspected.  Relative paths are intentionally ignored,
    and no filesystem access is performed.  Duplicate paths within the same node are
    collapsed while preserving first-seen order.
    """

    risks: list[TaskGraphPreflightRisk] = []
    for node in nodes:
        root_style = _path_style(node.workspace_root)
        if root_style is None:
            raise ValueError("workspace_root must be absolute")

        seen: set[tuple[str, str]] = set()
        for absolute_path in _absolute_paths(node.description):
            path_style = _path_style(absolute_path)
            if path_style is None:
                continue
            dedupe_key = (path_style, _normalized(absolute_path, path_style))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            if not _is_confidently_outside_workspace(absolute_path, node.workspace_root):
                continue
            risks.append(
                TaskGraphPreflightRisk(
                    code="absolute_path_outside_workspace",
                    severity="high",
                    node_id=node.node_id,
                    absolute_path=absolute_path,
                    workspace_root=node.workspace_root,
                    message=(
                        f"节点 {node.node_id} 的绝对路径不在执行体工作区内：" f"{absolute_path}"
                    ),
                )
            )
    return risks
