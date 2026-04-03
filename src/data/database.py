"""
数据库管理模块

负责数据库连接、初始化和迁移管理

【架构约束】本模块属于数据层，只提供数据库操作接口。
上层（业务层、UI层）必须通过 Repository 模式访问数据，不能直接执行 SQL。
详见 CLAUDE.md 核心约束 #3
"""

import sqlite3
import json
import threading
from typing import Optional, Any
import logging

from src.utils.helpers import get_default_data_dir

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
            db_path = str(get_default_data_dir() / "mexemplar.db")

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

            # 创建 schema_version 表
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
                """
            )
            # 仅在表为空时插入初始版本（避免重复插入导致 UNIQUE 冲突）
            cursor.execute(
                "INSERT INTO schema_version (version) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version)"
            )

            conn.commit()
            logger.info("数据库表结构初始化完成")

            # 在 commit 之后执行迁移（migrations.py 内部自行管理事务）
            from src.data.migrations import run_migrations

            run_migrations(self)

        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"数据库初始化失败: {e}")
            raise

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

    def __enter__(self):
        """上下文管理器入口"""
        self.connect()
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
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
