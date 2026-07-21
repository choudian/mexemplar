"""T067: US5 端到端 — 无人值守 fail-closed + 人工接管 + per-task 显式授权放行。

轻量 mock 版（避开真 LLM / 真 120s 确认超时），覆盖三条安全路径：

1. **未授权立即拒（D7，FR-023 / CC-004）**：scheduled 会话（task 未开免确认）触发高危
   确认时，``_confirm_or_reject`` 直接返回 ``confirmation_failed_closed``，不调
   ``_ask_user_confirm``、不空等 ``_CONFIRM_TIMEOUT``。
2. **反问 ``waiting_user`` 接管续跑（FR-013）**：run 落 ``waiting_user`` 后 ``takeover``
   CAS 回 ``running``，返回 ``sessionId`` 供前端打开接着聊。
3. **显式授权 per-task 放行（FR-024 / CC-005）**：用户开启某 task 免确认后，该 task 的
   scheduled 会话高危动作自动放行（``CONFIRM_SOURCE_UNATTENDED_TASK``），且**其他用户正在
   聊的会话不受影响**（``_auto_approve_enabled`` 仍 False）。
"""

from __future__ import annotations

import logging
import time

import pytest

import src.business.agents.tools.builtin_general_tools as general_tools
from src.business.agents import run_context
from src.business.agents.config import AgentType
from src.business.scheduling.scheduler_service import SchedulerService
from src.business.scheduling.session_launcher import SessionLauncher
from src.business.scheduling.unattended_confirmation_manager import (
    get_unattended_confirmation_manager,
    reset_state_for_tests as reset_unattended_state,
)
from src.data.models_sqlite import Session
from src.data.repos.scheduled_task_repository import ScheduledTaskRepository
from src.data.repos.session_repository import SessionRepository


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _reset_states():
    general_tools.reset_confirmation_state_for_tests()
    reset_unattended_state(authorized=set())
    yield
    general_tools.reset_confirmation_state_for_tests()
    reset_unattended_state(authorized=set())


def _create_session(
    session_id: str,
    *,
    source: str = "user",
    scheduled_task_id: str | None = None,
) -> str:
    SessionRepository().create(
        Session(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
            source=source,
            scheduled_task_id=scheduled_task_id,
            is_scheduled=1 if source == "scheduled" else 0,
        )
    )
    if source == "scheduled" and scheduled_task_id:
        with ScheduledTaskRepository() as repo:
            bound = repo.cas_bind_session(
                scheduled_task_id,
                session_id,
                expected_session_id=None,
            )
        assert bound is not None
    return session_id


def _create_scheduled_task(
    *,
    title: str = "test task",
    instruction: str = "test instruction",
    unattended: bool = False,
) -> str:
    with ScheduledTaskRepository() as r:
        row = r.create(
            source_type="direct",
            source_ref=instruction,
            title=title,
            schedule_kind="one_shot",
            schedule_payload={"run_at": "2026-07-19T10:00:00"},
            unattended_auto_approve=unattended,
        )
        return row.scheduled_task_id


# =============================================================================
# 1. 未授权立即拒（D7）—— 不空等超时
# =============================================================================


def test_unauthorized_scheduled_high_risk_rejected_immediately_without_timeout(monkeypatch):
    """scheduled + 未授权 → ``_confirm_or_reject`` 立即拒，``_ask_user_confirm`` 未被调。"""
    ask_calls: list[str] = []

    def _trap_ask(message, tool_name="unknown", **_kw):  # pragma: no cover - 不应被调
        ask_calls.append(message)
        return False

    monkeypatch.setattr(general_tools, "_ask_user_confirm", _trap_ask)

    # 创建未开免确认的 task + 关联 scheduled 会话
    task_id = _create_scheduled_task(title="高危 task", unattended=False)
    sched_session = _create_session(
        "ast_sched_e2e_unauth", source="scheduled", scheduled_task_id=task_id
    )

    run_context.begin(sched_session)
    started = time.monotonic()
    try:
        result = general_tools._confirm_or_reject("exec", "命令首行: Remove-Item -Recurse build")
    finally:
        run_context.end()
    elapsed = time.monotonic() - started

    assert ask_calls == []  # _ask_user_confirm 未被调
    assert elapsed < 5.0, f"D7 未立即返回，elapsed={elapsed:.2f}s"
    assert result is not None
    assert result.error_code == "confirmation_failed_closed"
    # 进程级开关仍未被读写
    assert general_tools.is_auto_approve_enabled() is False


