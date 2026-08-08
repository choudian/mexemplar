"""v42：user_tasks 用户层任务表 + sessions.focused_user_task_id 列。

注：v42 建表时此列语义为「聚焦指针」；v44 已将其重命名为
``owner_user_task_id`` 并重定义为「执行体 session 的出生归属」。
本测试只验证迁移到 v42 这一步的中间态，不涉及 v44 的重定义。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from src.data import migrations


def test_v42_is_registered_in_migrations() -> None:
    """v42 仍在 _MIGRATIONS 注册表里（不再断言是最新——v43 已接上）。"""
    assert (42, migrations.migrate_to_v42) in migrations._MIGRATIONS


def test_v42_creates_user_tasks_table_and_sessions_column() -> None:
    """迁移建了 user_tasks 表（含 CHECK + 索引）+ sessions.focused_user_task_id 列（v42 中间态）。"""
    from tests.data.test_migrations_v41 import _engine_at_v40

    engine = _engine_at_v40()
    migrations.migrate_to_v41(engine)
    migrations.migrate_to_v42(engine)

    inspector = inspect(engine)

    # user_tasks 表存在且列齐全
    assert "user_tasks" in inspector.get_table_names()
    task_cols = {c["name"] for c in inspector.get_columns("user_tasks")}
    assert {"task_id", "session_id", "title", "status", "created_at", "completed_at"} <= task_cols

    # sessions 列仅在 sessions 表存在时验证（迁移测试链从 v36 起，可能不含 sessions）
    if "sessions" in inspector.get_table_names():
        session_cols = {c["name"] for c in inspector.get_columns("sessions")}
        assert "focused_user_task_id" in session_cols

    # 索引存在
    index_names = {idx["name"] for idx in inspector.get_indexes("user_tasks")}
    assert "idx_user_tasks_session_created" in index_names
    assert "idx_user_tasks_status" in index_names

    # schema version 推进到 42
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version FROM schema_version")).scalar()
    assert version == 42


def test_v42_status_check_enforces_four_values() -> None:
    """CHECK 约束只接受 active/cooling/done/dropped。"""
    from tests.data.test_migrations_v40 import _engine_at_v39
    from tests.data.test_migrations_v41 import _engine_at_v40

    engine = _engine_at_v40()
    migrations.migrate_to_v41(engine)
    migrations.migrate_to_v42(engine)

    valid_statuses = ("active", "cooling", "done", "dropped")
    for status in valid_statuses:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO user_tasks (task_id, session_id, title, status) "
                    "VALUES (:id, 's', 't', :status)"
                ),
                {"id": f"utsk_test_{status}", "status": status},
            )

    # 非法 status 被拒
    with __import__("pytest").raises(Exception):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO user_tasks (task_id, session_id, title, status) "
                    "VALUES ('utsk_bad', 's', 't', 'suspended')"
                )
            )
