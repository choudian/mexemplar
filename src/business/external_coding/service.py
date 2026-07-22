"""Business service for external coding sessions."""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.data.repos.base_repository import generate_id
from src.data.repos.external_coding_session_repository import ExternalCodingSessionRepository
from src.data.unified_config import UnifiedConfigManager, get_unified_config
from src.execution.external_coding_process import ExternalProcessTerminationOutcome
from src.utils.events import emit
from src.utils.timezone import utc_now_naive

from .artifacts import (
    PLAN_FILENAME,
    RESULT_FILENAME,
    ensure_artifact_dir,
    read_text_if_exists,
    tail_file,
    write_attempt_prompt,
    write_handoff,
)
from .cli_adapters import CliExternalCodingAdapter, ExternalCodingAdapter
from .git_ops import GitOperationError, GitOps, GitProcessError
from .models import (
    AttemptStatus,
    CodingPhase,
    CodingSessionStatus,
    ConflictRisk,
    ErrorCategory,
    ExternalCodingTool,
    LaunchMode,
    MergeRecordStatus,
    OwnerType,
    ProcessStartResult,
    QuotaSignal,
    QuotaState,
    RESUMABLE_CODING_STATUSES,
    RollbackStrategy,
    TERMINAL_CODING_STATUSES,
)
from .quota_probe import QuotaProbe, choose_tool
from .serializers import (
    _json_loads_list,
    _safe_text,
    detail_to_dict,
    merge_record_to_dict,
    rollback_to_dict,
    summary_to_dict,
)
from .validators import validate_plan_markdown, validate_result_markdown

AdapterFactory = Callable[[], ExternalCodingAdapter]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _StartupResources:
    repo_root: Path
    worktree_path: Path
    branch_name: str
    artifact_dir: Path
    remove_worktree_root: bool
    remove_artifact_root: bool


def _now() -> str:
    return utc_now_naive().isoformat()


def _attempt_fields_from_result(
    result: ProcessStartResult,
    *,
    log_path: Path,
    max_log_chars: int,
    fallback_pid: int | None = None,
    fallback_process_create_time: float | None = None,
    fallback_external_session_ref: str | None = None,
    include_command_summary: bool = False,
) -> dict[str, object]:
    """Project an adapter result into the durable attempt field set."""
    fields: dict[str, object] = {
        "status": result.status.value,
        "pid": result.pid or fallback_pid,
        "process_create_time": (
            result.process_create_time
            if result.process_create_time is not None
            else fallback_process_create_time
        ),
        # A running attempt still owns a process (or an unresolved spawn), so
        # only a deterministic terminal observation may clear this guard.
        "termination_unconfirmed": result.status == AttemptStatus.RUNNING,
        "exit_code": result.exit_code,
        "log_path": str(log_path),
        "log_tail": (
            _safe_text(result.log_tail, max_chars=max_log_chars) if result.log_tail else None
        ),
        "external_session_ref": (result.external_session_ref or fallback_external_session_ref),
        "error_category": result.error_category.value if result.error_category else None,
        "error_message": (
            _safe_text(result.error_message, max_chars=600) if result.error_message else None
        ),
    }
    if include_command_summary:
        fields["command_summary"] = (
            _safe_text(result.command_summary, max_chars=500) if result.command_summary else None
        )
    return fields


def _validate_branch_name(name: str) -> str:
    """Reject branch names that could inject unexpected git arguments."""
    parts = name.split("/") if name else []
    if (
        not name
        or not re.fullmatch(r"[a-zA-Z0-9/_.-]+", name)
        or name.startswith(("-", ".", "/"))
        or name.endswith((".", "/"))
        or ".." in name
        or "//" in name
        or any(not part or part.startswith(".") or part.endswith(".lock") for part in parts)
    ):
        raise ValueError(
            "invalid branch name: must contain only alphanumeric, /, _, ., - characters"
        )
    return name


