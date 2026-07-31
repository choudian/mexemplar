from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.task_collaboration.models import SuspendReason
from src.business.task_collaboration.recovery import TaskRecoveryService
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.models_sqlite import Base
from src.data.repos import (
    AssistantTaskAdjudicationRepository,
    AssistantTaskAttemptRepository,
    AssistantTaskRepository,
)


def test_recovery_fences_expired_attempt_and_requeues_task() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        task_repo = AssistantTaskRepository(session)
        task = task_repo.create_task(
            graph_id="tg_1",
            session_id="ast_1",
            task_id="tsk_1",
            title="task",
            description="task",
            owner_session_id="ast_1",
            status="running",
        )
        attempt_repo = AssistantTaskAttemptRepository(session)
        attempt = attempt_repo.start_attempt(
            task_id=task.task_id,
            executor_type="ephemeral_subagent",
            executor_id="sub_1",
            lease_owner="worker_1",
            lease_expires_at=datetime.now() - timedelta(seconds=1),
            attempt_id="att_1",
        )
        assert attempt is not None
        adjudication_repo = AssistantTaskAdjudicationRepository(session)
        service = TaskRecoveryService(
            attempt_repo=attempt_repo,
            task_repo=task_repo,
            adjudication_repo=adjudication_repo,
        )

        assert service.fence_expired_attempts(datetime.now()) == 1
        assert attempt_repo.get_by_id("att_1").status == "fenced"
        recovered_task = task_repo.get_task("tsk_1")
        assert recovered_task.status == "pending_dispatch"
        assert recovered_task.suspend_reason is None
        assert adjudication_repo.get_pending_for_task("tsk_1") is None
    finally:
        session.close()
        engine.dispose()


def test_recovery_resumes_checkpoint_attempt_without_parent_adjudication() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        task_repo = AssistantTaskRepository(session)
        task = task_repo.create_task(
            graph_id="tg_resume",
            session_id="ast_resume",
            task_id="tsk_resume",
            title="task",
            description="task",
            owner_session_id="ast_resume",
            assignee_type="specialist",
            assignee_id="sp_resume",
            status="running",
        )
        attempt_repo = AssistantTaskAttemptRepository(session)
        checkpoint_ref = '{"subagent_id":"child_resume"}'
        attempt_repo.start_attempt(
            task_id=task.task_id,
            executor_type="specialist",
            executor_id="sp_resume",
            lease_owner="worker_1",
            lease_expires_at=datetime.now() - timedelta(seconds=1),
            attempt_id="att_resume",
            checkpoint_ref=checkpoint_ref,
        )
        adjudication_repo = AssistantTaskAdjudicationRepository(session)
        resume_calls: list[tuple[str, str]] = []
        service = TaskRecoveryService(
            attempt_repo=attempt_repo,
            task_repo=task_repo,
            adjudication_repo=adjudication_repo,
            resume_callback=lambda task_id, ref: resume_calls.append((task_id, ref)) or True,
        )

        assert service.fence_expired_attempts(datetime.now()) == 1

        assert resume_calls == [(task.task_id, checkpoint_ref)]
        assert attempt_repo.get_by_id("att_resume").status == "fenced"
        recovered_task = task_repo.get_task(task.task_id)
        assert recovered_task.status == "pending_dispatch"
        assert recovered_task.suspend_reason is None
        assert adjudication_repo.get_pending_for_task(task.task_id) is None
    finally:
        session.close()
        engine.dispose()


