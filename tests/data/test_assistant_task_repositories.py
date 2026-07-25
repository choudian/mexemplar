from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.data.models_sqlite import AssistantTaskAttempt, AssistantTaskClaim, Base
from src.data.repos import (
    AssistantMeetingRepository,
    AssistantTaskAdjudicationRepository,
    AssistantTaskAttemptRepository,
    AssistantTaskClaimRepository,
    AssistantTaskOperationRepository,
    AssistantTaskQuestionRepository,
    AssistantTaskRepository,
    AssistantTodoRepository,
)
from src.utils.timezone import utc_now_naive


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_fence_does_not_overwrite_terminal_attempt(db_session) -> None:
    """fence() 只围栏活跃态 attempt；已 succeeded/failed 的 attempt 不得被覆盖回 fenced。

    防 recovery 扫描与 worker 完成的竞态：recovery 扫到过期 running attempt 进入 fence
    时，worker 可能已 complete_if_current 把它置 succeeded；fence 必须识别终态并返回
    None（未围栏），让 recovery 跳过，不能损坏已 succeeded 状态、不能递增 fence_token。
    """
    repo = AssistantTaskAttemptRepository(db_session)
    started = repo.start_attempt(
        task_id="tsk_fence",
        executor_type="ephemeral_subagent",
        executor_id="sub_fence",
        lease_owner="w",
        lease_expires_at=datetime.now() + timedelta(seconds=60),
        attempt_id="att_fence",
    )
    assert started is not None
    completed = repo.complete_if_current(
        attempt_id="att_fence", fence_token=started.fence_token, result_ref="ref"
    )
    assert completed is not None
    assert completed.status == "succeeded"

    fenced = repo.fence("att_fence")

    # 未围栏（返回 None），且不覆盖 succeeded、不递增 fence_token
    assert fenced is None
    after = repo.get_by_id("att_fence")
    assert after.status == "succeeded"
    assert after.fence_token == started.fence_token


def test_task_graph_repository_creates_tasks_edges_and_rejects_cycles(db_session) -> None:
    repo = AssistantTaskRepository(db_session)
    root = repo.create_task(
        graph_id="tg_1",
        session_id="ast_1",
        task_id="tsk_root",
        title="root",
        description="root task",
    )
    child = repo.create_task(
        graph_id="tg_1",
        session_id="ast_1",
        task_id="tsk_child",
        parent_task_id=root.task_id,
        title="child",
        description="child task",
    )
    edge = repo.add_edge(
        graph_id="tg_1",
        source_task_id=root.task_id,
        target_task_id=child.task_id,
        edge_type="delegation",
        propagation="blocking",
    )

    assert repo.get_current_graph_id("ast_1") == "tg_1"
    assert [task.task_id for task in repo.list_graph_tasks("tg_1")] == ["tsk_root", "tsk_child"]
    assert edge.edge_type == "delegation"
    with pytest.raises(ValueError):
        repo.add_edge(
            graph_id="tg_1",
            source_task_id=child.task_id,
            target_task_id=root.task_id,
            edge_type="dependency",
        )


def test_task_graph_repository_resolves_only_graphs_inside_run_message_window(
    db_session,
) -> None:
    repo = AssistantTaskRepository(db_session)
    repo.create_task(
        graph_id="tg_previous_run",
        session_id="ast_reused",
        task_id="tsk_previous_root",
        title="old",
        description="old",
        user_message_sequence=2,
    )
    repo.create_task(
        graph_id="tg_current_run",
        session_id="ast_reused",
        task_id="tsk_current_root",
        title="current",
        description="current",
        user_message_sequence=8,
    )

    known, graph_id = repo.resolve_graph_id_for_run(
        "ast_reused",
        after_sequence=5,
        started_at=datetime.now() - timedelta(minutes=1),
    )

    assert known is True
    assert graph_id == "tg_current_run"


def test_task_graph_repository_fails_closed_for_unscoped_graph_created_during_run(
    db_session,
) -> None:
    repo = AssistantTaskRepository(db_session)
    started_at = utc_now_naive() - timedelta(minutes=1)
    repo.create_task(
        graph_id="tg_unknown_owner",
        session_id="ast_reused",
        task_id="tsk_unknown_root",
        title="unknown",
        description="unknown",
        user_message_sequence=None,
    )

    known, graph_id = repo.resolve_graph_id_for_run(
        "ast_reused",
        after_sequence=5,
        started_at=started_at,
    )

    assert known is False
    assert graph_id is None


