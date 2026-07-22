"""v32：scheduled task 常驻会话绑定与 run 消息窗口。"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from src.data import migrations


def _engine_at_v31():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (31)"))
        conn.execute(
            text(
                "CREATE TABLE sessions ("
                "session_id TEXT PRIMARY KEY, agent_type TEXT NOT NULL, "
                "status TEXT NOT NULL, source TEXT NOT NULL, "
                "scheduled_task_id TEXT, is_scheduled INTEGER NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE scheduled_tasks ("
                "scheduled_task_id TEXT PRIMARY KEY, is_deleted INTEGER NOT NULL DEFAULT 0)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE scheduled_task_runs ("
                "run_id TEXT PRIMARY KEY, scheduled_task_id TEXT NOT NULL, "
                "session_id TEXT NOT NULL, started_at DATETIME, status TEXT NOT NULL)"
            )
        )
    return engine


def test_v32_adds_current_session_and_run_message_window_columns() -> None:
    engine = _engine_at_v31()

    migrations.migrate_to_v32(engine)

    with engine.connect() as conn:
        task_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(scheduled_tasks)"))}
        run_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(scheduled_task_runs)"))
        }
        task_indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(scheduled_tasks)"))}
        run_indexes = {
            row[1] for row in conn.execute(text("PRAGMA index_list(scheduled_task_runs)"))
        }
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()

    assert "session_id" in task_columns
    assert {"baseline_message_sequence", "trigger_message_sequence"}.issubset(run_columns)
    assert "uq_scheduled_tasks_session" in task_indexes
    assert "uq_runs_active_per_session" in run_indexes
    assert "uq_runs_session_trigger" in run_indexes
    assert version == 32


def test_v32_backfills_latest_relationship_valid_scheduled_session() -> None:
    engine = _engine_at_v31()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO scheduled_tasks (scheduled_task_id) "
                "VALUES ('sch_reuse'), ('sch_without_valid_history')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO sessions "
                "(session_id, agent_type, status, source, scheduled_task_id, is_scheduled) "
                "VALUES "
                "('ast_old', 'assistant', 'active', 'scheduled', 'sch_reuse', 1), "
                "('ast_latest', 'assistant', 'completed', 'scheduled', 'sch_reuse', 1), "
                "('ast_invalid_status', 'assistant', 'deleted', 'scheduled', 'sch_reuse', 1), "
                "('ast_wrong_task', 'assistant', 'active', 'scheduled', 'sch_other', 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO scheduled_task_runs "
                "(run_id, scheduled_task_id, session_id, started_at, status) "
                "VALUES "
                "('schr_old', 'sch_reuse', 'ast_old', '2026-07-18 09:00:00', 'succeeded'), "
                "('schr_latest', 'sch_reuse', 'ast_latest', '2026-07-19 09:00:00', 'failed'), "
                "('schr_invalid_status', 'sch_reuse', 'ast_invalid_status', "
                "'2026-07-20 10:00:00', 'failed'), "
                "('schr_wrong', 'sch_without_valid_history', 'ast_wrong_task', "
                "'2026-07-20 09:00:00', 'succeeded')"
            )
        )

    migrations.migrate_to_v32(engine)

    with engine.connect() as conn:
        rows = dict(
            conn.execute(
                text(
                    "SELECT scheduled_task_id, session_id FROM scheduled_tasks "
                    "ORDER BY scheduled_task_id"
                )
            ).all()
        )

    assert rows["sch_reuse"] == "ast_latest"
    assert rows["sch_without_valid_history"] is None


def test_v32_is_idempotent_and_registered_as_latest_migration() -> None:
    engine = _engine_at_v31()

    migrations.migrate_to_v32(engine)
    migrations.migrate_to_v32(engine)

    with engine.connect() as conn:
        task_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(scheduled_tasks)"))]
        run_columns = [
            row[1] for row in conn.execute(text("PRAGMA table_info(scheduled_task_runs)"))
        ]
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()

    assert task_columns.count("session_id") == 1
    assert run_columns.count("baseline_message_sequence") == 1
    assert run_columns.count("trigger_message_sequence") == 1
    assert (32, migrations.migrate_to_v32) in migrations._MIGRATIONS
    assert version == 32


def test_v32_downgrade_removes_only_reuse_columns_and_can_upgrade_again() -> None:
    engine = _engine_at_v31()
    migrations.migrate_to_v32(engine)

    migrations.downgrade_v32(engine)

    with engine.connect() as conn:
        task_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(scheduled_tasks)"))}
        run_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(scheduled_task_runs)"))
        }
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
    assert "session_id" not in task_columns
    assert "baseline_message_sequence" not in run_columns
    assert "trigger_message_sequence" not in run_columns
    assert version == 31

    migrations.migrate_to_v32(engine)
    with engine.connect() as conn:
        upgraded_version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
    assert upgraded_version == 32
