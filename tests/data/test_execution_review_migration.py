from __future__ import annotations

from sqlalchemy import create_engine, text

from src.data import migrations


def test_v20_migration_creates_execution_reviews_table_and_index() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (19)"))

    migrations.migrate_to_v20(engine)
    migrations.migrate_to_v20(engine)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(execution_reviews)"))}
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(execution_reviews)"))}
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()

    assert {
        "id",
        "turn_session_id",
        "status",
        "priority",
        "verdict",
        "findings_json",
        "advisory",
        "model_used",
        "error",
        "created_at",
        "reviewed_at",
    }.issubset(columns)
    assert "ix_execution_reviews_status_priority" in indexes
    assert version == 20


def test_v20_registered_in_migration_steps() -> None:
    versions = [version for version, _ in migrations._MIGRATIONS]
    assert 20 in versions
