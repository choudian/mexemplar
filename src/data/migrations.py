"""
数据库迁移脚本

所有迁移函数接受 SQLAlchemy engine，通过 text() 执行原生 SQL。
新增列时应同时在 models_sqlite.py 的 ORM 模型和对应的迁移步骤中添加。
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from src.data.skill_bootstrap_seed import (
    BOOTSTRAP_DESCRIPTION,
    BOOTSTRAP_HOW_TO_SKILL_ID,
    BOOTSTRAP_NAME,
    BOOTSTRAP_REQUIRED_TOOLS,
    BOOTSTRAP_TRIGGERS,
    DEFAULT_SEED_FILE_PATH,
    FALLBACK_BODY,
)
from src.utils.timezone import local_naive_to_utc_naive

logger = logging.getLogger(__name__)


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def _add_column_if_missing(conn, table_name: str, column_name: str, definition: str) -> None:
    if _column_exists(conn, table_name, column_name):
        logger.debug("迁移跳过已存在列: %s.%s", table_name, column_name)
        return
    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))


def _coerce_datetime(value) -> datetime | None:
    """兼容 SQLite 原生字符串与 SQLAlchemy DateTime 返回值。"""
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            logger.warning(f"无法解析 datetime 值，跳过迁移: {value!r}")
            return None
    logger.warning(f"不支持的 datetime 值类型，跳过迁移: {type(value)!r}")
    return None


def get_schema_version(engine) -> int:
    """读取当前 schema 版本，表不存在或无记录时返回 0"""
    with engine.connect() as conn:
        try:
            result = conn.execute(text("SELECT version FROM schema_version"))
            row = result.fetchone()
            return row[0] if row else 0
        except OperationalError:
            return 0


def migrate_to_v2(engine):
    """迁移到版本 2：添加意图和试用相关表"""
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS intents (
                    intent_id TEXT PRIMARY KEY,
                    recording_id TEXT NOT NULL,
                    core_operations TEXT NOT NULL,
                    target TEXT,
                    business_scenario TEXT,
                    expected_results TEXT,
                    status TEXT NOT NULL,
                    confirmed_operations TEXT,
                    user_message TEXT,
                    analysis_confidence REAL DEFAULT 0.0,
                    llm_model_used TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    confirmed_at TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS pending_tools (
                    pending_tool_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    tool_description TEXT,
                    execution_code TEXT,
                    code_language TEXT DEFAULT 'python',
                    execution_strategy TEXT,
                    parameters TEXT,
                    status TEXT NOT NULL,
                    trial_count INTEGER DEFAULT 0,
                    max_trials INTEGER DEFAULT 3,
                    last_trial_result TEXT,
                    last_error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    promoted_at TIMESTAMP,
                    FOREIGN KEY (intent_id) REFERENCES intents(intent_id)
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS tool_trials (
                    trial_id TEXT PRIMARY KEY,
                    pending_tool_id TEXT NOT NULL,
                    trial_data TEXT,
                    status TEXT NOT NULL,
                    result TEXT,
                    error_message TEXT,
                    error_type TEXT,
                    execution_log TEXT,
                    execution_steps TEXT,
                    fix_attempted INTEGER DEFAULT 0,
                    fix_successful INTEGER DEFAULT 0,
                    fixed_code TEXT,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMP,
                    FOREIGN KEY (pending_tool_id) REFERENCES pending_tools(pending_tool_id)
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS trial_data_templates (
                    template_id TEXT PRIMARY KEY,
                    pending_tool_id TEXT NOT NULL,
                    template_name TEXT,
                    template_data TEXT,
                    is_real_data INTEGER DEFAULT 0,
                    description TEXT,
                    data_source TEXT,
                    created_at REAL,
                    updated_at REAL,
                    FOREIGN KEY (pending_tool_id) REFERENCES pending_tools(pending_tool_id)
                )
            """))

            # tools 表补充字段（如果不存在）
            for col, definition in [
                ("source_intent_id", "TEXT"),
                ("source", "TEXT DEFAULT 'manual'"),
                ("trial_count", "INTEGER DEFAULT 0"),
                ("pending_tool_id", "TEXT"),
            ]:
                _add_column_if_missing(conn, "tools", col, definition)

            # 索引
            for index_name, index_def in [
                ("idx_intents_recording_id", "intents(recording_id)"),
                ("idx_intents_status", "intents(status)"),
                ("idx_pending_tools_intent_id", "pending_tools(intent_id)"),
                ("idx_pending_tools_status", "pending_tools(status)"),
                ("idx_tool_trials_pending_tool_id", "tool_trials(pending_tool_id)"),
                ("idx_tool_trials_status", "tool_trials(status)"),
                (
                    "idx_trial_data_templates_pending_tool_id",
                    "trial_data_templates(pending_tool_id)",
                ),
            ]:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}"))

            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 2})
            conn.commit()
            logger.info("数据库迁移到版本 2 完成：添加意图和试用相关表")
        except Exception as e:
            conn.rollback()
            logger.error(f"数据库迁移失败: {e}")
            raise


