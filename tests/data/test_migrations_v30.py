"""Tests for v30 migration: scheduling center (033).

scheduled_tasks / scheduled_task_runs 两张新表 + sessions 加 source /
scheduled_task_id / is_scheduled 三列。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from src.data import migrations


def _engine_at_v29():
    """v29 基线：含 schema_version + 一张最小 sessions 表（pre-v30 列）。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (29)"))
        # 最小 sessions 表（v30 前）：含 v30 之前的列 + 一条既有行用于 backfill 验证
        conn.execute(
            text(
                "CREATE TABLE sessions ("
                "session_id TEXT PRIMARY KEY, "
                "workflow_id TEXT, "
                "agent_type TEXT NOT NULL, "
                "status TEXT DEFAULT 'active', "
                "title TEXT, "
                "tool_ids TEXT, "
                "created_at DATETIME, "
                "updated_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO sessions (session_id, agent_type) VALUES "
                "('ast_preexisting', 'assistant')"
            )
        )
    return engine


def test_v30_creates_tables_columns_and_indexes() -> None:
    engine = _engine_at_v29()

    migrations.migrate_to_v30(engine)

    with engine.connect() as conn:
        task_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(scheduled_tasks)"))}
        run_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(scheduled_task_runs)"))}
        session_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(sessions)"))}
        task_indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(scheduled_tasks)"))}
        run_indexes = {
            row[1] for row in conn.execute(text("PRAGMA index_list(scheduled_task_runs)"))
        }
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()

    assert {
        "scheduled_task_id",
        "source_type",
        "source_ref",
        "title",
        "instruction",
        "schedule_kind",
        "schedule_payload",
        "status",
        "unattended_auto_approve",
        "executor_hint",
        "next_fire_at",
        "last_fired_at",
        "is_deleted",
        "created_at",
        "updated_at",
    }.issubset(task_cols)
    assert {
        "run_id",
        "scheduled_task_id",
        "session_id",
        "started_at",
        "finished_at",
        "status",
        "summary",
        "failure_reason",
        "created_at",
    }.issubset(run_cols)
    assert {"source", "scheduled_task_id", "is_scheduled"}.issubset(session_cols)
    assert "idx_scheduled_tasks_fire" in task_indexes
    assert "idx_scheduled_tasks_source_todo" in task_indexes
    assert "idx_runs_task_started" in run_indexes
    assert "idx_runs_session" in run_indexes
    assert "uq_runs_active_per_task" in run_indexes
    assert version == 30


def test_v30_sessions_backfill_defaults() -> None:
    """既有 sessions 行 backfill source='user' / is_scheduled=0（DEFAULT 自动填充）。"""
    engine = _engine_at_v29()

    migrations.migrate_to_v30(engine)

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT source, scheduled_task_id, is_scheduled FROM sessions WHERE session_id='ast_preexisting'"
            )
        ).one()
    assert row.source == "user"
    assert row.scheduled_task_id is None
    assert row.is_scheduled == 0


def test_v30_idempotent() -> None:
    engine = _engine_at_v29()
    migrations.migrate_to_v30(engine)
    migrations.migrate_to_v30(engine)  # 二次迁移不报错
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
    assert version == 30


def test_v30_scheduled_tasks_status_check_constraint() -> None:
    engine = _engine_at_v29()
    migrations.migrate_to_v30(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO scheduled_tasks "
                    "(scheduled_task_id, source_type, source_ref, title, instruction, schedule_kind, "
                    "schedule_payload, status) "
                    "VALUES ('sch_1', 'direct', 'r', 't', 'r', 'one_shot', '{}', 'bogus')"
                )
            )


def test_v30_runs_status_check_constraint() -> None:
    engine = _engine_at_v29()
    migrations.migrate_to_v30(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO scheduled_task_runs "
                    "(run_id, scheduled_task_id, session_id, status) "
                    "VALUES ('schr_1', 'sch_1', 'ast_1', 'bogus')"
                )
            )


def test_v30_allows_only_one_active_run_per_task() -> None:
    engine = _engine_at_v29()
    migrations.migrate_to_v30(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO scheduled_task_runs "
                "(run_id, scheduled_task_id, session_id, status) "
                "VALUES ('schr_active_1', 'sch_same', 'ast_1', 'running')"
            )
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO scheduled_task_runs "
                    "(run_id, scheduled_task_id, session_id, status) "
                    "VALUES ('schr_active_2', 'sch_same', 'ast_2', 'waiting_user')"
                )
            )

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO scheduled_task_runs "
                "(run_id, scheduled_task_id, session_id, status) "
                "VALUES ('schr_terminal', 'sch_same', 'ast_terminal', 'skipped')"
            )
        )


def test_v30_unattended_auto_approve_check_constraint() -> None:
    engine = _engine_at_v29()
    migrations.migrate_to_v30(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO scheduled_tasks "
                    "(scheduled_task_id, source_type, source_ref, title, instruction, schedule_kind, "
                    "schedule_payload, unattended_auto_approve) "
                    "VALUES ('sch_2', 'direct', 'r', 't', 'r', 'one_shot', '{}', 7)"
                )
            )
