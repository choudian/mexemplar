"""Repository for ``scheduled_task_runs``（033/034 调度执行账目，append-only）。

仿 ``improvement_proposal_repository``（``RunStatus`` 状态机 + 条件 UPDATE CAS）。
终态（succeeded/failed/skipped）不可逆；waiting_user ⇄ running 可逆（接管续跑）。
枚举与合法转移来自同层中立契约 ``src.data.scheduling_types``。
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from sqlalchemy.exc import IntegrityError

from src.data.models_sqlite import ScheduledTask, ScheduledTaskRun, Session
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
    def _validate_scheduled_session(
        session: Session,
        *,
        scheduled_task_id: str,
    ) -> None:
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

    @staticmethod
    def _build_active_run(
        *,
        scheduled_task_id: str,
        session_id: str,
        started_at: Any | None,
        baseline_message_sequence: int = 0,
        trigger_message_sequence: int | None = None,
    ) -> ScheduledTaskRun:
        normalized_session_id = (session_id or "").strip()
        if not normalized_session_id or normalized_session_id.startswith(_SKIPPED_SESSION_PREFIX):
            raise ValueError("running runs require a real session_id")
        baseline = int(baseline_message_sequence)
        if baseline < 0:
            raise ValueError("baseline_message_sequence must be non-negative")
        trigger = int(trigger_message_sequence) if trigger_message_sequence is not None else None
        if trigger is not None and trigger != baseline + 1:
            raise ValueError("trigger_message_sequence must equal baseline_message_sequence + 1")
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
            baseline_message_sequence=baseline,
            trigger_message_sequence=trigger,
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
        baseline_message_sequence: int = 0,
        trigger_message_sequence: int | None = None,
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
            baseline_message_sequence=baseline_message_sequence,
            trigger_message_sequence=trigger_message_sequence,
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
            baseline_message_sequence=0,
            trigger_message_sequence=None,
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
        baseline_message_sequence: int = 0,
        trigger_message_sequence: int | None = None,
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
                baseline_message_sequence=baseline_message_sequence,
                trigger_message_sequence=trigger_message_sequence,
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
        baseline_message_sequence: int = 0,
        trigger_message_sequence: int | None = None,
    ) -> ScheduledTaskRun | None:
        """Atomically persist one scheduled session and its active run.

        The partial unique index remains the first-wins concurrency authority.  Both
        rows are flushed/committed as one unit, so a failed session insert can never
        leave a run whose ``session_id`` points at nothing.
        """
        self._validate_scheduled_session(
            session,
            scheduled_task_id=scheduled_task_id,
        )

        row = self._build_active_run(
            scheduled_task_id=scheduled_task_id,
            session_id=session.session_id,
            started_at=started_at,
            baseline_message_sequence=baseline_message_sequence,
            trigger_message_sequence=trigger_message_sequence,
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

    def try_create_active_with_new_bound_session(
        self,
        *,
        scheduled_task_id: str,
        session: Session,
        expected_session_id: str | None,
        baseline_message_sequence: int,
        trigger_message_sequence: int,
        started_at: Any | None = None,
    ) -> ScheduledTaskRun | None:
        """原子提交 current-session 绑定、全新 session 与 active run。"""
        self._validate_scheduled_session(
            session,
            scheduled_task_id=scheduled_task_id,
        )
        row = self._build_active_run(
            scheduled_task_id=scheduled_task_id,
            session_id=session.session_id,
            started_at=started_at,
            baseline_message_sequence=baseline_message_sequence,
            trigger_message_sequence=trigger_message_sequence,
        )
        try:
            self.session.add(session)
            self.session.add(row)
            task_query = self.session.query(ScheduledTask).filter(
                ScheduledTask.scheduled_task_id == scheduled_task_id,
                ScheduledTask.is_deleted == 0,
            )
            if expected_session_id is None:
                task_query = task_query.filter(ScheduledTask.session_id.is_(None))
            else:
                task_query = task_query.filter(
                    ScheduledTask.session_id == str(expected_session_id).strip()
                )
            bound = task_query.update(
                {
                    "session_id": session.session_id,
                    "updated_at": utc_now_naive(),
                },
                synchronize_session=False,
            )
            if bound != 1:
                self.session.rollback()
                return None
            self._commit()
            self.session.refresh(row)
            return row
        except IntegrityError:
            self.session.rollback()
            if self.has_active_run(scheduled_task_id):
                return None
            raise
        except Exception:
            self.session.rollback()
            raise

    def try_create_active_for_bound_session(
        self,
        *,
        scheduled_task_id: str,
        session_id: str,
        baseline_message_sequence: int,
        trigger_message_sequence: int,
        started_at: Any | None = None,
    ) -> ScheduledTaskRun | None:
        """为 task 当前绑定的既有 session 原子创建下一条 active run。"""
        normalized_session_id = (session_id or "").strip()
        task = (
            self.session.query(ScheduledTask)
            .filter(
                ScheduledTask.scheduled_task_id == scheduled_task_id,
                ScheduledTask.session_id == normalized_session_id,
                ScheduledTask.is_deleted == 0,
            )
            .one_or_none()
        )
        if task is None:
            return None
        session = self.session.get(Session, normalized_session_id)
        if session is None:
            raise ValueError("bound scheduled session does not exist")
        # AgentLoop 会在一轮结束后把长期 assistant session 标成 completed /
        # suspended / failed；下一条 user 消息本来就会将这些状态复活。run 与
        # session 必须在同一事务里先恢复 active，避免“第一轮成功、第二轮永远拒绝”。
        if session.status in {"archived", "completed", "suspended", "failed"}:
            session.status = "active"
            session.updated_at = utc_now_naive()
        self._validate_scheduled_session(
            session,
            scheduled_task_id=scheduled_task_id,
        )
        row = self._build_active_run(
            scheduled_task_id=scheduled_task_id,
            session_id=normalized_session_id,
            started_at=started_at,
            baseline_message_sequence=baseline_message_sequence,
            trigger_message_sequence=trigger_message_sequence,
        )
        try:
            self.session.add(row)
            self._commit()
            self.session.refresh(row)
            return row
        except IntegrityError:
            self.session.rollback()
            if self.has_active_run(scheduled_task_id) or self.has_active_session(
                normalized_session_id
            ):
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
        """会话反查最近一条历史 run（legacy/终态投影兼容；不得用于终态 mutation）。"""
        return (
            self.session.query(ScheduledTaskRun)
            .filter(ScheduledTaskRun.session_id == session_id)
            .order_by(ScheduledTaskRun.started_at.desc())
            .first()
        )

    def get_active_by_session(self, session_id: str) -> ScheduledTaskRun | None:
        """按 session 读取唯一 active run；不使用“最近一条”启发式。"""
        return (
            self.session.query(ScheduledTaskRun)
            .filter(
                ScheduledTaskRun.session_id == session_id,
                ScheduledTaskRun.status.in_(RUN_ACTIVE_STATUS_VALUES),
            )
            .one_or_none()
        )

    def get_for_message_sequence(
        self,
        session_id: str,
        message_sequence: int,
    ) -> ScheduledTaskRun | None:
        """把图/消息序号映射到其所属 run 窗口。"""
        sequence = int(message_sequence)
        return (
            self.session.query(ScheduledTaskRun)
            .filter(
                ScheduledTaskRun.session_id == session_id,
                ScheduledTaskRun.trigger_message_sequence.isnot(None),
                ScheduledTaskRun.baseline_message_sequence < sequence,
                ScheduledTaskRun.trigger_message_sequence <= sequence,
            )
            .order_by(
                ScheduledTaskRun.baseline_message_sequence.desc(),
                ScheduledTaskRun.started_at.desc(),
            )
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

    def has_active_session(self, session_id: str) -> bool:
        """该 session 是否已有 active scheduled run。"""
        return (
            self.session.query(ScheduledTaskRun)
            .filter(
                ScheduledTaskRun.session_id == session_id,
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
        clear_trigger_message_sequence: bool = False,
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
        if clear_trigger_message_sequence:
            # Launcher/runtime 可在 user trigger 尚未持久化前失败。释放这个预留序号，
            # 否则 session-trigger 唯一索引会让同一 current session 永久无法重试。
            values["trigger_message_sequence"] = None
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
