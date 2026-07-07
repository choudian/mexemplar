"""Repository for improvement_proposals — CAS state machine + dedup."""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from enum import StrEnum

from sqlalchemy.exc import IntegrityError

from src.data.models_sqlite import ImprovementProposal
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id

logger = logging.getLogger(__name__)


class ProposalStatus(StrEnum):
    """Improvement proposal lifecycle states (026 C3).

    Single source of truth for the status literals — ``_TRANSITIONS`` /
    ``TERMINAL_STATUSES`` / ``DEDUP_BLOCKING_STATUSES`` all derive from this enum
    so a typo (e.g. ``"inprogress"``) fails at the enum reference instead of
    silently making a CAS UPDATE never match. Method signatures stay ``str`` for
    backwards compatibility; StrEnum members compare equal to their string value.
    """

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Terminal statuses and dedup-blocking statuses
# (dedup-blocking includes non-terminal + "failed" to prevent re-proposing
#  recently failed improvements within the cooldown window)
# ---------------------------------------------------------------------------
TERMINAL_STATUSES: frozenset[ProposalStatus] = frozenset(
    {ProposalStatus.DONE, ProposalStatus.REJECTED}
)
DEDUP_BLOCKING_STATUSES: frozenset[ProposalStatus] = frozenset(
    {
        ProposalStatus.PENDING_REVIEW,
        ProposalStatus.APPROVED,
        ProposalStatus.IN_PROGRESS,
        ProposalStatus.FAILED,
    }
)

# Allowed transitions: {(from_status, to_status)}
_TRANSITIONS: frozenset[tuple[ProposalStatus, ProposalStatus]] = frozenset(
    {
        (ProposalStatus.PENDING_REVIEW, ProposalStatus.APPROVED),
        (ProposalStatus.PENDING_REVIEW, ProposalStatus.REJECTED),
        (ProposalStatus.APPROVED, ProposalStatus.IN_PROGRESS),
        (ProposalStatus.APPROVED, ProposalStatus.FAILED),
        (ProposalStatus.IN_PROGRESS, ProposalStatus.DONE),
        (ProposalStatus.IN_PROGRESS, ProposalStatus.FAILED),
        (ProposalStatus.FAILED, ProposalStatus.REJECTED),
    }
)


def _sources_for(to_status: str) -> frozenset[str]:
    """Source statuses allowed to transition to ``to_status``."""
    return frozenset(src for src, tgt in _TRANSITIONS if tgt == to_status)


