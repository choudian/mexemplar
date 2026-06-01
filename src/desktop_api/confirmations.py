from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import threading
from typing import Literal

from src.business.agents.tools.builtin_general_tools import (
    CONFIRM_SOURCE_TOAST_ACCEPT,
    CONFIRM_SOURCE_TOAST_REJECT,
    _ask_user_confirm,
    get_confirmation_remaining_timeout_ms,
    get_pending_confirmation,
    register_confirm_mechanism,
    set_confirm_result,
)
from src.desktop_api.events import event_queue
from src.desktop_api.ui_events import CONFIRMATION_VALID_ACTION_TYPES

_CONFIRMATION_INPUT_ACTION_TYPES = CONFIRMATION_VALID_ACTION_TYPES - frozenset({"unknown"})

ConfirmationDecision = Literal["approve", "deny"]
_GLOBAL_CONFIRMATION_SESSION_ID = "_global_confirmation"
_CONFIRMATION_EXTRA_KEYS = frozenset(
    {"affectedSkillId", "affectedEquipmentCount", "affectedSpecialistNames"}
)
_confirmation_context = threading.local()


class _DesktopConfirmationSignal:
    """Signal shim for the shared high-risk confirmation protocol."""

    def emit(self, request_id: str, _message: str) -> None:
        payload = confirmation_event_payload(request_id)
        session_id = str(payload.get("sessionId") or _GLOBAL_CONFIRMATION_SESSION_ID)
        payload["sessionId"] = session_id
        event_queue.publish_nowait(
            "assistant.confirmation",
            payload,
            {"sessionId": session_id},
        )


@dataclass(frozen=True)
class ConfirmationDecisionResult:
    request_id: str
    decision: ConfirmationDecision
    accepted: bool


def set_confirmation_session_context(session_id: str | None) -> None:
    """Bind the current assistant session to confirmations emitted by this thread."""
    _confirmation_context.session_id = session_id or ""


def get_confirmation_session_context() -> str:
    return str(getattr(_confirmation_context, "session_id", "") or "")


def clear_confirmation_session_context() -> None:
    if hasattr(_confirmation_context, "session_id"):
        delattr(_confirmation_context, "session_id")


def install_confirmation_signal() -> None:
    """Register the desktop-side emitter used by blocking confirmation waits."""
    register_confirm_mechanism(_DesktopConfirmationSignal())


def request_high_risk_confirmation(
    action_type: str,
    summary: str,
    *,
    extra_payload: dict[str, object] | None = None,
) -> bool:
    """Block until the frontend approves/denies a high-risk action."""
    return _ask_user_confirm(summary, tool_name=action_type, extra_payload=extra_payload)


def confirmation_event_payload(request_id: str) -> dict[str, object]:
    """Build the frontend-safe confirmation payload for a pending request."""
    pending = get_pending_confirmation(request_id)
    remaining_ms = get_confirmation_remaining_timeout_ms(request_id)
    expires_at = None
    if remaining_ms is not None and remaining_ms > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(milliseconds=remaining_ms)

    tool_name = pending.tool_name if pending else "unknown"
    session_id = get_confirmation_session_context() or _GLOBAL_CONFIRMATION_SESSION_ID
    payload = {
        "requestId": request_id,
        "sessionId": session_id,
        "actionType": (tool_name if tool_name in _CONFIRMATION_INPUT_ACTION_TYPES else "unknown"),
        "sanitizedSummary": pending.summary if pending else "需要确认高风险操作。",
        "status": "active",
        "expiresAt": expires_at.isoformat() if expires_at else None,
    }
    extra_payload = getattr(pending, "extra_payload", None) if pending else None
    if isinstance(extra_payload, dict):
        for key, value in extra_payload.items():
            if key in _CONFIRMATION_EXTRA_KEYS:
                payload[key] = value
    return payload


def record_confirmation_decision(
    request_id: str, decision: ConfirmationDecision
) -> ConfirmationDecisionResult:
    pending = get_pending_confirmation(request_id)
    if pending is None:
        return ConfirmationDecisionResult(request_id=request_id, decision=decision, accepted=False)

    accepted = decision == "approve"
    source = CONFIRM_SOURCE_TOAST_ACCEPT if accepted else CONFIRM_SOURCE_TOAST_REJECT
    set_confirm_result(request_id, accepted, source)
    return ConfirmationDecisionResult(request_id=request_id, decision=decision, accepted=True)
