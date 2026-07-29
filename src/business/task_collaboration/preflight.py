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


_PATH_END_DELIMITERS = r"""\s`"'<>|?*，。；：！？、（）()【】\[\]{}"""
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
            [A-Za-z]:[\\/][^{_PATH_END_DELIMITERS}]*
            |
            \\\\[^\\/{_PATH_END_DELIMITERS}]+[\\/]
            [^\\/{_PATH_END_DELIMITERS}]+
            (?:[\\/][^{_PATH_END_DELIMITERS}]+)*
        )
    )
    |
    (?P<posix>
        (?<![A-Za-z0-9_:/\\])
        /
        [^{_PATH_END_DELIMITERS}/]
        [^{_PATH_END_DELIMITERS}]*
    )
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


def _is_inside_workspace(candidate: str, workspace_root: str) -> bool:
    candidate_style = _path_style(candidate)
    root_style = _path_style(workspace_root)
    if candidate_style is None or root_style is None:
        raise ValueError("workspace_root must be absolute")
    if candidate_style != root_style:
        return False

    path_module = ntpath if candidate_style == "windows" else posixpath
    normalized_candidate = _normalized(candidate, candidate_style)
    normalized_root = _normalized(workspace_root, root_style)
    try:
        return path_module.commonpath([normalized_candidate, normalized_root]) == normalized_root
    except ValueError:
        # Different Windows drives (or otherwise incompatible roots) are necessarily outside.
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
        candidate = raw_candidate.rstrip(_TRAILING_SENTENCE_PUNCTUATION)
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
            if _is_inside_workspace(absolute_path, node.workspace_root):
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
