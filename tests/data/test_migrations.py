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
