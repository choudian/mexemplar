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
            conn.execute(
                text(
                    """
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
            """
                )
            )
            conn.execute(
                text(
                    """
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
            """
                )
            )
            conn.execute(
                text(
                    """
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
            """
                )
            )
            conn.execute(
                text(
                    """
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
            """
                )
            )

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
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
            conn.execute(
                text(
                    """
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
            """
                )
            )
            # DROP + CREATE 修复旧版本中 to_session_id TEXT NOT NULL 的错误约束
            conn.execute(text("DROP TABLE IF EXISTS workflow_transitions"))
            conn.execute(
                text(
                    """
                CREATE TABLE workflow_transitions (
                    transition_id   TEXT PRIMARY KEY,
                    workflow_id     TEXT NOT NULL,
                    from_session_id TEXT,
                    to_session_id   TEXT,
                    event_type      TEXT NOT NULL,
                    payload         TEXT,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
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
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS sessions_new (
                    session_id TEXT PRIMARY KEY,
                    workflow_id TEXT,
                    agent_type TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    tool_ids TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                INSERT OR IGNORE INTO sessions_new (session_id, workflow_id, agent_type, status, created_at, updated_at)
                SELECT session_id, workflow_id, agent_type, status, created_at, updated_at FROM sessions
            """
                )
            )
            conn.execute(text("DROP TABLE IF EXISTS sessions"))
            conn.execute(text("ALTER TABLE sessions_new RENAME TO sessions"))

            conn.execute(text("PRAGMA foreign_keys=ON"))

            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS assistant_profile (
                    profile_id TEXT PRIMARY KEY DEFAULT 'default',
                    display_name TEXT,
                    style TEXT,
                    notes TEXT,
                    raw_answers TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS pending_assistant_tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    payload TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tool_suggestion_history (
                    suggestion_id TEXT PRIMARY KEY,
                    task_pattern TEXT NOT NULL,
                    suggested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    accepted BOOLEAN,
                    times_seen INTEGER DEFAULT 0
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS assistant_summaries (
                    summary_id TEXT PRIMARY KEY,
                    level INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    source_ids TEXT,
                    embedding BLOB,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )

            for index_name, index_def in [
                ("idx_pending_tasks_status", "pending_assistant_tasks(status)"),
                ("idx_assistant_summaries_level", "assistant_summaries(level)"),
                ("idx_tool_suggestion_accepted", "tool_suggestion_history(accepted)"),
            ]:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}"))

            # FTS5 全文搜索虚拟表 + 同步触发器
            conn.execute(
                text(
                    """
                CREATE VIRTUAL TABLE IF NOT EXISTS assistant_summaries_fts
                USING fts5(summary_id UNINDEXED, content, tokenize='unicode61')
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TRIGGER IF NOT EXISTS trg_summaries_fts_insert
                AFTER INSERT ON assistant_summaries
                BEGIN
                    INSERT INTO assistant_summaries_fts(summary_id, content)
                    VALUES (new.summary_id, new.content);
                END
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TRIGGER IF NOT EXISTS trg_summaries_fts_delete
                AFTER DELETE ON assistant_summaries
                BEGIN
                    DELETE FROM assistant_summaries_fts
                    WHERE summary_id = old.summary_id;
                END
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TRIGGER IF NOT EXISTS trg_summaries_fts_update
                AFTER UPDATE OF content ON assistant_summaries
                BEGIN
                    UPDATE assistant_summaries_fts SET content = new.content
                    WHERE summary_id = new.summary_id;
                END
            """
                )
            )

            # sqlite-vec 向量搜索（扩展已由 engine 事件监听器加载，直接建表）
            try:
                conn.execute(
                    text(
                        """
                    CREATE VIRTUAL TABLE IF NOT EXISTS assistant_summaries_vec
                    USING vec0(
                        summary_id TEXT,
                        embedding float[1536] distance_metric=cosine
                    )
                """
                    )
                )
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
            conn.execute(
                text(
                    """
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
            """
                )
            )
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
            conn.execute(
                text(
                    """
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
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS skill_composition_members (
                    member_id TEXT PRIMARY KEY,
                    composition_id TEXT NOT NULL REFERENCES skill_compositions(composition_id),
                    tool_id TEXT NOT NULL REFERENCES tools(tool_id),
                    selected_order INTEGER DEFAULT 0,
                    execution_order INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
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
                    text(
                        """
                        UPDATE skill_compositions
                        SET updated_at = :updated_at
                        WHERE composition_id = :composition_id
                        """
                    ),
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
            table_exists = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'sessions'
                    """
                )
            ).fetchone()
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
            conn.execute(
                text(
                    """
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
            """
                )
            )

            # 2. brain_memory_entries 表
            conn.execute(
                text(
                    """
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
            """
                )
            )

            # 3. brain_specialists 表
            conn.execute(
                text(
                    """
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
            """
                )
            )

            # 4. brain_specialist_versions 表
            conn.execute(
                text(
                    """
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
            """
                )
            )

            # 5. brain_recruitment_signals 表
            conn.execute(
                text(
                    """
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
            """
                )
            )

            # 6. feedback_signals 表
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS feedback_signals (
                    signal_id TEXT PRIMARY KEY,
                    zone TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    context_summary TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )

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
                            text(
                                """
                            INSERT INTO brain_memory_entries
                                (entry_id, zone, content, status, origin, reason, created_at, updated_at)
                            VALUES (:entry_id, 'persistent', :content, 'active', 'system_migration',
                                    'v11 migration: assistant_profile data backfill',
                                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """
                            ),
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
        # 打包后 cwd 是安装目录，那里没有源码树；资源随 exe 走。
        from src.utils.helpers import bundled_resource_path

        path = bundled_resource_path(path)
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
        text(
            """
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
            """
        ),
        params,
    )
    conn.execute(
        text(
            """
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
            """
        ),
        params,
    )


def migrate_to_v12(engine):
    """迁移到版本 12：方法论资产层三表 + bootstrap 内置方法论。"""
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    """
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
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS brain_skill_source_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL REFERENCES brain_skills(skill_id),
                    segment_id TEXT NOT NULL REFERENCES brain_segments(segment_id),
                    source_zone TEXT NOT NULL CHECK (source_zone IN ('archive', 'failure')),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_brain_skill_source_segment UNIQUE (skill_id, segment_id)
                )
            """
                )
            )
            conn.execute(
                text(
                    """
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
            """
                )
            )

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


def migrate_to_v13(engine):
    """迁移到版本 13：Agent 内建工具 raw output 引用元数据表。"""
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tool_output_references (
                    reference_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    tool_call_id TEXT,
                    storage_key TEXT NOT NULL,
                    storage_root_kind TEXT NOT NULL DEFAULT 'app_data_tool_outputs',
                    size_bytes INTEGER NOT NULL,
                    content_type TEXT NOT NULL DEFAULT 'text/plain',
                    sha256 TEXT NOT NULL,
                    redaction_profile TEXT,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'expired', 'deleted')),
                    owner_workspace_hash TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME
                )
            """
                )
            )
            for index_sql in [
                "CREATE INDEX IF NOT EXISTS idx_tool_output_reference_id ON tool_output_references(reference_id)",
                "CREATE INDEX IF NOT EXISTS idx_tool_output_session ON tool_output_references(session_id)",
                "CREATE INDEX IF NOT EXISTS idx_tool_output_tool_call ON tool_output_references(tool_call_id)",
                "CREATE INDEX IF NOT EXISTS idx_tool_output_status ON tool_output_references(status)",
                "CREATE INDEX IF NOT EXISTS idx_tool_output_expires ON tool_output_references(expires_at)",
            ]:
                conn.execute(text(index_sql))
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 13})
            conn.commit()
            logger.info("数据库迁移到版本 13 完成：tool output reference 元数据表")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 13 失败: {e}")
            raise


def migrate_to_v14(engine):
    """迁移到版本 14：Assistant 终止失败与手动重试状态。"""
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS assistant_run_failures (
                    failure_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    message_sequence INTEGER NOT NULL,
                    category TEXT NOT NULL
                        CHECK (category IN (
                            'authentication', 'invalid_request', 'quota', 'network',
                            'provider', 'iteration_limit', 'internal'
                        )),
                    safe_message TEXT NOT NULL,
                    safe_suggestion TEXT NOT NULL,
                    internal_code TEXT,
                    exception_type TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 1
                        CHECK (attempt_count >= 1),
                    status TEXT NOT NULL DEFAULT 'failed'
                        CHECK (status IN ('failed', 'retrying', 'resolved')),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    failed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved_at DATETIME
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_assistant_run_failure_current_session
                ON assistant_run_failures(session_id)
                WHERE status IN ('failed', 'retrying')
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE INDEX IF NOT EXISTS idx_assistant_run_failure_message
                ON assistant_run_failures(session_id, message_sequence)
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE INDEX IF NOT EXISTS idx_assistant_run_failure_status
                ON assistant_run_failures(status)
            """
                )
            )
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 14})
            conn.commit()
            logger.info("数据库迁移到版本 14 完成：Assistant 失败重试状态表")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 14 失败: {e}")
            raise


