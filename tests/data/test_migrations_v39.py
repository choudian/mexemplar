"""v39：给「撞上程序缺陷」这一类停法开格子。

两张表各加一个值，而且**必须一起加**：

* ``assistant_tasks.suspend_reason`` += ``blocked_by_defect`` —— 活因为程序缺陷停下
* ``assistant_run_failures.category`` += ``code_defect`` —— 分类器的产出要能落库

第二张不是顺带：分类器算出一个 DB 不认的 category，落库就撞 CHECK，于是
**"记录失败"这件事本身失败**——出了事，连出过事都记不下来。
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from src.business.services.assistant_failure_classifier import KNOWN_FAILURE_CATEGORIES
from src.business.task_collaboration.models import SuspendReason
from src.data import migrations
from src.data.models_sqlite import AssistantRunFailure, AssistantTask

from tests.data.test_migrations_v38 import TASK_INDEXES, _engine_at_v37


FAILURE_INDEXES = {
    "uq_assistant_run_failure_current_session",
    "idx_assistant_run_failure_message",
    "idx_assistant_run_failure_status",
}

# v38 形态：category 只有 7 个值，没有 code_defect
_V38_RUN_FAILURES_DDL = """
    CREATE TABLE assistant_run_failures (
        failure_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        message_sequence INTEGER NOT NULL,
        category TEXT NOT NULL
            CONSTRAINT ck_assistant_run_failures_category
            CHECK (category IN (
                'authentication', 'invalid_request', 'quota', 'network',
                'provider', 'iteration_limit', 'internal'
            )),
        safe_message TEXT NOT NULL,
        safe_suggestion TEXT NOT NULL,
        internal_code TEXT,
        exception_type TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 1
            CONSTRAINT ck_assistant_run_failures_attempt_count
            CHECK (attempt_count >= 1),
        status TEXT NOT NULL DEFAULT 'failed'
            CONSTRAINT ck_assistant_run_failures_status
            CHECK (status IN ('failed', 'retrying', 'resolved')),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        failed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        resolved_at DATETIME
    )
"""


def _engine_at_v38():
    """v38 状态的库：复用 v38 测试的工厂 + 真跑一次 v38 迁移，再补一张
    v38 形态的 assistant_run_failures + 种子行。

    走真实迁移而不是手搭 v38 schema，顺带验证了 v37→v38→v39 能连着跑。
    """
    engine = _engine_at_v37()
    migrations.migrate_to_v38(engine)
    with engine.begin() as conn:
        conn.execute(text(_V38_RUN_FAILURES_DDL))
        for index_sql in (
            "CREATE UNIQUE INDEX uq_assistant_run_failure_current_session "
            "ON assistant_run_failures(session_id) WHERE status IN ('failed', 'retrying')",
            "CREATE INDEX idx_assistant_run_failure_message "
            "ON assistant_run_failures(session_id, message_sequence)",
            "CREATE INDEX idx_assistant_run_failure_status ON assistant_run_failures(status)",
        ):
            conn.execute(text(index_sql))
        conn.execute(
            text(
                """
                INSERT INTO assistant_run_failures (
                    failure_id, session_id, message_sequence, category,
                    safe_message, safe_suggestion, internal_code, exception_type,
                    attempt_count, status, created_at, updated_at, failed_at, resolved_at
                ) VALUES (
                    'fail_seed', 'ast_seed', 3, 'network',
                    '连接模型服务时中断了。', '请检查网络连接后重试。',
                    'assistant_network', 'TimeoutError',
                    2, 'failed', '2026-07-29 10:00:00', '2026-07-29 10:05:00',
                    '2026-07-29 10:00:00', NULL
                )
                """
            )
        )
    return engine


def _allowed_values(engine, table: str, constraint: str) -> set[str]:
    """从建表 DDL 里读出某条 CHECK 允许的取值。"""
    with engine.connect() as conn:
        ddl = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table},
        ).scalar_one()
    segment = ddl.split(constraint, 1)[1].split(")", 1)[0]
    return set(re.findall(r"'([a-z_]+)'", segment))


def _orm_allowed_values(model, constraint_name: str) -> set[str]:
    constraint = next(
        c for c in model.__table__.constraints if getattr(c, "name", None) == constraint_name
    )
    return set(re.findall(r"'([a-z_]+)'", str(constraint.sqltext)))


def _indexes(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        return {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=:t"),
                {"t": table},
            )
            if not row[0].startswith("sqlite_")
        }


def test_v39_lets_a_task_stop_because_of_a_code_defect() -> None:
    """撞上程序缺陷是一种停法。此前 CHECK 不认这个值——落库会被拒，
    于是"记下这个活撞了缺陷"这件事本身失败。"""
    engine = _engine_at_v38()
    migrations.migrate_to_v39(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO assistant_tasks (
                    task_id, graph_id, session_id, title, description,
                    status, suspend_reason, waiting_on, graph_version, task_version,
                    requires_confirmation
                ) VALUES (
                    'tsk_defect', 'tg_seed', 'ast_seed', 'defect', 'defect desc',
                    'suspended', 'blocked_by_defect', 'assistant', 1, 1, 0
                )
                """
            )
        )
        stored = conn.execute(
            text("SELECT suspend_reason, waiting_on FROM assistant_tasks WHERE task_id='tsk_defect'")
        ).one()
    assert stored == ("blocked_by_defect", "assistant")


