from __future__ import annotations

from sqlalchemy import create_engine, text

from src.data import migrations


def _engine_at_v28():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (28)"))
        conn.execute(
            text(
                "CREATE TABLE brain_specialists ("
                "specialist_id TEXT PRIMARY KEY, "
                "tool_whitelist TEXT NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE brain_specialist_versions ("
                "version_id TEXT PRIMARY KEY, "
                "tool_whitelist TEXT NOT NULL)"
            )
        )
    return engine


def test_v29_adds_versioned_specialist_composition_ids_idempotently() -> None:
    engine = _engine_at_v28()

    migrations.migrate_to_v29(engine)
    migrations.migrate_to_v29(engine)

    with engine.connect() as conn:
        specialist_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(brain_specialists)"))
        }
        version_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(brain_specialist_versions)"))
        }
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()

    assert "composition_ids" in specialist_columns
    assert "composition_ids" in version_columns
    assert version == 29


def test_v29_is_registered_after_external_coding_baseline() -> None:
    versions = [version for version, _ in migrations._MIGRATIONS]
    assert versions[-2:] == [28, 29]