def migrate_to_v15(engine):
    """迁移到版本 15：Assistant task collaboration schema。"""
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS assistant_tasks (
                    task_id TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    root_task_id TEXT,
                    parent_task_id TEXT,
                    session_id TEXT NOT NULL,
                    user_message_sequence INTEGER,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending_dispatch'
                        CHECK (status IN (
                            'pending_dispatch', 'running', 'suspended',
                            'completed', 'failed', 'cancelled'
                        )),
                    suspend_reason TEXT
                        CHECK (suspend_reason IS NULL OR suspend_reason IN
                               ('waiting_user', 'waiting_system', 'user_stop')),
                    assignee_type TEXT
                        CHECK (assignee_type IS NULL OR assignee_type IN ('ephemeral_subagent', 'specialist')),
                    assignee_id TEXT,
                    owner_session_id TEXT,
                    capability_scope TEXT,
                    graph_version INTEGER NOT NULL DEFAULT 1,
                    task_version INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    failed_at DATETIME,
                    cancelled_at DATETIME,
                    CHECK (
                        (status = 'suspended' AND suspend_reason IS NOT NULL)
                        OR
                        (status != 'suspended' AND suspend_reason IS NULL)
                    )
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS assistant_task_edges (
                    edge_id TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    source_task_id TEXT NOT NULL,
                    target_task_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL
                        CHECK (edge_type IN (
                            'dependency', 'delegation', 'question',
                            'meeting_channel', 'resource_request'
                        )),
                    propagation TEXT NOT NULL DEFAULT 'none'
                        CHECK (propagation IN ('blocking', 'cancel_cascade', 'message_only', 'none')),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS assistant_task_questions (
                    question_id TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    parent_task_id TEXT,
                    asker_type TEXT NOT NULL,
                    asker_id TEXT NOT NULL,
                    recipient_type TEXT,
                    recipient_id TEXT,
                    kind TEXT NOT NULL
                        CHECK (kind IN ('clarification', 'resource_request', 'capability_request')),
                    status TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN (
                            'open', 'escalated_to_parent', 'escalated_to_user',
                            'answered', 'cancelled', 'expired'
                        )),
                    question_text TEXT NOT NULL,
                    safe_answer_summary TEXT,
                    capability_delta TEXT,
                    escalated_to_user INTEGER NOT NULL DEFAULT 0,
                    user_request_id TEXT,
                    expires_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved_at DATETIME
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS assistant_task_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    executor_type TEXT NOT NULL
                        CHECK (executor_type IN ('ephemeral_subagent', 'specialist')),
                    executor_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'starting'
                        CHECK (status IN (
                            'starting', 'running', 'succeeded',
                            'paused', 'failed', 'cancelled', 'fenced'
                        )),
                    lease_owner TEXT NOT NULL,
                    lease_expires_at DATETIME NOT NULL,
                    heartbeat_at DATETIME,
                    fence_token INTEGER NOT NULL DEFAULT 1,
                    checkpoint_ref TEXT,
                    result_ref TEXT,
                    error_category TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    started_at DATETIME,
                    finished_at DATETIME
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS assistant_task_operations (
                    operation_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    operation_key TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    idempotency_scope TEXT NOT NULL DEFAULT 'unknown',
                    status TEXT NOT NULL DEFAULT 'planned'
                        CHECK (status IN (
                            'planned', 'in_progress', 'completed', 'failed', 'unsafe_to_retry'
                        )),
                    safe_summary TEXT NOT NULL,
                    result_ref TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS assistant_task_adjudications (
                    adjudication_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    graph_id TEXT NOT NULL,
                    parent_session_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'decided')),
                    delivered_status TEXT NOT NULL
                        CHECK (delivered_status IN ('done', 'stuck', 'failed_input')),
                    safe_summary TEXT NOT NULL,
                    raw_result_ref TEXT,
                    decision TEXT CHECK (decision IS NULL OR decision IN ('accepted', 'returned', 'abandoned')),
                    instruction TEXT,
                    decided_by TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    decided_at DATETIME
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS assistant_task_claims (
                    claim_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    claimer_type TEXT NOT NULL
                        CHECK (claimer_type IN ('ephemeral_subagent', 'specialist')),
                    claimer_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'claimed'
                        CHECK (status IN ('claimed', 'released', 'rejected', 'completed', 'expired')),
                    lease_expires_at DATETIME,
                    reject_reason TEXT,
                    task_version INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS assistant_meeting_channels (
                    channel_id TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    parent_task_id TEXT NOT NULL,
                    supervisor_session_id TEXT NOT NULL,
                    participant_a_type TEXT NOT NULL,
                    participant_a_id TEXT NOT NULL,
                    participant_b_type TEXT NOT NULL,
                    participant_b_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'concluded', 'closed_timeout', 'closed_abandoned')),
                    turn_budget INTEGER NOT NULL,
                    time_budget_seconds INTEGER NOT NULL,
                    turns_used INTEGER NOT NULL DEFAULT 0,
                    conclusion TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    closed_at DATETIME
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS assistant_meeting_messages (
                    message_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    sender_type TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS assistant_todo_items (
                    todo_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    executor_type TEXT NOT NULL
                        CHECK (executor_type IN ('ephemeral_subagent', 'specialist')),
                    executor_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'todo'
                        CHECK (status IN ('todo', 'doing', 'done', 'skipped')),
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME
                )
            """
                )
            )

            for index_sql in [
                "CREATE INDEX IF NOT EXISTS idx_assistant_tasks_graph_status ON assistant_tasks(graph_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_tasks_graph_parent ON assistant_tasks(graph_id, parent_task_id)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_tasks_session_message ON assistant_tasks(session_id, user_message_sequence)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_tasks_graph_version ON assistant_tasks(graph_id, task_version)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_edges_graph_source ON assistant_task_edges(graph_id, source_task_id)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_edges_graph_target ON assistant_task_edges(graph_id, target_task_id)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_attempts_task_status ON assistant_task_attempts(task_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_attempts_status_lease ON assistant_task_attempts(status, lease_expires_at)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_attempts_executor_status ON assistant_task_attempts(executor_type, executor_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_operations_task_key ON assistant_task_operations(task_id, operation_key)",
                (
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_assistant_task_operations_non_failed_key "
                    "ON assistant_task_operations(task_id, operation_key) WHERE status != 'failed'"
                ),
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_adjudications_task_status ON assistant_task_adjudications(task_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_adjudications_parent_status ON assistant_task_adjudications(parent_session_id, status)",
                (
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_assistant_task_adjudications_pending_task "
                    "ON assistant_task_adjudications(task_id) WHERE status = 'pending'"
                ),
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_claims_task_status ON assistant_task_claims(task_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_claims_status_lease ON assistant_task_claims(status, lease_expires_at)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_claims_claimer_status ON assistant_task_claims(claimer_type, claimer_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_questions_task_status ON assistant_task_questions(task_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_questions_graph_status ON assistant_task_questions(graph_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_task_questions_status_expires ON assistant_task_questions(status, expires_at)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_meeting_channels_graph ON assistant_meeting_channels(graph_id)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_meeting_channels_parent ON assistant_meeting_channels(parent_task_id)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_meeting_messages_channel_sequence ON assistant_meeting_messages(channel_id, sequence)",
                "CREATE INDEX IF NOT EXISTS idx_assistant_todo_items_task_sort ON assistant_todo_items(task_id, sort_order)",
            ]:
                conn.execute(text(index_sql))

            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 15})
            conn.commit()
            logger.info("数据库迁移到版本 15 完成：Assistant task collaboration schema")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 15 失败: {e}")
            raise


def migrate_to_v16(engine):
    """迁移到版本 16：task attempt/claim 加 partial unique index，DB 层兜底容量=1。

    应用层 read-check-write 在并发下可能双双通过 active=None 守卫；partial unique
    index（active-per-task / active-per-executor / active-claim-per-claimer）
    是最后防线，与 models_sqlite 的 Index 定义保持一致。Attempt 仅约束 active
    （starting/running）；I3：paused 不算 active（暂停即释放执行者槽，续跑开新
    attempt），与终态行一样不占名额。
    """
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_assistant_task_attempts_active_task "
                    "ON assistant_task_attempts (task_id) "
                    "WHERE status IN ('starting', 'running')"
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_assistant_task_attempts_active_executor "
                    "ON assistant_task_attempts (executor_type, executor_id) "
                    "WHERE status IN ('starting', 'running')"
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_assistant_task_claims_active_claimer "
                    "ON assistant_task_claims (claimer_type, claimer_id) "
                    "WHERE status = 'claimed'"
                )
            )
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 16})
            conn.commit()
            logger.info("数据库迁移到版本 16 完成：assistant task partial unique indexes")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 16 失败: {e}")
            raise


def migrate_to_v17(engine):
    """迁移到版本 17：024 task-graph-scheduling 数据脚手架。

    - assistant_tasks.requires_confirmation：高风险/不可逆节点标记，scheduler
      派发前判定是否走裁定暂停路径。DEFAULT 0 兼容现有数据。
    - brain_specialists.role_kind：专员角色分类（executor/planner），
      tool_registry 按角色分支装配工具。DEFAULT 'executor' 兼容现有专员。
    """
    with engine.connect() as conn:
        try:
            _add_column_if_missing(
                conn,
                "assistant_tasks",
                "requires_confirmation",
                "INTEGER NOT NULL DEFAULT 0",
            )
            _add_column_if_missing(
                conn,
                "brain_specialists",
                "role_kind",
                "TEXT NOT NULL DEFAULT 'executor'",
            )
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 17})
            conn.commit()
            logger.info("数据库迁移到版本 17 完成：requires_confirmation + role_kind")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 17 失败: {e}")
            raise


def migrate_to_v18(engine):
    """迁移到版本 18：用户个人待办列表。"""
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS user_todos (
                    todo_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'in_progress', 'done')),
                    priority TEXT NOT NULL DEFAULT 'medium'
                        CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME
                )
            """
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_user_todos_status_created "
                    "ON user_todos(status, created_at)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_user_todos_priority_created "
                    "ON user_todos(priority, created_at)"
                )
            )
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 18})
            conn.commit()
            logger.info("数据库迁移到版本 18 完成：user_todos")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 18 失败: {e}")
            raise