def test_v39_lets_every_classifier_category_be_persisted() -> None:
    """分类器产出什么，库就得存得下什么——逐个值真写一遍，不只是读 DDL。"""
    engine = _engine_at_v38()
    migrations.migrate_to_v39(engine)

    with engine.begin() as conn:
        for i, category in enumerate(sorted(KNOWN_FAILURE_CATEGORIES)):
            conn.execute(
                text(
                    """
                    INSERT INTO assistant_run_failures (
                        failure_id, session_id, message_sequence, category,
                        safe_message, safe_suggestion, attempt_count, status
                    ) VALUES (
                        :fid, :sid, 1, :category, 'safe', 'safe', 1, 'resolved'
                    )
                    """
                ),
                {"fid": f"fail_{i}", "sid": f"ast_{i}", "category": category},
            )
        stored = {
            row[0]
            for row in conn.execute(
                text("SELECT category FROM assistant_run_failures WHERE failure_id LIKE 'fail_%'")
            )
        }
    assert KNOWN_FAILURE_CATEGORIES <= stored


def test_v39_still_rejects_values_outside_both_lists() -> None:
    """放宽不等于放开：拼错的值必须当场被拒，不能等到运行时才发现。"""
    engine = _engine_at_v38()
    migrations.migrate_to_v39(engine)

    with pytest.raises(IntegrityError, match="ck_assistant_tasks_suspend_reason"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO assistant_tasks (
                        task_id, graph_id, session_id, title, description,
                        status, suspend_reason, waiting_on, graph_version,
                        task_version, requires_confirmation
                    ) VALUES (
                        'tsk_typo', 'tg_seed', 'ast_seed', 't', 'd',
                        'suspended', 'blocked_by_defct', 'assistant', 1, 1, 0
                    )
                    """
                )
            )

    with pytest.raises(IntegrityError, match="ck_assistant_run_failures_category"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO assistant_run_failures (
                        failure_id, session_id, message_sequence, category,
                        safe_message, safe_suggestion, attempt_count, status
                    ) VALUES (
                        'fail_typo', 'ast_typo', 1, 'code_defct', 's', 's', 1, 'failed'
                    )
                    """
                )
            )


def test_v39_preserves_every_row_and_rebuilds_both_index_sets() -> None:
    """整表重建最大的两个风险：丢数据、丢索引。两张表都要验。"""
    engine = _engine_at_v38()
    with engine.connect() as conn:
        tasks_before = [
            dict(row._mapping)
            for row in conn.execute(text("SELECT * FROM assistant_tasks ORDER BY task_id"))
        ]
        failures_before = [
            dict(row._mapping)
            for row in conn.execute(text("SELECT * FROM assistant_run_failures ORDER BY failure_id"))
        ]

    migrations.migrate_to_v39(engine)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT version FROM schema_version")).scalar() == 39
        tasks_after = [
            dict(row._mapping)
            for row in conn.execute(text("SELECT * FROM assistant_tasks ORDER BY task_id"))
        ]
        failures_after = [
            dict(row._mapping)
            for row in conn.execute(text("SELECT * FROM assistant_run_failures ORDER BY failure_id"))
        ]

    assert tasks_after == tasks_before
    assert failures_after == failures_before
    assert _indexes(engine, "assistant_tasks") == TASK_INDEXES
    assert _indexes(engine, "assistant_run_failures") == FAILURE_INDEXES


def test_v39_is_idempotent() -> None:
    """迁移会被重跑（升级中断、多进程启动），第二次不能炸也不能改动数据。"""
    engine = _engine_at_v38()
    migrations.migrate_to_v39(engine)
    with engine.connect() as conn:
        after_first = [
            dict(row._mapping)
            for row in conn.execute(text("SELECT * FROM assistant_tasks ORDER BY task_id"))
        ]

    migrations.migrate_to_v39(engine)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT version FROM schema_version")).scalar() == 39
        after_second = [
            dict(row._mapping)
            for row in conn.execute(text("SELECT * FROM assistant_tasks ORDER BY task_id"))
        ]
    assert after_second == after_first
    assert _indexes(engine, "assistant_tasks") == TASK_INDEXES


def test_v39_survives_a_database_without_those_tables() -> None:
    """老库可能压根没建过这两张表，迁移不能因此崩掉整个启动。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (38)"))

    migrations.migrate_to_v39(engine)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT version FROM schema_version")).scalar() == 39


def test_orm_and_migration_agree_on_both_constraints() -> None:
    """ORM 定义和迁移 DDL 是两份手写副本。它们漂移了不会有任何报错——
    新库按 ORM 建、老库按迁移升，两边行为就此分叉，而且很难查。"""
    engine = _engine_at_v38()
    migrations.migrate_to_v39(engine)

    assert _allowed_values(
        engine, "assistant_tasks", "ck_assistant_tasks_suspend_reason"
    ) == _orm_allowed_values(AssistantTask, "ck_assistant_tasks_suspend_reason")

    assert _allowed_values(
        engine, "assistant_run_failures", "ck_assistant_run_failures_category"
    ) == _orm_allowed_values(AssistantRunFailure, "ck_assistant_run_failures_category")


def test_the_business_enum_and_the_database_agree_on_suspend_reasons() -> None:
    """第三份副本：业务枚举。加了新停法却忘了迁移，活就落不了库。"""
    engine = _engine_at_v38()
    migrations.migrate_to_v39(engine)

    allowed = _allowed_values(engine, "assistant_tasks", "ck_assistant_tasks_suspend_reason")
    assert {reason.value for reason in SuspendReason} == allowed


def test_v39_is_registered_in_the_migration_chain() -> None:
    assert (39, migrations.migrate_to_v39) in migrations._MIGRATIONS
