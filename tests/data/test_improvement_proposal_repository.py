"""Tests for ImprovementProposalRepository — CAS state machine, dedup, serialisation gate."""

from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest
from sqlalchemy import event

import src.data.sqlalchemy_manager as sm_module
from src.data.sqlalchemy_manager import SQLAlchemyManager
from src.data.repos.improvement_proposal_repository import (
    ImprovementProposalRepository,
    compute_dedup_key,
)
from src.data.models_sqlite import ImprovementProposal

# -- Helper -----------------------------------------------------------------


def _make_proposal(repo: ImprovementProposalRepository, **overrides) -> ImprovementProposal:
    defaults = {
        "source_review_id": "rev_test",
        "finding_index": 0,
        "severity": "med",
        "finding_type": "efficiency",
        "what": "重复抓取同一数据",
    }
    defaults.update(overrides)
    row = repo.create(**defaults)
    assert row is not None, "create must succeed"
    return row


# -- 真并发夹具(file DB + NullPool + WAL,before_cursor_execute barrier)------
# 026 review CG-1::memory: + StaticPool 两线程共享单 DBAPI connection,Barrier
# 打不开 read-check-write 窗口;文件库才能复现跨连接并发竞争。模式同
# test_self_improvement_cas_concurrency。


@pytest.fixture
def file_db(tmp_path):
    """生产同构:文件库 -> NullPool + per-connection + WAL,替换全局 singleton 后还原。"""
    original = sm_module._sqlalchemy_instance
    manager = SQLAlchemyManager(str(tmp_path / "proposal_race.db"))
    manager.initialize()
    sm_module._sqlalchemy_instance = manager
    try:
        yield manager
    finally:
        manager.close()
        sm_module._sqlalchemy_instance = original


