from __future__ import annotations

import logging
from typing import Any, Callable

from src.business.agents.config import AgentType
from src.business.services.ui_event_safety_service import (
    DEFAULT_PUBLIC_TEXT_MAX_CHARS,
    DEFAULT_PUBLIC_TEXT_MAX_LEN,
    public_ui_event_text_with_flag,
    redact_public_ui_event_text,
)
from src.desktop_api.ui_event_types import UiEventDraft

logger = logging.getLogger(__name__)

# assistant.activity / assistant.subagent 仅对可观测的助理执行链路投影；其余 agent_type 零 UI 噪声。
# 从 AgentType 枚举派生，新增可观测类型时只需改枚举一处。
_OBSERVABLE_AGENT_TYPES = frozenset(
    {
        AgentType.ASSISTANT.value,
        AgentType.EPHEMERAL_SUBAGENT.value,
        AgentType.SPECIALIST.value,
    }
)


def _is_observable_agent_type(agent_type: Any) -> bool:
    """该 agent_type 是否属于助理可观测链路（主助理 / 临时子代理 / 专员）。"""
    return str(agent_type or "").lower() in _OBSERVABLE_AGENT_TYPES


def _redact_text(value: Any) -> str:
    return redact_public_ui_event_text(
        "text",
        value,
        max_preview_chars=DEFAULT_PUBLIC_TEXT_MAX_CHARS,
        max_len=DEFAULT_PUBLIC_TEXT_MAX_LEN,
    )


def _text_with_flag(value: Any) -> tuple[str, bool]:
    """activity step：保留原文（仅截断）+ 敏感标记，供 UI 默认隐藏 + 双击查看。"""
    return public_ui_event_text_with_flag(
        "text",
        value,
        max_preview_chars=DEFAULT_PUBLIC_TEXT_MAX_CHARS,
        max_len=DEFAULT_PUBLIC_TEXT_MAX_LEN,
    )


# ===== payload converters（纯函数，handler 共用）=====


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text[:5000]


def _safe_short_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text[:300]


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: Any) -> int:
    result = _int_or_none(value)
    return result if result is not None else 0


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _value_or_false(value: Any):
    """Nullable flag：None → False，其余原样透传（与其它 converter 命名风格一致）。"""
    return value if value is not None else False


# ===== scope / causation（主函数算一次，传入各 handler）=====


def _scope_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    scope: dict[str, str] = {}
    for source_key, public_key in [
        ("session_id", "sessionId"),
        ("workflow_id", "workflowId"),
        ("recording_id", "workflowId"),
        ("tool_id", "toolId"),
        ("composition_id", "compositionId"),
    ]:
        value = payload.get(source_key)
        if value is not None:
            scope[public_key] = str(value)
    return scope


def _causation_id(scope: dict[str, str], payload: dict[str, Any]) -> str | None:
    for key in ("workflowId", "sessionId", "toolId", "compositionId"):
        if scope.get(key):
            return scope[key]
    value = payload.get("trial_id") or payload.get("request_id")
    return str(value) if value is not None else None


# ===== task collaboration：声明式 field_map（A 类，注册表复用）=====


_TASK_GRAPH_FIELD_MAP: dict[str, tuple[str, Any]] = {
    "graphId": ("graph_id", _string_or_none),
    "taskId": ("task_id", _string_or_none),
    "changeType": ("change_type", _string_or_none),
    "status": ("status", _string_or_none),
    "displayPhase": ("display_phase", _string_or_none),
    "requiresReview": ("requires_review", _value_or_false),
    "safeExplanation": ("safe_explanation", _safe_short_text),
    "suspendReason": ("suspend_reason", _string_or_none),
    "sequence": ("sequence", _int_or_none),
}


