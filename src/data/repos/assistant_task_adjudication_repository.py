"""Repository for parent-side task adjudication rows."""

from __future__ import annotations

from src.data.models_sqlite import AssistantTaskAdjudication
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id


class AssistantTaskAdjudicationRepository(BaseRepository):
    def create_pending(
        self,
        *,
        task_id: str,
        graph_id: str,
        parent_session_id: str,
        delivered_status: str,
        safe_summary: str,
        raw_result_ref: str | None = None,
        adjudication_id: str | None = None,
    ) -> AssistantTaskAdjudication:
        self.ensure_immediate_transaction()
        row = AssistantTaskAdjudication(
            adjudication_id=adjudication_id or generate_id("adj"),
            task_id=task_id,
            graph_id=graph_id,
            parent_session_id=parent_session_id,
            status="pending",
            delivered_status=delivered_status,
            safe_summary=safe_summary,
            raw_result_ref=raw_result_ref,
        )
        return self._add_and_flush(row)

    def get_by_id(self, adjudication_id: str) -> AssistantTaskAdjudication | None:
        return self.session.get(AssistantTaskAdjudication, adjudication_id)

    def get_pending_for_task(self, task_id: str) -> AssistantTaskAdjudication | None:
        return (
            self.session.query(AssistantTaskAdjudication)
            .filter(
                AssistantTaskAdjudication.task_id == task_id,
                AssistantTaskAdjudication.status == "pending",
            )
            .first()
        )

    def has_decided_for_task(self, task_id: str, *, decision: str | None = None) -> bool:
        """Return whether a task already has a decided adjudication.

        Used as the dispatch-layer confirmation gate for ``requires_confirmation`` nodes:
        the scheduler/tooling may flip the task back to pending_dispatch, but the
        dispatcher must independently verify an accepted decision exists before
        creating an attempt.
        """
        query = self.session.query(AssistantTaskAdjudication.adjudication_id).filter(
            AssistantTaskAdjudication.task_id == task_id,
            AssistantTaskAdjudication.status == "decided",
        )
        if decision is not None:
            query = query.filter(AssistantTaskAdjudication.decision == decision)
        return query.limit(1).first() is not None

    def list_pending_for_graph(self, graph_id: str) -> list[AssistantTaskAdjudication]:
        """该图所有 pending 裁定，供快照批量解析，避免逐 task 的 N+1。"""
        return (
            self.session.query(AssistantTaskAdjudication)
            .filter(
                AssistantTaskAdjudication.graph_id == graph_id,
                AssistantTaskAdjudication.status == "pending",
            )
            .all()
        )

    def decide(
        self,
        adjudication_id: str,
        *,
        decision: str,
        decided_by: str,
        instruction: str | None = None,
    ) -> AssistantTaskAdjudication | None:
        # 原子条件 UPDATE：仅 pending 才裁定，守卫进 SQL，不做 PK 读后盲写。并发双裁定
        # （用户点击 + 自动重入等）下，ORM 读-改-写会让两笔都通过 Python 的 status=="pending"
        # 守卫并按 PK 盲写，两笔都落库（已由 test_concurrent_adjudication_decide_cannot_both_win
        # 复现 A=True B=True 的丢更新）。条件 UPDATE 把守卫推进 SQL，第二笔匹配 0 行 -> None
        # （视作已裁定），与 attempt fence / task assign_if_version 的 CAS 约定一致。
        self.ensure_immediate_transaction()
        updated = (
            self.session.query(AssistantTaskAdjudication)
            .filter(
                AssistantTaskAdjudication.adjudication_id == adjudication_id,
                AssistantTaskAdjudication.status == "pending",
            )
            .update(
                {
                    "status": "decided",
                    "decision": decision,
                    "decided_by": decided_by,
                    "instruction": instruction,
                    "decided_at": utc_now_naive(),
                },
                synchronize_session=False,
            )
        )
        self._commit()
        if updated == 0:
            # 不存在 / 已裁定：未写入，返回 None 让调用方按"已裁定"处理。
            return None
        return self._refetch(adjudication_id)

    def _refetch(self, adjudication_id: str) -> AssistantTaskAdjudication | None:
        """条件 UPDATE 后用 ``populate_existing`` 重取受影响行的权威态。

        ``synchronize_session=False`` 的 bulk UPDATE 不同步 identity map；只刷新本行，
        不像 ``expire_all`` 那样殃及共享 session 里已加载的 task 对象（同 attempt 仓库约定）。
        """
        return (
            self.session.query(AssistantTaskAdjudication)
            .populate_existing()
            .filter(AssistantTaskAdjudication.adjudication_id == adjudication_id)
            .one_or_none()
        )
