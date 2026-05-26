from __future__ import annotations

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


def _normalize_key(key: str) -> str:
    value = _CAMEL_CASE_PATTERN.sub(r"\1_\2", key).lower()
    return value.replace("-", "_")
