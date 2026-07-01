"""Task 协作 CAS 跨连接并发回归。

这些 CAS（attempt fence/terminate、task 认领占位）跑在独立连接上、不共用 dispatcher 的
``_write_lock``。必须用文件库（NullPool + 每连接独立 + WAL）才能复现跨连接 read-check-write
窗口；``:memory:`` + StaticPool 单连接造不出这个窗口（现有 task 测试就因此漏掉它）。

判别不变量：并发下两笔 CAS 必须恰好一个生效。修复前 ORM flush 发 ``WHERE pk=?`` 盲写，
两笔都落库 -> 两个都返回非 None（守卫只在 Python 判断没进 SQL）。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import timedelta

import pytest
from sqlalchemy import event

import src.data.sqlalchemy_manager as sm_module
from src.data.sqlalchemy_manager import SQLAlchemyManager
from src.data.repos import (
    AssistantTaskAdjudicationRepository,
    AssistantTaskAttemptRepository,
    AssistantTaskRepository,
)
from src.utils.timezone import utc_now_naive


@pytest.fixture
def file_db(tmp_path):
    """生产同构：文件库 -> NullPool + per-connection + WAL，替换全局 singleton 后还原。"""
    original = sm_module._sqlalchemy_instance
    manager = SQLAlchemyManager(str(tmp_path / "race.db"))
    manager.initialize()
    sm_module._sqlalchemy_instance = manager
    try:
        yield manager
    finally:
        manager.close()
        sm_module._sqlalchemy_instance = original


@contextmanager
def _update_barrier(engine, table: str):
    """在指定表的 UPDATE 语句执行前卡 2 方 barrier。

    强制两线程都越过各自读/守卫、都抵达写入点后再放行，精确命中竞态窗口。对“是否预读”
    的实现都成立——盲写和条件 UPDATE 都会发 UPDATE 语句。``gate["on"]`` 控制起停。
    """
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


def test_fence_and_late_complete_cannot_both_win(file_db) -> None:
    """fence(recovery) 与 late complete(worker) 并发时必须恰好一个生效。

    修复前两笔盲写都落库 -> 都返回非 None（late result 没被拒，行被污染成 fenced 却带
    worker 的 result_ref）。修复后 fence_token/status 守卫进 SQL，第二笔 UPDATE 匹配 0 行。
    """
    with AssistantTaskAttemptRepository() as seed:
        seed.start_attempt(
            task_id="tsk_race",
            executor_type="ephemeral_subagent",
            executor_id="exec_race",
            lease_owner="owner",
            lease_expires_at=utc_now_naive() + timedelta(seconds=60),
            attempt_id="att_race",
        )

    results: dict = {}

    def recovery_fence() -> None:
        try:
            with AssistantTaskAttemptRepository() as attempts:
                results["fence"] = attempts.fence("att_race") is not None
        except Exception as exc:  # noqa: BLE001
            results["fence_exc"] = repr(exc)

    def worker_complete() -> None:
        try:
            with AssistantTaskAttemptRepository() as attempts:
                row = attempts.complete_if_current(
                    attempt_id="att_race", fence_token=1, result_ref="done"
                )
                results["complete"] = row is not None
        except Exception as exc:  # noqa: BLE001
            results["complete_exc"] = repr(exc)

    with _update_barrier(file_db.engine, "assistant_task_attempts") as gate:
        gate["on"] = True
        _run_concurrently(recovery_fence, worker_complete)
        gate["on"] = False

    assert "fence_exc" not in results, results
    assert "complete_exc" not in results, results
    assert results.get("fence", False) != results.get("complete", False), (
        f"fence={results.get('fence')} complete={results.get('complete')} —— "
        "fence 与 late complete 不能同时生效（守卫必须进 SQL）"
    )

    with AssistantTaskAttemptRepository() as fin:
        row = fin.get_by_id("att_race")
        if row.status == "fenced":
            assert row.result_ref is None, "fenced 行不应保留 worker 完成结果（行被污染）"


def test_concurrent_claim_assignment_cannot_both_win(file_db) -> None:
    """两个认领者并发占位同一 task 时必须恰好一个成功。

    ``assign_if_version`` 是看板认领的占位 CAS。修复前 read-check-write 在并发下两双都通过
    ``task_version`` / ``assignee is None`` 守卫、两笔盲写都落库 -> 两个都返回非 None（双认领，
    assignee 被后写覆盖）。修复后守卫进 SQL，第二笔匹配 0 行返回 None。
    """
    with AssistantTaskRepository() as seed:
        seed.create_task(
            graph_id="tg_claim",
            session_id="ast_claim",
            task_id="tsk_claim",
            parent_task_id="root_claim",
            title="task",
            description="task",
            status="pending_dispatch",
        )

    results: dict = {}

    def claim(name: str) -> None:
        try:
            with AssistantTaskRepository() as tasks:
                row = tasks.assign_if_version(
                    "tsk_claim",
                    assignee_type="specialist",
                    assignee_id=name,
                    expected_task_version=1,
                )
                results[name] = row is not None
        except Exception as exc:  # noqa: BLE001
            results[f"{name}_exc"] = repr(exc)

    with _update_barrier(file_db.engine, "assistant_tasks") as gate:
        gate["on"] = True
        _run_concurrently(lambda: claim("A"), lambda: claim("B"))
        gate["on"] = False

    assert not any(k.endswith("_exc") for k in results), results
    assert results.get("A", False) != results.get("B", False), (
        f"A={results.get('A')} B={results.get('B')} —— "
        "两个认领者不能同时占位同一 task（守卫必须进 SQL）"
    )
    # 最终 task_version 只 +1（只有一次有效占位），且 assignee 是赢家
    with AssistantTaskRepository() as fin:
        task = fin.get_task("tsk_claim")
        assert task.task_version == 2, f"双认领会让版本号错乱，实际={task.task_version}"
        assert task.assignee_id in {"A", "B"}


def test_concurrent_adjudication_decide_cannot_both_win(file_db) -> None:
    """两笔并发裁定同一 pending adjudication 时必须恰好一个生效。

    修复前 ``decide`` 是 ORM 读-改-写（``get_by_id`` 后 ``WHERE pk=?`` 盲写），并发下两笔都
    通过 Python 的 ``status=="pending"`` 守卫；条件 UPDATE 把守卫推进 SQL，第二笔匹配 0 行
    返回 None（已裁定），赢家的 decision 不被败者覆盖。
    """
    with AssistantTaskRepository() as seed_task:
        seed_task.create_task(
            graph_id="tg_adj_race",
            session_id="ast_adj_race",
            task_id="tsk_adj_race",
            parent_task_id="root_adj_race",
            title="task",
            description="task",
            status="running",
        )
    with AssistantTaskAdjudicationRepository() as seed_adj:
        seed_adj.create_pending(
            task_id="tsk_adj_race",
            graph_id="tg_adj_race",
            parent_session_id="ast_adj_race",
            delivered_status="done",
            safe_summary="done",
            adjudication_id="adj_race",
        )

    results: dict = {}

    def decide(name: str, decision: str) -> None:
        try:
            with AssistantTaskAdjudicationRepository() as adjs:
                row = adjs.decide("adj_race", decision=decision, decided_by=name)
                results[name] = row is not None
        except Exception as exc:  # noqa: BLE001
            results[f"{name}_exc"] = repr(exc)

    with _update_barrier(file_db.engine, "assistant_task_adjudications") as gate:
        gate["on"] = True
        _run_concurrently(
            lambda: decide("A", "accepted"),
            lambda: decide("B", "abandoned"),
        )
        gate["on"] = False

    assert not any(k.endswith("_exc") for k in results), results
    assert results.get("A", False) != results.get("B", False), (
        f"A={results.get('A')} B={results.get('B')} —— " "两笔裁定不能同时生效（守卫必须进 SQL）"
    )
    # 最终只有一个赢家落库：status=decided 且 decision 为某一方，未被覆盖错乱
    with AssistantTaskAdjudicationRepository() as fin:
        row = fin.get_by_id("adj_race")
        assert row.status == "decided"
        assert row.decision in {"accepted", "abandoned"}