def test_task_graph_repository_exposes_root_message_sequence_for_run_mapping(
    db_session,
) -> None:
    repo = AssistantTaskRepository(db_session)
    repo.create_task(
        graph_id="tg_owned",
        session_id="ast_owned",
        task_id="tsk_owned_root",
        title="owned",
        description="owned",
        user_message_sequence=12,
    )

    assert repo.get_graph_user_message_sequence("tg_owned") == 12
    assert repo.get_graph_user_message_sequence("tg_missing") is None


def test_repository_detects_nonterminal_execution_nodes_by_session(db_session) -> None:
    repo = AssistantTaskRepository(db_session)
    root = repo.create_task(
        task_id="tsk_root_terminal_scan",
        graph_id="graph_terminal_scan",
        session_id="ast_terminal_scan",
        title="root",
        description="root",
        status="running",
    )
    child = repo.create_task(
        task_id="tsk_child_terminal_scan",
        graph_id="graph_terminal_scan",
        session_id="ast_terminal_scan",
        title="child",
        description="child",
        parent_task_id=root.task_id,
        root_task_id=root.task_id,
        status="running",
    )

    assert repo.has_nonterminal_execution_tasks("ast_terminal_scan") is True

    repo.update_status(child.task_id, status="completed")

    # Root is a container and may remain nonterminal for mixed-result graphs.
    assert repo.has_nonterminal_execution_tasks("ast_terminal_scan") is False


def test_attempt_operation_question_adjudication_claim_meeting_and_todo_repositories(
    db_session,
) -> None:
    task_repo = AssistantTaskRepository(db_session)
    task_repo.create_task(
        graph_id="tg_2",
        session_id="ast_2",
        task_id="tsk_2",
        title="task",
        description="description",
    )
    attempt_repo = AssistantTaskAttemptRepository(db_session)
    lease = datetime.now() + timedelta(minutes=5)
    attempt = attempt_repo.start_attempt(
        task_id="tsk_2",
        executor_type="ephemeral_subagent",
        executor_id="sub_1",
        lease_owner="worker_1",
        lease_expires_at=lease,
        attempt_id="att_1",
    )
    assert attempt is not None
    assert (
        attempt_repo.start_attempt(
            task_id="tsk_2",
            executor_type="specialist",
            executor_id="spec_1",
            lease_owner="worker_2",
            lease_expires_at=lease,
        )
        is None
    )
    assert (
        attempt_repo.complete_if_current(
            attempt_id="att_1",
            fence_token=99,
            result_ref="late",
        )
        is None
    )

    operation_repo = AssistantTaskOperationRepository(db_session)
    operation = operation_repo.record_planned(
        task_id="tsk_2",
        attempt_id="att_1",
        operation_key="write:file",
        operation_type="file_write",
        safe_summary="write file",
    )
    operation_repo.update_status(operation.operation_id, "completed", result_ref="ref_1")
    with pytest.raises(IntegrityError):
        operation_repo.record_planned(
            task_id="tsk_2",
            attempt_id="att_1",
            operation_key="write:file",
            operation_type="file_write",
            safe_summary="duplicate",
        )
    db_session.rollback()

    question_repo = AssistantTaskQuestionRepository(db_session)
    question = question_repo.create_question(
        graph_id="tg_2",
        task_id="tsk_2",
        asker_type="ephemeral_subagent",
        asker_id="sub_1",
        kind="resource_request",
        question_text="need file",
    )
    assert question_repo.update_status(
        question.question_id, "answered", safe_answer_summary="granted"
    )
    assert question_repo.list_open_for_task("tsk_2") == []

    adjudication_repo = AssistantTaskAdjudicationRepository(db_session)
    adjudication = adjudication_repo.create_pending(
        task_id="tsk_2",
        graph_id="tg_2",
        parent_session_id="ast_2",
        delivered_status="done",
        safe_summary="done",
    )
    assert adjudication_repo.get_pending_for_task("tsk_2") == adjudication
    assert adjudication_repo.decide(
        adjudication.adjudication_id,
        decision="accepted",
        decided_by="agent",
    )

    claim_repo = AssistantTaskClaimRepository(db_session)
    claim = claim_repo.create_claim(
        task_id="tsk_2",
        claimer_type="specialist",
        claimer_id="spec_1",
        task_version=1,
        lease_expires_at=lease,
    )
    assert claim_repo.update_status(claim.claim_id, "released")

    meeting_repo = AssistantMeetingRepository(db_session)
    channel = meeting_repo.create_channel(
        graph_id="tg_2",
        parent_task_id="tsk_2",
        supervisor_session_id="ast_2",
        participant_a_type="specialist",
        participant_a_id="spec_a",
        participant_b_type="specialist",
        participant_b_id="spec_b",
        turn_budget=12,
        time_budget_seconds=900,
    )
    message = meeting_repo.add_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="spec_a",
        content="hello",
    )
    assert message.sequence == 1
    assert len(meeting_repo.list_messages(channel.channel_id)) == 1

    todo_repo = AssistantTodoRepository(db_session)
    items = todo_repo.replace_for_executor(
        task_id="tsk_2",
        executor_type="specialist",
        executor_id="spec_1",
        items=[{"todo_id": "todo_1", "text": "step", "status": "done", "sort_order": 1}],
    )
    assert items[0].completed_at is not None


