"""
DuckDB 管理模块

负责 DuckDB 数据库连接、初始化和录制数据存储管理
"""

import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Any, List, Dict
import duckdb

from src.utils.helpers import get_default_data_dir

logger = logging.getLogger(__name__)

# 表名白名单，防止通过 f-string 拼接导致的 SQL 注入
_VALID_TABLES = frozenset([
    "recording_sessions",
    "actions",
    "network_requests",
    "filter_decisions",
    "sibling_snapshots",
    "recording_screenshots",
])

# 每个表的合法列名白名单，防止 data.keys() 注入
# ⚠️ 与 recording_data_tools._COMMON_TABLES.fields 保持同步
_VALID_COLUMNS: dict[str, frozenset] = {
    "recording_sessions": frozenset([
        "recording_id", "status", "recording_mode", "browser_type",
        "start_time", "end_time", "metadata", "created_at",
    ]),
    "actions": frozenset([
        "action_id", "recording_id", "sequence_number", "action_type",
        "recording_mode", "app_name", "process_name", "window_title",
        "parameters", "url", "dom_element", "dom_tree_snapshot",
        "visual_features",
        "timestamp",
    ]),
    "network_requests": frozenset([
        "request_id", "action_id", "recording_id", "url", "method",
        "request_type", "request_headers", "request_body",
        "response_status", "response_headers", "response_body",
        "duration", "timestamp", "filtered", "filter_reason",
        "filtered_at", "is_recommendation", "importance_level",
    ]),
    "filter_decisions": frozenset([
        "decision_id", "request_id", "action_id", "recording_id",
        "decision", "source", "confidence", "reason",
        "pattern_matched", "scores", "request_timestamp",
        "action_timestamp", "timestamp",
    ]),
    "sibling_snapshots": frozenset([
        "snapshot_id", "action_id", "recording_id",
        "container_selector", "item_selector", "list_type",
        "siblings", "structure_similarity", "is_homogeneous",
        "clicked_index", "total_count", "timestamp",
    ]),
    "recording_screenshots": frozenset([
        "screenshot_id", "recording_id", "moment", "timestamp",
        "capture_id", "source_trigger", "input_started_at",
        "input_completed_at", "media_type", "data",
    ]),
}


def _validate_columns(table: str, data: dict) -> None:
    """验证列名是否在白名单中，防止 SQL 注入"""
    valid = _VALID_COLUMNS.get(table)
    if valid is None:
        logger.warning(f"表 '{table}' 未在列名白名单中注册，跳过列验证")
        return
    invalid = [k for k in data.keys() if k not in valid]
    if invalid:
        raise ValueError(f"表 '{table}' 包含非法列名: {invalid}")

# 全局单例
_duckdb_instance: Optional["DuckDBManager"] = None
_duckdb_lock = threading.Lock()