def test_recovery_requeues_when_checkpoint_resume_fails() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        task_repo = AssistantTaskRepository(session)
        task = task_repo.create_task(
            graph_id="tg_resume_fail",
            session_id="ast_resume_fail",
            task_id="tsk_resume_fail",
            title="task",
            description="task",
            owner_session_id="ast_resume_fail",
            assignee_type="specialist",
            assignee_id="sp_resume",
            status="running",
        )
        attempt_repo = AssistantTaskAttemptRepository(session)
        attempt_repo.start_attempt(
            task_id=task.task_id,
            executor_type="specialist",
            executor_id="sp_resume",
            lease_owner="worker_1",
            lease_expires_at=datetime.now() - timedelta(seconds=1),
            attempt_id="att_resume_fail",
            checkpoint_ref='{"subagent_id":"child_resume"}',
        )
        adjudication_repo = AssistantTaskAdjudicationRepository(session)
        service = TaskRecoveryService(
            attempt_repo=attempt_repo,
            task_repo=task_repo,
            adjudication_repo=adjudication_repo,
            resume_callback=lambda _task_id, _ref: False,
        )

        assert service.fence_expired_attempts(datetime.now()) == 1

        recovered_task = task_repo.get_task(task.task_id)
        assert recovered_task.status == "pending_dispatch"
        assert recovered_task.suspend_reason is None
        assert adjudication_repo.get_pending_for_task(task.task_id) is None
    finally:
        session.close()
        engine.dispose()


def test_recovery_skips_terminal_task_and_continues_loop() -> None:
    """单个 attempt 对应终态 task 时不得中止整个恢复循环，且终态 task 不被翻回可派发。

    修复前：终态 task 的 validate_task_transition 抛 ValueError，recovery for 循环无
    per-iteration try/except → 异常传播中止循环，后续 attempt 永远不被处理；且即使不抛，
    update_status 也会把已 cancelled 的 task 错翻成 pending_dispatch。cancel_graph 只 transition
    task 不 fence 子 attempt，worker 仍在跑 → lease 过期 → recovery 扫到终态 task 是真实路径。
    """
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        task_repo = AssistantTaskRepository(session)
        task_a = task_repo.create_task(
            graph_id="tg_rc",
            session_id="ast_rc",
            task_id="tsk_a",
            title="a",
            description="a",
            owner_session_id="ast_rc",
            status="running",
        )
        task_repo.update_status(task_a.task_id, status="cancelled")
        task_b = task_repo.create_task(
            graph_id="tg_rc",
            session_id="ast_rc",
            task_id="tsk_b",
            title="b",
            description="b",
            owner_session_id="ast_rc",
            status="running",
        )
        attempt_repo = AssistantTaskAttemptRepository(session)
        attempt_repo.start_attempt(
            task_id=task_a.task_id,
            executor_type="ephemeral_subagent",
            executor_id="sub_a",
            lease_owner="w",
            lease_expires_at=datetime.now() - timedelta(seconds=1),
            attempt_id="att_a",
        )
        attempt_repo.start_attempt(
            task_id=task_b.task_id,
            executor_type="ephemeral_subagent",
            executor_id="sub_b",
            lease_owner="w",
            lease_expires_at=datetime.now() - timedelta(seconds=1),
            attempt_id="att_b",
        )
        adjudication_repo = AssistantTaskAdjudicationRepository(session)
        service = TaskRecoveryService(
            attempt_repo=attempt_repo,
            task_repo=task_repo,
            adjudication_repo=adjudication_repo,
        )

        count = service.fence_expired_attempts(datetime.now())

        # task A 终态被跳过（不翻回可派发、不建裁定），task B 正常恢复；循环未中断
        assert count == 1
        assert attempt_repo.get_by_id("att_a").status == "fenced"
        assert attempt_repo.get_by_id("att_b").status == "fenced"
        assert task_repo.get_task("tsk_a").status == "cancelled"
        assert adjudication_repo.get_pending_for_task("tsk_a") is None
        assert task_repo.get_task("tsk_b").status == "pending_dispatch"
        assert task_repo.get_task("tsk_b").suspend_reason is None
        assert adjudication_repo.get_pending_for_task("tsk_b") is None
    finally:
        session.close()
        engine.dispose()