# Declarative mapping for task-collaboration internal events → public UI events.
# Each entry: internal_event_name → (public_type, field_map)
# field_map: {public_key: (internal_key, converter)}
_TASK_EVENT_PROJECTIONS: dict[str, tuple[str, dict[str, tuple[str, Any]]]] = {
    "assistant_task_graph_changed": ("assistant.task_graph.changed", _TASK_GRAPH_FIELD_MAP),
    "assistant_task_adjudication_changed": ("assistant.task_graph.changed", _TASK_GRAPH_FIELD_MAP),
    "assistant_task_root_failed": ("assistant.task_graph.changed", _TASK_GRAPH_FIELD_MAP),
    "assistant_task_board_changed": (
        "assistant.task_board.changed",
        {
            "taskId": ("task_id", _string_or_none),
            "graphId": ("graph_id", _string_or_none),
            "changeType": ("change_type", _string_or_none),
            "claimStatus": ("claim_status", _string_or_none),
            "updatedAt": ("updated_at", _string_or_none),
        },
    ),
    "assistant_task_question_changed": (
        "assistant.task_question.changed",
        {
            "questionId": ("question_id", _string_or_none),
            "taskId": ("task_id", _string_or_none),
            "graphId": ("graph_id", _string_or_none),
            "kind": ("kind", _string_or_none),
            "status": ("status", _string_or_none),
            "changeType": ("change_type", _string_or_none),
        },
    ),
    "assistant_meeting_changed": (
        "assistant.meeting.changed",
        {
            "channelId": ("channel_id", _string_or_none),
            "graphId": ("graph_id", _string_or_none),
            "taskId": ("task_id", _string_or_none),
            "changeType": ("change_type", _string_or_none),
            "sequence": ("sequence", _int_or_none),
            "status": ("status", _string_or_none),
        },
    ),
    "assistant_todo_changed": (
        "assistant.todo.changed",
        {
            "taskId": ("task_id", _string_or_none),
            "todoId": ("todo_id", _string_or_none),
            "changeType": ("change_type", _string_or_none),
            "status": ("status", _string_or_none),
            "sortOrder": ("sort_order", _int_or_none),
        },
    ),
}


# ===== projection handlers =====
# 统一签名：(payload, scope, causation_id) -> list[UiEventDraft]
# scope/causation_id 由 project_internal_event 用 _scope_from_payload/_causation_id 算好后传入；
# brain_skill_* 忽略传入 scope、自行构造 skill 作用域。


def _project_assistant_agent_step(payload, scope, causation_id):
    if not _is_observable_agent_type(payload.get("agent_type")):
        return []  # 非助理流程（PM/Programmer/Trial）零 assistant.activity（E4/CC-005）
    activity_text, activity_redacted = _text_with_flag(payload.get("text"))
    return [
        UiEventDraft(
            "assistant.activity",
            {
                "subagentId": _string_or_none(payload.get("subagent_id")),
                "kind": _string_or_none(payload.get("kind")),
                "toolName": _string_or_none(payload.get("tool_name")),
                "text": activity_text,
                "redacted": activity_redacted,
                "seq": _int_or_none(payload.get("seq")),
            },
            scope,
            causation_id,
        )
    ]


def _project_subagent_lifecycle(payload, scope, causation_id):
    # 无需 agent_type 门控：这些生命周期事件只由 orchestrator 的助理委派点发出，
    # 按构造即属可观测助理链路，并以父助理 session 为 scope。
    return [
        UiEventDraft(
            "assistant.subagent",
            {
                "subagentId": _string_or_none(payload.get("subagent_id")),
                "label": _redact_text(payload.get("label")) or None,
                "task": _redact_text(payload.get("task")) or None,
                "status": _string_or_none(payload.get("status")),
                "lastOutput": (
                    _redact_text(payload.get("last_output"))
                    if payload.get("last_output") is not None
                    else None
                ),
                "reason": (
                    _redact_text(payload.get("reason"))
                    if payload.get("reason") is not None
                    else None
                ),
            },
            scope,
            causation_id,
        )
    ]