def migrate_to_v3(engine):
    """迁移到版本 3：添加 Agent 会话和消息表"""
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    message_type TEXT DEFAULT 'normal',
                    tool_call_id TEXT,
                    tool_name TEXT,
                    tool_calls TEXT,
                    compressed_range TEXT,
                    is_archived INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
            """))
            # DROP + CREATE 修复旧版本中 to_session_id TEXT NOT NULL 的错误约束
            conn.execute(text("DROP TABLE IF EXISTS workflow_transitions"))
            conn.execute(text("""
                CREATE TABLE workflow_transitions (
                    transition_id   TEXT PRIMARY KEY,
                    workflow_id     TEXT NOT NULL,
                    from_session_id TEXT,
                    to_session_id   TEXT,
                    event_type      TEXT NOT NULL,
                    payload         TEXT,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            for index_name, index_def in [
                ("idx_sessions_workflow", "sessions(workflow_id)"),
                ("idx_sessions_agent_type", "sessions(agent_type)"),
                ("idx_sessions_status", "sessions(status)"),
                ("idx_messages_session", "messages(session_id, sequence)"),
                ("idx_messages_archived", "messages(session_id, is_archived)"),
                ("idx_transitions_workflow", "workflow_transitions(workflow_id)"),
            ]:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}"))

            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 3})
            conn.commit()
            logger.info("数据库迁移到版本 3 完成：添加 sessions、messages、workflow_transitions 表")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 3 失败: {e}")
            raise


def migrate_to_v4(engine):
    """迁移到版本 4：tools 表增加 workflow_id、trial_success_count、status 字段"""
    with engine.connect() as conn:
        try:
            for col, definition in [
                ("workflow_id", "TEXT"),
                ("trial_success_count", "INTEGER DEFAULT 0"),
                ("status", "TEXT DEFAULT 'pending'"),
            ]:
                _add_column_if_missing(conn, "tools", col, definition)
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 4})
            conn.commit()
            logger.info(
                "数据库迁移到版本 4 完成：tools 表新增 workflow_id、trial_success_count、status"
            )
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 4 失败: {e}")
            raise