def test_stop_continue_and_cancel_graph_transitions() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        task_repo = AssistantTaskRepository(session)
        adjudication_repo = AssistantTaskAdjudicationRepository(session)
        service = TaskCollaborationService(
            task_repo=task_repo,
            adjudication_repo=adjudication_repo,
        )
        graph_id = service.create_root_graph(
            session_id="ast_stop",
            title="root",
            description="root",
        )
        root = task_repo.list_graph_tasks(graph_id)[0]
        child_id = service.create_child_task(
            graph_id=graph_id,
            session_id="ast_stop",
            parent_task_id=root.task_id,
            title="child",
            description="child",
        )
        service.update_task_status(task_id=child_id, status="running")

        assert service.stop_graph(session_id="ast_stop", graph_id=graph_id) == 2
        stopped = {task.task_id: task for task in task_repo.list_graph_tasks(graph_id)}
        assert stopped[root.task_id].status == "suspended"
        assert stopped[root.task_id].suspend_reason == "user_stop"
        assert stopped[child_id].status == "suspended"

        assert service.continue_graph(session_id="ast_stop", graph_id=graph_id) == 2
        resumed = {task.task_id: task for task in task_repo.list_graph_tasks(graph_id)}
        assert resumed[root.task_id].status == "pending_dispatch"
        assert resumed[child_id].status == "pending_dispatch"

        assert service.cancel_graph(session_id="ast_stop", graph_id=graph_id) == 2
        cancelled = {task.task_id: task for task in task_repo.list_graph_tasks(graph_id)}
        assert cancelled[root.task_id].status == "cancelled"
        assert cancelled[child_id].status == "cancelled"
    finally:
        session.close()
        engine.dispose()


def test_stop_graph_is_isolated_to_its_own_session() -> None:
    # FR-011：停止只作用于本会话本图。用 A 的 session 去停 B 的图必须拒绝，
    # 不得误停其他会话/其他请求的任务图。
    service = TaskCollaborationService()
    graph_a = service.create_root_graph(session_id="ast_A", title="A", description="A")
    graph_b = service.create_root_graph(session_id="ast_B", title="B", description="B")

    with pytest.raises(LookupError):
        service.stop_graph(session_id="ast_A", graph_id=graph_b)
    snap_b = service.get_graph_snapshot(session_id="ast_B", graph_id=graph_b)
    assert all(task.status == "pending_dispatch" for task in snap_b.tasks)

    # 停 A 自己的图只影响 A，B 会话的图状态不变
    assert service.stop_graph(session_id="ast_A", graph_id=graph_a) >= 1
    snap_b_after = service.get_graph_snapshot(session_id="ast_B", graph_id=graph_b)
    assert all(task.status == "pending_dispatch" for task in snap_b_after.tasks)


def test_create_child_task_enforces_bounded_delegation_depth() -> None:
    # FR-023：拓扑封顶为 枢纽(0)+一级(1)+专员单个子代理(2)；深度 2 的任务不得再有子任务
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(session_id="ast_depth", title="root", description="root")
    root = AssistantTaskRepository().list_graph_tasks(graph_id)[0]
    l1 = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_depth",
        parent_task_id=root.task_id,
        title="l1",
        description="l1",
    )
    l2 = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_depth",
        parent_task_id=l1,
        title="l2",
        description="l2",
    )

    with pytest.raises(ValueError):
        service.create_child_task(
            graph_id=graph_id,
            session_id="ast_depth",
            parent_task_id=l2,
            title="l3",
            description="l3",
        )


def test_cancelled_task_cannot_be_revived_by_replan() -> None:
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_cancel",
        title="root",
        description="root",
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    service.cancel_graph(session_id="ast_cancel", graph_id=graph_id)

    with pytest.raises(ValueError):
        service.update_task_status(task_id=root.task_id, status="pending_dispatch")


