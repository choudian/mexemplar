from __future__ import annotations

from datetime import datetime, timedelta

from src.business.task_collaboration.board import TaskBoardService
from src.data.repos import AssistantTaskClaimRepository, AssistantTaskRepository
from src.utils.timezone import utc_now_naive


class _FallbackConfig:
    def get_assistant_tasks_board_fallback_seconds(self) -> int:
        return 10

    def get_assistant_tasks_board_capacity(self) -> int:
        return 10

    def get_assistant_tasks_attempt_lease_seconds(self) -> int:
        return 60

    def get_assistant_tasks_recruitment_min_fallback_count(self) -> int:
        return 1


def _open_task(task_id: str = "tsk_board"):
    return AssistantTaskRepository().create_task(
        graph_id="tg_board",
        session_id="ast_board",
        task_id=task_id,
        parent_task_id="tsk_parent",
        title="open task",
        description="open task",
        owner_session_id="ast_board",
        status="pending_dispatch",
    )


def test_atomic_board_claim_allows_only_one_claimer() -> None:
    task = _open_task()
    service = TaskBoardService()

    first = service.claim_task(
        task_id=task.task_id,
        claimer_type="specialist",
        claimer_id="sp_a",
        lease_seconds=60,
    )
    second = service.claim_task(
        task_id=task.task_id,
        claimer_type="specialist",
        claimer_id="sp_b",
        lease_seconds=60,
    )

    claimed = AssistantTaskRepository().get_task(task.task_id)
    assert first is not None
    assert second is None
    assert claimed.assignee_type == "specialist"
    assert claimed.assignee_id == "sp_a"


def test_concurrent_claimers_on_same_version_only_one_wins() -> None:
    # SC-005：两个认领者在同一竞态窗口里基于同一 task_version 抢同一个 open task。
    # 用确定性 CAS 竞态而非真线程：测试 DB 是 StaticPool 单连接的 :memory: SQLite，
    # 多线程共享同一连接不安全且会 flaky；同版本号的两次 assign_if_version 正是并发
    # 认领要保证的不变量——恰好一个成功，绝不双认领。
    task = _open_task("tsk_race")
    version = task.task_version

    won_a = AssistantTaskRepository().assign_if_version(
        task.task_id,
        assignee_type="specialist",
        assignee_id="sp_a",
        expected_task_version=version,
    )
    won_b = AssistantTaskRepository().assign_if_version(
        task.task_id,
        assignee_type="specialist",
        assignee_id="sp_b",
        expected_task_version=version,
    )

    assert (won_a is None) != (won_b is None)  # 恰好一个赢
    final = AssistantTaskRepository().get_task(task.task_id)
    assert final.assignee_id in {"sp_a", "sp_b"}
    assert (final.assignee_id == "sp_a") == (won_a is not None)


def test_expired_claim_releases_open_task_for_new_claim() -> None:
    task = _open_task("tsk_expire")
    service = TaskBoardService()
    claim = service.claim_task(
        task_id=task.task_id,
        claimer_type="specialist",
        claimer_id="sp_a",
        lease_seconds=1,
    )

    expired_count = service.expire_claims(datetime.now() + timedelta(seconds=5))
    second = service.claim_task(
        task_id=task.task_id,
        claimer_type="specialist",
        claimer_id="sp_b",
        lease_seconds=60,
    )

    assert claim is not None
    assert expired_count == 1
    assert second is not None
    assert AssistantTaskRepository().get_task(task.task_id).assignee_id == "sp_b"


def test_rejected_claimer_is_excluded_from_retry() -> None:
    task = _open_task("tsk_reject")
    service = TaskBoardService()

    service.reject_task(
        task_id=task.task_id,
        claimer_type="specialist",
        claimer_id="sp_a",
        reason="not my specialty",
    )
    rejected_retry = service.claim_task(
        task_id=task.task_id,
        claimer_type="specialist",
        claimer_id="sp_a",
        lease_seconds=60,
    )
    assert rejected_retry is None
    claims = AssistantTaskClaimRepository().list_for_task(task.task_id)
    assert claims[0].status == "rejected"
    assert claims[0].reject_reason == "not my specialty"


def test_claim_task_enforces_claimer_capacity_one() -> None:
    # FR-003：单个认领者一次只持有一个进行中的认领（容量=1）。持有 active claim 时
    # 不得再认领第二个任务；该任务仍开放给其他认领者，释放后本人才能接下一个。
    first_task = _open_task("tsk_cap_1")
    second_task = _open_task("tsk_cap_2")
    service = TaskBoardService()

    first = service.claim_task(
        task_id=first_task.task_id,
        claimer_type="specialist",
        claimer_id="sp_busy",
        lease_seconds=60,
    )
    second = service.claim_task(
        task_id=second_task.task_id,
        claimer_type="specialist",
        claimer_id="sp_busy",
        lease_seconds=60,
    )

    assert first is not None
    assert second is None
    assert AssistantTaskRepository().get_task(second_task.task_id).assignee_id is None
    other = service.claim_task(
        task_id=second_task.task_id,
        claimer_type="specialist",
        claimer_id="sp_free",
        lease_seconds=60,
    )
    assert other is not None


def test_fallback_claims_stale_open_task_for_ephemeral_executor(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.board.get_unified_config",
        lambda: _FallbackConfig(),
    )
    monkeypatch.setattr(
        "src.business.task_collaboration.board._record_fallback_recruitment_signal",
        lambda task: None,
    )
    task = _open_task("tsk_fallback")
    repo = AssistantTaskRepository()
    row = repo.get_task(task.task_id)
    row.updated_at = utc_now_naive() - timedelta(seconds=30)
    repo.session.commit()

    claimed = TaskBoardService().start_fallback_executors(utc_now_naive())

    assert claimed == [task.task_id]
    refreshed = AssistantTaskRepository().get_task(task.task_id)
    assert refreshed.assignee_type == "ephemeral_subagent"
    assert refreshed.assignee_id == "ephemeral_subagent"
    claims = AssistantTaskClaimRepository().list_for_task(task.task_id)
    assert len(claims) == 1
    assert claims[0].status == "claimed"
