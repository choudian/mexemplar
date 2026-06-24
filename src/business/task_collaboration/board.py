"""Business service for open-board assignment and claim leases."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from src.business.task_collaboration.models import ClaimStatus, TaskStatus, safe_preview, safe_public_preview
from src.business.task_collaboration.service import (
    emit_board_changed,
    increment_task_collaboration_counter,
)
from src.business.task_collaboration.unit_of_work import AtomicTaskService
from src.data.repos import AssistantTaskClaimRepository, AssistantTaskRepository
from src.data.unified_config import get_unified_config
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)
_FALLBACK_EXECUTOR_TYPE = "ephemeral_subagent"
_FALLBACK_EXECUTOR_ID = "ephemeral_subagent"


class TaskBoardService(AtomicTaskService):
    def __init__(
        self,
        task_repo: AssistantTaskRepository | None = None,
        claim_repo: AssistantTaskClaimRepository | None = None,
    ) -> None:
        self._init_repos(
            tasks=(AssistantTaskRepository, task_repo),
            claims=(AssistantTaskClaimRepository, claim_repo),
        )

    def list_board(self, session_id: str) -> list[dict]:
        tasks = self._tasks.list_board_tasks(session_id)
        active_claims = self._claims.list_active_claims_for_tasks(
            [task.task_id for task in tasks]
        )
        items: list[dict] = []
        for task in tasks:
            active_claim = active_claims.get(task.task_id)
            items.append(
                {
                    "taskId": task.task_id,
                    "graphId": task.graph_id,
                    "title": safe_public_preview(task.title, key="title", max_chars=80),
                    "status": task.status,
                    "claimStatus": "claimed" if active_claim else "open",
                    "claimId": active_claim.claim_id if active_claim else None,
                    "assignee": (
                        {"type": task.assignee_type, "id": task.assignee_id}
                        if task.assignee_type and task.assignee_id
                        else None
                    ),
                    "updatedAt": task.updated_at,
                }
            )
        return items

    def claim_task(
        self,
        *,
        task_id: str,
        claimer_type: str,
        claimer_id: str,
        lease_seconds: int,
        session_id: str | None = None,
    ):
        task = self._tasks.get_task(task_id)
        if task is None or task.status != TaskStatus.PENDING_DISPATCH:
            increment_task_collaboration_counter("claim_conflict")
            return None
        if session_id is not None and task.session_id != session_id:
            increment_task_collaboration_counter("claim_conflict")
            return None
        if self._claims.has_rejection(
            task_id=task_id,
            claimer_type=claimer_type,
            claimer_id=claimer_id,
        ):
            increment_task_collaboration_counter("claim_conflict")
            return None
        # FR-003 容量=1：认领者已持有进行中的认领时不得再认领第二个任务；该任务保持开放，
        # 可被其他认领者拿走，本人释放后才能接下一个。
        if self._claims.has_active_claim(
            claimer_type=claimer_type,
            claimer_id=claimer_id,
        ):
            increment_task_collaboration_counter("claim_conflict")
            return None
        # 占位（assign_if_version）与写 claim 必须同一事务：否则占位成功但 claim 写入失败时，
        # task 已被标 assigned 却没有对应 claim，看板任务永久卡死。
        try:
            with self._atomic():
                assigned = self._tasks.assign_if_version(
                    task_id,
                    assignee_type=claimer_type,
                    assignee_id=claimer_id,
                    expected_task_version=task.task_version,
                )
                if assigned is None:
                    increment_task_collaboration_counter("claim_conflict")
                    return None
                claim = self._claims.create_claim(
                    task_id=task_id,
                    claimer_type=claimer_type,
                    claimer_id=claimer_id,
                    task_version=task.task_version,
                    lease_expires_at=utc_now_naive() + timedelta(seconds=max(1, lease_seconds)),
                )
        except IntegrityError:
            logger.info(
                "[task board] claim conflict task=%s claimer=%s/%s",
                task_id,
                claimer_type,
                claimer_id,
            )
            increment_task_collaboration_counter("claim_conflict")
            return None
        emit_board_changed(self, assigned, change_type="claimed", claim_status="claimed")
        return claim

    def _claim_for_fallback_candidate(
        self,
        *,
        task,
        current: datetime,
        lease_seconds: int,
        cutoff: datetime,
    ) -> bool:
        try:
            with self._atomic():
                task = self._tasks.get_task(task.task_id)
                if (
                    task is None
                    or task.status != TaskStatus.PENDING_DISPATCH
                    or task.assignee_type is not None
                    or task.assignee_id is not None
                    or task.updated_at > cutoff
                    or self._claims.has_active_claim(
                        claimer_type=_FALLBACK_EXECUTOR_TYPE,
                        claimer_id=_FALLBACK_EXECUTOR_ID,
                    )
                ):
                    increment_task_collaboration_counter("claim_conflict")
                    return False
                assigned = self._tasks.assign_if_version(
                    task.task_id,
                    assignee_type=_FALLBACK_EXECUTOR_TYPE,
                    assignee_id=_FALLBACK_EXECUTOR_ID,
                    expected_task_version=task.task_version,
                )
                if assigned is None:
                    increment_task_collaboration_counter("claim_conflict")
                    return False
                self._claims.create_claim(
                    task_id=task.task_id,
                    claimer_type=_FALLBACK_EXECUTOR_TYPE,
                    claimer_id=_FALLBACK_EXECUTOR_ID,
                    task_version=assigned.task_version,
                    lease_expires_at=current + timedelta(seconds=lease_seconds),
                )
        except IntegrityError:
            increment_task_collaboration_counter("claim_conflict")
            return False
        return True

    def start_fallback_executors(
        self,
        now: datetime | None = None,
        *,
        session_id: str | None = None,
    ) -> list[str]:
        """Durably claim stale open-board tasks for temporary fallback executors."""
        config = get_unified_config()
        current = now or utc_now_naive()
        cutoff = current - timedelta(seconds=config.get_assistant_tasks_board_fallback_seconds())
        limit = config.get_assistant_tasks_board_capacity()
        lease_seconds = config.get_assistant_tasks_attempt_lease_seconds()
        claimed_task_ids: list[str] = []
        for candidate in self._tasks.list_open_board_tasks_for_fallback(
            cutoff,
            limit=limit,
            session_id=session_id,
        ):
            try:
                if self._claim_for_fallback_candidate(
                    task=candidate,
                    current=current,
                    lease_seconds=lease_seconds,
                    cutoff=cutoff,
                ):
                    claimed_task_ids.append(candidate.task_id)
            except Exception:
                logger.exception(
                    "[task board] fallback claim failed for task %s",
                    getattr(candidate, "task_id", "<unknown>"),
                )
                continue
        for task_id in claimed_task_ids:
            task = self._tasks.get_task(task_id)
            if task is None:
                continue
            emit_board_changed(self, task, change_type="claimed", claim_status="claimed")
            _record_fallback_recruitment_signal(task)
        return claimed_task_ids

    def complete_active_claim(self, task_id: str) -> bool:
        task = self._tasks.get_task(task_id)
        claim = self._claims.get_active_claim_for_task(task_id)
        if task is None or claim is None:
            return False
        with self._atomic():
            updated = self._claims.update_status(claim.claim_id, ClaimStatus.COMPLETED)
        if updated is None:
            return False
        emit_board_changed(self, task, change_type="completed", claim_status="completed")
        return True

    def release_claim(self, claim_id: str, *, session_id: str | None = None):
        claim = self._claims.get_claim(claim_id)
        if claim is None:
            return None
        if session_id is not None:
            task = self._tasks.get_task(claim.task_id)
            if task is None or task.session_id != session_id:
                return None
        with self._atomic():
            released = self._claims.update_status(claim_id, ClaimStatus.RELEASED)
            task = self._tasks.unassign_if_assignee(
                claim.task_id,
                assignee_type=claim.claimer_type,
                assignee_id=claim.claimer_id,
            )
        if task is not None:
            emit_board_changed(self, task, change_type="released", claim_status="open")
        return released

    def reject_task(
        self,
        *,
        task_id: str,
        claimer_type: str,
        claimer_id: str,
        reason: str,
    ):
        task = self._tasks.get_task(task_id)
        if task is None:
            raise LookupError("task not found")
        with self._atomic():
            claim = self._claims.record_rejection(
                task_id=task_id,
                claimer_type=claimer_type,
                claimer_id=claimer_id,
                task_version=task.task_version,
                reject_reason=safe_preview(reason, max_chars=200),
            )
        emit_board_changed(self, task, change_type="rejected", claim_status="open")
        return claim

    def expire_claims(self, now: datetime) -> int:
        expired = 0
        for claim in self._claims.scan_expired_claims(now):
            with self._atomic():
                if self._claims.update_status(claim.claim_id, ClaimStatus.EXPIRED) is None:
                    continue
                task = self._tasks.unassign_if_assignee(
                    claim.task_id,
                    assignee_type=claim.claimer_type,
                    assignee_id=claim.claimer_id,
                )
            if task is not None:
                expired += 1
                emit_board_changed(self, task, change_type="expired", claim_status="open")
        return expired


def _record_fallback_recruitment_signal(task) -> None:
    try:
        threshold = get_unified_config().get_assistant_tasks_recruitment_min_fallback_count()
        from src.data.repos.brain_repository import BrainRepository

        summary = safe_preview(task.description or task.title, max_chars=220)
        with BrainRepository() as repo:
            repo.record_recruitment_signal(
                task_pattern=task.title,
                session_id=task.session_id,
                delegation_summary=f"fallback_threshold={threshold}: {summary}",
            )
    except Exception as exc:
        logger.warning("Failed to record fallback recruitment signal: %s", exc)