def test_create_child_task_rejects_cancelled_parent() -> None:
    """FR-011 / plan：replan 不得在已取消的 parent 下建子任务——被取消方向是终态、不复活。

    cancel_graph 是图级取消（cascade 所有非终态任务），取消后在已取消的子任务下建孙任务
    必须被 create_child_task 的祖先取消校验拒绝，不能让 late planning 复活被取消的方向。
    """
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_cancel_parent",
        title="root",
        description="root",
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    child_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_cancel_parent",
        parent_task_id=root.task_id,
        title="child",
        description="child",
    )
    service.cancel_graph(session_id="ast_cancel_parent", graph_id=graph_id)

    with pytest.raises(ValueError):
        service.create_child_task(
            graph_id=graph_id,
            session_id="ast_cancel_parent",
            parent_task_id=child_id,
            title="grandchild",
            description="grandchild",
        )


def test_create_child_task_rejects_cancelled_root() -> None:
    """FR-011 / plan：root 已取消时，即便直接 parent 未被取消也不得建子任务。

    防御性覆盖 root 祖先校验：手动把 root 翻成 CANCELLED（不走 cascade，故 child 仍是
    pending_dispatch），在未取消的 child 下建孙任务仍须因 root 取消被拒。
    """
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_cancel_root",
        title="root",
        description="root",
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    child_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_cancel_root",
        parent_task_id=root.task_id,
        title="child",
        description="child",
    )
    # 只翻 root，不 cascade——child 仍是 pending_dispatch，确保走到的是 root 祖先校验
    service.update_task_status(task_id=root.task_id, status="cancelled")

    with pytest.raises(ValueError):
        service.create_child_task(
            graph_id=graph_id,
            session_id="ast_cancel_root",
            parent_task_id=child_id,
            title="grandchild",
            description="grandchild",
        )


def test_cancel_graph_rejects_version_mismatch() -> None:
    """C1: cancel_graph() MUST reject when expected_graph_version doesn't match current."""
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_ver",
        title="root",
        description="root",
    )
    # 正常取消——版本匹配
    snapshot = service.get_graph_snapshot(session_id="ast_ver", graph_id=graph_id)
    assert snapshot is not None
    service.cancel_graph(
        session_id="ast_ver",
        graph_id=graph_id,
        expected_graph_version=snapshot.version,
    )

    # 创建新图，版本不匹配时应拒绝
    graph_id_2 = service.create_root_graph(
        session_id="ast_ver2",
        title="root2",
        description="root2",
    )
    with pytest.raises(ValueError, match="graph version mismatch"):
        service.cancel_graph(
            session_id="ast_ver2",
            graph_id=graph_id_2,
            expected_graph_version=9999,  # 不可能匹配的版本号
        )


def test_cancel_graph_succeeds_with_correct_version() -> None:
    """C1: cancel_graph() succeeds when expected_graph_version matches."""
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_ver_ok",
        title="root",
        description="root",
    )
    snapshot = service.get_graph_snapshot(session_id="ast_ver_ok", graph_id=graph_id)
    assert snapshot is not None
    cancelled = service.cancel_graph(
        session_id="ast_ver_ok",
        graph_id=graph_id,
        expected_graph_version=snapshot.version,
    )
    assert cancelled >= 1


def test_graph_version_increments_on_child_creation() -> None:
    """FR-011：add_edge（create_child_task）递增 graph_version，让 cancel 围栏真正生效。

    修复前 graph_version 恒为 1，cancel 的版本校验形同虚设，并发 replan 插入的新下游
    会带着旧快照的 expected_graph_version 顺利取消。
    """
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_ver_inc",
        title="root",
        description="root",
    )
    root_snapshot = service.get_graph_snapshot(session_id="ast_ver_inc", graph_id=graph_id)
    assert root_snapshot is not None
    version_before = root_snapshot.version
    root_task_id = root_snapshot.tasks[0].task_id

    service.create_child_task(
        graph_id=graph_id,
        session_id="ast_ver_inc",
        parent_task_id=root_task_id,
        title="child",
        description="child",
    )
    after_child = service.get_graph_snapshot(session_id="ast_ver_inc", graph_id=graph_id)
    assert after_child is not None
    # 加下游（replan）后版本必须递增，否则旧快照的 expected_graph_version 仍能取消新结构
    assert after_child.version > version_before

    # 用旧版本取消必须被拒绝：防止并发 replan 插入的新下游逃过取消波
    with pytest.raises(ValueError, match="graph version mismatch"):
        service.cancel_graph(
            session_id="ast_ver_inc",
            graph_id=graph_id,
            expected_graph_version=version_before,
        )


