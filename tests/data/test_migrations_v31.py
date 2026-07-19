"""v31 终态事件按代次确认，以及 migration 注册表全局顺序门卫。"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from src.data import migrations


def _engine_at_v30():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (30)"))
        conn.execute(
            text(
                "CREATE TABLE scheduled_task_runs ("
                "run_id TEXT PRIMARY KEY, scheduled_task_id TEXT NOT NULL, "
                "session_id TEXT NOT NULL, started_at DATETIME, finished_at DATETIME, "
                "status TEXT NOT NULL, summary TEXT, failure_reason TEXT, created_at DATETIME)"
            )
        )
    return engine


def test_v31_adds_terminal_delivery_ack_and_pending_index() -> None:
    engine = _engine_at_v30()

    migrations.migrate_to_v31(engine)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(scheduled_task_runs)"))}
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(scheduled_task_runs)"))}
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
    assert "terminal_event_delivered_at" in columns
    assert "terminal_event_version" in columns
    assert "idx_runs_terminal_event_pending" in indexes
    assert version == 31

    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO scheduled_task_runs "
                "(run_id, scheduled_task_id, session_id, status) "
                "VALUES ('schr_legacy', 'sch_legacy', 'ast_legacy', 'running')"
            )
        )
        event_version = conn.execute(
            text(
                "SELECT terminal_event_version FROM scheduled_task_runs "
                "WHERE run_id = 'schr_legacy'"
            )
        ).scalar_one()
    assert event_version == 0


def test_v31_is_idempotent() -> None:
    engine = _engine_at_v30()

    migrations.migrate_to_v31(engine)
    migrations.migrate_to_v31(engine)

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
    assert version == 31


def test_migration_registry_is_strictly_increasing_and_v31_follows_v30() -> None:
    """runner 依赖注册顺序推进 current_version；乱序会静默跳过较小版本。"""
    versions = [version for version, _ in migrations._MIGRATIONS]

    assert versions == sorted(set(versions))
    assert versions.index(30) == versions.index(29) + 1
    assert versions.index(31) == versions.index(30) + 1
