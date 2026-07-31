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

# ---------------------------------------------------------------------------
# Event type constants — single source of truth for all registered UI events
# ---------------------------------------------------------------------------
EVENT_TYPE_ASSISTANT_MESSAGE = "assistant.message"
EVENT_TYPE_ASSISTANT_PROGRESS = "assistant.progress"
EVENT_TYPE_ASSISTANT_ERROR = "assistant.error"
EVENT_TYPE_ASSISTANT_CONFIRMATION = "assistant.confirmation"
EVENT_TYPE_ASSISTANT_CLARIFICATION_REQUESTED = "assistant.clarification_requested"
EVENT_TYPE_ASSISTANT_CLARIFICATION_RESOLVED = "assistant.clarification_resolved"
EVENT_TYPE_ASSISTANT_ACTIVITY = "assistant.activity"
EVENT_TYPE_ASSISTANT_SUBAGENT = "assistant.subagent"
EVENT_TYPE_ASSISTANT_TASK_GRAPH_CHANGED = "assistant.task_graph.changed"
EVENT_TYPE_ASSISTANT_TASK_BOARD_CHANGED = "assistant.task_board.changed"
EVENT_TYPE_ASSISTANT_TASK_QUESTION_CHANGED = "assistant.task_question.changed"
EVENT_TYPE_ASSISTANT_MEETING_CHANGED = "assistant.meeting.changed"
EVENT_TYPE_ASSISTANT_TODO_CHANGED = "assistant.todo.changed"
EVENT_TYPE_ASSISTANT_EXTERNAL_CODING_CHANGED = "assistant.external_coding.changed"
EVENT_TYPE_RECORDING_PROGRESS = "recording.progress"
EVENT_TYPE_TEACHING_STAGE_CHANGED = "teaching.stage_changed"
EVENT_TYPE_TEACHING_PROGRESS = "teaching.progress"
EVENT_TYPE_TRIAL_PROGRESS = "trial.progress"
EVENT_TYPE_TRIAL_PREVIEW_REQUESTED = "trial.preview_requested"
EVENT_TYPE_TRIAL_PREVIEW_RESOLVED = "trial.preview_resolved"
EVENT_TYPE_TOOLS_CHANGED = "tools.changed"
EVENT_TYPE_SKILL_CHANGED = "skill.changed"
EVENT_TYPE_SKILL_EQUIPMENT_CHANGED = "skill.equipment.changed"
EVENT_TYPE_COMPOSITIONS_CHANGED = "compositions.changed"
EVENT_TYPE_SETTINGS_CHANGED = "settings.changed"
EVENT_TYPE_BACKEND_RESYNC_REQUIRED = "backend.resync_required"
EVENT_TYPE_BRAIN_ZONE_CHANGED = "brain_zone_changed"
EVENT_TYPE_BRAIN_SPECIALIST_RECRUITED = "brain_specialist_recruited"
EVENT_TYPE_BRAIN_SPECIALIST_CHANGED = "brain_specialist_changed"
EVENT_TYPE_BRAIN_CONTEXT_READY = "brain_context_ready"
EVENT_TYPE_IMPROVEMENT_PROPOSAL_CHANGED = "improvement_proposal.changed"
# 033 调度中心公开 UI 事件（经 UI Event Registry 注册的 typed envelope）
EVENT_TYPE_SCHEDULED_TASK_COMPLETED = "scheduled_task.completed"
EVENT_TYPE_SCHEDULED_TASK_NEEDS_TAKEOVER = "scheduled_task.needs_takeover"
EVENT_TYPE_SCHEDULED_TASK_CHANGED = "scheduled_task.changed"
EVENT_TYPE_SCHEDULING_CONFIRMATION_REQUESTED = "scheduling.confirmation_requested"
EVENT_TYPE_SCHEDULING_CONFIRMATION_RESOLVED = "scheduling.confirmation_resolved"

