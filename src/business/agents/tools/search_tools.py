"""Structured filename and content search built-ins."""

from __future__ import annotations

import fnmatch
import re
import time
from pathlib import Path
from typing import Any, Iterable

from src.business.agents.tools.builtin_config import get_config_int
from src.business.agents.tools.builtin_contracts import OUTCOME_REJECTED, error_json, success_json
from src.business.agents.tools.builtin_permissions import permission_for_path
from src.business.agents.tools.file_tools import _looks_binary, _redact_for_path

DEFAULT_IGNORED_DIRS = [
    ".git",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".venv",
    "venv",
    "target",
    "coverage",
]


def _offset_token(token: str | None) -> int:
    if not token:
        return 0
    if str(token).startswith("offset:"):
        token = str(token).split(":", 1)[1]
    try:
        return max(0, int(token))
    except (TypeError, ValueError):
        return 0


def _page_size(requested: int | None) -> int:
    default = get_config_int("get_agent_tools_search_default_page_size", 100, maximum=500)
    if requested is None:
        return default
    try:
        return max(1, min(int(requested), 500))
    except (TypeError, ValueError):
        return default


def _should_skip_dir(path: Path, root: Path, include_hidden: bool) -> bool:
    name = path.name
    if name in DEFAULT_IGNORED_DIRS:
        return True
    if not include_hidden and name.startswith("."):
        return True
    return False


def _iter_files(root: Path, *, include_hidden: bool) -> Iterable[Path]:
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if not _should_skip_dir(entry, root, include_hidden):
                    stack.append(entry)
                continue
            if not include_hidden and any(
                part.startswith(".") for part in entry.relative_to(root).parts
            ):
                continue
            if entry.is_file():
                yield entry


def _matches_pattern(path: Path, root: Path, pattern: str) -> bool:
    rel = path.relative_to(root).as_posix()
    pat = pattern or "*"
    return fnmatch.fnmatch(path.name, pat) or fnmatch.fnmatch(rel, pat)


def search_files_handler(
    root: str = ".",
    pattern: str = "*",
    pageSize: int | None = None,
    pageToken: str | None = None,
    includeHidden: bool = False,
) -> str:
    tool = "search_files"
    check = permission_for_path(root, operation="search", allow_hidden=includeHidden)
    if not check.allowed:
        return error_json(
            tool,
            check.error_code or "path_outside_workspace",
            check.message or "Search root is outside the workspace.",
            outcome=OUTCOME_REJECTED,
            permission=check.decision,
        )
    root_path = check.classification.resolved
    if not root_path.exists():
        return error_json(
            tool, "path_not_directory", "Search root does not exist.", outcome=OUTCOME_REJECTED
        )
    if not root_path.is_dir():
        return error_json(
            tool, "path_not_directory", "Search root is not a directory.", outcome=OUTCOME_REJECTED
        )

    offset = _offset_token(pageToken)
    limit = _page_size(pageSize)
    max_scanned = get_config_int("get_agent_tools_search_max_files_scanned", 50_000)
    matches = []
    scanned = 0
    for file_path in _iter_files(root_path, include_hidden=includeHidden):
        scanned += 1
        if scanned > max_scanned:
            break
        if _matches_pattern(file_path, root_path, pattern):
            matches.append(file_path)
    matches.sort(key=lambda p: p.relative_to(root_path).as_posix().lower())
    page = matches[offset : offset + limit]
    has_more = offset + limit < len(matches)
    payload = {
        "matches": [
            {
                "path": path.relative_to(root_path).as_posix(),
                "type": "file",
                "sizeBytes": path.stat().st_size,
            }
            for path in page
        ],
        "count": len(page),
        "hasMore": has_more,
        "nextPageToken": f"offset:{offset + limit}" if has_more else None,
        "ignoredDefaults": DEFAULT_IGNORED_DIRS,
        "scanned": min(scanned, max_scanned),
        "truncated": scanned > max_scanned,
    }
    return success_json(
        tool,
        payload,
        permission=check.decision,
        limits={
            "truncated": scanned > max_scanned,
            "pageSize": limit,
            "hasMore": has_more,
            "nextPageToken": payload["nextPageToken"],
        },
    )


def _compile_pattern(pattern: str, mode: str):
    if mode == "regex":
        return re.compile(pattern)
    if mode == "literal":
        return re.compile(re.escape(pattern))
    raise ValueError("unsupported search mode")


