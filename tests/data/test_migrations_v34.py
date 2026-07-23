"""v34 adds the token usage column without assuming the table exists."""

from __future__ import annotations

from sqlalchemy import create_engine, text

from src.data import migrations


def _engine(tmp_path, name):
    return create_engine(f"sqlite:///{tmp_path / name}")


def _seed_version(engine, version):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER)"))
        conn.execute(text("DELETE FROM schema_version"))
        conn.execute(text("INSERT INTO schema_version VALUES (:v)"), {"v": version})


def _columns(engine, table):
    with engine.connect() as conn:
        return [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))]


def _version(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT version FROM schema_version")).scalar_one()


def test_v34_adds_token_usage_column_and_is_idempotent(tmp_path):
    engine = _engine(tmp_path, "v34.db")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE messages ("
                "message_id TEXT PRIMARY KEY, session_id TEXT, sequence INTEGER, role TEXT)"
            )
        )
    _seed_version(engine, 33)

    migrations.migrate_to_v34(engine)
    migrations.migrate_to_v34(engine)

    assert _columns(engine, "messages").count("token_usage") == 1
    assert _version(engine) == 34


def test_v34_skips_gracefully_when_messages_table_absent(tmp_path):
    # Partially-built databases exist in the migration test suite; a hard
    # ALTER TABLE here would break every one of them.
    engine = _engine(tmp_path, "v34_empty.db")
    _seed_version(engine, 33)

    migrations.migrate_to_v34(engine)

    assert _version(engine) == 34


def test_v34_downgrade_removes_the_column(tmp_path):
    engine = _engine(tmp_path, "v34_down.db")
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE messages (message_id TEXT PRIMARY KEY, token_usage TEXT)")
        )
    _seed_version(engine, 34)

    migrations.downgrade_from_v34(engine)

    assert "token_usage" not in _columns(engine, "messages")
    assert _version(engine) == 33


def test_v34_is_registered_in_the_migration_chain():
    assert (34, migrations.migrate_to_v34) in migrations._MIGRATIONS
