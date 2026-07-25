"""File, edit, and patch built-ins with baseline-safe mutation."""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.business.agents.tools.builtin_config import get_config_int
from src.business.agents.tools.builtin_contracts import (
    OUTCOME_CONFIRMATION_REQUIRED,
    OUTCOME_REJECTED,
    OUTCOME_UNSUPPORTED,
    PermissionDecision,
    VerificationResult,
    current_tool_runtime,
    error_json,
    success_json,
    utc_now_iso,
)
from src.business.agents.tools.builtin_permissions import (
    display_path,
    permission_for_path,
    resolve_workspace_root,
)
from src.utils.agent_tool_health import increment_agent_tool_health

# 二进制判定只信显式扩展名 + 内容嗅探，不用 ``mimetypes``：后者在 Windows 上会读
# HKEY_CLASSES_ROOT，同一份代码在不同机器上结果不同（实测 ``.ts`` 被本机注册为
# ``video/vnd.dlna.mpeg-tts``，于是 TypeScript 源码全部读不了，而 Linux CI 上复现不出）。
_BINARY_EXTENSIONS = {
    # 图片
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",
    ".tiff",
    ".tif",
    # 视频
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".wmv",
    ".flv",
    ".m4v",
    ".mpeg",
    ".mpg",
    # 音频
    ".mp3",
    ".wav",
    ".ogg",
    ".flac",
    ".aac",
    ".m4a",
    ".wma",
    ".aiff",
    ".opus",
    # 压缩包
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    ".xz",
    ".tgz",
    ".iso",
    # 可执行与目标文件
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".o",
    ".a",
    ".obj",
    ".lib",
    ".msi",
    ".deb",
    ".rpm",
    # 文档
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    # 字体
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    # 字节码与虚拟机产物
    ".pyc",
    ".pyo",
    ".class",
    ".jar",
    ".war",
    ".ear",
    ".node",
    ".wasm",
    # 数据库
    ".sqlite",
    ".sqlite3",
    ".db",
    ".mdb",
    # 设计与 3D
    ".psd",
    ".ai",
    ".eps",
    ".sketch",
    ".fig",
    ".blend",
}

# 键与值都可能被引号包裹（JSON / TS 对象字面量）；不允许引号就漏掉 ``config.json``
# 这类真正持有明文密钥的文件。值本身不含引号、空格、逗号和分号。
_SECRET_SEPARATOR = r"[\"']?\s*[:=]\s*[\"']?"
_SECRET_VALUE = r"[^\s,;\"']+"

_SECRET_PATTERNS = [
    ("api_key", re.compile(r"(?i)\bapi[_-]?key" + _SECRET_SEPARATOR + _SECRET_VALUE)),
    ("token", re.compile(r"(?i)\btoken" + _SECRET_SEPARATOR + _SECRET_VALUE)),
    ("password", re.compile(r"(?i)\bpassword" + _SECRET_SEPARATOR + _SECRET_VALUE)),
    ("secret", re.compile(r"(?i)\bsecret" + _SECRET_SEPARATOR + _SECRET_VALUE)),
    ("openai_key", re.compile(r"(?<!\w)sk-[A-Za-z0-9_\-]{8,}", re.IGNORECASE)),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}")),
]

_REPEAT_READS_MAX = 4096
_MUTATION_LOCKS_MAX = 1024
_repeat_reads: OrderedDict[str, int] = OrderedDict()
_repeat_lock = threading.Lock()
_mutation_locks: OrderedDict[str, threading.RLock] = OrderedDict()
_mutation_locks_guard = threading.Lock()


def _evict_oldest_half(d: OrderedDict, lock: threading.Lock, max_size: int) -> None:
    """Evict oldest half of *d* when it exceeds *max_size*."""
    if len(d) <= max_size:
        return
    with lock:
        excess = len(d) - max_size // 2
        for _ in range(excess):
            d.popitem(last=False)


@dataclass(frozen=True)
class FileBaseline:
    baseline_id: str
    sha256: str
    size_bytes: int
    modified_at: str | None
    observed_at: str
    path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "baselineId": self.baseline_id,
            "sha256": self.sha256,
            "sizeBytes": self.size_bytes,
            "modifiedAt": self.modified_at,
            "observedAt": self.observed_at,
            "path": self.path,
        }


