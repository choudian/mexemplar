"""Tests for v26 migration: external_skill_installs table (029)."""

from __future__ import annotations

from sqlalchemy import create_engine, text

from src.data import migrations


def _engine_at_v25():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (25)"))
    return engine


def test_v26_creates_table_and_indexes() -> None:
    engine = _engine_at_v25()

    migrations.migrate_to_v26(engine)

    with engine.connect() as conn:
        columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(external_skill_installs)"))
        }
        indexes = {
            row[1] for row in conn.execute(text("PRAGMA index_list(external_skill_installs)"))
        }
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()

    assert {
        "install_id",
        "skill_id",
        "source_type",
        "source_ref",
        "source_url",
        "local_dir",
        "installed_at",
        "uninstalled_at",
    }.issubset(columns)
    assert "uq_external_skill_installs_skill_id" in indexes
    assert "ix_external_skill_installs_source" in indexes
    assert version == 26


def test_v26_idempotent() -> None:
    engine = _engine_at_v25()
    migrations.migrate_to_v26(engine)
    migrations.migrate_to_v26(engine)
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
    assert version == 26


def test_v26_source_type_check_constraint() -> None:
    engine = _engine_at_v25()
    migrations.migrate_to_v26(engine)
    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO external_skill_installs "
                    "(install_id, skill_id, source_type, source_ref, source_url, "
                    "local_dir, installed_at) "
                    "VALUES ('e1', 's1', 'npm', 'x/y', 'http://x', '/d', '2026-01-01')"
                )
            )


def test_v26_downgrade_drops_table() -> None:
    engine = _engine_at_v25()
    migrations.migrate_to_v26(engine)

    migrations.downgrade_v26(engine)

    with engine.connect() as conn:
        exists = conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='external_skill_installs'"
            )
        ).fetchone()
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
    assert exists is None
    assert version == 25
