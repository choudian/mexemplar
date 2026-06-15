"""Desktop adapter：把内存澄清机制（clarification_manager）桥接到 UI 事件流与 API。

对标 confirmations.py，但走独立事件（assistant.clarification_requested / _resolved）与独立
manager，绝不复用高危确认链路（FR-020）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.business.agents.tools import clarification_manager
from src.business.agents.tools.clarification_manager import (
    NormalizedQuestion,
    PendingClarification,
)
from src.desktop_api.events import event_queue


class _DesktopClarificationSignal:
    """Signal shim：澄清发起/结算时向前端事件流发布注册过的公开事件。"""

    def emit_requested(self, request_id: str) -> None:
        pending = clarification_manager.get_pending(request_id)
        if pending is None:
            return
        payload = _requested_payload(pending)
        event_queue.publish_nowait(
            "assistant.clarification_requested",
            payload,
            {"sessionId": pending.session_id},
        )

    def emit_resolved(self, request_id: str) -> None:
        pending = clarification_manager.get_pending(request_id)
        if pending is None:
            return
        event_queue.publish_nowait(
            "assistant.clarification_resolved",
            {
                "requestId": pending.request_id,
                "sessionId": pending.session_id,
                "status": pending.status,
            },
            {"sessionId": pending.session_id},
        )


def install_clarification_signal() -> None:
    """注册 desktop 端澄清信号（由 sidecar adapter 初始化时调用）。"""
    clarification_manager.register_clarification_signal(_DesktopClarificationSignal())


def _question_projection(question: NormalizedQuestion) -> dict[str, Any]:
    return {
        "questionId": question.question_id,
        "question": question.question,
        "header": question.header,
        "multiSelect": question.multi_select,
        "options": [
            {
                "optionId": o.option_id,
                "label": o.label,
                "description": o.description,
                "preview": o.preview,
            }
            for o in question.options
        ],
    }


def _expires_at_iso(request_id: str) -> str | None:
    remaining_ms = clarification_manager.get_remaining_timeout_ms(request_id)
    if remaining_ms is None or remaining_ms <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(milliseconds=remaining_ms)).isoformat()


def _requested_payload(pending: PendingClarification) -> dict[str, Any]:
    return {
        "requestId": pending.request_id,
        "sessionId": pending.session_id,
        "questions": [_question_projection(q) for q in pending.questions],
        "expiresAt": _expires_at_iso(pending.request_id),
        "status": "pending",
    }


def pending_clarification_snapshot(session_id: str) -> dict[str, Any] | None:
    """返回该会话当前 pending 澄清的前端安全快照（不含答案/草稿）；无则 None。"""
    pending = clarification_manager.get_pending_for_session(session_id)
    if pending is None:
        return None
    return _requested_payload(pending)


def record_clarification_decision(
    session_id: str,
    request_id: str,
    decision: str,
    answers: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """提交/取消决策。归属错配抛 LookupError；校验失败抛 ClarificationValidationError。"""
    return clarification_manager.submit_decision(
        session_id,
        request_id,
        decision,  # type: ignore[arg-type]
        answers or [],
    )


def settle_clarifications_for_session_stopped(session_id: str) -> list[str]:
    """停止当前回合：把该会话仍 pending 的澄清结算为 stopped 并唤醒 worker。"""
    return clarification_manager.settle_clarifications_for_session(session_id, "stopped")


def settle_all_clarifications_shutdown() -> list[str]:
    """应用关闭：把所有仍 pending 的澄清结算为 shutdown 并唤醒 worker。"""
    return clarification_manager.settle_all_clarifications("shutdown")