def migrate_to_v19(engine):
    """迁移到版本 19：Agent 自我改进基础设施。

    - brain_memory_entries zone CHECK 扩展：新增 'reflection' 区
    - prompt_supplements：Prompt section 级补丁（candidate/active/superseded/retracted）
    - tool_gap_reports：工具能力缺口检测
    - tool_fix_proposals：工具 bug 自动修复提案
    - self_improvement_metrics：度量时序存储
    - self_improvement_audit_log：append-only 审计日志
    """
    with engine.connect() as conn:
        try:
            # 1. 扩展 brain_memory_entries zone CHECK 约束（需重建表）
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS brain_memory_entries_new (
                    entry_id TEXT PRIMARY KEY,
                    zone TEXT NOT NULL
                        CHECK (zone IN ('hot', 'persistent', 'archive', 'subconscious',
                                        'failure', 'prediction', 'reflection')),
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
            """
                )
            )
            conn.execute(
                text(
                    """
                INSERT OR IGNORE INTO brain_memory_entries_new
                SELECT entry_id, zone, entry_type, content, status, origin, scope, reason,
                       source_segment_id, source_session_id, superseded_by,
                       loaded_count, referenced_count, relevance_score,
                       verification_checkpoint, verification_status, verification_rationale,
                       created_at, updated_at
                FROM brain_memory_entries
            """
                )
            )
            conn.execute(text("DROP TABLE IF EXISTS brain_memory_entries"))
            conn.execute(
                text("ALTER TABLE brain_memory_entries_new RENAME TO brain_memory_entries")
            )
            conn.execute(text("PRAGMA foreign_keys=ON"))

            # 重建旧索引
            for index_sql in [
                "CREATE INDEX IF NOT EXISTS idx_brain_entries_zone_status ON brain_memory_entries(zone, status)",
                "CREATE INDEX IF NOT EXISTS idx_brain_entries_source_segment ON brain_memory_entries(source_segment_id)",
                "CREATE INDEX IF NOT EXISTS idx_brain_entries_superseded_by ON brain_memory_entries(superseded_by)",
                "CREATE INDEX IF NOT EXISTS idx_brain_entries_zone_relevance ON brain_memory_entries(zone, relevance_score DESC)",
            ]:
                conn.execute(text(index_sql))

            # 2. prompt_supplements
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS prompt_supplements (
                    supplement_id TEXT PRIMARY KEY,
                    target_section TEXT NOT NULL,
                    content TEXT NOT NULL,
                    rationale TEXT,
                    metric_evidence TEXT,
                    status TEXT NOT NULL DEFAULT 'candidate'
                        CHECK (status IN ('candidate', 'active', 'superseded', 'retracted')),
                    version INTEGER DEFAULT 1,
                    prompt_hash TEXT,
                    before_snapshot TEXT,
                    after_snapshot TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    applied_at DATETIME,
                    retracted_at DATETIME
                )
            """
                )
            )

            # 3. tool_gap_reports
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tool_gap_reports (
                    report_id TEXT PRIMARY KEY,
                    gap_type TEXT NOT NULL
                        CHECK (gap_type IN ('missing_tool', 'repeated_pattern',
                                            'high_iteration', 'bug_pattern')),
                    tool_name TEXT,
                    pattern_signature TEXT,
                    occurrence_count INTEGER DEFAULT 1,
                    confidence REAL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'detected'
                        CHECK (status IN ('detected', 'trial_pending', 'resolved', 'trial_failed')),
                    evidence TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )

            # 4. tool_fix_proposals
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS tool_fix_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    tool_id TEXT NOT NULL,
                    gap_report_id TEXT,
                    proposed_code TEXT,
                    rationale TEXT,
                    status TEXT NOT NULL DEFAULT 'proposed'
                        CHECK (status IN ('proposed', 'trial_pending', 'applied', 'rejected')),
                    before_code TEXT,
                    trial_result TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    applied_at DATETIME
                )
            """
                )
            )

            # 5. self_improvement_metrics
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS self_improvement_metrics (
                    metric_id TEXT PRIMARY KEY,
                    metric_type TEXT NOT NULL,
                    metric_key TEXT,
                    metric_value REAL NOT NULL,
                    sample_size INTEGER DEFAULT 1,
                    measured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            """
                )
            )

            # 6. self_improvement_audit_log
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS self_improvement_audit_log (
                    audit_id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    before_snapshot TEXT,
                    after_snapshot TEXT,
                    rationale TEXT,
                    metric_evidence TEXT,
                    triggered_by TEXT NOT NULL DEFAULT 'auto',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )

            # 索引
            for index_sql in [
                "CREATE INDEX IF NOT EXISTS idx_prompt_supplements_status ON prompt_supplements(status)",
                "CREATE INDEX IF NOT EXISTS idx_prompt_supplements_section_version ON prompt_supplements(target_section, version)",
                "CREATE INDEX IF NOT EXISTS idx_tool_gap_reports_status ON tool_gap_reports(status)",
                "CREATE INDEX IF NOT EXISTS idx_tool_gap_reports_pattern ON tool_gap_reports(pattern_signature)",
                "CREATE INDEX IF NOT EXISTS idx_tool_fix_proposals_status ON tool_fix_proposals(status)",
                "CREATE INDEX IF NOT EXISTS idx_tool_fix_proposals_tool ON tool_fix_proposals(tool_id)",
                "CREATE INDEX IF NOT EXISTS idx_si_metrics_type_key ON self_improvement_metrics(metric_type, metric_key)",
                "CREATE INDEX IF NOT EXISTS idx_si_metrics_measured ON self_improvement_metrics(measured_at)",
                "CREATE INDEX IF NOT EXISTS idx_si_audit_action ON self_improvement_audit_log(action_type)",
                "CREATE INDEX IF NOT EXISTS idx_si_audit_target ON self_improvement_audit_log(target_type, target_id)",
                "CREATE INDEX IF NOT EXISTS idx_si_audit_created ON self_improvement_audit_log(created_at)",
            ]:
                conn.execute(text(index_sql))

            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 19})
            conn.commit()
            logger.info(
                "数据库迁移到版本 19 完成：Agent 自我改进基础设施（5 表 + reflection zone）"
            )
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 19 失败: {e}")
            raise


def migrate_to_v20(engine):
    """迁移到版本 20：执行复盘报告队列。"""
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS execution_reviews (
                    id TEXT PRIMARY KEY,
                    turn_session_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    priority INTEGER NOT NULL DEFAULT 0,
                    verdict TEXT,
                    findings_json TEXT,
                    advisory INTEGER NOT NULL DEFAULT 1,
                    model_used TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                )
            """
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_execution_reviews_status_priority "
                    "ON execution_reviews(status, priority DESC)"
                )
            )
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 20})
            conn.commit()
            logger.info("数据库迁移到版本 20 完成：execution_reviews")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 20 失败: {e}")
            raise


def migrate_to_v21(engine):
    """迁移到版本 21：改进提案表（improvement_proposals）。"""
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS improvement_proposals (
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
                    CHECK(status IN ('pending_review','approved','in_progress','done','failed','rejected')),
                    CHECK(result_tests_passed IN (0, 1) OR result_tests_passed IS NULL)
                )
            """
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_improvement_proposals_status "
                    "ON improvement_proposals(status)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_improvement_proposals_dedup_key "
                    "ON improvement_proposals(dedup_key)"
                )
            )
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 21})
            conn.commit()
            logger.info("数据库迁移到版本 21 完成：improvement_proposals")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 21 失败: {e}")
            raise


def migrate_to_v22(engine):
    """迁移到版本 22：assistant_tasks 新增 workspace_root 列（per-task 隔离工作区路径）。"""
    try:
        # 用 with engine.begin() 管理连接（自动 commit/rollback + 归还池），避免
        # raw_connection 无 finally 导致的 DBAPI 连接泄漏（026 I10）。
        with engine.begin() as conn:
            # 幂等：列已存在则跳过
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(assistant_tasks)"))}
            if "workspace_root" not in columns:
                conn.execute(text("ALTER TABLE assistant_tasks ADD COLUMN workspace_root TEXT"))
            conn.execute(text("UPDATE schema_version SET version = 22"))
    except Exception as e:
        logger.error(f"迁移到版本 22 失败: {e}")
        raise
    logger.info("迁移到版本 22 完成：assistant_tasks.workspace_root")


