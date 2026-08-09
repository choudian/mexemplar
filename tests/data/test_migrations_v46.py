"""v46：assistant_tasks.status 的 completed 改名为 done。"""

from __future__ import annotations

from sqlalchemy import inspect, text

from src.data import migrations


def test_v46_is_registered_in_migrations() -> None:
    assert (46, migrations.migrate_to_v46) in migrations._MIGRATIONS


def test_v46_renames_completed_to_done() -> None:
    """迁移后 CHECK 接受 done，拒绝 completed；存量 completed 回填为 done。"""
    from tests.data.test_migrations_v41 import _engine_at_v40

    engine = _engine_at_v40()
    migrations.migrate_to_v41(engine)
    migrations.migrate_to_v42(engine)
    migrations.migrate_to_v43(engine)
    migrations.migrate_to_v44(engine)
    migrations.migrate_to_v45(engine)

    # 埋一条 completed 行
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assistant_tasks "
                "(task_id, graph_id, session_id, title, description, status) "
                "VALUES ('tsk_v46_test', 'tg', 's', 't', 'd', 'completed')"
            )
        )

    migrations.migrate_to_v46(engine)

    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM assistant_tasks WHERE task_id = 'tsk_v46_test'")
        ).scalar()
    assert status == "done"

    # done 能写，completed 被拒
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assistant_tasks "
                "(task_id, graph_id, session_id, title, description, status) "
                "VALUES ('tsk_v46_new', 'tg', 's', 't', 'd', 'done')"
            )
        )

    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO assistant_tasks "
                    "(task_id, graph_id, session_id, title, description, status) "
                    "VALUES ('tsk_v46_bad', 'tg', 's', 't', 'd', 'completed')"
                )
            )


def test_v46_preserves_indexes_and_user_task_id() -> None:
    """迁移保留 5 个索引 + user_task_id 列。"""
    from tests.data.test_migrations_v41 import _engine_at_v40

    engine = _engine_at_v40()
    migrations.migrate_to_v41(engine)
    migrations.migrate_to_v42(engine)
    migrations.migrate_to_v43(engine)
    migrations.migrate_to_v44(engine)
    migrations.migrate_to_v45(engine)
    migrations.migrate_to_v46(engine)

    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("assistant_tasks")}
    assert "user_task_id" in cols

    index_names = {idx["name"] for idx in inspector.get_indexes("assistant_tasks")}
    assert "idx_assistant_tasks_user_task" in index_names

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version FROM schema_version")).scalar()
    assert version == 46