def migrate_to_v5(engine):
    """迁移到版本 5：办公助理 Agent 相关表"""
    with engine.connect() as conn:
        try:
            conn.execute(text("PRAGMA foreign_keys=OFF"))

            # 重建 sessions 表：workflow_id nullable + 新增 tool_ids
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS sessions_new (
                    session_id TEXT PRIMARY KEY,
                    workflow_id TEXT,
                    agent_type TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    tool_ids TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                INSERT OR IGNORE INTO sessions_new (session_id, workflow_id, agent_type, status, created_at, updated_at)
                SELECT session_id, workflow_id, agent_type, status, created_at, updated_at FROM sessions
            """))
            conn.execute(text("DROP TABLE IF EXISTS sessions"))
            conn.execute(text("ALTER TABLE sessions_new RENAME TO sessions"))

            conn.execute(text("PRAGMA foreign_keys=ON"))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS assistant_profile (
                    profile_id TEXT PRIMARY KEY DEFAULT 'default',
                    display_name TEXT,
                    style TEXT,
                    notes TEXT,
                    raw_answers TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS pending_assistant_tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    payload TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS tool_suggestion_history (
                    suggestion_id TEXT PRIMARY KEY,
                    task_pattern TEXT NOT NULL,
                    suggested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    accepted BOOLEAN,
                    times_seen INTEGER DEFAULT 0
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS assistant_summaries (
                    summary_id TEXT PRIMARY KEY,
                    level INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    source_ids TEXT,
                    embedding BLOB,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

            for index_name, index_def in [
                ("idx_pending_tasks_status", "pending_assistant_tasks(status)"),
                ("idx_assistant_summaries_level", "assistant_summaries(level)"),
                ("idx_tool_suggestion_accepted", "tool_suggestion_history(accepted)"),
            ]:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}"))

            # FTS5 全文搜索虚拟表 + 同步触发器
            conn.execute(text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS assistant_summaries_fts
                USING fts5(summary_id UNINDEXED, content, tokenize='unicode61')
            """))
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_summaries_fts_insert
                AFTER INSERT ON assistant_summaries
                BEGIN
                    INSERT INTO assistant_summaries_fts(summary_id, content)
                    VALUES (new.summary_id, new.content);
                END
            """))
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_summaries_fts_delete
                AFTER DELETE ON assistant_summaries
                BEGIN
                    DELETE FROM assistant_summaries_fts
                    WHERE summary_id = old.summary_id;
                END
            """))
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_summaries_fts_update
                AFTER UPDATE OF content ON assistant_summaries
                BEGIN
                    UPDATE assistant_summaries_fts SET content = new.content
                    WHERE summary_id = new.summary_id;
                END
            """))

            # sqlite-vec 向量搜索（扩展已由 engine 事件监听器加载，直接建表）
            try:
                conn.execute(text("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS assistant_summaries_vec
                    USING vec0(
                        summary_id TEXT,
                        embedding float[1536] distance_metric=cosine
                    )
                """))
                logger.info("sqlite-vec 向量表创建成功")
            except Exception as e:
                logger.info(f"sqlite-vec 未安装，跳过向量表创建（将使用 FTS-only 模式）: {e}")

            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 5})
            conn.commit()
            logger.info(
                "数据库迁移到版本 5 完成：sessions 表重建、"
                "新增 assistant_profile/pending_assistant_tasks/tool_suggestion_history/assistant_summaries 表"
            )
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 5 失败: {e}")
            raise


