"""
数据库迁移脚本

所有迁移函数接受 SQLAlchemy engine，通过 text() 执行原生 SQL。
新增列时应同时在 models_sqlite.py 的 ORM 模型和对应的迁移步骤中添加。
"""

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


def get_schema_version(engine) -> int:
    """读取当前 schema 版本，表不存在或无记录时返回 0"""
    with engine.connect() as conn:
        try:
            result = conn.execute(text("SELECT version FROM schema_version"))
            row = result.fetchone()
            return row[0] if row else 0
        except Exception:
            return 0


def run_migrations(engine):
    """运行所有待执行的迁移"""
    current_version = get_schema_version(engine)

    if current_version < 2:
        migrate_to_v2(engine)
        logger.info(f"数据库迁移完成：{current_version} -> 2")

    if current_version < 3:
        migrate_to_v3(engine)
        logger.info(f"数据库迁移完成：{max(current_version, 2)} -> 3")

    if current_version < 4:
        migrate_to_v4(engine)
        logger.info(f"数据库迁移完成：{max(current_version, 3)} -> 4")

    if current_version < 5:
        migrate_to_v5(engine)
        logger.info(f"数据库迁移完成：{max(current_version, 4)} -> 5")

    if current_version < 6:
        migrate_to_v6(engine)
        logger.info(f"数据库迁移完成：{max(current_version, 5)} -> 6")

    if current_version < 7:
        migrate_to_v7(engine)
        logger.info(f"数据库迁移完成：{max(current_version, 6)} -> 7")

    if current_version < 8:
        migrate_to_v8(engine)
        logger.info(f"数据库迁移完成：{max(current_version, 7)} -> 8")

    logger.info(f"数据库已是最新版本：{get_schema_version(engine)}")


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
            result = conn.execute(text("PRAGMA table_info(tools)"))
            existing_columns = {row[1] for row in result.fetchall()}
            for col, definition in [
                ("source_intent_id", "TEXT"),
                ("source", "TEXT DEFAULT 'manual'"),
                ("trial_count", "INTEGER DEFAULT 0"),
                ("pending_tool_id", "TEXT"),
            ]:
                if col not in existing_columns:
                    conn.execute(text(f"ALTER TABLE tools ADD COLUMN {col} {definition}"))

            # 索引
            for index_name, index_def in [
                ("idx_intents_recording_id", "intents(recording_id)"),
                ("idx_intents_status", "intents(status)"),
                ("idx_pending_tools_intent_id", "pending_tools(intent_id)"),
                ("idx_pending_tools_status", "pending_tools(status)"),
                ("idx_tool_trials_pending_tool_id", "tool_trials(pending_tool_id)"),
                ("idx_tool_trials_status", "tool_trials(status)"),
                ("idx_trial_data_templates_pending_tool_id", "trial_data_templates(pending_tool_id)"),
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
                try:
                    conn.execute(text(f"ALTER TABLE tools ADD COLUMN {col} {definition}"))
                except Exception:
                    pass  # 列已存在，忽略
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 4})
            conn.commit()
            logger.info("数据库迁移到版本 4 完成：tools 表新增 workflow_id、trial_success_count、status")
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
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_tfr_status ON teaching_failure_records (status)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_tfr_updated_at ON teaching_failure_records (updated_at DESC)"
            ))
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
                try:
                    conn.execute(text(f"ALTER TABLE tools ADD COLUMN {col} {definition}"))
                except Exception:
                    pass  # 列已存在，忽略
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 7})
            conn.commit()
            logger.info("数据库迁移到版本 7 完成：tools 表补齐 dependencies、workflow_id、trial_success_count、status 列")
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
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_scm_composition_tool "
                "ON skill_composition_members (composition_id, tool_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_skill_compositions_status "
                "ON skill_compositions (status)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_skill_compositions_updated_at "
                "ON skill_compositions (updated_at DESC)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_scm_composition_id "
                "ON skill_composition_members (composition_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_scm_tool_id "
                "ON skill_composition_members (tool_id)"
            ))
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 8})
            conn.commit()
            logger.info("数据库迁移到版本 8 完成：新增技能组合表与成员关系表")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 8 失败: {e}")
            raise
