"""v37：Assistant Task 暂停原因约束与领域枚举保持一致。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.business.task_collaboration.models import SuspendReason, waiting_on_for_reason
from src.data import migrations
from src.data.models_sqlite import Base
from src.data.repos import AssistantTaskRepository


TASK_INDEXES = {
    "idx_assistant_tasks_graph_status",
    "idx_assistant_tasks_graph_parent",
    "idx_assistant_tasks_session_message",
    "idx_assistant_tasks_graph_version",
}

EXPECTED_SUSPEND_REASONS = {
    "waiting_user",
    "waiting_system",
    "user_stop",
    "budget_exhausted",
    "interrupted",
}


def _engine_at_v36():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (36)"))
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
                            'waiting_user', 'waiting_system', 'user_stop'
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
            "CREATE INDEX idx_assistant_tasks_graph_status " "ON assistant_tasks(graph_id, status)",
            "CREATE INDEX idx_assistant_tasks_graph_parent "
            "ON assistant_tasks(graph_id, parent_task_id)",
            "CREATE INDEX idx_assistant_tasks_session_message "
            "ON assistant_tasks(session_id, user_message_sequence)",
            "CREATE INDEX idx_assistant_tasks_graph_version "
            "ON assistant_tasks(graph_id, task_version)",
        ):
            conn.execute(text(index_sql))
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
                    'tsk_existing', 'tg_existing', 'tsk_root', 'tsk_parent',
                    'ast_existing', 42, 'existing title', 'existing description',
                    'suspended', 'waiting_user', 'specialist', 'sp_existing',
                    'ast_owner', '["read_file"]', 3,
                    7, '2026-07-28 10:00:00', '2026-07-28 10:05:00', NULL,
                    NULL, NULL, 1,
                    'E:/worktrees/existing'
                )
                """
            )
        )
    return engine


def test_v37_accepts_budget_exhausted_through_repository_and_preserves_rows() -> None:
    engine = _engine_at_v36()

    # 跑完整迁移链而不是只跑 v37：下面用的 Repository 走的是最新 ORM 定义，
    # 库停在旧版本就会缺列。验证的仍是 v37 引入的 suspend_reason 约束。
    migrations.run_migrations(engine)

    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        repo = AssistantTaskRepository(session)
        updated = repo.update_status(
            "tsk_existing",
            status="suspended",
            suspend_reason=SuspendReason.BUDGET_EXHAUSTED.value,
            waiting_on=waiting_on_for_reason(SuspendReason.BUDGET_EXHAUSTED),
        )

    assert updated is not None
    with engine.connect() as conn:
        persisted = conn.execute(
            text(
                "SELECT status, suspend_reason FROM assistant_tasks "
                "WHERE task_id = 'tsk_existing'"
            )
        ).one()
    assert persisted == ("suspended", "budget_exhausted")


def test_v37_persists_every_suspend_reason_through_repository() -> None:
    assert {reason.value for reason in SuspendReason} == EXPECTED_SUSPEND_REASONS
    engine = _engine_at_v36()
    migrations.run_migrations(engine)  # 同上：Repository 走最新 ORM

    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        repo = AssistantTaskRepository(session)
        for reason in SuspendReason:
            task_id = f"tsk_{reason.value}"
            repo.create_task(
                task_id=task_id,
                graph_id="tg_all_reasons",
                session_id="ast_all_reasons",
                title=reason.value,
                description="suspend reason persistence contract",
            )
            updated = repo.update_status(
                task_id,
                status="suspended",
                suspend_reason=reason.value,
                waiting_on=waiting_on_for_reason(reason),
            )
            assert updated is not None

    with engine.connect() as conn:
        persisted_reasons = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT suspend_reason FROM assistant_tasks "
                    "WHERE graph_id = 'tg_all_reasons'"
                )
            )
        }
    assert persisted_reasons == EXPECTED_SUSPEND_REASONS


def test_v37_advances_version_and_rebuilds_all_assistant_task_indexes() -> None:
    engine = _engine_at_v36()

    migrations.migrate_to_v37(engine)
    migrations.migrate_to_v37(engine)

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
        indexes = {
            row[1]
            for row in conn.execute(text("PRAGMA index_list(assistant_tasks)"))
            if row[1].startswith("idx_assistant_tasks_")
        }
        existing_row = dict(
            conn.execute(text("SELECT * FROM assistant_tasks WHERE task_id = 'tsk_existing'"))
            .one()
            ._mapping
        )

    assert version == 37
    assert indexes == TASK_INDEXES
    assert existing_row == {
        "task_id": "tsk_existing",
        "graph_id": "tg_existing",
        "root_task_id": "tsk_root",
        "parent_task_id": "tsk_parent",
        "session_id": "ast_existing",
        "user_message_sequence": 42,
        "title": "existing title",
        "description": "existing description",
        "status": "suspended",
        "suspend_reason": "waiting_user",
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
    assert (37, migrations.migrate_to_v37) in migrations._MIGRATIONS


def test_orm_schema_persists_every_suspend_reason() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session.begin() as session:
        repo = AssistantTaskRepository(session)
        for reason in SuspendReason:
            task_id = f"tsk_orm_{reason.value}"
            repo.create_task(
                task_id=task_id,
                graph_id="tg_orm_reasons",
                session_id="ast_orm_reasons",
                title=reason.value,
                description="ORM suspend reason persistence contract",
            )
            updated = repo.update_status(
                task_id,
                status="suspended",
                suspend_reason=reason.value,
                waiting_on=waiting_on_for_reason(reason),
            )
            assert updated is not None

    with engine.connect() as conn:
        persisted_reasons = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT suspend_reason FROM assistant_tasks "
                    "WHERE graph_id = 'tg_orm_reasons'"
                )
            )
        }
    assert persisted_reasons == EXPECTED_SUSPEND_REASONS


def test_v37_still_rejects_unknown_suspend_reasons() -> None:
    engine = _engine_at_v36()
    migrations.migrate_to_v37(engine)

    with pytest.raises(IntegrityError, match="ck_assistant_tasks_suspend_reason"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE assistant_tasks SET suspend_reason = 'unknown_reason' "
                    "WHERE task_id = 'tsk_existing'"
                )
            )
