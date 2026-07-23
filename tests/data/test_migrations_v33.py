"""v33：持久化 external coding 进程身份与 fail-closed ownership。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from src.data import migrations


def _engine_at_v32():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (32)"))
        conn.execute(
            text(
                "CREATE TABLE external_coding_attempts ("
                "attempt_id TEXT PRIMARY KEY, coding_session_id TEXT NOT NULL, "
                "status TEXT NOT NULL, pid INTEGER)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO external_coding_attempts "
                "(attempt_id, coding_session_id, status, pid) "
                "VALUES ('eca_existing', 'ecs_existing', 'running', 42100)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO external_coding_attempts "
                "(attempt_id, coding_session_id, status, pid) "
                "VALUES ('eca_terminal', 'ecs_terminal', 'failed', 42101)"
            )
        )
    return engine


def _attempt_columns(engine) -> list[str]:
    with engine.connect() as conn:
        return [row[1] for row in conn.execute(text("PRAGMA table_info(external_coding_attempts)"))]


def test_v33_adds_restart_safe_process_ownership_columns_idempotently() -> None:
    engine = _engine_at_v32()

    migrations.migrate_to_v33(engine)
    migrations.migrate_to_v33(engine)

    columns = _attempt_columns(engine)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT process_create_time, termination_unconfirmed, launch_started "
                "FROM external_coding_attempts WHERE attempt_id = 'eca_existing'"
            )
        ).one()
        terminal_row = conn.execute(
            text(
                "SELECT process_create_time, termination_unconfirmed, launch_started "
                "FROM external_coding_attempts WHERE attempt_id = 'eca_terminal'"
            )
        ).one()
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
        index_names = {
            item[1] for item in conn.execute(text("PRAGMA index_list(external_coding_attempts)"))
        }
        trigger_names = {
            item[0]
            for item in conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'trigger' AND tbl_name = 'external_coding_attempts'"
                )
            )
        }

    assert columns.count("process_create_time") == 1
    assert columns.count("termination_unconfirmed") == 1
    assert columns.count("launch_started") == 1
    assert row.process_create_time is None
    assert row.termination_unconfirmed == 1
    assert row.launch_started == 1
    assert terminal_row.process_create_time is None
    assert terminal_row.termination_unconfirmed == 0
    assert terminal_row.launch_started == 1
    assert "uq_external_coding_attempts_active_session" in index_names
    assert trigger_names == {
        "trg_external_coding_attempts_ownership_insert",
        "trg_external_coding_attempts_ownership_update",
    }
    # v33 已注册即可；不锁定它是最后一个，否则每加一个迁移都要改这行。
    assert (33, migrations.migrate_to_v33) in migrations._MIGRATIONS
    assert version == 33

    with pytest.raises(IntegrityError, match="invalid external coding process ownership state"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO external_coding_attempts "
                    "(attempt_id, coding_session_id, status, pid, "
                    "termination_unconfirmed, launch_started) "
                    "VALUES ('eca_invalid_running', 'ecs_invalid_running', "
                    "'running', NULL, 0, 0)"
                )
            )
    with pytest.raises(IntegrityError, match="invalid external coding process ownership state"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO external_coding_attempts "
                    "(attempt_id, coding_session_id, status, pid, process_create_time, "
                    "termination_unconfirmed, launch_started) "
                    "VALUES ('eca_invalid_unlaunched', 'ecs_invalid_unlaunched', "
                    "'running', 42111, 100.0, 1, 0)"
                )
            )

    with pytest.raises(IntegrityError, match="invalid external coding process ownership state"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE external_coding_attempts SET termination_unconfirmed = 0 "
                    "WHERE attempt_id = 'eca_existing'"
                )
            )
    with pytest.raises(IntegrityError, match="invalid external coding process ownership state"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE external_coding_attempts "
                    "SET launch_started = 0, pid = NULL, process_create_time = NULL "
                    "WHERE attempt_id = 'eca_terminal'"
                )
            )
    with engine.connect() as conn:
        running_after_failed_updates = conn.execute(
            text(
                "SELECT pid, termination_unconfirmed, launch_started "
                "FROM external_coding_attempts WHERE attempt_id = 'eca_existing'"
            )
        ).one()
        terminal_after_failed_updates = conn.execute(
            text(
                "SELECT pid, termination_unconfirmed, launch_started "
                "FROM external_coding_attempts WHERE attempt_id = 'eca_terminal'"
            )
        ).one()
    assert running_after_failed_updates == (42100, 1, 1)
    assert terminal_after_failed_updates == (42101, 0, 1)


def test_v33_downgrade_removes_only_ownership_columns_and_can_upgrade_again() -> None:
    engine = _engine_at_v32()
    migrations.migrate_to_v33(engine)

    migrations.downgrade_v33(engine)

    columns = _attempt_columns(engine)
    with engine.connect() as conn:
        existing = conn.execute(
            text(
                "SELECT status, pid FROM external_coding_attempts "
                "WHERE attempt_id = 'eca_existing'"
            )
        ).one()
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
        triggers = conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'trigger' AND tbl_name = 'external_coding_attempts'"
            )
        ).all()
    assert "process_create_time" not in columns
    assert "termination_unconfirmed" not in columns
    assert "launch_started" not in columns
    assert existing == ("running", 42100)
    assert triggers == []
    assert version == 32

    migrations.migrate_to_v33(engine)
    assert {
        "process_create_time",
        "termination_unconfirmed",
        "launch_started",
    }.issubset(_attempt_columns(engine))
