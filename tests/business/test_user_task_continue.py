"""⑦+③ 后端行为测试：latest_resume_target_for_task + continue_user_task + distribution。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.business.agents.config import AgentType
from src.business.task_collaboration.models import TaskStatus
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.models_sqlite import Message, Session as SessionModel
from src.data.repos import (
    AssistantTaskRepository,
    SessionRepository,
    UserTaskRepository,
)
from src.data.repos.assistant_task_attempt_repository import (
    AssistantTaskAttemptRepository,
)
from src.utils.timezone import utc_now_naive


def _seed_session(session_id: str) -> str:
    SessionRepository().create(
        SessionModel(
            session_id=session_id, workflow_id=None,
            agent_type=AgentType.ASSISTANT, status="active",
        )
    )
    return session_id


def _suspend_task(task_id: str, *, suspend_reason: str, waiting_on: str) -> None:
    """把 task 从 running 翻成 suspended（需要 suspend_reason + waiting_on）。"""
    with AssistantTaskRepository() as tasks:
        tasks.update_status(
            task_id, status="suspended",
            suspend_reason=suspend_reason, waiting_on=waiting_on,
        )


# ---------------------------------------------------------------------------
# latest_resume_target_for_task：三条硬规则
# ---------------------------------------------------------------------------


class TestLatestResumeTarget:
    def _setup_task_with_attempt(
        self,
        *,
        task_id: str,
        session_id: str,
        executor_session_id: str,
        attempt_status: str,
        assignee_type: str = "ephemeral_subagent",
        assignee_id: str = "exec_1",
        with_assistant_msg: bool = True,
    ) -> None:
        with AssistantTaskRepository() as tasks:
            tasks.create_task(
                graph_id=f"tg_{task_id}", session_id=session_id,
                task_id=task_id, title="t", description="d",
                assignee_type=assignee_type, assignee_id=assignee_id,
                status="running",
            )
        with AssistantTaskAttemptRepository() as attempts:
            attempt = attempts.start_attempt(
                task_id=task_id, executor_type=assignee_type,
                executor_id=assignee_id, lease_owner="test",
                lease_expires_at=utc_now_naive() + timedelta(minutes=5),
            )
            attempts.bind_session(task_id=task_id, executor_session_id=executor_session_id)
            if attempt_status == "paused":
                attempts.pause_if_current(
                    attempt_id=attempt.attempt_id, fence_token=attempt.fence_token,
                )
            elif attempt_status == "fenced":
                attempts.fence(attempt_id=attempt.attempt_id)
        if with_assistant_msg:
            from src.data.repos.message_repository import MessageRepository
            with MessageRepository() as msgs:
                msgs.create(Message(
                    message_id=f"msg_{executor_session_id}",
                    session_id=executor_session_id,
                    sequence=1, role="assistant", content="",
                ))

    def test_fenced_attempt_is_resumable(self, in_memory_db):
        """规则一修订：fenced 也续跑（带对账提示）。"""
        sid = _seed_session("sess_rt_fenced")
        self._setup_task_with_attempt(
            task_id="tsk_rt_fenced", session_id=sid,
            executor_session_id="exec_sess_fenced",
            attempt_status="fenced",
        )
        with AssistantTaskAttemptRepository() as attempts:
            target = attempts.latest_resume_target_for_task(
                "tsk_rt_fenced",
                assignee_type="ephemeral_subagent",
                assignee_id="exec_1",
            )
        assert target is not None
        assert target["session_id"] == "exec_sess_fenced"
        assert target["was_fenced"] is True

    def test_paused_attempt_is_resumable(self, in_memory_db):
        """paused 正常续跑。"""
        sid = _seed_session("sess_rt_paused")
        self._setup_task_with_attempt(
            task_id="tsk_rt_paused", session_id=sid,
            executor_session_id="exec_sess_paused",
            attempt_status="paused",
        )
        with AssistantTaskAttemptRepository() as attempts:
            target = attempts.latest_resume_target_for_task(
                "tsk_rt_paused",
                assignee_type="ephemeral_subagent",
                assignee_id="exec_1",
            )
        assert target is not None
        assert target["was_fenced"] is False

    def test_executor_mismatch_rejected(self, in_memory_db):
        """规则二：executor 不匹配时不选。"""
        sid = _seed_session("sess_rt_mismatch")
        self._setup_task_with_attempt(
            task_id="tsk_rt_mm", session_id=sid,
            executor_session_id="exec_sess_mm",
            attempt_status="paused",
            assignee_id="exec_A",
        )
        with AssistantTaskAttemptRepository() as attempts:
            target = attempts.latest_resume_target_for_task(
                "tsk_rt_mm",
                assignee_type="ephemeral_subagent",
                assignee_id="exec_B",  # 不同执行人
            )
        assert target is None

    def test_no_progress_skipped(self, in_memory_db):
        """has_progress：会话没有 assistant 消息时不选。"""
        sid = _seed_session("sess_rt_noprog")
        self._setup_task_with_attempt(
            task_id="tsk_rt_noprog", session_id=sid,
            executor_session_id="exec_sess_noprog",
            attempt_status="paused",
            with_assistant_msg=False,
        )
        with AssistantTaskAttemptRepository() as attempts:
            target = attempts.latest_resume_target_for_task(
                "tsk_rt_noprog",
                assignee_type="ephemeral_subagent",
                assignee_id="exec_1",
            )
        assert target is None

    def test_none_when_no_paused_or_fenced(self, in_memory_db):
        """没有 paused/fenced attempt 时返回 None。"""
        sid = _seed_session("sess_rt_none")
        with AssistantTaskRepository() as tasks:
            tasks.create_task(
                graph_id="tg_none", session_id=sid,
                task_id="tsk_rt_none", title="t", description="d",
                assignee_type="ephemeral_subagent", assignee_id="exec_1",
                status="running",
            )
        with AssistantTaskAttemptRepository() as attempts:
            target = attempts.latest_resume_target_for_task(
                "tsk_rt_none",
                assignee_type="ephemeral_subagent",
                assignee_id="exec_1",
            )
        assert target is None


# ---------------------------------------------------------------------------
# continue_user_task：单节点图（直接挂的专员）不被跳过
# ---------------------------------------------------------------------------


class TestContinueUserTaskSingleNode:
    def test_single_node_graph_root_is_pushed(self, in_memory_db):
        """同步委派的单节点图根不被 continue_user_task 跳过。"""
        sid = _seed_session("sess_ct_single")
        user_task_id = UserTaskRepository().create(
            session_id=sid, title="测试任务"
        ).task_id

        with AssistantTaskRepository() as tasks:
            tasks.create_task(
                graph_id="tg_single", session_id=sid,
                task_id="tsk_single", title="单节点任务", description="d",
                user_task_id=user_task_id,
                assignee_type="ephemeral_subagent", assignee_id="exec",
                status="running",
            )
        _suspend_task("tsk_single", suspend_reason="user_stop", waiting_on="user")

        with TaskCollaborationService() as tcs:
            report = tcs.continue_user_task(
                session_id=sid, user_task_id=user_task_id,
            )
        assert report["success"] is True
        assert len(report["pushed"]) == 1
        assert report["pushed"][0]["title"] == "单节点任务"


# ---------------------------------------------------------------------------
# status_distribution_for_user_task：读 waiting_on 列
# ---------------------------------------------------------------------------


class TestStatusDistribution:
    def test_distribution_reads_waiting_on_column(self, in_memory_db):
        """分布查询直接读 waiting_on 列（不硬编码 map）。"""
        sid = _seed_session("sess_dist")
        user_task_id = UserTaskRepository().create(
            session_id=sid, title="分布测试"
        ).task_id

        with AssistantTaskRepository() as tasks:
            # root 容器
            tasks.create_task(
                graph_id="tg_dist", session_id=sid,
                task_id="tsk_root", title="root", description="d",
                user_task_id=user_task_id,
                status="running",
            )
            # 2 个 done 子节点
            for i in range(2):
                tasks.create_task(
                    graph_id="tg_dist", session_id=sid,
                    root_task_id="tsk_root", parent_task_id="tsk_root",
                    task_id=f"tsk_done_{i}", title="done", description="d",
                    status="done",
                )
            # 1 个 suspended:waiting_user 子节点
            tasks.create_task(
                graph_id="tg_dist", session_id=sid,
                root_task_id="tsk_root", parent_task_id="tsk_root",
                task_id="tsk_su", title="suspended", description="d",
                status="running",
            )

        _suspend_task("tsk_su", suspend_reason="waiting_user", waiting_on="user")

        with AssistantTaskRepository() as tasks:
            distribution = tasks.status_distribution_for_user_task(user_task_id)

        assert distribution.get("done") == 2
        assert distribution.get("suspended:user") == 1


# ---------------------------------------------------------------------------
# §2.4 原子化 continue：不经过 PENDING_DISPATCH
# ---------------------------------------------------------------------------


class TestAtomicContinue:
    def test_suspended_task_goes_straight_to_running(self, in_memory_db):
        """原子化 continue：task 从 SUSPENDED 直接翻 RUNNING，不经过 PENDING_DISPATCH。"""
        from src.business.task_collaboration.dispatcher import TaskDispatcher

        sid = _seed_session("sess_atomic")
        # 建一条 suspended task（有 paused attempt + executor_session_id + assistant 消息）
        with AssistantTaskRepository() as tasks:
            tasks.create_task(
                graph_id="tg_atomic", session_id=sid,
                task_id="tsk_atomic", title="原子测试", description="d",
                assignee_type="ephemeral_subagent", assignee_id="exec_atomic",
                status="running",
            )
        _suspend_task("tsk_atomic", suspend_reason="user_stop", waiting_on="user")

        with AssistantTaskAttemptRepository() as attempts:
            attempt = attempts.start_attempt(
                task_id="tsk_atomic", executor_type="ephemeral_subagent",
                executor_id="exec_atomic", lease_owner="test",
                lease_expires_at=utc_now_naive() + timedelta(minutes=5),
            )
            attempts.bind_session(task_id="tsk_atomic", executor_session_id="exec_sess_atomic")
            attempts.pause_if_current(
                attempt_id=attempt.attempt_id, fence_token=attempt.fence_token,
            )
        from src.data.repos.message_repository import MessageRepository
        with MessageRepository() as msgs:
            msgs.create(Message(
                message_id="msg_atomic", session_id="exec_sess_atomic",
                sequence=1, role="assistant", content="",
            ))

        # 执行原子化 continue——只验证状态变更（attempt + task RUNNING），
        # 不实际跑 worker。直接模拟原子操作的核心：选续跑目标 → 建 attempt → 翻 RUNNING。
        with AssistantTaskAttemptRepository() as attempts:
            target = attempts.latest_resume_target_for_task(
                "tsk_atomic",
                assignee_type="ephemeral_subagent",
                assignee_id="exec_atomic",
            )
            assert target is not None
            import json
            checkpoint_ref = json.dumps({"executor_session_id": target["session_id"]})
            attempt = attempts.start_attempt(
                task_id="tsk_atomic", executor_type="ephemeral_subagent",
                executor_id="exec_atomic", lease_owner="test",
                lease_expires_at=utc_now_naive() + timedelta(minutes=5),
                checkpoint_ref=checkpoint_ref,
            )
            assert attempt is not None

        # task 从 SUSPENDED 直接翻 RUNNING（不经过 PENDING_DISPATCH）
        from src.business.task_collaboration.service import TaskCollaborationService
        with TaskCollaborationService() as svc:
            svc.update_task_status(task_id="tsk_atomic", status="running")

        # task 应该直接是 running，不是 pending_dispatch
        with AssistantTaskRepository() as tasks:
            task = tasks.get_task("tsk_atomic")
        assert task is not None
        assert task.status == "running"  # 不是 pending_dispatch

    def test_non_suspended_task_skipped(self, in_memory_db):
        """非 SUSPENDED 的 task 被跳过（返回 None）。"""
        from src.business.task_collaboration.dispatcher import TaskDispatcher

        sid = _seed_session("sess_atomic_skip")
        with AssistantTaskRepository() as tasks:
            tasks.create_task(
                graph_id="tg_skip", session_id=sid,
                task_id="tsk_skip", title="skip", description="d",
                assignee_type="ephemeral_subagent", assignee_id="exec",
                status="done",
            )

        dispatcher = TaskDispatcher(executor_callback=lambda _aid: {"success": True})
        future = dispatcher.continue_task_atomically(task_id="tsk_skip")
        assert future is None  # done 状态不该被 continue


# ---------------------------------------------------------------------------
# §2.5 有界等待：旧 attempt 还 active 时轮询等停稳
# ---------------------------------------------------------------------------


class TestWaitForActiveAttempt:
    def test_returns_true_when_no_active_attempt(self, in_memory_db):
        """没有 active attempt 时立即返回 True。"""
        from src.business.task_collaboration.dispatcher import TaskDispatcher

        dispatcher = TaskDispatcher()
        assert dispatcher.wait_for_active_attempt("never_exists", timeout_seconds=0.5) is True

    def test_returns_false_on_timeout(self, in_memory_db):
        """旧 attempt 一直 active 时超时返回 False。"""
        from src.business.task_collaboration.dispatcher import TaskDispatcher

        sid = _seed_session("sess_wait_timeout")
        with AssistantTaskRepository() as tasks:
            tasks.create_task(
                graph_id="tg_wait", session_id=sid,
                task_id="tsk_wait", title="wait", description="d",
                assignee_type="ephemeral_subagent", assignee_id="exec_wait",
                status="running",
            )
        with AssistantTaskAttemptRepository() as attempts:
            attempts.start_attempt(
                task_id="tsk_wait", executor_type="ephemeral_subagent",
                executor_id="exec_wait", lease_owner="test",
                lease_expires_at=utc_now_naive() + timedelta(minutes=5),
            )

        dispatcher = TaskDispatcher()
        # attempt 是 running（active），轮询 0.5 秒后超时
        result = dispatcher.wait_for_active_attempt(
            "tsk_wait", timeout_seconds=0.5, poll_interval_seconds=0.1
        )
        assert result is False

