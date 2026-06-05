from __future__ import annotations

import ast
import json
import re
from typing import Any

_FORBIDDEN_PAYLOAD_KEYS = {
    "token",
    "runtime_token",
    "session_token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "code",
    "full_code",
    "command",
    "command_body",
    "stack_trace",
    "traceback",
    "database_path",
    "db_path",
    "query_results",
    "raw_query_results",
    "recording_data",
    "unfiltered_recording_data",
    "prompt",
    "raw_prompt",
    "system_prompt",
    "prompt_messages",
    "input_messages",
    "output_content",
    "output_tool_calls",
    "trace_id",
    "trace_ids",
    "llm_trace",
    "handoff",
    "handoff_payload",
    "handoff_detail",
    "correlation_id",
    "causation_trace",
    "source_event",
    "media",
    "media_url",
    "media_bytes",
    "raw_media",
    "base64",
    "image_base64",
}

_DB_EXTENSION_PATTERN = r"\.(sqlite3?|duckdb|db)\b"

_FORBIDDEN_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"MEXEMPLAR_DESKTOP_TOKEN", re.IGNORECASE),
    re.compile(r"Traceback \(most recent call last\):"),
    re.compile(r"data:(?:image|audio|video)/[a-z0-9.+-]+;base64,", re.IGNORECASE),
    re.compile(r"\b(api[_-]?key|password|secret|token)\s*[:=]", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\[^\\\n]+\\[^\\\n]+\\[^\\\n]+" + _DB_EXTENSION_PATTERN, re.IGNORECASE),
]

_CAMEL_CASE_PATTERN = re.compile(r"([a-z0-9])([A-Z])")


def unsafe_public_ui_event_value_reason(
    key: str,
    value: Any,
    *,
    max_preview_chars: int,
) -> str | None:
    normalized_key = _normalize_key(key)
    if normalized_key in _FORBIDDEN_PAYLOAD_KEYS:
        return f"UI event payload key is forbidden: {key}"
    if (
        normalized_key.endswith("path")
        and isinstance(value, str)
        and re.search(_DB_EXTENSION_PATTERN, value, re.IGNORECASE)
    ):
        return f"UI event payload path looks like a local database path: {key}"
    if isinstance(value, str):
        if key == "codePreview" and len(value) > max_preview_chars:
            return "UI event codePreview exceeds the maximum preview length"
        for pattern in _FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                return f"UI event payload value failed safety validation: {key}"
        parsed = _parse_json_container(value)
        if parsed is not None:
            reason = unsafe_public_ui_event_value_reason(
                key,
                parsed,
                max_preview_chars=max_preview_chars,
            )
            if reason is not None:
                return reason
    elif isinstance(value, dict):
        for child_key, child_value in value.items():
            reason = unsafe_public_ui_event_value_reason(
                str(child_key),
                child_value,
                max_preview_chars=max_preview_chars,
            )
            if reason is not None:
                return reason
    elif isinstance(value, list):
        for item in value:
            reason = unsafe_public_ui_event_value_reason(
                key,
                item,
                max_preview_chars=max_preview_chars,
            )
            if reason is not None:
                return reason
    return None


_REDACTED_PLACEHOLDER = "[内容已隐藏]"

# 共享脱敏常量（014-assistant-chat-transparency）：observability 和 ui_event_projector 统一使用。
DEFAULT_PUBLIC_TEXT_MAX_CHARS = 1200
DEFAULT_PUBLIC_TEXT_MAX_LEN = 2000


def redact_public_ui_event_text(
    key: str,
    value: Any,
    *,
    max_preview_chars: int,
    max_len: int | None = None,
) -> Any:
    """把面向 UI 的文本走 009 payload safety allowlist 脱敏（不仅截断）。

    命中 forbidden key / value 规则（私钥、traceback、api_key=、本地 DB 路径等）→ 替换为占位符；
    否则按需截断后原样返回。供 ui_event_projector 与业务读模型（observability）共享，确保实时事件
    与历史 transcript 重建的脱敏口径一致。
    """
    text = _public_text(value)
    truncated = text if max_len is None else text[:max_len]
    validation_value: Any = value if isinstance(value, (dict, list)) else truncated
    reason = unsafe_public_ui_event_value_reason(
        key, validation_value, max_preview_chars=max_preview_chars
    )
    if reason is not None:
        return _REDACTED_PLACEHOLDER
    return truncated


def _normalize_key(key: str) -> str:
    value = _CAMEL_CASE_PATTERN.sub(r"\1_\2", key).lower()
    return value.replace("-", "_")


def _parse_json_container(value: str) -> dict[str, Any] | list[Any] | None:
    stripped = value.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        parsed = json.loads(stripped)
    except (TypeError, ValueError):
        try:
            parsed = ast.literal_eval(stripped)
        except (SyntaxError, ValueError, TypeError):
            return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _public_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    return str(value)
