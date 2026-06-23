from __future__ import annotations

from typing import Any

from src.business.agents.config import AgentType
from src.business.services.ui_event_safety_service import (
    DEFAULT_PUBLIC_TEXT_MAX_CHARS,
    DEFAULT_PUBLIC_TEXT_MAX_LEN,
    public_ui_event_text_with_flag,
    redact_public_ui_event_text,
)
from src.desktop_api.ui_event_types import UiEventDraft

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


def project_internal_event(event_name: str, payload: dict[str, Any]) -> list[UiEventDraft]:
    scope = _scope_from_payload(payload)
    causation_id = _causation_id(scope, payload)

    if event_name == "assistant_agent_step":
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
    if event_name in {
        "assistant_subagent_started",
        "assistant_subagent_finished",
        "assistant_subagent_paused",
    }:
        # 无需 agent_type 门控：这些生命周期事件只由 orchestrator 的助理委派点（_emit_subagent_*）
        # 发出，按构造即属可观测助理链路，并以父助理 session 为 scope。
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

    # --- Task collaboration events: declarative mapping ---
    _task_event = _TASK_EVENT_PROJECTIONS.get(event_name)
    if _task_event is not None:
        public_type, field_map = _task_event
        projected = {}
        for public_key, (internal_key, converter) in field_map.items():
            projected[public_key] = converter(payload.get(internal_key))
        return [UiEventDraft(public_type, projected, scope, causation_id)]

    if event_name == "recording_started":
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
    if event_name == "recording_stopped":
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
    if event_name == "recording_completed":
        return [
            UiEventDraft(
                "recording.progress",
                {"status": "completed", "message": "Recording completed."},
                scope,
                causation_id,
            )
        ]
    if event_name == "desktop_action_count_changed":
        return [
            UiEventDraft(
                "recording.progress",
                {"status": "recording", "actionCount": _int_or_zero(payload.get("action_count"))},
                scope,
                causation_id,
            )
        ]
    if event_name in {"desktop_recording_degraded", "desktop_recorder_start_failed"}:
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
    if event_name == "agent_needs_user_input":
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
        return [
            UiEventDraft(
                event_type,
                event_payload,
                scope,
                causation_id,
            )
        ]
    if event_name == "agent_error":
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
        if agent_type in {"pm", "programmer"} or (
            scope.get("workflowId") and scope.get("sessionId")
        ):
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
        status_payload = {"status": "failed", "error": status_payload["message"]}
        return [UiEventDraft("teaching.progress", status_payload, scope, causation_id)]
    if event_name == "requirement_confirmed":
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
    if event_name in {"code_completed", "review_passed"}:
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
    if event_name in {"review_failed", "teaching_failure_updated"}:
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
    if event_name == "teaching_failure_resolved":
        return [
            UiEventDraft(
                "teaching.progress",
                {"status": "succeeded", "headline": "Teaching failure resolved"},
                scope,
                causation_id,
            )
        ]
    if event_name == "teaching_failure_retrying":
        return [
            UiEventDraft(
                "teaching.progress",
                {"status": "running", "headline": "Skill teaching retry started"},
                scope,
                causation_id,
            )
        ]
    if event_name == "trial_requested":
        return [
            UiEventDraft(
                "trial.progress",
                {"status": "running", "headline": "Skill trial requested"},
                scope,
                causation_id,
            )
        ]
    if event_name == "trial_success":
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
    if event_name == "trial_failed":
        return [
            UiEventDraft(
                "teaching.stage_changed",
                {
                    "stage": "failed",
                    "failureStage": "trial",
                },
                scope,
                causation_id,
            ),
        ]
    if event_name == "desktop_trial_finished":
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
    if event_name in {"tool_saved", "tool_published", "tools_changed"}:
        skill_payload = {
            "reason": "catalog_invalidated",
            "toolId": _string_or_none(payload.get("tool_id")),
        }
        if event_name == "tool_saved":
            skill_payload["status"] = "saved"
        elif event_name == "tool_published":
            skill_payload["status"] = "published"
        return [
            UiEventDraft(
                "tools.changed",
                skill_payload,
                scope,
                causation_id,
            )
        ]
    if event_name == "brain_skill_changed":
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
    if event_name == "brain_skill_bootstrap_fallback_used":
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
    if event_name == "brain_skill_equipment_changed":
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
    if event_name == "brain_skill_supersede_completed":
        # brain_skill_changed is already emitted by skill_service.supersede() and
        # projected to skill.changed above; suppressing duplicate here.
        return []
    if event_name == "composition_review_needed":
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
    if event_name == "settings_changed":
        return [
            UiEventDraft(
                "settings.changed",
                {"reason": "settings_invalidated", "keys": _string_list(payload.get("keys"))},
                scope,
                causation_id,
            )
        ]
    if event_name == "brain_zone_changed":
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
    if event_name == "brain_specialist_recruited":
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
    if event_name == "brain_specialist_changed":
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
    if event_name == "brain_context_ready":
        return [
            UiEventDraft(
                "brain_context_ready",
                {"sessionId": _string_or_none(payload.get("session_id"))},
                scope,
                causation_id,
            )
        ]
    return []


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
# 三个 graph 类事件共享 _TASK_GRAPH_FIELD_MAP；改字段时只改一处。
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
