"""
数据库管理模块

负责数据库连接、初始化和迁移管理
"""

import sqlite3
import os
import json
import threading
from pathlib import Path
from typing import Optional, Any, Dict, List
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    """数据库管理器"""

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化数据库管理器

        Args:
            db_path: 数据库文件路径，如果为None则使用默认路径
        """
        if db_path is None:
            # 使用默认路径：data/mexemplar.db
            project_root = Path(__file__).parent.parent.parent
            data_dir = project_root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "mexemplar.db")

        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        # 创建线程锁，保护数据库操作
        self._lock = threading.RLock()  # 使用可重入锁

    def connect(self) -> sqlite3.Connection:
        """建立数据库连接"""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            # 启用外键约束
            self.conn.execute("PRAGMA foreign_keys = ON")
            # 设置行工厂，返回字典格式
            self.conn.row_factory = sqlite3.Row
            logger.info(f"数据库连接已建立: {self.db_path}")
        return self.conn

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("数据库连接已关闭")

    def initialize(self):
        """初始化数据库表结构"""
        conn = self.connect()
        cursor = conn.cursor()

        try:
            # 创建 tools 表（工具定义）- 包含代码执行相关字段
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tools (
                    tool_id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    description TEXT,
                    parameters TEXT NOT NULL,  -- JSON格式
                    steps TEXT NOT NULL,       -- JSON格式
                    execution_code TEXT,        -- LLM生成的可执行代码
                    code_language TEXT DEFAULT 'python',
                    code_version TEXT DEFAULT '1.0',
                    execution_strategy TEXT,    -- 执行策略：api, browser, hybrid
                    source_intent_id TEXT,      -- 来源意图ID
                    source TEXT DEFAULT 'manual', -- 来源：manual, intent, trial
                    trial_count INTEGER DEFAULT 0,
                    pending_tool_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # 创建 task_executions 表（任务执行记录）
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS task_executions (
                    execution_id TEXT PRIMARY KEY,
                    tool_id TEXT NOT NULL,
                    parameters TEXT,           -- JSON格式
                    status TEXT NOT NULL,      -- 'running', 'success', 'failed', 'cancelled'
                    result TEXT,               -- JSON格式
                    error_message TEXT,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP,
                    execution_log TEXT,
                    FOREIGN KEY (tool_id) REFERENCES tools(tool_id)
                )
            """
            )

            # 创建 conversations 表（对话历史）
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    user_message TEXT NOT NULL,
                    assistant_response TEXT NOT NULL,
                    tool_used TEXT,
                    parameters_extracted TEXT,  -- JSON格式
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tool_used) REFERENCES tools(tool_id)
                )
            """
            )

            # 创建 app_settings 表（全局设置）
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT,
                    setting_type TEXT DEFAULT 'string',
                    description TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # 创建 user_preferences 表（用户偏好）
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    pref_key TEXT PRIMARY KEY,
                    pref_value TEXT,
                    pref_type TEXT DEFAULT 'string',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # 创建索引以提高查询性能
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_executions_tool_id ON task_executions(tool_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_executions_status ON task_executions(status)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_tool_used ON conversations(tool_used)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp)"
            )

            # 创建 schema_version 表
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
                """
            )
            # 插入初始版本（如果不存在）
            cursor.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (1)")

            # 执行迁移（在 commit 之前）
            self._run_migrations(cursor)

            conn.commit()
            logger.info("数据库表结构初始化完成")

        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"数据库初始化失败: {e}")
            raise

    def _run_migrations(self, cursor):
        """执行数据库迁移"""
        # 获取当前版本
        cursor.execute("SELECT version FROM schema_version")
        result = cursor.fetchone()
        current_version = result[0] if result else 1

        # 版本2：添加 execution_code 等字段到 tools 表
        if current_version < 2:
            try:
                # 检查字段是否已存在
                cursor.execute("PRAGMA table_info(tools)")
                columns = [col[1] for col in cursor.fetchall()]

                new_columns = [
                    ("execution_code", "TEXT"),
                    ("code_language", "TEXT DEFAULT 'python'"),
                    ("code_version", "TEXT DEFAULT '1.0'"),
                    ("execution_strategy", "TEXT"),
                    ("source_intent_id", "TEXT"),
                    ("source", "TEXT DEFAULT 'manual'"),
                    ("trial_count", "INTEGER DEFAULT 0"),
                    ("pending_tool_id", "TEXT"),
                ]

                for col_name, col_type in new_columns:
                    if col_name not in columns:
                        cursor.execute(f"ALTER TABLE tools ADD COLUMN {col_name} {col_type}")
                        logger.info(f"添加字段: {col_name}")

                # 更新版本
                cursor.execute("UPDATE schema_version SET version = 2")
                cursor.connection.commit()
                logger.info("数据库迁移到版本2完成")
            except sqlite3.Error as e:
                cursor.connection.rollback()
                logger.warning(f"迁移到版本2失败（可能字段已存在）: {e}")

    def get_version(self) -> int:
        """
        获取数据库版本

        Returns:
            数据库版本号
        """
        conn = self.connect()
        cursor = conn.cursor()

        # 检查是否存在版本表
        cursor.execute(
            """
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='schema_version'
        """
        )

        if cursor.fetchone() is None:
            # 创建版本表
            cursor.execute(
                """
                CREATE TABLE schema_version (
                    version INTEGER PRIMARY KEY
                )
            """
            )
            cursor.execute("INSERT INTO schema_version (version) VALUES (1)")
            conn.commit()
            return 1

        cursor.execute("SELECT version FROM schema_version")
        result = cursor.fetchone()
        return result[0] if result else 1

    def set_version(self, version: int):
        """
        设置数据库版本

        Args:
            version: 版本号
        """
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("UPDATE schema_version SET version = ?", (version,))
        conn.commit()

    def __enter__(self):
        """上下文管理器入口"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()

    # ===== 全局设置（从 ConfigDatabase 迁移）=====

    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        获取全局设置（线程安全）

        Args:
            key: 设置键
            default: 默认值

        Returns:
            设置值
        """
        with self._lock:
            conn = self.connect()
            cursor = conn.execute(
                "SELECT setting_value, setting_type FROM app_settings WHERE setting_key = ?", (key,)
            )
            row = cursor.fetchone()

            if row is None:
                return default

            value, value_type = row
            if value_type == "json":
                return json.loads(value)
            elif value_type == "int":
                return int(value)
            elif value_type == "float":
                return float(value)
            elif value_type == "bool":
                return value.lower() == "true"
            else:
                return value

    def set_setting(
        self, key: str, value: Any, value_type: str = "string", description: str = None
    ):
        """
        设置全局设置（线程安全）

        Args:
            key: 设置键
            value: 设置值
            value_type: 值类型（string, int, float, bool, json）
            description: 设置描述
        """
        with self._lock:
            # 转换值
            if value_type == "json":
                value_str = json.dumps(value, ensure_ascii=False)
            elif value_type == "bool":
                value_str = "true" if value else "false"
            else:
                value_str = str(value)

            conn = self.connect()
            conn.execute(
                """
                INSERT OR REPLACE INTO app_settings
                (setting_key, setting_value, setting_type, description, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
                (key, value_str, value_type, description),
            )

            conn.commit()


def init_database(db_path: Optional[str] = None) -> DatabaseManager:
    """
    初始化数据库

    Args:
        db_path: 数据库文件路径

    Returns:
        DatabaseManager实例
    """
    db_manager = DatabaseManager(db_path)
    db_manager.initialize()
    return db_manager
