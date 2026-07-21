"""Repository for ``scheduled_tasks``（033 调度中心定时任务主表）。

仿 ``UserTodoRepository``（CRUD + 分页 list）+ ``improvement_proposal_repository``
（条件 UPDATE + rowcount CAS）。状态枚举与合法转移来自 data 中立契约
``src.data.scheduling_types``，Repository 自己是最终状态机门卫。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.data.models_sqlite import ScheduledTask
from src.data.scheduling_types import ScheduledTaskStatus, task_status_sources_for
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id

logger = logging.getLogger(__name__)


class ScheduledTaskRepository(BaseRepository):
    """定时任务 CRUD + 分页 list + 软删 + CAS（status / next_fire_at / is_deleted）。"""

    # -- Create ----------------------------------------------------------------

    def create(
        self,
        *,
        source_type: str,
        source_ref: str,
        title: str,
        schedule_kind: str,
        schedule_payload: dict[str, Any] | str,
        status: str = "active",
        unattended_auto_approve: bool = False,
        executor_hint: str | None = None,
        next_fire_at: Any = None,
        instruction: str | None = None,
    ) -> ScheduledTask:
        now = utc_now_naive()
        payload_str = (
            schedule_payload
            if isinstance(schedule_payload, str)
            else json.dumps(schedule_payload, ensure_ascii=False)
        )
        instruction_text = (instruction or "").strip()
        if not instruction_text:
            instruction_text = source_ref if source_type == "direct" else title
        row = ScheduledTask(
            scheduled_task_id=generate_id("sch"),
            source_type=source_type,
            source_ref=source_ref,
            title=title,
            instruction=instruction_text,
            schedule_kind=schedule_kind,
            schedule_payload=payload_str,
            status=status,
            unattended_auto_approve=1 if unattended_auto_approve else 0,
            executor_hint=executor_hint,
            next_fire_at=next_fire_at,
            last_fired_at=None,
            is_deleted=0,
            created_at=now,
            updated_at=now,
        )
        return self._add_and_flush(row)

    # -- Read ------------------------------------------------------------------

    def get(self, scheduled_task_id: str) -> ScheduledTask | None:
        return self.session.get(ScheduledTask, scheduled_task_id)

    def list_tasks(
        self,
        *,
        status_filter: str | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ScheduledTask], int]:
        query = self.session.query(ScheduledTask)
        if not include_deleted:
            query = query.filter(ScheduledTask.is_deleted == 0)
        if status_filter and status_filter != "all":
            query = query.filter(ScheduledTask.status == status_filter)
        total = query.count()
        items = (
            query.order_by(ScheduledTask.created_at.desc(), ScheduledTask.scheduled_task_id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return items, total

    def list_due(self, now: Any, *, limit: int = 100) -> list[ScheduledTask]:
        """活跃且 ``next_fire_at <= now`` 的任务（调度扫描主路径）。"""
        return (
            self.session.query(ScheduledTask)
            .filter(
                ScheduledTask.status == "active",
                ScheduledTask.is_deleted == 0,
                ScheduledTask.next_fire_at.isnot(None),
                ScheduledTask.next_fire_at <= now,
            )
            .order_by(ScheduledTask.next_fire_at.asc())
            .limit(limit)
            .all()
        )

    def soonest_next_fire(self) -> Any | None:
        """最近一个活跃任务的 next_fire_at（worker 动态 wait timeout 用）。"""
        row = (
            self.session.query(ScheduledTask.next_fire_at)
            .filter(
                ScheduledTask.status == "active",
                ScheduledTask.is_deleted == 0,
                ScheduledTask.next_fire_at.isnot(None),
            )
            .order_by(ScheduledTask.next_fire_at.asc())
            .first()
        )
        return row[0] if row else None

    def list_todo_sources(self) -> list[ScheduledTask]:
        """todo 来源、未软删且未终态的任务（悬空反查）。"""
        return (
            self.session.query(ScheduledTask)
            .filter(
                ScheduledTask.source_type == "todo",
                ScheduledTask.is_deleted == 0,
                ScheduledTask.status.in_(("active", "paused")),
            )
            .all()
        )

    def list_unattended_auto_approve_task_ids(self) -> list[str]:
        """所有 ``unattended_auto_approve=1`` 的任务 id（UnattendedConfirmationManager 全量加载）。"""
        rows = (
            self.session.query(ScheduledTask.scheduled_task_id)
            .filter(
                ScheduledTask.unattended_auto_approve == 1,
                ScheduledTask.is_deleted == 0,
            )
            .all()
        )
        return [row[0] for row in rows]

    # -- Update（CAS / 受限字段）------------------------------------------------

    def update_display(
        self, scheduled_task_id: str, *, title: str | None = None
    ) -> ScheduledTask | None:
        """仅展示字段更新（白名单：title）。调度核心字段不可经此改。"""
        values: dict[str, Any] = {"updated_at": utc_now_naive()}
        if title is not None:
            values["title"] = title
        updated = (
            self.session.query(ScheduledTask)
            .filter(
                ScheduledTask.scheduled_task_id == scheduled_task_id,
                ScheduledTask.is_deleted == 0,
            )
            .update(values, synchronize_session=False)
        )
        self._commit()
        if updated == 0:
            return None
        return self._refetch(scheduled_task_id)

    def cas_status(
        self,
        scheduled_task_id: str,
        *,
        from_status: str | frozenset[str],
        to_status: str,
    ) -> ScheduledTask | None:
        """状态转移 CAS（active⇄paused / →completed / →expired）。非法转移返回 None。"""
        from_statuses = {from_status} if isinstance(from_status, str) else set(from_status)
        try:
            target_status = ScheduledTaskStatus(to_status)
        except ValueError:
            return None
        allowed_sources = {str(value) for value in task_status_sources_for(target_status)}
        from_statuses.intersection_update(allowed_sources)
        if not from_statuses:
            return None
        updated = (
            self.session.query(ScheduledTask)
            .filter(
                ScheduledTask.scheduled_task_id == scheduled_task_id,
                ScheduledTask.status.in_(from_statuses),
                ScheduledTask.is_deleted == 0,
            )
            .update(
                {"status": to_status, "updated_at": utc_now_naive()},
                synchronize_session=False,
            )
        )
        self._commit()
        if updated == 0:
            return None
        return self._refetch(scheduled_task_id)

    def cas_resume_with_next_fire(
        self,
        scheduled_task_id: str,
        *,
        next_fire_at: Any,
    ) -> ScheduledTask | None:
        """暂停过点的 recurring 任务原子滚到未来首点并恢复 active。"""
        updated = (
            self.session.query(ScheduledTask)
            .filter(
                ScheduledTask.scheduled_task_id == scheduled_task_id,
                ScheduledTask.status == "paused",
                ScheduledTask.is_deleted == 0,
            )
            .update(
                {
                    "status": "active",
                    "next_fire_at": next_fire_at,
                    "updated_at": utc_now_naive(),
                },
                synchronize_session=False,
            )
        )
        self._commit()
        if updated == 0:
            return None
        return self._refetch(scheduled_task_id)

    def cas_next_fire(
        self,
        scheduled_task_id: str,
        *,
        next_fire_at: Any,
        last_fired_at: Any | None = None,
    ) -> ScheduledTask | None:
        """滚动 ``next_fire_at``（可选同时写 ``last_fired_at``）。CAS 仅校验未软删。"""
        values: dict[str, Any] = {
            "next_fire_at": next_fire_at,
            "updated_at": utc_now_naive(),
        }
        if last_fired_at is not None:
            values["last_fired_at"] = last_fired_at
        updated = (
            self.session.query(ScheduledTask)
            .filter(
                ScheduledTask.scheduled_task_id == scheduled_task_id,
                ScheduledTask.is_deleted == 0,
            )
            .update(values, synchronize_session=False)
        )
        self._commit()
        if updated == 0:
            return None
        return self._refetch(scheduled_task_id)

    def set_unattended_auto_approve(
        self, scheduled_task_id: str, enabled: bool
    ) -> ScheduledTask | None:
        """仅对未软删任务条件更新 per-task 免确认开关。"""
        updated = (
            self.session.query(ScheduledTask)
            .filter(
                ScheduledTask.scheduled_task_id == scheduled_task_id,
                ScheduledTask.is_deleted == 0,
            )
            .update(
                {
                    "unattended_auto_approve": 1 if enabled else 0,
                    "updated_at": utc_now_naive(),
                },
                synchronize_session=False,
            )
        )
        self._commit()
        if updated == 0:
            return None
        return self._refetch(scheduled_task_id)

    def cas_bind_session(
        self,
        scheduled_task_id: str,
        session_id: str,
        *,
        expected_session_id: str | None,
    ) -> ScheduledTask | None:
        """把 current session 从期望值原子切到 ``session_id``。"""
        normalized_session_id = (session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("session_id must not be empty")
        query = self.session.query(ScheduledTask).filter(
            ScheduledTask.scheduled_task_id == scheduled_task_id,
            ScheduledTask.is_deleted == 0,
        )
        if expected_session_id is None:
            query = query.filter(ScheduledTask.session_id.is_(None))
        else:
            query = query.filter(ScheduledTask.session_id == str(expected_session_id).strip())
        updated = query.update(
            {
                "session_id": normalized_session_id,
                "updated_at": utc_now_naive(),
            },
            synchronize_session=False,
        )
        self._commit()
        if updated == 0:
            return None
        return self._refetch(scheduled_task_id)

    def cas_clear_session(
        self,
        scheduled_task_id: str,
        *,
        expected_session_id: str,
    ) -> ScheduledTask | None:
        """仅当仍绑定给定 session 时清空 current session。"""
        normalized_session_id = (expected_session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("expected_session_id must not be empty")
        updated = (
            self.session.query(ScheduledTask)
            .filter(
                ScheduledTask.scheduled_task_id == scheduled_task_id,
                ScheduledTask.session_id == normalized_session_id,
                ScheduledTask.is_deleted == 0,
            )
            .update(
                {
                    "session_id": None,
                    "updated_at": utc_now_naive(),
                },
                synchronize_session=False,
            )
        )
        self._commit()
        if updated == 0:
            return None
        return self._refetch(scheduled_task_id)

    def soft_delete(self, scheduled_task_id: str) -> bool:
        """软删（is_deleted=1，历史 runs 保留）。"""
        updated = (
            self.session.query(ScheduledTask)
            .filter(
                ScheduledTask.scheduled_task_id == scheduled_task_id,
                ScheduledTask.is_deleted == 0,
            )
            .update(
                {"is_deleted": 1, "updated_at": utc_now_naive()},
                synchronize_session=False,
            )
        )
        self._commit()
        return updated > 0

    # -- helpers ---------------------------------------------------------------

    def _refetch(self, scheduled_task_id: str) -> ScheduledTask | None:
        return (
            self.session.query(ScheduledTask)
            .populate_existing()
            .filter(ScheduledTask.scheduled_task_id == scheduled_task_id)
            .one_or_none()
        )
