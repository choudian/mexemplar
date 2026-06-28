from __future__ import annotations

import inspect

from sqlalchemy import create_engine, text

from src.data import migrations
from src.data.skill_bootstrap_seed import BOOTSTRAP_HOW_TO_SKILL_ID


def test_v12_invoked_in_run_migrations(monkeypatch):
    calls: list[int] = []
    schema_versions = iter([11, 12])

    monkeypatch.setattr(migrations, "get_schema_version", lambda _engine: next(schema_versions))
    monkeypatch.setattr(migrations, "_MIGRATIONS", [(12, lambda _engine: calls.append(12))])

    migrations.run_migrations(object())

    assert calls == [12]


def test_v12_migration_seeds_bootstrap_without_importing_business_layer() -> None:
    assert "src.business" not in inspect.getsource(migrations.migrate_to_v12)

    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (11)"))

    migrations.migrate_to_v12(engine)

    with engine.connect() as conn:
        skill = conn.execute(
            text(
                "SELECT status, origin, chain_root_id FROM brain_skills WHERE skill_id = :skill_id"
            ),
            {"skill_id": BOOTSTRAP_HOW_TO_SKILL_ID},
        ).one()
        equipment = conn.execute(
            text("""
                SELECT equipped_entity_type, equipped_entity_id, status
                FROM brain_skill_equipment
                WHERE skill_id = :skill_id
                """),
            {"skill_id": BOOTSTRAP_HOW_TO_SKILL_ID},
        ).one()

    assert skill == ("active", "system_bootstrap", BOOTSTRAP_HOW_TO_SKILL_ID)
    assert equipment == ("assistant", "_assistant", "active")


def test_v14_migration_creates_assistant_failure_state_table() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (13)"))

    migrations.migrate_to_v14(engine)

    with engine.connect() as conn:
        columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(assistant_run_failures)"))
        }
        indexes = {
            row[1] for row in conn.execute(text("PRAGMA index_list(assistant_run_failures)"))
        }
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()

    assert {
        "failure_id",
        "session_id",
        "message_sequence",
        "category",
        "safe_message",
        "safe_suggestion",
        "attempt_count",
        "status",
        "failed_at",
        "resolved_at",
    }.issubset(columns)
    assert "uq_assistant_run_failure_current_session" in indexes
    assert version == 14


def test_v16_migration_creates_attempt_partial_unique_indexes() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (15)"))
        # 预建 v15 状态的 attempts 表（无 partial unique index），供 v16 升级
        conn.execute(text(
            "CREATE TABLE assistant_task_attempts ("
            "attempt_id TEXT PRIMARY KEY, "
            "task_id TEXT NOT NULL, "
            "executor_type TEXT NOT NULL, "
            "executor_id TEXT NOT NULL, "
            "status TEXT NOT NULL, "
            "lease_owner TEXT NOT NULL, "
            "lease_expires_at DATETIME NOT NULL)"
        ))
        conn.execute(text(
            "CREATE TABLE assistant_task_claims ("
            "claim_id TEXT PRIMARY KEY, "
            "task_id TEXT NOT NULL, "
            "claimer_type TEXT NOT NULL, "
            "claimer_id TEXT NOT NULL, "
            "status TEXT NOT NULL, "
            "lease_expires_at DATETIME, "
            "task_version INTEGER NOT NULL)"
        ))

    migrations.migrate_to_v16(engine)

    with engine.connect() as conn:
        indexes = {
            row[1] for row in conn.execute(text("PRAGMA index_list(assistant_task_attempts)"))
        }
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()

    assert "uq_assistant_task_attempts_active_task" in indexes
    assert "uq_assistant_task_attempts_active_executor" in indexes
    assert version == 16


def test_v16_registered_in_migration_steps() -> None:
    versions = [version for version, _ in migrations._MIGRATIONS]
    assert 16 in versions