def migrate_to_v23(engine):
    """迁移到版本 23：收紧 improvement_proposals.result_tests_passed 三态布尔约束。"""
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='improvement_proposals'"
                )
            ).fetchone()
            if exists is None:
                conn.execute(text("UPDATE schema_version SET version = 23"))
                return

            create_sql = (
                conn.execute(
                    text(
                        "SELECT sql FROM sqlite_master "
                        "WHERE type='table' AND name='improvement_proposals'"
                    )
                ).scalar_one()
                or ""
            )
            if "result_tests_passed IN (0, 1)" in create_sql:
                conn.execute(text("UPDATE schema_version SET version = 23"))
                return

            conn.execute(text("DROP INDEX IF EXISTS ix_improvement_proposals_status"))
            conn.execute(text("DROP INDEX IF EXISTS ix_improvement_proposals_dedup_key"))
            conn.execute(
                text("ALTER TABLE improvement_proposals " "RENAME TO improvement_proposals_v22")
            )
            conn.execute(
                text(
                    """
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
                    CONSTRAINT uq_proposal_review_finding UNIQUE(source_review_id, finding_index),
                    CHECK(status IN ('pending_review','approved','in_progress','done','failed','rejected')),
                    CHECK(result_tests_passed IN (0, 1) OR result_tests_passed IS NULL)
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                INSERT INTO improvement_proposals (
                    id,
                    source_review_id,
                    finding_index,
                    status,
                    severity,
                    finding_type,
                    dedup_key,
                    what,
                    evidence,
                    suggestion,
                    user_supplement,
                    graph_id,
                    worktree_path,
                    branch_name,
                    result_tests_passed,
                    result_summary,
                    error,
                    created_at,
                    decided_at,
                    completed_at
                )
                SELECT
                    id,
                    source_review_id,
                    finding_index,
                    status,
                    severity,
                    finding_type,
                    dedup_key,
                    what,
                    evidence,
                    suggestion,
                    user_supplement,
                    graph_id,
                    worktree_path,
                    branch_name,
                    CASE
                        WHEN result_tests_passed IN (0, 1) THEN result_tests_passed
                        ELSE NULL
                    END,
                    result_summary,
                    error,
                    created_at,
                    decided_at,
                    completed_at
                FROM improvement_proposals_v22
            """
                )
            )
            conn.execute(text("DROP TABLE improvement_proposals_v22"))
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_improvement_proposals_status "
                    "ON improvement_proposals(status)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_improvement_proposals_dedup_key "
                    "ON improvement_proposals(dedup_key)"
                )
            )
            conn.execute(text("UPDATE schema_version SET version = 23"))
    except Exception as e:
        logger.error(f"迁移到版本 23 失败: {e}")
        raise
    logger.info("迁移到版本 23 完成：improvement_proposals.result_tests_passed CHECK")


def migrate_to_v24(engine):
    """迁移到版本 24：新增 mcp_servers 表。"""
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS mcp_servers (
                        server_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        transport TEXT NOT NULL CHECK (transport IN ('stdio', 'http')),
                        command TEXT,
                        args_json TEXT,
                        url TEXT,
                        headers_json TEXT,
                        secret_header_keys_json TEXT,
                        env_json TEXT,
                        secret_env_keys_json TEXT,
                        enabled BOOLEAN NOT NULL DEFAULT 1,
                        last_known_status TEXT,
                        last_error_message TEXT,
                        suggestion TEXT,
                        circuit_breaker_open BOOLEAN NOT NULL DEFAULT 0,
                        tool_count INTEGER,
                        tools_json TEXT,
                        is_preset BOOLEAN NOT NULL DEFAULT 0,
                        preset_slug TEXT,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_servers_name " "ON mcp_servers(name)"
                )
            )
            conn.execute(text("UPDATE schema_version SET version = 24"))
    except Exception as e:
        logger.error(f"迁移到版本 24 失败: {e}")
        raise
    logger.info("迁移到版本 24 完成：mcp_servers 表")


def downgrade_v24(engine):
    """回退版本 24：删除 mcp_servers 表和相关凭证。"""
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS mcp_servers"))
            conn.execute(text("DELETE FROM app_settings WHERE setting_key LIKE 'mcp.servers.%'"))
            conn.execute(text("UPDATE schema_version SET version = 23"))
    except Exception as e:
        logger.error(f"回退版本 24 失败: {e}")
        raise
    logger.info("回退版本 24 完成：mcp_servers 表已删除")


def migrate_to_v25(engine):
    """迁移到版本 25：improvement_proposals 新增 discussion_session_id 列（028）。"""
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='improvement_proposals'"
                )
            ).fetchone()
            if exists is not None:
                columns = {
                    row[1]
                    for row in conn.execute(
                        text("PRAGMA table_info(improvement_proposals)")
                    ).fetchall()
                }
                if "discussion_session_id" not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE improvement_proposals "
                            "ADD COLUMN discussion_session_id TEXT"
                        )
                    )
            conn.execute(text("UPDATE schema_version SET version = 25"))
    except Exception as e:
        logger.error(f"迁移到版本 25 失败: {e}")
        raise
    logger.info("迁移到版本 25 完成：improvement_proposals.discussion_session_id")


def downgrade_v25(engine):
    """回退版本 25：移除 discussion_session_id 列。"""
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='improvement_proposals'"
                )
            ).fetchone()
            if exists is not None:
                columns = {
                    row[1]
                    for row in conn.execute(
                        text("PRAGMA table_info(improvement_proposals)")
                    ).fetchall()
                }
                if "discussion_session_id" in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE improvement_proposals " "DROP COLUMN discussion_session_id"
                        )
                    )
            conn.execute(text("UPDATE schema_version SET version = 24"))
    except Exception as e:
        logger.error(f"回退版本 25 失败: {e}")
        raise
    logger.info("回退版本 25 完成：discussion_session_id 列已移除")


def migrate_to_v26(engine):
    """迁移到版本 26：新增 external_skill_installs 表（029 技能商店）。"""
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS external_skill_installs (
                        install_id TEXT PRIMARY KEY,
                        skill_id TEXT NOT NULL,
                        source_type TEXT NOT NULL
                            CHECK (source_type IN ('skills_sh', 'github')),
                        source_ref TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        local_dir TEXT NOT NULL,
                        installed_at TEXT NOT NULL,
                        uninstalled_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_external_skill_installs_skill_id "
                    "ON external_skill_installs(skill_id)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_external_skill_installs_source "
                    "ON external_skill_installs(source_type, source_ref)"
                )
            )
            conn.execute(text("UPDATE schema_version SET version = 26"))
    except Exception as e:
        logger.error(f"迁移到版本 26 失败: {e}")
        raise
    logger.info("迁移到版本 26 完成：external_skill_installs 表")


def downgrade_v26(engine):
    """回退版本 26：删除 external_skill_installs 表（文件目录非 schema，不在此清理）。"""
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS external_skill_installs"))
            conn.execute(text("UPDATE schema_version SET version = 25"))
    except Exception as e:
        logger.error(f"回退版本 26 失败: {e}")
        raise
    logger.info("回退版本 26 完成：external_skill_installs 表已删除")


