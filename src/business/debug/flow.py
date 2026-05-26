"""Agent Flow projection — reads authoritative transitions, adds ephemeral debug detail.

``FlowCorrelationService`` manages ephemeral delegation task/result detail that
supplements the authoritative ``workflow_transitions`` already persisted by the
orchestration layer.  Ephemeral detail exists only while tracing is armed and
is destroyed on disable/clear/restart.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.business.debug.trace_buffer import SharedRetentionBudget


@dataclass(frozen=True)
class EphemeralFlowDetail:
    """Ephemeral debug detail attached to a workflow transition.

    This data is process-local and exists only for the current enabled
    tracing epoch.  It is never persisted to the database.
    """

    transition_id: str
    workflow_id: str
    retention_epoch: str
    detail_type: str  # "delegated_task" | "delegated_result" | "diagnostic_error"
    content: str
    retained_bytes: int
    detail_availability: str = "full_text"  # same enum as LLMTraceRecord
    provenance: str = "ephemeral_debug_capture"


class FlowCorrelationService:
    """Manage ephemeral flow detail scoped to the current tracing epoch.

    Parameters
    ----------
    max_total_bytes:
        Aggregate byte budget for all ephemeral detail.  Content that would
        exceed the budget is stored with ``detail_availability`` set to
        ``"oversized_omitted"``.
    """

    def __init__(
        self,
        max_total_bytes: int = 16_777_216,
        shared_budget: SharedRetentionBudget | None = None,
    ) -> None:
        self._details: dict[str, EphemeralFlowDetail] = {}  # transition_id -> detail
        self._epoch: str | None = None
        self._retained_bytes: int = 0
        self._max_bytes: int = max(1, max_total_bytes)
        self._budget = shared_budget or SharedRetentionBudget(self._max_bytes)
        self._lock = self._budget.lock

    # ---- epoch management ----

    def set_epoch(self, epoch: str) -> None:
        """Set the current retention epoch.

        Clears any previously stored detail.
        """
        with self._lock:
            self._release_retained_bytes_unlocked()
            self._epoch = epoch
            self._details.clear()

    def clear_epoch(self) -> None:
        """Invalidate the current epoch and clear all detail."""
        with self._lock:
            self._release_retained_bytes_unlocked()
            self._epoch = None
            self._details.clear()

    # ---- detail management ----

    def add_detail(
        self,
        transition_id: str,
        workflow_id: str,
        detail_type: str,
        content: str,
    ) -> EphemeralFlowDetail | None:
        """Attach ephemeral detail to a workflow transition.

        Returns the created detail, or ``None`` if no epoch is active.

        If the content would exceed the aggregate byte budget, the detail is
        stored with ``detail_availability="oversized_omitted"`` and empty
        content.
        """
        with self._lock:
            if not self._epoch:
                return None

            existing = self._details.pop(transition_id, None)
            if existing is not None:
                self._retained_bytes -= existing.retained_bytes
                self._budget.release(self._budget_key(existing))

            content_bytes = len(content.encode("utf-8"))
            retained = (
                content_bytes <= self._max_bytes
                and self._budget.reserve(
                    self._budget_key_for_current_epoch(transition_id),
                    content_bytes,
                    lambda: self._evict_detail_unlocked(transition_id),
                )
            )
            detail = EphemeralFlowDetail(
                transition_id=transition_id,
                workflow_id=workflow_id,
                retention_epoch=self._epoch,
                detail_type=detail_type,
                content=content if retained else "",
                retained_bytes=content_bytes if retained else 0,
                detail_availability="full_text" if retained else "oversized_omitted",
            )

            self._details[transition_id] = detail
            self._retained_bytes += detail.retained_bytes
            return detail

    def get_detail(self, transition_id: str) -> EphemeralFlowDetail | None:
        """Return ephemeral detail for a transition, or ``None``."""
        with self._lock:
            detail = self._details.get(transition_id)
            if detail is None:
                return None
            if self._epoch and detail.retention_epoch == self._epoch:
                return detail
            return None

    def get_details_for_workflow(self, workflow_id: str) -> list[EphemeralFlowDetail]:
        """Return all ephemeral detail for a given workflow in the current epoch."""
        with self._lock:
            if not self._epoch:
                return []
            return [
                d
                for d in self._details.values()
                if d.workflow_id == workflow_id and d.retention_epoch == self._epoch
            ]

    def clear(self) -> None:
        """Clear all stored ephemeral detail and reset byte accounting."""
        with self._lock:
            self._release_retained_bytes_unlocked()
            self._details.clear()

    @property
    def retained_bytes(self) -> int:
        """Total retained bytes across all stored ephemeral detail."""
        with self._lock:
            return self._retained_bytes

    def _release_retained_bytes_unlocked(self) -> None:
        for detail in self._details.values():
            self._budget.release(self._budget_key(detail))
        self._retained_bytes = 0

    def _evict_detail_unlocked(self, transition_id: str) -> None:
        detail = self._details.get(transition_id)
        if detail is not None:
            self._retained_bytes -= detail.retained_bytes
            self._details[transition_id] = EphemeralFlowDetail(
                transition_id=detail.transition_id,
                workflow_id=detail.workflow_id,
                retention_epoch=detail.retention_epoch,
                detail_type=detail.detail_type,
                content="",
                retained_bytes=0,
                detail_availability="oversized_omitted",
            )

    @staticmethod
    def _budget_key(detail: EphemeralFlowDetail) -> str:
        return f"flow:{detail.retention_epoch}:{detail.transition_id}"

    def _budget_key_for_current_epoch(self, transition_id: str) -> str:
        return f"flow:{self._epoch}:{transition_id}"


# ---------------------------------------------------------------------------
# Event-type to stable UI status mapping
# ---------------------------------------------------------------------------

_EVENT_STATUS_MAP: dict[str, str] = {
    "requirement_confirmed": "handoff",
    "review_passed": "accepted",
    "review_failed": "retry",
    "code_completed": "completed",
    "trial_success": "completed",
    "trial_failed": "failed",
    "tool_saved": "published",
    "triage_completed": "handoff",
    "assistant_delegation_started": "handoff",
    "assistant_delegation_completed": "completed",
    "assistant_delegation_failed": "failed",
    "agent_error": "failed",
}


def classify_event_status(event_type: str) -> str:
    """Map a transition ``event_type`` to a stable UI status string.

    Returns ``"waiting"`` for unknown event types.
    """
    return _EVENT_STATUS_MAP.get(event_type, "waiting")
