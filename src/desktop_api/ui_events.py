from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from src.business.services.ui_event_safety_service import unsafe_public_ui_event_value_reason
from src.desktop_api.schemas import UiEvent
from src.desktop_api.ui_event_types import UiEventDraft

logger = logging.getLogger(__name__)

UiEventCategory = Literal["notification", "interactive", "control"]
TrialPreviewDecision = Literal["approve", "deny"]
TrialPreviewStatus = Literal[
    "pending",
    "approved",
    "denied",
    "timeout",
    "disconnect",
    "overflow",
    "shutdown",
    "already_resolved",
    "conflict",
    "expired",
]

_MAX_PREVIEW_CHARS = 1200
_DEFAULT_PREVIEW_TIMEOUT_SECONDS = 30.0
_SESSION_SCOPE = frozenset({"sessionId"})


@dataclass(frozen=True)
class UiEventDefinition:
    event_type: str
    category: UiEventCategory
    payload_keys: frozenset[str]
    scope_keys: frozenset[str]
    example: dict[str, Any]
    required_payload_keys: frozenset[str] = frozenset()
    required_scope_keys: frozenset[str] = frozenset()
    payload_enum_values: tuple[tuple[str, frozenset[str]], ...] = ()
    # 这些字段有意保留原文（UI 默认隐藏 + 双击查看），跳过 forbidden value 脱敏校验。
    unredacted_payload_keys: frozenset[str] = frozenset()


class UiEventValidationError(ValueError):
    """Raised when a public UI event violates the registered contract."""


CONFIRMATION_VALID_ACTION_TYPES: frozenset[str] = frozenset(
    {"write_file", "edit_file", "exec", "unknown", "skill.edit_protected", "skill.soft_delete"}
)