def migrate_to_v6(engine):
    """迁移到版本 6：新增 teaching_failure_records 表"""
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS teaching_failure_records (
                    record_id TEXT PRIMARY KEY,
                    workflow_id TEXT UNIQUE,
                    tool_name TEXT,
                    failed_stage TEXT NOT NULL,
                    error_summary TEXT,
                    error_type TEXT,
                    status TEXT DEFAULT 'active',
                    retry_count INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved_at DATETIME
                )
            """))
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_tfr_status ON teaching_failure_records (status)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_tfr_updated_at ON teaching_failure_records (updated_at DESC)"
                )
            )
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 6})
            conn.commit()
            logger.info("数据库迁移到版本 6 完成：新增 teaching_failure_records 表")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 6 失败: {e}")
            raise


def migrate_to_v7(engine):
    """迁移到版本 7：tools 表补齐 dependencies、workflow_id、trial_success_count、status 列"""
    with engine.connect() as conn:
        try:
            for col, definition in [
                ("dependencies", "TEXT DEFAULT '[]'"),
                ("workflow_id", "TEXT"),
                ("trial_success_count", "INTEGER DEFAULT 0"),
                ("status", "TEXT DEFAULT 'pending'"),
            ]:
                _add_column_if_missing(conn, "tools", col, definition)
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 7})
            conn.commit()
            logger.info(
                "数据库迁移到版本 7 完成：tools 表补齐 dependencies、workflow_id、trial_success_count、status 列"
            )
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 7 失败: {e}")
            raise


def migrate_to_v8(engine):
    """迁移到版本 8：新增 skill_compositions 与 skill_composition_members 表"""
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS skill_compositions (
                    composition_id TEXT PRIMARY KEY,
                    composition_name TEXT NOT NULL,
                    description TEXT,
                    applicability TEXT NOT NULL,
                    mode TEXT DEFAULT 'range',
                    status TEXT DEFAULT 'draft',
                    assistant_enabled INTEGER DEFAULT 1,
                    recommend_order INTEGER DEFAULT 0,
                    needs_review INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS skill_composition_members (
                    member_id TEXT PRIMARY KEY,
                    composition_id TEXT NOT NULL REFERENCES skill_compositions(composition_id),
                    tool_id TEXT NOT NULL REFERENCES tools(tool_id),
                    selected_order INTEGER DEFAULT 0,
                    execution_order INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_scm_composition_tool "
                    "ON skill_composition_members (composition_id, tool_id)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_skill_compositions_status "
                    "ON skill_compositions (status)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_skill_compositions_updated_at "
                    "ON skill_compositions (updated_at DESC)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_scm_composition_id "
                    "ON skill_composition_members (composition_id)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_scm_tool_id "
                    "ON skill_composition_members (tool_id)"
                )
            )
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 8})
            conn.commit()
            logger.info("数据库迁移到版本 8 完成：新增技能组合表与成员关系表")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 8 失败: {e}")
            raise


def migrate_to_v9(engine):
    """迁移到版本 9：归一化旧版技能组合 updated_at 的 local naive 时间。"""
    with engine.connect() as conn:
        try:
            rows = conn.execute(
                text("SELECT composition_id, updated_at FROM skill_compositions")
            ).mappings()

            migrated_count = 0
            for row in rows:
                updated_at = _coerce_datetime(row["updated_at"])
                # Python 端 datetime.now() 带微秒，SQL CURRENT_TIMESTAMP 不带；
                # 只迁移带微秒的行（来自旧 Python 代码），跳过 SQL 生成的（已是 UTC）
                if updated_at is None or updated_at.microsecond == 0:
                    continue

                normalized = local_naive_to_utc_naive(updated_at)
                if normalized == updated_at:
                    continue

                conn.execute(
                    text("""
                        UPDATE skill_compositions
                        SET updated_at = :updated_at
                        WHERE composition_id = :composition_id
                        """),
                    {
                        "composition_id": row["composition_id"],
                        "updated_at": normalized,
                    },
                )
                migrated_count += 1

            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 9})
            conn.commit()
            logger.info(
                "数据库迁移到版本 9 完成：已归一化 %s 条技能组合 updated_at",
                migrated_count,
            )
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 9 失败: {e}")
            raise


def migrate_to_v10(engine):
    """迁移到版本 10：sessions 表新增用户可编辑标题。"""
    with engine.connect() as conn:
        try:
            table_exists = conn.execute(text("""
                    SELECT 1
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'sessions'
                    """)).fetchone()
            if table_exists is None:
                conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 10})
                conn.commit()
                logger.info("数据库迁移到版本 10 完成：sessions 表不存在，跳过 title")
                return

            _add_column_if_missing(conn, "sessions", "title", "TEXT")
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 10})
            conn.commit()
            logger.info("数据库迁移到版本 10 完成：sessions 表新增 title")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 10 失败: {e}")
            raise


def migrate_to_v11(engine):
    """迁移到版本 11：大脑架构 - 创建 6 分区 + 支撑表，回填 Profile 数据"""
    with engine.connect() as conn:
        try:
            # 1. brain_segments 表
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS brain_segments (
                    segment_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('pending', 'distilling', 'completed', 'failed')),
                    retry_count INTEGER DEFAULT 0,
                    all_empty_retried INTEGER DEFAULT 0,
                    boundary_reason TEXT,
                    message_id_start TEXT,
                    message_id_end TEXT,
                    sealed_at DATETIME,
                    distilling_started_at DATETIME,
                    completed_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

            # 2. brain_memory_entries 表
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS brain_memory_entries (
                    entry_id TEXT PRIMARY KEY,
                    zone TEXT NOT NULL
                        CHECK (zone IN ('hot', 'persistent', 'archive', 'subconscious', 'failure', 'prediction')),
                    entry_type TEXT,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'fading', 'invalidated', 'soft-deleted')),
                    origin TEXT NOT NULL,
                    scope TEXT,
                    reason TEXT NOT NULL,
                    source_segment_id TEXT,
                    source_session_id TEXT,
                    superseded_by TEXT,
                    loaded_count INTEGER DEFAULT 0,
                    referenced_count INTEGER DEFAULT 0,
                    relevance_score REAL DEFAULT 1.0,
                    verification_checkpoint TEXT,
                    verification_status TEXT,
                    verification_rationale TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

            # 3. brain_specialists 表
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS brain_specialists (
                    specialist_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    role_definition TEXT NOT NULL,
                    tool_whitelist TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    current_version INTEGER DEFAULT 1,
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

            # 4. brain_specialist_versions 表
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS brain_specialist_versions (
                    version_id TEXT PRIMARY KEY,
                    specialist_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    role_definition TEXT NOT NULL,
                    tool_whitelist TEXT NOT NULL,
                    changed_by TEXT NOT NULL,
                    change_reason TEXT,
                    changed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_brain_specialist_version UNIQUE (specialist_id, version)
                )
            """))

            # 5. brain_recruitment_signals 表
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS brain_recruitment_signals (
                    signal_id TEXT PRIMARY KEY,
                    task_pattern TEXT NOT NULL,
                    delegation_count INTEGER DEFAULT 0,
                    example_session_ids TEXT,
                    example_delegation_summaries TEXT,
                    specialist_id TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

            # 6. feedback_signals 表
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS feedback_signals (
                    signal_id TEXT PRIMARY KEY,
                    zone TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    context_summary TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

            # 索引
            for index_sql in [
                "CREATE INDEX IF NOT EXISTS idx_brain_segments_session_id ON brain_segments(session_id)",
                "CREATE INDEX IF NOT EXISTS idx_brain_segments_status ON brain_segments(status)",
                "CREATE INDEX IF NOT EXISTS idx_brain_entries_zone_status ON brain_memory_entries(zone, status)",
                "CREATE INDEX IF NOT EXISTS idx_brain_entries_source_segment ON brain_memory_entries(source_segment_id)",
                "CREATE INDEX IF NOT EXISTS idx_brain_entries_superseded_by ON brain_memory_entries(superseded_by)",
                "CREATE INDEX IF NOT EXISTS idx_brain_entries_zone_relevance ON brain_memory_entries(zone, relevance_score DESC)",
                "CREATE INDEX IF NOT EXISTS idx_brain_specialists_is_active ON brain_specialists(is_active)",
                "CREATE INDEX IF NOT EXISTS idx_feedback_signals_target ON feedback_signals(target_id)",
                "CREATE INDEX IF NOT EXISTS idx_feedback_signals_zone ON feedback_signals(zone)",
            ]:
                conn.execute(text(index_sql))

            # 数据回填：Profile → brain_memory_entries 持久区
            try:
                profile_columns = {
                    row[1]
                    for row in conn.execute(text("PRAGMA table_info(assistant_profile)")).fetchall()
                }
                readable_columns = frozenset(
                    column
                    for column in ("display_name", "style", "notes")
                    if column in profile_columns
                )
                backfill_queries = {
                    frozenset({"display_name"}): (
                        "SELECT display_name, NULL AS style, NULL AS notes "
                        "FROM assistant_profile WHERE profile_id = 'default'"
                    ),
                    frozenset({"style"}): (
                        "SELECT NULL AS display_name, style, NULL AS notes "
                        "FROM assistant_profile WHERE profile_id = 'default'"
                    ),
                    frozenset({"notes"}): (
                        "SELECT NULL AS display_name, NULL AS style, notes "
                        "FROM assistant_profile WHERE profile_id = 'default'"
                    ),
                    frozenset({"display_name", "style"}): (
                        "SELECT display_name, style, NULL AS notes "
                        "FROM assistant_profile WHERE profile_id = 'default'"
                    ),
                    frozenset({"display_name", "notes"}): (
                        "SELECT display_name, NULL AS style, notes "
                        "FROM assistant_profile WHERE profile_id = 'default'"
                    ),
                    frozenset({"style", "notes"}): (
                        "SELECT NULL AS display_name, style, notes "
                        "FROM assistant_profile WHERE profile_id = 'default'"
                    ),
                    frozenset({"display_name", "style", "notes"}): (
                        "SELECT display_name, style, notes "
                        "FROM assistant_profile WHERE profile_id = 'default'"
                    ),
                }
                backfill_query = backfill_queries.get(readable_columns)
                if backfill_query is None:
                    profile_rows = []
                else:
                    profile_rows = conn.execute(text(backfill_query)).mappings()
                for row in profile_rows:
                    parts = []
                    if row.get("display_name"):
                        parts.append(f"用户名称：{row['display_name']}")
                    if row.get("style"):
                        parts.append(f"偏好风格：{row['style']}")
                    if row.get("notes"):
                        parts.append(f"备注：{row['notes']}")
                    if parts:
                        from uuid import uuid4

                        content = "\n".join(parts)
                        conn.execute(
                            text("""
                            INSERT INTO brain_memory_entries
                                (entry_id, zone, content, status, origin, reason, created_at, updated_at)
                            VALUES (:entry_id, 'persistent', :content, 'active', 'system_migration',
                                    'v11 migration: assistant_profile data backfill',
                                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """),
                            {"entry_id": uuid4().hex[:50], "content": content},
                        )
            except Exception as backfill_err:
                logger.warning(
                    f"Profile 数据回填跳过（assistant_profile 表可能不存在）: {backfill_err}"
                )

            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 11})
            conn.commit()
            logger.info("数据库迁移到版本 11 完成：大脑架构 6 分区表 + 支撑表 + Profile 数据回填")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 11 失败: {e}")
            raise