def test_start_attempt_enforces_executor_capacity_one(db_session) -> None:
    # FR-003 / plan Dispatch and Concurrency Model：单个执行者一次只执行一件任务
    # （容量=1）。同一 executor 已持有 active attempt 时，不得在另一个任务上再起
    # attempt；需要更多并行只能由别的 executor 承接。
    task_repo = AssistantTaskRepository(db_session)
    for tid in ("tsk_cap_a", "tsk_cap_b"):
        task_repo.create_task(
            graph_id="tg_cap",
            session_id="ast_cap",
            task_id=tid,
            title="task",
            description="description",
        )
    attempt_repo = AssistantTaskAttemptRepository(db_session)
    lease = datetime.now() + timedelta(minutes=5)
    busy = attempt_repo.start_attempt(
        task_id="tsk_cap_a",
        executor_type="specialist",
        executor_id="spec_busy",
        lease_owner="worker_1",
        lease_expires_at=lease,
    )
    assert busy is not None
    assert (
        attempt_repo.start_attempt(
            task_id="tsk_cap_b",
            executor_type="specialist",
            executor_id="spec_busy",
            lease_owner="worker_2",
            lease_expires_at=lease,
        )
        is None
    )
    other = attempt_repo.start_attempt(
        task_id="tsk_cap_b",
        executor_type="ephemeral_subagent",
        executor_id="sub_free",
        lease_owner="worker_3",
        lease_expires_at=lease,
    )
    assert other is not None


def test_claim_unique_index_blocks_second_active_per_claimer(db_session) -> None:
    # DB 层兜底看板 claimer capacity=1：应用层 has_active_claim 在并发窗口外读取，
    # 可能被两笔并发认领同时绕过；partial unique index 必须拒绝第二个 claimed。
    task_repo = AssistantTaskRepository(db_session)
    for tid in ("tsk_claim_a", "tsk_claim_b"):
        task_repo.create_task(
            graph_id="tg_claim_uq",
            session_id="ast_claim_uq",
            task_id=tid,
            title="task",
            description="description",
        )
    claim_repo = AssistantTaskClaimRepository(db_session)
    lease = datetime.now() + timedelta(minutes=5)
    claim_repo._add_and_flush(
        AssistantTaskClaim(
            claim_id="clm_active_a",
            task_id="tsk_claim_a",
            claimer_type="specialist",
            claimer_id="sp_busy",
            status="claimed",
            lease_expires_at=lease,
            task_version=1,
        )
    )
    with pytest.raises(IntegrityError):
        claim_repo._add_and_flush(
            AssistantTaskClaim(
                claim_id="clm_active_b",
                task_id="tsk_claim_b",
                claimer_type="specialist",
                claimer_id="sp_busy",
                status="claimed",
                lease_expires_at=lease,
                task_version=1,
            )
        )


def _make_attempt(
    *,
    attempt_id: str,
    task_id: str,
    executor_type: str = "specialist",
    executor_id: str = "sp_1",
    status: str = "running",
) -> AssistantTaskAttempt:
    now = datetime.now()
    return AssistantTaskAttempt(
        attempt_id=attempt_id,
        task_id=task_id,
        executor_type=executor_type,
        executor_id=executor_id,
        status=status,
        lease_owner="worker",
        lease_expires_at=now + timedelta(minutes=5),
        heartbeat_at=now,
        started_at=now,
    )


