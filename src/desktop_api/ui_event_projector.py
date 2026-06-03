from __future__ import annotations

from typing import Any

from src.desktop_api.ui_event_types import UiEventDraft


def project_internal_event(event_name: str, payload: dict[str, Any]) -> list[UiEventDraft]:
    scope = _scope_from_payload(payload)
    causation_id = _causation_id(scope, payload)

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
        if agent_type == "pm":
            event_type = "teaching.progress"
            event_payload = {
                "status": "waiting_for_user",
                "headline": question,
                "question": question,
            }
        elif agent_type == "trial":
            event_type = "trial.progress"
            event_payload = {
                "status": "waiting_for_user",
                "headline": question,
            }
        elif scope.get("sessionId"):
            event_type = "assistant.progress"
            event_payload = {
                "status": "waiting_for_user",
                "headline": question,
                "question": question,
            }
        elif scope.get("workflowId"):
            event_type = "teaching.progress"
            event_payload = {
                "status": "waiting_for_user",
                "headline": question,
                "question": question,
            }
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