UI_EVENT_REGISTRY: dict[str, UiEventDefinition] = {
    "assistant.message": UiEventDefinition(
        "assistant.message",
        "notification",
        frozenset({"sequence", "role", "content", "createdAt", "rendering", "failure"}),
        frozenset({"sessionId"}),
        {"sequence": 1, "role": "assistant", "content": "Ready.", "rendering": "safe_markdown"},
        required_payload_keys=frozenset({"sequence", "role", "content", "rendering"}),
        required_scope_keys=frozenset({"sessionId"}),
        payload_enum_values=(
            ("role", frozenset({"user", "assistant", "summary"})),
            ("rendering", frozenset({"plain_text", "safe_markdown"})),
        ),
    ),
    "assistant.progress": UiEventDefinition(
        "assistant.progress",
        "notification",
        frozenset({"status", "headline", "message", "question", "runId"}),
        frozenset({"sessionId", "workflowId"}),
        {"status": "running", "headline": "Assistant is working", "runId": "run-1"},
        required_payload_keys=frozenset({"status"}),
        required_scope_keys=frozenset({"sessionId"}),
        payload_enum_values=(
            (
                "status",
                frozenset({"running", "waiting_for_user", "succeeded", "failed", "cancelled"}),
            ),
        ),
    ),
    "assistant.error": UiEventDefinition(
        "assistant.error",
        "notification",
        frozenset({"message", "type"}),
        frozenset({"sessionId", "workflowId"}),
        {"message": "Assistant failed to complete the request.", "type": "RuntimeError"},
        required_payload_keys=frozenset({"message"}),
        required_scope_keys=frozenset({"sessionId"}),
    ),
    "assistant.confirmation": UiEventDefinition(
        "assistant.confirmation",
        "interactive",
        frozenset(
            {
                "requestId",
                "actionType",
                "sanitizedSummary",
                "status",
                "sessionId",
                "remainingMs",
                "expiresAt",
                "affectedSkillId",
                "affectedEquipmentCount",
                "affectedSpecialistNames",
            }
        ),
        frozenset({"sessionId"}),
        {
            "requestId": "req_1",
            "actionType": "exec",
            "sanitizedSummary": "命令首行: npm test",
            "status": "active",
        },
        required_payload_keys=frozenset({"requestId", "actionType", "sanitizedSummary", "status"}),
        required_scope_keys=frozenset({"sessionId"}),
        payload_enum_values=(
            ("actionType", CONFIRMATION_VALID_ACTION_TYPES),
            ("status", frozenset({"active"})),
        ),
    ),
    "assistant.clarification_requested": UiEventDefinition(
        "assistant.clarification_requested",
        "interactive",
        frozenset({"requestId", "sessionId", "questions", "expiresAt", "status"}),
        frozenset({"sessionId"}),
        {
            "requestId": "clr_1",
            "sessionId": "sess_1",
            "questions": [
                {
                    "questionId": "q1",
                    "question": "选择执行方式？",
                    "header": "执行方式",
                    "multiSelect": False,
                    "options": [{"optionId": "q1o1", "label": "按顺序执行"}],
                }
            ],
            "expiresAt": "2026-06-15T08:05:00Z",
            "status": "pending",
        },
        required_payload_keys=frozenset({"requestId", "sessionId", "questions", "status"}),
        required_scope_keys=frozenset({"sessionId"}),
        payload_enum_values=(("status", frozenset({"pending"})),),
    ),
    "assistant.clarification_resolved": UiEventDefinition(
        "assistant.clarification_resolved",
        "interactive",
        frozenset({"requestId", "sessionId", "status"}),
        frozenset({"sessionId"}),
        {"requestId": "clr_1", "sessionId": "sess_1", "status": "answered"},
        required_payload_keys=frozenset({"requestId", "sessionId", "status"}),
        required_scope_keys=frozenset({"sessionId"}),
        payload_enum_values=(
            (
                "status",
                frozenset({"answered", "cancelled", "timeout", "stopped", "shutdown"}),
            ),
        ),
    ),
    "assistant.activity": UiEventDefinition(
        "assistant.activity",
        "notification",
        frozenset({"subagentId", "kind", "toolName", "text", "seq", "redacted"}),
        frozenset({"sessionId"}),
        {"kind": "tool_call", "toolName": "delegate_to_subagent", "text": "派发子任务", "seq": 1},
        required_payload_keys=frozenset({"kind", "seq"}),
        required_scope_keys=frozenset({"sessionId"}),
        payload_enum_values=(("kind", frozenset({"reasoning", "tool_call", "tool_result"})),),
        unredacted_payload_keys=frozenset({"text"}),
    ),
    "assistant.subagent": UiEventDefinition(
        "assistant.subagent",
        "notification",
        frozenset({"subagentId", "label", "task", "status", "lastOutput", "reason"}),
        frozenset({"sessionId"}),
        {
            "subagentId": "sess_child_1",
            "label": "子助手 · 资料检索",
            "task": "检索最新季度报表",
            "status": "running",
        },
        required_payload_keys=frozenset({"subagentId", "status"}),
        required_scope_keys=frozenset({"sessionId"}),
        payload_enum_values=(("status", frozenset({"running", "done", "suspended", "failed"})),),
    ),
    "assistant.task_graph.changed": UiEventDefinition(
        "assistant.task_graph.changed",
        "notification",
        frozenset(
            {
                "graphId",
                "taskId",
                "changeType",
                "status",
                "displayPhase",
                "requiresReview",
                "safeExplanation",
                "suspendReason",
                "sequence",
            }
        ),
        _SESSION_SCOPE,
        {
            "graphId": "tg_123",
            "taskId": "tsk_1",
            "changeType": "task_updated",
            "status": "running",
            "displayPhase": "reviewing",
            "requiresReview": True,
            "safeExplanation": "等待上级检查结果",
            "suspendReason": None,
            "sequence": 42,
        },
        required_payload_keys=frozenset({"graphId", "changeType"}),
        required_scope_keys=_SESSION_SCOPE,
        payload_enum_values=(
            (
                "changeType",
                frozenset(
                    {
                        "graph_created",
                        "task_created",
                        "task_updated",
                        "edge_created",
                        "adjudication_created",
                        "adjudication_decided",
                        "graph_completed",
                        "graph_stopped",
                        "graph_continued",
                        "graph_cancelled",
                        "root_failed",
                    }
                ),
            ),
            (
                "status",
                frozenset(
                    {
                        "pending_dispatch",
                        "running",
                        "suspended",
                        "completed",
                        "failed",
                        "cancelled",
                    }
                ),
            ),
            (
                "displayPhase",
                frozenset({"running", "reviewing", "needs_attention", "paused", "done"}),
            ),
            (
                "suspendReason",
                frozenset({"waiting_user", "waiting_system", "user_stop"}),
            ),
        ),
    ),
    "assistant.task_board.changed": UiEventDefinition(
        "assistant.task_board.changed",
        "notification",
        frozenset({"taskId", "graphId", "changeType", "claimStatus", "updatedAt"}),
        _SESSION_SCOPE,
        {"taskId": "tsk_9", "graphId": "tg_123", "changeType": "claimed"},
        required_payload_keys=frozenset({"taskId", "changeType"}),
        required_scope_keys=_SESSION_SCOPE,
        payload_enum_values=(
            (
                "changeType",
                frozenset({"opened", "claimed", "released", "expired", "completed", "rejected"}),
            ),
        ),
    ),
    "assistant.task_question.changed": UiEventDefinition(
        "assistant.task_question.changed",
        "notification",
        frozenset({"questionId", "taskId", "graphId", "kind", "status", "changeType"}),
        _SESSION_SCOPE,
        {
            "questionId": "qst_1",
            "taskId": "tsk_1",
            "graphId": "tg_123",
            "kind": "resource_request",
            "status": "escalated_to_parent",
            "changeType": "created",
        },
        required_payload_keys=frozenset({"questionId", "taskId", "changeType"}),
        required_scope_keys=_SESSION_SCOPE,
        payload_enum_values=(
            ("kind", frozenset({"clarification", "resource_request", "capability_request"})),
            (
                "status",
                frozenset(
                    {
                        "open",
                        "escalated_to_parent",
                        "escalated_to_user",
                        "answered",
                        "cancelled",
                        "expired",
                    }
                ),
            ),
            (
                "changeType",
                frozenset({"created", "escalated_to_user", "answered", "cancelled", "expired"}),
            ),
        ),
    ),
    "assistant.meeting.changed": UiEventDefinition(
        "assistant.meeting.changed",
        "notification",
        frozenset({"channelId", "graphId", "taskId", "changeType", "sequence", "status"}),
        _SESSION_SCOPE,
        {"channelId": "mtg_1", "graphId": "tg_123", "changeType": "message_added"},
        required_payload_keys=frozenset({"channelId", "changeType"}),
        required_scope_keys=_SESSION_SCOPE,
        payload_enum_values=(
            (
                "changeType",
                frozenset(
                    {
                        "opened",
                        "message_added",
                        "concluded",
                        "closed_timeout",
                        "closed_abandoned",
                    }
                ),
            ),
        ),
    ),
    "assistant.todo.changed": UiEventDefinition(
        "assistant.todo.changed",
        "notification",
        frozenset({"taskId", "todoId", "changeType", "status", "sortOrder"}),
        _SESSION_SCOPE,
        {"taskId": "tsk_1", "todoId": "todo_1", "changeType": "updated"},
        required_payload_keys=frozenset({"taskId", "todoId", "changeType"}),
        required_scope_keys=_SESSION_SCOPE,
        payload_enum_values=(
            ("changeType", frozenset({"created", "updated", "deleted", "reordered"})),
            ("status", frozenset({"todo", "doing", "done", "skipped"})),
        ),
    ),
    "recording.progress": UiEventDefinition(
        "recording.progress",
        "notification",
        frozenset(
            {
                "status",
                "message",
                "headline",
                "recordingMode",
                "actionCount",
                "degraded",
                "subsystem",
                "error",
            }
        ),
        frozenset({"workflowId"}),
        {"status": "recording", "message": "Recording started.", "recordingMode": "desktop"},
        required_payload_keys=frozenset({"status"}),
        required_scope_keys=frozenset({"workflowId"}),
    ),
    "teaching.stage_changed": UiEventDefinition(
        "teaching.stage_changed",
        "notification",
        frozenset(
            {"stage", "status", "message", "headline", "failureStage", "successCount", "published"}
        ),
        frozenset({"workflowId"}),
        {"stage": "learning", "message": "Tool learning started."},
        required_payload_keys=frozenset({"stage"}),
        required_scope_keys=frozenset({"workflowId"}),
        payload_enum_values=(
            (
                "stage",
                frozenset(
                    {
                        "selecting",
                        "recording",
                        "intent_confirmation",
                        "learning",
                        "trial_validation",
                        "published",
                        "failed",
                        "abandoned",
                    }
                ),
            ),
        ),
    ),
    "teaching.progress": UiEventDefinition(
        "teaching.progress",
        "notification",
        frozenset({"status", "message", "headline", "question", "failureStage", "error", "type"}),
        frozenset({"workflowId", "sessionId"}),
        {"status": "running", "headline": "Tool learning started"},
        required_payload_keys=frozenset({"status"}),
        required_scope_keys=frozenset({"workflowId"}),
    ),
    "trial.progress": UiEventDefinition(
        "trial.progress",
        "notification",
        frozenset(
            {
                "status",
                "message",
                "headline",
                "toolId",
                "successCount",
                "published",
                "trialId",
                "result",
                "error",
                "type",
            }
        ),
        frozenset({"workflowId", "toolId"}),
        {"status": "succeeded", "published": False, "successCount": 1},
        required_payload_keys=frozenset({"status"}),
        required_scope_keys=frozenset({"workflowId"}),
    ),
    "trial.preview_requested": UiEventDefinition(
        "trial.preview_requested",
        "interactive",
        frozenset(
            {
                "requestId",
                "workflowId",
                "trialId",
                "summary",
                "codePreview",
                "riskSummary",
                "expires_at",
                "status",
            }
        ),
        frozenset({"workflowId"}),
        {
            "requestId": "preview_1",
            "workflowId": "rec_1",
            "trialId": "trial_1",
            "summary": "桌面试用需要确认。",
            "codePreview": "async def execute(): ...",
            "riskSummary": "将控制本机桌面。",
            "expires_at": "2026-05-16T00:00:30Z",
            "status": "pending",
        },
        required_payload_keys=frozenset(
            {
                "requestId",
                "workflowId",
                "trialId",
                "summary",
                "codePreview",
                "riskSummary",
                "expires_at",
                "status",
            }
        ),
        required_scope_keys=frozenset({"workflowId"}),
        payload_enum_values=(("status", frozenset({"pending"})),),
    ),
    "trial.preview_resolved": UiEventDefinition(
        "trial.preview_resolved",
        "interactive",
        frozenset({"requestId", "workflowId", "trialId", "decision", "status", "message"}),
        frozenset({"workflowId"}),
        {
            "requestId": "preview_1",
            "workflowId": "rec_1",
            "trialId": "trial_1",
            "decision": "deny",
            "status": "timeout",
        },
        required_payload_keys=frozenset({"requestId", "workflowId", "decision", "status"}),
        required_scope_keys=frozenset({"workflowId"}),
        payload_enum_values=(
            ("decision", frozenset({"approve", "deny"})),
            (
                "status",
                frozenset(
                    {
                        "approved",
                        "denied",
                        "timeout",
                        "disconnect",
                        "overflow",
                        "shutdown",
                        "already_resolved",
                        "conflict",
                        "expired",
                    }
                ),
            ),
        ),
    ),
    "tools.changed": UiEventDefinition(
        "tools.changed",
        "notification",
        frozenset({"reason", "toolId", "status"}),
        frozenset({"toolId"}),
        {"reason": "catalog_invalidated"},
    ),
    "skill.changed": UiEventDefinition(
        "skill.changed",
        "notification",
        frozenset(
            {
                "reason",
                "skillId",
                "chainRootId",
                "newSkillId",
                "callerType",
                "callerId",
                "bootstrapFallbackUsed",
                "bootstrapFallbackInfo",
            }
        ),
        frozenset({"skillId"}),
        {
            "reason": "create",
            "skillId": "skl_abc",
            "chainRootId": "skl_abc",
        },
        required_payload_keys=frozenset({"reason", "skillId", "chainRootId"}),
        required_scope_keys=frozenset({"skillId"}),
        payload_enum_values=(
            (
                "reason",
                frozenset(
                    {
                        "create",
                        "supersede",
                        "user_edit",
                        "soft_delete",
                        "bootstrap_fallback_used",
                    }
                ),
            ),
            ("callerType", frozenset({"assistant", "specialist", "user", "system"})),
        ),
    ),
    "skill.equipment.changed": UiEventDefinition(
        "skill.equipment.changed",
        "notification",
        frozenset(
            {
                "changeType",
                "entityType",
                "entityId",
                "skillId",
                "unequippedReason",
            }
        ),
        frozenset({"entityId", "skillId"}),
        {
            "changeType": "equipped",
            "entityType": "assistant",
            "entityId": "_assistant",
            "skillId": "skl_abc",
        },
        required_payload_keys=frozenset({"changeType", "entityType", "entityId", "skillId"}),
        payload_enum_values=(
            (
                "changeType",
                frozenset(
                    {
                        "equipped",
                        "unequipped",
                        "reorder",
                        "supersede_transfer",
                        "force_remove_on_soft_delete",
                        "default_propagate",
                    }
                ),
            ),
            ("entityType", frozenset({"assistant", "specialist"})),
        ),
    ),
    "compositions.changed": UiEventDefinition(
        "compositions.changed",
        "notification",
        frozenset({"reason", "compositionId", "status"}),
        frozenset({"compositionId"}),
        {"reason": "catalog_invalidated"},
    ),
    "settings.changed": UiEventDefinition(
        "settings.changed",
        "notification",
        frozenset({"reason", "keys"}),
        frozenset(),
        {"reason": "settings_invalidated", "keys": []},
        required_payload_keys=frozenset({"reason"}),
    ),
    "backend.resync_required": UiEventDefinition(
        "backend.resync_required",
        "control",
        frozenset({"reason", "domains", "lastAvailableSequence", "eventSessionId"}),
        frozenset({"workflowId", "sessionId", "toolId", "compositionId"}),
        {"reason": "replay_gap", "domains": ["teaching", "tools", "brain", "skill"]},
        required_payload_keys=frozenset({"reason", "domains"}),
    ),
    "brain_zone_changed": UiEventDefinition(
        "brain_zone_changed",
        "notification",
        frozenset({"zone", "entryId", "changeType"}),
        frozenset(),
        {"zone": "hot", "entryId": "entry_1", "changeType": "create"},
        required_payload_keys=frozenset({"zone", "changeType"}),
    ),
    "brain_specialist_recruited": UiEventDefinition(
        "brain_specialist_recruited",
        "notification",
        frozenset({"specialistId", "name", "reason", "managementUrl"}),
        frozenset(),
        {
            "specialistId": "spec_1",
            "name": "报表专员",
            "reason": "检测到持续报表委托",
            "managementUrl": "/brain/specialists",
        },
        required_payload_keys=frozenset({"specialistId", "name", "reason"}),
    ),
    "brain_specialist_changed": UiEventDefinition(
        "brain_specialist_changed",
        "notification",
        frozenset({"specialistId", "changeType"}),
        frozenset(),
        {"specialistId": "spec_1", "changeType": "update"},
        required_payload_keys=frozenset({"specialistId", "changeType"}),
    ),
    "brain_context_ready": UiEventDefinition(
        "brain_context_ready",
        "notification",
        frozenset({"sessionId"}),
        frozenset({"sessionId"}),
        {"sessionId": "sess_1"},
        required_payload_keys=frozenset({"sessionId"}),
        required_scope_keys=frozenset({"sessionId"}),
    ),
}