def _load_v12_bootstrap_body() -> str:
    path = Path(DEFAULT_SEED_FILE_PATH)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        body = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        logger.warning("v12 bootstrap seed 加载失败，使用 fallback: path=%s error=%s", path, exc)
        return FALLBACK_BODY.strip()
    if not body:
        logger.warning("v12 bootstrap seed 为空，使用 fallback: path=%s", path)
        return FALLBACK_BODY.strip()
    return body


def _seed_v12_bootstrap(conn) -> None:
    """Insert the migration-safe bootstrap row without importing business services."""
    params = {
        "skill_id": BOOTSTRAP_HOW_TO_SKILL_ID,
        "name": BOOTSTRAP_NAME,
        "description": BOOTSTRAP_DESCRIPTION,
        "trigger_conditions": json.dumps(BOOTSTRAP_TRIGGERS, ensure_ascii=False),
        "required_tools": json.dumps(BOOTSTRAP_REQUIRED_TOOLS, ensure_ascii=False),
        "body_markdown": _load_v12_bootstrap_body(),
    }
    conn.execute(
        text("""
            INSERT INTO brain_skills (
                skill_id, name, description, trigger_conditions, required_tools,
                body_markdown, status, origin, chain_root_id, version,
                created_at, updated_at, loaded_count, referenced_count,
                last_changed_by, change_reason
            )
            SELECT
                :skill_id, :name, :description, :trigger_conditions, :required_tools,
                :body_markdown, 'active', 'system_bootstrap', :skill_id, 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0, 0, 'system', 'bootstrap'
            WHERE NOT EXISTS (
                SELECT 1 FROM brain_skills WHERE skill_id = :skill_id
            )
            """),
        params,
    )
    conn.execute(
        text("""
            INSERT INTO brain_skill_equipment (
                equipped_entity_type, equipped_entity_id, skill_id, status,
                equipped_order, equipped_at, created_at
            )
            SELECT 'assistant', '_assistant', :skill_id, 'active', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            WHERE EXISTS (
                SELECT 1 FROM brain_skills WHERE skill_id = :skill_id AND status = 'active'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM brain_skill_equipment
                WHERE equipped_entity_type = 'assistant'
                  AND equipped_entity_id = '_assistant'
                  AND skill_id = :skill_id
                  AND status = 'active'
            )
            """),
        params,
    )