# =============================================================================
# 2. 反问 waiting_user → 接管续跑（CAS 回 running）
# =============================================================================


def test_waiting_user_takeover_restores_running_and_returns_session_id():
    """run 落 ``waiting_user`` 后 ``takeover`` CAS 回 ``running``，返回 sessionId。"""
    dispatched: list = []
    launcher = SessionLauncher(
        dispatch_callback=lambda sid, instr, _run_id, _reservation_id: (
            dispatched.append((sid, instr)) or True
        )
    )
    with SchedulerService(launcher=launcher) as service:
        task_id = _create_scheduled_task(title="反问接管 task")
        run = service.fire_now(task_id)
        run_id = run["runId"]
        session_id = run["sessionId"]
        assert run["status"] == "running"

        # 模拟主助理反问：run CAS 转 waiting_user（由 RunCompletionMonitor 反问路径触发）
        from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

        with ScheduledTaskRunRepository() as rr:
            updated = rr.cas_transition(run_id, from_status="running", to_status="waiting_user")
        assert updated is not None
        assert updated.status == "waiting_user"

        # 用户接管：takeover CAS 回 running，返回原 sessionId
        result = service.takeover(run_id)
        assert result["sessionId"] == session_id

        # 验证 run 已回 running
        run_after = service.get_run(run_id)
        assert run_after["status"] == "running"


def test_takeover_returns_session_for_failed_run_without_resurrecting():
    """接管 failed run：返回原 sessionId 供前端打开，但不复活 failed run。"""
    launcher = SessionLauncher(dispatch_callback=lambda *_args: True)
    with SchedulerService(launcher=launcher) as service:
        task_id = _create_scheduled_task(title="failed 接管 task")
        run = service.fire_now(task_id)
        run_id = run["runId"]
        session_id = run["sessionId"]

        from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

        with ScheduledTaskRunRepository() as rr:
            rr.cas_transition(run_id, from_status="running", to_status="failed")

        # 接管 failed run：返回原 sessionId，run 状态保持 failed
        result = service.takeover(run_id)
        assert result["sessionId"] == session_id

        run_after = service.get_run(run_id)
        assert run_after["status"] == "failed"


def test_takeover_unknown_run_raises_lookup_error():
    """接管不存在的 run → LookupError（router 映射 404）。"""
    with SchedulerService() as service:
        with pytest.raises(LookupError):
            service.takeover("schr_does_not_exist")


# =============================================================================
# 3. 显式授权 per-task 放行（其他用户会话不受影响）
# =============================================================================


def test_authorized_task_auto_approves_only_for_its_scheduled_session(monkeypatch):
    """开启 per-task 免确认后：该 task 的 scheduled 会话自动放行，其他用户会话不受影响。"""
    ask_calls: list[str] = []

    def _record_ask(message, tool_name="unknown", **_kw):
        ask_calls.append(message)
        return False  # 用户会话走原流程，被拒绝

    monkeypatch.setattr(general_tools, "_ask_user_confirm", _record_ask)

    # 用户显式开 task 免确认（经 service.set_unattended，模拟详情页 PATCH）
    task_id = _create_scheduled_task(title="授权 task", unattended=False)
    with SchedulerService() as service:
        service.set_unattended(task_id, True)
    # UnattendedConfirmationManager 应已增量刷新（SchedulerService.set_unattended 内部调）
    manager = get_unattended_confirmation_manager()
    assert manager.is_authorized(task_id) is True
    # 进程级开关未被读写
    assert general_tools.is_auto_approve_enabled() is False

    # 该 task 的 scheduled 会话 → 自动放行（_ask_user_confirm 未被调）
    sched_session = _create_session(
        "ast_sched_e2e_auth", source="scheduled", scheduled_task_id=task_id
    )
    run_context.begin(sched_session)
    try:
        result = general_tools._confirm_or_reject("write_file", "目标文件: out.log")
    finally:
        run_context.end()
    assert result is None  # 放行
    assert ask_calls == []  # scheduled session 没走 _ask_user_confirm

    # 切到用户会话：高危确认仍走原流程（_ask_user_confirm 被调）
    user_session = _create_session("ast_user_e2e_chat", source="user")
    run_context.begin(user_session)
    try:
        user_result = general_tools._confirm_or_reject("write_file", "目标文件: user.txt")
    finally:
        run_context.end()
    assert len(ask_calls) == 1  # 用户会话走原流程
    assert user_result is not None
    assert user_result.error_code == "permission_denied"
    # 进程级开关仍未被读写
    assert general_tools.is_auto_approve_enabled() is False


