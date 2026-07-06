"""ProposalService — generate, approve, and reject improvement proposals.

Reads ``worth_changing`` findings from execution reviews and creates
``pending_review`` proposals.  Idempotent on (source_review_id, finding_index)
and suppressed by dedup_key (FR-001a).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.data.repos.improvement_proposal_repository import (
    ImprovementProposalRepository,
    compute_dedup_key,
)
from src.utils.events import emit

logger = logging.getLogger(__name__)

# DTO 边界脱敏：公共错误/结果摘要不得携带 secret 或绝对路径（data-model 标注
# "脱敏安全原因"）。这是纵深防御——来源侧也应只写安全摘要——但 DTO 边界保证
# 不变量，杜绝漏网。
_ERROR_REDACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # OpenAI 风格 key
    re.compile(r"sk_live_[A-Za-z0-9]{16,}"),  # Stripe live key
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),  # Google API key
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub token
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),  # Slack token
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\._\-]+"),  # Bearer token
    re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),  # JWT token
    re.compile(r"[A-Za-z]:\\[^\s'\"<>]+"),  # Windows 绝对路径
    re.compile(r"(?i)/(?:home|users|root)/[^\s'\"<>]+"),  # POSIX 家目录路径
    re.compile(r"(?i)\b[\w.\-]+\.env\b"),  # .env 文件名
    re.compile(r"(?i)\b[\w.\-]+\.(?:pem|key|pfx|p12)\b"),  # 密钥文件名
    re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://\S+:\S+@"),  # URL user:password@
)
_ERROR_REDACTED = "***REDACTED***"
_ERROR_MAX_LEN = 500
# DTO 边界脱敏自身故障时的固定回退（MEDIUM-9）：不得把 sanitizer 异常透到 FastAPI 500。
_DTO_SAFE_FALLBACK = "详情不可用"


class ProposalCleanupError(RuntimeError):
    """Raised when rejecting a failed proposal cannot clean retained worktree."""


def sanitize_proposal_public_text(text: str | None) -> str | None:
    """Strip secrets/absolute paths from proposal text before exposing via DTO.

    Returns ``None`` unchanged; otherwise applies the redaction patterns and
    truncates to ``_ERROR_MAX_LEN``.
    """
    if not text:
        return text
    cleaned = text
    for pattern in _ERROR_REDACT_PATTERNS:
        cleaned = pattern.sub(_ERROR_REDACTED, cleaned)
    return cleaned[:_ERROR_MAX_LEN]


def _sanitize_dto_text(value: str | None) -> str | None:
    """Sanitize text for the DTO boundary with a fail-safe fallback (MEDIUM-9).

    Mirrors ``proposal_bridge._safe_public_text``: if the sanitizer itself raises,
    return a fixed safe string instead of bubbling into a FastAPI 500.  None/empty
    pass through unchanged so the DTO can still distinguish "no summary" from a
    redacted one.
    """
    if not value:
        return value
    try:
        return sanitize_proposal_public_text(value)
    except Exception:
        logger.error("Proposal public text sanitizer failed at DTO boundary", exc_info=True)
        return _DTO_SAFE_FALLBACK


class ProposalService:
    """Business layer for improvement proposal lifecycle."""

    # -- Generate from review (D1) -------------------------------------------

    def generate_from_review(self, review_id: str, findings: list[dict[str, Any]]) -> int:
        """Generate proposals from a review's ``worth_changing`` findings.

        Called after the execution review has been written back (旁路调用) with
        the already-parsed findings list.  Idempotent: same
        (review_id, finding_index) does not duplicate.  Dedup: same dedup_key
        with an unresolved or within-cooldown proposal is suppressed (FR-001a).

        Returns the number of new proposals actually created.
        """
        if not findings:
            return 0

        created = 0
        with ImprovementProposalRepository() as repo:
            for idx, finding in enumerate(findings):
                if not finding.get("worth_changing"):
                    continue
                dedup_key = compute_dedup_key(finding.get("type"), finding.get("what"))
                row = repo.create(
                    source_review_id=review_id,
                    finding_index=idx,
                    severity=finding.get("severity"),
                    finding_type=finding.get("type"),
                    dedup_key=dedup_key,
                    what=finding.get("what"),
                    evidence=finding.get("evidence"),
                    suggestion=finding.get("suggestion"),
                )
                if row is not None:
                    created += 1
                    self._emit_changed(row, change_type="created")

        return created

    # -- Approve / Reject (US1) ---------------------------------------------

    def approve(self, proposal_id: str, supplement: str | None = None) -> dict[str, Any] | None:
        """Approve a pending proposal.  Returns updated row or None on CAS miss."""
        with ImprovementProposalRepository() as repo:
            row = repo.approve(proposal_id, supplement=supplement)
            if row is None:
                return None
            result = self._to_dict(row)
        self._emit_changed(row, change_type="approved")
        return result

    def reject(self, proposal_id: str) -> dict[str, Any] | None:
        """Reject a pending or failed proposal.  Returns updated row or None."""
        with ImprovementProposalRepository() as repo:
            current = repo.get_by_id(proposal_id)
            if current is None:
                return None
            should_cleanup = current.status == "failed" and bool(current.worktree_path)
            worktree_path = current.worktree_path

        if should_cleanup and worktree_path:
            self._cleanup_rejected_worktree(proposal_id, worktree_path)

        with ImprovementProposalRepository() as repo:
            row = repo.reject(proposal_id)
            if row is None:
                return None
            result = self._to_dict(row)
        self._emit_changed(row, change_type="rejected")
        return result

    # -- Discussion session (028) ---------------------------------------------

    # 会话列表可见状态（chat_service._VISIBLE_SESSION_STATUSES 同源语义）：
    # 归档（删除）或行缺失都视为绑定死亡，走自愈重建。
    _DISCUSSION_ALIVE_STATUSES = ("active", "suspended", "completed", "failed")

    def get_or_create_discussion_session(self, proposal_id: str) -> dict[str, Any] | None:
        """获取或创建提案的讨论会话（幂等 + 绑定死亡自愈）。

        Returns ``{"sessionId": str, "created": bool}``，提案不存在返回 None。
        创建路径零模型调用：新会话仅落一条 assistant 角色开场消息
        （proposal_context 序列化），不触发任何实施副作用（FR-425）。
        """
        from src.business.self_improvement.proposal_context import (
            format_discussion_opening_message,
        )
        from src.business.services.chat_service import ChatService
        from src.data.models_sqlite import Message
        from src.data.repositories import MessageRepository, SessionRepository

        with ImprovementProposalRepository() as repo:
            row = repo.get_by_id(proposal_id)
            if row is None:
                return None
            bound_id = row.discussion_session_id
            opening = format_discussion_opening_message(row)
            title_stub = (row.what or "改进提案").strip() or "改进提案"

        if bound_id:
            session = SessionRepository().get_by_id(bound_id)
            if session is not None and session.status in self._DISCUSSION_ALIVE_STATUSES:
                return {"sessionId": bound_id, "created": False}

        chat = ChatService()
        new_session_id = chat.create_session(title=f"讨论：{title_stub[:24]}")
        import uuid as _uuid

        msg_repo = MessageRepository()
        msg_repo.create(
            Message(
                message_id=str(_uuid.uuid4()),
                session_id=new_session_id,
                sequence=msg_repo.get_next_sequence(new_session_id),
                role="assistant",
                content=opening,
            )
        )

        if bound_id:
            # 旧绑定已确认死亡：直接换绑（自愈路径）。
            with ImprovementProposalRepository() as repo:
                repo.rebind_discussion_session(proposal_id, new_session_id)
            return {"sessionId": new_session_id, "created": True}

        with ImprovementProposalRepository() as repo:
            if repo.bind_discussion_session(proposal_id, new_session_id):
                return {"sessionId": new_session_id, "created": True}
            # 竞态输者：丢弃孤儿会话，复用赢者绑定。
            chat.archive_session(new_session_id)
            current = repo.get_by_id(proposal_id)
        winner = current.discussion_session_id if current is not None else None
        if winner:
            return {"sessionId": winner, "created": False}
        logger.error(
            "Discussion binding race left proposal %s unbound; rebinding fallback",
            proposal_id,
        )
        with ImprovementProposalRepository() as repo:
            repo.rebind_discussion_session(proposal_id, new_session_id)
        return {"sessionId": new_session_id, "created": True}

    # -- Query ---------------------------------------------------------------

    def list_proposals(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with ImprovementProposalRepository() as repo:
            rows = repo.list_recent(limit=limit, status=status)
            return [self._to_dict(r) for r in rows]

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with ImprovementProposalRepository() as repo:
            row = repo.get_by_id(proposal_id)
            if row is None:
                return None
            return self._to_dict(row)

    # -- Internal helpers ----------------------------------------------------

    @staticmethod
    def _emit_changed(row, *, change_type: str) -> None:
        """Emit blinker event for proposal state change."""
        try:
            emit(
                "improvement_proposal_changed",
                proposal_id=row.id,
                source_review_id=row.source_review_id,
                status=row.status,
                severity=row.severity,
                change_type=change_type,
            )
        except Exception as exc:
            logger.warning(
                "Failed to emit improvement_proposal_changed for proposal %s: %s",
                getattr(row, "id", "unknown"),
                exc,
                exc_info=True,
            )

    @staticmethod
    def _cleanup_rejected_worktree(proposal_id: str, worktree_path: str) -> None:
        try:
            from src.business.self_improvement.proposal_workspace import remove_worktree

            remove_worktree(worktree_path)
            with ImprovementProposalRepository() as repo:
                cleared = repo.clear_worktree_location(proposal_id)
            if cleared is None:
                raise ProposalCleanupError("proposal worktree metadata could not be cleared")
        except ProposalCleanupError:
            raise
        except Exception as exc:
            logger.warning(
                "Failed to cleanup rejected proposal worktree: proposal=%s",
                proposal_id,
                exc_info=True,
            )
            raise ProposalCleanupError("failed to cleanup proposal worktree") from exc

    @staticmethod
    def _to_dict(row) -> dict[str, Any]:
        return {
            "id": row.id,
            "sourceReviewId": row.source_review_id,
            "findingIndex": row.finding_index,
            "status": row.status,
            "severity": row.severity,
            "findingType": row.finding_type,
            "what": row.what,
            "evidence": row.evidence,
            "suggestion": row.suggestion,
            "userSupplement": row.user_supplement,
            "graphId": row.graph_id,
            "worktreeAvailable": bool(row.worktree_path),
            "branchName": row.branch_name,
            "resultTestsPassed": (
                None if row.result_tests_passed is None else bool(row.result_tests_passed)
            ),
            "resultSummary": _sanitize_dto_text(row.result_summary),
            "error": _sanitize_dto_text(row.error),
            "discussionSessionId": row.discussion_session_id,
            "createdAt": row.created_at,
            "decidedAt": row.decided_at,
            "completedAt": row.completed_at,
        }
