"""v38：assistant_tasks.waiting_on —— 暂停时球在谁手上。

这一列是持久化的通知意图：状态落库即等于通知已发出。所以它的正确性得在数据层
就锁死——回填要对、约束要拦得住、重跑不能把已经改过的值冲掉。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.business.task_collaboration.models import (
    SuspendReason,
    WaitingOn,
    waiting_on_for_reason,
)
from src.data import migrations
from src.data.models_sqlite import Base
from src.data.repos import AssistantTaskRepository


TASK_INDEXES = {
    "idx_assistant_tasks_graph_status",
    "idx_assistant_tasks_graph_parent",
    "idx_assistant_tasks_session_message",
    "idx_assistant_tasks_graph_version",
}

EXPECTED_WAITING_ON = {"user", "assistant", "system"}

# 每种暂停原因一行种子数据，用来验证回填。
SEEDED_REASONS = (
    "waiting_user",
    "waiting_system",
    "user_stop",
    "budget_exhausted",
    "interrupted",
)


def _engine_at_v37():
    """手搭 v37 schema（有 suspend_reason、还没有 waiting_on）+ 种子数据。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (37)"))
        conn.execute(
            text(
                """
                CREATE TABLE assistant_tasks (
                    task_id TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    root_task_id TEXT,
                    parent_task_id TEXT,
                    session_id TEXT NOT NULL,
                    user_message_sequence INTEGER,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending_dispatch'
                        CONSTRAINT ck_assistant_tasks_status
                        CHECK (status IN (
                            'pending_dispatch', 'running', 'suspended',
                            'completed', 'failed', 'cancelled'
                        )),
                    suspend_reason TEXT
                        CONSTRAINT ck_assistant_tasks_suspend_reason
                        CHECK (suspend_reason IS NULL OR suspend_reason IN (
                            'waiting_user', 'waiting_system', 'user_stop',
                            'budget_exhausted', 'interrupted'
                        )),
                    assignee_type TEXT
                        CONSTRAINT ck_assistant_tasks_assignee_type
                        CHECK (
                            assignee_type IS NULL OR assignee_type IN (
                                'ephemeral_subagent', 'specialist'
                            )
                        ),
                    assignee_id TEXT,
                    owner_session_id TEXT,
                    capability_scope TEXT,
                    graph_version INTEGER NOT NULL DEFAULT 1,
                    task_version INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    failed_at DATETIME,
                    cancelled_at DATETIME,
                    requires_confirmation INTEGER NOT NULL DEFAULT 0,
                    workspace_root TEXT,
                    CONSTRAINT ck_assistant_tasks_suspend_reason_required CHECK (
                        (status = 'suspended' AND suspend_reason IS NOT NULL)
                        OR
                        (status != 'suspended' AND suspend_reason IS NULL)
                    )
                )
                """
            )
        )
        for index_sql in (
            "CREATE INDEX idx_assistant_tasks_graph_status ON assistant_tasks(graph_id, status)",
            "CREATE INDEX idx_assistant_tasks_graph_parent "
            "ON assistant_tasks(graph_id, parent_task_id)",
            "CREATE INDEX idx_assistant_tasks_session_message "
            "ON assistant_tasks(session_id, user_message_sequence)",
            "CREATE INDEX idx_assistant_tasks_graph_version "
            "ON assistant_tasks(graph_id, task_version)",
        ):
            conn.execute(text(index_sql))

        for reason in SEEDED_REASONS:
            conn.execute(
                text(
                    """
                    INSERT INTO assistant_tasks (
                        task_id, graph_id, session_id, title, description,
                        status, suspend_reason, graph_version, task_version,
                        created_at, updated_at, requires_confirmation
                    ) VALUES (
                        :task_id, 'tg_seed', 'ast_seed', 'seeded', 'seeded desc',
                        'suspended', :reason, 1, 1,
                        '2026-07-28 10:00:00', '2026-07-28 10:05:00', 0
                    )
                    """
                ),
                {"task_id": f"tsk_{reason}", "reason": reason},
            )

        # 一行完整的非暂停任务，用来验证迁移不动无关列、且 waiting_on 保持 NULL
        conn.execute(
            text(
                """
                INSERT INTO assistant_tasks (
                    task_id, graph_id, root_task_id, parent_task_id,
                    session_id, user_message_sequence, title, description,
                    status, suspend_reason, assignee_type, assignee_id,
                    owner_session_id, capability_scope, graph_version,
                    task_version, created_at, updated_at, completed_at,
                    failed_at, cancelled_at, requires_confirmation,
                    workspace_root
                ) VALUES (
                    'tsk_running', 'tg_existing', 'tsk_root', 'tsk_parent',
                    'ast_existing', 42, 'existing title', 'existing description',
                    'running', NULL, 'specialist', 'sp_existing',
                    'ast_owner', '["read_file"]', 3,
                    7, '2026-07-28 10:00:00', '2026-07-28 10:05:00', NULL,
                    NULL, NULL, 1,
                    'E:/worktrees/existing'
                )
                """
            )
        )
    return engine


