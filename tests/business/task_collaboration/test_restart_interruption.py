"""⑤ 状态对齐半：断电恢复启动栅栏的行为测试。

sidecar 重启后，``TaskRecoveryService.mark_interrupted_after_restart`` 和
``ExternalCodingSessionService.recover_interrupted_after_restart`` 必须把上一代进程遗留的
假状态一次性对齐。判据是进程级全局事实——重启 = 上一代执行体线程物理全死。
"""

from __future__ import annotations

from datetime import timedelta

from src.business.external_coding.service import ExternalCodingSessionService
from src.business.task_collaboration.models import (
    ClaimStatus,
    OperationStatus,
    SuspendReason,
    TaskStatus,
    WaitingOn,
    _SUSPEND_REASON_WAITING_ON,
)
from src.business.task_collaboration.recovery import TaskRecoveryService
from src.business.task_collaboration.service import TaskCollaborationService
from src.business.agents.config import AgentType
from src.data.models_sqlite import Session
from src.data.repos import (
    AssistantTaskAttemptRepository,
    AssistantTaskClaimRepository,
    AssistantTaskOperationRepository,
    AssistantTaskRepository,
    SessionRepository,
)
from src.data.repos.base_repository import generate_id
from src.data.repos.external_coding_session_repository import (
    ExternalCodingSessionRepository,
)
from src.utils.timezone import utc_now_naive


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_graph_with_running_attempt(*, task_status: str = "running"):
    """建一个含单个节点的图，task 转 running，起一个未过期的 running attempt。

    返回 (graph_id, task_id, attempt_id, session_id)。
    """
    session_id = generate_id("sess")
    with TaskCollaborationService() as svc:
        result = svc.build_task_graph(
            session_id=session_id,
            nodes=[{"nodeId": "n1", "title": "Node", "description": "work"}],
        )
    task_id = result["nodeTaskIds"]["n1"]
    graph_id = result["graphId"]
    with TaskCollaborationService() as svc:
        svc.update_task_status(task_id=task_id, status=task_status)
    with AssistantTaskAttemptRepository() as attempts:
        attempt = attempts.start_attempt(
            task_id=task_id,
            executor_type="ephemeral_subagent",
            executor_id=task_id,
            lease_owner="test",
            lease_expires_at=utc_now_naive() + timedelta(hours=1),  # 未过期
        )
    assert attempt is not None
    return graph_id, task_id, attempt.attempt_id, session_id