def registered_event_types() -> list[str]:
    return sorted(UI_EVENT_REGISTRY)


def exported_registry_examples() -> dict[str, dict[str, Any]]:
    return {
        event_type: dict(definition.example) for event_type, definition in UI_EVENT_REGISTRY.items()
    }


def exported_registry_payload_enums() -> dict[str, dict[str, list[str]]]:
    return {
        event_type: {key: sorted(values) for key, values in definition.payload_enum_values}
        for event_type, definition in UI_EVENT_REGISTRY.items()
        if definition.payload_enum_values
    }


def validate_ui_event_payload(event_type: str, payload: dict[str, Any]) -> None:
    definition = UI_EVENT_REGISTRY.get(event_type)
    if definition is None:
        raise UiEventValidationError(f"unregistered UI event type: {event_type}")
    extra_keys = set(payload) - set(definition.payload_keys)
    if extra_keys:
        raise UiEventValidationError(
            f"UI event {event_type} contains non-allowlisted payload keys: {sorted(extra_keys)}"
        )
    missing_keys = {
        key
        for key in definition.required_payload_keys
        if key not in payload or payload[key] is None
    }
    if missing_keys:
        raise UiEventValidationError(
            f"UI event {event_type} is missing required payload keys: {sorted(missing_keys)}"
        )
    for key, allowed_values in definition.payload_enum_values:
        if key in payload and payload[key] is not None and str(payload[key]) not in allowed_values:
            raise UiEventValidationError(
                f"UI event {event_type} contains invalid enum value for {key}: {payload[key]}"
            )
    if event_type == "assistant.message" and payload.get("failure") is not None:
        _validate_assistant_failure_payload(payload)
    for key, value in payload.items():
        if key in definition.unredacted_payload_keys:
            continue  # 有意保留原文（UI 默认隐藏 + 双击查看），不做 forbidden value 脱敏校验
        _validate_payload_value(key, value)