def _project_recording_started(payload, scope, causation_id):
    return [
        UiEventDraft(
            "recording.progress",
            {
                "status": "recording",
                "message": "Recording started.",
                "recordingMode": _string_or_none(payload.get("recording_mode")),
            },
            scope,
            causation_id,
        ),
        UiEventDraft("teaching.stage_changed", {"stage": "recording"}, scope, causation_id),
    ]


def _project_recording_stopped(payload, scope, causation_id):
    return [
        UiEventDraft(
            "recording.progress",
            {
                "status": "stopped",
                "message": "Recording stopped.",
                "recordingMode": _string_or_none(payload.get("recording_mode")),
            },
            scope,
            causation_id,
        ),
        UiEventDraft(
            "teaching.stage_changed", {"stage": "intent_confirmation"}, scope, causation_id
        ),
    ]


def _project_recording_completed(payload, scope, causation_id):
    return [
        UiEventDraft(
            "recording.progress",
            {"status": "completed", "message": "Recording completed."},
            scope,
            causation_id,
        )
    ]


def _project_desktop_action_count_changed(payload, scope, causation_id):
    return [
        UiEventDraft(
            "recording.progress",
            {"status": "recording", "actionCount": _int_or_zero(payload.get("action_count"))},
            scope,
            causation_id,
        )
    ]


def _project_desktop_recording_problem(event_name):
    def _project(payload, scope, causation_id):
        return [
            UiEventDraft(
                "recording.progress",
                {
                    "status": (
                        "failed" if event_name == "desktop_recorder_start_failed" else "degraded"
                    ),
                    "message": _safe_short_text(
                        payload.get("message") or payload.get("error") or event_name
                    ),
                    "error": (
                        _safe_short_text(payload.get("error")) if payload.get("error") else None
                    ),
                    "subsystem": _string_or_none(payload.get("subsystem")),
                    "degraded": event_name == "desktop_recording_degraded",
                },
                scope,
                causation_id,
            )
        ]

    return _project


def _project_agent_needs_user_input(payload, scope, causation_id):
    question = _safe_text(payload.get("question") or payload.get("message"))
    raw_agent_type = payload.get("agent_type")
    agent_type = str(getattr(raw_agent_type, "value", raw_agent_type or "")).lower()
    base_payload = {"status": "waiting_for_user", "headline": question}
    if agent_type == "pm":
        event_type = "teaching.progress"
        event_payload = {**base_payload, "question": question}
    elif agent_type == "trial":
        event_type = "trial.progress"
        event_payload = base_payload
    elif scope.get("sessionId"):
        event_type = "assistant.progress"
        event_payload = {**base_payload, "question": question}
    elif scope.get("workflowId"):
        event_type = "teaching.progress"
        event_payload = {**base_payload, "question": question}
    else:
        return []
    return [UiEventDraft(event_type, event_payload, scope, causation_id)]


def _project_agent_error(payload, scope, causation_id):
    raw_agent_type = payload.get("agent_type")
    agent_type = str(getattr(raw_agent_type, "value", raw_agent_type or "")).lower()
    status_payload = {
        "message": _safe_short_text(
            payload.get("message") or payload.get("error") or "Agent failed."
        ),
        "type": _string_or_none(payload.get("type")),
    }
    if agent_type == "trial":
        return [
            UiEventDraft(
                "trial.progress",
                {
                    "status": "failed",
                    "error": status_payload["message"],
                    "type": status_payload["type"],
                },
                scope,
                causation_id,
            )
        ]
    if agent_type in {"pm", "programmer"} or (scope.get("workflowId") and scope.get("sessionId")):
        return [
            UiEventDraft(
                "teaching.progress",
                {
                    "status": "failed",
                    "error": status_payload["message"],
                    "type": status_payload["type"],
                },
                scope,
                causation_id,
            )
        ]
    if scope.get("sessionId"):
        return [UiEventDraft("assistant.error", status_payload, scope, causation_id)]
    fallback = {"status": "failed", "error": status_payload["message"]}
    return [UiEventDraft("teaching.progress", fallback, scope, causation_id)]