def _workspace_root() -> Path:
    runtime = current_tool_runtime()
    return runtime.workspace_root if runtime is not None else resolve_workspace_root()


def _file_baseline(path: Path, workspace_root: Path | None = None) -> FileBaseline:
    root = workspace_root or _workspace_root()
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    baseline_id = f"base_{digest[:20]}_{stat.st_size}"
    return FileBaseline(
        baseline_id=baseline_id,
        sha256=digest,
        size_bytes=stat.st_size,
        modified_at=modified_at,
        observed_at=utc_now_iso(),
        path=display_path(path, root),
    )


def _baseline_matches(path: Path, expected_id: str | None, expected_sha: str | None = None) -> bool:
    if not path.exists():
        return False
    baseline = _file_baseline(path)
    if expected_id and expected_id == baseline.baseline_id:
        return True
    if expected_sha and expected_sha == baseline.sha256:
        return True
    return False


def _baseline_error(tool: str, path: Path, *, stale: bool, old_baseline: str | None = None) -> str:
    code = "baseline_stale" if stale else "baseline_required"
    increment_agent_tool_health(
        **({"stale_mutation_rejections": 1} if stale else {"missing_baseline_rejections": 1})
    )
    message = (
        "The file changed since it was observed; read the current file before mutating."
        if stale
        else "Existing file mutation requires a current baseline from read_file."
    )
    return error_json(
        tool,
        code,
        message,
        outcome=OUTCOME_REJECTED,
        next_action="read_file",
        payload={"path": display_path(path, _workspace_root()), "expectedBaselineId": old_baseline},
    )


# 源码文件不做密钥脱敏。源码里的 ``api_key: str`` / ``password: string;`` 是类型声明
# 与变量引用，不是密钥；抹掉它们等于把 agent 要修改的代码本身改坏——它读到
# ``password:***`` 只能靠猜。项目硬规则本就禁止 secret 进源码，真出现了让 agent 看见
# 并上报比静默抹掉更有用。脚本（.sh/.ps1/.bat）不算源码：``export API_KEY=`` 很常见。
# 未列出的类型（配置、文档、无扩展名）一律保持脱敏，fail-safe 方向。
_SOURCE_CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".swift",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".scala",
}


def _redact_for_path(path: Path, text: str) -> tuple[str, list[dict[str, Any]]]:
    if path.suffix.lower() in _SOURCE_CODE_EXTENSIONS:
        return text, []
    return _redact_text(text)


def _redact_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    counts: dict[str, int] = {}
    redacted = text
    for category, pattern in _SECRET_PATTERNS:
        matches = list(pattern.finditer(redacted))
        if not matches:
            continue
        counts[category] = counts.get(category, 0) + len(matches)
        redacted = pattern.sub(lambda match: _redacted_secret(match.group()), redacted)
    return redacted, [
        {"category": category, "count": count} for category, count in sorted(counts.items())
    ]


def _redacted_secret(value: str) -> str:
    lower = value.lower()
    if lower.startswith("sk-"):
        return "sk-***"
    if "bearer" in lower[:16]:
        return value.split()[0] + " ***"
    if "=" in value:
        return value.split("=", 1)[0] + "=***"
    if ":" in value:
        return value.split(":", 1)[0] + ":***"
    return "***"


def _looks_binary(path: Path, sample: bytes) -> bool:
    if path.suffix.lower() in _BINARY_EXTENSIONS:
        return True
    if b"\x00" in sample:
        return True
    if not sample:
        return False
    control = sum(1 for b in sample if b < 9 or (13 < b < 32))
    return control / max(1, len(sample)) > 0.20


def _decode_text(raw: bytes, encoding: str) -> tuple[str, str]:
    selected = encoding or "utf-8"
    if raw.startswith(b"\xef\xbb\xbf") and selected.lower().replace("-", "") == "utf8":
        selected = "utf-8-sig"
    return raw.decode(selected), selected


def _count_total_lines(path: Path) -> int:
    total_newlines = 0
    last_byte = b""
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            total_newlines += chunk.count(b"\n")
            last_byte = chunk[-1:]
    if size == 0:
        return 0
    return total_newlines if last_byte == b"\n" else total_newlines + 1


