"""v36：执行记录补上"这次开工跑在哪个会话里"。"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from src.data import migrations


def _engine_at_v35():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (35)"))
        conn.execute(
            text(
                "CREATE TABLE assistant_task_attempts ("
                "attempt_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
                "executor_type TEXT NOT NULL, executor_id TEXT NOT NULL, "
                "status TEXT NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assistant_task_attempts "
                "(attempt_id, task_id, executor_type, executor_id, status) "
                "VALUES ('att_old', 'tsk_old', 'ephemeral_subagent', 'tsk_old', 'succeeded')"
            )
        )
    return engine


def _attempt_columns(engine) -> list[str]:
    with engine.connect() as conn:
        return [row[1] for row in conn.execute(text("PRAGMA table_info(assistant_task_attempts)"))]


def _version(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version FROM schema_version")).scalar_one()


def test_v36_adds_executor_session_column_idempotently() -> None:
    engine = _engine_at_v35()
    assert "executor_session_id" not in _attempt_columns(engine)

    migrations.migrate_to_v36(engine)
    migrations.migrate_to_v36(engine)

    assert "executor_session_id" in _attempt_columns(engine)
    assert _version(engine) == 36


def test_v36_leaves_existing_rows_unbound() -> None:
    """既有行的执行早已结束，补造身份只会伪造无法验证的关联。"""
    engine = _engine_at_v35()

    migrations.migrate_to_v36(engine)

    with engine.connect() as conn:
        value = conn.execute(
            text(
                "SELECT executor_session_id FROM assistant_task_attempts "
                "WHERE attempt_id = 'att_old'"
            )
        ).scalar_one()
    assert value is None


def test_v36_skips_when_attempts_table_absent() -> None:
    """部分建表的测试库不能被硬 ALTER 打挂（v34 迁移踩过这个坑）。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (35)"))

    migrations.migrate_to_v36(engine)

    assert _version(engine) == 36


def test_v36_downgrade_removes_column_and_can_upgrade_again() -> None:
    engine = _engine_at_v35()
    migrations.migrate_to_v36(engine)

    migrations.downgrade_from_v36(engine)

    assert "executor_session_id" not in _attempt_columns(engine)
    assert _version(engine) == 35

    migrations.migrate_to_v36(engine)
    assert "executor_session_id" in _attempt_columns(engine)
    assert _version(engine) == 36
