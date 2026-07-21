"""T062: per-task 无人值守免确认范围 guard（033 US5 / FR-024 / CC-005）。

四重限定的硬保证（独立维度，绝不污染进程级 ``_auto_approve_enabled``）：

1. **``_auto_approve_enabled`` 值不被读写**——开启某 task 免确认后，进程级单一布尔
   仍为 False（per-task 走独立 ``UnattendedConfirmationManager``）；
2. **用户会话（``source='user'``）高危确认仍走原流程**（``_ask_user_confirm`` 被调）；
3. **另一未授权 scheduled task 的高危确认立即拒**（D7，不调 ``_ask_user_confirm``、不空等
   ``_CONFIRM_TIMEOUT``）；
4. **决策审计日志记 ``CONFIRM_SOURCE_UNATTENDED_TASK``**（authorized 路径，per-task 来源
   标记可观测）。

通过 ``run_context.begin`` 把 root session 绑到当前线程，``_confirm_or_reject`` 据此查
session.source / scheduled_task_id 与 UnattendedConfirmationManager 授权集；mock
``_ask_user_confirm`` 避开真 LLM / 真 120s 等待。
"""

from __future__ import annotations

import logging
import time

import pytest

import src.business.agents.tools.builtin_general_tools as general_tools
from src.business.agents import run_context
from src.business.agents.config import AgentType
from src.business.scheduling.unattended_confirmation_manager import (
    get_unattended_confirmation_manager,
    reset_state_for_tests as reset_unattended_state,
)
from src.data.models_sqlite import ScheduledTask, Session
from src.data.repos.scheduled_task_repository import ScheduledTaskRepository
from src.data.repos.session_repository import SessionRepository
from src.utils.timezone import utc_now_naive

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
    bind_current: bool = True,
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
    if source == "scheduled" and scheduled_task_id and bind_current:
        now = utc_now_naive()
        with ScheduledTaskRepository() as repo:
            repo.session.add(
                ScheduledTask(
                    scheduled_task_id=scheduled_task_id,
                    source_type="direct",
                    source_ref="测试调度任务",
                    title="测试调度任务",
                    instruction="测试调度任务",
                    schedule_kind="recurring",
                    schedule_payload='{"interval_seconds":60}',
                    status="active",
                    unattended_auto_approve=1,
                    next_fire_at=now,
                    session_id=session_id,
                    is_deleted=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            repo.session.commit()
    return session_id


# =============================================================================
# 1. 进程级 _auto_approve_enabled 与 per-task 授权集完全独立
# =============================================================================


def test_unattended_per_task_does_not_touch_process_level_auto_approve():
    """开启某 task 免确认后，``_auto_approve_enabled`` 仍为 False（独立维度）。"""
    assert general_tools.is_auto_approve_enabled() is False
    manager = get_unattended_confirmation_manager()

    # 给两个 task 开启 per-task 免确认
    manager.set("sch_task_a", True)
    manager.set("sch_task_b", True)
    assert manager.is_authorized("sch_task_a") is True
    assert manager.is_authorized("sch_task_b") is True

    # 进程级单一布尔必须仍为 False（per-task 走独立维度）
    assert general_tools.is_auto_approve_enabled() is False

    # 关闭其中之一，进程级仍不变
    manager.set("sch_task_a", False)
    assert manager.is_authorized("sch_task_a") is False
    assert manager.is_authorized("sch_task_b") is True
    assert general_tools.is_auto_approve_enabled() is False


def test_unattended_helper_does_not_call_is_auto_approve_enabled(monkeypatch):
    """``_unattended_auto_approve_for`` 决不读写进程级开关（mutator/accessor 都不调）。"""
    forbidden_calls: list[str] = []

    def _forbid_setter(enabled, source):  # type: ignore[no-untyped-def]
        forbidden_calls.append(f"set:{enabled}:{source}")
        # 仍提供真实行为以不破坏其他路径
        general_tools._auto_approve_enabled = bool(enabled)

    def _forbid_getter():
        forbidden_calls.append("get")
        return False

    monkeypatch.setattr(general_tools, "set_auto_approve_enabled", _forbid_setter)
    monkeypatch.setattr(general_tools, "is_auto_approve_enabled", _forbid_getter)

    _create_session("ast_sched_alpha", source="scheduled", scheduled_task_id="sch_alpha")
    get_unattended_confirmation_manager().set("sch_alpha", True)

    decision = general_tools._unattended_auto_approve_for("ast_sched_alpha")
    assert decision == "authorized"
    # 进程级开关的 setter / getter 完全未被本路径调用
    assert forbidden_calls == []


# =============================================================================
# 2. 用户会话（source='user'）高危确认仍走原流程
# =============================================================================


def test_user_session_high_risk_falls_through_to_ask_user(monkeypatch):
    """``source='user'`` 会话不被 per-task 免确认放行，也不被 D7 立即拒——走原逻辑。"""
    ask_calls: list[str] = []

    def _fake_ask(message, tool_name="unknown", **_kw):
        ask_calls.append(message)
        return False  # 用户拒绝

    monkeypatch.setattr(general_tools, "_ask_user_confirm", _fake_ask)

    user_session = _create_session("ast_user_main_001", source="user")
    run_context.begin(user_session)
    try:
        result = general_tools._confirm_or_reject("write_file", "目标文件: demo.txt")
    finally:
        run_context.end()

    # 走原逻辑 = _ask_user_confirm 被调（用户拒绝 → permission_denied）
    assert len(ask_calls) == 1
    assert result is not None
    assert result.error_code == "permission_denied"


def test_user_session_unattended_helper_returns_passthrough():
    """``source='user'`` 直接判定 ``passthrough``（不进 scheduled 分支）。"""
    _create_session("ast_user_main_002", source="user")
    # 即使错把 user session 的 task_id 加进授权集，user 会话仍走原逻辑
    get_unattended_confirmation_manager().set("sch_user_phantom", True)

    decision = general_tools._unattended_auto_approve_for("ast_user_main_002")
    assert decision == "passthrough"


# =============================================================================
# 3. 另一未授权 scheduled task 的高危确认仍立即拒绝（D7，不空等超时）
# =============================================================================


def test_unauthorized_scheduled_session_rejects_immediately_without_waiting(monkeypatch):
    """scheduled + 未授权 → D7 立即拒：``_ask_user_confirm`` 不被调，不空等超时。"""
    ask_calls: list[str] = []

    def _trap_ask(message, tool_name="unknown", **_kw):  # pragma: no cover - 不应被调
        ask_calls.append(message)
        return False

    monkeypatch.setattr(general_tools, "_ask_user_confirm", _trap_ask)

    # 任务 A 已授权，但本次 session 关联的是任务 B（未授权）
    get_unattended_confirmation_manager().set("sch_authorized_task_a", True)

    scheduled_session = _create_session(
        "ast_sched_unauth", source="scheduled", scheduled_task_id="sch_unauthorized_task_b"
    )
    run_context.begin(scheduled_session)
    started = time.monotonic()
    try:
        result = general_tools._confirm_or_reject("exec", "命令首行: rm -rf build")
    finally:
        run_context.end()
    elapsed = time.monotonic() - started

    # D7 立即拒 = ``_ask_user_confirm`` 未被调
    assert ask_calls == []
    # 必须 < 5s（远短于 120s 超时；测试环境略有抖动留余量）
    assert elapsed < 5.0, f"D7 未立即返回，elapsed={elapsed:.2f}s"
    assert result is not None
    assert result.error_code == "confirmation_failed_closed"


def test_process_auto_approve_cannot_override_unauthorized_scheduled_task(monkeypatch):
    """普通聊天开启「全部允许」也不得越过 scheduled 的 per-task 授权边界。"""
    ask_calls: list[str] = []
    monkeypatch.setattr(
        general_tools,
        "_ask_user_confirm",
        lambda *_args, **_kwargs: ask_calls.append("called") or True,
    )
    general_tools.set_auto_approve_enabled(
        True,
        general_tools.CONFIRM_SOURCE_TOP_TOGGLE,
    )
    scheduled_session = _create_session(
        "ast_sched_global_auto_scope",
        source="scheduled",
        scheduled_task_id="sch_without_unattended_authorization",
    )

    run_context.begin(scheduled_session)
    try:
        result = general_tools._confirm_or_reject("exec", "命令首行: dangerous-command")
    finally:
        run_context.end()

    assert ask_calls == []
    assert result is not None
    assert result.error_code == "confirmation_failed_closed"
    assert general_tools.is_auto_approve_enabled() is True


def test_unauthorized_scheduled_helper_returns_reject_immediately():
    """``_unattended_auto_approve_for`` 对未授权 scheduled 直接返回 ``reject_immediately``。"""
    _create_session(
        "ast_sched_unauth_helper", source="scheduled", scheduled_task_id="sch_task_orphan"
    )
    # 授权集为空（未对该 task 显式开启）
    decision = general_tools._unattended_auto_approve_for("ast_sched_unauth_helper")
    assert decision == "reject_immediately"


def test_scheduled_authorization_lookup_failure_rejects_instead_of_prompting(
    monkeypatch,
):
    from src.business.scheduling import (
        unattended_confirmation_manager as manager_module,
    )

    class _FailingManager:
        @staticmethod
        def is_authorized(_task_id):
            raise RuntimeError("authorization store unavailable")

    _create_session(
        "ast_sched_auth_error",
        source="scheduled",
        scheduled_task_id="sch_auth_error",
    )
    monkeypatch.setattr(
        manager_module,
        "get_unattended_confirmation_manager",
        lambda: _FailingManager(),
    )

    decision = general_tools._unattended_auto_approve_for("ast_sched_auth_error")

    assert decision == "reject_immediately"


# =============================================================================
# 4. 决策审计日志记 CONFIRM_SOURCE_UNATTENDED_TASK（authorized 路径）
# =============================================================================


def test_authorized_scheduled_session_logs_unattended_task_source(caplog):
    """scheduled + 授权 → 放行且审计日志记 ``CONFIRM_SOURCE_UNATTENDED_TASK``。"""
    _create_session("ast_sched_auth_log", source="scheduled", scheduled_task_id="sch_audit_task")
    get_unattended_confirmation_manager().set("sch_audit_task", True)

    run_context.begin("ast_sched_auth_log")
    try:
        with caplog.at_level(
            logging.INFO, logger="src.business.agents.tools.builtin_general_tools"
        ):
            result = general_tools._confirm_or_reject("write_file", "目标文件: out.log")
    finally:
        run_context.end()

    assert result is None  # 放行
    assert '"source": "unattended_task"' in caplog.text
    assert '"decision": "auto_approved"' in caplog.text
    # 进程级开关未被读写
    assert general_tools.is_auto_approve_enabled() is False


def test_authorized_scheduled_session_actually_passes_through(monkeypatch):
    """scheduled + 授权 → ``_ask_user_confirm`` 不被调，``_confirm_or_reject`` 返回 None。"""
    ask_calls: list[str] = []

    def _trap_ask(message, tool_name="unknown", **_kw):  # pragma: no cover - 不应被调
        ask_calls.append(message)
        return True

    monkeypatch.setattr(general_tools, "_ask_user_confirm", _trap_ask)

    _create_session("ast_sched_auth_pass", source="scheduled", scheduled_task_id="sch_pass_task")
    get_unattended_confirmation_manager().set("sch_pass_task", True)

    run_context.begin("ast_sched_auth_pass")
    try:
        result = general_tools._confirm_or_reject("edit_file", "编辑文件: config.toml")
    finally:
        run_context.end()

    assert ask_calls == []
    assert result is None  # 放行


def test_reset_old_session_cannot_reuse_task_unattended_authorization() -> None:
    task_id = "sch_rebound_unattended"
    _create_session(
        "ast_rebound_old",
        source="scheduled",
        scheduled_task_id=task_id,
        bind_current=False,
    )
    _create_session(
        "ast_rebound_current",
        source="scheduled",
        scheduled_task_id=task_id,
    )
    get_unattended_confirmation_manager().set(task_id, True)

    assert general_tools._unattended_auto_approve_for("ast_rebound_old") == "reject_immediately"
    assert general_tools._unattended_auto_approve_for("ast_rebound_current") == "authorized"


# =============================================================================
# 5. 空 session_id 走原逻辑；非空 id 无法识别 → fail-closed
# =============================================================================


def test_missing_session_id_returns_passthrough():
    assert general_tools._unattended_auto_approve_for(None) == "passthrough"
    assert general_tools._unattended_auto_approve_for("") == "passthrough"
    assert general_tools._unattended_auto_approve_for("   ") == "passthrough"


def test_unknown_session_id_rejects_fail_closed():
    """已有 root session id 但查不到行时不能退回进程级「全部允许」路径。"""
    decision = general_tools._unattended_auto_approve_for("ast_does_not_exist")
    assert decision == "reject_immediately"


@pytest.mark.parametrize("lookup_result", ["missing", "error"])
def test_unresolved_nonempty_session_cannot_use_process_auto_approve(
    monkeypatch,
    lookup_result,
):
    """非空 root session 识别失败时，即使全局已允许也必须立即拒绝。"""
    ask_calls: list[str] = []

    def _trap_ask(message, tool_name="unknown", **_kw):  # pragma: no cover - 不应被调
        ask_calls.append(message)
        return True

    if lookup_result == "missing":
        monkeypatch.setattr(SessionRepository, "get_by_id", lambda _repo, _sid: None)
    else:

        def _raise_lookup(_repo, _sid):
            raise RuntimeError("session store unavailable")

        monkeypatch.setattr(SessionRepository, "get_by_id", _raise_lookup)

    monkeypatch.setattr(general_tools, "_ask_user_confirm", _trap_ask)
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOP_TOGGLE)

    run_context.begin(f"ast_unresolved_{lookup_result}")
    try:
        result = general_tools._confirm_or_reject("write_file", "目标文件: protected.txt")
    finally:
        run_context.end()

    assert ask_calls == []
    assert result is not None
    assert result.error_code == "confirmation_failed_closed"


# =============================================================================
# 6. UnattendedConfirmationManager 增量刷新与全量重载
# =============================================================================


def test_manager_load_all_pulls_from_sqlite_unattended_flag():
    """``load_all`` 从 ``scheduled_tasks`` 全量拉 ``unattended_auto_approve=1`` 的 task id。"""
    from src.data.repos.scheduled_task_repository import ScheduledTaskRepository

    with ScheduledTaskRepository() as repo:
        repo.create(
            source_type="direct",
            source_ref="任务 1 指令",
            title="任务 1",
            schedule_kind="one_shot",
            schedule_payload={"run_at": "2026-07-19T10:00:00"},
            unattended_auto_approve=True,
        )
        repo.create(
            source_type="direct",
            source_ref="任务 2 指令",
            title="任务 2",
            schedule_kind="one_shot",
            schedule_payload={"run_at": "2026-07-19T11:00:00"},
            unattended_auto_approve=False,
        )
        repo.create(
            source_type="direct",
            source_ref="任务 3 指令",
            title="任务 3",
            schedule_kind="one_shot",
            schedule_payload={"run_at": "2026-07-19T12:00:00"},
            unattended_auto_approve=True,
        )

    # 重置 + reload
    reset_unattended_state(authorized=set())
    manager = get_unattended_confirmation_manager()
    assert manager.snapshot() == frozenset()

    manager.load_all()
    snapshot = manager.snapshot()
    # 恰好 2 个 authorized task（任务 1 + 任务 3），不含任务 2
    assert len(snapshot) == 2


def test_manager_set_incrementally_adds_and_discards():
    """``set`` 增量刷新（不必全量 reload），操作幂等。"""
    manager = get_unattended_confirmation_manager()
    assert manager.is_authorized("sch_incremental") is False

    manager.set("sch_incremental", True)
    assert manager.is_authorized("sch_incremental") is True
    # 幂等
    manager.set("sch_incremental", True)
    assert manager.is_authorized("sch_incremental") is True

    manager.set("sch_incremental", False)
    assert manager.is_authorized("sch_incremental") is False
    # 幂等
    manager.set("sch_incremental", False)
    assert manager.is_authorized("sch_incremental") is False


def test_manager_load_failure_clears_stale_authorizations_fail_closed():
    def _raise():
        raise RuntimeError("database unavailable")

    manager = reset_unattended_state(
        loader=_raise,
        authorized={"sch_stale_authorized"},
    )

    manager.load_all()

    assert manager.snapshot() == frozenset()


def test_manager_snapshot_is_isolated_copy():
    """snapshot 返回 frozenset 副本，外部 mutate 不影响内部授权集。"""
    manager = get_unattended_confirmation_manager()
    manager.set("sch_iso", True)
    snap = manager.snapshot()
    assert isinstance(snap, frozenset)
    assert "sch_iso" in snap

    # frozenset 本身不可变；测试 set() 的返回值类型即可
    assert manager.is_authorized("sch_iso") is True