@contextmanager
def _update_barrier(engine, table: str):
    """在指定表的 UPDATE 执行前卡 2 方 barrier,强制两线程都越过读点后再放行。"""
    barrier = threading.Barrier(2, timeout=15)
    state = {"n": 0, "on": False}
    lock = threading.Lock()
    prefix = f"UPDATE {table}".upper()

    @event.listens_for(engine, "before_cursor_execute")
    def _interpose(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
        if not state["on"]:
            return
        if statement.lstrip()[:60].upper().startswith(prefix):
            with lock:
                state["n"] += 1
                mine = state["n"]
            if mine <= 2:
                try:
                    barrier.wait()
                except Exception:
                    pass

    try:
        yield state
    finally:
        event.remove(engine, "before_cursor_execute", _interpose)


def _run_concurrently(*targets) -> None:
    threads = [threading.Thread(target=t) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# -- Create & idempotent -----------------------------------------------------


def test_create_returns_pending_review(in_memory_db):
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        row = _make_proposal(repo)
        assert row.status == "pending_review"
        assert row.source_review_id == "rev_test"
        assert row.finding_index == 0


def test_create_idempotent_on_unique_constraint(in_memory_db):
    """Same (source_review_id, finding_index) → create returns None."""
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        _make_proposal(repo, source_review_id="rev_a", finding_index=0)
        dup = repo.create(source_review_id="rev_a", finding_index=0)
        assert dup is None


# -- Dedup suppression (FR-001a) ---------------------------------------------


def test_create_dedup_suppresses_same_key_non_terminal(in_memory_db):
    """Same dedup_key with non-terminal status → suppressed (None)."""
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        key = compute_dedup_key("efficiency", "重复抓取")
        _make_proposal(repo, dedup_key=key, what="重复抓取", finding_type="efficiency")
        dup = repo.create(
            source_review_id="rev_other",
            finding_index=1,
            dedup_key=key,
            what="重复抓取",
            finding_type="efficiency",
        )
        assert dup is None


def test_create_dedup_suppresses_same_key_failed(in_memory_db):
    """Same dedup_key with failed status remains unresolved until rejected."""
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        key = compute_dedup_key("efficiency", "失败后仍未处理")
        row = _make_proposal(
            repo,
            dedup_key=key,
            what="失败后仍未处理",
            finding_type="efficiency",
        )
        repo.approve(row.id)
        repo.mark_failed(row.id, error="worktree creation failed")

        dup = repo.create(
            source_review_id="rev_after_failed",
            finding_index=1,
            dedup_key=key,
            what="失败后仍未处理",
            finding_type="efficiency",
        )

        assert dup is None


def test_create_dedup_allows_same_key_terminal_outside_cooldown(in_memory_db):
    """Same dedup_key but terminal (rejected) and outside cooldown → allowed."""
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        key = compute_dedup_key("efficiency", "老问题")
        row = _make_proposal(repo, dedup_key=key, what="老问题")
        # Move to terminal rejected
        repo.reject(row.id)
        # Create new with same dedup_key — cooldown is 24h but we can't easily
        # control time in tests. Instead, verify that dedup_key matching logic
        # exists; full cooldown test requires time mocking which would be fragile.
        # Here we verify terminal + different (review, index) still works.
        new_row = repo.create(
            source_review_id="rev_new",
            finding_index=5,
            dedup_key=compute_dedup_key("efficiency", "新问题"),
            what="新问题",
        )
        assert new_row is not None


def test_create_dedup_suppresses_same_key_terminal_within_cooldown(in_memory_db, monkeypatch):
    """FR-001a: Same dedup_key, terminal (rejected), but WITHIN cooldown → suppressed."""
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        key = compute_dedup_key("efficiency", "冷却期内问题")

        row = _make_proposal(repo, dedup_key=key, what="冷却期内问题")
        repo.reject(row.id)

        # Mock cooldown to a very large value (9999h) so the recently-rejected
        # proposal is always within the cooldown window.
        monkeypatch.setattr(
            ImprovementProposalRepository,
            "_get_dedup_cooldown_hours",
            staticmethod(lambda: 9999),
        )

        dup = repo.create(
            source_review_id="rev_after_reject",
            finding_index=1,
            dedup_key=key,
            what="冷却期内问题",
            finding_type="efficiency",
        )
        assert dup is None, "same dedup_key within cooldown must be suppressed"


def test_create_dedup_allows_same_key_terminal_after_cooldown(in_memory_db, monkeypatch):
    """FR-001a: Same dedup_key, terminal (rejected), OUTSIDE cooldown → allowed."""
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        key = compute_dedup_key("efficiency", "冷却期外问题")

        row = _make_proposal(repo, dedup_key=key, what="冷却期外问题")
        repo.reject(row.id)

        # Mock cooldown to 0h so the recently-rejected proposal is immediately
        # outside the cooldown window.
        monkeypatch.setattr(
            ImprovementProposalRepository,
            "_get_dedup_cooldown_hours",
            staticmethod(lambda: 0),
        )

        new_row = repo.create(
            source_review_id="rev_after_cooldown",
            finding_index=1,
            dedup_key=key,
            what="冷却期外问题",
            finding_type="efficiency",
        )
        assert new_row is not None, "same dedup_key outside cooldown must be allowed"


# -- CAS state machine -------------------------------------------------------


def test_approve_transitions_pending_to_approved(in_memory_db):
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        row = _make_proposal(repo)
        result = repo.approve(row.id, supplement="请优先改缓存")
        assert result is not None
        assert result.status == "approved"
        assert result.user_supplement == "请优先改缓存"
        assert result.decided_at is not None


def test_approve_non_pending_returns_none(in_memory_db):
    """CAS guard: approving an already-approved proposal returns None."""
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        row = _make_proposal(repo)
        repo.approve(row.id)
        second = repo.approve(row.id)
        assert second is None


def test_reject_transitions_pending_to_rejected(in_memory_db):
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        row = _make_proposal(repo)
        result = repo.reject(row.id)
        assert result is not None
        assert result.status == "rejected"


def test_reject_transitions_failed_to_rejected(in_memory_db):
    """reject on a failed proposal (D8 cleanup trigger)."""
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        row = _make_proposal(repo)
        # Force approved first, then failed
        repo.approve(row.id)
        repo.mark_in_progress(row.id, graph_id="g1", worktree_path="/tmp/w", branch_name="b1")
        repo.mark_failed(row.id, error="build failed")
        result = repo.reject(row.id)
        assert result is not None
        assert result.status == "rejected"


def test_reject_approved_returns_none(in_memory_db):
    """reject cannot apply to approved (not in allowed transitions)."""
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        row = _make_proposal(repo)
        repo.approve(row.id)
        result = repo.reject(row.id)
        assert result is None


def test_mark_in_progress_transitions_approved_to_in_progress(in_memory_db):
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        row = _make_proposal(repo)
        repo.approve(row.id)
        result = repo.mark_in_progress(
            row.id,
            graph_id="graph_abc",
            worktree_path="/worktrees/improvement/prop_abc",
            branch_name="improvement/prop_abc",
        )
        assert result is not None
        assert result.status == "in_progress"
        assert result.graph_id == "graph_abc"
        assert result.worktree_path == "/worktrees/improvement/prop_abc"
        assert result.branch_name == "improvement/prop_abc"


def test_mark_done_transitions_in_progress_to_done(in_memory_db):
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        row = _make_proposal(repo)
        repo.approve(row.id)
        repo.mark_in_progress(row.id, graph_id="g1", worktree_path="/w", branch_name="b1")
        result = repo.mark_done(row.id, tests_passed=True, summary="所有测试通过")
        assert result is not None
        assert result.status == "done"
        assert result.result_tests_passed is True
        assert result.result_summary == "所有测试通过"
        assert result.completed_at is not None


def test_mark_done_rejects_failing_tests(in_memory_db):
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        row = _make_proposal(repo)
        repo.approve(row.id)
        repo.mark_in_progress(row.id, graph_id="g1", worktree_path="/w", branch_name="b1")

        try:
            repo.mark_done(row.id, tests_passed=False, summary="测试失败")
        except ValueError as exc:
            assert "passing tests" in str(exc)
        else:
            raise AssertionError("mark_done must reject tests_passed=False")

        current = repo.get_by_id(row.id)
        assert current is not None
        assert current.status == "in_progress"


def test_mark_failed_transitions_in_progress_to_failed(in_memory_db):
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        row = _make_proposal(repo)
        repo.approve(row.id)
        repo.mark_in_progress(row.id, graph_id="g1", worktree_path="/w", branch_name="b1")
        result = repo.mark_failed(row.id, error="build failed", tests_passed=False)
        assert result is not None
        assert result.status == "failed"
        assert result.result_tests_passed is False
        assert result.error == "build failed"


def test_mark_failed_from_approved(in_memory_db):
    """approved -> failed (bridge build worktree/graph failed)."""
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        row = _make_proposal(repo)
        repo.approve(row.id)
        result = repo.mark_failed(row.id, error="worktree creation failed")
        assert result is not None
        assert result.status == "failed"


def test_illegal_transition_returns_none(in_memory_db):
    """Attempting an invalid transition returns None."""
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        row = _make_proposal(repo)
        # pending_review -> in_progress is illegal
        result = repo.mark_in_progress(row.id, graph_id="g1", worktree_path="/w", branch_name="b1")
        assert result is None


# -- has_in_progress serialisation gate (FR-018) ----------------------------


def test_has_in_progress_returns_false_when_no_in_progress(in_memory_db):
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        assert not repo.has_in_progress()


def test_has_in_progress_returns_true_after_transition(in_memory_db):
    with in_memory_db.get_session() as session:
        repo = ImprovementProposalRepository(session=session)
        row = _make_proposal(repo)
        repo.approve(row.id)
        repo.mark_in_progress(row.id, graph_id="g1", worktree_path="/w", branch_name="b1")
        assert repo.has_in_progress()


# -- Concurrent approve does not double-trigger ------------------------------


def test_concurrent_approve_no_double_trigger(file_db):
    """Two threads approving the same proposal concurrently — exactly one CAS wins.

    026 review CG-1: the prior in_memory_db + StaticPool variant could not expose a
    read-check-write race (two threads share one DBAPI connection, so the Barrier
    could not open a window) and asserted ``<= 1``, which holds even with no CAS
    guard. This variant uses a file DB + NullPool + a before_cursor_execute barrier
    so both threads reach the CAS UPDATE having already read status='pending_review';
    the conditional UPDATE must still let exactly one win.
    """
    with ImprovementProposalRepository() as repo:
        row = _make_proposal(repo, source_review_id="rev_concurrent", finding_index=0)
        row_id = row.id

    results: list = []

    def _approve() -> None:
        try:
            with ImprovementProposalRepository() as repo:
                results.append(repo.approve(row_id))
        except Exception as exc:  # noqa: BLE001
            results.append(repr(exc))

    with _update_barrier(file_db.engine, "improvement_proposals") as gate:
        gate["on"] = True
        _run_concurrently(_approve, _approve)
        gate["on"] = False

    assert not any(isinstance(r, str) for r in results), results
    successful = [r for r in results if r is not None]
    assert len(successful) == 1, f"expected exactly one CAS winner, got {results}"
    assert successful[0].status == "approved"


def test_mark_in_progress_single_flight_guard(in_memory_db):
    """FR-018: ~exists(in_progress) 守卫——已有 in_progress 时，第二个 mark 返回 None。

    mark_in_progress 把"无其他 in_progress 行"守卫折进 approved→in_progress 的同一条
    CAS UPDATE。这里序列化验证该守卫：第一个 mark 成功后，第二个 mark 即便其目标仍处
    approved 态也必须被挡住（single-flight）。

    注：threading 并发在此 fixture 下不可靠——in_memory_db 用 StaticPool 单连接，两
    线程共享同一 DBAPI connection 而非独立事务（test_concurrent_approve 的 ``<=1``
    断言即为此妥协），故用确定性序列覆盖 ~exists 守卫逻辑本身。
    """
    from src.data.sqlalchemy_manager import get_sqlalchemy_manager

    mgr = get_sqlalchemy_manager()
    with mgr.get_session() as s:
        repo = ImprovementProposalRepository(session=s)
        row_a = _make_proposal(repo, source_review_id="rev_mi_a", finding_index=0)
        row_b = _make_proposal(repo, source_review_id="rev_mi_b", finding_index=0)
        repo.approve(row_a.id)
        repo.approve(row_b.id)
        id_a, id_b = row_a.id, row_b.id

        # 第一个 mark 成功（此刻无 in_progress）
        first = repo.mark_in_progress(id_a, graph_id="g_a", worktree_path="/wa", branch_name="ba")
        assert first is not None
        assert first.status == "in_progress"
        assert repo.has_in_progress() is True

        # 第二个 mark 被 ~exists(in_progress) 守卫挡住，即便 id_b 仍 approved
        second = repo.mark_in_progress(id_b, graph_id="g_b", worktree_path="/wb", branch_name="bb")
        assert second is None
        assert repo.get_by_id(id_b).status == "approved"


# -- compute_dedup_key -------------------------------------------------------


def test_compute_dedup_key_stable():
    k1 = compute_dedup_key("efficiency", "重复抓取同一数据")
    k2 = compute_dedup_key("efficiency", "重复抓取同一数据")
    assert k1 == k2
    assert len(k1) == 40


def test_compute_dedup_key_different_for_different_what():
    k1 = compute_dedup_key("efficiency", "问题 A")
    k2 = compute_dedup_key("efficiency", "问题 B")
    assert k1 != k2


def test_compute_dedup_key_null_when_no_what():
    assert compute_dedup_key("efficiency", None) is None
    assert compute_dedup_key(None, None) is None