class ExternalCodingSessionService:
    """Owner-bound external coding session orchestration."""

    def __init__(
        self,
        *,
        repo: ExternalCodingSessionRepository | None = None,
        config: UnifiedConfigManager | None = None,
        git_ops: GitOps | None = None,
        quota_probe: QuotaProbe | None = None,
        adapter_factory: AdapterFactory | None = None,
    ) -> None:
        self._repo = repo or ExternalCodingSessionRepository()
        self._owns_repo = repo is None
        self._config = config or get_unified_config()
        self._git = git_ops or GitOps()
        self._quota_probe = quota_probe
        self._adapter_factory = adapter_factory or (
            lambda: CliExternalCodingAdapter(config=self._config)
        )

    def close(self) -> None:
        if self._owns_repo:
            self._repo.close()

    def __enter__(self) -> "ExternalCodingSessionService":
        return self

    def __exit__(self, *_):
        self.close()

    def start_session(
        self,
        *,
        owner_type: str,
        owner_id: str,
        objective: str,
        context: str = "",
        session_id: str | None = None,
        parent_session_id: str | None = None,
        tool_preference: str | None = None,
        launch_mode: str | None = None,
        target_branch: str | None = None,
        target_worktree_path: str | None = None,
        explicit_exhausted_override: bool = False,
    ) -> dict:
        if not self._config.get_external_coding_enabled():
            raise ValueError("external coding sessions are disabled")
        owner = self._coerce_owner(owner_type, owner_id)
        if not objective.strip():
            raise ValueError("objective is required for external coding sessions")
        raw_target_path = (target_worktree_path or "").strip()
        if not raw_target_path:
            raise ValueError(
                "target repository path is required; provide an absolute path "
                "to a usable git repository"
            )
        target_path = Path(raw_target_path).expanduser()
        if not target_path.is_absolute():
            raise ValueError(
                "target repository path must be absolute; provide the absolute path "
                "to a usable git repository"
            )
        try:
            if not target_path.exists():
                raise ValueError(
                    "target repository path does not exist; provide an " "existing absolute path"
                )
            if not target_path.is_dir():
                raise ValueError(
                    "target repository must be a usable git repository with at least one commit"
                )
            repo_root = target_path.resolve(strict=True)
        except OSError:
            raise ValueError(
                "target repository path could not be accessed; provide an accessible "
                "absolute path"
            ) from None
        try:
            base_commit = self._git.head(repo_root, "HEAD")
        except GitProcessError as exc:
            logger.warning(
                "target repository Git process could not be used (%s)",
                type(exc).__name__,
            )
            raise ValueError(
                "target repository could not be inspected; verify Git is installed "
                "and the repository is accessible"
            ) from None
        except GitOperationError as exc:
            logger.warning(
                "target repository HEAD could not be resolved (%s)",
                type(exc).__name__,
            )
            raise ValueError(
                "target repository must be a usable git repository with at least one commit"
            ) from None
        mode = LaunchMode(launch_mode or self._config.get_external_coding_default_launch_mode())

        signals = self._probe_and_persist_quota()
        tool, selected_reason = choose_tool(
            preference=tool_preference or self._config.get_external_coding_preferred_tool(),
            signals=signals,
            explicit_exhausted_override=explicit_exhausted_override,
        )
        signal = signals.get(tool)
        if target_branch:
            _validate_branch_name(target_branch)
        coding_session_id = generate_id("ecs")
        artifact_root = (
            Path(self._config.get_external_coding_artifact_root()).expanduser().resolve()
        )
        configured_worktree_root = Path(
            self._config.get_external_coding_worktree_root()
        ).expanduser()
        worktree_root = (
            configured_worktree_root
            if configured_worktree_root.is_absolute()
            else repo_root / configured_worktree_root
        ).resolve()
        artifact_dir = artifact_root / coding_session_id
        worktree_path = (worktree_root / coding_session_id).resolve()
        branch_name = f"coding/{coding_session_id}"
        branch_exists = getattr(self._git, "branch_exists", None)
        try:
            generated_branch_exists = bool(
                callable(branch_exists) and branch_exists(repo_root, branch_name)
            )
        except GitOperationError as exc:
            logger.warning(
                "external coding generated branch state could not be checked (%s)",
                type(exc).__name__,
            )
            raise ValueError(
                "target repository state could not be verified; verify Git access and retry"
            ) from None
        generated_target_exists = (
            artifact_dir.exists() or worktree_path.exists() or generated_branch_exists
        )
        if generated_target_exists:
            raise ValueError("failed to allocate external coding session paths; retry the request")
        artifact_root_existed = artifact_root.exists()
        worktree_root_existed = worktree_root.exists()
        resources = _StartupResources(
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch_name=branch_name,
            artifact_dir=artifact_dir,
            remove_worktree_root=not worktree_root_existed,
            remove_artifact_root=not artifact_root_existed,
        )
        startup_stage = "artifacts"
        worktree_started = False
        try:
            artifact_dir = ensure_artifact_dir(artifact_root, coding_session_id)
            plan_path = artifact_dir / PLAN_FILENAME
            result_path = artifact_dir / RESULT_FILENAME
            handoff_path = write_handoff(
                artifact_dir,
                objective=objective,
                context=context,
                plan_path=plan_path,
                result_path=result_path,
                worktree_path=worktree_path,
            )

            startup_stage = "worktree"
            worktree_started = True
            self._git.create_worktree(
                target_worktree=repo_root,
                worktree_path=worktree_path,
                branch_name=branch_name,
            )

            startup_stage = "persistence"
            row = self._repo.create_session(
                coding_session_id=coding_session_id,
                session_id=session_id,
                owner_type=owner.value,
                owner_id=owner_id.strip(),
                parent_session_id=parent_session_id,
                tool=tool.value,
                launch_mode=mode.value,
                status=CodingSessionStatus.PLANNING.value,
                phase=CodingPhase.PLAN.value,
                selected_reason=selected_reason,
                quota_state=signal.state.value if signal else QuotaState.UNKNOWN.value,
                worktree_path=str(worktree_path),
                branch_name=branch_name,
                base_commit=base_commit,
                artifact_dir=str(artifact_dir),
                handoff_path=str(handoff_path),
                plan_path=str(plan_path),
                result_path=str(result_path),
                target_branch=target_branch,
                target_worktree_path=str(repo_root),
            )
        except Exception as exc:
            durable_row = None
            if startup_stage == "persistence":
                try:
                    durable_row = self._repo.get_session(coding_session_id)
                except Exception as lookup_exc:
                    logger.error(
                        "external coding session persistence outcome is unknown for %s "
                        "(create=%s lookup=%s)",
                        coding_session_id,
                        type(exc).__name__,
                        type(lookup_exc).__name__,
                    )
                    raise ValueError(
                        "external coding session persistence could not be verified; "
                        "generated resources were retained for recovery under "
                        f"session {coding_session_id}"
                    ) from None
            if durable_row is not None:
                logger.warning(
                    "external coding session create raised after durable persistence (%s)",
                    type(exc).__name__,
                )
                row = durable_row
            else:
                cleanup_errors = self._cleanup_failed_startup(
                    resources,
                    cleanup_git=worktree_started,
                )
                if cleanup_errors:
                    logger.error(
                        "external coding startup compensation was incomplete at %s (%s)",
                        startup_stage,
                        ",".join(cleanup_errors),
                    )
                    raise ValueError(
                        "external coding session startup failed and cleanup could not be completed "
                        f"for session {coding_session_id}; remove the generated session resources "
                        "and retry"
                    ) from None
                logger.warning(
                    "external coding session startup failed at %s (%s)",
                    startup_stage,
                    type(exc).__name__,
                )
                if startup_stage == "artifacts":
                    raise ValueError(
                        "failed to create external coding artifacts; "
                        "verify the configured artifact root"
                    ) from None
                if startup_stage == "worktree":
                    raise ValueError(
                        "failed to create external coding worktree; verify the repository "
                        "and configured worktree root"
                    ) from None
                raise ValueError(
                    "failed to persist external coding session; retry the request"
                ) from None
        row = self._repo.get_session(row.coding_session_id)
        if mode == LaunchMode.INTERACTIVE or self._config.get_external_coding_autostart_enabled():
            self._start_attempt(row, CodingPhase.PLAN)
            row = self._repo.get_session(row.coding_session_id)
        # Autostart may flip the session to interrupted if the CLI failed to
        # launch; emit the actual outcome rather than always reporting "created".
        change_type = (
            "start_failed" if row.status == CodingSessionStatus.INTERRUPTED.value else "created"
        )
        self._emit(row, change_type)
        return self.detail_to_dict(row)

    def refresh_session(self, coding_session_id: str) -> dict:
        row = self._require_session(coding_session_id)
        if row.phase == CodingPhase.PLAN.value and row.status in {
            CodingSessionStatus.PLANNING.value,
            CodingSessionStatus.INTERRUPTED.value,
        }:
            row = self._refresh_plan(row)
        elif row.phase == CodingPhase.IMPLEMENT.value and row.status in {
            CodingSessionStatus.IMPLEMENTING.value,
            CodingSessionStatus.INTERRUPTED.value,
        }:
            row = self._refresh_result(row)
        return self.detail_to_dict(row)

    def decide_plan(
        self,
        *,
        coding_session_id: str,
        decision: str,
        decided_by: str = "agent",
        feedback: str = "",
    ) -> dict:
        row = self._require_session(coding_session_id)
        if row.status != CodingSessionStatus.PLAN_READY.value:
            raise ValueError("plan is not ready for decision")
        normalized = decision.strip().lower()
        if normalized == "approved":
            row = self._repo.update_session(
                coding_session_id,
                status=CodingSessionStatus.PLAN_APPROVED.value,
                phase=CodingPhase.IMPLEMENT.value,
                plan_approved_at=_now(),
                plan_approved_by=decided_by,
                last_error_category=None,
                last_error_message=None,
            )
            if (
                row.launch_mode == LaunchMode.INTERACTIVE.value
                or self._config.get_external_coding_autostart_enabled()
            ):
                row = self._repo.update_session(
                    coding_session_id,
                    status=CodingSessionStatus.IMPLEMENTING.value,
                    phase=CodingPhase.IMPLEMENT.value,
                )
                self._start_attempt(
                    row,
                    CodingPhase.IMPLEMENT,
                    approval_feedback=feedback,
                )
                row = self._repo.get_session(coding_session_id)
            self._emit(row, "plan_approved")
            return self.detail_to_dict(row)
        if normalized in {"rejected", "clarification_requested"}:
            if not feedback.strip():
                raise ValueError("feedback is required when a plan is not approved")
            row = self._repo.update_session(
                coding_session_id,
                status=CodingSessionStatus.PLAN_REJECTED.value,
                phase=CodingPhase.PLAN.value,
                last_error_category=ErrorCategory.PROTOCOL_VIOLATION.value,
                last_error_message=_safe_text(feedback or "plan requires revision"),
            )
            self._emit(row, "plan_rejected")
            return self.detail_to_dict(row)
        raise ValueError("decision must be approved, rejected or clarification_requested")

    def resume_session(
        self,
        *,
        coding_session_id: str,
        instruction: str = "",
        phase: str | None = None,
    ) -> dict:
        row = self._require_session(coding_session_id)
        active_attempt = self._repo.get_active_attempt(coding_session_id)
        if active_attempt is not None and not active_attempt.launch_started:
            if not self._fail_reserved_attempt(
                row,
                active_attempt.attempt_id,
                message="external coding launch did not begin",
            ):
                raise RuntimeError("unlaunched external coding reservation could not be recovered")
            row = self._require_session(coding_session_id)
            active_attempt = None
        if active_attempt is not None:
            raise ValueError("session has an active external coding attempt")
        if row.status not in RESUMABLE_CODING_STATUSES:
            raise ValueError(f"session in status {row.status} cannot be resumed")
        target_phase = CodingPhase(phase or row.phase)
        if target_phase == CodingPhase.IMPLEMENT and not row.plan_approved_at:
            raise ValueError("implementation cannot resume before plan approval")
        if target_phase == CodingPhase.PLAN:
            status = CodingSessionStatus.PLANNING
        elif target_phase == CodingPhase.IMPLEMENT:
            status = CodingSessionStatus.IMPLEMENTING
        else:
            raise ValueError("only plan or implement phases can be resumed")
        previous_feedback = (
            row.last_error_message if row.status == CodingSessionStatus.PLAN_REJECTED.value else ""
        )
        row = self._repo.update_session(
            coding_session_id,
            status=status.value,
            phase=target_phase.value,
            resume_count=(row.resume_count or 0) + 1,
            last_error_category=None,
            last_error_message=None,
            **(
                {"plan_approved_at": None, "plan_approved_by": None}
                if target_phase == CodingPhase.PLAN
                else {}
            ),
        )
        self._start_attempt(
            row,
            target_phase,
            approval_feedback=previous_feedback or "",
            resume_instruction=instruction,
        )
        row = self._repo.get_session(coding_session_id)
        self._emit(row, "resumed")
        return self.detail_to_dict(row)

    def escalate_to_user(
        self,
        *,
        coding_session_id: str,
        reason: str,
    ) -> dict:
        """Transition an interrupted session to waiting_user when the agent cannot resolve it internally.

        FR-020: waiting_user MUST only be entered after an agent decides the
        interruption cannot be resolved internally and asks the user for action
        or clarification.
        """
        row = self._require_session(coding_session_id)
        if row.status != CodingSessionStatus.INTERRUPTED.value:
            raise ValueError("only interrupted sessions can be escalated to waiting_user")
        row = self._repo.update_session(
            coding_session_id,
            status=CodingSessionStatus.WAITING_USER.value,
            last_error_message=_safe_text(reason, max_chars=600),
        )
        self._emit(row, "waiting_user")
        return self.detail_to_dict(row)

    def abandon_session(self, *, coding_session_id: str, reason: str) -> dict:
        row = self._require_session(coding_session_id)
        if row.status in TERMINAL_CODING_STATUSES:
            raise ValueError(f"session in status {row.status} cannot be abandoned")
        session_fields = {
            "status": CodingSessionStatus.ABANDONED.value,
            "phase": CodingPhase.DONE.value,
            "last_error_category": ErrorCategory.UNKNOWN.value,
            "last_error_message": _safe_text(reason, max_chars=600),
        }
        row = self._stop_running_attempts(
            row,
            reason="session abandoned",
            session_fields=session_fields,
        ) or self._repo.update_session(coding_session_id, **session_fields)
        self._emit(row, "abandoned")
        return self.detail_to_dict(row)

    def list_sessions(
        self,
        *,
        session_id: str | None = None,
        owner_type: str | None = None,
        owner_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        rows = self._repo.list_sessions(
            session_id=session_id,
            owner_type=owner_type,
            owner_id=owner_id,
            status=status,
            limit=max(1, min(limit, 100)),
        )
        return [self.summary_to_dict(row) for row in rows]

    def get_session(self, coding_session_id: str) -> dict:
        return self.detail_to_dict(self._require_session(coding_session_id))

    def require_owner(
        self,
        coding_session_id: str,
        *,
        owner_type: str,
        owner_id: str,
    ) -> None:
        """Fail closed when a caller tries to cross an owner boundary."""
        row = self._require_session(coding_session_id)
        expected_owner = self._coerce_owner(owner_type, owner_id)
        if row.owner_type != expected_owner.value or row.owner_id != owner_id.strip():
            raise PermissionError("external coding session belongs to a different owner")

    def list_task_summaries(self, task_id: str) -> list[dict]:
        return [self._task_summary(row) for row in self._repo.list_for_owner("task", task_id)]

    def list_task_summaries_by_task(self, task_ids: list[str]) -> dict[str, list[dict]]:
        grouped = {task_id: [] for task_id in dict.fromkeys(task_ids) if task_id}
        for row in self._repo.list_for_owners("task", list(grouped)):
            grouped[row.owner_id].append(self._task_summary(row))
        return grouped

    def record_review_outcome(
        self,
        *,
        coding_session_id: str,
        independently_reviewed: bool,
        independently_tested: bool,
        skipped_reason: str = "",
    ) -> dict:
        row = self._require_session(coding_session_id)
        reviewable_statuses = {
            CodingSessionStatus.COMPLETED.value,
            CodingSessionStatus.MERGE_READY.value,
            CodingSessionStatus.MERGE_BLOCKED.value,
            CodingSessionStatus.MERGED.value,
            CodingSessionStatus.ROLLBACK_PROPOSED.value,
        }
        if row.status not in reviewable_statuses:
            raise ValueError("review outcome can only be recorded after completion")
        complete = independently_reviewed and independently_tested
        if not complete and not skipped_reason.strip():
            raise ValueError("skippedReason is required when review or test is skipped")
        row = self._repo.update_session(
            coding_session_id,
            review_recommended=not complete,
            review_skipped_reason=(None if complete else _safe_text(skipped_reason, max_chars=600)),
        )
        self._emit(row, "review_recorded")
        return self.detail_to_dict(row)

    @staticmethod
    def _task_summary(row) -> dict:
        return {
            "codingSessionId": row.coding_session_id,
            "tool": row.tool,
            "status": row.status,
            "phase": row.phase,
        }

    def analyze_merge(
        self,
        *,
        coding_session_id: str,
        target_branch: str,
        target_worktree_path: str,
    ) -> dict:
        _validate_branch_name(target_branch)
        row = self._require_session(coding_session_id)
        if row.status not in {
            CodingSessionStatus.COMPLETED.value,
            CodingSessionStatus.MERGE_READY.value,
            CodingSessionStatus.MERGE_BLOCKED.value,
        }:
            raise ValueError("session must be completed before merge analysis")
        try:
            analysis = self._git.merge_analysis(
                coding_worktree=Path(row.worktree_path),
                coding_branch=row.branch_name,
                target_worktree=Path(target_worktree_path),
                target_branch=target_branch,
            )
        except Exception as exc:
            message = _safe_text(str(exc), max_chars=600)
            row = self._repo.update_session(
                coding_session_id,
                status=CodingSessionStatus.MERGE_BLOCKED.value,
                phase=CodingPhase.MERGE.value,
                last_error_category=ErrorCategory.PROCESS_ERROR.value,
                last_error_message=message,
            )
            self._emit(row, "merge_failed")
            raise ValueError(f"merge analysis failed: {message}") from exc
        merge = self._repo.add_merge_record(
            coding_session_id=coding_session_id,
            target_branch=target_branch,
            target_worktree_path=target_worktree_path,
            pre_merge_head=analysis.pre_merge_head,
            coding_branch_head=analysis.coding_branch_head,
            dirty_files=analysis.dirty_files,
            changed_files=analysis.changed_files,
            overlap_files=analysis.overlap_files,
            conflict_risk=analysis.conflict_risk.value,
        )
        next_status = (
            CodingSessionStatus.MERGE_READY
            if analysis.conflict_risk == ConflictRisk.LOW
            else CodingSessionStatus.MERGE_BLOCKED
        )
        row = self._repo.update_session(
            coding_session_id,
            status=next_status.value,
            phase=CodingPhase.MERGE.value,
            target_branch=target_branch,
            target_worktree_path=target_worktree_path,
        )
        self._emit(row, "merge_analysis")
        return self.merge_record_to_dict(merge)

    def merge_session(
        self,
        *,
        coding_session_id: str,
        merge_record_id: str,
        agent_decision: str = "",
    ) -> dict:
        row = self._require_session(coding_session_id)
        merge = self._repo.get_merge_record(merge_record_id)
        if merge is None or merge.coding_session_id != coding_session_id:
            raise LookupError("merge record not found")
        if row.status not in {
            CodingSessionStatus.MERGE_READY.value,
            CodingSessionStatus.MERGE_BLOCKED.value,
        }:
            raise ValueError("session is not ready for merge")
        if merge.status not in {
            MergeRecordStatus.ANALYSIS_READY.value,
            MergeRecordStatus.BLOCKED.value,
        }:
            raise ValueError("merge record is not available for merge")

        try:
            fresh = self._git.merge_analysis(
                coding_worktree=Path(row.worktree_path),
                coding_branch=row.branch_name,
                target_worktree=Path(merge.target_worktree_path),
                target_branch=merge.target_branch,
            )
        except Exception as exc:
            message = _safe_text(str(exc), max_chars=500)
            self._repo.update_merge_record(
                merge_record_id,
                status=MergeRecordStatus.BLOCKED.value,
                error=f"merge analysis could not be revalidated: {message}",
            )
            row = self._repo.update_session(
                coding_session_id,
                status=CodingSessionStatus.MERGE_BLOCKED.value,
                phase=CodingPhase.MERGE.value,
                last_error_category=ErrorCategory.PROCESS_ERROR.value,
                last_error_message="merge analysis could not be revalidated",
            )
            self._emit(row, "merge_failed")
            raise ValueError("merge analysis could not be revalidated; run analysis again") from exc

        snapshot_matches = (
            fresh.pre_merge_head == merge.pre_merge_head
            and fresh.coding_branch_head == merge.coding_branch_head
            and fresh.target_branch == merge.target_branch
            and str(Path(fresh.target_worktree_path).resolve())
            == str(Path(merge.target_worktree_path).resolve())
            and fresh.dirty_files == _json_loads_list(merge.dirty_files_json)
            and fresh.changed_files == _json_loads_list(merge.changed_files_json)
            and fresh.overlap_files == _json_loads_list(merge.overlap_files_json)
            and fresh.conflict_risk.value == merge.conflict_risk
        )
        if not snapshot_matches:
            self._repo.update_merge_record(
                merge_record_id,
                status=MergeRecordStatus.BLOCKED.value,
                error="merge analysis is stale; run analysis again",
            )
            row = self._repo.update_session(
                coding_session_id,
                status=CodingSessionStatus.MERGE_BLOCKED.value,
                phase=CodingPhase.MERGE.value,
                last_error_category=ErrorCategory.PROCESS_ERROR.value,
                last_error_message="merge analysis is stale; run analysis again",
            )
            self._emit(row, "merge_failed")
            raise ValueError("merge analysis is stale; run analysis again")

        if fresh.conflict_risk != ConflictRisk.LOW and not agent_decision.strip():
            merge = self._repo.update_merge_record(
                merge_record_id,
                status=MergeRecordStatus.BLOCKED.value,
                error="agent decision required for non-low merge risk",
            )
            raise ValueError("merge risk is not low; agent decision is required")
        try:
            merge_commit = self._git.merge(
                target_worktree=Path(merge.target_worktree_path),
                branch_name=row.branch_name,
                expected_target_head=merge.pre_merge_head,
                expected_coding_head=merge.coding_branch_head,
                expected_changed_files=fresh.changed_files,
            )
            if not merge_commit or merge_commit == merge.pre_merge_head:
                raise RuntimeError("merge produced no new commit")
        except Exception as exc:
            merge = self._repo.update_merge_record(
                merge_record_id,
                status=MergeRecordStatus.FAILED.value,
                agent_decision=(
                    _safe_text(agent_decision, max_chars=600) if agent_decision else None
                ),
                error=_safe_text(str(exc), max_chars=600),
            )
            row = self._repo.update_session(
                coding_session_id,
                status=CodingSessionStatus.MERGE_BLOCKED.value,
                phase=CodingPhase.MERGE.value,
                last_error_category=ErrorCategory.PROCESS_ERROR.value,
                last_error_message="merge failed",
            )
            self._emit(row, "merge_failed")
            return self.merge_record_to_dict(merge)
        merge = self._repo.update_merge_record(
            merge_record_id,
            status=MergeRecordStatus.MERGED.value,
            agent_decision=_safe_text(agent_decision, max_chars=600) if agent_decision else None,
            merge_commit=merge_commit,
            merged_at=_now(),
            error=None,
        )
        row = self._repo.update_session(
            coding_session_id,
            status=CodingSessionStatus.MERGED.value,
            phase=CodingPhase.DONE.value,
        )
        self._emit(row, "merged")
        return self.merge_record_to_dict(merge)

    def create_rollback_plan(self, *, coding_session_id: str, intent_summary: str) -> dict:
        row = self._require_session(coding_session_id)
        if row.status != CodingSessionStatus.MERGED.value:
            raise ValueError("only merged sessions can be rolled back")
        if not intent_summary.strip():
            raise ValueError("rollback intent summary is required")
        merges = self._repo.list_merge_records(coding_session_id)
        merged = next(
            (
                merge
                for merge in merges
                if merge.status == MergeRecordStatus.MERGED.value and merge.merge_commit
            ),
            None,
        )
        if merged is None:
            raise ValueError("merged session has no recorded merge commit to roll back")
        decision = self._repo.add_rollback_decision(
            coding_session_id=coding_session_id,
            merge_record_id=merged.merge_record_id,
            intent_summary=_safe_text(intent_summary, max_chars=1000),
            chosen_strategy=RollbackStrategy.REVERT_COMMIT.value,
            requires_confirmation=True,
        )
        row = self._repo.update_session(
            row.coding_session_id,
            status=CodingSessionStatus.ROLLBACK_PROPOSED.value,
            phase=CodingPhase.ROLLBACK.value,
        )
        self._emit(row, "rollback_proposed")
        return self.rollback_to_dict(decision)

    def confirm_rollback(
        self,
        *,
        coding_session_id: str,
        rollback_id: str,
        confirmed_by: str = "agent",
    ) -> dict:
        """Confirm and apply a previously proposed rollback plan.

        The actual git revert/reset is executed here; this is the only
        code path that performs rollback actions.

        V1 limitation: ``reset_hard`` is not supported and always raises
        ``NotImplementedError`` regardless of ``confirmed_by``.  The
        user-confirmation check for reset_hard is a V2-ready guard that
        is currently unreachable.
        """
        row = self._require_session(coding_session_id)
        if row.status != CodingSessionStatus.ROLLBACK_PROPOSED.value:
            raise ValueError("session is not waiting for rollback confirmation")
        if confirmed_by not in {"agent", "user"}:
            raise ValueError("confirmedBy must be agent or user")
        rollback = self._repo.list_rollback_decisions(coding_session_id)
        target_rb = next((r for r in rollback if r.rollback_id == rollback_id), None)
        if target_rb is None:
            raise LookupError("rollback decision not found")
        if target_rb.status != "proposed":
            raise ValueError("rollback decision is not in proposed status")
        strategy = RollbackStrategy(target_rb.chosen_strategy)
        if strategy == RollbackStrategy.RESET_HARD:
            raise NotImplementedError("reset_hard rollback is not supported in V1")
        if strategy != RollbackStrategy.REVERT_COMMIT:
            raise NotImplementedError("only revert_commit rollback is supported in V1")
        if not target_rb.merge_record_id:
            raise ValueError("rollback decision is not bound to a merge record")
        merged = self._repo.get_merge_record(target_rb.merge_record_id)
        if (
            merged is None
            or merged.coding_session_id != coding_session_id
            or merged.status != MergeRecordStatus.MERGED.value
            or not merged.merge_commit
        ):
            raise ValueError("rollback merge record is not eligible for rollback")
        try:
            self._git.revert_commit(
                target_worktree=Path(merged.target_worktree_path),
                commit=merged.merge_commit,
                expected_parent=merged.pre_merge_head,
                expected_branch=merged.target_branch,
            )
        except Exception as exc:
            self._repo.update_rollback_decision(
                rollback_id,
                status="failed",
            )
            row = self._repo.update_session(
                coding_session_id,
                status=CodingSessionStatus.MERGE_BLOCKED.value,
                phase=CodingPhase.ROLLBACK.value,
                last_error_category=ErrorCategory.PROCESS_ERROR.value,
                last_error_message=_safe_text(str(exc), max_chars=600),
            )
            self._emit(row, "rollback_failed")
            raise ValueError("rollback git operation failed") from exc
        self._repo.update_rollback_decision(
            rollback_id,
            status="applied",
            confirmed_by=confirmed_by,
            applied_at=_now(),
        )
        self._repo.update_merge_record(
            merged.merge_record_id,
            status=MergeRecordStatus.ROLLED_BACK.value,
        )
        row = self._repo.update_session(
            coding_session_id,
            status=CodingSessionStatus.ROLLED_BACK.value,
            phase=CodingPhase.DONE.value,
        )
        self._emit(row, "rolled_back")
        return self.rollback_to_dict(
            next(
                r
                for r in self._repo.list_rollback_decisions(coding_session_id)
                if r.rollback_id == rollback_id
            )
        )

    def _start_attempt(
        self,
        row,
        phase: CodingPhase,
        *,
        approval_feedback: str = "",
        resume_instruction: str = "",
    ) -> None:
        if self._repo.get_active_attempt(row.coding_session_id) is not None:
            raise ValueError("session has an active external coding attempt")
        if not row.plan_path or not row.result_path:
            updated = self._repo.update_session(
                row.coding_session_id,
                status=CodingSessionStatus.INTERRUPTED.value,
                last_error_category=ErrorCategory.MISSING_ARTIFACT.value,
                last_error_message="external coding session artifact paths are incomplete",
            )
            if updated is None:
                raise RuntimeError("external coding session disappeared during attempt startup")
            return
        phase_attempts = [
            attempt
            for attempt in self._repo.list_attempts(row.coding_session_id)
            if attempt.phase == phase.value
        ]
        attempt_number = len(phase_attempts)
        log_path = Path(row.artifact_dir) / "logs" / f"{phase.value}-{attempt_number}.log"
        try:
            reserved = self._repo.add_attempt(
                coding_session_id=row.coding_session_id,
                phase=phase.value,
                launch_mode=row.launch_mode,
                status=AttemptStatus.RUNNING.value,
                termination_unconfirmed=True,
                launch_started=False,
                log_path=str(log_path),
            )
        except Exception as exc:
            logger.error(
                "external coding attempt reservation failed (%s)",
                type(exc).__name__,
            )
            try:
                active_attempt = self._repo.get_active_attempt(row.coding_session_id)
            except Exception:
                active_attempt = None
            if active_attempt is not None:
                raise ValueError("session has an active external coding attempt") from None
            try:
                updated = self._repo.update_session(
                    row.coding_session_id,
                    status=CodingSessionStatus.INTERRUPTED.value,
                    last_error_category=ErrorCategory.PROCESS_ERROR.value,
                    last_error_message="external coding attempt could not be reserved",
                )
            except Exception:
                updated = None
            if updated is None:
                raise RuntimeError("external coding attempt reservation failed") from None
            return
        try:
            prompt_path = write_attempt_prompt(
                Path(row.artifact_dir),
                phase=phase.value,
                attempt_number=attempt_number,
                handoff_path=Path(row.handoff_path),
                plan_path=Path(row.plan_path),
                result_path=Path(row.result_path),
                approval_feedback=approval_feedback,
                resume_instruction=resume_instruction,
                external_session_ref=row.external_session_ref,
            )
        except Exception as exc:
            logger.error(
                "external coding attempt prompt creation failed (%s)",
                type(exc).__name__,
            )
            if not self._fail_reserved_attempt(
                row,
                reserved.attempt_id,
                message="external coding attempt prompt could not be created",
            ):
                raise RuntimeError("external coding attempt prompt creation failed") from None
            return
        try:
            adapter = self._adapter_factory()
        except Exception as exc:
            logger.error(
                "external coding adapter preparation failed (%s)",
                type(exc).__name__,
            )
            if not self._fail_reserved_attempt(
                row,
                reserved.attempt_id,
                message="external coding process adapter could not be prepared",
            ):
                raise RuntimeError("external coding adapter preparation failed") from None
            return
        try:
            launch_marked = self._repo.mark_attempt_launch_started(reserved.attempt_id)
            if launch_marked is None:
                raise RuntimeError("external coding attempt disappeared before launch")
        except Exception as exc:
            logger.error(
                "external coding launch intent persistence failed (%s)",
                type(exc).__name__,
            )
            if not self._fail_reserved_attempt(
                row,
                reserved.attempt_id,
                message="external coding launch could not be prepared",
            ):
                raise RuntimeError("external coding launch preparation failed") from None
            return
        try:
            result = adapter.start(
                tool=ExternalCodingTool(row.tool),
                phase=phase,
                prompt_path=prompt_path,
                worktree_path=Path(row.worktree_path),
                artifact_dir=Path(row.artifact_dir),
                log_path=log_path,
                launch_mode=LaunchMode(row.launch_mode),
                external_session_ref=row.external_session_ref,
            )
        except Exception as exc:
            logger.error("external coding adapter start failed (%s)", type(exc).__name__)
            if not self._fail_reserved_attempt(
                row,
                reserved.attempt_id,
                message="external coding process could not be started",
            ):
                raise RuntimeError("external coding process startup failed") from None
            return
        try:
            self._apply_attempt_result(
                row,
                attempt_id=reserved.attempt_id,
                result=result,
                log_path=log_path,
                fallback_pid=reserved.pid,
                fallback_process_create_time=reserved.process_create_time,
                fallback_external_session_ref=reserved.external_session_ref,
                include_command_summary=True,
            )
        except Exception as exc:
            logger.error(
                "external coding attempt result persistence failed (%s)",
                type(exc).__name__,
            )
            termination = (
                ExternalProcessTerminationOutcome.CONFIRMED_EXITED
                if result.status != AttemptStatus.RUNNING
                else self._stop_started_process(
                    adapter,
                    pid=result.pid,
                    process_create_time=result.process_create_time,
                    termination_unconfirmed=result.termination_unconfirmed,
                    log_path=log_path,
                )
            )
            if termination.confirmed:
                if not self._fail_reserved_attempt(
                    row,
                    reserved.attempt_id,
                    message="external coding process state could not be persisted",
                ):
                    raise RuntimeError("external coding process state persistence failed") from None
                return
            if not self._record_unstopped_process(
                row,
                reserved.attempt_id,
                result=result,
                log_path=log_path,
            ):
                logger.critical(
                    "external coding process ownership persistence failed for %s pid=%s",
                    row.coding_session_id,
                    result.pid,
                )
                raise RuntimeError(
                    "external coding process ownership could not be persisted "
                    f"for session {row.coding_session_id} (pid {result.pid}); "
                    "managed shutdown is required"
                ) from None

    def _refresh_running_attempt(self, row, phase: CodingPhase):
        attempt = self._latest_attempt(row.coding_session_id, phase)
        if attempt is None or attempt.status != AttemptStatus.RUNNING.value:
            return attempt
        if not attempt.launch_started:
            if self._fail_reserved_attempt(
                row,
                attempt.attempt_id,
                message="external coding launch did not begin",
            ):
                return self._repo.get_attempt(attempt.attempt_id)
            logger.warning(
                "unlaunched external coding reservation could not be recovered for %s",
                row.coding_session_id,
            )
            return attempt
        log_path = (
            Path(attempt.log_path)
            if attempt.log_path
            else Path(row.artifact_dir) / "logs" / f"{phase.value}.log"
        )
        adapter = self._adapter_factory()
        try:
            result = adapter.poll(
                pid=attempt.pid,
                log_path=log_path,
                process_create_time=attempt.process_create_time,
                termination_unconfirmed=attempt.termination_unconfirmed,
            )
        except Exception as exc:
            logger.warning(
                "external coding process status check failed for %s (%s)",
                row.coding_session_id,
                type(exc).__name__,
            )
            message = "external coding process status could not be determined"
            try:
                projected = self._repo.update_session_and_attempt(
                    coding_session_id=row.coding_session_id,
                    attempt_id=attempt.attempt_id,
                    session_fields={
                        "last_error_category": ErrorCategory.PROCESS_ERROR.value,
                        "last_error_message": message,
                    },
                    attempt_fields={
                        "status": AttemptStatus.RUNNING.value,
                        "termination_unconfirmed": True,
                        "error_category": ErrorCategory.PROCESS_ERROR.value,
                        "error_message": message,
                        "log_tail": tail_file(
                            log_path,
                            max_chars=self._config.get_external_coding_log_tail_chars(),
                        ),
                    },
                    expected_attempt_status=AttemptStatus.RUNNING.value,
                )
                if projected is not None:
                    return projected[1]
                return self._repo.get_attempt(attempt.attempt_id) or attempt
            except Exception as persist_exc:
                logger.warning(
                    "external coding status uncertainty could not be persisted for %s (%s)",
                    row.coding_session_id,
                    type(persist_exc).__name__,
                )
                return attempt

        try:
            return self._apply_attempt_result(
                row,
                attempt_id=attempt.attempt_id,
                result=result,
                log_path=log_path,
                fallback_pid=attempt.pid,
                fallback_process_create_time=attempt.process_create_time,
                fallback_external_session_ref=attempt.external_session_ref,
                stale_conflict_is_noop=True,
            )
        except Exception as exc:
            # The repository rolls both projections back, leaving the durable
            # running attempt available for a later retry.
            logger.warning(
                "external coding poll result could not be persisted for %s (%s)",
                row.coding_session_id,
                type(exc).__name__,
            )
            return attempt

    def _apply_attempt_result(
        self,
        row,
        *,
        attempt_id: str,
        result: ProcessStartResult,
        log_path: Path,
        fallback_pid: int | None,
        fallback_process_create_time: float | None,
        fallback_external_session_ref: str | None,
        include_command_summary: bool = False,
        stale_conflict_is_noop: bool = False,
    ):
        fields = _attempt_fields_from_result(
            result,
            log_path=log_path,
            max_log_chars=self._config.get_external_coding_log_tail_chars(),
            fallback_pid=fallback_pid,
            fallback_process_create_time=fallback_process_create_time,
            fallback_external_session_ref=fallback_external_session_ref,
            include_command_summary=include_command_summary,
        )
        session_fields: dict[str, object] = {}
        if result.external_session_ref:
            session_fields["external_session_ref"] = result.external_session_ref
        if result.status in {AttemptStatus.FAILED, AttemptStatus.INTERRUPTED}:
            session_fields.update(
                {
                    "status": CodingSessionStatus.INTERRUPTED.value,
                    "last_error_category": (
                        result.error_category.value
                        if result.error_category
                        else ErrorCategory.UNKNOWN.value
                    ),
                    "last_error_message": _safe_text(
                        result.error_message or "external coding process was interrupted",
                        max_chars=600,
                    ),
                }
            )
        if session_fields:
            projected = self._repo.update_session_and_attempt(
                coding_session_id=row.coding_session_id,
                attempt_id=attempt_id,
                session_fields=session_fields,
                attempt_fields=fields,
                expected_attempt_status=AttemptStatus.RUNNING.value,
            )
            if projected is None:
                current = self._repo.get_attempt(attempt_id)
                if stale_conflict_is_noop and current is not None:
                    return current
                raise RuntimeError("external coding state changed during result persistence")
            return projected[1]
        updated = self._repo.update_attempt(
            attempt_id,
            expected_status=AttemptStatus.RUNNING.value,
            **fields,
        )
        if updated is None:
            current = self._repo.get_attempt(attempt_id)
            if stale_conflict_is_noop and current is not None:
                return current
            raise RuntimeError("external coding attempt changed during result persistence")
        return updated

    def _fail_reserved_attempt(self, row, attempt_id: str, *, message: str) -> bool:
        try:
            projected = self._repo.update_session_and_attempt(
                coding_session_id=row.coding_session_id,
                attempt_id=attempt_id,
                session_fields={
                    "status": CodingSessionStatus.INTERRUPTED.value,
                    "last_error_category": ErrorCategory.PROCESS_ERROR.value,
                    "last_error_message": message,
                },
                attempt_fields={
                    "status": AttemptStatus.FAILED.value,
                    "termination_unconfirmed": False,
                    "error_category": ErrorCategory.PROCESS_ERROR.value,
                    "error_message": message,
                },
                expected_attempt_status=AttemptStatus.RUNNING.value,
            )
        except Exception as exc:
            logger.error("failed to close reserved external coding state (%s)", type(exc).__name__)
            return False
        if projected is not None:
            return True
        current = self._repo.get_attempt(attempt_id)
        return current is not None and current.status != AttemptStatus.RUNNING.value

    @staticmethod
    def _stop_started_process(
        adapter,
        *,
        pid: int | None,
        process_create_time: float | None,
        termination_unconfirmed: bool,
        log_path: Path,
    ) -> ExternalProcessTerminationOutcome:
        if not pid:
            return ExternalProcessTerminationOutcome.UNCONFIRMED
        try:
            return adapter.stop(
                pid=pid,
                log_path=log_path,
                reason="attempt state persistence failed",
                process_create_time=process_create_time,
                termination_unconfirmed=termination_unconfirmed,
            )
        except Exception:
            return ExternalProcessTerminationOutcome.UNCONFIRMED

    def _record_unstopped_process(
        self,
        row,
        attempt_id: str,
        *,
        result: ProcessStartResult,
        log_path: Path,
    ) -> bool:
        message = "external coding process could not be stopped after state persistence failed"
        try:
            projected = self._repo.update_session_and_attempt(
                coding_session_id=row.coding_session_id,
                attempt_id=attempt_id,
                session_fields={
                    "last_error_category": ErrorCategory.PROCESS_ERROR.value,
                    "last_error_message": message,
                },
                attempt_fields={
                    "status": AttemptStatus.RUNNING.value,
                    "pid": result.pid,
                    "process_create_time": result.process_create_time,
                    "termination_unconfirmed": True,
                    "command_summary": _safe_text(result.command_summary, max_chars=500),
                    "log_path": str(log_path),
                    "error_category": ErrorCategory.PROCESS_ERROR.value,
                    "error_message": message,
                },
                expected_attempt_status=AttemptStatus.RUNNING.value,
            )
            if projected is None:
                return False
        except Exception as exc:
            logger.error(
                "unstopped external coding process could not be persisted (%s)",
                type(exc).__name__,
            )
            return False
        return True

    def _stop_running_attempts(
        self,
        row,
        *,
        reason: str,
        session_fields: dict[str, object],
    ):
        running_attempts = [
            attempt
            for attempt in self._repo.list_attempts(row.coding_session_id)
            if attempt.status == AttemptStatus.RUNNING.value
        ]
        if len(running_attempts) > 1:
            raise RuntimeError("external coding session has multiple active attempts")
        if not running_attempts:
            return None
        adapter = self._adapter_factory()
        for attempt in running_attempts:
            log_path = (
                Path(attempt.log_path)
                if attempt.log_path
                else Path(row.artifact_dir) / "logs" / f"{attempt.phase}.log"
            )
            pid = attempt.pid
            process_create_time = attempt.process_create_time
            if attempt.launch_started and not pid:
                observed = adapter.poll(
                    pid=None,
                    log_path=log_path,
                    process_create_time=attempt.process_create_time,
                    termination_unconfirmed=attempt.termination_unconfirmed,
                )
                pid = observed.pid
                process_create_time = observed.process_create_time
                if pid:
                    self._repo.update_attempt(
                        attempt.attempt_id,
                        expected_status=AttemptStatus.RUNNING.value,
                        pid=pid,
                        process_create_time=observed.process_create_time,
                        termination_unconfirmed=True,
                    )
            if attempt.launch_started:
                termination = adapter.stop(
                    pid=pid,
                    log_path=log_path,
                    reason=reason,
                    process_create_time=process_create_time,
                    termination_unconfirmed=attempt.termination_unconfirmed,
                )
                if not termination.confirmed:
                    raise ValueError("unable to confirm external coding process tree termination")
            projected = self._repo.update_session_and_attempt(
                coding_session_id=row.coding_session_id,
                attempt_id=attempt.attempt_id,
                session_fields=session_fields,
                attempt_fields={
                    "status": AttemptStatus.INTERRUPTED.value,
                    "termination_unconfirmed": False,
                    "log_tail": tail_file(
                        log_path,
                        max_chars=self._config.get_external_coding_log_tail_chars(),
                    ),
                    "error_category": ErrorCategory.UNKNOWN.value,
                    "error_message": reason,
                },
                expected_attempt_status=AttemptStatus.RUNNING.value,
            )
            if projected is not None:
                return projected[0]
            current = self._repo.get_attempt(attempt.attempt_id)
            if current is None:
                raise RuntimeError("external coding attempt disappeared during stop")
        return None

    def _refresh_plan(self, row):
        attempt = self._refresh_running_attempt(row, CodingPhase.PLAN)
        row = self._require_session(row.coding_session_id)
        dirty = self._worktree_dirty(row)
        if dirty:
            session_fields = {
                "status": CodingSessionStatus.INTERRUPTED.value,
                "phase": CodingPhase.PLAN.value,
                "last_error_category": ErrorCategory.PROTOCOL_VIOLATION.value,
                "last_error_message": f"plan phase modified files: {', '.join(dirty[:10])}",
            }
            row = self._stop_running_attempts(
                row,
                reason="plan phase protocol violation",
                session_fields=session_fields,
            ) or self._repo.update_session(row.coding_session_id, **session_fields)
            self._emit(row, "protocol_violation")
            return row
        if dirty is None:
            # git dirty check failed: cannot prove the worktree is clean, so do
            # not advance to plan_ready and do not penalize as a violation.
            logger.warning(
                "skipping plan readiness for %s: worktree dirty check unavailable",
                row.coding_session_id,
            )
            return row
        if attempt is None or attempt.status == AttemptStatus.RUNNING.value:
            return row
        if attempt.status in {
            AttemptStatus.FAILED.value,
            AttemptStatus.INTERRUPTED.value,
        }:
            return row
        plan_text = read_text_if_exists(Path(row.plan_path)) if row.plan_path else None
        if not plan_text:
            return self._interrupt_if_attempt_finished_without_artifact(
                row,
                phase=CodingPhase.PLAN,
                missing_name=PLAN_FILENAME,
            )
        validation = validate_plan_markdown(plan_text)
        if not validation.valid:
            row = self._repo.update_session(
                row.coding_session_id,
                status=CodingSessionStatus.PLAN_REJECTED.value,
                phase=CodingPhase.PLAN.value,
                last_error_category=ErrorCategory.MISSING_ARTIFACT.value,
                last_error_message=f"PLAN.md missing semantic items: {', '.join(validation.missing)}",
            )
            self._emit(row, "plan_invalid")
            return row
        row = self._repo.update_session(
            row.coding_session_id,
            status=CodingSessionStatus.PLAN_READY.value,
            phase=CodingPhase.PLAN.value,
            last_error_category=None,
            last_error_message=None,
        )
        self._emit(row, "plan_ready")
        return row

    def _refresh_result(self, row):
        attempt = self._refresh_running_attempt(row, CodingPhase.IMPLEMENT)
        row = self._require_session(row.coding_session_id)
        if attempt is None or attempt.status == AttemptStatus.RUNNING.value:
            return row
        if attempt.status in {
            AttemptStatus.FAILED.value,
            AttemptStatus.INTERRUPTED.value,
        }:
            return row
        result_text = read_text_if_exists(Path(row.result_path)) if row.result_path else None
        if not result_text:
            return self._interrupt_if_attempt_finished_without_artifact(
                row,
                phase=CodingPhase.IMPLEMENT,
                missing_name=RESULT_FILENAME,
            )
        validation = validate_result_markdown(result_text)
        if not validation.valid:
            row = self._repo.update_session(
                row.coding_session_id,
                status=CodingSessionStatus.INTERRUPTED.value,
                phase=CodingPhase.IMPLEMENT.value,
                last_error_category=ErrorCategory.MISSING_ARTIFACT.value,
                last_error_message=f"RESULT.md missing semantic items: {', '.join(validation.missing)}",
            )
            self._emit(row, "result_invalid")
            return row
        # D8: warn if RESULT.md exists but worktree has no actual file changes
        empty_diff_warning = None
        try:
            changed = self._git.changed_files_against(
                worktree=Path(row.worktree_path), base_ref="HEAD"
            )
            if not changed:
                empty_diff_warning = "RESULT.md present but worktree has no file changes; result not independently verified"
        except Exception as exc:
            logger.warning("Could not verify worktree diff for %s: %s", row.coding_session_id, exc)
            empty_diff_warning = (
                "worktree diff verification failed; result not independently verified"
            )
        row = self._repo.update_session(
            row.coding_session_id,
            status=CodingSessionStatus.COMPLETED.value,
            phase=CodingPhase.DONE.value,
            completed_at=_now(),
            last_error_category=None,
            last_error_message=empty_diff_warning,
            review_recommended=True,
            review_skipped_reason=(
                "Independent review/test has not yet been recorded; final reporting "
                "must state that the result was not independently verified."
            ),
        )
        self._emit(row, "completed")
        return row

    def _interrupt_if_attempt_finished_without_artifact(
        self,
        row,
        *,
        phase: CodingPhase,
        missing_name: str,
    ):
        attempt = self._latest_attempt(row.coding_session_id, phase)
        if attempt is None or attempt.status == AttemptStatus.RUNNING.value:
            return row
        session_fields = {
            "status": CodingSessionStatus.INTERRUPTED.value,
            "phase": phase.value,
            "last_error_category": ErrorCategory.MISSING_ARTIFACT.value,
            "last_error_message": f"{missing_name} was not produced before the process exited",
        }
        if attempt.status == AttemptStatus.SUCCEEDED.value:
            log_path = Path(attempt.log_path) if attempt.log_path else None
            projected = self._repo.update_session_and_attempt(
                coding_session_id=row.coding_session_id,
                attempt_id=attempt.attempt_id,
                session_fields=session_fields,
                attempt_fields={
                    "status": AttemptStatus.INTERRUPTED.value,
                    "log_tail": tail_file(
                        log_path,
                        max_chars=self._config.get_external_coding_log_tail_chars(),
                    ),
                    "error_category": ErrorCategory.MISSING_ARTIFACT.value,
                    "error_message": (f"{missing_name} was not produced before the process exited"),
                },
                expected_attempt_status=AttemptStatus.SUCCEEDED.value,
            )
            if projected is None:
                raise RuntimeError("external coding state disappeared during artifact validation")
            row = projected[0]
        else:
            row = self._repo.update_session(row.coding_session_id, **session_fields)
        self._emit(row, "missing_artifact")
        return row

    def _latest_attempt(self, coding_session_id: str, phase: CodingPhase):
        attempts = [
            attempt
            for attempt in self._repo.list_attempts(coding_session_id)
            if attempt.phase == phase.value
        ]
        return attempts[-1] if attempts else None

    def _probe_and_persist_quota(self) -> dict[ExternalCodingTool, QuotaSignal]:
        probe = self._quota_probe or QuotaProbe(
            command_by_tool={
                ExternalCodingTool.CLAUDE_CODE.value: self._config.get_external_coding_claude_command(),
                ExternalCodingTool.CODEX_CLI.value: self._config.get_external_coding_codex_command(),
            },
            enabled=self._config.get_external_coding_quota_probe_enabled(),
            low_threshold_percent=self._config.get_external_coding_quota_low_threshold_percent(),
            timeout_seconds=self._config.get_external_coding_quota_probe_timeout_seconds(),
        )
        signals = probe.probe_all()
        for signal in signals.values():
            self._repo.add_quota_observation(
                tool=signal.tool.value,
                state=signal.state.value,
                source=signal.source,
                confidence=signal.confidence,
                reset_at=signal.reset_at,
                safe_detail=(
                    _safe_text(signal.safe_detail, max_chars=400) if signal.safe_detail else None
                ),
            )
        return signals

    def _worktree_dirty(self, row) -> list[str] | None:
        if not row.base_commit:
            logger.warning("coding session %s has no worktree baseline", row.coding_session_id)
            return None
        try:
            return self._git.changed_files_against(
                worktree=Path(row.worktree_path), base_ref=row.base_commit
            )
        except Exception as exc:
            logger.warning("git dirty check failed for %s: %s", row.coding_session_id, exc)
            return None

    def _cleanup_failed_startup(
        self,
        resources: _StartupResources,
        *,
        cleanup_git: bool,
    ) -> list[str]:
        """Compensate startup resources and report every unverified cleanup."""
        failures: list[str] = []
        if cleanup_git:
            try:
                self._git.remove_worktree(
                    target_worktree=resources.repo_root,
                    worktree_path=resources.worktree_path,
                )
            except Exception:
                failures.append("worktree")
            try:
                self._git.delete_branch(
                    target_worktree=resources.repo_root,
                    branch_name=resources.branch_name,
                )
            except Exception:
                failures.append("branch")
        if resources.remove_worktree_root:
            try:
                resources.worktree_path.parent.rmdir()
            except OSError:
                pass
        try:
            shutil.rmtree(resources.artifact_dir)
        except FileNotFoundError:
            pass
        except OSError:
            failures.append("artifacts")
        if resources.artifact_dir.exists() and "artifacts" not in failures:
            failures.append("artifacts")
        if resources.remove_artifact_root:
            try:
                resources.artifact_dir.parent.rmdir()
            except OSError:
                pass
        return failures

    def _coerce_owner(self, owner_type: str, owner_id: str) -> OwnerType:
        if not (owner_id or "").strip():
            raise ValueError("ownerId is required for external coding sessions")
        try:
            return OwnerType(owner_type)
        except ValueError as exc:
            raise ValueError("ownerType must be task or workflow") from exc

    def _require_session(self, coding_session_id: str):
        row = self._repo.get_session(coding_session_id)
        if row is None:
            raise LookupError("external coding session not found")
        return row

    def _emit(self, row, change_type: str) -> None:
        if row is None:
            return
        emit(
            "external_coding_session_changed",
            sender=self,
            session_id=row.session_id,
            owner_type=row.owner_type,
            owner_id=row.owner_id,
            coding_session_id=row.coding_session_id,
            tool=row.tool,
            status=row.status,
            phase=row.phase,
            change_type=change_type,
            updated_at=row.updated_at,
        )

    def summary_to_dict(self, row) -> dict:
        return summary_to_dict(row, config=self._config)

    def detail_to_dict(self, row) -> dict:
        return detail_to_dict(row, repo=self._repo, config=self._config)

    def merge_record_to_dict(self, row) -> dict:
        return merge_record_to_dict(row)

    def rollback_to_dict(self, row) -> dict:
        return rollback_to_dict(row)