def _waiting_on_by_task(engine) -> dict[str, str | None]:
    with engine.connect() as conn:
        return {
            row[0]: row[1]
            for row in conn.execute(text("SELECT task_id, waiting_on FROM assistant_tasks"))
        }


def test_v38_backfills_waiting_on_from_suspend_reason() -> None:
    engine = _engine_at_v37()
    migrations.migrate_to_v38(engine)

    actual = _waiting_on_by_task(engine)
    assert actual["tsk_waiting_user"] == "user"
    assert actual["tsk_user_stop"] == "user"
    assert actual["tsk_budget_exhausted"] == "assistant"
    # waiting_system 的生产者是 ask_parent 和未知情形兜底，两者都该由主助理处理；
    # 归到 system 会让它进 recovery 自动重试，那是错的。
    assert actual["tsk_waiting_system"] == "assistant"
    assert actual["tsk_interrupted"] == "system"
    # 非暂停任务不该有 waiting_on
    assert actual["tsk_running"] is None


def test_v38_backfill_matches_the_business_mapping() -> None:
    """迁移里的 CASE 与 models.waiting_on_for_reason 是同一份语义，不许漂移。"""
    engine = _engine_at_v37()
    migrations.migrate_to_v38(engine)

    actual = _waiting_on_by_task(engine)
    for reason in SEEDED_REASONS:
        expected = waiting_on_for_reason(reason)
        assert actual[f"tsk_{reason}"] == expected.value, (
            f"{reason}: 迁移回填 {actual[f'tsk_{reason}']}，"
            f"业务映射 {expected.value}"
        )


def test_v38_rerun_does_not_clobber_an_explicitly_changed_waiting_on() -> None:
    """重跑迁移不能把已被改写过的 waiting_on 冲回推导值。

    waiting_on 迟早不再是 suspend_reason 的纯函数——同一个原因下球会换手（例如进程
    重启后，原本等主助理的活要改成等用户）。迁移重跑时必须搬运既有值，不是重新推导。
    """
    engine = _engine_at_v37()
    migrations.migrate_to_v38(engine)

    # 模拟球换手：budget_exhausted 推导是 assistant，这里显式改成 user
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE assistant_tasks SET waiting_on = 'user' WHERE task_id = :t"),
            {"t": "tsk_budget_exhausted"},
        )

    migrations.migrate_to_v38(engine)

    assert _waiting_on_by_task(engine)["tsk_budget_exhausted"] == "user"


