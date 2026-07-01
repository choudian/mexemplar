"""Self-improvement repository CAS 跨连接并发回归（026 I7）。

occurrence_count 自增、prompt supplement version 递增曾是 read-modify-write 反模式，
并发下丢更新。修复后用原子条件 UPDATE + SQL 自增表达式。文件库（NullPool + WAL）
才能复现跨连接 read-check-write 窗口；``:memory:`` 单连接造不出。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest
from sqlalchemy import event

import src.data.sqlalchemy_manager as sm_module
from src.data.sqlalchemy_manager import SQLAlchemyManager
from src.data.repos.self_improvement_repository import SelfImprovementRepository


@pytest.fixture
def file_db(tmp_path):
    """生产同构：文件库 -> NullPool + per-connection + WAL，替换全局 singleton 后还原。"""
    original = sm_module._sqlalchemy_instance
    manager = SQLAlchemyManager(str(tmp_path / "si_race.db"))
    manager.initialize()
    sm_module._sqlalchemy_instance = manager
    try:
        yield manager
    finally:
        manager.close()
        sm_module._sqlalchemy_instance = original


@contextmanager
def _update_barrier(engine, table: str):
    """在指定表的 UPDATE 执行前卡 2 方 barrier，强制两线程都越过读点后再放行。"""
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


def test_create_gap_report_concurrent_increment_does_not_lose_count(file_db) -> None:
    """并发对同 pattern_signature 的 gap report 自增不得丢计数（026 I7）。

    修复前 read-modify-write：两线程各读 occurrence_count=1、各写 2 -> 最终 2（丢一次）。
    修复后原子 ``occurrence_count = occurrence_count + 1``：串行自增 -> 最终 3。
    """
    with SelfImprovementRepository() as seed:
        seed.create_gap_report(
            gap_type="bug_pattern",
            tool_name="search_web",
            pattern_signature="bug:search_web:abc",
            evidence={"sample": "e1"},
        )

    errors: list = []

    def _bump() -> None:
        try:
            with SelfImprovementRepository() as repo:
                repo.create_gap_report(
                    gap_type="bug_pattern",
                    tool_name="search_web",
                    pattern_signature="bug:search_web:abc",
                    evidence={"sample": "e2"},
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    with _update_barrier(file_db.engine, "tool_gap_reports") as gate:
        gate["on"] = True
        _run_concurrently(_bump, _bump)
        gate["on"] = False

    assert not errors, errors
    with SelfImprovementRepository() as repo:
        reports = repo.get_unresolved_gap_reports()
        assert len(reports) == 1, f"dedup 应保持单行，实际 {len(reports)} 行"
        assert (
            reports[0].occurrence_count == 3
        ), f"并发自增丢更新：期望 3，实际 {reports[0].occurrence_count}"


def test_promote_supplement_concurrent_no_duplicate_version(file_db) -> None:
    """并发 promote 同 section 的两个 candidate supplement 不得产生重复 version（026 I7）。

    修复前 read-modify-write max_version+1：两线程各读 max=1、各写 2 -> 两个 active
    version=2。修复后原子 ``version = (SELECT max+1)`` 串行求值 -> {2, 3}。
    """
    with SelfImprovementRepository() as seed:
        a = seed.create_supplement("intro", "cA", "r", None, None)
        b = seed.create_supplement("intro", "cB", "r", None, None)
        a_id, b_id = a.supplement_id, b.supplement_id

    errors: list = []

    def _promote(supplement_id: str) -> None:
        try:
            with SelfImprovementRepository() as repo:
                repo.promote_supplement(supplement_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    with _update_barrier(file_db.engine, "prompt_supplements") as gate:
        gate["on"] = True
        _run_concurrently(lambda: _promote(a_id), lambda: _promote(b_id))
        gate["on"] = False

    assert not errors, errors
    # 两 supplement 都成功 promote（version 被赋值）。supersede 语义下，后 promote 的会
    # 取代先 promote 的（先者变 superseded），但 version 必须不重复且递增——修复前两并发
    # read max=1 -> 都 version=2 重复。核心不变量：version 集合不重复。
    from src.data.models_sqlite import PromptSupplement

    with SelfImprovementRepository() as repo:
        rows = (
            repo.session.query(PromptSupplement)
            .filter(PromptSupplement.supplement_id.in_([a_id, b_id]))
            .all()
        )
        versions = sorted(r.version for r in rows)
        assert {a_id, b_id} == {r.supplement_id for r in rows}, "两 supplement 都应存在"
        assert len(set(versions)) == 2, f"并发 promote 产生重复 version：{versions}"


def test_create_gap_report_returns_row_not_none_on_cas_loss(in_memory_db, monkeypatch) -> None:
    """CAS UPDATE 匹配 0 行（并发下 status 被改）时返回当前行而非 None（026 I7 follow-up）。

    tool_gap_detector 的 4 个调用方直接访问 report.report_id，None 会 AttributeError。
    """
    from sqlalchemy.orm import Query

    with SelfImprovementRepository() as repo:
        repo.create_gap_report("bug_pattern", "t", "sig_cas_lost", {})

        original_update = Query.update
        state = {"bypassed": False}

        def fake_update(self, *args, **kwargs):
            if not state["bypassed"]:
                state["bypassed"] = True
                return 0  # 模拟 CAS UPDATE 匹配 0 行（status 已变）
            return original_update(self, *args, **kwargs)

        monkeypatch.setattr(Query, "update", fake_update)
        result = repo.create_gap_report("bug_pattern", "t", "sig_cas_lost", {})

    assert result is not None
    assert result.report_id