def _validate_assistant_failure_payload(payload: dict[str, Any]) -> None:
    if payload.get("role") != "user":
        raise UiEventValidationError("assistant.message failure is only valid for user messages")
    failure = payload.get("failure")
    if not isinstance(failure, dict):
        raise UiEventValidationError("assistant.message failure must be an object")
    expected = {"category", "message", "suggestion", "attemptCount", "failedAt"}
    if set(failure) != expected:
        raise UiEventValidationError("assistant.message failure contains invalid fields")
    if failure.get("category") not in {
        "authentication",
        "invalid_request",
        "quota",
        "network",
        "provider",
        "iteration_limit",
        "internal",
    }:
        raise UiEventValidationError("assistant.message failure category is invalid")
    if not isinstance(failure.get("message"), str) or not isinstance(
        failure.get("suggestion"), str
    ):
        raise UiEventValidationError("assistant.message failure copy is invalid")
    if not isinstance(failure.get("attemptCount"), int) or failure["attemptCount"] < 1:
        raise UiEventValidationError("assistant.message failure attemptCount is invalid")
    failed_at = failure.get("failedAt")
    if not isinstance(failed_at, str):
        raise UiEventValidationError("assistant.message failure failedAt is invalid")
    try:
        datetime.fromisoformat(failed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UiEventValidationError("assistant.message failure failedAt is invalid") from exc


def build_ui_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    scope: dict[str, str] | None,
    sequence: int,
    session_id: str,
    causation_id: str | None = None,
) -> UiEvent:
    validate_ui_event_payload(event_type, payload)
    definition = UI_EVENT_REGISTRY[event_type]
    normalized_scope = {
        key: str(value) for key, value in (scope or {}).items() if value is not None
    }
    extra_scope = set(normalized_scope) - set(definition.scope_keys)
    if extra_scope:
        raise UiEventValidationError(
            f"UI event {event_type} contains non-allowlisted scope keys: {sorted(extra_scope)}"
        )
    missing_scope = set(definition.required_scope_keys) - set(normalized_scope)
    if missing_scope:
        raise UiEventValidationError(
            f"UI event {event_type} is missing required scope keys: {sorted(missing_scope)}"
        )
    if (
        "workflowId" in payload
        and "workflowId" in normalized_scope
        and str(payload["workflowId"]) != normalized_scope["workflowId"]
    ):
        raise UiEventValidationError("UI event workflowId payload and scope do not match")
    return UiEvent(
        eventId=f"evt_{uuid4().hex[:12]}",
        sequence=sequence,
        sessionId=session_id,
        causationId=causation_id,
        type=event_type,
        scope=normalized_scope,
        payload=payload,
        createdAt=datetime.now(timezone.utc),
    )


