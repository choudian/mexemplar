"""Repository for ``scheduled_task_runs``（033 调度中心执行账目，append-only）。

仿 ``improvement_proposal_repository``（``RunStatus`` 状态机 + 条件 UPDATE CAS）。
终态（succeeded/failed/skipped）不可逆；waiting_user ⇄ running 可逆（接管续跑）。
枚举与合法转移来自同层中立契约 ``src.data.scheduling_types``。
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from sqlalchemy.exc import IntegrityError

from src.data.models_sqlite import ScheduledTaskRun, Session
from src.data.scheduling_types import (
    RUN_ACTIVE_STATUS_VALUES,
    RUN_EVENT_DELIVERABLE_STATUSES,
    RUN_EVENT_DELIVERABLE_STATUS_VALUES,
    RUN_TERMINAL_STATUSES,
    RunStatus,
    SessionSource,
    run_status_sources_for,
)
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id

logger = logging.getLogger(__name__)

_SKIPPED_SESSION_PREFIX = "ast_skipped_"


class ScheduledTaskRunRepository(BaseRepository):
    """执行账目 append-only + CAS 状态机。"""

    @staticmethod
    def _build_active_run(
        *,
        scheduled_task_id: str,
        session_id: str,
        started_at: Any | None,
    ) -> ScheduledTaskRun:
        normalized_session_id = (session_id or "").strip()
        if not normalized_session_id or normalized_session_id.startswith(_SKIPPED_SESSION_PREFIX):
            raise ValueError("running runs require a real session_id")
        now = started_at or utc_now_naive()
        return ScheduledTaskRun(
            run_id=generate_id("schr"),
            scheduled_task_id=scheduled_task_id,
            session_id=normalized_session_id,
            started_at=now,
            finished_at=None,
            status="running",
            summary=None,
            failure_reason=None,
            terminal_event_version=0,
            created_at=now,
        )

    def create(
        self,
        *,
        scheduled_task_id: str,
        session_id: str,
        status: Literal["running"] = "running",
        started_at: Any | None = None,
    ) -> ScheduledTaskRun:
        """Create a real active run.

        ``skipped`` means no session was launched and must use ``create_skipped``;
        keeping that construction separate prevents a real session from being hidden
        later by the skipped projection.
        """

        if status != "running":
            raise ValueError("create only accepts running; use create_skipped for skipped runs")
        row = self._build_active_run(
            scheduled_task_id=scheduled_task_id,
            session_id=session_id,
            started_at=started_at,
        )
        return self._add_and_flush(row)

    def create_skipped(
        self,
        *,
        scheduled_task_id: str,
        started_at: Any | None = None,
    ) -> ScheduledTaskRun:
        """Record a trigger rejected before session creation.

        SQLite v30 keeps ``session_id`` non-null, so skipped rows receive an internal,
        run-specific placeholder.  DTO projection must continue to expose it as null.
        """

        now = started_at or utc_now_naive()
        run_id = generate_id("schr")
        row = ScheduledTaskRun(
            run_id=run_id,
            scheduled_task_id=scheduled_task_id,
            session_id=f"{_SKIPPED_SESSION_PREFIX}{run_id}",
            started_at=now,
            finished_at=now,
            status="skipped",
            summary=None,
            failure_reason=None,
            terminal_event_version=0,
            created_at=now,
        )
        return self._add_and_flush(row)

    def try_create_active(
        self,
        *,
        scheduled_task_id: str,
        session_id: str,
        started_at: Any | None = None,
    ) -> ScheduledTaskRun | None:
        """原子占用 task 的 active-run 槽；已被占用返回 ``None``。

        ``uq_runs_active_per_task`` 是并发事实来源。只有确认冲突后数据库里确有
        ``running`` / ``waiting_user`` 行才折叠成 ``None``；其他完整性错误继续抛出。
        """
        try:
            return self.create(
                scheduled_task_id=scheduled_task_id,
                session_id=session_id,
                status="running",
                started_at=started_at,
            )
        except IntegrityError:
            self.session.rollback()
            if self.has_active_run(scheduled_task_id):
                return None
            raise

    def try_create_active_with_session(
        self,
        *,
        scheduled_task_id: str,
        session: Session,
        started_at: Any | None = None,
    ) -> ScheduledTaskRun | None:
        """Atomically persist one scheduled session and its active run.

        The partial unique index remains the first-wins concurrency authority.  Both
        rows are flushed/committed as one unit, so a failed session insert can never
        leave a run whose ``session_id`` points at nothing.
        """
        if not isinstance(session, Session):
            raise TypeError("session must be a Session model")
        if SessionSource(session.source) is not SessionSource.SCHEDULED:
            raise ValueError("active scheduled runs require a scheduled session")
        if session.agent_type != "assistant" or session.status != "active":
            raise ValueError("active scheduled runs require an active assistant session")
        if session.is_scheduled not in (1, True):
            raise ValueError("active scheduled runs require is_scheduled=1")
        if session.scheduled_task_id != scheduled_task_id:
            raise ValueError("scheduled session task relationship does not match run")

        row = self._build_active_run(
            scheduled_task_id=scheduled_task_id,
            session_id=session.session_id,
            started_at=started_at,
        )
        try:
            self.session.add(session)
            self.session.add(row)
            self._commit()
            return row
        except IntegrityError:
            self.session.rollback()
            if self.has_active_run(scheduled_task_id):
                return None
            raise
        except Exception:
            self.session.rollback()
            raise

    # -- Read ------------------------------------------------------------------

    def get(self, run_id: str) -> ScheduledTaskRun | None:
        return self.session.get(ScheduledTaskRun, run_id)

    def get_fresh(self, run_id: str) -> ScheduledTaskRun | None:
        """Read the current row even when this Repository has an identity-map copy."""
        return (
            self.session.query(ScheduledTaskRun)
            .populate_existing()
            .filter(ScheduledTaskRun.run_id == run_id)
            .one_or_none()
        )

    def get_by_session(self, session_id: str) -> ScheduledTaskRun | None:
        """会话反查最近一条 run（接管/完成判定用）。"""
        return (
            self.session.query(ScheduledTaskRun)
            .filter(ScheduledTaskRun.session_id == session_id)
            .order_by(ScheduledTaskRun.started_at.desc())
            .first()
        )

    def list_by_task(
        self, scheduled_task_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[ScheduledTaskRun], int]:
        query = self.session.query(ScheduledTaskRun).filter(
            ScheduledTaskRun.scheduled_task_id == scheduled_task_id
        )
        total = query.count()
        items = query.order_by(ScheduledTaskRun.started_at.desc()).offset(offset).limit(limit).all()
        return items, total

    def has_active_run(self, scheduled_task_id: str) -> bool:
        """该任务是否存在未静默的 run（running / waiting_user）—— reentry 判定用。"""
        return (
            self.session.query(ScheduledTaskRun)
            .filter(
                ScheduledTaskRun.scheduled_task_id == scheduled_task_id,
                ScheduledTaskRun.status.in_(RUN_ACTIVE_STATUS_VALUES),
            )
            .count()
            > 0
        )

    def list_pending_terminal_events(self, *, limit: int = 100) -> list[ScheduledTaskRun]:
        """Return durable terminal notifications that still need projection."""
        return (
            self.session.query(ScheduledTaskRun)
            .populate_existing()
            .filter(
                ScheduledTaskRun.status.in_(RUN_EVENT_DELIVERABLE_STATUS_VALUES),
                ScheduledTaskRun.terminal_event_delivered_at.is_(None),
            )
            .order_by(ScheduledTaskRun.finished_at.asc(), ScheduledTaskRun.started_at.asc())
            .limit(max(1, min(int(limit), 500)))
            .all()
        )

    # -- CAS 状态机 ------------------------------------------------------------

    def cas_transition(
        self,
        run_id: str,
        *,
        from_status: str | frozenset[str],
        to_status: str,
        summary: str | None = None,
        failure_reason: str | None = None,
    ) -> ScheduledTaskRun | None:
        """状态转移 CAS。终态写 ``finished_at``；接管回 running 清 ``finished_at``。

        ``from_status`` 为空集合或不匹配时 rowcount=0 返回 None（非法转移拒绝）。
        """
        from_statuses = {from_status} if isinstance(from_status, str) else set(from_status)
        try:
            target_status = RunStatus(to_status)
        except ValueError:
            return None
        allowed_sources = {str(value) for value in run_status_sources_for(target_status)}
        from_statuses.intersection_update(allowed_sources)
        if not from_statuses:
            return None
        # 清除当前 ack；每次进入可投递状态还要递增事件代次。旧代次即使在 emit
        # 返回后才 ack，也无法确认掉并发产生的新终态。
        values: dict[str, Any] = {
            "status": to_status,
            "terminal_event_delivered_at": None,
        }
        if target_status in RUN_EVENT_DELIVERABLE_STATUSES:
            values["terminal_event_version"] = ScheduledTaskRun.terminal_event_version + 1
        if target_status in RUN_TERMINAL_STATUSES:
            values["finished_at"] = utc_now_naive()
        elif target_status is RunStatus.RUNNING:
            values["finished_at"] = None
        if summary is not None:
            values["summary"] = summary
        if failure_reason is not None:
            values["failure_reason"] = failure_reason
        updated = (
            self.session.query(ScheduledTaskRun)
            .filter(
                ScheduledTaskRun.run_id == run_id,
                ScheduledTaskRun.status.in_(from_statuses),
            )
            .update(values, synchronize_session=False)
        )
        self._commit()
        if updated == 0:
            return None
        return self._refetch(run_id)

    def mark_terminal_event_delivered(self, run_id: str, *, event_version: int) -> bool:
        """CAS-ack exactly one pending terminal projection generation."""
        updated = (
            self.session.query(ScheduledTaskRun)
            .filter(
                ScheduledTaskRun.run_id == run_id,
                ScheduledTaskRun.status.in_(RUN_EVENT_DELIVERABLE_STATUS_VALUES),
                ScheduledTaskRun.terminal_event_version == event_version,
                ScheduledTaskRun.terminal_event_delivered_at.is_(None),
            )
            .update(
                {"terminal_event_delivered_at": utc_now_naive()},
                synchronize_session=False,
            )
        )
        self._commit()
        return updated == 1

    def update_summary(self, run_id: str, *, summary: str | None) -> ScheduledTaskRun | None:
        """单独更新汇报摘要（不改状态，advisory）。"""
        row = self.get(run_id)
        if row is None:
            return None
        row.summary = summary
        return self._update_and_flush(row)

    def _refetch(self, run_id: str) -> ScheduledTaskRun | None:
        return self.get_fresh(run_id)