def _project_requirement_confirmed(payload, scope, causation_id):
    return [
        UiEventDraft(
            "teaching.stage_changed",
            {"stage": "learning", "message": "Requirements confirmed."},
            scope,
            causation_id,
        ),
        UiEventDraft(
            "teaching.progress",
            {"status": "running", "headline": "Skill learning started"},
            scope,
            causation_id,
        ),
    ]


def _project_code_completed(payload, scope, causation_id):
    return [
        UiEventDraft(
            "teaching.stage_changed",
            {"stage": "trial_validation", "message": "Skill learning completed."},
            scope,
            causation_id,
        ),
        UiEventDraft(
            "teaching.progress",
            {"status": "succeeded", "headline": "Skill learning completed"},
            scope,
            causation_id,
        ),
    ]


def _project_review_failed(payload, scope, causation_id):
    return [
        UiEventDraft(
            "teaching.stage_changed",
            {"stage": "failed", "failureStage": _string_or_none(payload.get("failed_stage"))},
            scope,
            causation_id,
        ),
        UiEventDraft(
            "teaching.progress",
            {
                "status": "failed",
                "failureStage": _string_or_none(payload.get("failed_stage")),
                "error": _safe_text(
                    payload.get("error") or payload.get("message") or "Skill teaching failed."
                ),
            },
            scope,
            causation_id,
        ),
    ]


def _project_teaching_failure_resolved(payload, scope, causation_id):
    return [
        UiEventDraft(
            "teaching.progress",
            {"status": "succeeded", "headline": "Teaching failure resolved"},
            scope,
            causation_id,
        )
    ]


def _project_teaching_failure_retrying(payload, scope, causation_id):
    return [
        UiEventDraft(
            "teaching.progress",
            {"status": "running", "headline": "Skill teaching retry started"},
            scope,
            causation_id,
        )
    ]


def _project_trial_requested(payload, scope, causation_id):
    return [
        UiEventDraft(
            "trial.progress",
            {"status": "running", "headline": "Skill trial requested"},
            scope,
            causation_id,
        )
    ]


def _project_trial_success(payload, scope, causation_id):
    published = bool(payload.get("published", False))
    drafts = [
        UiEventDraft(
            "trial.progress",
            {
                "status": "succeeded",
                "published": published,
                "successCount": _int_or_none(
                    payload.get("success_count") or payload.get("trial_success_count")
                ),
            },
            scope,
            causation_id,
        )
    ]
    if published:
        drafts.append(
            UiEventDraft(
                "teaching.stage_changed",
                {"stage": "published", "published": True},
                scope,
                causation_id,
            )
        )
    return drafts


def _project_trial_failed(payload, scope, causation_id):
    return [
        UiEventDraft(
            "teaching.stage_changed",
            {"stage": "failed", "failureStage": "trial"},
            scope,
            causation_id,
        )
    ]


def _project_desktop_trial_finished(payload, scope, causation_id):
    return [
        UiEventDraft(
            "trial.progress",
            {
                "status": "succeeded",
                "trialId": _string_or_none(payload.get("trial_id")),
                "result": _safe_text(payload.get("result")),
            },
            scope,
            causation_id,
        )
    ]


def _project_tool_changed(event_name):
    def _project(payload, scope, causation_id):
        skill_payload = {
            "reason": "catalog_invalidated",
            "toolId": _string_or_none(payload.get("tool_id")),
        }
        if event_name == "tool_saved":
            skill_payload["status"] = "saved"
        elif event_name == "tool_published":
            skill_payload["status"] = "published"
        return [UiEventDraft("tools.changed", skill_payload, scope, causation_id)]

    return _project