def migrate_to_v27(engine):
    """迁移到版本 27：新增外部 coding session 表（030）。"""
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS external_coding_sessions (
                        coding_session_id TEXT PRIMARY KEY,
                        session_id TEXT,
                        owner_type TEXT NOT NULL CHECK (owner_type IN ('task', 'workflow')),
                        owner_id TEXT NOT NULL,
                        parent_session_id TEXT,
                        tool TEXT NOT NULL CHECK (tool IN ('claude_code', 'codex_cli')),
                        launch_mode TEXT NOT NULL CHECK (launch_mode IN ('headless', 'interactive')),
                        status TEXT NOT NULL CHECK (
                            status IN (
                                'created','planning','plan_ready','plan_approved','plan_rejected',
                                'implementing','interrupted','waiting_user','completed','merge_ready',
                                'merged','merge_blocked','rollback_proposed','rolled_back','abandoned','failed'
                            )
                        ),
                        phase TEXT NOT NULL CHECK (phase IN ('plan','implement','merge','rollback','done')),
                        selected_reason TEXT,
                        quota_state TEXT,
                        external_session_ref TEXT,
                        worktree_path TEXT NOT NULL,
                        branch_name TEXT NOT NULL,
                        base_commit TEXT,
                        target_branch TEXT,
                        target_worktree_path TEXT,
                        artifact_dir TEXT NOT NULL,
                        handoff_path TEXT NOT NULL,
                        plan_path TEXT,
                        result_path TEXT,
                        plan_approved_at TEXT,
                        plan_approved_by TEXT,
                        last_error_category TEXT,
                        last_error_message TEXT,
                        resume_count INTEGER NOT NULL DEFAULT 0,
                        review_recommended BOOLEAN NOT NULL DEFAULT 1,
                        review_skipped_reason TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        completed_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS external_coding_attempts (
                        attempt_id TEXT PRIMARY KEY,
                        coding_session_id TEXT NOT NULL,
                        phase TEXT NOT NULL CHECK (phase IN ('plan', 'implement')),
                        launch_mode TEXT NOT NULL CHECK (launch_mode IN ('headless', 'interactive')),
                        command_summary TEXT,
                        external_session_ref TEXT,
                        status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'interrupted', 'failed')),
                        pid INTEGER,
                        exit_code INTEGER,
                        started_at TEXT NOT NULL,
                        finished_at TEXT,
                        log_path TEXT,
                        log_tail TEXT,
                        error_category TEXT,
                        error_message TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS external_coding_quota_observations (
                        observation_id TEXT PRIMARY KEY,
                        tool TEXT NOT NULL CHECK (tool IN ('claude_code', 'codex_cli')),
                        state TEXT NOT NULL CHECK (state IN ('available', 'low', 'exhausted', 'unknown')),
                        source TEXT NOT NULL,
                        confidence REAL NOT NULL DEFAULT 0.0,
                        reset_at TEXT,
                        checked_at TEXT NOT NULL,
                        safe_detail TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS external_coding_merge_records (
                        merge_record_id TEXT PRIMARY KEY,
                        coding_session_id TEXT NOT NULL,
                        target_branch TEXT NOT NULL,
                        target_worktree_path TEXT NOT NULL,
                        pre_merge_head TEXT NOT NULL,
                        coding_branch_head TEXT NOT NULL,
                        dirty_files_json TEXT NOT NULL DEFAULT '[]',
                        changed_files_json TEXT NOT NULL DEFAULT '[]',
                        overlap_files_json TEXT NOT NULL DEFAULT '[]',
                        conflict_risk TEXT NOT NULL CHECK (
                            conflict_risk IN ('low', 'overlap', 'conflict_predicted', 'unknown')
                        ),
                        agent_decision TEXT,
                        status TEXT NOT NULL CHECK (
                            status IN ('analysis_ready', 'merged', 'blocked', 'failed', 'rolled_back')
                        ),
                        merge_commit TEXT,
                        error TEXT,
                        created_at TEXT NOT NULL,
                        merged_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS external_coding_rollback_decisions (
                        rollback_id TEXT PRIMARY KEY,
                        coding_session_id TEXT NOT NULL,
                        merge_record_id TEXT,
                        intent_summary TEXT NOT NULL,
                        chosen_strategy TEXT NOT NULL CHECK (
                            chosen_strategy IN ('revert_commit', 'reverse_patch', 'reset_hard', 'manual')
                        ),
                        requires_confirmation BOOLEAN NOT NULL DEFAULT 1,
                        confirmed_by TEXT,
                        status TEXT NOT NULL CHECK (status IN ('proposed', 'applied', 'blocked', 'failed')),
                        created_at TEXT NOT NULL,
                        applied_at TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_external_coding_sessions_owner "
                    "ON external_coding_sessions(owner_type, owner_id, updated_at)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_external_coding_sessions_session "
                    "ON external_coding_sessions(session_id, updated_at)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_external_coding_sessions_status "
                    "ON external_coding_sessions(status, updated_at)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_external_coding_attempts_session "
                    "ON external_coding_attempts(coding_session_id, started_at)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_external_coding_quota_tool_checked "
                    "ON external_coding_quota_observations(tool, checked_at)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_external_coding_merge_session "
                    "ON external_coding_merge_records(coding_session_id, created_at)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_external_coding_rollback_session "
                    "ON external_coding_rollback_decisions(coding_session_id, created_at)"
                )
            )
            conn.execute(text("UPDATE schema_version SET version = 27"))
    except Exception as e:
        logger.error(f"迁移到版本 27 失败: {e}")
        raise
    logger.info("迁移到版本 27 完成：external_coding_* 表")


def downgrade_v27(engine):
    """回退版本 27：删除外部 coding session 表。"""
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS external_coding_rollback_decisions"))
            conn.execute(text("DROP TABLE IF EXISTS external_coding_merge_records"))
            conn.execute(text("DROP TABLE IF EXISTS external_coding_quota_observations"))
            conn.execute(text("DROP TABLE IF EXISTS external_coding_attempts"))
            conn.execute(text("DROP TABLE IF EXISTS external_coding_sessions"))
            conn.execute(text("UPDATE schema_version SET version = 26"))
    except Exception as e:
        logger.error(f"回退版本 27 失败: {e}")
        raise
    logger.info("回退版本 27 完成：external_coding_* 表已删除")


def migrate_to_v28(engine):
    """迁移到版本 28：记录 external coding worktree 创建基线。"""
    try:
        with engine.begin() as conn:
            _add_column_if_missing(
                conn,
                "external_coding_sessions",
                "base_commit",
                "TEXT",
            )
            conn.execute(text("UPDATE schema_version SET version = 28"))
    except Exception as e:
        logger.error(f"迁移到版本 28 失败: {e}")
        raise
    logger.info("迁移到版本 28 完成：external coding base_commit")


def downgrade_v28(engine):
    """回退版本 28：删除 external coding 基线列。"""
    try:
        with engine.begin() as conn:
            if _column_exists(conn, "external_coding_sessions", "base_commit"):
                conn.execute(text("ALTER TABLE external_coding_sessions DROP COLUMN base_commit"))
            conn.execute(text("UPDATE schema_version SET version = 27"))
    except Exception as e:
        logger.error(f"回退版本 28 失败: {e}")
        raise
    logger.info("回退版本 28 完成：external coding base_commit 已删除")


def migrate_to_v29(engine):
    """迁移到版本 29：为专员及其版本记录增加技能组合授权。"""
    try:
        with engine.begin() as conn:
            _add_column_if_missing(
                conn,
                "brain_specialists",
                "composition_ids",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            _add_column_if_missing(
                conn,
                "brain_specialist_versions",
                "composition_ids",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            conn.execute(text("UPDATE schema_version SET version = 29"))
    except Exception as e:
        logger.error(f"迁移到版本 29 失败: {e}")
        raise
    logger.info("迁移到版本 29 完成：specialist composition_ids")


def downgrade_v29(engine):
    """回退版本 29：删除专员技能组合授权列。"""
    try:
        with engine.begin() as conn:
            if _column_exists(conn, "brain_specialist_versions", "composition_ids"):
                conn.execute(
                    text("ALTER TABLE brain_specialist_versions DROP COLUMN composition_ids")
                )
            if _column_exists(conn, "brain_specialists", "composition_ids"):
                conn.execute(text("ALTER TABLE brain_specialists DROP COLUMN composition_ids"))
            conn.execute(text("UPDATE schema_version SET version = 28"))
    except Exception as e:
        logger.error(f"回退版本 29 失败: {e}")
        raise
    logger.info("回退版本 29 完成：specialist composition_ids 已删除")


def migrate_to_v30(engine):
    """迁移到版本 30：调度中心——scheduled_tasks / scheduled_task_runs 两张新表，
    sessions 加 source / scheduled_task_id / is_scheduled 三列。

    与 ``models_sqlite.py`` 的 ``ScheduledTask`` / ``ScheduledTaskRun`` / ``Session``
    ORM 同步（ORM 头注释要求一致）。不碰 ``user_todos``（CC-001）。
    """
    try:
        with engine.begin() as conn:
            # 1) scheduled_tasks 主表（仿 v18/v21：CREATE TABLE IF NOT EXISTS + 内联 CHECK）
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    scheduled_task_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL CHECK (source_type IN ('direct', 'todo')),
                    source_ref TEXT NOT NULL,
                    title TEXT NOT NULL,
                    instruction TEXT NOT NULL,
                    schedule_kind TEXT NOT NULL CHECK (schedule_kind IN ('one_shot', 'recurring')),
                    schedule_payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'paused', 'completed', 'expired')),
                    unattended_auto_approve INTEGER NOT NULL DEFAULT 0
                        CHECK (unattended_auto_approve IN (0, 1)),
                    executor_hint TEXT,
                    next_fire_at DATETIME,
                    last_fired_at DATETIME,
                    is_deleted INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1)),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
            # 调度扫描主索引（仅活跃未软删）+ 待办悬空反查索引
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_fire "
                    "ON scheduled_tasks(next_fire_at) "
                    "WHERE status = 'active' AND is_deleted = 0"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_source_todo "
                    "ON scheduled_tasks(source_ref) "
                    "WHERE source_type = 'todo' AND is_deleted = 0"
                )
            )

            # 2) scheduled_task_runs 执行账目（append-only）
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS scheduled_task_runs (
                    run_id TEXT PRIMARY KEY,
                    scheduled_task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at DATETIME,
                    status TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running', 'succeeded', 'failed', 'waiting_user', 'skipped')),
                    summary TEXT,
                    failure_reason TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_runs_task_started "
                    "ON scheduled_task_runs(scheduled_task_id, started_at DESC)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_runs_session ON scheduled_task_runs(session_id)"
                )
            )
            # FR-011 硬门卫：同一 task 同时最多一个 active run。业务层的预读只用于
            # 快速路径，真正的并发正确性由该 partial unique index 保证。
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_active_per_task "
                    "ON scheduled_task_runs(scheduled_task_id) "
                    "WHERE status IN ('running', 'waiting_user')"
                )
            )

            # 3) sessions 加三列（仿 v10：先验表存在再 ALTER；幂等；DEFAULT 自动 backfill）。
            #    旧 baseline 测试可能从无 sessions 表的版本起步，此时跳过列变更仅推进版本号。
            sessions_exists = conn.execute(
                text("SELECT 1 FROM sqlite_master " "WHERE type = 'table' AND name = 'sessions'")
            ).fetchone()
            if sessions_exists is not None:
                _add_column_if_missing(
                    conn,
                    "sessions",
                    "source",
                    "TEXT NOT NULL DEFAULT 'user' CHECK (source IN ('user', 'scheduled'))",
                )
                _add_column_if_missing(conn, "sessions", "scheduled_task_id", "TEXT")
                _add_column_if_missing(
                    conn, "sessions", "is_scheduled", "INTEGER NOT NULL DEFAULT 0"
                )
            else:
                logger.info("迁移到版本 30：sessions 表不存在，跳过 source 等列")

            conn.execute(text("UPDATE schema_version SET version = 30"))
    except Exception as e:
        logger.error(f"迁移到版本 30 失败: {e}")
        raise
    logger.info("迁移到版本 30 完成：scheduled_tasks / scheduled_task_runs / sessions.source")