def migrate_to_v12(engine):
    """迁移到版本 12：方法论资产层三表 + bootstrap 内置方法论。"""
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS brain_skills (
                    skill_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    trigger_conditions TEXT NOT NULL,
                    required_tools TEXT NOT NULL DEFAULT '[]',
                    body_markdown TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'superseded', 'soft_deleted')),
                    origin TEXT NOT NULL
                        CHECK (origin IN ('system_bootstrap', 'user_edit', 'assistant_tool_call',
                                          'specialist_tool_call', 'external_import')),
                    parent_skill_id TEXT REFERENCES brain_skills(skill_id),
                    superseded_by TEXT REFERENCES brain_skills(skill_id),
                    version INTEGER NOT NULL DEFAULT 1,
                    chain_root_id TEXT NOT NULL REFERENCES brain_skills(skill_id),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_changed_by TEXT,
                    change_reason TEXT,
                    loaded_count INTEGER DEFAULT 0,
                    referenced_count INTEGER DEFAULT 0,
                    last_referenced_at DATETIME,
                    CHECK ((status = 'superseded') = (superseded_by IS NOT NULL))
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS brain_skill_source_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL REFERENCES brain_skills(skill_id),
                    segment_id TEXT NOT NULL REFERENCES brain_segments(segment_id),
                    source_zone TEXT NOT NULL CHECK (source_zone IN ('archive', 'failure')),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_brain_skill_source_segment UNIQUE (skill_id, segment_id)
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS brain_skill_equipment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    equipped_entity_type TEXT NOT NULL
                        CHECK (equipped_entity_type IN ('assistant', 'specialist')),
                    equipped_entity_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL REFERENCES brain_skills(skill_id),
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'unequipped')),
                    equipped_order INTEGER NOT NULL DEFAULT 0,
                    equipped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    unequipped_at DATETIME,
                    unequipped_reason TEXT
                        CHECK (unequipped_reason IS NULL OR unequipped_reason IN
                               ('user_unequip', 'force_remove_on_soft_delete', 'supersede_transfer')),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    CHECK (
                        (status = 'active' AND unequipped_at IS NULL AND unequipped_reason IS NULL)
                        OR
                        (status = 'unequipped' AND unequipped_at IS NOT NULL AND unequipped_reason IS NOT NULL)
                    )
                )
            """))

            for index_sql in [
                "CREATE INDEX IF NOT EXISTS idx_brain_skills_status ON brain_skills(status)",
                (
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_brain_skills_active_name "
                    "ON brain_skills(name) WHERE status = 'active'"
                ),
                "CREATE INDEX IF NOT EXISTS idx_brain_skills_chain_root ON brain_skills(chain_root_id)",
                "CREATE INDEX IF NOT EXISTS idx_brain_skills_parent ON brain_skills(parent_skill_id)",
                "CREATE INDEX IF NOT EXISTS idx_brain_skills_origin ON brain_skills(origin)",
                "CREATE INDEX IF NOT EXISTS idx_brain_skills_last_referenced ON brain_skills(last_referenced_at)",
                "CREATE INDEX IF NOT EXISTS idx_brain_skill_source_skill ON brain_skill_source_segments(skill_id)",
                (
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_brain_skill_equipment_active "
                    "ON brain_skill_equipment(equipped_entity_type, equipped_entity_id, skill_id) "
                    "WHERE status = 'active'"
                ),
                (
                    "CREATE INDEX IF NOT EXISTS idx_brain_skill_equipment_entity_status "
                    "ON brain_skill_equipment(equipped_entity_type, equipped_entity_id, status)"
                ),
                (
                    "CREATE INDEX IF NOT EXISTS idx_brain_skill_equipment_skill_status "
                    "ON brain_skill_equipment(skill_id, status)"
                ),
                (
                    "CREATE INDEX IF NOT EXISTS idx_brain_skill_equipment_entity_order "
                    "ON brain_skill_equipment(equipped_entity_type, equipped_entity_id, equipped_order)"
                ),
            ]:
                conn.execute(text(index_sql))

            for trigger_sql in [
                """
                CREATE TRIGGER IF NOT EXISTS trg_brain_skills_no_delete
                BEFORE DELETE ON brain_skills
                BEGIN
                    SELECT RAISE(ABORT, 'brain_skills_no_physical_delete');
                END
                """,
                """
                CREATE TRIGGER IF NOT EXISTS trg_brain_skill_equipment_no_delete
                BEFORE DELETE ON brain_skill_equipment
                BEGIN
                    SELECT RAISE(ABORT, 'brain_skill_equipment_no_physical_delete');
                END
                """,
            ]:
                conn.execute(text(trigger_sql))

            try:
                _seed_v12_bootstrap(conn)
            except Exception as exc:
                logger.warning(
                    "v12 bootstrap seed 插入跳过，将在启动时由 SkillBootstrapService 补全: %s", exc
                )

            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 12})
            conn.commit()
            logger.info("数据库迁移到版本 12 完成：方法论资产表 + bootstrap")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 12 失败: {e}")
            raise


_MIGRATIONS = [
    (2, migrate_to_v2),
    (3, migrate_to_v3),
    (4, migrate_to_v4),
    (5, migrate_to_v5),
    (6, migrate_to_v6),
    (7, migrate_to_v7),
    (8, migrate_to_v8),
    (9, migrate_to_v9),
    (10, migrate_to_v10),
    (11, migrate_to_v11),
    (12, migrate_to_v12),
]


def run_migrations(engine):
    """运行所有待执行的迁移"""
    current_version = get_schema_version(engine)

    for version, migrate_fn in _MIGRATIONS:
        if current_version < version:
            migrate_fn(engine)
            current_version = version

    logger.info(f"数据库已是最新版本：{get_schema_version(engine)}")