class ImprovementProposalRepository(BaseRepository):
    """CRUD + CAS state machine for improvement proposals."""

    # -- Create (idempotent) --------------------------------------------------

    def create(
        self,
        *,
        source_review_id: str,
        finding_index: int,
        severity: str | None = None,
        finding_type: str | None = None,
        dedup_key: str | None = None,
        what: str | None = None,
        evidence: str | None = None,
        suggestion: str | None = None,
    ) -> ImprovementProposal | None:
        """Create a proposal; idempotent on UNIQUE(source_review_id, finding_index).

        Returns the new row, or *None* if a duplicate already exists or if
        dedup suppression applies (same ``dedup_key`` with an unresolved or
        within-cooldown proposal).
        """
        # Dedup suppression (FR-001a): skip if same dedup_key has an unresolved
        # or within-cooldown proposal.  One query fetches all matching rows; the
        # cooldown config is only read when terminal rows exist (avoids session
        # invalidation from get_unified_config() on shared sessions).
        if dedup_key:
            existing = (
                self.session.query(ImprovementProposal)
                .filter(ImprovementProposal.dedup_key == dedup_key)
                .all()
            )
            if existing:
                if any(r.status in DEDUP_BLOCKING_STATUSES for r in existing):
                    return None
                terminal = [r for r in existing if r.status in TERMINAL_STATUSES]
                if terminal:
                    cutoff = (
                        utc_now_naive() - timedelta(hours=self._get_dedup_cooldown_hours())
                    ).isoformat()
                    if any(r.created_at and r.created_at >= cutoff for r in terminal):
                        return None

        row = ImprovementProposal(
            id=generate_id("prop"),
            source_review_id=source_review_id,
            finding_index=finding_index,
            status="pending_review",
            severity=severity,
            finding_type=finding_type,
            dedup_key=dedup_key,
            what=what,
            evidence=evidence,
            suggestion=suggestion,
            created_at=utc_now_naive().isoformat(),
        )
        try:
            return self._add_and_flush(row)
        except IntegrityError:
            # UNIQUE hit — idempotent, return None silently
            self._abort_conflict()
            return None

    # -- Read -----------------------------------------------------------------

    def get_by_id(self, proposal_id: str) -> ImprovementProposal | None:
        return self.session.get(ImprovementProposal, proposal_id)

    def get_by_discussion_session(self, session_id: str) -> ImprovementProposal | None:
        return (
            self.session.query(ImprovementProposal)
            .filter(ImprovementProposal.discussion_session_id == session_id)
            .one_or_none()
        )

    def list_recent(self, limit: int = 50, status: str | None = None) -> list[ImprovementProposal]:
        q = self.session.query(ImprovementProposal)
        if status:
            q = q.filter(ImprovementProposal.status == status)
        return q.order_by(ImprovementProposal.created_at.desc()).limit(limit).all()

    def list_by_status(self, status: str) -> list[ImprovementProposal]:
        return (
            self.session.query(ImprovementProposal)
            .filter(ImprovementProposal.status == status)
            .order_by(ImprovementProposal.created_at.desc())
            .all()
        )

    def get_oldest_by_status(self, status: str) -> ImprovementProposal | None:
        """Return the oldest proposal in ``status`` for FIFO queue draining."""
        return (
            self.session.query(ImprovementProposal)
            .filter(ImprovementProposal.status == status)
            .order_by(ImprovementProposal.created_at.asc(), ImprovementProposal.id.asc())
            .first()
        )

    def list_with_worktrees(
        self,
        *,
        statuses: list[str],
    ) -> list[ImprovementProposal]:
        """Return proposals that still point at an implementation worktree."""
        return (
            self.session.query(ImprovementProposal)
            .filter(
                ImprovementProposal.status.in_(statuses),
                ImprovementProposal.worktree_path.is_not(None),
            )
            .order_by(
                ImprovementProposal.completed_at.desc().nullslast(),
                ImprovementProposal.created_at.desc(),
                ImprovementProposal.id.desc(),
            )
            .all()
        )

    def has_in_progress(self) -> bool:
        """Serialisation gate (FR-018): at most one in_progress proposal."""
        return (
            self.session.query(ImprovementProposal)
            .filter(ImprovementProposal.status == "in_progress")
            .first()
            is not None
        )

    # -- CAS state transitions ------------------------------------------------

    def approve(
        self, proposal_id: str, supplement: str | None = None
    ) -> ImprovementProposal | None:
        """CAS pending_review -> approved.  Returns updated row or None."""
        return self._cas_transition(
            proposal_id,
            from_status="pending_review",
            to_status="approved",
            extra_updates={
                "user_supplement": supplement,
                "decided_at": utc_now_naive().isoformat(),
            },
        )

    def reject(self, proposal_id: str) -> ImprovementProposal | None:
        """CAS pending_review|failed -> rejected.  Returns updated row or None."""
        return self._cas_transition(
            proposal_id,
            from_status=_sources_for("rejected"),
            to_status="rejected",
            extra_updates={"decided_at": utc_now_naive().isoformat()},
        )

    def mark_in_progress(
        self,
        proposal_id: str,
        *,
        graph_id: str,
        worktree_path: str,
        branch_name: str,
    ) -> ImprovementProposal | None:
        """CAS approved -> in_progress when no other proposal is running.

        FR-018 requires a single in-progress self-improvement implementation.
        Keep the "no other in_progress row exists" guard in the same SQL UPDATE
        as the status transition, so concurrent bridge threads cannot both win
        after observing an idle queue.
        """
        updated = (
            self.session.query(ImprovementProposal)
            .filter(
                ImprovementProposal.id == proposal_id,
                ImprovementProposal.status == "approved",
                ~self.session.query(ImprovementProposal.id)
                .filter(ImprovementProposal.status == "in_progress")
                .exists(),
            )
            .update(
                {
                    "status": "in_progress",
                    "graph_id": graph_id,
                    "worktree_path": worktree_path,
                    "branch_name": branch_name,
                },
                synchronize_session=False,
            )
        )
        self._commit()
        if updated == 0:
            return None
        return self._refetch(proposal_id)

    def mark_done(
        self,
        proposal_id: str,
        *,
        summary: str | None = None,
        tests_passed: bool = True,
    ) -> ImprovementProposal | None:
        """CAS in_progress -> done.  Returns updated row or None."""
        if tests_passed is not True:
            raise ValueError("done improvement proposals require passing tests")
        return self._cas_transition(
            proposal_id,
            from_status="in_progress",
            to_status="done",
            extra_updates={
                "result_tests_passed": True,
                "result_summary": summary,
                "completed_at": utc_now_naive().isoformat(),
            },
        )

    def mark_failed(
        self,
        proposal_id: str,
        *,
        error: str | None = None,
        tests_passed: bool | None = None,
        summary: str | None = None,
    ) -> ImprovementProposal | None:
        """CAS in_progress|approved -> failed.  Returns updated row or None."""
        extra: dict = {
            "error": error,
            "completed_at": utc_now_naive().isoformat(),
        }
        if tests_passed is not None:
            extra["result_tests_passed"] = tests_passed
        if summary is not None:
            extra["result_summary"] = summary
        return self._cas_transition(
            proposal_id,
            from_status=_sources_for("failed"),
            to_status="failed",
            extra_updates=extra,
        )

    def clear_worktree_location(
        self,
        proposal_id: str,
        *,
        clear_branch: bool = True,
    ) -> ImprovementProposal | None:
        """Clear stale worktree metadata after cleanup."""
        values: dict = {"worktree_path": None}
        if clear_branch:
            values["branch_name"] = None
        updated = (
            self.session.query(ImprovementProposal)
            .filter(ImprovementProposal.id == proposal_id)
            .update(values, synchronize_session=False)
        )
        self._commit()
        if updated == 0:
            return None
        return self._refetch(proposal_id)

    # -- Discussion session binding (028) --------------------------------------

    def bind_discussion_session(self, proposal_id: str, session_id: str) -> bool:
        """First-time binding via conditional UPDATE (idempotency guard).

        Matches only when no discussion session is bound yet; rowcount 0 means
        another caller won the race (or the proposal doesn't exist) and the
        caller must discard its own session and re-read the winner's binding.
        """
        updated = (
            self.session.query(ImprovementProposal)
            .filter(
                ImprovementProposal.id == proposal_id,
                ImprovementProposal.discussion_session_id.is_(None),
            )
            .update({"discussion_session_id": session_id}, synchronize_session=False)
        )
        self._commit()
        return updated == 1

    def rebind_discussion_session(self, proposal_id: str, session_id: str) -> None:
        """Replace a binding whose session is confirmed dead (self-heal path)."""
        self.session.query(ImprovementProposal).filter(
            ImprovementProposal.id == proposal_id
        ).update({"discussion_session_id": session_id}, synchronize_session=False)
        self._commit()

    # -- Internal helpers -----------------------------------------------------

    def _cas_transition(
        self,
        proposal_id: str,
        *,
        from_status: str | frozenset[str],
        to_status: str,
        extra_updates: dict | None = None,
    ) -> ImprovementProposal | None:
        """Atomic conditional UPDATE with rowcount CAS guard.

        ``from_status`` may be a single status or a set of valid source
        statuses; the UPDATE matches nothing (rowcount 0 -> None) when the
        current status is not among them, so invalid transitions are rejected
        without a pre-read.
        """
        from_statuses = {from_status} if isinstance(from_status, str) else set(from_status)
        values: dict = {"status": to_status}
        if extra_updates:
            values.update(extra_updates)
        updated = (
            self.session.query(ImprovementProposal)
            .filter(
                ImprovementProposal.id == proposal_id,
                ImprovementProposal.status.in_(from_statuses),
            )
            .update(values, synchronize_session=False)
        )
        self._commit()
        if updated == 0:
            return None
        return self._refetch(proposal_id)

    def _refetch(self, proposal_id: str) -> ImprovementProposal | None:
        """Re-read the row with populate_existing after a bulk UPDATE."""
        return (
            self.session.query(ImprovementProposal)
            .populate_existing()
            .filter(ImprovementProposal.id == proposal_id)
            .one_or_none()
        )

    @staticmethod
    def _get_dedup_cooldown_hours() -> int:
        """Lazy-load dedup cooldown from config (avoids circular import)."""
        from src.data.unified_config import get_unified_config

        return get_unified_config().get_self_improvement_proposals_dedup_cooldown_hours()


def compute_dedup_key(finding_type: str | None, what: str | None) -> str | None:
    """Compute a stable dedup key from finding type + normalised what."""
    if not what:
        return None
    normalised = what.strip().lower()
    prefix = (finding_type or "unknown").strip().lower()
    payload = f"{prefix}:{normalised}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]