def migrate_to_v31(engine):
    """迁移到版本 31：scheduled run 终态事件的持久投递确认。"""
    try:
        with engine.begin() as conn:
            runs_exists = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'scheduled_task_runs'"
                )
            ).fetchone()
            if runs_exists is not None:
                _add_column_if_missing(
                    conn,
                    "scheduled_task_runs",
                    "terminal_event_delivered_at",
                    "DATETIME",
                )
                _add_column_if_missing(
                    conn,
                    "scheduled_task_runs",
                    "terminal_event_version",
                    "INTEGER NOT NULL DEFAULT 0",
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_runs_terminal_event_pending "
                        "ON scheduled_task_runs(terminal_event_delivered_at, started_at) "
                        "WHERE status IN ('succeeded', 'failed', 'waiting_user')"
                    )
                )
            else:
                logger.info("迁移到版本 31：scheduled_task_runs 表不存在，跳过终态投递列")
            conn.execute(text("UPDATE schema_version SET version = 31"))
    except Exception as e:
        logger.error(f"迁移到版本 31 失败: {e}")
        raise
    logger.info("迁移到版本 31 完成：scheduled run 终态事件按代次可恢复投递")


def migrate_to_v32(engine):
    """迁移到版本 32：scheduled task 常驻会话 + run 消息窗口归属。"""
    try:
        with engine.begin() as conn:
            tasks_exists = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'scheduled_tasks'"
                )
            ).fetchone()
            if tasks_exists is not None:
                _add_column_if_missing(conn, "scheduled_tasks", "session_id", "TEXT")
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_scheduled_tasks_session "
                        "ON scheduled_tasks(session_id) WHERE session_id IS NOT NULL"
                    )
                )
            else:
                logger.info("迁移到版本 32：scheduled_tasks 表不存在，跳过常驻会话列")

            runs_exists = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'scheduled_task_runs'"
                )
            ).fetchone()
            if runs_exists is not None:
                _add_column_if_missing(
                    conn,
                    "scheduled_task_runs",
                    "baseline_message_sequence",
                    "INTEGER NOT NULL DEFAULT 0",
                )
                _add_column_if_missing(
                    conn,
                    "scheduled_task_runs",
                    "trigger_message_sequence",
                    "INTEGER",
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_active_per_session "
                        "ON scheduled_task_runs(session_id) "
                        "WHERE status IN ('running', 'waiting_user')"
                    )
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_session_trigger "
                        "ON scheduled_task_runs(session_id, trigger_message_sequence) "
                        "WHERE trigger_message_sequence IS NOT NULL"
                    )
                )
            else:
                logger.info("迁移到版本 32：scheduled_task_runs 表不存在，跳过消息窗口列")

            sessions_exists = conn.execute(
                text("SELECT 1 FROM sqlite_master " "WHERE type = 'table' AND name = 'sessions'")
            ).fetchone()
            if tasks_exists is not None and runs_exists is not None and sessions_exists is not None:
                # 每个 task 只认最近一条关系完整的真实 scheduled session。非法/缺失历史
                # 保持 NULL，交给下一次 launch 惰性创建，绝不伪造绑定。
                conn.execute(
                    text(
                        "UPDATE scheduled_tasks AS task "
                        "SET session_id = ("
                        "  SELECT run.session_id "
                        "  FROM scheduled_task_runs AS run "
                        "  JOIN sessions AS sess ON sess.session_id = run.session_id "
                        "  WHERE run.scheduled_task_id = task.scheduled_task_id "
                        "    AND sess.agent_type = 'assistant' "
                        "    AND sess.status IN "
                        "      ('active', 'archived', 'completed', 'suspended', 'failed') "
                        "    AND sess.source = 'scheduled' "
                        "    AND sess.is_scheduled = 1 "
                        "    AND sess.scheduled_task_id = task.scheduled_task_id "
                        "  ORDER BY run.started_at DESC, run.run_id DESC "
                        "  LIMIT 1"
                        ") "
                        "WHERE task.session_id IS NULL"
                    )
                )
            conn.execute(text("UPDATE schema_version SET version = 32"))
    except Exception as e:
        logger.error(f"迁移到版本 32 失败: {e}")
        raise
    logger.info("迁移到版本 32 完成：scheduled task 常驻会话与 run 消息窗口")


def downgrade_v32(engine):
    """回退版本 32（仅测试调用，不注册）。"""
    try:
        with engine.begin() as conn:
            runs_exists = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'scheduled_task_runs'"
                )
            ).fetchone()
            if runs_exists is not None:
                conn.execute(text("DROP INDEX IF EXISTS uq_runs_session_trigger"))
                conn.execute(text("DROP INDEX IF EXISTS uq_runs_active_per_session"))
                if _column_exists(
                    conn,
                    "scheduled_task_runs",
                    "trigger_message_sequence",
                ):
                    conn.execute(
                        text(
                            "ALTER TABLE scheduled_task_runs "
                            "DROP COLUMN trigger_message_sequence"
                        )
                    )
                if _column_exists(
                    conn,
                    "scheduled_task_runs",
                    "baseline_message_sequence",
                ):
                    conn.execute(
                        text(
                            "ALTER TABLE scheduled_task_runs "
                            "DROP COLUMN baseline_message_sequence"
                        )
                    )
            tasks_exists = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'scheduled_tasks'"
                )
            ).fetchone()
            if tasks_exists is not None:
                conn.execute(text("DROP INDEX IF EXISTS uq_scheduled_tasks_session"))
                if _column_exists(conn, "scheduled_tasks", "session_id"):
                    conn.execute(text("ALTER TABLE scheduled_tasks DROP COLUMN session_id"))
            conn.execute(text("UPDATE schema_version SET version = 31"))
    except Exception as e:
        logger.error(f"回退版本 32 失败: {e}")
        raise
    logger.info("回退版本 32 完成：移除 scheduled session reuse 字段")


def migrate_to_v33(engine):
    """迁移到版本 33：持久化 external coding 进程 ownership 身份。"""
    try:
        with engine.begin() as conn:
            attempts_exists = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'external_coding_attempts'"
                )
            ).fetchone()
            if attempts_exists is not None:
                launch_started_exists = _column_exists(
                    conn,
                    "external_coding_attempts",
                    "launch_started",
                )
                termination_unconfirmed_exists = _column_exists(
                    conn,
                    "external_coding_attempts",
                    "termination_unconfirmed",
                )
                _add_column_if_missing(
                    conn,
                    "external_coding_attempts",
                    "process_create_time",
                    "REAL",
                )
                _add_column_if_missing(
                    conn,
                    "external_coding_attempts",
                    "termination_unconfirmed",
                    "BOOLEAN NOT NULL DEFAULT 0",
                )
                if not termination_unconfirmed_exists:
                    # Pre-v33 running rows may still own a live CLI, but they
                    # have no creation-time proof. Keep them fail-closed.
                    conn.execute(
                        text(
                            "UPDATE external_coding_attempts "
                            "SET termination_unconfirmed = 1 "
                            "WHERE status = 'running'"
                        )
                    )
                _add_column_if_missing(
                    conn,
                    "external_coding_attempts",
                    "launch_started",
                    "BOOLEAN NOT NULL DEFAULT 0",
                )
                if not launch_started_exists:
                    # Every row predating v33 was created by calling an adapter;
                    # only new v33 reservations may safely remain false.
                    conn.execute(text("UPDATE external_coding_attempts SET launch_started = 1"))
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS "
                        "uq_external_coding_attempts_active_session "
                        "ON external_coding_attempts(coding_session_id) "
                        "WHERE status = 'running'"
                    )
                )
                ownership_guard = (
                    "((NEW.status = 'running' AND NEW.termination_unconfirmed != 1) "
                    "OR (NEW.status != 'running' AND NEW.termination_unconfirmed != 0) "
                    "OR (NEW.launch_started = 0 AND "
                    "(NEW.pid IS NOT NULL OR NEW.process_create_time IS NOT NULL)) "
                    "OR (NEW.process_create_time IS NOT NULL AND NEW.pid IS NULL))"
                )
                ownership_update_guard = (
                    f"({ownership_guard} OR "
                    "(OLD.launch_started = 1 AND NEW.launch_started = 0))"
                )
                conn.execute(
                    text("DROP TRIGGER IF EXISTS trg_external_coding_attempts_ownership_insert")
                )
                conn.execute(
                    text("DROP TRIGGER IF EXISTS trg_external_coding_attempts_ownership_update")
                )
                conn.execute(
                    text(
                        "CREATE TRIGGER IF NOT EXISTS "
                        "trg_external_coding_attempts_ownership_insert "
                        "BEFORE INSERT ON external_coding_attempts "
                        f"WHEN {ownership_guard} "
                        "BEGIN SELECT RAISE(ABORT, "
                        "'invalid external coding process ownership state'); END"
                    )
                )
                conn.execute(
                    text(
                        "CREATE TRIGGER IF NOT EXISTS "
                        "trg_external_coding_attempts_ownership_update "
                        "BEFORE UPDATE ON external_coding_attempts "
                        f"WHEN {ownership_update_guard} "
                        "BEGIN SELECT RAISE(ABORT, "
                        "'invalid external coding process ownership state'); END"
                    )
                )
            else:
                logger.info("迁移到版本 33：external_coding_attempts 表不存在，跳过 ownership 列")
            conn.execute(text("UPDATE schema_version SET version = 33"))
    except Exception as e:
        logger.error(f"迁移到版本 33 失败: {e}")
        raise
    logger.info("迁移到版本 33 完成：external coding 进程 ownership 身份")