def _read_raw_line_window(
    path: Path,
    *,
    line_start: int,
    line_count: int,
    byte_cap: int,
) -> tuple[bytes, int, bool]:
    """Read only the requested one-based line window, capped by raw bytes."""
    raw_lines: list[bytes] = []
    consumed = 0
    current_line = 1
    byte_truncated = False
    with path.open("rb") as handle:
        for raw_line in handle:
            if current_line < line_start:
                current_line += 1
                continue
            if len(raw_lines) >= line_count:
                break
            if consumed + len(raw_line) > byte_cap:
                if not raw_lines:
                    remaining = max(0, byte_cap - consumed)
                    raw_lines.append(raw_line[:remaining])
                byte_truncated = True
                break
            raw_lines.append(raw_line)
            consumed += len(raw_line)
            current_line += 1
    if not raw_lines:
        return b"", max(0, line_start - 1), byte_truncated
    return b"".join(raw_lines), line_start + len(raw_lines) - 1, byte_truncated


def _read_permission_error(tool: str, check) -> str:
    outcome = (
        OUTCOME_CONFIRMATION_REQUIRED
        if check.decision.decision == "confirmation_required"
        else OUTCOME_REJECTED
    )
    return error_json(
        tool,
        check.error_code or "permission_denied",
        check.message or "Permission denied.",
        outcome=outcome,
        permission=check.decision,
        next_action="request_confirmation" if outcome == OUTCOME_CONFIRMATION_REQUIRED else None,
        payload={"path": check.classification.display_path},
    )


def read_file_handler(
    path: str,
    startLine: int | None = None,
    maxLines: int | None = None,
    encoding: str = "utf-8",
    includeLineNumbers: bool = True,
    start_line: int | None = None,
    max_lines: int | None = None,
    max_bytes: int | None = None,
) -> str:
    tool = "read_file"
    root = _workspace_root()
    runtime = current_tool_runtime()
    check = permission_for_path(
        path,
        operation="read",
        workspace_root=root,
        session_id=runtime.session_id if runtime is not None else None,
    )
    if not check.allowed:
        return _read_permission_error(tool, check)
    target = check.classification.resolved
    if not target.exists():
        return error_json(tool, "path_not_found", "File does not exist.", outcome=OUTCOME_REJECTED)
    if not target.is_file():
        return error_json(tool, "path_not_file", "Path is not a file.", outcome=OUTCOME_REJECTED)

    max_decode_bytes = get_config_int(
        "get_agent_tools_file_max_decode_bytes", 1_048_576, maximum=10_485_760
    )
    default_max_lines = get_config_int("get_agent_tools_file_default_max_lines", 200, maximum=1000)
    max_window_chars = get_config_int(
        "get_agent_tools_file_max_window_chars", 50_000, maximum=250_000
    )
    requested_start = startLine if startLine is not None else start_line
    requested_max = maxLines if maxLines is not None else max_lines
    line_start = max(1, int(requested_start or 1))
    line_count = max(1, min(int(requested_max or default_max_lines), 1000))
    if max_bytes is not None:
        max_window_chars = max(1, min(int(max_bytes), max_window_chars))

    with target.open("rb") as handle:
        raw_prefix = handle.read(4096)
    if _looks_binary(target, raw_prefix[:4096]):
        return error_json(
            tool,
            "unsupported_binary",
            "Binary or media files are not rendered as text.",
            outcome=OUTCOME_UNSUPPORTED,
            permission=check.decision,
            payload={
                "path": check.classification.display_path,
                "fileType": "binary",
                "sizeBytes": target.stat().st_size,
            },
        )

    size_bytes = target.stat().st_size
    total_lines = _count_total_lines(target)
    raw_for_decode, line_end, byte_truncated = _read_raw_line_window(
        target,
        line_start=line_start,
        line_count=line_count,
        byte_cap=max_decode_bytes,
    )
    if not raw_for_decode:
        line_end = min(line_end, total_lines)
    try:
        text, selected_encoding = _decode_text(raw_for_decode, encoding)
    except UnicodeDecodeError:
        return error_json(
            tool,
            "decode_failed",
            "Could not decode the file with the requested encoding.",
            outcome=OUTCOME_UNSUPPORTED,
            permission=check.decision,
            payload={"path": check.classification.display_path, "encoding": encoding},
        )

    content = "\n".join(text.splitlines())
    char_truncated = False
    if len(content) > max_window_chars:
        content = content[:max_window_chars]
        char_truncated = True
    redacted_content, redactions = _redact_for_path(target, content)
    baseline = _file_baseline(target, root)
    repeat = _record_repeat_read(
        target, line_start, line_count, baseline.baseline_id, selected_encoding
    )
    has_more_after = line_end < total_lines or char_truncated or byte_truncated
    next_token = f"line:{line_end + 1}" if has_more_after else None
    payload: dict[str, Any] = {
        "path": check.classification.display_path,
        "fileType": "text",
        "encoding": selected_encoding,
        "lineStart": line_start,
        "lineEnd": line_end,
        "totalLines": total_lines,
        "hasMoreBefore": line_start > 1,
        "hasMoreAfter": has_more_after,
        "content": redacted_content,
        "baseline": baseline.to_dict(),
        "redactions": redactions,
    }
    if includeLineNumbers:
        payload["lineNumbers"] = [
            {"line": line_start + idx, "text": line}
            for idx, line in enumerate(redacted_content.splitlines())
        ]
    if repeat["seenCount"] > 1:
        payload["repeatRead"] = repeat
    return success_json(
        tool,
        payload,
        permission=check.decision,
        limits={
            "truncated": has_more_after,
            "visibleChars": len(redacted_content),
            "rawBytes": size_bytes,
            "pageSize": line_count,
            "hasMore": has_more_after,
            "nextPageToken": next_token,
            "lineStart": line_start,
            "lineEnd": line_end,
            "capName": "agent_tools.file.max_window_chars" if char_truncated else None,
        },
    )


