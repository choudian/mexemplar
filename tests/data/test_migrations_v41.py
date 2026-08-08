"""v41：assistant task 新增 ``quota_exhausted`` 暂停原因。"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from src.business.task_collaboration.models import SuspendReason
from src.data import migrations
from src.data.models_sqlite import AssistantTask
from tests.data.test_migrations_v38 import TASK_INDEXES
from tests.data.test_migrations_v39 import _allowed_values, _indexes
from tests.data.test_migrations_v40 import _engine_at_v39


def _engine_at_v40():
    engine = _engine_at_v39()
    migrations.migrate_to_v40(engine)
    return engine


def test_v41_accepts_quota_exhausted_and_advances_version() -> None:
    engine = _engine_at_v40()

    migrations.migrate_to_v41(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE assistant_tasks "
                "SET status='suspended', suspend_reason='quota_exhausted', waiting_on='user' "
                "WHERE task_id='tsk_v40_completed'"
            )
        )
    with engine.connect() as conn:
        stored = conn.execute(
            text(
                "SELECT status, suspend_reason, waiting_on FROM assistant_tasks "
                "WHERE task_id='tsk_v40_completed'"
            )
        ).one()
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()

    assert tuple(stored) == ("suspended", "quota_exhausted", "user")
    assert version == 41
    assert _allowed_values(engine, "assistant_tasks", "ck_assistant_tasks_suspend_reason") == {
        reason.value for reason in SuspendReason
    }


def test_v41_carries_every_existing_column_through_the_rebuild() -> None:
    engine = _engine_at_v40()
    with engine.connect() as conn:
        before = dict(
            conn.execute(text("SELECT * FROM assistant_tasks WHERE task_id='tsk_v40_failed'"))
            .one()
            ._mapping
        )

    migrations.migrate_to_v41(engine)

    with engine.connect() as conn:
        after = dict(
            conn.execute(text("SELECT * FROM assistant_tasks WHERE task_id='tsk_v40_failed'"))
            .one()
            ._mapping
        )
    assert after == before


def test_v41_is_idempotent_and_rebuilds_indexes() -> None:
    engine = _engine_at_v40()

    migrations.migrate_to_v41(engine)
    migrations.migrate_to_v41(engine)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT version FROM schema_version")).scalar_one() == 41
    assert _indexes(engine, "assistant_tasks") == TASK_INDEXES


def test_v41_rejects_unknown_suspend_reason() -> None:
    engine = _engine_at_v40()
    migrations.migrate_to_v41(engine)

    with pytest.raises(IntegrityError, match="ck_assistant_tasks_suspend_reason"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE assistant_tasks "
                    "SET status='suspended', suspend_reason='unknown_reason', waiting_on='user' "
                    "WHERE task_id='tsk_v40_completed'"
                )
            )


def test_v41_skips_cleanly_when_the_table_is_absent() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (40)"))

    migrations.migrate_to_v41(engine)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT version FROM schema_version")).scalar_one() == 41


def test_v41_orm_and_migration_agree_on_every_suspend_reason() -> None:
    orm_constraint = next(
        constraint
        for constraint in AssistantTask.__table__.constraints
        if getattr(constraint, "name", None) == "ck_assistant_tasks_suspend_reason"
    )
    orm_values = set(re.findall(r"'([a-z_]+)'", str(orm_constraint.sqltext)))
    engine = _engine_at_v40()
    migrations.migrate_to_v41(engine)
    migrated_values = _allowed_values(
        engine,
        "assistant_tasks",
        "ck_assistant_tasks_suspend_reason",
    )

    assert orm_values == migrated_values == {reason.value for reason in SuspendReason}


def test_v41_is_registered_in_migrations() -> None:
    """v41 仍在 _MIGRATIONS 注册表里（不再断言是最新——v42 已接上）。"""
    assert (41, migrations.migrate_to_v41) in migrations._MIGRATIONS
