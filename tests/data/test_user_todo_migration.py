from __future__ import annotations

from sqlalchemy import create_engine, text

from src.data import migrations


def test_v18_migration_creates_user_todos_table_and_indexes() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (17)"))

    migrations.migrate_to_v18(engine)
    migrations.migrate_to_v18(engine)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(user_todos)"))}
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(user_todos)"))}
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()

    assert {
        "todo_id",
        "title",
        "description",
        "status",
        "priority",
        "sort_order",
        "created_at",
        "updated_at",
        "completed_at",
    }.issubset(columns)
    assert "idx_user_todos_status_created" in indexes
    assert "idx_user_todos_priority_created" in indexes
    assert version == 18


def test_v18_registered_in_migration_steps() -> None:
    versions = [version for version, _ in migrations._MIGRATIONS]
    assert 18 in versions
