"""Tests for v21 migration: improvement_proposals table."""

from __future__ import annotations

from sqlalchemy import create_engine, text

from src.data import migrations


def test_v21_migration_creates_improvement_proposals_table_and_indexes() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (20)"))

    migrations.migrate_to_v21(engine)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(improvement_proposals)"))}
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(improvement_proposals)"))}
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()

    expected_columns = {
        "id",
        "source_review_id",
        "finding_index",
        "status",
        "severity",
        "finding_type",
        "dedup_key",
        "what",
        "evidence",
        "suggestion",
        "user_supplement",
        "graph_id",
        "worktree_path",
        "branch_name",
        "result_tests_passed",
        "result_summary",
        "error",
        "created_at",
        "decided_at",
        "completed_at",
    }
    assert expected_columns.issubset(columns)
    assert "ix_improvement_proposals_status" in indexes
    assert "ix_improvement_proposals_dedup_key" in indexes
    assert version == 21


def test_v21_migration_idempotent() -> None:
    """Re-running v21 on an already-migrated DB must not fail."""
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (20)"))

    migrations.migrate_to_v21(engine)
    migrations.migrate_to_v21(engine)

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
    assert version == 21


def test_v21_unique_constraint_on_review_finding() -> None:
    """UNIQUE(source_review_id, finding_index) must reject duplicates."""
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (20)"))

    migrations.migrate_to_v21(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO improvement_proposals "
                "(id, source_review_id, finding_index, status, created_at) "
                "VALUES ('p1', 'r1', 0, 'pending_review', '2026-01-01')"
            )
        )
        # Same (source_review_id, finding_index) must fail
        from sqlalchemy.exc import IntegrityError

        try:
            conn.execute(
                text(
                    "INSERT INTO improvement_proposals "
                    "(id, source_review_id, finding_index, status, created_at) "
                    "VALUES ('p2', 'r1', 0, 'pending_review', '2026-01-01')"
                )
            )
            assert False, "Expected IntegrityError"
        except IntegrityError:
            pass  # Expected


def test_v21_status_check_rejects_unknown_status() -> None:
    """CHECK(status IN (...)) 必须拒绝封闭状态集之外的值。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (20)"))

    migrations.migrate_to_v21(engine)

    from sqlalchemy.exc import IntegrityError

    with engine.begin() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO improvement_proposals "
                    "(id, source_review_id, finding_index, status, created_at) "
                    "VALUES ('p1', 'r1', 0, 'bogus_status', '2026-01-01')"
                )
            )
            assert False, "Expected IntegrityError for unknown status"
        except IntegrityError:
            pass  # Expected — CHECK constraint rejected the unknown status


def test_v21_result_tests_passed_check_rejects_non_boolean_integer() -> None:
    """result_tests_passed 必须保持三态布尔：NULL/0/1。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (20)"))

    migrations.migrate_to_v21(engine)

    from sqlalchemy.exc import IntegrityError

    with engine.begin() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO improvement_proposals "
                    "(id, source_review_id, finding_index, status, result_tests_passed, created_at) "
                    "VALUES ('p1', 'r1', 0, 'failed', 2, '2026-01-01')"
                )
            )
            assert False, "Expected IntegrityError for non-boolean result_tests_passed"
        except IntegrityError:
            pass


def test_v21_registered_in_migration_steps() -> None:
    versions = [version for version, _ in migrations._MIGRATIONS]
    assert 21 in versions


def _seed_v22_baseline(engine) -> None:
    """模拟 v21 后态：schema_version=21 + assistant_tasks 表已存在（v22 只加列）。"""
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (21)"))
        conn.execute(text("CREATE TABLE assistant_tasks (task_id TEXT PRIMARY KEY)"))


def test_v22_migration_adds_workspace_root_column() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    _seed_v22_baseline(engine)

    migrations.migrate_to_v22(engine)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(assistant_tasks)"))}
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()

    assert "workspace_root" in columns
    assert version == 22


def test_v22_migration_idempotent() -> None:
    """列已存在时重跑 v22 不得失败。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    _seed_v22_baseline(engine)

    migrations.migrate_to_v22(engine)
    migrations.migrate_to_v22(engine)

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
    assert version == 22


def test_v22_does_not_leak_raw_connection() -> None:
    """v22 迁移后引擎连接池必须仍可正常开新连接（修复前 raw_connection 无 finally 泄漏）。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    _seed_v22_baseline(engine)

    migrations.migrate_to_v22(engine)

    # 迁移后仍能开多个新连接读写，说明 raw_connection 已归还池（未泄漏）
    for _ in range(3):
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
        assert version == 22


def test_v22_registered_in_migration_steps() -> None:
    versions = [version for version, _ in migrations._MIGRATIONS]
    assert 22 in versions


def _seed_v23_old_improvement_proposals(engine) -> None:
    """模拟已跑到 v22、但 result_tests_passed 还没有 CHECK 的旧表。"""
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (22)"))
        conn.execute(text("""
            CREATE TABLE improvement_proposals (
                id TEXT PRIMARY KEY,
                source_review_id TEXT NOT NULL,
                finding_index INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending_review',
                severity TEXT,
                finding_type TEXT,
                dedup_key TEXT,
                what TEXT,
                evidence TEXT,
                suggestion TEXT,
                user_supplement TEXT,
                graph_id TEXT,
                worktree_path TEXT,
                branch_name TEXT,
                result_tests_passed INTEGER,
                result_summary TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                completed_at TEXT,
                UNIQUE(source_review_id, finding_index),
                CHECK(status IN ('pending_review','approved','in_progress','done','failed','rejected'))
            )
        """))
        conn.execute(
            text(
                "INSERT INTO improvement_proposals "
                "(id, source_review_id, finding_index, status, result_tests_passed, created_at) "
                "VALUES ('p1', 'r1', 0, 'failed', 2, '2026-01-01')"
            )
        )


def test_v23_migration_adds_result_tests_passed_check_to_existing_table() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    _seed_v23_old_improvement_proposals(engine)

    migrations.migrate_to_v23(engine)

    from sqlalchemy.exc import IntegrityError

    with engine.begin() as conn:
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
        carried = conn.execute(
            text("SELECT result_tests_passed FROM improvement_proposals WHERE id='p1'")
        ).scalar_one()
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(improvement_proposals)"))}
        try:
            conn.execute(
                text(
                    "INSERT INTO improvement_proposals "
                    "(id, source_review_id, finding_index, status, result_tests_passed, created_at) "
                    "VALUES ('p2', 'r2', 0, 'failed', 2, '2026-01-01')"
                )
            )
            assert False, "Expected IntegrityError for non-boolean result_tests_passed"
        except IntegrityError:
            pass

    assert version == 23
    assert carried is None
    assert "ix_improvement_proposals_status" in indexes
    assert "ix_improvement_proposals_dedup_key" in indexes


def test_v23_registered_in_migration_steps() -> None:
    versions = [version for version, _ in migrations._MIGRATIONS]
    assert 23 in versions