def test_attempt_unique_index_blocks_second_active_per_task(db_session) -> None:
    # DB 层 partial unique index 兜底 capacity=1：应用层 read-check-write 在并发下
    # 可能双双通过 active=None 守卫，DB unique 是最后防线——同一 task 下不允许两个
    # active（starting/running）attempt。直接插入以测约束本身（绕过应用层 read）。
    task_repo = AssistantTaskRepository(db_session)
    task_repo.create_task(
        graph_id="tg_uq_task",
        session_id="ast_uq",
        task_id="tsk_uq_task",
        title="t",
        description="d",
    )
    attempt_repo = AssistantTaskAttemptRepository(db_session)
    attempt_repo._add_and_flush(_make_attempt(attempt_id="att_a", task_id="tsk_uq_task"))
    with pytest.raises(IntegrityError):
        attempt_repo._add_and_flush(
            _make_attempt(
                attempt_id="att_b",
                task_id="tsk_uq_task",
                executor_id="sp_other",  # 不同 executor，同 task 仍应被拒
            )
        )


def test_attempt_unique_index_blocks_second_active_per_executor(db_session) -> None:
    # 同一 executor 不允许两个 active attempt（即便在不同 task 上）——executor
    # capacity=1 的 DB 层兜底。
    task_repo = AssistantTaskRepository(db_session)
    for tid in ("tsk_uq_e1", "tsk_uq_e2"):
        task_repo.create_task(
            graph_id="tg_uq_exec",
            session_id="ast_uq",
            task_id=tid,
            title="t",
            description="d",
        )
    attempt_repo = AssistantTaskAttemptRepository(db_session)
    attempt_repo._add_and_flush(
        _make_attempt(attempt_id="att_e1", task_id="tsk_uq_e1", executor_id="sp_dup")
    )
    with pytest.raises(IntegrityError):
        attempt_repo._add_and_flush(
            _make_attempt(attempt_id="att_e2", task_id="tsk_uq_e2", executor_id="sp_dup")
        )


def test_paused_attempt_does_not_hold_capacity_slot(db_session) -> None:
    # I3：暂停即释放执行者槽。paused 不再算 active，不占 per-task / per-executor 名额——
    # 续跑（continue_graph → pending_dispatch → 新 start_attempt）才能为同一 task/executor 开
    # 新 attempt。修复前 paused 在 ACTIVE_STATUSES 里，旧 paused 会撞唯一索引把续跑挡死。
    task_repo = AssistantTaskRepository(db_session)
    task_repo.create_task(
        graph_id="tg_pause_slot",
        session_id="ast_pause",
        task_id="tsk_pause_slot",
        title="t",
        description="d",
    )
    attempt_repo = AssistantTaskAttemptRepository(db_session)
    lease = datetime.now() + timedelta(minutes=5)
    first = attempt_repo.start_attempt(
        task_id="tsk_pause_slot",
        executor_type="specialist",
        executor_id="sp_pause",
        lease_owner="w1",
        lease_expires_at=lease,
    )
    assert first is not None
    paused = attempt_repo.pause_if_current(
        attempt_id=first.attempt_id, fence_token=first.fence_token
    )
    assert paused is not None and paused.status == "paused"
    # 同一 task + 同一 executor 续跑：新 attempt 不应被旧 paused 的唯一索引/容量守卫挡住
    resumed = attempt_repo.start_attempt(
        task_id="tsk_pause_slot",
        executor_type="specialist",
        executor_id="sp_pause",
        lease_owner="w2",
        lease_expires_at=lease,
    )
    assert resumed is not None
    assert resumed.attempt_id != first.attempt_id


def test_attempt_unique_index_allows_new_active_after_terminal(db_session) -> None:
    # 终态（succeeded/failed/cancelled/fenced）attempt 不占 active 名额——
    # sqlite_where 把 unique 限制在 active 状态，旧终态行不阻塞新 active。
    task_repo = AssistantTaskRepository(db_session)
    task_repo.create_task(
        graph_id="tg_uq_term",
        session_id="ast_uq",
        task_id="tsk_uq_term",
        title="t",
        description="d",
    )
    attempt_repo = AssistantTaskAttemptRepository(db_session)
    attempt_repo._add_and_flush(
        _make_attempt(attempt_id="att_old", task_id="tsk_uq_term", status="succeeded")
    )
    new_active = attempt_repo._add_and_flush(
        _make_attempt(attempt_id="att_new", task_id="tsk_uq_term", executor_id="sp_new")
    )
    assert new_active is not None


