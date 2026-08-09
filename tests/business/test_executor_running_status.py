"""④ 把"执行体在不在跑"从 session.status 切到 attempt.status。

验证：
- 同步委派路径建 task + attempt（executor_session_id 绑定、终态正确映射）
- 三处"在不在跑"判断查 attempt（不读 session.status）
- session→attempt 反查方法正确工作
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from src.business.agents.config import AgentType
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
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
# session→attempt 反查
# ---------------------------------------------------------------------------


class TestAttemptSessionLookup:
    def test_latest_attempt_for_session_returns_newest(self, in_memory_db):
        """按 executor_session_id 反查返回最新 attempt。"""
        sid = "sess-lookup-1"
        SessionRepository().create(
            SessionModel(
                session_id=sid, workflow_id=None, agent_type="ephemeral_subagent", status="active"
            )
        )
        with AssistantTaskRepository() as tasks:
            tid = tasks.create_task(
                graph_id="tg1", session_id="p1", title="t1", description="d",
                assignee_type="ephemeral_subagent", assignee_id=sid, status="running",
            ).task_id
        with AssistantTaskAttemptRepository() as attempts:
            attempt = attempts.start_attempt(
                task_id=tid, executor_type="ephemeral_subagent", executor_id=sid,
                lease_owner="test", lease_expires_at=utc_now_naive() + timedelta(minutes=5),
            )
            attempts.bind_session(task_id=tid, executor_session_id=sid)

            latest = attempts.latest_attempt_for_session(sid)
        assert latest is not None
        assert latest.attempt_id == attempt.attempt_id
        assert latest.status == "running"

    def test_latest_attempt_for_session_none_when_no_attempt(self, in_memory_db):
        """无 attempt 的 session 返回 None。"""
        with AssistantTaskAttemptRepository() as attempts:
            assert attempts.latest_attempt_for_session("never-existed") is None

    def test_active_executor_sessions_returns_active_set(self, in_memory_db):
        """批量返回有 active attempt 的 session 集合。"""
        sessions = [f"sess-batch-{i}" for i in range(3)]
        for sid in sessions:
            SessionRepository().create(
                SessionModel(
                    session_id=sid, workflow_id=None,
                    agent_type="ephemeral_subagent", status="active"
                )
            )
        with AssistantTaskRepository() as tasks:
            for i, sid in enumerate(sessions):
                tid = tasks.create_task(
                    graph_id=f"tg-{i}", session_id="p", title=f"t{i}", description="d",
                    assignee_type="ephemeral_subagent", assignee_id=sid, status="running",
                ).task_id
                with AssistantTaskAttemptRepository() as attempts:
                    attempt = attempts.start_attempt(
                        task_id=tid, executor_type="ephemeral_subagent", executor_id=sid,
                        lease_owner="test", lease_expires_at=utc_now_naive() + timedelta(minutes=5),
                    )
                    attempts.bind_session(task_id=tid, executor_session_id=sid)
                    if i == 1:
                        # 第二个已终态
                        attempts.complete_if_current(
                            attempt_id=attempt.attempt_id,
                            fence_token=attempt.fence_token,
                            result_ref="done",
                        )

        with AssistantTaskAttemptRepository() as attempts:
            active = attempts.active_executor_sessions(sessions)
        assert sessions[0] in active
        assert sessions[1] not in active  # 已 completed
        assert sessions[2] in active


# ---------------------------------------------------------------------------
# _is_executor_running（替代 session.status == "active"）
# ---------------------------------------------------------------------------


class TestIsExecutorRunning:
    def test_active_attempt_means_running(self, in_memory_db):
        """有 active attempt 的 session 判为在跑。"""
        sid = "sess-running-1"
        SessionRepository().create(
            SessionModel(
                session_id=sid, workflow_id=None,
                agent_type="ephemeral_subagent", status="active"
            )
        )
        with AssistantTaskRepository() as tasks:
            tid = tasks.create_task(
                graph_id="tg", session_id="p", title="t", description="d",
                assignee_type="ephemeral_subagent", assignee_id=sid, status="running",
            ).task_id
        with AssistantTaskAttemptRepository() as attempts:
            attempts.start_attempt(
                task_id=tid, executor_type="ephemeral_subagent", executor_id=sid,
                lease_owner="test", lease_expires_at=utc_now_naive() + timedelta(minutes=5),
            )
            attempts.bind_session(task_id=tid, executor_session_id=sid)

        assert AgentOrchestrator._is_executor_running(sid) is True

    def test_terminal_attempt_means_not_running(self, in_memory_db):
        """终态 attempt 判为不在跑。"""
        sid = "sess-running-2"
        SessionRepository().create(
            SessionModel(
                session_id=sid, workflow_id=None,
                agent_type="ephemeral_subagent", status="suspended"
            )
        )
        with AssistantTaskRepository() as tasks:
            tid = tasks.create_task(
                graph_id="tg", session_id="p", title="t", description="d",
                assignee_type="ephemeral_subagent", assignee_id=sid, status="running",
            ).task_id
        with AssistantTaskAttemptRepository() as attempts:
            attempt = attempts.start_attempt(
                task_id=tid, executor_type="ephemeral_subagent", executor_id=sid,
                lease_owner="test", lease_expires_at=utc_now_naive() + timedelta(minutes=5),
            )
            attempts.bind_session(task_id=tid, executor_session_id=sid)
            attempts.complete_if_current(
                attempt_id=attempt.attempt_id, fence_token=attempt.fence_token, result_ref="done"
            )

        assert AgentOrchestrator._is_executor_running(sid) is False

    def test_no_attempt_means_not_running(self, in_memory_db):
        """无 attempt 的 session 判为不在跑。"""
        assert AgentOrchestrator._is_executor_running("never-existed") is False


# ---------------------------------------------------------------------------
# latest_statuses_for_sessions：批量查每 session 最新 attempt status
# ---------------------------------------------------------------------------


class TestLatestStatusesForSessions:
    def _seed_session_with_attempt(self, session_id: str, status: str) -> None:
        """建 session + task + attempt，attempt 终态为给定 status。"""
        SessionRepository().create(
            SessionModel(
                session_id=session_id, workflow_id=None,
                agent_type="ephemeral_subagent", status="active"
            )
        )
        with AssistantTaskRepository() as tasks:
            tid = tasks.create_task(
                graph_id=f"tg_{session_id}", session_id="p", title="t", description="d",
                assignee_type="ephemeral_subagent", assignee_id=session_id, status="running",
            ).task_id
        with AssistantTaskAttemptRepository() as attempts:
            attempt = attempts.start_attempt(
                task_id=tid, executor_type="ephemeral_subagent", executor_id=session_id,
                lease_owner="test", lease_expires_at=utc_now_naive() + timedelta(minutes=5),
            )
            attempts.bind_session(task_id=tid, executor_session_id=session_id)
            if status == "succeeded":
                attempts.complete_if_current(
                    attempt_id=attempt.attempt_id, fence_token=attempt.fence_token,
                    result_ref="done"
                )
            elif status == "failed":
                attempts.fail_if_current(
                    attempt_id=attempt.attempt_id, fence_token=attempt.fence_token,
                    error_category="test"
                )
            elif status == "paused":
                attempts.pause_if_current(
                    attempt_id=attempt.attempt_id, fence_token=attempt.fence_token,
                )

    def test_returns_correct_status_per_session(self, in_memory_db):
        """每个 session 返回其最新 attempt 的 status。"""
        self._seed_session_with_attempt("sess-ls-1", "succeeded")
        self._seed_session_with_attempt("sess-ls-2", "paused")
        self._seed_session_with_attempt("sess-ls-3", "failed")

        with AssistantTaskAttemptRepository() as attempts:
            result = attempts.latest_statuses_for_sessions(
                ["sess-ls-1", "sess-ls-2", "sess-ls-3", "sess-no-attempt"]
            )
        assert result["sess-ls-1"] == "succeeded"
        assert result["sess-ls-2"] == "paused"
        assert result["sess-ls-3"] == "failed"
        assert "sess-no-attempt" not in result

    def test_empty_input_returns_empty(self, in_memory_db):
        with AssistantTaskAttemptRepository() as attempts:
            assert attempts.latest_statuses_for_sessions([]) == {}

    def test_returns_newest_when_multiple_attempts(self, in_memory_db):
        """同一 session 有多个 attempt 时返回最新那条的 status。"""
        sid = "sess-multi"
        SessionRepository().create(
            SessionModel(
                session_id=sid, workflow_id=None,
                agent_type="ephemeral_subagent", status="active"
            )
        )
        with AssistantTaskRepository() as tasks:
            t1 = tasks.create_task(
                graph_id="tg1", session_id="p", title="t1", description="d",
                assignee_type="ephemeral_subagent", assignee_id=sid, status="running",
            ).task_id
            t2 = tasks.create_task(
                graph_id="tg2", session_id="p", title="t2", description="d",
                assignee_type="ephemeral_subagent", assignee_id=sid, status="running",
            ).task_id
        with AssistantTaskAttemptRepository() as attempts:
            # 第一个 attempt 完成后，第二个还在 running
            a1 = attempts.start_attempt(
                task_id=t1, executor_type="ephemeral_subagent", executor_id=sid,
                lease_owner="test", lease_expires_at=utc_now_naive() + timedelta(minutes=5),
            )
            attempts.bind_session(task_id=t1, executor_session_id=sid)
            attempts.complete_if_current(
                attempt_id=a1.attempt_id, fence_token=a1.fence_token, result_ref="done"
            )
            import time
            time.sleep(1.1)  # 确保 created_at 不同（SQLite 精度到秒）
            a2 = attempts.start_attempt(
                task_id=t2, executor_type="ephemeral_subagent", executor_id=sid,
                lease_owner="test", lease_expires_at=utc_now_naive() + timedelta(minutes=5),
            )
            attempts.bind_session(task_id=t2, executor_session_id=sid)

            result = attempts.latest_statuses_for_sessions([sid])
        assert result[sid] == "running"  # 最新的是 running，不是 succeeded


# ---------------------------------------------------------------------------
# _finalize_sync_attempt：code_defect 终态映射
# ---------------------------------------------------------------------------


class TestFinalizeSyncAttemptCodeDefect:
    def test_code_defect_maps_to_paused_not_failed(self, in_memory_db):
        """code_defect 结果应映射成 paused（不是 failed）——与 _map_to_outcome 对齐。"""
        sid = "sess-defect"
        SessionRepository().create(
            SessionModel(
                session_id=sid, workflow_id=None,
                agent_type="ephemeral_subagent", status="active"
            )
        )
        from src.business.orchestration.agent.delegation_orchestrator import (
            _start_sync_attempt,
            _finalize_sync_attempt,
        )
        from src.business.agents.config import AgentType

        task_id = _start_sync_attempt(
            parent_session_id="parent",
            task_title="测试",
            task_description="d",
            executor_type=AgentType.EPHEMERAL_SUBAGENT.value,
            executor_id=AgentType.EPHEMERAL_SUBAGENT.value,
            user_task_id=None,
        )
        assert task_id is not None

        # code_defect 结果：success=False, failure_class=code_defect, 无 paused
        _finalize_sync_attempt(task_id, {
            "success": False,
            "failure_class": "code_defect",
            "failure_exception_type": "TypeError",
        })

        with AssistantTaskAttemptRepository() as attempts:
            latest = attempts.latest_attempt_for_task(task_id)
        assert latest is not None
        assert latest.status == "paused"  # 不是 failed