def test_v38_advances_version_rebuilds_indexes_and_preserves_every_column() -> None:
    engine = _engine_at_v37()
    migrations.migrate_to_v38(engine)
    migrations.migrate_to_v38(engine)  # 幂等

    with engine.connect() as conn:
        assert conn.execute(text("SELECT version FROM schema_version")).scalar() == 38
        indexes = {
            row[1]
            for row in conn.execute(text("PRAGMA index_list(assistant_tasks)"))
            if str(row[1]).startswith("idx_assistant_tasks_")
        }
        assert indexes == TASK_INDEXES

        row = conn.execute(
            text("SELECT * FROM assistant_tasks WHERE task_id = 'tsk_running'")
        ).one()
        assert dict(row._mapping) == {
            "task_id": "tsk_running",
            "graph_id": "tg_existing",
            "root_task_id": "tsk_root",
            "parent_task_id": "tsk_parent",
            "session_id": "ast_existing",
            "user_message_sequence": 42,
            "title": "existing title",
            "description": "existing description",
            "status": "running",
            "suspend_reason": None,
            "waiting_on": None,
            "assignee_type": "specialist",
            "assignee_id": "sp_existing",
            "owner_session_id": "ast_owner",
            "capability_scope": '["read_file"]',
            "graph_version": 3,
            "task_version": 7,
            "created_at": "2026-07-28 10:00:00",
            "updated_at": "2026-07-28 10:05:00",
            "completed_at": None,
            "failed_at": None,
            "cancelled_at": None,
            "requires_confirmation": 1,
            "workspace_root": "E:/worktrees/existing",
        }

    assert (38, migrations.migrate_to_v38) in migrations._MIGRATIONS


def test_v38_persists_every_waiting_on_through_repository() -> None:
    engine = _engine_at_v37()
    migrations.migrate_to_v38(engine)
    Session = sessionmaker(bind=engine, future=True)

    assert {w.value for w in WaitingOn} == EXPECTED_WAITING_ON

    for index, waiting_on in enumerate(sorted(EXPECTED_WAITING_ON)):
        with Session.begin() as session:
            repo = AssistantTaskRepository(session)
            repo.create_task(
                task_id=f"tsk_wo_{index}",
                graph_id="tg_wo",
                session_id="ast_wo",
                title="t",
                description="d",
                root_task_id="tsk_wo_0",
            )
            repo.update_status(
                f"tsk_wo_{index}",
                status="suspended",
                suspend_reason="waiting_system",
                waiting_on=waiting_on,
            )

    stored = _waiting_on_by_task(engine)
    assert {stored[f"tsk_wo_{i}"] for i in range(len(EXPECTED_WAITING_ON))} == EXPECTED_WAITING_ON


def test_orm_schema_carries_the_same_waiting_on_constraints() -> None:
    """ORM 定义与迁移 DDL 不许漂移——干净库走 create_all，约束必须一样在。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    for index, waiting_on in enumerate(sorted(EXPECTED_WAITING_ON)):
        with Session.begin() as session:
            repo = AssistantTaskRepository(session)
            repo.create_task(
                task_id=f"tsk_orm_{index}",
                graph_id="tg_orm",
                session_id="ast_orm",
                title="t",
                description="d",
                root_task_id="tsk_orm_0",
            )
            repo.update_status(
                f"tsk_orm_{index}",
                status="suspended",
                suspend_reason=SuspendReason.WAITING_SYSTEM.value,
                waiting_on=waiting_on,
            )

    stored = _waiting_on_by_task(engine)
    assert {stored[f"tsk_orm_{i}"] for i in range(len(EXPECTED_WAITING_ON))} == EXPECTED_WAITING_ON


def test_v38_rejects_unknown_waiting_on() -> None:
    """拼错的值必须当场炸——它是"通知发给谁"的唯一依据，不能静默落库。"""
    engine = _engine_at_v37()
    migrations.migrate_to_v38(engine)

    with pytest.raises(IntegrityError, match="ck_assistant_tasks_waiting_on"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE assistant_tasks SET waiting_on = 'assitant' "
                    "WHERE task_id = 'tsk_user_stop'"
                )
            )


def test_v38_requires_waiting_on_exactly_when_suspended() -> None:
    """waiting_on 与 suspend_reason 同生同灭。"""
    engine = _engine_at_v37()
    migrations.migrate_to_v38(engine)

    with pytest.raises(IntegrityError, match="ck_assistant_tasks_waiting_on_required"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE assistant_tasks SET waiting_on = NULL "
                    "WHERE task_id = 'tsk_user_stop'"
                )
            )

    with pytest.raises(IntegrityError, match="ck_assistant_tasks_waiting_on_required"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE assistant_tasks SET waiting_on = 'user' "
                    "WHERE task_id = 'tsk_running'"
                )
            )
