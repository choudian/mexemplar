"""Repository for external coding sessions (030)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import update as sqlalchemy_update

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


_TERMINAL_ATTEMPT_STATUSES = frozenset({"succeeded", "interrupted", "failed"})
_SESSION_MUTABLE_FIELDS = frozenset(
    {
        "status",
        "phase",
        "selected_reason",
        "quota_state",
        "external_session_ref",
        "target_branch",
        "target_worktree_path",
        "plan_approved_at",
        "plan_approved_by",
        "last_error_category",
        "last_error_message",
        "resume_count",
        "review_recommended",
        "review_skipped_reason",
        "completed_at",
    }
)
_ATTEMPT_MUTABLE_FIELDS = frozenset(
    {
        "status",
        "command_summary",
        "external_session_ref",
        "pid",
        "process_create_time",
        "termination_unconfirmed",
        "exit_code",
        "finished_at",
        "log_path",
        "log_tail",
        "error_category",
        "error_message",
    }
)


def _validate_attempt_state(
    *,
    status: str,
    pid: int | None,
    process_create_time: float | None,
    termination_unconfirmed: bool,
    launch_started: bool,
) -> None:
    if status == "running" and not termination_unconfirmed:
        raise ValueError("running external coding attempts must retain process ownership")
    if status in _TERMINAL_ATTEMPT_STATUSES and termination_unconfirmed:
        raise ValueError("terminal external coding attempts cannot retain process ownership")
    if not launch_started and (pid is not None or process_create_time is not None):
        raise ValueError("unlaunched external coding attempts cannot have process identity")
    if process_create_time is not None and pid is None:
        raise ValueError("external coding process creation time requires a PID")


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
        plan_path: str,
        result_path: str,
        target_branch: str | None = None,
        target_worktree_path: str | None = None,
        selected_reason: str | None = None,
        quota_state: str | None = None,
        coding_session_id: str | None = None,
    ) -> ExternalCodingSession:
        if (
            not isinstance(plan_path, str)
            or not isinstance(result_path, str)
            or not plan_path.strip()
            or not result_path.strip()
        ):
            raise ValueError("plan_path and result_path are required")
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
            plan_path=plan_path,
            result_path=result_path,
            created_at=now,
            updated_at=now,
        )
        return self._add_and_flush(row)

    def get_session(self, coding_session_id: str) -> ExternalCodingSession | None:
        return (
            self.session.query(ExternalCodingSession)
            .populate_existing()
            .filter(ExternalCodingSession.coding_session_id == coding_session_id)
            .one_or_none()
        )

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
        self._apply_session_fields(row, fields)
        try:
            return self._update_and_flush(row)
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise

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
        process_create_time: float | None = None,
        termination_unconfirmed: bool = False,
        launch_started: bool = False,
        exit_code: int | None = None,
        log_path: str | None = None,
        log_tail: str | None = None,
        error_category: str | None = None,
        error_message: str | None = None,
        attempt_id: str | None = None,
    ) -> ExternalCodingAttempt:
        _validate_attempt_state(
            status=status,
            pid=pid,
            process_create_time=process_create_time,
            termination_unconfirmed=termination_unconfirmed,
            launch_started=launch_started,
        )
        row = ExternalCodingAttempt(
            attempt_id=attempt_id or generate_id("eca"),
            coding_session_id=coding_session_id,
            phase=phase,
            launch_mode=launch_mode,
            command_summary=command_summary,
            external_session_ref=external_session_ref,
            status=status,
            pid=pid,
            process_create_time=process_create_time,
            termination_unconfirmed=termination_unconfirmed,
            launch_started=launch_started,
            exit_code=exit_code,
            started_at=_now(),
            finished_at=_now() if status in _TERMINAL_ATTEMPT_STATUSES else None,
            log_path=log_path,
            log_tail=log_tail,
            error_category=error_category,
            error_message=error_message,
        )
        try:
            return self._add_and_flush(row)
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise

    def update_attempt(
        self,
        attempt_id: str,
        *,
        expected_status: str | None = None,
        **fields: Any,
    ) -> ExternalCodingAttempt | None:
        if expected_status is not None:
            current = self.get_attempt(attempt_id)
            if current is None:
                return None
            if current.status != expected_status:
                self._abort_conflict()
                return None
            try:
                values = self._attempt_update_values(
                    expected_status,
                    fields,
                    current_attempt=current,
                )
                result = self.session.execute(
                    sqlalchemy_update(ExternalCodingAttempt)
                    .where(
                        ExternalCodingAttempt.attempt_id == attempt_id,
                        ExternalCodingAttempt.status == expected_status,
                    )
                    .values(**values)
                )
                if result.rowcount != 1:
                    self._abort_conflict()
                    return None
                self._commit()
                return self.get_attempt(attempt_id)
            except Exception:
                if self.session.in_transaction():
                    self.session.rollback()
                raise
        row = self.get_attempt(attempt_id)
        if row is None:
            return None
        try:
            self._apply_attempt_fields(row, fields)
            return self._update_and_flush(row)
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise

    def mark_attempt_launch_started(self, attempt_id: str) -> ExternalCodingAttempt | None:
        """CAS the reservation across the spawn boundary exactly once."""
        try:
            result = self.session.execute(
                sqlalchemy_update(ExternalCodingAttempt)
                .where(
                    ExternalCodingAttempt.attempt_id == attempt_id,
                    ExternalCodingAttempt.status == "running",
                    ExternalCodingAttempt.launch_started.is_(False),
                )
                .values(launch_started=True)
            )
            if result.rowcount != 1:
                self._abort_conflict()
                return None
            self._commit()
            return self.get_attempt(attempt_id)
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise

    def get_attempt(self, attempt_id: str) -> ExternalCodingAttempt | None:
        return (
            self.session.query(ExternalCodingAttempt)
            .populate_existing()
            .filter(ExternalCodingAttempt.attempt_id == attempt_id)
            .one_or_none()
        )

    def update_session_and_attempt(
        self,
        *,
        coding_session_id: str,
        attempt_id: str,
        session_fields: dict[str, Any],
        attempt_fields: dict[str, Any],
        expected_attempt_status: str | None = None,
    ) -> tuple[ExternalCodingSession, ExternalCodingAttempt] | None:
        """Project one process observation atomically into both durable rows."""
        session_row = self.get_session(coding_session_id)
        if session_row is None:
            return None
        if expected_attempt_status is not None:
            current_attempt = self.get_attempt(attempt_id)
            if current_attempt is None:
                return None
            if current_attempt.coding_session_id != coding_session_id:
                raise ValueError("external coding attempt does not belong to the session")
            if current_attempt.status != expected_attempt_status:
                self._abort_conflict()
                return None
            try:
                attempt_values = self._attempt_update_values(
                    expected_attempt_status,
                    attempt_fields,
                    current_attempt=current_attempt,
                )
                result = self.session.execute(
                    sqlalchemy_update(ExternalCodingAttempt)
                    .where(
                        ExternalCodingAttempt.attempt_id == attempt_id,
                        ExternalCodingAttempt.coding_session_id == coding_session_id,
                        ExternalCodingAttempt.status == expected_attempt_status,
                    )
                    .values(**attempt_values)
                )
                if result.rowcount != 1:
                    self._abort_conflict()
                    return None
                self._apply_session_fields(session_row, session_fields)
                self._commit()
                self.session.refresh(session_row)
                attempt_row = self.get_attempt(attempt_id)
                if attempt_row is None:
                    raise RuntimeError("external coding attempt disappeared after projection")
                return session_row, attempt_row
            except Exception:
                if self.session.in_transaction():
                    self.session.rollback()
                raise
        attempt_row = self.get_attempt(attempt_id)
        if attempt_row is None:
            return None
        if attempt_row.coding_session_id != coding_session_id:
            raise ValueError("external coding attempt does not belong to the session")
        try:
            self._apply_session_fields(session_row, session_fields)
            self._apply_attempt_fields(attempt_row, attempt_fields)
            self._commit()
            self.session.refresh(session_row)
            self.session.refresh(attempt_row)
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise
        return session_row, attempt_row

    def get_active_attempt(self, coding_session_id: str) -> ExternalCodingAttempt | None:
        return (
            self.session.query(ExternalCodingAttempt)
            .filter(
                ExternalCodingAttempt.coding_session_id == coding_session_id,
                ExternalCodingAttempt.status == "running",
            )
            .populate_existing()
            .order_by(ExternalCodingAttempt.started_at.desc())
            .first()
        )

    def scan_running_attempts(self) -> list[ExternalCodingAttempt]:
        """断电恢复：跨 session 列出所有 ``status='running'`` 的 attempt。

        ``get_active_attempt`` 是按单 session 查；本方法扫全表，供 sidecar 重启时的启动
        栅栏使用。DB 约束 ``ck_external_coding_attempts_ownership_status`` 强制 running 行必然
        带 ``termination_unconfirmed=1``，所以这里无需再合取该条件——扫 running 即扫"假活"。
        终态值（succeeded/interrupted/failed）断电后是真的，不扫。
        """
        return (
            self.session.query(ExternalCodingAttempt)
            .filter(ExternalCodingAttempt.status == "running")
            .order_by(ExternalCodingAttempt.started_at)
            .all()
        )

    def list_attempts(self, coding_session_id: str) -> list[ExternalCodingAttempt]:
        return (
            self.session.query(ExternalCodingAttempt)
            .filter(ExternalCodingAttempt.coding_session_id == coding_session_id)
            .populate_existing()
            .order_by(ExternalCodingAttempt.started_at)
            .all()
        )

    @staticmethod
    def _apply_session_fields(row: ExternalCodingSession, fields: dict[str, Any]) -> None:
        if {"plan_path", "result_path"}.intersection(fields):
            raise ValueError("external coding artifact paths are immutable")
        unknown = set(fields).difference(_SESSION_MUTABLE_FIELDS)
        if unknown:
            raise ValueError(f"unsupported external coding session fields: {sorted(unknown)}")
        for key, value in fields.items():
            if key in _SESSION_MUTABLE_FIELDS:
                setattr(row, key, value)
        row.updated_at = _now()

    @staticmethod
    def _apply_attempt_fields(row: ExternalCodingAttempt, fields: dict[str, Any]) -> None:
        values = ExternalCodingSessionRepository._attempt_update_values(
            row.status,
            fields,
            current_attempt=row,
        )
        for key, value in values.items():
            setattr(row, key, value)

    @staticmethod
    def _attempt_update_values(
        current_status: str,
        fields: dict[str, Any],
        *,
        current_attempt: ExternalCodingAttempt | None = None,
    ) -> dict[str, Any]:
        unknown = set(fields).difference(_ATTEMPT_MUTABLE_FIELDS)
        if unknown:
            raise ValueError(f"unsupported external coding attempt fields: {sorted(unknown)}")
        resulting_status = str(fields.get("status", current_status))
        if current_status in _TERMINAL_ATTEMPT_STATUSES and resulting_status == "running":
            raise ValueError("terminal external coding attempts cannot return to running")
        if resulting_status == "running" and fields.get("termination_unconfirmed") is False:
            raise ValueError("running external coding attempts must retain process ownership")
        if (
            resulting_status in _TERMINAL_ATTEMPT_STATUSES
            and fields.get("termination_unconfirmed") is True
        ):
            raise ValueError("terminal external coding attempts cannot retain process ownership")
        values = {key: value for key, value in fields.items() if key in _ATTEMPT_MUTABLE_FIELDS}
        if resulting_status in _TERMINAL_ATTEMPT_STATUSES:
            values["termination_unconfirmed"] = False
            if values.get("finished_at") is None:
                values["finished_at"] = _now()
        elif resulting_status == "running":
            values["finished_at"] = None
        if current_attempt is not None:
            _validate_attempt_state(
                status=resulting_status,
                pid=(values["pid"] if "pid" in values else current_attempt.pid),
                process_create_time=(
                    values["process_create_time"]
                    if "process_create_time" in values
                    else current_attempt.process_create_time
                ),
                termination_unconfirmed=bool(
                    values["termination_unconfirmed"]
                    if "termination_unconfirmed" in values
                    else current_attempt.termination_unconfirmed
                ),
                launch_started=bool(
                    values["launch_started"]
                    if "launch_started" in values
                    else current_attempt.launch_started
                ),
            )
        return values

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