def _seed_active_session(session_id: str | None = None) -> str:
    """直接造一个 active session（模拟断电时卡住的会话）。"""
    session_id = session_id or generate_id("sess")
    SessionRepository().create(
        Session(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    return session_id


def _seed_claimed(task_id: str) -> str:
    """造一个未过期 claimed 认领。"""
    with AssistantTaskClaimRepository() as claims:
        claim = claims.create_claim(
            task_id=task_id,
            claimer_type="ephemeral_subagent",
            claimer_id=task_id,
            task_version=1,
            lease_expires_at=utc_now_naive() + timedelta(hours=1),
        )
    return claim.claim_id


def _seed_in_progress_operation(task_id: str) -> str:
    """造一个 in_progress 副作用记录。"""
    with AssistantTaskOperationRepository() as operations:
        operation = operations.record_planned(
            task_id=task_id,
            attempt_id=task_id,  # 测试用，attempt_id 只做关联
            operation_key=f"op-{task_id}",
            operation_type="test",
            safe_summary="test side effect",
        )
        operations.update_status(operation.operation_id, OperationStatus.IN_PROGRESS)
    return operation.operation_id


# ---------------------------------------------------------------------------
# 摊①任务执行 + 摊②会话状态
# ---------------------------------------------------------------------------


class TestRestartMarksRunningAttemptsInterrupted:
    def test_running_attempt_fenced_and_task_suspended(self, in_memory_db):
        """遗留 running attempt → fenced，task → SUSPENDED + INTERRUPTED + USER。"""
        graph_id, task_id, attempt_id, session_id = _build_graph_with_running_attempt()

        with TaskRecoveryService() as service:
            count = service.mark_interrupted_after_restart()

        assert count == 1
        with AssistantTaskAttemptRepository() as attempts:
            attempt = attempts.get_by_id(attempt_id)
        assert attempt.status == "fenced"

        task = AssistantTaskRepository().get_task(task_id)
        assert task.status == TaskStatus.SUSPENDED.value
        assert task.suspend_reason == SuspendReason.INTERRUPTED.value
        assert task.waiting_on == WaitingOn.USER.value

    def test_all_active_sessions_cleared(self, in_memory_db):
        """所有 active session（含无 attempt 绑定的根 session）→ suspended。"""
        # 一个独立的主助理根 session（无 attempt 绑定——这才是⑤要覆盖的漏网场景）
        root_session = _seed_active_session()
        # 一个已完成（completed）的 session，不该被动
        done_session = _seed_active_session()
        SessionRepository().update_status(done_session, "completed")

        with TaskRecoveryService() as service:
            service.mark_interrupted_after_restart()

        repo = SessionRepository()
        assert repo.get_status(root_session) == "suspended"
        # 已终态的不动
        assert repo.get_status(done_session) == "completed"

    def test_scan_skips_terminal_tasks(self, in_memory_db):
        """task 已终态（COMPLETED）的，只 fence attempt，不碰 task。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[{"nodeId": "n1", "title": "N", "description": "d"}],
            )
        task_id = result["nodeTaskIds"]["n1"]
        with TaskCollaborationService() as svc:
            svc.update_task_status(task_id=task_id, status="running")
            svc.update_task_status(task_id=task_id, status="done")
        with AssistantTaskAttemptRepository() as attempts:
            attempt = attempts.start_attempt(
                task_id=task_id,
                executor_type="ephemeral_subagent",
                executor_id=task_id,
                lease_owner="test",
                lease_expires_at=utc_now_naive() + timedelta(hours=1),
            )

        with TaskRecoveryService() as service:
            count = service.mark_interrupted_after_restart()

        assert count == 1  # attempt 被处理
        with AssistantTaskAttemptRepository() as attempts:
            assert attempts.get_by_id(attempt.attempt_id).status == "fenced"
        # task 仍是 completed，没被改成 suspended
        task = AssistantTaskRepository().get_task(task_id)
        assert task.status == TaskStatus.COMPLETED.value

    def test_scan_idempotent(self, in_memory_db):
        """调两次：第二次 attempt 已 fenced（非 active），count=0。"""
        _, _, _, _ = _build_graph_with_running_attempt()

        with TaskRecoveryService() as service:
            first = service.mark_interrupted_after_restart()
        with TaskRecoveryService() as service:
            second = service.mark_interrupted_after_restart()

        assert first == 1
        assert second == 0


# ---------------------------------------------------------------------------
# 摊③看板认领 + 摊④副作用
# ---------------------------------------------------------------------------


class TestRestartClearsClaimsAndOperations:
    def test_claimed_expired_after_restart(self, in_memory_db):
        """所有 claimed → expired。"""
        _, task_id, _, _ = _build_graph_with_running_attempt()
        claim_id = _seed_claimed(task_id)

        with TaskRecoveryService() as service:
            service.mark_interrupted_after_restart()

        with AssistantTaskClaimRepository() as claims:
            claim = claims.get_claim(claim_id)
        assert claim.status == ClaimStatus.EXPIRED.value

    def test_in_progress_operation_failed_after_restart(self, in_memory_db):
        """所有 in_progress operation → failed。"""
        from src.data.models_sqlite import AssistantTaskOperation

        _, task_id, _, _ = _build_graph_with_running_attempt()
        op_id = _seed_in_progress_operation(task_id)

        with TaskRecoveryService() as service:
            service.mark_interrupted_after_restart()

        # get_by_key 排除 failed（设计如此——它是幂等重入查询，failed 允许重试），
        # 所以这里直接按主键查。
        with AssistantTaskOperationRepository() as operations:
            op = operations.session.get(AssistantTaskOperation, op_id)
        assert op is not None
        assert op.status == OperationStatus.FAILED.value


# ---------------------------------------------------------------------------
# 契约门卫
# ---------------------------------------------------------------------------


class TestInterruptedWaitingOnContract:
    def test_interrupted_maps_to_user(self):
        """契约门卫：INTERRUPTED → USER（防回退到 SYSTEM）。"""
        assert _SUSPEND_REASON_WAITING_ON[SuspendReason.INTERRUPTED] == WaitingOn.USER


# ---------------------------------------------------------------------------
# 启动栅栏后 worker 看到干净状态
# ---------------------------------------------------------------------------


class TestWorkerSeesCleanState:
    def test_scan_expired_active_returns_empty_after_restart_scan(self, in_memory_db):
        """扫描后，scan_expired_active 对原来的死 attempt 返回空（已 fenced）。"""
        _, _, _, _ = _build_graph_with_running_attempt()

        with TaskRecoveryService() as service:
            service.mark_interrupted_after_restart()

        with AssistantTaskAttemptRepository() as attempts:
            expired = attempts.scan_expired_active(utc_now_naive())
        assert expired == []


# ---------------------------------------------------------------------------
# 摊⑤外部 coding
# ---------------------------------------------------------------------------


def _seed_external_coding_running_attempt(*, coding_session_id: str | None = None):
    """直接造一个 running+unconfirmed 的 external coding attempt + planning session。"""
    coding_session_id = coding_session_id or generate_id("ecs")
    with ExternalCodingSessionRepository() as repo:
        repo.create_session(
            coding_session_id=coding_session_id,
            session_id=generate_id("sess"),
            owner_type="task",
            owner_id=generate_id("tsk"),
            parent_session_id=None,
            tool="claude_code",
            launch_mode="headless",
            status="planning",
            phase="plan",
            selected_reason="test",
            quota_state="available",
            worktree_path="worktree",
            branch_name=f"coding/{coding_session_id}",
            base_commit="a" * 40,
            artifact_dir="artifacts",
            handoff_path="artifacts/HANDOFF.md",
            plan_path="artifacts/PLAN.md",
            result_path="artifacts/RESULT.md",
        )
        attempt = repo.add_attempt(
            coding_session_id=coding_session_id,
            phase="plan",
            launch_mode="headless",
            status="running",
            command_summary="claude -p test",
            pid=99999,
            process_create_time=1234.5,
            termination_unconfirmed=True,
            launch_started=True,
        )
    return coding_session_id, attempt.attempt_id


class TestRestartRecoversExternalCoding:
    def test_running_attempt_marked_interrupted(self, in_memory_db):
        """external coding running attempt → interrupted，unconfirmed 清零，session → interrupted。"""
        coding_session_id, attempt_id = _seed_external_coding_running_attempt()

        with ExternalCodingSessionService() as service:
            count = service.recover_interrupted_after_restart()

        assert count == 1
        with ExternalCodingSessionRepository() as repo:
            attempt = repo.get_attempt(attempt_id)
            session = repo.get_session(coding_session_id)
        assert attempt.status == "interrupted"
        assert attempt.termination_unconfirmed is False
        assert attempt.finished_at is not None
        assert session.status == "interrupted"

    def test_terminal_attempts_not_touched(self, in_memory_db):
        """已终态（succeeded）的 attempt 不被动。"""
        coding_session_id, attempt_id = _seed_external_coding_running_attempt()
        with ExternalCodingSessionRepository() as repo:
            repo.update_attempt(
                attempt_id,
                status="succeeded",
                termination_unconfirmed=False,
            )

        with ExternalCodingSessionService() as service:
            count = service.recover_interrupted_after_restart()

        assert count == 0
        with ExternalCodingSessionRepository() as repo:
            attempt = repo.get_attempt(attempt_id)
        assert attempt.status == "succeeded"

    def test_scan_idempotent(self, in_memory_db):
        """调两次：第二次 running 池已空，count=0。"""
        _seed_external_coding_running_attempt()

        with ExternalCodingSessionService() as service:
            first = service.recover_interrupted_after_restart()
        with ExternalCodingSessionService() as service:
            second = service.recover_interrupted_after_restart()

        assert first == 1
        assert second == 0


# ---------------------------------------------------------------------------
# 静默失败路径隔离（AGENTS.md 规则 6：改静默失败路径必须补测试）
# ---------------------------------------------------------------------------


class TestSilentFailureIsolation:
    """每个 except Exception 块的 continue 必须不阻断其余摊。

    注入单摊 repo 失败，验证其余摊仍执行——这是"逐条 try/except 隔离"的设计契约。
    """

    def test_attempt_failure_does_not_block_other_stalls(self, in_memory_db, monkeypatch):
        """摊① fence 抛异常时，摊②③④仍执行。"""
        _, task_id, _, _ = _build_graph_with_running_attempt()
        _seed_active_session()
        _seed_claimed(task_id)
        _seed_in_progress_operation(task_id)

        with TaskRecoveryService() as service:
            monkeypatch.setattr(
                service._attempts, "fence", lambda _id: (_ for _ in ()).throw(RuntimeError("injected fence"))
            )
            service.mark_interrupted_after_restart()

        # 摊④ 仍执行：operation → failed
        from src.data.models_sqlite import AssistantTaskOperation

        with AssistantTaskOperationRepository() as operations:
            ops = (
                operations.session.query(AssistantTaskOperation)
                .filter(AssistantTaskOperation.task_id == task_id)
                .all()
            )
        assert any(o.status == OperationStatus.FAILED.value for o in ops)

    def test_session_failure_does_not_block_attempts(self, in_memory_db, monkeypatch):
        """摊② clear_all_active 抛异常时，摊①仍执行（attempt fenced + task suspended）。"""
        _, task_id, attempt_id, _ = _build_graph_with_running_attempt()

        with TaskRecoveryService() as service:
            monkeypatch.setattr(
                service._sessions,
                "clear_all_active",
                lambda: (_ for _ in ()).throw(RuntimeError("injected")),
            )
            service.mark_interrupted_after_restart()

        # 摊① 不受影响
        with AssistantTaskAttemptRepository() as attempts:
            assert attempts.get_by_id(attempt_id).status == "fenced"
        task = AssistantTaskRepository().get_task(task_id)
        assert task.status == TaskStatus.SUSPENDED.value

    def test_claim_failure_does_not_block_other_stalls(self, in_memory_db, monkeypatch):
        """摊③ update_status 抛异常时，摊①②仍执行。"""
        _, task_id, attempt_id, _ = _build_graph_with_running_attempt()
        root_session = _seed_active_session()

        with TaskRecoveryService() as service:
            monkeypatch.setattr(
                service._claims,
                "update_status",
                lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("injected claim")),
            )
            service.mark_interrupted_after_restart()

        # 摊①② 仍执行
        with AssistantTaskAttemptRepository() as attempts:
            assert attempts.get_by_id(attempt_id).status == "fenced"
        assert SessionRepository().get_status(root_session) == "suspended"

    def test_operation_failure_does_not_block_attempts(self, in_memory_db, monkeypatch):
        """摊④ update_status 抛异常时，摊①仍执行。"""
        _, task_id, attempt_id, _ = _build_graph_with_running_attempt()

        with TaskRecoveryService() as service:
            monkeypatch.setattr(
                service._operations,
                "update_status",
                lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("injected")),
            )
            service.mark_interrupted_after_restart()

        # 摊① 不受影响
        with AssistantTaskAttemptRepository() as attempts:
            assert attempts.get_by_id(attempt_id).status == "fenced"

    def test_external_coding_failure_isolated_per_attempt(self, in_memory_db, monkeypatch):
        """external coding 摊：一条 attempt 投影失败不阻断其它。"""
        first_session, first_attempt = _seed_external_coding_running_attempt()
        second_session, second_attempt = _seed_external_coding_running_attempt()

        original = ExternalCodingSessionRepository.update_session_and_attempt

        def _fail_first_then_pass(self, *, attempt_id, **kw):
            if attempt_id == first_attempt:
                raise RuntimeError("injected projection failure")
            return original(self, attempt_id=attempt_id, **kw)

        monkeypatch.setattr(
            ExternalCodingSessionRepository,
            "update_session_and_attempt",
            _fail_first_then_pass,
        )

        with ExternalCodingSessionService() as service:
            count = service.recover_interrupted_after_restart()

        # 第二条成功
        assert count == 1
        with ExternalCodingSessionRepository() as repo:
            assert repo.get_attempt(second_attempt).status == "interrupted"
            # 第一条仍 running（失败被跳过）
            assert repo.get_attempt(first_attempt).status == "running"


# ---------------------------------------------------------------------------
# external_coding _emit 契约（review finding 1）
# ---------------------------------------------------------------------------


class TestExternalCodingEmitContract:
    def test_recover_emits_session_changed(self, in_memory_db):
        """recover_interrupted_after_restart 必须发 external_coding_session_changed。"""
        from unittest.mock import patch

        _seed_external_coding_running_attempt()

        with patch("src.business.external_coding.service.emit") as mock_emit:
            with ExternalCodingSessionService() as service:
                service.recover_interrupted_after_restart()

        # 至少有一条 external_coding_session_changed 事件（change_type=interrupted）
        emitted_types = [c.kwargs.get("change_type") for c in mock_emit.call_args_list]
        assert "interrupted" in emitted_types