def test_fenced_attempt_does_not_hold_capacity_slot(db_session) -> None:
    # D1：崩溃围栏（fence）释放执行者容量槽。同步子树崩溃后专员的 fenced attempt 不再算
    # active，不占 per-executor 名额，该 executor 可在新任务上起新 active attempt
    # （与 paused/terminal 同语义；fence 是崩溃恢复路径，专员占用必须随之释放）。
    task_repo = AssistantTaskRepository(db_session)
    task_repo.create_task(
        graph_id="tg_fence_slot",
        session_id="ast_fence",
        task_id="tsk_fence_slot_a",
        title="t",
        description="d",
    )
    attempt_repo = AssistantTaskAttemptRepository(db_session)
    lease = datetime.now() + timedelta(minutes=5)
    first = attempt_repo.start_attempt(
        task_id="tsk_fence_slot_a",
        executor_type="specialist",
        executor_id="sp_fence",
        lease_owner="w1",
        lease_expires_at=lease,
    )
    assert first is not None
    fenced = attempt_repo.fence(first.attempt_id)
    assert fenced is not None and fenced.status == "fenced"
    # fenced 后，同一 executor 在新 task 上起新 active attempt（per-executor 容量槽已释放）
    task_repo.create_task(
        graph_id="tg_fence_slot",
        session_id="ast_fence",
        task_id="tsk_fence_slot_b",
        title="t2",
        description="d2",
    )
    new_active = attempt_repo.start_attempt(
        task_id="tsk_fence_slot_b",
        executor_type="specialist",
        executor_id="sp_fence",
        lease_owner="w2",
        lease_expires_at=lease,
    )
    assert new_active is not None
    assert new_active.attempt_id != first.attempt_id


def test_renew_lease_extends_an_active_attempt(db_session) -> None:
    """续租把到期时间往后推，让还在干活的执行体不被恢复扫描判死。

    租约原本只在创建时写死，此后无人续约：执行体只要跑得比租约长就会被判死并
    重新派发，而它其实还活着——重派只会又起一个。
    """
    repo = AssistantTaskAttemptRepository(db_session)
    original_expiry = datetime.now() + timedelta(seconds=60)
    started = repo.start_attempt(
        task_id="tsk_renew",
        executor_type="specialist",
        executor_id="spec_renew",
        lease_owner="w",
        lease_expires_at=original_expiry,
        attempt_id="att_renew",
    )
    assert started is not None
    extended = original_expiry + timedelta(seconds=300)

    assert repo.renew_lease("att_renew", lease_expires_at=extended) is True

    after = repo.get_by_id("att_renew")
    assert after.lease_expires_at > original_expiry
    assert after.status == started.status
    assert after.fence_token == started.fence_token


def test_renew_lease_refuses_to_revive_a_terminal_attempt(db_session) -> None:
    """终态 attempt 不得被续租复活。

    续租跑在执行线程，围栏和终态写入在别的连接上；ORM 的 read-check-write 会盲写
    覆盖，把已经交出所有权的 attempt 又标成有租约的活跃态。守卫必须进 SQL。
    """
    repo = AssistantTaskAttemptRepository(db_session)
    started = repo.start_attempt(
        task_id="tsk_renew_terminal",
        executor_type="specialist",
        executor_id="spec_renew_terminal",
        lease_owner="w",
        lease_expires_at=datetime.now() + timedelta(seconds=60),
        attempt_id="att_renew_terminal",
    )
    assert started is not None
    repo.complete_if_current(
        attempt_id="att_renew_terminal", fence_token=started.fence_token, result_ref="ref"
    )

    renewed = repo.renew_lease(
        "att_renew_terminal", lease_expires_at=datetime.now() + timedelta(seconds=600)
    )

    assert renewed is False
    assert repo.get_by_id("att_renew_terminal").status == "succeeded"


def test_renew_lease_refuses_a_fenced_attempt(db_session) -> None:
    # Recovery already handed the task to someone else; renewing here would put
    # two executors on the same work.
    repo = AssistantTaskAttemptRepository(db_session)
    started = repo.start_attempt(
        task_id="tsk_renew_fenced",
        executor_type="specialist",
        executor_id="spec_renew_fenced",
        lease_owner="w",
        lease_expires_at=datetime.now() + timedelta(seconds=60),
        attempt_id="att_renew_fenced",
    )
    assert started is not None
    repo.fence("att_renew_fenced")

    assert (
        repo.renew_lease(
            "att_renew_fenced", lease_expires_at=datetime.now() + timedelta(seconds=600)
        )
        is False
    )


def test_renew_lease_on_a_missing_attempt_is_a_no_op(db_session) -> None:
    repo = AssistantTaskAttemptRepository(db_session)

    assert (
        repo.renew_lease("att_nonexistent", lease_expires_at=datetime.now()) is False
    )