def _include_match(path: Path, root: Path, include_globs: list[str] | None) -> bool:
    if not include_globs:
        return True
    rel = path.relative_to(root).as_posix()
    return any(
        fnmatch.fnmatch(rel, glob) or fnmatch.fnmatch(path.name, glob) for glob in include_globs
    )


def search_content_handler(
    root: str = ".",
    pattern: str = "",
    mode: str = "literal",
    includeGlobs: list[str] | None = None,
    contextLines: int = 0,
    pageSize: int | None = None,
    pageToken: str | None = None,
    includeHidden: bool = False,
) -> str:
    tool = "search_content"
    if not pattern:
        return error_json(
            tool,
            "search_pattern_invalid",
            "Search pattern must not be empty.",
            outcome=OUTCOME_REJECTED,
        )
    try:
        compiled = _compile_pattern(pattern, mode)
    except re.error as exc:
        return error_json(
            tool, "search_pattern_invalid", f"Invalid regex: {exc}", outcome=OUTCOME_REJECTED
        )
    except ValueError:
        return error_json(
            tool,
            "search_pattern_invalid",
            "Search mode must be literal or regex.",
            outcome=OUTCOME_REJECTED,
        )

    check = permission_for_path(root, operation="search", allow_hidden=includeHidden)
    if not check.allowed:
        return error_json(
            tool,
            check.error_code or "path_outside_workspace",
            check.message or "Search root is outside the workspace.",
            outcome=OUTCOME_REJECTED,
            permission=check.decision,
        )
    root_path = check.classification.resolved
    if not root_path.exists() or not root_path.is_dir():
        return error_json(
            tool, "path_not_directory", "Search root is not a directory.", outcome=OUTCOME_REJECTED
        )

    offset = _offset_token(pageToken)
    limit = _page_size(pageSize)
    max_scanned = get_config_int("get_agent_tools_search_max_files_scanned", 50_000)
    max_bytes = get_config_int("get_agent_tools_search_max_bytes_per_file", 1_048_576)
    max_elapsed_ms = get_config_int("get_agent_tools_search_max_elapsed_ms", 30_000)
    context = max(0, min(int(contextLines or 0), 20))
    started = time.monotonic()
    flat: list[dict[str, Any]] = []
    skipped_binary = 0
    scanned = 0
    elapsed_truncated = False
    for file_path in _iter_files(root_path, include_hidden=includeHidden):
        if not _include_match(file_path, root_path, includeGlobs):
            continue
        scanned += 1
        if scanned > max_scanned:
            break
        if (time.monotonic() - started) * 1000 > max_elapsed_ms:
            elapsed_truncated = True
            break
        try:
            with file_path.open("rb") as handle:
                raw = handle.read(max_bytes + 1)
        except OSError:
            continue
        raw = raw[:max_bytes]
        if _looks_binary(file_path, raw[:4096]):
            skipped_binary += 1
            continue
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            if not compiled.search(line):
                continue
            redacted_line, _ = _redact_for_path(file_path, line)
            before = [_redact_for_path(file_path, v)[0] for v in lines[max(0, idx - context) : idx]]
            after = [_redact_for_path(file_path, v)[0] for v in lines[idx + 1 : idx + 1 + context]]
            flat.append(
                {
                    "path": file_path.relative_to(root_path).as_posix(),
                    "line": idx + 1,
                    "text": redacted_line,
                    "before": before,
                    "after": after,
                }
            )
    flat.sort(key=lambda item: (item["path"].lower(), item["line"]))
    page = flat[offset : offset + limit]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for match in page:
        grouped.setdefault(match["path"], []).append(
            {
                "line": match["line"],
                "text": match["text"],
                "before": match["before"],
                "after": match["after"],
            }
        )
    has_more = offset + limit < len(flat)
    payload = {
        "files": [{"path": path, "matches": matches} for path, matches in grouped.items()],
        "matchCount": len(page),
        "hasMore": has_more,
        "nextPageToken": f"offset:{offset + limit}" if has_more else None,
        "ignoredDefaults": DEFAULT_IGNORED_DIRS,
        "skippedBinary": skipped_binary,
        "scanned": min(scanned, max_scanned),
        "truncated": scanned > max_scanned or elapsed_truncated,
    }
    return success_json(
        tool,
        payload,
        permission=check.decision,
        limits={
            "truncated": payload["truncated"],
            "pageSize": limit,
            "hasMore": has_more,
            "nextPageToken": payload["nextPageToken"],
        },
    )