UI_EVENT_REGISTRY: dict[str, UiEventDefinition] = {
    EVENT_TYPE_ASSISTANT_MESSAGE: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_MESSAGE,
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
    EVENT_TYPE_ASSISTANT_PROGRESS: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_PROGRESS,
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
    EVENT_TYPE_ASSISTANT_ERROR: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_ERROR,
        "notification",
        frozenset({"message", "type"}),
        frozenset({"sessionId", "workflowId"}),
        {"message": "Assistant failed to complete the request.", "type": "RuntimeError"},
        required_payload_keys=frozenset({"message"}),
        required_scope_keys=frozenset({"sessionId"}),
    ),
    EVENT_TYPE_ASSISTANT_CONFIRMATION: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_CONFIRMATION,
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
    EVENT_TYPE_ASSISTANT_CLARIFICATION_REQUESTED: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_CLARIFICATION_REQUESTED,
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
    EVENT_TYPE_ASSISTANT_CLARIFICATION_RESOLVED: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_CLARIFICATION_RESOLVED,
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
    EVENT_TYPE_ASSISTANT_ACTIVITY: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_ACTIVITY,
        "notification",
        frozenset({"subagentId", "kind", "toolName", "text", "seq", "redacted"}),
        frozenset({"sessionId"}),
        {"kind": "tool_call", "toolName": "delegate_to_subagent", "text": "派发子任务", "seq": 1},
        required_payload_keys=frozenset({"kind", "seq"}),
        required_scope_keys=frozenset({"sessionId"}),
        payload_enum_values=(("kind", frozenset({"reasoning", "tool_call", "tool_result"})),),
        unredacted_payload_keys=frozenset({"text"}),
    ),
    EVENT_TYPE_ASSISTANT_SUBAGENT: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_SUBAGENT,
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
    EVENT_TYPE_ASSISTANT_TASK_GRAPH_CHANGED: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_TASK_GRAPH_CHANGED,
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
                "waitingOn",
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
            "waitingOn": None,
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
                # interrupted 此前漏在这张表外——业务枚举、schema Literal 和 DB CHECK
                # 都有它，唯独这里没有。它目前零生产者所以没炸，但启动对账落地后
                # 会立刻撞 UiEventValidationError。
                "suspendReason",
                frozenset(
                    {
                        "waiting_user",
                        "waiting_system",
                        "user_stop",
                        "budget_exhausted",
                        "interrupted",
                    }
                ),
            ),
            (
                "waitingOn",
                frozenset({"user", "assistant", "system"}),
            ),
        ),
    ),
    EVENT_TYPE_ASSISTANT_TASK_BOARD_CHANGED: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_TASK_BOARD_CHANGED,
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
    EVENT_TYPE_ASSISTANT_TASK_QUESTION_CHANGED: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_TASK_QUESTION_CHANGED,
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
    EVENT_TYPE_ASSISTANT_MEETING_CHANGED: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_MEETING_CHANGED,
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
    EVENT_TYPE_ASSISTANT_TODO_CHANGED: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_TODO_CHANGED,
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
    EVENT_TYPE_ASSISTANT_EXTERNAL_CODING_CHANGED: UiEventDefinition(
        EVENT_TYPE_ASSISTANT_EXTERNAL_CODING_CHANGED,
        "notification",
        frozenset(
            {
                "codingSessionId",
                "sessionId",
                "ownerType",
                "ownerId",
                "tool",
                "status",
                "phase",
                "changeType",
                "updatedAt",
            }
        ),
        _SESSION_SCOPE,
        {
            "codingSessionId": "ecs_123",
            "sessionId": "sess_1",
            "ownerType": "task",
            "ownerId": "tsk_1",
            "tool": "claude_code",
            "status": "plan_ready",
            "phase": "plan",
            "changeType": "plan_ready",
        },
        required_payload_keys=frozenset(
            {"codingSessionId", "ownerType", "ownerId", "tool", "status", "phase", "changeType"}
        ),
        required_scope_keys=frozenset(),
        payload_enum_values=(
            ("ownerType", frozenset({"task", "workflow"})),
            ("tool", frozenset({"claude_code", "codex_cli"})),
            (
                "status",
                frozenset(
                    {
                        "created",
                        "planning",
                        "plan_ready",
                        "plan_approved",
                        "plan_rejected",
                        "implementing",
                        "interrupted",
                        "waiting_user",
                        "completed",
                        "merge_ready",
                        "merged",
                        "merge_blocked",
                        "rollback_proposed",
                        "rolled_back",
                        "abandoned",
                        "failed",
                    }
                ),
            ),
            ("phase", frozenset({"plan", "implement", "merge", "rollback", "done"})),
            (
                "changeType",
                frozenset(
                    {
                        "created",
                        "start_failed",
                        "plan_ready",
                        "plan_approved",
                        "plan_rejected",
                        "resumed",
                        "waiting_user",
                        "abandoned",
                        "merge_analysis",
                        "merge_failed",
                        "merged",
                        "rollback_proposed",
                        "rolled_back",
                        "rollback_failed",
                        "protocol_violation",
                        "plan_invalid",
                        "result_invalid",
                        "review_recorded",
                        "missing_artifact",
                        "completed",
                    }
                ),
            ),
        ),
    ),
    EVENT_TYPE_RECORDING_PROGRESS: UiEventDefinition(
        EVENT_TYPE_RECORDING_PROGRESS,
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
    EVENT_TYPE_TEACHING_STAGE_CHANGED: UiEventDefinition(
        EVENT_TYPE_TEACHING_STAGE_CHANGED,
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
    EVENT_TYPE_TEACHING_PROGRESS: UiEventDefinition(
        EVENT_TYPE_TEACHING_PROGRESS,
        "notification",
        frozenset({"status", "message", "headline", "question", "failureStage", "error", "type"}),
        frozenset({"workflowId", "sessionId"}),
        {"status": "running", "headline": "Tool learning started"},
        required_payload_keys=frozenset({"status"}),
        required_scope_keys=frozenset({"workflowId"}),
    ),
    EVENT_TYPE_TRIAL_PROGRESS: UiEventDefinition(
        EVENT_TYPE_TRIAL_PROGRESS,
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
    EVENT_TYPE_TRIAL_PREVIEW_REQUESTED: UiEventDefinition(
        EVENT_TYPE_TRIAL_PREVIEW_REQUESTED,
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
    EVENT_TYPE_TRIAL_PREVIEW_RESOLVED: UiEventDefinition(
        EVENT_TYPE_TRIAL_PREVIEW_RESOLVED,
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
    EVENT_TYPE_TOOLS_CHANGED: UiEventDefinition(
        EVENT_TYPE_TOOLS_CHANGED,
        "notification",
        frozenset({"reason", "toolId", "status"}),
        frozenset({"toolId"}),
        {"reason": "catalog_invalidated"},
    ),
    EVENT_TYPE_SKILL_CHANGED: UiEventDefinition(
        EVENT_TYPE_SKILL_CHANGED,
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
    EVENT_TYPE_SKILL_EQUIPMENT_CHANGED: UiEventDefinition(
        EVENT_TYPE_SKILL_EQUIPMENT_CHANGED,
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
    EVENT_TYPE_COMPOSITIONS_CHANGED: UiEventDefinition(
        EVENT_TYPE_COMPOSITIONS_CHANGED,
        "notification",
        frozenset({"reason", "compositionId", "status"}),
        frozenset({"compositionId"}),
        {"reason": "catalog_invalidated"},
    ),
    EVENT_TYPE_SETTINGS_CHANGED: UiEventDefinition(
        EVENT_TYPE_SETTINGS_CHANGED,
        "notification",
        frozenset({"reason", "keys"}),
        frozenset(),
        {"reason": "settings_invalidated", "keys": []},
        required_payload_keys=frozenset({"reason"}),
    ),
    EVENT_TYPE_BACKEND_RESYNC_REQUIRED: UiEventDefinition(
        EVENT_TYPE_BACKEND_RESYNC_REQUIRED,
        "control",
        frozenset({"reason", "domains", "lastAvailableSequence", "eventSessionId"}),
        frozenset({"workflowId", "sessionId", "toolId", "compositionId"}),
        {"reason": "replay_gap", "domains": ["teaching", "tools", "brain", "skill"]},
        required_payload_keys=frozenset({"reason", "domains"}),
    ),
    EVENT_TYPE_BRAIN_ZONE_CHANGED: UiEventDefinition(
        EVENT_TYPE_BRAIN_ZONE_CHANGED,
        "notification",
        frozenset({"zone", "entryId", "changeType"}),
        frozenset(),
        {"zone": "hot", "entryId": "entry_1", "changeType": "create"},
        required_payload_keys=frozenset({"zone", "changeType"}),
    ),
    EVENT_TYPE_BRAIN_SPECIALIST_RECRUITED: UiEventDefinition(
        EVENT_TYPE_BRAIN_SPECIALIST_RECRUITED,
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
    EVENT_TYPE_BRAIN_SPECIALIST_CHANGED: UiEventDefinition(
        EVENT_TYPE_BRAIN_SPECIALIST_CHANGED,
        "notification",
        frozenset({"specialistId", "changeType"}),
        frozenset(),
        {"specialistId": "spec_1", "changeType": "update"},
        required_payload_keys=frozenset({"specialistId", "changeType"}),
    ),
    EVENT_TYPE_BRAIN_CONTEXT_READY: UiEventDefinition(
        EVENT_TYPE_BRAIN_CONTEXT_READY,
        "notification",
        frozenset({"sessionId"}),
        frozenset({"sessionId"}),
        {"sessionId": "sess_1"},
        required_payload_keys=frozenset({"sessionId"}),
        required_scope_keys=frozenset({"sessionId"}),
    ),
    # status / changeType 交叉关系契约（026 I6）：changeType 恒等于 status，唯一例外
    # 是 proposal 首次创建时 changeType="created" 且 status="pending_review"。通用
    # enum 校验在 registry 中声明，交叉关系由 validate_ui_event_payload 的专用分支校验。
    EVENT_TYPE_IMPROVEMENT_PROPOSAL_CHANGED: UiEventDefinition(
        EVENT_TYPE_IMPROVEMENT_PROPOSAL_CHANGED,
        "notification",
        frozenset({"proposalId", "sourceReviewId", "status", "severity", "changeType"}),
        frozenset(),
        {
            "proposalId": "prop_abc",
            "sourceReviewId": "rev_1",
            "status": "pending_review",
            "severity": "med",
            "changeType": "created",
        },
        required_payload_keys=frozenset({"proposalId", "sourceReviewId", "status", "changeType"}),
        payload_enum_values=(
            (
                "status",
                frozenset(
                    {"pending_review", "approved", "in_progress", "done", "failed", "rejected"}
                ),
            ),
            (
                "changeType",
                frozenset({"created", "approved", "rejected", "in_progress", "done", "failed"}),
            ),
        ),
    ),
    EVENT_TYPE_SCHEDULED_TASK_COMPLETED: UiEventDefinition(
        EVENT_TYPE_SCHEDULED_TASK_COMPLETED,
        "notification",
        frozenset(
            {"taskId", "taskTitle", "runId", "sessionId", "outcome", "summary", "failureReason"}
        ),
        frozenset({"sessionId"}),
        {
            "taskId": "sch_abc",
            "taskTitle": "查竞品价格",
            "runId": "schr_xyz",
            "sessionId": "ast_001",
            "outcome": "succeeded",
            "summary": "竞品 A 价格 99 元",
            "failureReason": None,
        },
        required_payload_keys=frozenset({"taskId", "runId", "sessionId", "outcome"}),
        required_scope_keys=frozenset({"sessionId"}),
        payload_enum_values=(("outcome", frozenset({"succeeded", "failed"})),),
        unredacted_payload_keys=frozenset({"taskTitle", "summary"}),
    ),
    EVENT_TYPE_SCHEDULED_TASK_NEEDS_TAKEOVER: UiEventDefinition(
        EVENT_TYPE_SCHEDULED_TASK_NEEDS_TAKEOVER,
        "notification",
        frozenset({"taskId", "taskTitle", "runId", "sessionId", "reason"}),
        frozenset({"sessionId"}),
        {
            "taskId": "sch_abc",
            "taskTitle": "查竞品价格",
            "runId": "schr_xyz",
            "sessionId": "ast_001",
            "reason": "needs_user_input",
        },
        required_payload_keys=frozenset({"taskId", "runId", "sessionId", "reason"}),
        required_scope_keys=frozenset({"sessionId"}),
        payload_enum_values=(("reason", frozenset({"needs_user_input", "failed_takeover"})),),
        unredacted_payload_keys=frozenset({"taskTitle"}),
    ),
    EVENT_TYPE_SCHEDULED_TASK_CHANGED: UiEventDefinition(
        EVENT_TYPE_SCHEDULED_TASK_CHANGED,
        "notification",
        frozenset({"taskId", "changeType"}),
        frozenset(),
        {"taskId": "sch_abc", "changeType": "created"},
        required_payload_keys=frozenset({"taskId", "changeType"}),
        payload_enum_values=(
            (
                "changeType",
                frozenset({"created", "paused", "resumed", "deleted", "fired", "status_changed"}),
            ),
        ),
    ),
    EVENT_TYPE_SCHEDULING_CONFIRMATION_REQUESTED: UiEventDefinition(
        EVENT_TYPE_SCHEDULING_CONFIRMATION_REQUESTED,
        "interactive",
        frozenset(
            {"requestId", "sessionId", "draft", "unattendedAutoApprove", "expiresAt", "status"}
        ),
        frozenset({"sessionId"}),
        {
            "requestId": "scf_abc",
            "sessionId": "ast_001",
            "draft": {
                "title": "查竞品价格",
                "scheduleDescription": "每天 09:00",
                "instruction": "查询竞品价格并汇总",
                "scheduleKind": "recurring",
                "sourceType": "direct",
            },
            "unattendedAutoApprove": False,
            "expiresAt": "2026-07-19T12:00:00+00:00",
        },
        required_payload_keys=frozenset({"requestId", "sessionId", "draft", "expiresAt"}),
        required_scope_keys=frozenset({"sessionId"}),
        payload_enum_values=(("status", frozenset({"pending"})),),
    ),
    EVENT_TYPE_SCHEDULING_CONFIRMATION_RESOLVED: UiEventDefinition(
        EVENT_TYPE_SCHEDULING_CONFIRMATION_RESOLVED,
        "interactive",
        frozenset({"requestId", "sessionId", "status"}),
        frozenset({"sessionId"}),
        {"requestId": "scf_abc", "sessionId": "ast_001", "status": "confirmed"},
        required_payload_keys=frozenset({"requestId", "sessionId", "status"}),
        required_scope_keys=frozenset({"sessionId"}),
        payload_enum_values=(
            (
                "status",
                frozenset({"confirmed", "cancelled", "timeout", "stopped", "shutdown"}),
            ),
        ),
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
    if event_type == EVENT_TYPE_IMPROVEMENT_PROPOSAL_CHANGED:
        _validate_improvement_proposal_changed_payload(payload)
    if event_type == EVENT_TYPE_ASSISTANT_MESSAGE and payload.get("failure") is not None:
        _validate_assistant_failure_payload(payload)
    for key, value in payload.items():
        if key in definition.unredacted_payload_keys:
            continue  # 有意保留原文（UI 默认隐藏 + 双击查看），不做 forbidden value 脱敏校验
        _validate_payload_value(key, value)


def _validate_improvement_proposal_changed_payload(payload: dict[str, Any]) -> None:
    status = str(payload.get("status") or "")
    change_type = str(payload.get("changeType") or "")
    if change_type == "created" and status == "pending_review":
        return
    if change_type != status:
        raise UiEventValidationError(
            "improvement_proposal.changed status and changeType do not match"
        )


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
            validate_ui_event_payload(EVENT_TYPE_TRIAL_PREVIEW_REQUESTED, payload)
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
                EVENT_TYPE_TRIAL_PREVIEW_REQUESTED,
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
            EVENT_TYPE_TRIAL_PREVIEW_RESOLVED,
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
