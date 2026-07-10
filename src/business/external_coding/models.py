"""Domain models for external coding sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ExternalCodingTool(StrEnum):
    CLAUDE_CODE = "claude_code"
    CODEX_CLI = "codex_cli"


class LaunchMode(StrEnum):
    HEADLESS = "headless"
    INTERACTIVE = "interactive"


class OwnerType(StrEnum):
    TASK = "task"
    WORKFLOW = "workflow"


class CodingPhase(StrEnum):
    PLAN = "plan"
    IMPLEMENT = "implement"
    MERGE = "merge"
    ROLLBACK = "rollback"
    DONE = "done"


class CodingSessionStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    PLAN_APPROVED = "plan_approved"
    PLAN_REJECTED = "plan_rejected"
    IMPLEMENTING = "implementing"
    INTERRUPTED = "interrupted"
    WAITING_USER = "waiting_user"
    COMPLETED = "completed"
    MERGE_READY = "merge_ready"
    MERGED = "merged"
    MERGE_BLOCKED = "merge_blocked"
    ROLLBACK_PROPOSED = "rollback_proposed"
    ROLLED_BACK = "rolled_back"
    ABANDONED = "abandoned"
    FAILED = "failed"


class AttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class QuotaState(StrEnum):
    AVAILABLE = "available"
    LOW = "low"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class ErrorCategory(StrEnum):
    QUOTA_EXHAUSTED = "quota_exhausted"
    NETWORK = "network"
    LOGIN_REQUIRED = "login_required"
    MODEL_UNAVAILABLE = "model_unavailable"
    MISSING_ARTIFACT = "missing_artifact"
    PROTOCOL_VIOLATION = "protocol_violation"
    PROCESS_ERROR = "process_error"
    UNKNOWN = "unknown"


class ConflictRisk(StrEnum):
    LOW = "low"
    OVERLAP = "overlap"
    CONFLICT_PREDICTED = "conflict_predicted"
    UNKNOWN = "unknown"


class MergeRecordStatus(StrEnum):
    ANALYSIS_READY = "analysis_ready"
    MERGED = "merged"
    BLOCKED = "blocked"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class RollbackStrategy(StrEnum):
    REVERT_COMMIT = "revert_commit"
    REVERSE_PATCH = "reverse_patch"
    RESET_HARD = "reset_hard"
    MANUAL = "manual"


class RollbackDecisionStatus(StrEnum):
    PROPOSED = "proposed"
    APPLIED = "applied"
    BLOCKED = "blocked"
    FAILED = "failed"


# Status groupings shared by the service and serializers. Kept here so a status
# transition rule lives in exactly one place; adding a new status only requires
# updating the enum plus the relevant frozenset.
RESUMABLE_CODING_STATUSES = frozenset(
    {
        CodingSessionStatus.INTERRUPTED.value,
        CodingSessionStatus.PLAN_REJECTED.value,
        CodingSessionStatus.PLAN_APPROVED.value,
        CodingSessionStatus.WAITING_USER.value,
    }
)
TERMINAL_CODING_STATUSES = frozenset(
    {
        CodingSessionStatus.MERGED.value,
        CodingSessionStatus.ROLLED_BACK.value,
        CodingSessionStatus.ABANDONED.value,
    }
)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QuotaSignal:
    tool: ExternalCodingTool
    state: QuotaState
    source: str
    confidence: float
    checked_at: str
    reset_at: str | None = None
    safe_detail: str | None = None


@dataclass(frozen=True)
class ProcessStartResult:
    status: AttemptStatus
    command_summary: str
    pid: int | None = None
    external_session_ref: str | None = None
    exit_code: int | None = None
    log_path: str | None = None
    log_tail: str | None = None
    error_category: ErrorCategory | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class MergeAnalysis:
    target_branch: str
    target_worktree_path: str
    pre_merge_head: str
    coding_branch_head: str
    dirty_files: list[str]
    changed_files: list[str]
    overlap_files: list[str]
    conflict_risk: ConflictRisk