def _project_brain_skill_changed(payload, scope, causation_id):
    skill_id = _string_or_none(payload.get("skill_id") or payload.get("new_skill_id"))
    chain_root_id = _string_or_none(payload.get("chain_root_id") or skill_id)
    return [
        UiEventDraft(
            "skill.changed",
            {
                "reason": _string_or_none(payload.get("operation") or payload.get("reason")),
                "skillId": skill_id,
                "chainRootId": chain_root_id,
                "newSkillId": _string_or_none(payload.get("new_skill_id")),
                "callerType": _string_or_none(payload.get("caller_type")),
                "callerId": _string_or_none(payload.get("caller_id")),
            },
            {"skillId": skill_id} if skill_id else {},
            causation_id,
        )
    ]


def _project_brain_skill_bootstrap_fallback_used(payload, scope, causation_id):
    skill_id = _string_or_none(payload.get("skill_id") or payload.get("sender"))
    return [
        UiEventDraft(
            "skill.changed",
            {
                "reason": "bootstrap_fallback_used",
                "skillId": skill_id,
                "chainRootId": skill_id,
                "newSkillId": skill_id,
                "callerType": "system",
                "callerId": "_system",
                "bootstrapFallbackUsed": True,
                "bootstrapFallbackInfo": {
                    "reason": _string_or_none(payload.get("reason")),
                    "seedFilePath": _string_or_none(payload.get("seed_file_path")),
                },
            },
            {"skillId": skill_id} if skill_id else {},
            causation_id,
        )
    ]


def _project_brain_skill_equipment_changed(payload, scope, causation_id):
    skill_id = _string_or_none(payload.get("skill_id"))
    entity_id = _string_or_none(payload.get("entity_id"))
    return [
        UiEventDraft(
            "skill.equipment.changed",
            {
                "changeType": _string_or_none(payload.get("change_type")),
                "entityType": _string_or_none(payload.get("entity_type")),
                "entityId": entity_id,
                "skillId": skill_id,
                "unequippedReason": _string_or_none(payload.get("unequipped_reason")),
            },
            {
                key: value
                for key, value in {"skillId": skill_id, "entityId": entity_id}.items()
                if value
            },
            causation_id,
        )
    ]


def _project_brain_skill_supersede_completed(payload, scope, causation_id):
    # brain_skill_changed is already emitted by skill_service.supersede() and
    # projected to skill.changed; suppressing duplicate here.
    return []


def _project_composition_review_needed(payload, scope, causation_id):
    return [
        UiEventDraft(
            "compositions.changed",
            {
                "reason": "catalog_invalidated",
                "compositionId": _string_or_none(payload.get("composition_id")),
            },
            scope,
            causation_id,
        )
    ]


def _project_settings_changed(payload, scope, causation_id):
    return [
        UiEventDraft(
            "settings.changed",
            {"reason": "settings_invalidated", "keys": _string_list(payload.get("keys"))},
            scope,
            causation_id,
        )
    ]


def _project_brain_zone_changed(payload, scope, causation_id):
    return [
        UiEventDraft(
            "brain_zone_changed",
            {
                "zone": _string_or_none(payload.get("zone")),
                "entryId": _string_or_none(payload.get("entry_id")),
                "changeType": _string_or_none(
                    payload.get("change_type") or payload.get("operation")
                ),
            },
            scope,
            causation_id,
        )
    ]


def _project_brain_specialist_recruited(payload, scope, causation_id):
    return [
        UiEventDraft(
            "brain_specialist_recruited",
            {
                "specialistId": _string_or_none(payload.get("specialist_id")),
                "name": _string_or_none(payload.get("name")),
                "reason": _safe_short_text(payload.get("reason") or ""),
                "managementUrl": "/brain/specialists",
            },
            scope,
            causation_id,
        )
    ]


def _project_brain_specialist_changed(payload, scope, causation_id):
    return [
        UiEventDraft(
            "brain_specialist_changed",
            {
                "specialistId": _string_or_none(payload.get("specialist_id")),
                "changeType": _string_or_none(
                    payload.get("change_type") or payload.get("operation")
                ),
            },
            scope,
            causation_id,
        )
    ]