class DuckDBManager:
    """DuckDB 数据库管理器（单例模式）"""

    def __new__(cls, db_path: Optional[str] = None):
        """
        线程安全的单例模式（双重检查锁定）

        Args:
            db_path: 数据库文件路径（仅首次创建时有效）
        """
        global _duckdb_instance

        # 第一次检查（无锁）
        if _duckdb_instance is not None:
            if db_path is not None and hasattr(_duckdb_instance, 'db_path') and _duckdb_instance.db_path != db_path:
                logger.warning(
                    f"DuckDBManager 单例已存在（路径: {_duckdb_instance.db_path}），"
                    f"忽略新路径: {db_path}"
                )
            return _duckdb_instance

        # 加锁创建
        with _duckdb_lock:
            # 第二次检查（有锁）
            if _duckdb_instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                _duckdb_instance = instance

        return _duckdb_instance

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化 DuckDB 管理器

        Args:
            db_path: 数据库文件路径，如果为None则使用默认路径
        """
        # 防止重复初始化
        if self._initialized:
            return

        if db_path is None:
            # 使用默认路径：data/mexemplar.duckdb
            db_path = str(get_default_data_dir() / "mexemplar.duckdb")

        self.db_path = db_path
        self.conn: Optional[Any] = None
        self._op_lock = threading.RLock()  # 保护跨线程的数据库操作
        self._transaction_state = threading.local()
        self._initialized = True
        self._needs_queue_recovery = False  # 是否需要从 queues 恢复

    def _transaction_depth(self) -> int:
        return getattr(self._transaction_state, "depth", 0)

    @contextmanager
    def transaction(self):
        """Execute a group of DB operations in one DuckDB transaction."""
        conn = self.connect()
        with self._op_lock:
            depth = self._transaction_depth()
            outermost = depth == 0
            self._transaction_state.depth = depth + 1

            if outermost:
                conn.execute("BEGIN TRANSACTION")

            try:
                yield conn
            except Exception:
                self._transaction_state.depth = depth
                if outermost:
                    conn.execute("ROLLBACK")
                raise
            else:
                self._transaction_state.depth = depth
                if outermost:
                    conn.execute("COMMIT")

    def connect(self, allow_wal_recovery: bool = True) -> Any:
        """
        建立数据库连接（线程安全）

        Args:
            allow_wal_recovery: 是否允许从 WAL 恢复（默认 True）

        Returns:
            数据库连接对象

        Raises:
            IOError: 如果数据库文件被占用或无法访问
        """
        if self.conn is not None:
            return self.conn

        with self._op_lock:
            # 双重检查：其他线程可能已在等锁期间创建了连接
            if self.conn is not None:
                return self.conn

            try:
                self.conn = duckdb.connect(self.db_path)
                logger.info(f"DuckDB 连接已建立: {self.db_path}")
                return self.conn
            except Exception as e:
                error_msg = str(e)

                # ⭐ 检测是否为文件被占用错误
                if (
                    "another program" in error_msg.lower()
                    or "process cannot access" in error_msg.lower()
                ):
                    logger.error(f"DuckDB 连接失败: {e}")
                    logger.error("⚠️  数据库文件被其他程序占用（如 PyCharm、DBeaver 等）")
                    raise IOError(
                        f"数据库文件被占用: {self.db_path}\n\n"
                        f"请执行以下操作：\n"
                        f"1. 关闭 PyCharm 或其他可能打开数据库的程序\n"
                        f"2. 检查是否有其他 Mexemplar 实例在运行\n"
                        f"3. 在 PyCharm 中禁用 'Enable DuckDB support' 插件"
                    ) from e

                # 检测是否为 WAL 文件错误
                if allow_wal_recovery and (
                    "WAL" in error_msg or "Failure while replaying" in error_msg
                ):
                    logger.warning(f"⚠️  DuckDB WAL 文件损坏: {error_msg}")
                    logger.warning("📋 将从 queues 队列文件恢复数据...")

                    # 关闭可能存在的连接
                    if self.conn:
                        try:
                            self.conn.close()
                        except Exception as close_err:
                            logger.debug(f"关闭数据库连接时出错（已忽略）: {close_err}")
                        self.conn = None

                    # 删除损坏的 WAL 文件
                    wal_path = Path(self.db_path).with_suffix(".duckdb.wal")
                    if wal_path.exists():
                        try:
                            wal_path.unlink()
                            logger.info(f"🗑️  已删除损坏的 WAL 文件: {wal_path}")
                        except Exception as e2:
                            logger.error(f"删除 WAL 文件失败: {e2}")

                    # 重新连接（不使用 WAL，因为已删除）
                    logger.info("🔄 重新连接数据库（WAL 已清理）...")
                    try:
                        self.conn = duckdb.connect(self.db_path)
                        logger.info(f"DuckDB 连接已建立: {self.db_path}")
                    except Exception as e3:
                        logger.error(f"重新连接失败: {e3}")
                        raise

                    # 标记需要从 queues 恢复
                    self._needs_queue_recovery = True
                    return self.conn
                else:
                    # 非 WAL 错误，直接抛出
                    logger.error(f"DuckDB 连接失败: {e}")
                    raise

    def close(self):
        """关闭数据库连接（线程安全）"""
        with self._op_lock:
            if self.conn is not None:
                self.conn.close()
                self.conn = None
                logger.info("DuckDB 连接已关闭")

    def initialize(self):
        """初始化数据库表结构"""
        conn = self.connect()

        try:
            # 创建录制会话表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recording_sessions (
                    recording_id TEXT PRIMARY KEY,
                    status TEXT,
                    recording_mode TEXT,
                    browser_type TEXT,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    metadata JSON,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # ⭐ 迁移：添加新列（如果不存在）
            self._migrate_network_requests_table()
            self._migrate_other_tables()

            # 创建操作序列表
            conn.execute(
                """
                CREATE SEQUENCE IF NOT EXISTS action_id_seq START 1
            """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS actions (
                    action_id INTEGER PRIMARY KEY DEFAULT nextval('action_id_seq'),
                    recording_id TEXT,
                    sequence_number INTEGER,
                    action_type TEXT,
                    recording_mode TEXT,
                    app_name TEXT,
                    process_name TEXT,
                    window_title TEXT,
                    parameters JSON,
                    url TEXT,
                    dom_element JSON,
                    dom_tree_snapshot JSON,
                    visual_features JSON,
                    timestamp TIMESTAMP
                )
            """
            )

            # 创建网络请求表
            conn.execute(
                """
                CREATE SEQUENCE IF NOT EXISTS request_id_seq START 1
            """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS network_requests (
                    request_id INTEGER PRIMARY KEY DEFAULT nextval('request_id_seq'),
                    action_id INTEGER,
                    recording_id TEXT,
                    url TEXT,
                    method TEXT,
                    request_type TEXT,
                    request_headers JSON,
                    request_body TEXT,
                    response_status INTEGER,
                    response_headers JSON,
                    response_body TEXT,
                    duration FLOAT,
                    timestamp TIMESTAMP,
                    filtered BOOLEAN DEFAULT FALSE,
                    filter_reason JSON,
                    filtered_at TIMESTAMP,
                    is_recommendation BOOLEAN DEFAULT FALSE,
                    importance_level VARCHAR DEFAULT 'unknown'
                )
            """
            )

            # 创建兄弟元素快照表
            conn.execute(
                """
                CREATE SEQUENCE IF NOT EXISTS snapshot_id_seq START 1
            """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sibling_snapshots (
                    snapshot_id INTEGER PRIMARY KEY DEFAULT nextval('snapshot_id_seq'),
                    action_id INTEGER,
                    recording_id TEXT,
                    container_selector TEXT,
                    item_selector TEXT,
                    list_type TEXT,
                    siblings JSON,
                    structure_similarity FLOAT,
                    is_homogeneous BOOLEAN,
                    clicked_index INTEGER,
                    total_count INTEGER,
                    timestamp TIMESTAMP
                )
            """
            )

            # ⭐ 创建过滤决策表（用于反馈循环）
            conn.execute(
                """
                CREATE SEQUENCE IF NOT EXISTS filter_decision_id_seq START 1
            """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS filter_decisions (
                    decision_id INTEGER PRIMARY KEY DEFAULT nextval('filter_decision_id_seq'),
                    request_id TEXT,
                    action_id INTEGER,
                    recording_id TEXT,
                    decision TEXT,  -- 'keep' or 'filter'
                    source TEXT,  -- 'rule' or 'llm'
                    confidence FLOAT,
                    reason TEXT,
                    pattern_matched TEXT,  -- V2提示词的模式匹配
                    scores JSON,  -- V2提示词的各维度评分
                    request_timestamp TIMESTAMP,
                    action_timestamp TIMESTAMP,
                    timestamp TIMESTAMP
                )
            """
            )

            # 创建截图时序表
            conn.execute(
                """
                CREATE SEQUENCE IF NOT EXISTS recording_screenshot_id_seq START 1
            """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recording_screenshots (
                    screenshot_id INTEGER PRIMARY KEY DEFAULT nextval('recording_screenshot_id_seq'),
                    recording_id VARCHAR NOT NULL,
                    moment VARCHAR NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    capture_id VARCHAR,
                    source_trigger VARCHAR,
                    input_started_at TIMESTAMP,
                    input_completed_at TIMESTAMP,
                    media_type VARCHAR,
                    data BLOB
                )
            """
            )

            # 创建索引
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_screenshots_recording_moment_time "
                "ON recording_screenshots(recording_id, moment, timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_actions_recording_time ON actions(recording_id, timestamp)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_type ON actions(action_type)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_network_requests_action ON network_requests(action_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_network_requests_url ON network_requests(url)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sibling_snapshots_action ON sibling_snapshots(action_id)"
            )

            logger.info("DuckDB 表结构初始化完成")
        except Exception as e:
            logger.error(f"DuckDB 初始化失败: {e}")
            raise

    def execute(self, sql: str, parameters: Optional[tuple] = None) -> Any:
        """
        执行 SQL 语句（线程安全）

        Args:
            sql: SQL 语句
            parameters: 参数元组

        Returns:
            查询结果
        """
        conn = self.connect()
        with self._op_lock:
            if parameters:
                return conn.execute(sql, parameters)
            return conn.execute(sql)

    def fetchall(self, sql: str, parameters: Optional[tuple] = None) -> List[tuple]:
        """
        执行 SQL 并返回所有结果（线程安全，fetch 在锁内完成）

        Args:
            sql: SQL 语句
            parameters: 参数元组

        Returns:
            查询结果列表
        """
        conn = self.connect()
        with self._op_lock:
            cursor = conn.execute(sql, parameters) if parameters else conn.execute(sql)
            return cursor.fetchall()

    def fetchone(self, sql: str, parameters: Optional[tuple] = None) -> Optional[tuple]:
        """
        执行 SQL 并返回单条结果（线程安全，fetch 在锁内完成）

        Args:
            sql: SQL 语句
            parameters: 参数元组

        Returns:
            查询结果或 None
        """
        conn = self.connect()
        with self._op_lock:
            cursor = conn.execute(sql, parameters) if parameters else conn.execute(sql)
            return cursor.fetchone()

    def execute_and_fetchall(
        self, sql: str, parameters: Optional[tuple] = None
    ) -> tuple[list[str], list[tuple]]:
        """
        在锁内执行 SQL、读取列名和所有行，返回 (columns, rows)。

        避免 execute() 返回 cursor 后锁已释放的线程安全缺口。
        """
        conn = self.connect()
        with self._op_lock:
            cursor = conn.execute(sql, parameters) if parameters else conn.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
        return columns, rows

    def insert(self, table: str, data: Dict[str, Any], auto_commit: bool = False) -> int:
        """
        插入单条数据

        Args:
            table: 表名
            data: 数据字典
            auto_commit: 是否立即提交到磁盘（防止意外断电数据丢失）

        Returns:
            插入的行 ID

        Raises:
            ValueError: 表名不在白名单中
        """
        if table not in _VALID_TABLES:
            raise ValueError(f"非法表名 '{table}'，合法表名: {sorted(_VALID_TABLES)}")
        _validate_columns(table, data)
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?" for _ in data])
        # 使用 RETURNING 子句获取插入的 ID
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) RETURNING *"

        conn = self.connect()
        with self._op_lock:
            result = conn.execute(sql, list(data.values())).fetchone()

            # ⭐ 自动提交模式：强制写入磁盘，防止断电数据丢失
            if auto_commit and self._transaction_depth() == 0:
                conn.execute("CHECKPOINT")
                logger.debug(f"数据已提交到磁盘: {table}")

        # 返回第一列（通常是主键 ID）
        return result[0] if result else 0

    def insert_many(
        self, table: str, data_list: List[Dict[str, Any]], auto_commit: bool = False
    ) -> List[int]:
        """
        批量插入数据

        Args:
            table: 表名
            data_list: 数据字典列表
            auto_commit: 是否立即提交到磁盘（防止意外断电数据丢失）

        Returns:
            插入的行 ID 列表

        Raises:
            ValueError: 表名不在白名单中
        """
        if table not in _VALID_TABLES:
            raise ValueError(f"非法表名 '{table}'，合法表名: {sorted(_VALID_TABLES)}")
        if not data_list:
            return []

        _validate_columns(table, dict.fromkeys(
            set().union(*(d.keys() for d in data_list))
        ))

        columns = ", ".join(data_list[0].keys())
        placeholders = ", ".join(["?" for _ in data_list[0]])
        # 使用 RETURNING 子句获取插入的 ID
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) RETURNING *"

        conn = self.connect()
        row_ids = []

        with self._op_lock:
            in_outer_transaction = self._transaction_depth() > 0
            if not in_outer_transaction:
                conn.execute("BEGIN TRANSACTION")
            try:
                for data in data_list:
                    result = conn.execute(sql, list(data.values())).fetchone()
                    if result:
                        row_ids.append(result[0])
            except Exception:
                if not in_outer_transaction:
                    conn.execute("ROLLBACK")
                raise
            else:
                if not in_outer_transaction:
                    conn.execute("COMMIT")

            # ⭐ 自动提交模式：强制写入磁盘，防止断电数据丢失
            if auto_commit and not in_outer_transaction:
                conn.execute("CHECKPOINT")
                logger.debug(f"批量数据已提交到磁盘: {table}, {len(row_ids)} 条")

        return row_ids

    def needs_queue_recovery(self) -> bool:
        """
        检查是否需要从 queues 队列文件恢复数据

        Returns:
            是否需要恢复（WAL 文件损坏时返回 True）
        """
        return getattr(self, "_needs_queue_recovery", False)

    def clear_queue_recovery_flag(self):
        """清除队列恢复标志"""
        self._needs_queue_recovery = False

    def _migrate_add_recording_id(
        self, table_name: str, reference_column: str = "action_id"
    ) -> bool:
        """
        通用迁移：为表添加 recording_id 列，并从关联表回填数据

        Args:
            table_name: 要迁移的表名
            reference_column: 关联列名（默认为 action_id）

        Returns:
            是否成功添加并回填了数据
        """
        conn = self.connect()

        try:
            # 检查表是否存在
            tables = conn.execute("SHOW TABLES").fetchall()
            table_names = [row[0] for row in tables]

            if table_name not in table_names:
                logger.debug(f"{table_name} 表不存在，跳过迁移")
                return False

            # 获取现有列
            columns_info = conn.execute(f"DESCRIBE {table_name}").fetchall()
            existing_columns = {row[0] for row in columns_info}

            # 添加 recording_id 列
            if "recording_id" not in existing_columns:
                conn.execute(
                    f"""
                    ALTER TABLE {table_name}
                    ADD COLUMN recording_id VARCHAR
                """
                )
                logger.info(f"✅ DuckDB迁移: 已为 {table_name} 添加 recording_id 列")

            # 回填历史数据（从 actions 表获取）
            if reference_column == "action_id":
                conn.execute(
                    f"""
                    UPDATE {table_name} t
                    SET recording_id = a.recording_id
                    FROM actions a
                    WHERE t.{reference_column} = a.action_id
                    AND t.recording_id IS NULL
                """
                )
                updated_count = conn.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE recording_id IS NOT NULL"
                ).fetchone()[0]
                logger.info(
                    f"✅ DuckDB迁移: 已通过 action_id 回填 {table_name} 的 {updated_count} 条记录"
                )

                # 特殊处理 network_requests 表：回填孤立请求（通过时间戳匹配）
                if table_name == "network_requests":
                    self._backfill_orphaned_network_requests()

            # 创建索引以提高查询性能
            try:
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table_name}_recording ON {table_name}(recording_id)"
                )
                logger.info(f"✅ DuckDB迁移: 已为 {table_name}.recording_id 创建索引")
            except Exception as idx_err:
                logger.warning(f"创建索引失败（已忽略）: {idx_err}")

            return True

        except Exception as e:
            logger.error(f"DuckDB 迁移失败 ({table_name}): {e}")
            return False

    def _backfill_orphaned_network_requests(self):
        """
        回填孤立的网络请求（action_id 为 NULL 的请求）

        策略：通过时间戳匹配到对应的录制会话
        """
        conn = self.connect()

        try:
            # 检查是否有孤立请求
            orphaned_count = conn.execute(
                "SELECT COUNT(*) FROM network_requests WHERE recording_id IS NULL"
            ).fetchone()[0]

            if orphaned_count == 0:
                logger.debug("没有孤立的网络请求需要回填")
                return

            logger.info(f"🔍 发现 {orphaned_count} 条孤立的网络请求，尝试通过时间戳回填...")

            # 通过时间戳匹配到录制会话
            conn.execute(
                """
                UPDATE network_requests nr
                SET recording_id = rs.recording_id
                FROM recording_sessions rs
                WHERE nr.recording_id IS NULL
                AND nr.timestamp BETWEEN rs.start_time AND COALESCE(rs.end_time, '9999-12-31')
            """
            )

            backfilled_count = conn.execute(
                "SELECT COUNT(*) FROM network_requests WHERE recording_id IS NOT NULL"
            ).fetchone()[0]

            remaining_orphaned = conn.execute(
                "SELECT COUNT(*) FROM network_requests WHERE recording_id IS NULL"
            ).fetchone()[0]

            logger.info(
                f"✅ DuckDB迁移: 已通过时间戳回填 {backfilled_count} 条网络请求的 recording_id"
            )
            if remaining_orphaned > 0:
                logger.warning(
                    f"⚠️ 仍有 {remaining_orphaned} 条网络请求的 recording_id 为 NULL（无法匹配到录制会话）"
                )

        except Exception as e:
            logger.error(f"回填孤立网络请求失败: {e}")
            # 不抛出异常，允许系统继续运行

    def _migrate_network_requests_table(self):
        """
        迁移 network_requests 表，添加新列

        添加列：
        - recording_id: 录制会话 ID（用于关联和查询）
        - filtered: 是否被智能过滤
        - filter_reason: 过滤原因（JSON格式）
        - filtered_at: 过滤时间
        - is_recommendation: 是否为推荐内容
        - importance_level: 重要性等级
        """
        conn = self.connect()

        try:
            # 检查表是否存在
            tables = conn.execute("SHOW TABLES").fetchall()
            table_names = [row[0] for row in tables]

            if "network_requests" not in table_names:
                logger.debug("network_requests 表不存在，跳过迁移")
                return

            # 获取现有列
            columns_info = conn.execute("DESCRIBE network_requests").fetchall()
            existing_columns = {row[0] for row in columns_info}

            # 添加 recording_id 列
            self._migrate_add_recording_id("network_requests", reference_column="action_id")

            # 添加 filtered 列
            if "filtered" not in existing_columns:
                conn.execute(
                    """
                    ALTER TABLE network_requests
                    ADD COLUMN filtered BOOLEAN DEFAULT FALSE
                """
                )
                logger.info("✅ DuckDB迁移: 已添加 filtered 列")

            # 添加 filter_reason 列
            if "filter_reason" not in existing_columns:
                conn.execute(
                    """
                    ALTER TABLE network_requests
                    ADD COLUMN filter_reason JSON
                """
                )
                logger.info("✅ DuckDB迁移: 已添加 filter_reason 列")

            # 添加 filtered_at 列
            if "filtered_at" not in existing_columns:
                conn.execute(
                    """
                    ALTER TABLE network_requests
                    ADD COLUMN filtered_at TIMESTAMP
                """
                )
                logger.info("✅ DuckDB迁移: 已添加 filtered_at 列")

            # 添加 is_recommendation 列
            if "is_recommendation" not in existing_columns:
                conn.execute(
                    """
                    ALTER TABLE network_requests
                    ADD COLUMN is_recommendation BOOLEAN DEFAULT FALSE
                """
                )
                logger.info("✅ DuckDB迁移: 已添加 is_recommendation 列")

            # 添加 importance_level 列
            if "importance_level" not in existing_columns:
                conn.execute(
                    """
                    ALTER TABLE network_requests
                    ADD COLUMN importance_level VARCHAR DEFAULT 'unknown'
                """
                )
                logger.info("✅ DuckDB迁移: 已添加 importance_level 列")

            # 创建复合索引（提高查询性能）
            try:
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_network_recording_filtered
                    ON network_requests(recording_id, filtered)
                """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_network_recording_time
                    ON network_requests(recording_id, timestamp)
                """
                )
                logger.info("✅ DuckDB迁移: 已为 network_requests 创建复合索引")
            except Exception as idx_err:
                logger.warning(f"创建复合索引失败（已忽略）: {idx_err}")

        except Exception as e:
            logger.error(f"DuckDB 迁移失败: {e}")
            # 不抛出异常，允许系统继续运行

    def _migrate_other_tables(self):
        """
        迁移其他表，添加 recording_id 列

        迁移的表：
        - sibling_snapshots
        - filter_decisions
        """
        # 迁移 sibling_snapshots
        self._migrate_add_recording_id("sibling_snapshots", reference_column="action_id")

        # 迁移 filter_decisions（特殊处理：需要通过 network_requests -> actions 获取）
        self._migrate_filter_decisions_table()

    def _migrate_filter_decisions_table(self):
        """
        迁移 filter_decisions 表，添加新列

        添加列：
        - recording_id: 录制会话 ID
        - action_id: 操作 ID（方便直接关联到 actions）
        - request_timestamp: 请求时间戳（冗余，方便查询）
        - action_timestamp: 操作时间戳（冗余，方便查询）
        """
        conn = self.connect()

        try:
            # 检查表是否存在
            tables = conn.execute("SHOW TABLES").fetchall()
            table_names = [row[0] for row in tables]

            if "filter_decisions" not in table_names:
                logger.debug("filter_decisions 表不存在，跳过迁移")
                return

            # 获取现有列
            columns_info = conn.execute("DESCRIBE filter_decisions").fetchall()
            existing_columns = {row[0] for row in columns_info}

            # 添加 action_id 列
            if "action_id" not in existing_columns:
                conn.execute(
                    """
                    ALTER TABLE filter_decisions
                    ADD COLUMN action_id INTEGER
                """
                )
                logger.info("✅ DuckDB迁移: 已为 filter_decisions 添加 action_id 列")

                # 回填 action_id（从 network_requests 获取）
                conn.execute(
                    """
                    UPDATE filter_decisions fd
                    SET action_id = nr.action_id
                    FROM network_requests nr
                    WHERE fd.request_id = CAST(nr.request_id AS VARCHAR)
                    AND fd.action_id IS NULL
                """
                )
                updated_count = conn.execute(
                    "SELECT COUNT(*) FROM filter_decisions WHERE action_id IS NOT NULL"
                ).fetchone()[0]
                logger.info(
                    f"✅ DuckDB迁移: 已回填 filter_decisions 的 {updated_count} 条记录的 action_id"
                )

            # 添加 recording_id 列
            self._migrate_add_recording_id("filter_decisions", reference_column="action_id")

            # 添加 request_timestamp 列
            if "request_timestamp" not in existing_columns:
                conn.execute(
                    """
                    ALTER TABLE filter_decisions
                    ADD COLUMN request_timestamp TIMESTAMP
                """
                )
                logger.info("✅ DuckDB迁移: 已为 filter_decisions 添加 request_timestamp 列")

                # 回填 request_timestamp
                conn.execute(
                    """
                    UPDATE filter_decisions fd
                    SET request_timestamp = nr.timestamp
                    FROM network_requests nr
                    WHERE fd.request_id = CAST(nr.request_id AS VARCHAR)
                    AND fd.request_timestamp IS NULL
                """
                )
                logger.info("✅ DuckDB迁移: 已回填 request_timestamp")

            # 添加 action_timestamp 列
            if "action_timestamp" not in existing_columns:
                conn.execute(
                    """
                    ALTER TABLE filter_decisions
                    ADD COLUMN action_timestamp TIMESTAMP
                """
                )
                logger.info("✅ DuckDB迁移: 已为 filter_decisions 添加 action_timestamp 列")

                # 回填 action_timestamp
                conn.execute(
                    """
                    UPDATE filter_decisions fd
                    SET action_timestamp = a.timestamp
                    FROM actions a
                    WHERE fd.action_id = a.action_id
                    AND fd.action_timestamp IS NULL
                """
                )
                logger.info("✅ DuckDB迁移: 已回填 action_timestamp")

        except Exception as e:
            logger.error(f"DuckDB 迁移失败 (filter_decisions): {e}")
            # 不抛出异常，允许系统继续运行