def test_continue_graph_does_not_resume_waiting_user_tasks() -> None:
    """continue_graph 只恢复 user_stop 暂停的任务，不恢复 waiting_user 暂停的任务。

    waiting_user 表示任务在等待用户明确信号，不应被 continue 自动恢复。
    """
    service = TaskCollaborationService()
    try:
        graph_id = service.create_root_graph(
            session_id="ast_wu",
            title="root",
            description="root",
        )
        root = service._tasks.list_graph_tasks(graph_id)[0]
        # 手动将任务设为 running 再 suspended + waiting_user
        service.update_task_status(task_id=root.task_id, status="running")
        service.update_task_status(
            task_id=root.task_id, status="suspended", suspend_reason="waiting_user"
        )

        # continue_graph 应该不恢复 waiting_user 暂停的任务
        resumed = service.continue_graph(session_id="ast_wu", graph_id=graph_id)
        assert resumed == 0
        task_after = service._tasks.get_task(root.task_id)
        assert task_after.status == "suspended"
        assert task_after.suspend_reason == "waiting_user"
    finally:
        service.close()


def test_continue_graph_does_not_resume_a_task_blocked_by_a_defect() -> None:
    """撞上程序缺陷的活，"继续"推不动它——代码不改，重试多少次都是同一个错。

    放行的后果是把"主助理重试 7 次"那个循环原样搬给用户手动重复：点继续 →
    派活 → 立刻撞同样的错 → 又停 → 再点。烧的是他的耐心。那种活该给的是
    跳过 / 放弃，不是继续。
    """
    service = TaskCollaborationService()
    try:
        graph_id = service.create_root_graph(
            session_id="ast_defect",
            title="root",
            description="root",
        )
        root = service._tasks.list_graph_tasks(graph_id)[0]
        service.update_task_status(task_id=root.task_id, status="running")
        service.update_task_status(
            task_id=root.task_id,
            status="suspended",
            suspend_reason=SuspendReason.BLOCKED_BY_DEFECT,
        )

        resumed = service.continue_graph(session_id="ast_defect", graph_id=graph_id)

        assert resumed == 0
        task_after = service._tasks.get_task(root.task_id)
        assert task_after.status == "suspended"
        assert task_after.suspend_reason == "blocked_by_defect"
        # 球在主助理手上：它去做绕行决定，不是用户去点继续
        assert task_after.waiting_on == "assistant"
    finally:
        service.close()


def test_continue_graph_still_resumes_everything_that_can_actually_move() -> None:
    """排除是逐条加的，别把"默认放行"改回"白名单"——那正是旧 bug 的形状。"""
    resumable = (
        SuspendReason.USER_STOP,
        SuspendReason.BUDGET_EXHAUSTED,
        SuspendReason.WAITING_SYSTEM,
        SuspendReason.INTERRUPTED,
    )
    for reason in resumable:
        service = TaskCollaborationService()
        try:
            session_id = f"ast_resume_{reason.value}"
            graph_id = service.create_root_graph(
                session_id=session_id, title="root", description="root"
            )
            root = service._tasks.list_graph_tasks(graph_id)[0]
            service.update_task_status(task_id=root.task_id, status="running")
            service.update_task_status(
                task_id=root.task_id, status="suspended", suspend_reason=reason
            )

            assert service.continue_graph(session_id=session_id, graph_id=graph_id) == 1, reason
        finally:
            service.close()