def _project_brain_context_ready(payload, scope, causation_id):
    return [
        UiEventDraft(
            "brain_context_ready",
            {"sessionId": _string_or_none(payload.get("session_id"))},
            scope,
            causation_id,
        )
    ]


def _make_task_projection(public_type: str, field_map: dict[str, tuple[str, Any]]):
    def _project(payload, scope, causation_id):
        projected = {
            public_key: converter(payload.get(internal_key))
            for public_key, (internal_key, converter) in field_map.items()
        }
        return [UiEventDraft(public_type, projected, scope, causation_id)]

    return _project


# ===== projection registry =====
# 新增内部事件：在上面写 handler，然后在此注册一行。project_internal_event 只做 lookup。

ProjectionHandler = Callable[
    [dict[str, Any], dict[str, str], "str | None"], list[UiEventDraft]
]

_PROJECTIONS: dict[str, ProjectionHandler] = {
    "assistant_agent_step": _project_assistant_agent_step,
    "assistant_subagent_started": _project_subagent_lifecycle,
    "assistant_subagent_finished": _project_subagent_lifecycle,
    "assistant_subagent_paused": _project_subagent_lifecycle,
    "recording_started": _project_recording_started,
    "recording_stopped": _project_recording_stopped,
    "recording_completed": _project_recording_completed,
    "desktop_action_count_changed": _project_desktop_action_count_changed,
    "desktop_recording_degraded": _project_desktop_recording_problem("desktop_recording_degraded"),
    "desktop_recorder_start_failed": _project_desktop_recording_problem(
        "desktop_recorder_start_failed"
    ),
    "agent_needs_user_input": _project_agent_needs_user_input,
    "agent_error": _project_agent_error,
    "requirement_confirmed": _project_requirement_confirmed,
    "code_completed": _project_code_completed,
    "review_passed": _project_code_completed,
    "review_failed": _project_review_failed,
    "teaching_failure_updated": _project_review_failed,
    "teaching_failure_resolved": _project_teaching_failure_resolved,
    "teaching_failure_retrying": _project_teaching_failure_retrying,
    "trial_requested": _project_trial_requested,
    "trial_success": _project_trial_success,
    "trial_failed": _project_trial_failed,
    "desktop_trial_finished": _project_desktop_trial_finished,
    "tool_saved": _project_tool_changed("tool_saved"),
    "tool_published": _project_tool_changed("tool_published"),
    "tools_changed": _project_tool_changed("tools_changed"),
    "brain_skill_changed": _project_brain_skill_changed,
    "brain_skill_bootstrap_fallback_used": _project_brain_skill_bootstrap_fallback_used,
    "brain_skill_equipment_changed": _project_brain_skill_equipment_changed,
    "brain_skill_supersede_completed": _project_brain_skill_supersede_completed,
    "composition_review_needed": _project_composition_review_needed,
    "settings_changed": _project_settings_changed,
    "brain_zone_changed": _project_brain_zone_changed,
    "brain_specialist_recruited": _project_brain_specialist_recruited,
    "brain_specialist_changed": _project_brain_specialist_changed,
    "brain_context_ready": _project_brain_context_ready,
}

# task collaboration 事件复用声明式 _TASK_EVENT_PROJECTIONS（A 类 field_map）
for _event_name, (_public_type, _field_map) in _TASK_EVENT_PROJECTIONS.items():
    _PROJECTIONS[_event_name] = _make_task_projection(_public_type, _field_map)


def project_internal_event(event_name: str, payload: dict[str, Any]) -> list[UiEventDraft]:
    scope = _scope_from_payload(payload)
    causation_id = _causation_id(scope, payload)
    handler = _PROJECTIONS.get(event_name)
    if handler is None:
        logger.warning("projector: 未注册的内部事件 %r 被丢弃", event_name)
        return []
    return handler(payload, scope, causation_id)
