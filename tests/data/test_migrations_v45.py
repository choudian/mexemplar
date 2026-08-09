"""v45：assistant_tasks.status 加 delivered + skipped。"""

from __future__ import annotations

from sqlalchemy import inspect, text

from src.data import migrations


def test_v45_is_registered_in_migrations() -> None:
    assert (45, migrations.migrate_to_v45) in migrations._MIGRATIONS


def test_v45_adds_new_status_values() -> None:
    """迁移后 CHECK 约束接受 delivered 和 skipped。"""
    from tests.data.test_migrations_v41 import _engine_at_v40

    engine = _engine_at_v40()
    migrations.migrate_to_v41(engine)
    migrations.migrate_to_v42(engine)
    migrations.migrate_to_v43(engine)
    migrations.migrate_to_v44(engine)
    migrations.migrate_to_v45(engine)

    with engine.begin() as conn:
        # delivered 能写
        conn.execute(
            text(
                "INSERT INTO assistant_tasks "
                "(task_id, graph_id, session_id, title, description, status) "
                "VALUES ('tsk_delivered', 'tg', 's', 't', 'd', 'delivered')"
            )
        )
        # skipped 能写
        conn.execute(
            text(
                "INSERT INTO assistant_tasks "
                "(task_id, graph_id, session_id, title, description, status) "
                "VALUES ('tsk_skipped', 'tg', 's', 't', 'd', 'skipped')"
            )
        )
        # 旧值仍然能用
        conn.execute(
            text(
                "INSERT INTO assistant_tasks "
                "(task_id, graph_id, session_id, title, description, status) "
                "VALUES ('tsk_completed', 'tg', 's', 't', 'd', 'completed')"
            )
        )


def test_v45_preserves_user_task_id_and_indexes() -> None:
    """迁移保留 user_task_id 列和 5 个索引（含 v43 加的第 5 个）。"""
    from tests.data.test_migrations_v41 import _engine_at_v40

    engine = _engine_at_v40()
    migrations.migrate_to_v41(engine)
    migrations.migrate_to_v42(engine)
    migrations.migrate_to_v43(engine)
    migrations.migrate_to_v44(engine)
    migrations.migrate_to_v45(engine)

    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("assistant_tasks")}
    assert "user_task_id" in cols

    index_names = {idx["name"] for idx in inspector.get_indexes("assistant_tasks")}
    assert "idx_assistant_tasks_graph_status" in index_names
    assert "idx_assistant_tasks_graph_parent" in index_names
    assert "idx_assistant_tasks_session_message" in index_names
    assert "idx_assistant_tasks_graph_version" in index_names
    assert "idx_assistant_tasks_user_task" in index_names

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version FROM schema_version")).scalar()
    assert version == 45
