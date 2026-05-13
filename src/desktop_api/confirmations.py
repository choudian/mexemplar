from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import threading
from typing import Literal

from src.business.agents.tools.builtin_general_tools import (
    CONFIRM_SOURCE_TOAST_ACCEPT,
    CONFIRM_SOURCE_TOAST_REJECT,
    get_confirmation_remaining_timeout_ms,
    get_pending_confirmation,
    set_confirm_result,
)

ConfirmationDecision = Literal["approve", "deny"]
_confirmation_context = threading.local()


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


def confirmation_event_payload(request_id: str) -> dict[str, object]:
    """Build the frontend-safe confirmation payload for a pending request."""
    pending = get_pending_confirmation(request_id)
    remaining_ms = get_confirmation_remaining_timeout_ms(request_id)
    expires_at = None
    if remaining_ms is not None and remaining_ms > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(milliseconds=remaining_ms)

    tool_name = pending.tool_name if pending else "unknown"
    return {
        "requestId": request_id,
        "sessionId": get_confirmation_session_context(),
        "actionType": tool_name if tool_name in {"write_file", "edit_file", "exec"} else "unknown",
        "sanitizedSummary": pending.summary if pending else "需要确认高风险操作。",
        "status": "active",
        "expiresAt": expires_at.isoformat() if expires_at else None,
    }


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
