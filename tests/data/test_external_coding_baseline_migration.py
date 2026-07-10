from __future__ import annotations

from sqlalchemy import create_engine, text

from src.data import migrations


def _engine_at_v27():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (27)"))
        conn.execute(
            text(
                "CREATE TABLE external_coding_sessions ("
                "coding_session_id TEXT PRIMARY KEY, "
                "status TEXT NOT NULL)"
            )
        )
    return engine


def test_v28_adds_external_coding_base_commit_idempotently() -> None:
    engine = _engine_at_v27()

    migrations.migrate_to_v28(engine)
    migrations.migrate_to_v28(engine)

    with engine.connect() as conn:
        columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(external_coding_sessions)"))
        }
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
    assert "base_commit" in columns
    assert version == 28


def test_v28_is_registered_after_external_coding_tables() -> None:
    versions = [version for version, _ in migrations._MIGRATIONS]
    assert versions[-2:] == [27, 28]
