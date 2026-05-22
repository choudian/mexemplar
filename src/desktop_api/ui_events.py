from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from src.desktop_api.schemas import UiEvent

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


@dataclass(frozen=True)
class UiEventDraft:
    event_type: str
    payload: dict[str, Any]
    scope: dict[str, str]
    causation_id: str | None = None


class UiEventValidationError(ValueError):
    """Raised when a public UI event violates the registered contract."""


UI_EVENT_REGISTRY: dict[str, UiEventDefinition] = {
    "assistant.message": UiEventDefinition(
        "assistant.message",
        "notification",
        frozenset({"sequence", "role", "content", "createdAt", "rendering"}),
        frozenset({"sessionId"}),
        {"sequence": 1, "role": "assistant", "content": "Ready.", "rendering": "safe_markdown"},
        required_payload_keys=frozenset({"sequence", "role", "content", "rendering"}),
        required_scope_keys=frozenset({"sessionId"}),
        payload_enum_values=(
            ("role", frozenset({"user", "assistant"})),
            ("rendering", frozenset({"plain_text", "safe_markdown"})),
        ),
    ),
    "assistant.progress": UiEventDefinition(
        "assistant.progress",
        "notification",
        frozenset({"status", "headline", "message", "question"}),
        frozenset({"sessionId", "workflowId"}),
        {"status": "running", "headline": "Assistant is working"},
        required_payload_keys=frozenset({"status"}),
        required_scope_keys=frozenset({"sessionId"}),
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
        {"stage": "learning", "message": "Skill learning started."},
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
        {"status": "running", "headline": "Skill learning started"},
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
    "skills.changed": UiEventDefinition(
        "skills.changed",
        "notification",
        frozenset({"reason", "toolId", "status"}),
        frozenset({"toolId"}),
        {"reason": "catalog_invalidated"},
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
        {"reason": "replay_gap", "domains": ["teaching", "skills", "brain"]},
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
}

_DB_EXTENSION_PATTERN = r"\.(sqlite3?|duckdb|db)\b"

_FORBIDDEN_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"MEXEMPLAR_DESKTOP_TOKEN", re.IGNORECASE),
    re.compile(r"Traceback \(most recent call last\):"),
    re.compile(r"\b(api[_-]?key|password|secret|token)\s*[:=]", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\[^\\\n]+\\[^\\\n]+\\[^\\\n]+" + _DB_EXTENSION_PATTERN, re.IGNORECASE),
]


def registered_event_types() -> list[str]:
    return sorted(UI_EVENT_REGISTRY)


def exported_registry_examples() -> dict[str, dict[str, Any]]:
    return {
        event_type: dict(definition.example) for event_type, definition in UI_EVENT_REGISTRY.items()
    }


def exported_registry_payload_enums() -> dict[str, dict[str, list[str]]]:
    return {
        event_type: {
            key: sorted(values)
            for key, values in definition.payload_enum_values
        }
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
        key for key in definition.required_payload_keys if key not in payload or payload[key] is None
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
    for key, value in payload.items():
        _validate_payload_value(key, value)


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
                    "error": _safe_short_text(payload.get("error")) if payload.get("error") else None,
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
        elif "sessionId" in scope:
            event_type = "assistant.progress"
            event_payload = {
                "status": "waiting_for_user",
                "headline": question,
                "question": question,
            }
        elif "workflowId" in scope:
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
        event_type = "assistant.error" if "sessionId" in scope else "teaching.progress"
        status_payload = {
            "message": _safe_text(
                payload.get("message") or payload.get("error") or "Agent failed."
            ),
            "type": _string_or_none(payload.get("type")),
        }
        if event_type == "teaching.progress":
            status_payload = {"status": "failed", "error": status_payload["message"]}
        return [UiEventDraft(event_type, status_payload, scope, causation_id)]
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
    if event_name in {"tool_saved", "tool_published", "skills_changed"}:
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
                "skills.changed",
                skill_payload,
                scope,
                causation_id,
            )
        ]
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
    normalized_key = _normalize_key(key)
    if normalized_key in _FORBIDDEN_PAYLOAD_KEYS:
        raise UiEventValidationError(f"UI event payload key is forbidden: {key}")
    if (
        normalized_key.endswith("path")
        and isinstance(value, str)
        and re.search(_DB_EXTENSION_PATTERN, value, re.IGNORECASE)
    ):
        raise UiEventValidationError(
            f"UI event payload path looks like a local database path: {key}"
        )
    if isinstance(value, str):
        if key == "codePreview" and len(value) > _MAX_PREVIEW_CHARS:
            raise UiEventValidationError("UI event codePreview exceeds the maximum preview length")
        for pattern in _FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                raise UiEventValidationError(
                    f"UI event payload value failed safety validation: {key}"
                )
    elif isinstance(value, dict):
        for child_key, child_value in value.items():
            _validate_payload_value(str(child_key), child_value)
    elif isinstance(value, list):
        for item in value:
            _validate_payload_value(key, item)


_CAMEL_CASE_PATTERN = re.compile(r"([a-z0-9])([A-Z])")


def _normalize_key(key: str) -> str:
    value = _CAMEL_CASE_PATTERN.sub(r"\1_\2", key).lower()
    return value.replace("-", "_")


def _scope_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    scope: dict[str, str] = {}
    for source_key, target_key in [
        ("session_id", "sessionId"),
        ("workflow_id", "workflowId"),
        ("recording_id", "workflowId"),
        ("tool_id", "toolId"),
        ("composition_id", "compositionId"),
    ]:
        value = payload.get(source_key)
        if value is not None:
            scope[target_key] = str(value)
    return scope


def _causation_id(scope: dict[str, str], payload: dict[str, Any]) -> str | None:
    for key in ("workflowId", "sessionId", "toolId", "compositionId"):
        if scope.get(key):
            return scope[key]
    value = payload.get("trial_id") or payload.get("request_id")
    return str(value) if value is not None else None


def _truncate_preview(value: str) -> str:
    if len(value) <= _MAX_PREVIEW_CHARS:
        return value
    return value[: _MAX_PREVIEW_CHARS - 1] + "…"


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


def _without_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def normalize_draft(draft: UiEventDraft) -> UiEventDraft:
    definition = UI_EVENT_REGISTRY.get(draft.event_type)
    allowed_scope_keys = definition.scope_keys if definition is not None else frozenset(draft.scope)
    return UiEventDraft(
        event_type=draft.event_type,
        payload=_without_none(draft.payload),
        scope={
            key: value
            for key, value in draft.scope.items()
            if value and key in allowed_scope_keys
        },
        causation_id=draft.causation_id,
    )