@dataclass
class TrialPreviewRecord:
    request_id: str
    workflow_id: str
    trial_id: str
    expires_at: datetime
    decision: TrialPreviewDecision | None = None
    status: TrialPreviewStatus = "pending"


class TrialPreviewRequestManager:
    def __init__(self) -> None:
        self._records: dict[str, TrialPreviewRecord] = {}
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def create_request(
        self,
        *,
        workflow_id: str,
        trial_id: str,
        code_preview: str,
        publish: Callable[[UiEventDraft], None],
        timeout_seconds: float = _DEFAULT_PREVIEW_TIMEOUT_SECONDS,
    ) -> bool:
        request_id = f"preview_{uuid4().hex[:12]}"
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(timeout_seconds, 0.01))
        record = TrialPreviewRecord(
            request_id=request_id,
            workflow_id=workflow_id,
            trial_id=trial_id,
            expires_at=expires_at,
        )
        payload = {
            "requestId": request_id,
            "workflowId": workflow_id,
            "trialId": trial_id,
            "summary": "桌面试用需要确认。",
            "codePreview": _truncate_preview(code_preview),
            "riskSummary": "该试用可能控制本机桌面，请确认预览内容后继续。",
            "expires_at": expires_at.isoformat(),
            "status": "pending",
        }
        try:
            validate_ui_event_payload("trial.preview_requested", payload)
        except UiEventValidationError as exc:
            logger.warning(
                "Rejected unsafe trial preview request",
                extra={"workflow_id": workflow_id, "trial_id": trial_id},
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            return False
        wait_event = threading.Event()
        with self._lock:
            self._records[request_id] = record
            self._events[request_id] = wait_event
        publish(
            UiEventDraft(
                "trial.preview_requested",
                payload,
                {"workflowId": workflow_id},
                workflow_id,
            )
        )
        wait_event.wait(max((expires_at - datetime.now(timezone.utc)).total_seconds(), 0.01))
        with self._lock:
            current = self._records.get(request_id)
            if current is None:
                return False
            if current.status == "pending":
                current.status = "timeout"
                current.decision = "deny"
                wait_event.set()
                should_publish_timeout = True
            else:
                should_publish_timeout = False
            decision = current.decision
            status = current.status
        if should_publish_timeout:
            publish(self._resolved_draft(current, "Preview request expired."))
        return decision == "approve" and status == "approved"

    def fail_pending(
        self, status: Literal["disconnect", "overflow", "shutdown"]
    ) -> list[UiEventDraft]:
        messages = {
            "disconnect": "Preview request denied because the event stream disconnected.",
            "overflow": "Preview request denied because an event subscriber overflowed.",
            "shutdown": "Preview request denied because the application is shutting down.",
        }
        resolved: list[UiEventDraft] = []
        with self._lock:
            for record in self._records.values():
                if record.status != "pending":
                    continue
                record.status = status
                record.decision = "deny"
                event = self._events.get(record.request_id)
                if event is not None:
                    event.set()
                resolved.append(self._resolved_draft(record, messages[status]))
        return resolved

    def record_decision(self, request_id: str, decision: TrialPreviewDecision) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return {
                    "requestId": request_id,
                    "decision": decision,
                    "accepted": False,
                    "status": "already_resolved",
                }
            if record.status != "pending":
                status: TrialPreviewStatus = (
                    "already_resolved" if record.decision == decision else "conflict"
                )
                return self._decision_result(record, decision, accepted=False, status=status)
            if now >= record.expires_at:
                record.status = "timeout"
                record.decision = "deny"
                event = self._events.get(request_id)
                if event is not None:
                    event.set()
                return self._decision_result(record, decision, accepted=False, status="expired")
            record.decision = decision
            record.status = "approved" if decision == "approve" else "denied"
            event = self._events.get(request_id)
            if event is not None:
                event.set()
            return self._decision_result(record, decision, accepted=True, status=record.status)

    def clear_for_tests(self) -> None:
        with self._lock:
            self._records.clear()
            self._events.clear()

    @staticmethod
    def _resolved_draft(record: TrialPreviewRecord, message: str) -> UiEventDraft:
        return UiEventDraft(
            "trial.preview_resolved",
            {
                "requestId": record.request_id,
                "workflowId": record.workflow_id,
                "trialId": record.trial_id,
                "decision": record.decision or "deny",
                "status": record.status,
                "message": message,
            },
            {"workflowId": record.workflow_id},
            record.workflow_id,
        )

    @staticmethod
    def _decision_result(
        record: TrialPreviewRecord,
        requested_decision: TrialPreviewDecision,
        *,
        accepted: bool,
        status: TrialPreviewStatus,
    ) -> dict[str, Any]:
        return {
            "requestId": record.request_id,
            "decision": requested_decision,
            "accepted": accepted,
            "status": status,
            "workflowId": record.workflow_id,
            "trialId": record.trial_id,
            "eventDecision": record.decision or requested_decision,
            "eventStatus": status,
        }


trial_preview_manager = TrialPreviewRequestManager()


def _validate_payload_value(key: str, value: Any) -> None:
    reason = unsafe_public_ui_event_value_reason(
        key,
        value,
        max_preview_chars=_MAX_PREVIEW_CHARS,
    )
    if reason is not None:
        raise UiEventValidationError(reason)


def _truncate_preview(value: str) -> str:
    if len(value) <= _MAX_PREVIEW_CHARS:
        return value
    return value[: _MAX_PREVIEW_CHARS - 1] + "…"


def _without_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def normalize_draft(draft: UiEventDraft) -> UiEventDraft:
    definition = UI_EVENT_REGISTRY.get(draft.event_type)
    allowed_scope_keys = definition.scope_keys if definition is not None else frozenset(draft.scope)
    return UiEventDraft(
        event_type=draft.event_type,
        payload=_without_none(draft.payload),
        scope={
            key: value for key, value in draft.scope.items() if value and key in allowed_scope_keys
        },
        causation_id=draft.causation_id,
    )
