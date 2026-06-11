"""Shared contract objects for upgraded Agent built-in tools."""

from __future__ import annotations

import contextlib
import json
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1

OUTCOME_SUCCESS = "success"
OUTCOME_ERROR = "error"
OUTCOME_REJECTED = "rejected"
OUTCOME_UNSUPPORTED = "unsupported"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_BACKGROUND_STARTED = "background_started"
OUTCOME_NOT_EXECUTED = "not_executed"
OUTCOME_CONFIRMATION_REQUIRED = "confirmation_required"

OUTCOMES = frozenset(
    {
        OUTCOME_SUCCESS,
        OUTCOME_ERROR,
        OUTCOME_REJECTED,
        OUTCOME_UNSUPPORTED,
        OUTCOME_TIMEOUT,
        OUTCOME_BACKGROUND_STARTED,
        OUTCOME_NOT_EXECUTED,
        OUTCOME_CONFIRMATION_REQUIRED,
    }
)

FAILURE_OUTCOMES = {
    OUTCOME_ERROR,
    OUTCOME_REJECTED,
    OUTCOME_UNSUPPORTED,
    OUTCOME_TIMEOUT,
    OUTCOME_NOT_EXECUTED,
    OUTCOME_CONFIRMATION_REQUIRED,
}

ERROR_CODES = frozenset(
    {
        "path_not_found",
        "path_not_file",
        "path_not_directory",
        "path_outside_workspace",
        "path_hidden_or_system",
        "permission_denied",
        "confirmation_failed_closed",
        "unsupported_binary",
        "decode_failed",
        "baseline_required",
        "baseline_stale",
        "edit_target_not_found",
        "edit_target_not_unique",
        "patch_validation_failed",
        "search_pattern_invalid",
        "command_rejected",
        "command_timeout",
        "process_input_failed",
        "process_limit_reached",
        "process_not_found",
        "process_start_failed",
        "process_stop_failed",
        "process_unavailable_after_restart",
        "output_reference_not_found",
        "output_reference_expired",
        "compaction_failed_fallback",
        "internal_error",
        "unknown_tool",
        "pre_hook_rejected",
        "pre_hook_exception",
        "handler_exception",
        "handler_contract_violation",
        "invalid_model_output",
        "not_executed",
    }
)

UPGRADED_BUILTIN_TOOL_NAMES = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "list_dir",
        "apply_patch",
        "search_files",
        "search_content",
        "exec",
        "process_list",
        "process_poll",
        "process_logs",
        "process_wait",
        "process_stop",
        "process_send_input",
        "process_close",
        "load_tool_output",
    }
)