def downgrade_v33(engine):
    """回退版本 33（仅测试调用，不注册）。"""
    try:
        with engine.begin() as conn:
            attempts_exists = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'external_coding_attempts'"
                )
            ).fetchone()
            if attempts_exists is not None:
                conn.execute(
                    text("DROP TRIGGER IF EXISTS trg_external_coding_attempts_ownership_insert")
                )
                conn.execute(
                    text("DROP TRIGGER IF EXISTS trg_external_coding_attempts_ownership_update")
                )
                conn.execute(
                    text("DROP INDEX IF EXISTS uq_external_coding_attempts_active_session")
                )
                if _column_exists(
                    conn,
                    "external_coding_attempts",
                    "launch_started",
                ):
                    conn.execute(
                        text("ALTER TABLE external_coding_attempts " "DROP COLUMN launch_started")
                    )
                if _column_exists(
                    conn,
                    "external_coding_attempts",
                    "termination_unconfirmed",
                ):
                    conn.execute(
                        text(
                            "ALTER TABLE external_coding_attempts "
                            "DROP COLUMN termination_unconfirmed"
                        )
                    )
                if _column_exists(
                    conn,
                    "external_coding_attempts",
                    "process_create_time",
                ):
                    conn.execute(
                        text(
                            "ALTER TABLE external_coding_attempts "
                            "DROP COLUMN process_create_time"
                        )
                    )
            conn.execute(text("UPDATE schema_version SET version = 32"))
    except Exception as e:
        logger.error(f"回退版本 33 失败: {e}")
        raise
    logger.info("回退版本 33 完成：移除 external coding ownership 字段")


def migrate_to_v34(engine):
    """迁移到版本 34：assistant 消息记录本次调用的 token 用量。

    provider 每次都上报用量，此前被整体丢弃。落到消息上而非独立表，
    是为了天然按会话 / 任务 / 专员聚合，且压缩触发能直接读到最后一条
    assistant 消息的真实 input_tokens。
    """
    try:
        with engine.begin() as conn:
            messages_exists = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'messages'"
                )
            ).fetchone()
            if messages_exists is not None:
                _add_column_if_missing(conn, "messages", "token_usage", "TEXT")
            else:
                logger.info("迁移到版本 34：messages 表不存在，跳过 token 用量列")
            conn.execute(text("UPDATE schema_version SET version = 34"))
    except Exception as e:
        logger.error(f"迁移到版本 34 失败: {e}")
        raise
    logger.info("迁移到版本 34 完成：messages 记录 token 用量")


def downgrade_from_v34(engine):
    """回退版本 34：移除 token 用量列。"""
    try:
        with engine.begin() as conn:
            columns = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(messages)")).fetchall()
            }
            if "token_usage" in columns:
                conn.execute(text("ALTER TABLE messages DROP COLUMN token_usage"))
            conn.execute(text("UPDATE schema_version SET version = 33"))
    except Exception as e:
        logger.error(f"回退版本 34 失败: {e}")
        raise
    logger.info("回退版本 34 完成：移除 token 用量列")


def migrate_to_v35(engine):
    """迁移到版本 35：内置专员种子的归属与改动标记。

    ``preset_key`` 让种子在用户改名后仍能认出同一个专员；
    ``preset_fingerprint`` 记录种子写入时的内容摘要，与当前内容不符即说明
    用户改过，此后不再自动更新——否则每次升级都会撤销一次用户的修改。
    """
    try:
        with engine.begin() as conn:
            table_exists = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'brain_specialists'"
                )
            ).fetchone()
            if table_exists is not None:
                _add_column_if_missing(conn, "brain_specialists", "preset_key", "TEXT")
                _add_column_if_missing(
                    conn, "brain_specialists", "preset_fingerprint", "TEXT"
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS "
                        "uq_brain_specialists_preset_key "
                        "ON brain_specialists(preset_key) WHERE preset_key IS NOT NULL"
                    )
                )
            else:
                logger.info("迁移到版本 35：brain_specialists 表不存在，跳过种子标记列")
            conn.execute(text("UPDATE schema_version SET version = 35"))
    except Exception as e:
        logger.error(f"迁移到版本 35 失败: {e}")
        raise
    logger.info("迁移到版本 35 完成：内置专员可安全升级且不覆盖用户改动")


def migrate_to_v36(engine):
    """迁移到版本 36：执行记录补上"这次开工跑在哪个会话里"。

    派活发生在执行体被创建之前，所以 ``executor_id`` 对临时子代理只能填任务 id 顶替
    （见 ``graph_scheduler`` 的执行器解析）。结果是"谁在干这活"在库里根本不存在：
    ``ask_parent`` / ``todo_update`` 的归属校验查无此人，任务也无法下钻到执行过程。
    本列由执行体在 agent loop 启动前回填，是该问题唯一缺失的事实。

    既有行保持 NULL——它们的执行早已结束，补造身份只会伪造无法验证的关联。
    """
    try:
        with engine.begin() as conn:
            table_exists = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'assistant_task_attempts'"
                )
            ).fetchone()
            if table_exists is not None:
                _add_column_if_missing(
                    conn, "assistant_task_attempts", "executor_session_id", "TEXT"
                )
            else:
                logger.info("迁移到版本 36：assistant_task_attempts 表不存在，跳过执行会话列")
            conn.execute(text("UPDATE schema_version SET version = 36"))
    except Exception as e:
        logger.error(f"迁移到版本 36 失败: {e}")
        raise
    logger.info("迁移到版本 36 完成：执行记录可追溯到执行会话")


def migrate_to_v37(engine):
    """迁移到版本 37：扩展 Assistant Task 的暂停原因约束。"""
    try:
        with engine.begin() as conn:
            table_exists = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'assistant_tasks'"
                )
            ).fetchone()
            if table_exists is not None:
                conn.execute(
                    text(
                        """
                        CREATE TABLE assistant_tasks_v37 (
                            task_id TEXT PRIMARY KEY,
                            graph_id TEXT NOT NULL,
                            root_task_id TEXT,
                            parent_task_id TEXT,
                            session_id TEXT NOT NULL,
                            user_message_sequence INTEGER,
                            title TEXT NOT NULL,
                            description TEXT NOT NULL,
                            status TEXT NOT NULL DEFAULT 'pending_dispatch'
                                CONSTRAINT ck_assistant_tasks_status
                                CHECK (status IN (
                                    'pending_dispatch', 'running', 'suspended',
                                    'completed', 'failed', 'cancelled'
                                )),
                            suspend_reason TEXT
                                CONSTRAINT ck_assistant_tasks_suspend_reason
                                CHECK (
                                    suspend_reason IS NULL OR suspend_reason IN (
                                        'waiting_user', 'waiting_system', 'user_stop',
                                        'budget_exhausted', 'interrupted'
                                    )
                                ),
                            assignee_type TEXT
                                CONSTRAINT ck_assistant_tasks_assignee_type
                                CHECK (
                                    assignee_type IS NULL OR assignee_type IN (
                                        'ephemeral_subagent', 'specialist'
                                    )
                                ),
                            assignee_id TEXT,
                            owner_session_id TEXT,
                            capability_scope TEXT,
                            graph_version INTEGER NOT NULL DEFAULT 1,
                            task_version INTEGER NOT NULL DEFAULT 1,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            completed_at DATETIME,
                            failed_at DATETIME,
                            cancelled_at DATETIME,
                            requires_confirmation INTEGER NOT NULL DEFAULT 0,
                            workspace_root TEXT,
                            CONSTRAINT ck_assistant_tasks_suspend_reason_required CHECK (
                                (status = 'suspended' AND suspend_reason IS NOT NULL)
                                OR
                                (status != 'suspended' AND suspend_reason IS NULL)
                            )
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO assistant_tasks_v37 (
                            task_id, graph_id, root_task_id, parent_task_id,
                            session_id, user_message_sequence, title, description,
                            status, suspend_reason, assignee_type, assignee_id,
                            owner_session_id, capability_scope, graph_version,
                            task_version, created_at, updated_at, completed_at,
                            failed_at, cancelled_at, requires_confirmation,
                            workspace_root
                        )
                        SELECT
                            task_id, graph_id, root_task_id, parent_task_id,
                            session_id, user_message_sequence, title, description,
                            status, suspend_reason, assignee_type, assignee_id,
                            owner_session_id, capability_scope, graph_version,
                            task_version, created_at, updated_at, completed_at,
                            failed_at, cancelled_at, requires_confirmation,
                            workspace_root
                        FROM assistant_tasks
                        """
                    )
                )
                conn.execute(text("DROP TABLE assistant_tasks"))
                conn.execute(text("ALTER TABLE assistant_tasks_v37 RENAME TO assistant_tasks"))
                for index_sql in (
                    "CREATE INDEX idx_assistant_tasks_graph_status "
                    "ON assistant_tasks(graph_id, status)",
                    "CREATE INDEX idx_assistant_tasks_graph_parent "
                    "ON assistant_tasks(graph_id, parent_task_id)",
                    "CREATE INDEX idx_assistant_tasks_session_message "
                    "ON assistant_tasks(session_id, user_message_sequence)",
                    "CREATE INDEX idx_assistant_tasks_graph_version "
                    "ON assistant_tasks(graph_id, task_version)",
                ):
                    conn.execute(text(index_sql))
            else:
                logger.info("迁移到版本 37：assistant_tasks 表不存在，跳过约束重建")
            conn.execute(text("UPDATE schema_version SET version = 37"))
    except Exception as e:
        logger.error(f"迁移到版本 37 失败: {e}")
        raise
    logger.info("迁移到版本 37 完成：Assistant Task 暂停原因约束已扩展")


