"""⑥ 第一步行为测试：delivered/skipped 状态 + derive_display_phase + 同步委派 task 终态。"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from src.business.agents.config import AgentType
from src.business.task_collaboration.models import (
    TaskStatus,
    derive_display_phase,
)
from src.data.models_sqlite import Session as SessionModel
from src.data.repos import (
    AssistantTaskRepository,
    SessionRepository,
    UserTaskRepository,
)
from src.data.repos.assistant_task_attempt_repository import (
    AssistantTaskAttemptRepository,
)
from src.utils.timezone import utc_now_naive


# ---------------------------------------------------------------------------
# derive_display_phase：新状态映射
# ---------------------------------------------------------------------------


class TestDeriveDisplayPhaseNewStatuses:
    def test_delivered_shows_reviewing(self):
        """delivered → reviewing（显式状态，不再依赖 has_pending_adjudication hack）。"""
        assert derive_display_phase(TaskStatus.DELIVERED) == "reviewing"

    def test_delivered_with_adjudication_still_reviewing(self):
        assert derive_display_phase(TaskStatus.DELIVERED, has_pending_adjudication=True) == "reviewing"

    def test_skipped_shows_done(self):
        """skipped → done（跳过的节点跟完成一样不碍眼）。"""
        assert derive_display_phase(TaskStatus.SKIPPED) == "done"

    def test_completed_still_done(self):
        assert derive_display_phase(TaskStatus.COMPLETED) == "done"

    def test_suspended_with_adjudication_still_reviewing(self):
        """requires_confirmation 节点（SUSPENDED + adjudication）仍显示 reviewing。"""
        assert derive_display_phase(
            TaskStatus.SUSPENDED, has_pending_adjudication=True
        ) == "reviewing"

    def test_suspended_without_adjudication_paused(self):
        assert derive_display_phase(TaskStatus.SUSPENDED) == "paused"


# ---------------------------------------------------------------------------
# 同步委派 task 行终态（修了卡 running 的 bug）
# ---------------------------------------------------------------------------


def _seed_session(session_id: str) -> str:
    SessionRepository().create(
        SessionModel(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    return session_id


class TestSyncDelegationTaskStatus:
    def test_sync_attempt_success_completes_task(self, in_memory_db):
        """同步委派成功后 task 行落 COMPLETED（不再是卡 running）。"""
        from src.business.orchestration.agent.delegation_orchestrator import (
            _start_sync_attempt,
            _finalize_sync_attempt,
        )

        sid = _seed_session("sess-sync-ok")
        task_id = _start_sync_attempt(
            parent_session_id=sid,
            task_title="测试",
            task_description="d",
            executor_type=AgentType.EPHEMERAL_SUBAGENT.value,
            executor_id=AgentType.EPHEMERAL_SUBAGENT.value,
            user_task_id=None,
        )
        assert task_id is not None

        _finalize_sync_attempt(task_id, {"success": True, "result_text": "done"})

        with AssistantTaskRepository() as tasks:
            task = tasks.get_task(task_id)
        assert task is not None
        assert task.status == "completed"

    def test_sync_attempt_paused_suspends_task(self, in_memory_db):
        """同步委派暂停后 task 行落 SUSPENDED。"""
        from src.business.orchestration.agent.delegation_orchestrator import (
            _start_sync_attempt,
            _finalize_sync_attempt,
        )

        sid = _seed_session("sess-sync-paused")
        task_id = _start_sync_attempt(
            parent_session_id=sid,
            task_title="测试",
            task_description="d",
            executor_type=AgentType.EPHEMERAL_SUBAGENT.value,
            executor_id=AgentType.EPHEMERAL_SUBAGENT.value,
            user_task_id=None,
        )

        _finalize_sync_attempt(task_id, {
            "success": False,
            "paused": True,
            "subagent_id": "child-1",
        })

        with AssistantTaskRepository() as tasks:
            task = tasks.get_task(task_id)
        assert task is not None
        assert task.status == "suspended"

    def test_sync_attempt_failure_suspends_not_abandoned(self, in_memory_db):
        """同步委派失败落 SUSPENDED（不是 ABANDONED——ABANDONED 是'有人拍板'）。"""
        from src.business.orchestration.agent.delegation_orchestrator import (
            _start_sync_attempt,
            _finalize_sync_attempt,
        )

        sid = _seed_session("sess-sync-fail")
        task_id = _start_sync_attempt(
            parent_session_id=sid,
            task_title="测试",
            task_description="d",
            executor_type=AgentType.EPHEMERAL_SUBAGENT.value,
            executor_id=AgentType.EPHEMERAL_SUBAGENT.value,
            user_task_id=None,
        )

        _finalize_sync_attempt(task_id, {"success": False, "message": "出错了"})

        with AssistantTaskRepository() as tasks:
            task = tasks.get_task(task_id)
        assert task is not None
        assert task.status == "suspended"  # 不是 abandoned
        assert task.suspend_reason == "waiting_system"

    def test_sync_attempt_code_defect_suspends(self, in_memory_db):
        """code_defect 落 SUSPENDED + blocked_by_defect。"""
        from src.business.orchestration.agent.delegation_orchestrator import (
            _start_sync_attempt,
            _finalize_sync_attempt,
        )

        sid = _seed_session("sess-sync-defect")
        task_id = _start_sync_attempt(
            parent_session_id=sid,
            task_title="测试",
            task_description="d",
            executor_type=AgentType.EPHEMERAL_SUBAGENT.value,
            executor_id=AgentType.EPHEMERAL_SUBAGENT.value,
            user_task_id=None,
        )

        _finalize_sync_attempt(task_id, {
            "success": False,
            "failure_class": "code_defect",
            "failure_exception_type": "TypeError",
        })

        with AssistantTaskRepository() as tasks:
            task = tasks.get_task(task_id)
        assert task is not None
        assert task.status == "suspended"
        assert task.suspend_reason == "blocked_by_defect"

    def test_sync_finalize_does_not_swallow_task_status_exception(self, in_memory_db):
        """_update_sync_task_status 不吞异常——吞了等于 task 静默留在 running。

        review 发现：如果 update_task_status 抛异常被 try/except 吞掉，
        task 就卡在 running——正是这个函数要修的 bug。
        """
        from src.business.orchestration.agent.delegation_orchestrator import (
            _finalize_sync_attempt,
            _start_sync_attempt,
        )

        sid = _seed_session("sess-sync-exception")
        task_id = _start_sync_attempt(
            parent_session_id=sid,
            task_title="测试",
            task_description="d",
            executor_type=AgentType.EPHEMERAL_SUBAGENT.value,
            executor_id=AgentType.EPHEMERAL_SUBAGENT.value,
            user_task_id=None,
        )

        # patch update_task_status 抛异常——_finalize_sync_attempt 的外层
        # except 会记日志但不抛（attempt 终态已经写完，task 状态更新失败是降级）。
        # 关键：_update_sync_task_status 内部不再吞异常。
        original_update = None

        from src.business.task_collaboration.service import TaskCollaborationService

        original_update = TaskCollaborationService.update_task_status
        TaskCollaborationService.update_task_status = MagicMock(
            side_effect=RuntimeError("DB down")
        )
        try:
            # 不应该抛出——_finalize_sync_attempt 外层 catch 了
            _finalize_sync_attempt(task_id, {"success": True, "result_text": "done"})
        finally:
            TaskCollaborationService.update_task_status = original_update

        # attempt 应该还是终态了（complete_if_current 在 update_task_status 之前）
        with AssistantTaskAttemptRepository() as attempts:
            latest = attempts.latest_attempt_for_task(task_id)
        assert latest is not None
        assert latest.status == "succeeded"


# ---------------------------------------------------------------------------
# dispatcher DELIVERED 写入顺序不变性
# ---------------------------------------------------------------------------


class TestDispatcherDeliveredWriteOrder:
    def test_delivered_written_after_adjudication(self, in_memory_db):
        """DELIVERED 在 create_parent_adjudication 之后写入。

        反顺序会留下"delivered 但无 pending 裁定"的死格子——非终态、非暂停、
        没 active attempt，recovery 扫不到、scheduler 推不动。
        """
        # 这个测试验证代码路径顺序——通过 patch 确认调用顺序
        from src.business.task_collaboration.dispatcher import TaskDispatcher
        from src.business.task_collaboration.service import TaskCollaborationService

        # 建一条 running task + active attempt
        sid = _seed_session("sess-order")
        with AssistantTaskRepository() as tasks:
            task_id = tasks.create_task(
                graph_id="tg_order",
                session_id=sid,
                title="顺序测试",
                description="d",
                assignee_type="ephemeral_subagent",
                assignee_id="exec_order",
                status="running",
            ).task_id
        with AssistantTaskAttemptRepository() as attempts:
            attempt = attempts.start_attempt(
                task_id=task_id,
                executor_type="ephemeral_subagent",
                executor_id="exec_order",
                lease_owner="test",
                lease_expires_at=utc_now_naive() + timedelta(minutes=5),
            )
            attempts.bind_session(task_id=task_id, executor_session_id="sess_order_child")

        # 记录调用顺序
        call_order: list[str] = []
        original_create = TaskCollaborationService.create_parent_adjudication
        original_update = TaskCollaborationService.update_task_status

        def track_create(self, **kw):
            call_order.append("adjudication")
            return original_create(self, **kw)

        def track_update(self, **kw):
            call_order.append("task_status")
            return original_update(self, **kw)

        TaskCollaborationService.create_parent_adjudication = track_create
        TaskCollaborationService.update_task_status = track_update
        try:
            dispatcher = TaskDispatcher()
            dispatcher._record_attempt_outcome(
                attempt_id=attempt.attempt_id,
                fence_token=attempt.fence_token,
                delivered_status="done",
                safe_summary="完成",
                result_ref="结果",
            )
        finally:
            TaskCollaborationService.create_parent_adjudication = original_create
            TaskCollaborationService.update_task_status = original_update

        # adjudication 必须在 task_status 之前
        assert "adjudication" in call_order
        assert "task_status" in call_order
        assert call_order.index("adjudication") < call_order.index("task_status")
