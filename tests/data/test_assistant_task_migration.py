from __future__ import annotations

from sqlalchemy import create_engine, text

from src.data import migrations

TASK_TABLES = {
    "assistant_tasks",
    "assistant_task_edges",
    "assistant_task_questions",
    "assistant_task_attempts",
    "assistant_task_operations",
    "assistant_task_adjudications",
    "assistant_task_claims",
    "assistant_meeting_channels",
    "assistant_meeting_messages",
    "assistant_todo_items",
}

TASK_INDEXES = {
    "idx_assistant_tasks_graph_status",
    "idx_assistant_tasks_graph_parent",
    "idx_assistant_tasks_session_message",
    "idx_assistant_tasks_graph_version",
    "idx_assistant_task_edges_graph_source",
    "idx_assistant_task_edges_graph_target",
    "idx_assistant_task_attempts_task_status",
    "idx_assistant_task_attempts_status_lease",
    "idx_assistant_task_operations_task_key",
    "uq_assistant_task_operations_non_failed_key",
    "idx_assistant_task_adjudications_task_status",
    "idx_assistant_task_adjudications_parent_status",
    "uq_assistant_task_adjudications_pending_task",
    "idx_assistant_task_claims_task_status",
    "idx_assistant_task_claims_status_lease",
    "idx_assistant_task_questions_task_status",
    "idx_assistant_task_questions_graph_status",
    "idx_assistant_task_questions_status_expires",
    "idx_assistant_meeting_messages_channel_sequence",
    "idx_assistant_todo_items_task_sort",
}

TASK_V16_INDEXES = {
    "uq_assistant_task_attempts_active_task",
    "uq_assistant_task_attempts_active_executor",
    "uq_assistant_task_claims_active_claimer",
}


def test_v15_migration_creates_task_collaboration_tables_and_indexes() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (14)"))
        conn.execute(text("""
            CREATE TABLE pending_assistant_tasks (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                payload TEXT,
                status TEXT DEFAULT 'pending'
            )
        """))
        conn.execute(text("""
            INSERT INTO pending_assistant_tasks(task_id, task_type, status)
            VALUES ('legacy_1', 'codify_as_tool', 'pending')
        """))

    migrations.migrate_to_v15(engine)
    migrations.migrate_to_v15(engine)

    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
        }
        indexes = {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'index'"))
        }
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
        legacy_count = conn.execute(
            text("SELECT count(*) FROM pending_assistant_tasks")
        ).scalar_one()

    assert TASK_TABLES.issubset(tables)
    assert TASK_INDEXES.issubset(indexes)
    assert version == 15
    assert legacy_count == 1


def test_v16_migration_adds_task_capacity_unique_indexes() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (14)"))
        conn.execute(text("""
            CREATE TABLE pending_assistant_tasks (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                payload TEXT,
                status TEXT DEFAULT 'pending'
            )
        """))

    migrations.migrate_to_v15(engine)
    migrations.migrate_to_v16(engine)
    migrations.migrate_to_v16(engine)

    with engine.connect() as conn:
        indexes = {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'index'"))
        }
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()

    assert TASK_V16_INDEXES.issubset(indexes)
    assert version == 16
