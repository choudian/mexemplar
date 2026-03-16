"""
数据库迁移脚本

添加意图确认和工具试用相关的表和字段
添加 Agent 会话和消息表
"""

import sqlite3
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def migrate_to_v2(db_manager):
    """
    迁移到版本 2：添加意图和试用相关表

    Args:
        db_manager: DatabaseManager 实例
    """
    conn = db_manager.connect()
    cursor = conn.cursor()

    try:
        # 1. 创建 intents 表
        cursor.execute(
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

        # 2. 创建 pending_tools 表
        cursor.execute(
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

        # 3. 创建 tool_trials 表
        cursor.execute(
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

        # 4. 扩展 tools 表（添加新字段）
        # 注意：SQLite 不支持直接添加带默认值的字段，需要分步处理
        # 先检查字段是否已存在
        cursor.execute("PRAGMA table_info(tools)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        # 添加新字段（如果不存在）
        if "source_intent_id" not in existing_columns:
            cursor.execute("ALTER TABLE tools ADD COLUMN source_intent_id TEXT")

        if "source" not in existing_columns:
            cursor.execute("ALTER TABLE tools ADD COLUMN source TEXT DEFAULT 'manual'")

        if "trial_count" not in existing_columns:
            cursor.execute("ALTER TABLE tools ADD COLUMN trial_count INTEGER DEFAULT 0")

        if "pending_tool_id" not in existing_columns:
            cursor.execute("ALTER TABLE tools ADD COLUMN pending_tool_id TEXT")

        # 5. 创建索引以提高查询性能
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_intents_recording_id ON intents(recording_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_intents_status ON intents(status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_tools_intent_id ON pending_tools(intent_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_tools_status ON pending_tools(status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tool_trials_pending_tool_id ON tool_trials(pending_tool_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tool_trials_status ON tool_trials(status)"
        )

        # 6. 创建试用数据模板表
        cursor.execute(
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

        # 7. 创建索引以提高查询性能
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_intents_recording_id ON intents(recording_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_intents_status ON intents(status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_tools_intent_id ON pending_tools(intent_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_tools_status ON pending_tools(status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tool_trials_pending_tool_id ON tool_trials(pending_tool_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tool_trials_status ON tool_trials(status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_trial_data_templates_pending_tool_id ON trial_data_templates(pending_tool_id)"
        )

        # 8. 更新数据库版本
        cursor.execute("UPDATE schema_version SET version = 2")

        conn.commit()
        logger.info("数据库迁移到版本 2 完成：添加意图和试用相关表")
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"数据库迁移失败: {e}")
        raise


def run_migrations(db_manager):
    """
    运行所有数据库迁移

    Args:
        db_manager: DatabaseManager 实例
    """
    current_version = db_manager.get_version()

    if current_version < 2:
        migrate_to_v2(db_manager)
        logger.info(f"数据库迁移完成：{current_version} -> 2")

    if current_version < 3:
        migrate_to_v3(db_manager)
        prev_version = current_version if current_version >= 2 else 2
        logger.info(f"数据库迁移完成：{prev_version} -> 3")

    logger.info(f"数据库已是最新版本：{db_manager.get_version()}")


def migrate_to_v3(db_manager):
    """
    迁移到版本 3：添加 Agent 会话和消息表

    新增表：
    - sessions: Agent 运行会话
    - messages: 会话消息（支持压缩和归档）
    - workflow_transitions: Agent 协作交接记录
    """
    conn = db_manager.connect()
    cursor = conn.cursor()

    try:
        # 1. 创建 sessions 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. 创建 messages 表
        cursor.execute("""
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
        """)

        # 3. 创建 workflow_transitions 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workflow_transitions (
                transition_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                from_session_id TEXT,
                to_session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 4. 创建索引
        indexes = [
            ("idx_sessions_workflow", "sessions(workflow_id)"),
            ("idx_sessions_agent_type", "sessions(agent_type)"),
            ("idx_sessions_status", "sessions(status)"),
            ("idx_messages_session", "messages(session_id, sequence)"),
            ("idx_messages_archived", "messages(session_id, is_archived)"),
            ("idx_transitions_workflow", "workflow_transitions(workflow_id)"),
        ]
        for index_name, index_def in indexes:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}")

        # 5. 更新版本号
        cursor.execute("UPDATE schema_version SET version = 3")
        conn.commit()

        logger.info("数据库迁移到版本 3 完成：添加 sessions、messages、workflow_transitions 表")

    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"迁移到版本 3 失败: {e}")
        raise