def _record_repeat_read(
    path: Path,
    line_start: int,
    line_count: int,
    baseline_id: str,
    encoding: str,
) -> dict[str, Any]:
    runtime = current_tool_runtime()
    session_id = runtime.session_id if runtime is not None else "_default_agent_session"
    run_id = "_no_run"
    try:
        from src.business.agents import run_context

        current_run = run_context.get_current()
        if current_run is not None:
            run_id = current_run.run_id
    except Exception:
        run_id = "_no_run"
    key_src = f"{session_id}|{run_id}|{path}|{line_start}|{line_count}|{baseline_id}|{encoding}"
    key = hashlib.sha256(key_src.encode("utf-8", errors="replace")).hexdigest()
    with _repeat_lock:
        _repeat_reads[key] = _repeat_reads.get(key, 0) + 1
        _repeat_reads.move_to_end(key)
        seen = _repeat_reads[key]
    _evict_oldest_half(_repeat_reads, _repeat_lock, _REPEAT_READS_MAX)
    return {
        "windowKey": key,
        "seenCount": seen,
        "recommendation": "request a different window or explain why rereading is intentional",
    }


def _mutation_lock(path: Path) -> threading.RLock:
    key = str(path)
    with _mutation_locks_guard:
        lock = _mutation_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _mutation_locks[key] = lock
        else:
            _mutation_locks.move_to_end(key)
    # Eviction must run AFTER releasing _mutation_locks_guard: _evict_oldest_half
    # reacquires the same Lock, and threading.Lock is non-reentrant — taking it
    # twice on one thread would deadlock once the dict exceeds the cap.
    _evict_oldest_half(_mutation_locks, _mutation_locks_guard, _MUTATION_LOCKS_MAX)
    return lock


def _mutation_permission_error(tool: str, check) -> str:
    return error_json(
        tool,
        check.error_code or "permission_denied",
        check.message or "Mutation rejected before changing files.",
        outcome=OUTCOME_REJECTED,
        permission=check.decision,
        payload={"path": check.classification.display_path},
    )


