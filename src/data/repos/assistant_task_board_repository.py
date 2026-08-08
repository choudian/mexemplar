"""Repository for open-board task claims."""

from __future__ import annotations

from datetime import datetime

from src.data.models_sqlite import AssistantTaskClaim
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id


class AssistantTaskClaimRepository(BaseRepository):
    def _insert_claim(
        self,
        *,
        task_id: str,
        claimer_type: str,
        claimer_id: str,
        task_version: int,
        status: str,
        lease_expires_at: datetime | None = None,
        reject_reason: str | None = None,
        claim_id: str | None = None,
    ) -> AssistantTaskClaim:
        self.ensure_immediate_transaction()
        row = AssistantTaskClaim(
            claim_id=claim_id or generate_id("clm"),
            task_id=task_id,
            claimer_type=claimer_type,
            claimer_id=claimer_id,
            status=status,
            lease_expires_at=lease_expires_at,
            reject_reason=reject_reason,
            task_version=task_version,
        )
        return self._add_and_flush(row)

    def create_claim(
        self,
        *,
        task_id: str,
        claimer_type: str,
        claimer_id: str,
        task_version: int,
        lease_expires_at: datetime,
        claim_id: str | None = None,
    ) -> AssistantTaskClaim:
        return self._insert_claim(
            task_id=task_id,
            claimer_type=claimer_type,
            claimer_id=claimer_id,
            task_version=task_version,
            status="claimed",
            lease_expires_at=lease_expires_at,
            claim_id=claim_id,
        )

    def record_rejection(
        self,
        *,
        task_id: str,
        claimer_type: str,
        claimer_id: str,
        task_version: int,
        reject_reason: str,
        claim_id: str | None = None,
    ) -> AssistantTaskClaim:
        return self._insert_claim(
            task_id=task_id,
            claimer_type=claimer_type,
            claimer_id=claimer_id,
            task_version=task_version,
            status="rejected",
            reject_reason=reject_reason,
            claim_id=claim_id,
        )

    def get_claim(self, claim_id: str) -> AssistantTaskClaim | None:
        return self.session.get(AssistantTaskClaim, claim_id)

    def update_status(
        self,
        claim_id: str,
        status: str,
        *,
        reject_reason: str | None = None,
    ) -> AssistantTaskClaim | None:
        self.ensure_immediate_transaction()
        row = self.session.get(AssistantTaskClaim, claim_id)
        if row is None:
            return None
        row.status = status
        if reject_reason is not None:
            row.reject_reason = reject_reason
        row.updated_at = utc_now_naive()
        return self._update_and_flush(row)

    def list_for_task(self, task_id: str) -> list[AssistantTaskClaim]:
        return (
            self.session.query(AssistantTaskClaim)
            .filter(AssistantTaskClaim.task_id == task_id)
            .order_by(AssistantTaskClaim.created_at)
            .all()
        )

    def list_active_claims_for_tasks(self, task_ids: list[str]) -> dict[str, AssistantTaskClaim]:
        """task_id → 该 task 最新一条 ``claimed`` 认领（按 created_at 升序遍历，末位覆盖）。

        供看板列表批量解析认领态，避免逐 task 调 ``list_for_task`` 的 N+1。无认领的 task
        不出现在返回 dict 中。
        """
        if not task_ids:
            return {}
        rows = (
            self.session.query(AssistantTaskClaim)
            .filter(
                AssistantTaskClaim.task_id.in_(task_ids),
                AssistantTaskClaim.status == "claimed",
            )
            .order_by(AssistantTaskClaim.created_at, AssistantTaskClaim.claim_id)
            .all()
        )
        return {row.task_id: row for row in rows}

    def get_active_claim_for_task(self, task_id: str) -> AssistantTaskClaim | None:
        return (
            self.session.query(AssistantTaskClaim)
            .filter(
                AssistantTaskClaim.task_id == task_id,
                AssistantTaskClaim.status == "claimed",
            )
            .order_by(AssistantTaskClaim.created_at.desc(), AssistantTaskClaim.claim_id.desc())
            .first()
        )

    def has_rejection(
        self,
        *,
        task_id: str,
        claimer_type: str,
        claimer_id: str,
    ) -> bool:
        return (
            self.session.query(AssistantTaskClaim)
            .filter(
                AssistantTaskClaim.task_id == task_id,
                AssistantTaskClaim.claimer_type == claimer_type,
                AssistantTaskClaim.claimer_id == claimer_id,
                AssistantTaskClaim.status == "rejected",
            )
            .first()
            is not None
        )

    def has_active_claim(
        self,
        *,
        claimer_type: str,
        claimer_id: str,
    ) -> bool:
        # FR-003 容量=1：认领者一次只持有一个进行中的认领。
        return (
            self.session.query(AssistantTaskClaim)
            .filter(
                AssistantTaskClaim.claimer_type == claimer_type,
                AssistantTaskClaim.claimer_id == claimer_id,
                AssistantTaskClaim.status == "claimed",
            )
            .first()
            is not None
        )

    def scan_expired_claims(self, now: datetime) -> list[AssistantTaskClaim]:
        return (
            self.session.query(AssistantTaskClaim)
            .filter(
                AssistantTaskClaim.status == "claimed",
                AssistantTaskClaim.lease_expires_at.is_not(None),
                AssistantTaskClaim.lease_expires_at <= now,
            )
            .all()
        )

    def scan_all_active_claims(self) -> list[AssistantTaskClaim]:
        """断电恢复：所有 ``claimed`` 认领，不看 lease 过期。

        与 ``scan_expired_claims`` 的区别：那个只扫 lease 过期的（运行期，由
        ``TaskCollaborationBackgroundWorker`` 周期调用）；这个扫**全部** claimed——sidecar
        重启后认领它的执行体已死，无论 lease 到没到期都是假的。不清的后果：claimed 行撑着
        ``uq_assistant_task_claims_active_claimer`` partial unique index，挡住重新认领。
        """
        return (
            self.session.query(AssistantTaskClaim)
            .filter(AssistantTaskClaim.status == "claimed")
            .order_by(AssistantTaskClaim.created_at)
            .all()
        )
