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
