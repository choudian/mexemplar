"""v11 migration 和 ORM 模型覆盖测试"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def engine_with_v11(tmp_path):
    """创建临时数据库并运行 v11 migration"""
    from src.data.sqlalchemy_manager import SQLAlchemyManager

    db_path = tmp_path / "test.db"
    sa = SQLAlchemyManager(str(db_path))
    sa.initialize()
    return sa.engine


class TestV11MigrationTables:
    """验证 v11 migration 创建了所有 6 张新表"""

    EXPECTED_TABLES = {
        "brain_segments",
        "brain_memory_entries",
        "brain_specialists",
        "brain_specialist_versions",
        "brain_recruitment_signals",
        "feedback_signals",
    }

    def test_all_brain_tables_exist(self, engine_with_v11):
        inspector = inspect(engine_with_v11)
        existing = set(inspector.get_table_names())
        for table in self.EXPECTED_TABLES:
            assert table in existing, f"Table {table} not found after v11 migration"

    def test_schema_version_is_current(self, engine_with_v11):
        with engine_with_v11.connect() as conn:
            result = conn.execute(text("SELECT version FROM schema_version"))
            row = result.fetchone()
            assert row is not None
            assert row[0] == 13

    def test_profile_backfill_handles_legacy_profile_without_raw_answers(self, tmp_path):
        from src.data.migrations import migrate_to_v11

        engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}", future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE schema_version (version INTEGER)"))
            conn.execute(text("INSERT INTO schema_version (version) VALUES (10)"))
            conn.execute(text("""
                CREATE TABLE assistant_profile (
                    profile_id TEXT PRIMARY KEY DEFAULT 'default',
                    display_name TEXT,
                    style TEXT,
                    notes TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                INSERT INTO assistant_profile (profile_id, display_name, style, notes)
                VALUES ('default', '高攀', '简洁直接', '偏好中文')
            """))

        migrate_to_v11(engine)

        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT content, zone, origin
                FROM brain_memory_entries
                WHERE zone = 'persistent'
            """)).fetchall()

        assert len(rows) == 1
        assert rows[0].zone == "persistent"
        assert rows[0].origin == "system_migration"
        assert "用户名称：高攀" in rows[0].content
        assert "偏好风格：简洁直接" in rows[0].content
        assert "备注：偏好中文" in rows[0].content

    def test_profile_backfill_handles_partial_legacy_profile_columns(self, tmp_path):
        from src.data.migrations import migrate_to_v11

        engine = create_engine(f"sqlite:///{tmp_path / 'partial-legacy.db'}", future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE schema_version (version INTEGER)"))
            conn.execute(text("INSERT INTO schema_version (version) VALUES (10)"))
            conn.execute(text("""
                CREATE TABLE assistant_profile (
                    profile_id TEXT PRIMARY KEY DEFAULT 'default',
                    notes TEXT
                )
            """))
            conn.execute(text("""
                INSERT INTO assistant_profile (profile_id, notes)
                VALUES ('default', '仅保留旧备注')
            """))

        migrate_to_v11(engine)

        with engine.connect() as conn:
            content = conn.execute(
                text("SELECT content FROM brain_memory_entries WHERE zone = 'persistent'")
            ).scalar_one()

        assert content == "备注：仅保留旧备注"


class TestV11MigrationIndexes:
    """验证关键索引存在"""

    def test_brain_segments_indexes(self, engine_with_v11):
        inspector = inspect(engine_with_v11)
        indexes = inspector.get_indexes("brain_segments")
        index_names = {idx["name"] for idx in indexes}
        assert "idx_brain_segments_session_id" in index_names
        assert "idx_brain_segments_status" in index_names

    def test_brain_memory_entries_indexes(self, engine_with_v11):
        inspector = inspect(engine_with_v11)
        indexes = inspector.get_indexes("brain_memory_entries")
        index_names = {idx["name"] for idx in indexes}
        assert "idx_brain_entries_zone_status" in index_names
        assert "idx_brain_entries_source_segment" in index_names
        assert "idx_brain_entries_superseded_by" in index_names
        assert "idx_brain_entries_zone_relevance" in index_names


class TestV11DomainConstraints:
    def test_brain_segment_rejects_unknown_status(self, engine_with_v11):
        with pytest.raises(IntegrityError), engine_with_v11.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO brain_segments (segment_id, session_id, status) "
                    "VALUES ('seg-invalid', 'sess-1', 'unknown')"
                )
            )

    @pytest.mark.parametrize(
        ("zone", "status"),
        [("unknown", "active"), ("hot", "unknown")],
    )
    def test_brain_memory_entry_rejects_unknown_domain_value(
        self,
        engine_with_v11,
        zone,
        status,
    ):
        with pytest.raises(IntegrityError), engine_with_v11.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO brain_memory_entries "
                    "(entry_id, zone, content, status, origin, reason) "
                    "VALUES ('entry-invalid', :zone, 'content', :status, 'manual', 'test')"
                ),
                {"zone": zone, "status": status},
            )

    def test_brain_specialist_rejects_non_boolean_active_value(self, engine_with_v11):
        with pytest.raises(IntegrityError), engine_with_v11.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO brain_specialists "
                    "(specialist_id, name, description, role_definition, tool_whitelist, "
                    "origin, reason, is_active) "
                    "VALUES ('sp-invalid', 'n', 'd', 'r', '[]', 'manual', 'test', 2)"
                )
            )


