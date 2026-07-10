"""Repository for external coding sessions (030)."""

from __future__ import annotations

import json
from typing import Any

from src.data.models_sqlite import (
    ExternalCodingAttempt,
    ExternalCodingMergeRecord,
    ExternalCodingQuotaObservation,
    ExternalCodingRollbackDecision,
    ExternalCodingSession,
)
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id


def _now() -> str:
    return utc_now_naive().isoformat()


def _json_list(value: list[str] | None) -> str:
    return json.dumps(value or [], ensure_ascii=False)


class ExternalCodingSessionRepository(BaseRepository):
    """Persistence boundary for external coding session state and audit rows."""

    def create_session(
        self,
        *,
        session_id: str | None,
        owner_type: str,
        owner_id: str,
        parent_session_id: str | None,
        tool: str,
        launch_mode: str,
        status: str,
        phase: str,
        worktree_path: str,
        branch_name: str,
        base_commit: str | None,
        artifact_dir: str,
        handoff_path: str,
        target_branch: str | None = None,
        target_worktree_path: str | None = None,
        selected_reason: str | None = None,
        quota_state: str | None = None,
        coding_session_id: str | None = None,
    ) -> ExternalCodingSession:
        now = _now()
        row = ExternalCodingSession(
            coding_session_id=coding_session_id or generate_id("ecs"),
            session_id=session_id,
            owner_type=owner_type,
            owner_id=owner_id,
            parent_session_id=parent_session_id,
            tool=tool,
            launch_mode=launch_mode,
            status=status,
            phase=phase,
            selected_reason=selected_reason,
            quota_state=quota_state,
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_commit=base_commit,
            target_branch=target_branch,
            target_worktree_path=target_worktree_path,
            artifact_dir=artifact_dir,
            handoff_path=handoff_path,
            created_at=now,
            updated_at=now,
        )
        return self._add_and_flush(row)

    def get_session(self, coding_session_id: str) -> ExternalCodingSession | None:
        return self.session.get(ExternalCodingSession, coding_session_id)

    def list_sessions(
        self,
        *,
        session_id: str | None = None,
        owner_type: str | None = None,
        owner_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[ExternalCodingSession]:
        query = self.session.query(ExternalCodingSession)
        if session_id:
            query = query.filter(ExternalCodingSession.session_id == session_id)
        if owner_type:
            query = query.filter(ExternalCodingSession.owner_type == owner_type)
        if owner_id:
            query = query.filter(ExternalCodingSession.owner_id == owner_id)
        if status:
            query = query.filter(ExternalCodingSession.status == status)
        return query.order_by(ExternalCodingSession.updated_at.desc()).limit(limit).all()

    def list_for_owner(self, owner_type: str, owner_id: str) -> list[ExternalCodingSession]:
        return (
            self.session.query(ExternalCodingSession)
            .filter(
                ExternalCodingSession.owner_type == owner_type,
                ExternalCodingSession.owner_id == owner_id,
            )
            .order_by(ExternalCodingSession.updated_at.desc())
            .all()
        )

    def list_for_owners(
        self,
        owner_type: str,
        owner_ids: list[str],
    ) -> list[ExternalCodingSession]:
        unique_ids = sorted({owner_id for owner_id in owner_ids if owner_id})
        if not unique_ids:
            return []
        return (
            self.session.query(ExternalCodingSession)
            .filter(
                ExternalCodingSession.owner_type == owner_type,
                ExternalCodingSession.owner_id.in_(unique_ids),
            )
            .order_by(ExternalCodingSession.updated_at.desc())
            .all()
        )

    def update_session(self, coding_session_id: str, **fields: Any) -> ExternalCodingSession | None:
        row = self.get_session(coding_session_id)
        if row is None:
            return None
        allowed = {
            "status",
            "phase",
            "selected_reason",
            "quota_state",
            "external_session_ref",
            "target_branch",
            "target_worktree_path",
            "plan_path",
            "result_path",
            "plan_approved_at",
            "plan_approved_by",
            "last_error_category",
            "last_error_message",
            "resume_count",
            "review_recommended",
            "review_skipped_reason",
            "completed_at",
        }
        for key, value in fields.items():
            if key in allowed:
                setattr(row, key, value)
        row.updated_at = _now()
        return self._update_and_flush(row)

    def add_attempt(
        self,
        *,
        coding_session_id: str,
        phase: str,
        launch_mode: str,
        status: str,
        command_summary: str | None = None,
        external_session_ref: str | None = None,
        pid: int | None = None,
        exit_code: int | None = None,
        log_path: str | None = None,
        log_tail: str | None = None,
        error_category: str | None = None,
        error_message: str | None = None,
        attempt_id: str | None = None,
    ) -> ExternalCodingAttempt:
        row = ExternalCodingAttempt(
            attempt_id=attempt_id or generate_id("eca"),
            coding_session_id=coding_session_id,
            phase=phase,
            launch_mode=launch_mode,
            command_summary=command_summary,
            external_session_ref=external_session_ref,
            status=status,
            pid=pid,
            exit_code=exit_code,
            started_at=_now(),
            finished_at=_now() if status in {"succeeded", "interrupted", "failed"} else None,
            log_path=log_path,
            log_tail=log_tail,
            error_category=error_category,
            error_message=error_message,
        )
        return self._add_and_flush(row)

    def update_attempt(self, attempt_id: str, **fields: Any) -> ExternalCodingAttempt | None:
        row = self.session.get(ExternalCodingAttempt, attempt_id)
        if row is None:
            return None
        for key in {
            "status",
            "command_summary",
            "external_session_ref",
            "pid",
            "exit_code",
            "finished_at",
            "log_path",
            "log_tail",
            "error_category",
            "error_message",
        }:
            if key in fields:
                setattr(row, key, fields[key])
        if row.status in {"succeeded", "interrupted", "failed"} and row.finished_at is None:
            row.finished_at = _now()
        return self._update_and_flush(row)

    def list_attempts(self, coding_session_id: str) -> list[ExternalCodingAttempt]:
        return (
            self.session.query(ExternalCodingAttempt)
            .filter(ExternalCodingAttempt.coding_session_id == coding_session_id)
            .order_by(ExternalCodingAttempt.started_at)
            .all()
        )

    def add_quota_observation(
        self,
        *,
        tool: str,
        state: str,
        source: str,
        confidence: float,
        reset_at: str | None = None,
        safe_detail: str | None = None,
    ) -> ExternalCodingQuotaObservation:
        row = ExternalCodingQuotaObservation(
            observation_id=generate_id("ecq"),
            tool=tool,
            state=state,
            source=source,
            confidence=float(confidence),
            reset_at=reset_at,
            checked_at=_now(),
            safe_detail=safe_detail,
        )
        return self._add_and_flush(row)

    def latest_quota_by_tool(self) -> dict[str, ExternalCodingQuotaObservation]:
        rows = (
            self.session.query(ExternalCodingQuotaObservation)
            .order_by(ExternalCodingQuotaObservation.checked_at.desc())
            .all()
        )
        result: dict[str, ExternalCodingQuotaObservation] = {}
        for row in rows:
            result.setdefault(row.tool, row)
        return result

    def add_merge_record(
        self,
        *,
        coding_session_id: str,
        target_branch: str,
        target_worktree_path: str,
        pre_merge_head: str,
        coding_branch_head: str,
        dirty_files: list[str],
        changed_files: list[str],
        overlap_files: list[str],
        conflict_risk: str,
        status: str = "analysis_ready",
        agent_decision: str | None = None,
        error: str | None = None,
    ) -> ExternalCodingMergeRecord:
        row = ExternalCodingMergeRecord(
            merge_record_id=generate_id("ecm"),
            coding_session_id=coding_session_id,
            target_branch=target_branch,
            target_worktree_path=target_worktree_path,
            pre_merge_head=pre_merge_head,
            coding_branch_head=coding_branch_head,
            dirty_files_json=_json_list(dirty_files),
            changed_files_json=_json_list(changed_files),
            overlap_files_json=_json_list(overlap_files),
            conflict_risk=conflict_risk,
            agent_decision=agent_decision,
            status=status,
            error=error,
            created_at=_now(),
        )
        return self._add_and_flush(row)

    def get_merge_record(self, merge_record_id: str) -> ExternalCodingMergeRecord | None:
        return self.session.get(ExternalCodingMergeRecord, merge_record_id)

    def update_merge_record(
        self, merge_record_id: str, **fields: Any
    ) -> ExternalCodingMergeRecord | None:
        row = self.get_merge_record(merge_record_id)
        if row is None:
            return None
        for key in {"agent_decision", "status", "merge_commit", "error", "merged_at"}:
            if key in fields:
                setattr(row, key, fields[key])
        return self._update_and_flush(row)

    def list_merge_records(self, coding_session_id: str) -> list[ExternalCodingMergeRecord]:
        return (
            self.session.query(ExternalCodingMergeRecord)
            .filter(ExternalCodingMergeRecord.coding_session_id == coding_session_id)
            .order_by(ExternalCodingMergeRecord.created_at.desc())
            .all()
        )

    def add_rollback_decision(
        self,
        *,
        coding_session_id: str,
        intent_summary: str,
        chosen_strategy: str,
        requires_confirmation: bool,
        merge_record_id: str | None = None,
        status: str = "proposed",
        confirmed_by: str | None = None,
    ) -> ExternalCodingRollbackDecision:
        row = ExternalCodingRollbackDecision(
            rollback_id=generate_id("ecr"),
            coding_session_id=coding_session_id,
            merge_record_id=merge_record_id,
            intent_summary=intent_summary,
            chosen_strategy=chosen_strategy,
            requires_confirmation=requires_confirmation,
            confirmed_by=confirmed_by,
            status=status,
            created_at=_now(),
        )
        return self._add_and_flush(row)

    def list_rollback_decisions(
        self, coding_session_id: str
    ) -> list[ExternalCodingRollbackDecision]:
        return (
            self.session.query(ExternalCodingRollbackDecision)
            .filter(ExternalCodingRollbackDecision.coding_session_id == coding_session_id)
            .order_by(ExternalCodingRollbackDecision.created_at.desc())
            .all()
        )

    def update_rollback_decision(
        self,
        rollback_id: str,
        *,
        status: str | None = None,
        confirmed_by: str | None = None,
        applied_at: str | None = None,
    ) -> ExternalCodingRollbackDecision | None:
        row = self.session.get(ExternalCodingRollbackDecision, rollback_id)
        if row is None:
            return None
        if status is not None:
            row.status = status
        if confirmed_by is not None:
            row.confirmed_by = confirmed_by
        if applied_at is not None:
            row.applied_at = applied_at
        return self._update_and_flush(row)