_ENVELOPE_KEYS = {
    "schemaVersion",
    "tool",
    "outcome",
    "payload",
    "error",
    "permission",
    "limits",
    "references",
    "warnings",
    "verification",
    "createdAt",
}
_OPTIONAL_MAPPING_KEYS = {
    "error": {"code", "message", "retryable", "nextAction", "details"},
    "permission": {"scope", "risk", "decision", "summary", "reason"},
    "limits": {
        "truncated",
        "visibleChars",
        "rawBytes",
        "pageSize",
        "hasMore",
        "nextPageToken",
        "lineStart",
        "lineEnd",
        "capName",
    },
    "verification": {"status", "oldBaseline", "newBaseline", "message"},
}
_REFERENCE_KEYS = {
    "referenceId",
    "kind",
    "sizeBytes",
    "contentType",
    "sha256",
    "expiresAt",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: compact_nested(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [compact_nested(item) for item in value]
    return value


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    retryable: bool = False
    next_action: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.code not in ERROR_CODES:
            code = "internal_error"
            message = f"Unregistered built-in tool error: {self.code}"
        else:
            code = self.code
            message = self.message
        return compact_nested(
            {
                "code": code,
                "message": message,
                "retryable": bool(self.retryable),
                "nextAction": self.next_action,
                "details": self.details,
            }
        )


@dataclass(frozen=True)
class PermissionDecision:
    scope: str
    risk: str
    decision: str
    summary: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return compact_nested(
            {
                "scope": self.scope,
                "risk": self.risk,
                "decision": self.decision,
                "summary": self.summary,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True)
class ToolOutputReference:
    reference_id: str
    kind: str
    size_bytes: int
    content_type: str | None = None
    sha256: str | None = None
    expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return compact_nested(
            {
                "referenceId": self.reference_id,
                "kind": self.kind,
                "sizeBytes": int(self.size_bytes),
                "contentType": self.content_type,
                "sha256": self.sha256,
                "expiresAt": self.expires_at,
            }
        )


@dataclass(frozen=True)
class VerificationResult:
    status: str
    old_baseline: str | None = None
    new_baseline: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return compact_nested(
            {
                "status": self.status,
                "oldBaseline": self.old_baseline,
                "newBaseline": self.new_baseline,
                "message": self.message,
            }
        )


@dataclass(frozen=True)
class ToolRuntimeContext:
    session_id: str
    tool_call_id: str
    tool_name: str
    workspace_root: Path


_CURRENT_TOOL_RUNTIME: ContextVar[ToolRuntimeContext | None] = ContextVar(
    "agent_builtin_tool_runtime", default=None
)


@contextlib.contextmanager
def use_tool_runtime(
    *,
    session_id: str,
    tool_call_id: str,
    tool_name: str,
    workspace_root: Path | str | None = None,
) -> Iterator[None]:
    root = Path(workspace_root or Path.cwd()).expanduser().resolve()
    token = _CURRENT_TOOL_RUNTIME.set(
        ToolRuntimeContext(
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            workspace_root=root,
        )
    )
    try:
        yield
    finally:
        _CURRENT_TOOL_RUNTIME.reset(token)


def current_tool_runtime() -> ToolRuntimeContext | None:
    return _CURRENT_TOOL_RUNTIME.get()


def runtime_session_id(default: str = "_default_agent_session") -> str:
    """Return session_id from current tool runtime, or *default* if not set."""
    ctx = current_tool_runtime()
    return ctx.session_id if ctx is not None else default


def runtime_workspace_root(default: Path | str | None = None) -> Path:
    """Return workspace_root from current tool runtime, resolving *default* if not set."""
    ctx = current_tool_runtime()
    if ctx is not None:
        return ctx.workspace_root
    return Path(default or Path.cwd()).expanduser().resolve()


def envelope_dict(
    *,
    tool: str,
    outcome: str,
    payload: dict[str, Any] | None = None,
    error: ToolError | dict[str, Any] | None = None,
    permission: PermissionDecision | dict[str, Any] | None = None,
    limits: dict[str, Any] | None = None,
    references: list[ToolOutputReference | dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    verification: VerificationResult | dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    if isinstance(error, ToolError):
        error_value = error.to_dict()
    else:
        error_value = error
    if isinstance(permission, PermissionDecision):
        permission_value = permission.to_dict()
    else:
        permission_value = permission
    refs = None
    if references is not None:
        refs = [
            ref.to_dict() if isinstance(ref, ToolOutputReference) else ref for ref in references
        ]
    if isinstance(verification, VerificationResult):
        verification_value = verification.to_dict()
    else:
        verification_value = verification
    obj = compact_nested(
        {
            "schemaVersion": SCHEMA_VERSION,
            "tool": tool,
            "outcome": outcome,
            "payload": compact_nested(payload or {}),
            "error": error_value,
            "permission": permission_value,
            "limits": compact_nested(limits) if limits is not None else None,
            "references": refs,
            "warnings": warnings,
            "verification": (
                compact_nested(verification_value) if verification_value is not None else None
            ),
            "createdAt": created_at or utc_now_iso(),
        }
    )
    if outcome in FAILURE_OUTCOMES and "error" not in obj:
        obj["error"] = ToolError(
            code="internal_error",
            message=f"Built-in tool {tool} returned {outcome} without an error.",
        ).to_dict()
    return obj


def envelope_json(**kwargs: Any) -> str:
    return json.dumps(envelope_dict(**kwargs), ensure_ascii=False, default=str)


def success_json(
    tool: str,
    payload: dict[str, Any],
    *,
    permission: PermissionDecision | dict[str, Any] | None = None,
    limits: dict[str, Any] | None = None,
    references: list[ToolOutputReference | dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    verification: VerificationResult | dict[str, Any] | None = None,
    outcome: str = OUTCOME_SUCCESS,
) -> str:
    return envelope_json(
        tool=tool,
        outcome=outcome,
        payload=payload,
        permission=permission,
        limits=limits,
        references=references,
        warnings=warnings,
        verification=verification,
    )


def error_json(
    tool: str,
    code: str,
    message: str,
    *,
    outcome: str = OUTCOME_ERROR,
    retryable: bool = False,
    next_action: str | None = None,
    details: dict[str, Any] | None = None,
    permission: PermissionDecision | dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    references: list[ToolOutputReference | dict[str, Any]] | None = None,
) -> str:
    return envelope_json(
        tool=tool,
        outcome=outcome,
        payload=payload or {},
        error=ToolError(code, message, retryable, next_action, details),
        permission=permission,
        warnings=warnings,
        references=references,
    )


def parse_envelope(value: str) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    candidate = value.lstrip()
    if not candidate.startswith("{"):
        return None
    try:
        obj = json.loads(candidate)
    except (TypeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    if not set(obj).issubset(_ENVELOPE_KEYS):
        return None
    if obj.get("schemaVersion") != SCHEMA_VERSION:
        return None
    if not isinstance(obj.get("tool"), str) or not obj["tool"]:
        return None
    if obj.get("outcome") not in OUTCOMES:
        return None
    if not isinstance(obj.get("payload"), dict):
        return None
    if not isinstance(obj.get("createdAt"), str) or not obj["createdAt"]:
        return None
    if obj["outcome"] in FAILURE_OUTCOMES and not isinstance(obj.get("error"), dict):
        return None
    expected_types = {
        "error": dict,
        "permission": dict,
        "limits": dict,
        "references": list,
        "warnings": list,
        "verification": dict,
    }
    for key, expected_type in expected_types.items():
        if key in obj and not isinstance(obj[key], expected_type):
            return None
    for key, allowed_keys in _OPTIONAL_MAPPING_KEYS.items():
        if key in obj and not set(obj[key]).issubset(allowed_keys):
            return None
    if "error" in obj:
        error = obj["error"]
        if (
            error.get("code") not in ERROR_CODES
            or not isinstance(error.get("message"), str)
            or not isinstance(error.get("retryable"), bool)
        ):
            return None
    if "references" in obj:
        for reference in obj["references"]:
            if not isinstance(reference, dict) or not set(reference).issubset(_REFERENCE_KEYS):
                return None
            if not isinstance(reference.get("referenceId"), str):
                return None
    if "warnings" in obj and not all(isinstance(item, str) for item in obj["warnings"]):
        return None
    return obj


def is_tool_failure_result(value: str) -> bool:
    obj = parse_envelope(value)
    return bool(obj and obj.get("outcome") in FAILURE_OUTCOMES)


def standardized_error_to_envelope(tool: str, value: str) -> str | None:
    if not isinstance(value, str) or not value.startswith("{"):
        return None
    try:
        obj = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    code = obj.get("error")
    message = obj.get("message")
    if isinstance(code, str) and code:
        details = {k: v for k, v in obj.items() if k not in {"error", "message"}}
        return error_json(
            tool,
            code if code in ERROR_CODES else "internal_error",
            str(message or code),
            outcome=OUTCOME_NOT_EXECUTED if code == "not_executed" else OUTCOME_REJECTED,
            details=details or None,
        )
    if obj.get("success") is False:
        if "message" in obj:
            return error_json(tool, "internal_error", str(obj["message"]))
        if isinstance(obj.get("error"), str) and obj["error"]:
            return error_json(tool, "internal_error", str(obj["error"]))
    return None


def truncate_with_marker(text: str, cap: int) -> tuple[str, bool]:
    """Truncate *text* to *cap* chars by keeping head + tail with a marker.

    Returns (truncated_text, was_truncated).
    """
    if len(text) <= cap:
        return text, False
    if cap <= 0:
        return "", True
    marker = "\n...[truncated]...\n"
    if cap <= len(marker) + 2:
        return text[:cap], True
    available = cap - len(marker)
    head = max(1, available // 2)
    tail = max(0, available - head)
    return text[:head] + marker + (text[-tail:] if tail else ""), True