class TestOrmModels:
    """验证 ORM 模型与数据库表对齐"""

    def test_brain_segment_model_maps(self, engine_with_v11):
        inspector = inspect(engine_with_v11)
        columns = {col["name"] for col in inspector.get_columns("brain_segments")}
        expected = {
            "segment_id",
            "session_id",
            "status",
            "retry_count",
            "all_empty_retried",
            "boundary_reason",
            "message_id_start",
            "message_id_end",
            "sealed_at",
            "distilling_started_at",
            "completed_at",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(columns)

    def test_brain_memory_entry_model_maps(self, engine_with_v11):
        inspector = inspect(engine_with_v11)
        columns = {col["name"] for col in inspector.get_columns("brain_memory_entries")}
        expected = {
            "entry_id",
            "zone",
            "entry_type",
            "content",
            "status",
            "origin",
            "scope",
            "reason",
            "source_segment_id",
            "source_session_id",
            "superseded_by",
            "loaded_count",
            "referenced_count",
            "relevance_score",
            "verification_checkpoint",
            "verification_status",
            "verification_rationale",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(columns)

    def test_brain_specialist_model_maps(self, engine_with_v11):
        inspector = inspect(engine_with_v11)
        columns = {col["name"] for col in inspector.get_columns("brain_specialists")}
        expected = {
            "specialist_id",
            "name",
            "description",
            "role_definition",
            "tool_whitelist",
            "origin",
            "reason",
            "current_version",
            "is_active",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(columns)

    def test_brain_specialist_version_model_maps(self, engine_with_v11):
        inspector = inspect(engine_with_v11)
        columns = {col["name"] for col in inspector.get_columns("brain_specialist_versions")}
        expected = {
            "version_id",
            "specialist_id",
            "version",
            "name",
            "description",
            "role_definition",
            "tool_whitelist",
            "changed_by",
            "change_reason",
            "changed_at",
        }
        assert expected.issubset(columns)

    def test_brain_recruitment_signal_model_maps(self, engine_with_v11):
        inspector = inspect(engine_with_v11)
        columns = {col["name"] for col in inspector.get_columns("brain_recruitment_signals")}
        expected = {
            "signal_id",
            "task_pattern",
            "delegation_count",
            "example_session_ids",
            "example_delegation_summaries",
            "specialist_id",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(columns)

    def test_feedback_signal_model_maps(self, engine_with_v11):
        inspector = inspect(engine_with_v11)
        columns = {col["name"] for col in inspector.get_columns("feedback_signals")}
        expected = {
            "signal_id",
            "zone",
            "operation",
            "target_id",
            "context_summary",
            "created_at",
        }
        assert expected.issubset(columns)