def write_file_handler(
    path: str,
    content: str,
    expectedBaselineId: str | None = None,
    expectedSha256: str | None = None,
    encoding: str = "utf-8",
    expected_baseline_id: str | None = None,
    expected_sha256: str | None = None,
) -> str:
    tool = "write_file"
    root = _workspace_root()
    check = permission_for_path(path, operation="write", workspace_root=root)
    if not check.allowed:
        return _mutation_permission_error(tool, check)
    target = check.classification.resolved
    expected_id = expectedBaselineId or expected_baseline_id
    expected_sha = expectedSha256 or expected_sha256
    with _mutation_lock(target):
        existed = target.exists()
        old_baseline = (
            _file_baseline(target, root).baseline_id if existed and target.is_file() else None
        )
        if existed:
            if not expected_id and not expected_sha:
                return _baseline_error(tool, target, stale=False, old_baseline=old_baseline)
            if not _baseline_matches(target, expected_id, expected_sha):
                return _baseline_error(tool, target, stale=True, old_baseline=expected_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = str(content).encode(encoding)
        target.write_bytes(data)
        new_baseline = _file_baseline(target, root)
    return success_json(
        tool,
        {
            "path": check.classification.display_path,
            "bytesWritten": len(data),
            "created": not existed,
            "changeSummary": {
                "operation": "create" if not existed else "replace",
                "changedRegions": [
                    {"lineStart": 1, "lineEnd": max(1, str(content).count("\n") + 1)}
                ],
            },
        },
        permission=check.decision,
        verification=VerificationResult(
            "verified",
            old_baseline=old_baseline,
            new_baseline=new_baseline.baseline_id,
            message="write readback matched current baseline",
        ),
    )


def _detect_style(raw: bytes, text: str) -> dict[str, Any]:
    newline = "\r\n" if text.count("\r\n") >= max(text.count("\n"), text.count("\r")) else "\n"
    if "\r" in text and "\n" not in text:
        newline = "\r"
    return {
        "bom": raw.startswith(b"\xef\xbb\xbf"),
        "newline": newline,
        "finalNewline": text.endswith(("\n", "\r")),
        "encoding": "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8",
    }


def _normalize_replacements(
    replacements: list[dict[str, Any]] | None,
    old_text: str | None,
    new_text: str | None,
    replace_all: bool,
) -> list[dict[str, Any]]:
    if replacements is not None:
        return list(replacements)
    if old_text is None:
        return []
    return [{"oldText": old_text, "newText": new_text or "", "replaceAll": replace_all}]


def _plan_replacements(
    text: str, replacements: list[dict[str, Any]]
) -> tuple[list[tuple[int, int, str]], str | None]:
    spans: list[tuple[int, int, str]] = []
    for repl in replacements:
        old = str(repl.get("oldText", ""))
        new = str(repl.get("newText", ""))
        replace_all = bool(repl.get("replaceAll", False))
        if not old:
            return [], "patch_validation_failed"
        positions = [match.start() for match in re.finditer(re.escape(old), text)]
        if not positions:
            return [], "edit_target_not_found"
        if not replace_all and len(positions) > 1:
            return [], "edit_target_not_unique"
        for start in positions if replace_all else positions[:1]:
            spans.append((start, start + len(old), new))
    spans.sort(key=lambda item: item[0])
    for prev, cur in zip(spans, spans[1:]):
        if cur[0] < prev[1]:
            return [], "patch_validation_failed"
    return spans, None


def _apply_spans(text: str, spans: list[tuple[int, int, str]], newline: str) -> str:
    parts: list[str] = []
    cursor = 0
    for start, end, new in spans:
        parts.append(text[cursor:start])
        parts.append(new.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def edit_file_handler(
    path: str,
    expectedBaselineId: str | None = None,
    replacements: list[dict[str, Any]] | None = None,
    old_text: str | None = None,
    new_text: str | None = None,
    replaceAll: bool = False,
    expected_baseline_id: str | None = None,
) -> str:
    tool = "edit_file"
    root = _workspace_root()
    check = permission_for_path(path, operation="edit", workspace_root=root)
    if not check.allowed:
        return _mutation_permission_error(tool, check)
    target = check.classification.resolved
    expected_id = expectedBaselineId or expected_baseline_id
    if not target.exists():
        return error_json(tool, "path_not_found", "File does not exist.", outcome=OUTCOME_REJECTED)
    if not target.is_file():
        return error_json(tool, "path_not_file", "Path is not a file.", outcome=OUTCOME_REJECTED)
    with _mutation_lock(target):
        old_baseline = _file_baseline(target, root)
        if not expected_id:
            return _baseline_error(tool, target, stale=False, old_baseline=old_baseline.baseline_id)
        if expected_id != old_baseline.baseline_id:
            return _baseline_error(tool, target, stale=True, old_baseline=expected_id)
        raw = target.read_bytes()
        try:
            text = raw.decode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8")
        except UnicodeDecodeError:
            return error_json(
                tool,
                "decode_failed",
                "Could not decode file for edit.",
                outcome=OUTCOME_UNSUPPORTED,
            )
        style = _detect_style(raw, text)
        repls = _normalize_replacements(replacements, old_text, new_text, replaceAll)
        spans, error_code = _plan_replacements(text, repls)
        if error_code:
            messages = {
                "edit_target_not_found": "Replacement target was not found.",
                "edit_target_not_unique": "Replacement target is ambiguous.",
                "patch_validation_failed": "Replacement operations overlap or are invalid.",
            }
            return error_json(
                tool,
                error_code,
                messages[error_code],
                outcome=OUTCOME_REJECTED,
                next_action="read_file",
                payload={"path": check.classification.display_path, "replacementCount": len(repls)},
            )
        new_text_value = _apply_spans(text, spans, style["newline"])
        if style["finalNewline"] and not new_text_value.endswith(("\n", "\r")):
            new_text_value += style["newline"]
        target.write_bytes(new_text_value.encode(style["encoding"]))
        new_baseline = _file_baseline(target, root)
    changed_regions = [
        {"lineStart": text[:start].count("\n") + 1, "lineEnd": text[:end].count("\n") + 1}
        for start, end, _ in spans
    ]
    return success_json(
        tool,
        {
            "path": check.classification.display_path,
            "replacementCount": len(spans),
            "changeSummary": {"operation": "edit", "changedRegions": changed_regions},
            "preservedStyle": {
                "newline": (
                    "crlf"
                    if style["newline"] == "\r\n"
                    else "cr" if style["newline"] == "\r" else "lf"
                ),
                "bom": style["bom"],
                "finalNewline": style["finalNewline"],
            },
        },
        permission=check.decision,
        verification=VerificationResult(
            "verified",
            old_baseline=old_baseline.baseline_id,
            new_baseline=new_baseline.baseline_id,
            message="edit writeback matched current baseline",
        ),
    )


def apply_patch_handler(operations: list[dict[str, Any]]) -> str:
    tool = "apply_patch"
    root = _workspace_root()
    if not isinstance(operations, list) or not operations:
        return error_json(
            tool,
            "patch_validation_failed",
            "Patch requires at least one operation.",
            outcome=OUTCOME_REJECTED,
        )
    plans: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for index, op in enumerate(operations):
        op_id = str(op.get("operationId") or f"op{index + 1}")
        op_type = str(op.get("type") or "").lower()
        target_path = op.get("path")
        if op_type not in {"add", "update", "delete"} or not target_path:
            return _patch_rejected(op_id, "patch_validation_failed", "Invalid patch operation.")
        check = permission_for_path(target_path, operation="patch", workspace_root=root)
        if not check.allowed:
            return _patch_rejected(
                op_id,
                check.error_code or "path_outside_workspace",
                check.message or "Unsafe patch target.",
                check.decision,
            )
        target = check.classification.resolved
        target_key = str(target)
        if target_key in seen_targets:
            return _patch_rejected(
                op_id,
                "patch_validation_failed",
                "Patch cannot contain multiple operations for the same path.",
                check.decision,
            )
        seen_targets.add(target_key)
        expected = op.get("expectedBaselineId") or op.get("expected_baseline_id")
        plans.append(
            {
                "op": op,
                "op_id": op_id,
                "type": op_type,
                "path": target,
                "display": check.classification.display_path,
                "permission": check.decision,
                "expected": expected,
            }
        )

    with ExitStack() as stack:
        for target in sorted({plan["path"] for plan in plans}, key=lambda p: str(p)):
            stack.enter_context(_mutation_lock(target))

        prepared: list[dict[str, Any]] = []
        for plan in plans:
            op = plan["op"]
            op_id = plan["op_id"]
            op_type = plan["type"]
            target = plan["path"]
            expected = plan["expected"]
            permission = plan["permission"]
            old_baseline = (
                _file_baseline(target, root).baseline_id
                if target.exists() and target.is_file()
                else None
            )
            if op_type == "add":
                if target.exists():
                    return _patch_rejected(
                        op_id,
                        "patch_validation_failed",
                        "Add operation target already exists.",
                        permission,
                    )
                prepared.append(
                    {
                        **plan,
                        "oldBaseline": None,
                        "newContent": str(op.get("content", "")),
                        "encoding": "utf-8",
                    }
                )
                continue

            if not target.exists():
                return _patch_rejected(
                    op_id, "path_not_found", "Patch target does not exist.", permission
                )
            if not target.is_file():
                return _patch_rejected(
                    op_id, "path_not_file", "Patch target is not a file.", permission
                )
            if not expected:
                return _patch_rejected(
                    op_id,
                    "baseline_required",
                    "Patch update/delete requires a baseline.",
                    permission,
                )
            if expected != old_baseline:
                return _patch_rejected(
                    op_id, "baseline_stale", "Patch baseline is stale.", permission
                )
            if op_type == "delete":
                prepared.append({**plan, "oldBaseline": old_baseline})
                continue

            if "content" in op:
                prepared.append(
                    {
                        **plan,
                        "oldBaseline": old_baseline,
                        "newContent": str(op.get("content", "")),
                        "encoding": "utf-8",
                    }
                )
                continue

            raw = target.read_bytes()
            try:
                text = raw.decode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8")
            except UnicodeDecodeError:
                return _patch_rejected(
                    op_id, "decode_failed", "Could not decode file for patch.", permission
                )
            style = _detect_style(raw, text)
            repls = _normalize_replacements(op.get("replacements"), None, None, False)
            spans, error_code = _plan_replacements(text, repls)
            if error_code:
                messages = {
                    "edit_target_not_found": "Replacement target was not found.",
                    "edit_target_not_unique": "Replacement target is ambiguous.",
                    "patch_validation_failed": "Replacement operations overlap or are invalid.",
                }
                return _patch_rejected(op_id, error_code, messages[error_code], permission)
            new_text_value = _apply_spans(text, spans, style["newline"])
            if style["finalNewline"] and not new_text_value.endswith(("\n", "\r")):
                new_text_value += style["newline"]
            prepared.append(
                {
                    **plan,
                    "oldBaseline": old_baseline,
                    "newContent": new_text_value,
                    "encoding": style["encoding"],
                }
            )

        changed: list[dict[str, Any]] = []
        for plan in prepared:
            target = plan["path"]
            if plan["type"] == "add":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(plan["newContent"], encoding=plan["encoding"])
            elif plan["type"] == "delete":
                target.unlink()
                changed.append(
                    {
                        "operationId": plan["op_id"],
                        "path": plan["display"],
                        "operation": plan["type"],
                        "oldBaseline": plan["oldBaseline"],
                        "newBaseline": None,
                        "verification": "verified",
                    }
                )
                continue
            else:
                target.write_text(plan["newContent"], encoding=plan["encoding"])
            new = _file_baseline(target, root).baseline_id if target.exists() else None
            changed.append(
                {
                    "operationId": plan["op_id"],
                    "path": plan["display"],
                    "operation": plan["type"],
                    "oldBaseline": plan["oldBaseline"],
                    "newBaseline": new,
                    "verification": "verified",
                }
            )
    return success_json(
        tool,
        {
            "affectedFiles": len(changed),
            "changedFiles": changed,
            "rejected": [],
        },
        verification=VerificationResult("verified", message="all patch operations verified"),
    )


def _patch_rejected(
    operation_id: str,
    code: str,
    message: str,
    permission: PermissionDecision | None = None,
) -> str:
    if code == "baseline_stale":
        increment_agent_tool_health(stale_mutation_rejections=1)
    elif code == "baseline_required":
        increment_agent_tool_health(missing_baseline_rejections=1)
    return error_json(
        "apply_patch",
        code,
        message,
        outcome=OUTCOME_REJECTED,
        permission=permission,
        payload={"rejected": [{"operationId": operation_id, "code": code}]},
    )