# 与 src/business/task_collaboration/models.py 的 _SUSPEND_REASON_WAITING_ON 同源。
# 两处必须一致，由 tests/data/test_migrations_v38.py 的一致性测试守住。
_V38_WAITING_ON_BACKFILL = """
                            CASE suspend_reason
                                WHEN 'waiting_user'     THEN 'user'
                                WHEN 'user_stop'        THEN 'user'
                                WHEN 'budget_exhausted' THEN 'assistant'
                                WHEN 'waiting_system'   THEN 'assistant'
                                WHEN 'interrupted'      THEN 'system'
                                ELSE NULL
                            END
"""


def migrate_to_v38(engine):
    """迁移到版本 38：assistant_tasks 新增 waiting_on（暂停时球在谁手上）。

    ``waiting_on`` 是持久化的通知意图——状态落库即等于通知已发出，派发时直接读它，
    不做第二次判断。此前落库写 ``suspend_reason``、而决定是否通知父侧的代码查另一套
    白名单，两套判断对不上，撞轮次预算暂停的任务永远没人被告知。

    与 ``suspend_reason`` 同生同灭（见 ck_assistant_tasks_waiting_on_required），
    保证不会出现"有原因却不知道等谁"或反之。
    """
    try:
        with engine.begin() as conn:
            table_exists = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'assistant_tasks'"
                )
            ).fetchone()
            if table_exists is not None:
                existing_columns = {
                    row[1] for row in conn.execute(text("PRAGMA table_info(assistant_tasks)"))
                }
                # 重跑时旧表已带 waiting_on，原样搬运；只有首次迁移才按 suspend_reason
                # 回填。两者不能混——被显式改写过的 waiting_on（例如球从主助理换手到
                # 用户）不该被推导值覆盖回去。
                waiting_on_source = (
                    "waiting_on" if "waiting_on" in existing_columns else _V38_WAITING_ON_BACKFILL
                )
                conn.execute(
                    text(
                        """
                        CREATE TABLE assistant_tasks_v38 (
                            task_id TEXT PRIMARY KEY,
                            graph_id TEXT NOT NULL,
                            root_task_id TEXT,
                            parent_task_id TEXT,
                            session_id TEXT NOT NULL,
                            user_message_sequence INTEGER,
                            title TEXT NOT NULL,
                            description TEXT NOT NULL,
                            status TEXT NOT NULL DEFAULT 'pending_dispatch'
                                CONSTRAINT ck_assistant_tasks_status
                                CHECK (status IN (
                                    'pending_dispatch', 'running', 'suspended',
                                    'completed', 'failed', 'cancelled'
                                )),
                            suspend_reason TEXT
                                CONSTRAINT ck_assistant_tasks_suspend_reason
                                CHECK (
                                    suspend_reason IS NULL OR suspend_reason IN (
                                        'waiting_user', 'waiting_system', 'user_stop',
                                        'budget_exhausted', 'interrupted'
                                    )
                                ),
                            waiting_on TEXT
                                CONSTRAINT ck_assistant_tasks_waiting_on
                                CHECK (
                                    waiting_on IS NULL OR waiting_on IN (
                                        'user', 'assistant', 'system'
                                    )
                                ),
                            assignee_type TEXT
                                CONSTRAINT ck_assistant_tasks_assignee_type
                                CHECK (
                                    assignee_type IS NULL OR assignee_type IN (
                                        'ephemeral_subagent', 'specialist'
                                    )
                                ),
                            assignee_id TEXT,
                            owner_session_id TEXT,
                            capability_scope TEXT,
                            graph_version INTEGER NOT NULL DEFAULT 1,
                            task_version INTEGER NOT NULL DEFAULT 1,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            completed_at DATETIME,
                            failed_at DATETIME,
                            cancelled_at DATETIME,
                            requires_confirmation INTEGER NOT NULL DEFAULT 0,
                            workspace_root TEXT,
                            CONSTRAINT ck_assistant_tasks_suspend_reason_required CHECK (
                                (status = 'suspended' AND suspend_reason IS NOT NULL)
                                OR
                                (status != 'suspended' AND suspend_reason IS NULL)
                            ),
                            CONSTRAINT ck_assistant_tasks_waiting_on_required CHECK (
                                (status = 'suspended' AND waiting_on IS NOT NULL)
                                OR
                                (status != 'suspended' AND waiting_on IS NULL)
                            )
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        f"""
                        INSERT INTO assistant_tasks_v38 (
                            task_id, graph_id, root_task_id, parent_task_id,
                            session_id, user_message_sequence, title, description,
                            status, suspend_reason, waiting_on, assignee_type,
                            assignee_id, owner_session_id, capability_scope,
                            graph_version, task_version, created_at, updated_at,
                            completed_at, failed_at, cancelled_at,
                            requires_confirmation, workspace_root
                        )
                        SELECT
                            task_id, graph_id, root_task_id, parent_task_id,
                            session_id, user_message_sequence, title, description,
                            status, suspend_reason,
                            {waiting_on_source},
                            assignee_type,
                            assignee_id, owner_session_id, capability_scope,
                            graph_version, task_version, created_at, updated_at,
                            completed_at, failed_at, cancelled_at,
                            requires_confirmation, workspace_root
                        FROM assistant_tasks
                        """
                    )
                )
                conn.execute(text("DROP TABLE assistant_tasks"))
                conn.execute(text("ALTER TABLE assistant_tasks_v38 RENAME TO assistant_tasks"))
                for index_sql in (
                    "CREATE INDEX idx_assistant_tasks_graph_status "
                    "ON assistant_tasks(graph_id, status)",
                    "CREATE INDEX idx_assistant_tasks_graph_parent "
                    "ON assistant_tasks(graph_id, parent_task_id)",
                    "CREATE INDEX idx_assistant_tasks_session_message "
                    "ON assistant_tasks(session_id, user_message_sequence)",
                    "CREATE INDEX idx_assistant_tasks_graph_version "
                    "ON assistant_tasks(graph_id, task_version)",
                ):
                    conn.execute(text(index_sql))
            else:
                logger.info("迁移到版本 38：assistant_tasks 表不存在，跳过 waiting_on 新增")
            conn.execute(text("UPDATE schema_version SET version = 38"))
    except Exception as e:
        logger.error(f"迁移到版本 38 失败: {e}")
        raise
    logger.info("迁移到版本 38 完成：assistant_tasks.waiting_on")


def downgrade_from_v36(engine):
    """回退版本 36：移除执行会话列。"""
    try:
        with engine.begin() as conn:
            columns = {
                row[1]
                for row in conn.execute(
                    text("PRAGMA table_info(assistant_task_attempts)")
                ).fetchall()
            }
            if "executor_session_id" in columns:
                conn.execute(
                    text("ALTER TABLE assistant_task_attempts DROP COLUMN executor_session_id")
                )
            conn.execute(text("UPDATE schema_version SET version = 35"))
    except Exception as e:
        logger.error(f"回退版本 36 失败: {e}")
        raise
    logger.info("回退版本 36 完成：移除执行会话列")


def downgrade_from_v35(engine):
    """回退版本 35：移除种子标记列。"""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("DROP INDEX IF EXISTS uq_brain_specialists_preset_key")
            )
            columns = {
                row[1]
                for row in conn.execute(
                    text("PRAGMA table_info(brain_specialists)")
                ).fetchall()
            }
            for column in ("preset_key", "preset_fingerprint"):
                if column in columns:
                    conn.execute(
                        text(f"ALTER TABLE brain_specialists DROP COLUMN {column}")
                    )
            conn.execute(text("UPDATE schema_version SET version = 34"))
    except Exception as e:
        logger.error(f"回退版本 35 失败: {e}")
        raise
    logger.info("回退版本 35 完成：移除内置专员种子标记列")


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
    (13, migrate_to_v13),
    (14, migrate_to_v14),
    (15, migrate_to_v15),
    (16, migrate_to_v16),
    (17, migrate_to_v17),
    (18, migrate_to_v18),
    (19, migrate_to_v19),
    (20, migrate_to_v20),
    (21, migrate_to_v21),
    (22, migrate_to_v22),
    (23, migrate_to_v23),
    (24, migrate_to_v24),
    (25, migrate_to_v25),
    (26, migrate_to_v26),
    (27, migrate_to_v27),
    (28, migrate_to_v28),
    (29, migrate_to_v29),
    (30, migrate_to_v30),
    (31, migrate_to_v31),
    (32, migrate_to_v32),
    (33, migrate_to_v33),
    (34, migrate_to_v34),
    (35, migrate_to_v35),
    (36, migrate_to_v36),
    (37, migrate_to_v37),
    (38, migrate_to_v38),
]


def run_migrations(engine):
    """运行所有待执行的迁移"""
    current_version = get_schema_version(engine)

    for version, migrate_fn in _MIGRATIONS:
        if current_version < version:
            migrate_fn(engine)
            current_version = version

    logger.info(f"数据库已是最新版本：{get_schema_version(engine)}")
