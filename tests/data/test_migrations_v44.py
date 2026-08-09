"""v44：sessions.focused_user_task_id → owner_user_task_id（语义重定义）。"""

from __future__ import annotations

from sqlalchemy import inspect, text

from src.data import migrations


def test_v44_is_registered_in_migrations() -> None:
    """v44 仍在 _MIGRATIONS 注册表里（不再断言是最新——v45 已接上）。"""
    assert (44, migrations.migrate_to_v44) in migrations._MIGRATIONS


def test_v44_renames_focused_to_owner() -> None:
    """迁移把 focused_user_task_id 改名为 owner_user_task_id。"""
    from tests.data.test_migrations_v41 import _engine_at_v40

    engine = _engine_at_v40()
    migrations.migrate_to_v41(engine)
    migrations.migrate_to_v42(engine)
    migrations.migrate_to_v43(engine)
    migrations.migrate_to_v44(engine)

    # sessions 表可能不存在于迁移测试链（从 v36 起只建 assistant_tasks）
    inspector = inspect(engine)
    if "sessions" not in inspector.get_table_names():
        return

    cols = {c["name"] for c in inspector.get_columns("sessions")}
    assert "owner_user_task_id" in cols
    assert "focused_user_task_id" not in cols

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version FROM schema_version")).scalar()
    assert version == 44