def test_authorized_task_only_authorizes_its_own_session_not_others(monkeypatch):
    """task A 开启免确认：task B 的 scheduled 会话仍立即拒（per-task 粒度）。"""
    ask_calls: list[str] = []

    def _trap_ask(message, tool_name="unknown", **_kw):  # pragma: no cover - 不应被调
        ask_calls.append(message)
        return False

    monkeypatch.setattr(general_tools, "_ask_user_confirm", _trap_ask)

    task_a = _create_scheduled_task(title="task A 授权", unattended=False)
    task_b = _create_scheduled_task(title="task B 未授权", unattended=False)

    with SchedulerService() as service:
        service.set_unattended(task_a, True)
    manager = get_unattended_confirmation_manager()
    assert manager.is_authorized(task_a) is True
    assert manager.is_authorized(task_b) is False

    # task B 的 scheduled 会话仍 D7 立即拒
    sched_b = _create_session("ast_sched_task_b", source="scheduled", scheduled_task_id=task_b)
    run_context.begin(sched_b)
    try:
        result = general_tools._confirm_or_reject("exec", "命令首行: del build")
    finally:
        run_context.end()
    assert ask_calls == []
    assert result is not None
    assert result.error_code == "confirmation_failed_closed"


# =============================================================================
# 4. soft_delete 回收 per-task 授权
# =============================================================================


def test_soft_delete_revokes_per_task_authorization():
    """软删 task 后 UnattendedConfirmationManager 立即移除该 task 的授权（防悬空授权）。"""
    task_id = _create_scheduled_task(title="待删 task", unattended=False)
    with SchedulerService() as service:
        service.set_unattended(task_id, True)
    manager = get_unattended_confirmation_manager()
    assert manager.is_authorized(task_id) is True

    with SchedulerService() as service:
        service.soft_delete(task_id)
    # 软删后授权立即被回收
    assert manager.is_authorized(task_id) is False


# =============================================================================
# 5. 全量 reload + 审计日志（CONFIRM_SOURCE_UNATTENDED_TASK）
# =============================================================================


def test_load_all_pulls_persisted_unauthorized_tasks_and_audit_log_records_source(caplog):
    """重启侧载：load_all 从 SQLite 拉回持久化的 authorized set；放行路径审计来源正确。"""
    # 写一条持久化的 authorized task
    persistent_task = _create_scheduled_task(title="持久授权", unattended=True)
    # 写一条未授权 task
    unauth_task = _create_scheduled_task(title="持久未授权", unattended=False)

    # 重置 manager 内存授权集，模拟 sidecar 重启
    reset_unattended_state(authorized=set())
    manager = get_unattended_confirmation_manager()
    assert manager.snapshot() == frozenset()

    # 启动时全量加载（lifespan 入口）
    manager.load_all()
    assert manager.is_authorized(persistent_task) is True
    assert manager.is_authorized(unauth_task) is False

    # authorized 路径走 CONFIRM_SOURCE_UNATTENDED_TASK 审计来源
    sched_session = _create_session(
        "ast_sched_audit", source="scheduled", scheduled_task_id=persistent_task
    )
    run_context.begin(sched_session)
    try:
        with caplog.at_level(
            logging.INFO, logger="src.business.agents.tools.builtin_general_tools"
        ):
            result = general_tools._confirm_or_reject("edit_file", "编辑: config.toml")
    finally:
        run_context.end()

    assert result is None
    assert '"source": "unattended_task"' in caplog.text
    assert '"decision": "auto_approved"' in caplog.text
