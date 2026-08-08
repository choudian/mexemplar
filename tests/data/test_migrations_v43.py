"""v43：assistant_tasks 加 user_task_id 列（图根归属）。"""

from __future__ import annotations

from sqlalchemy import inspect, text

from src.data import migrations


def test_v43_is_registered_in_migrations() -> None:
    """v43 仍在 _MIGRATIONS 注册表里（v44 已接上）。"""
    assert (43, migrations.migrate_to_v43) in migrations._MIGRATIONS


def test_v43_adds_user_task_id_column_and_index() -> None:
    """迁移加了 user_task_id 列 + partial index。"""
    from tests.data.test_migrations_v41 import _engine_at_v40

    engine = _engine_at_v40()
    migrations.migrate_to_v41(engine)
    migrations.migrate_to_v42(engine)
    migrations.migrate_to_v43(engine)

    inspector = inspect(engine)

    # 列存在
    cols = {c["name"] for c in inspector.get_columns("assistant_tasks")}
    assert "user_task_id" in cols

    # 索引存在
    index_names = {idx["name"] for idx in inspector.get_indexes("assistant_tasks")}
    assert "idx_assistant_tasks_user_task" in index_names

    # schema version 推进到 43
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version FROM schema_version")).scalar()
    assert version == 43
