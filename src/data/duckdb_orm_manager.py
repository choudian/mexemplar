"""
SQLAlchemy 数据库管理器 - DuckDB

使用 ORM 操作录制数据

架构说明（CS 应用架构）：
- 应用启动时自动初始化数据库
- 使用 Base.metadata.create_all() 自动创建表（用户无感知）
- 支持未来扩展为自动迁移模式

注意：
- DuckDB 不支持 SERIAL 类型，需要使用 Sequence 实现自增主键
- 参考：https://github.com/Mause/duckdb_engine#auto-incrementing-id-columns
- 所有 ORM 模型已在 models_duckdb.py 中使用 Sequence 定义
"""

import logging
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.data.models_duckdb import Base

logger = logging.getLogger(__name__)


class SQLAlchemyDuckDBManager:
    """
    SQLAlchemy DuckDB 管理器

    使用 ORM 操作 DuckDB 录制数据
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化 DuckDB 管理器

        Args:
            db_path: 数据库文件路径，如果为None则使用默认路径
        """
        if db_path is None:
            project_root = Path(__file__).parent.parent.parent
            data_dir = project_root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "mexemplar.duckdb")

        self.db_path = db_path
        self.engine = None
        self.SessionLocal = None
        self._initialized = False

        logger.debug(f"DuckDB ORM Manager initialized: {self.db_path}")

    def connect(self):
        """
        建立 DuckDB 连接

        Returns:
            Connection: DuckDB 连接对象（兼容旧代码）
        """
        if not self._initialized:
            self.initialize()

        # 返回原生连接（兼容旧代码）
        import duckdb
        return duckdb.connect(self.db_path)

    def initialize(self):
        """
        初始化数据库连接和表结构（应用启动时自动调用）

        CS 架构说明：
        - 应用启动时自动调用此方法
        - 自动创建所有表（用户无感知）
        - 未来可扩展为自动迁移模式
        """
        if self._initialized:
            return

        try:
            # 创建 DuckDB 引擎
            self.engine = create_engine(
                f"duckdb:///{self.db_path}",
                echo=False,  # 设置为 True 可以查看 SQL 语句
            )

            # 创建会话工厂
            self.SessionLocal = sessionmaker(
                autocommit=False, autoflush=False, bind=self.engine
            )

            # ⭐ 自动创建所有表（CS 架构：用户无需手动操作）
            Base.metadata.create_all(self.engine)

            self._initialized = True
            logger.info(f"DuckDB ORM 数据库已初始化: {self.db_path}")

        except Exception as e:
            logger.error(f"DuckDB ORM 初始化失败: {e}")
            raise

    def get_session(self) -> Session:
        """
        获取数据库会话

        Returns:
            Session: SQLAlchemy 会话对象
        """
        if not self._initialized:
            self.initialize()

        return self.SessionLocal()

    def insert(self, table: str, data: Dict[str, Any]) -> int:
        """
        插入单条记录（兼容旧代码）

        Args:
            table: 表名
            data: 数据字典

        Returns:
            插入记录的 ID
        """
        session = self.get_session()

        try:
            # 根据表名选择模型
            if table == "recording_sessions":
                from src.data.models_duckdb import RecordingSession
                model_class = RecordingSession
            elif table == "actions":
                from src.data.models_duckdb import Action
                model_class = Action
            elif table == "network_requests":
                from src.data.models_duckdb import NetworkRequest
                model_class = NetworkRequest
            elif table == "sibling_snapshots":
                from src.data.models_duckdb import SiblingSnapshot
                model_class = SiblingSnapshot
            elif table == "list_contexts":
                from src.data.models_duckdb import ListContext
                model_class = ListContext
            elif table == "filter_decisions":
                from src.data.models_duckdb import FilterDecision
                model_class = FilterDecision
            else:
                raise ValueError(f"Unknown table: {table}")

            # 创建对象并插入
            obj = model_class(**data)
            session.add(obj)
            session.commit()
            session.refresh(obj)

            # 返回 ID
            if hasattr(obj, "request_id"):
                return obj.request_id
            elif hasattr(obj, "action_id"):
                return obj.action_id
            elif hasattr(obj, "snapshot_id"):
                return obj.snapshot_id
            elif hasattr(obj, "context_id"):
                return obj.context_id
            elif hasattr(obj, "decision_id"):
                return obj.decision_id
            elif hasattr(obj, "recording_id"):
                return obj.recording_id
            else:
                return 0

        except Exception as e:
            session.rollback()
            logger.error(f"插入记录失败 ({table}): {e}")
            raise
        finally:
            session.close()

    def insert_many(self, table: str, data_list: List[Dict[str, Any]]) -> List[int]:
        """
        批量插入记录（兼容旧代码）

        Args:
            table: 表名
            data_list: 数据字典列表

        Returns:
            插入记录的 ID 列表
        """
        ids = []
        for data in data_list:
            ids.append(self.insert(table, data))
        return ids

    def fetchone(self, query: str, params: Optional[tuple] = None):
        """
        执行查询并返回单条结果（兼容旧代码）

        Args:
            query: SQL 查询语句
            params: 查询参数

        Returns:
            查询结果
        """
        conn = self.connect()
        try:
            if params:
                result = conn.execute(query, params).fetchone()
            else:
                result = conn.execute(query).fetchone()
            return result
        finally:
            conn.close()

    def fetchall(self, query: str, params: Optional[tuple] = None):
        """
        执行查询并返回所有结果（兼容旧代码）

        Args:
            query: SQL 查询语句
            params: 查询参数

        Returns:
            查询结果列表
        """
        conn = self.connect()
        try:
            if params:
                result = conn.execute(query, params).fetchall()
            else:
                result = conn.execute(query).fetchall()
            return result
        finally:
            conn.close()

    def execute(self, query: str, params: Optional[tuple] = None):
        """
        执行 SQL 语句（兼容旧代码）

        Args:
            query: SQL 语句
            params: 参数
        """
        conn = self.connect()
        try:
            if params:
                conn.execute(query, params)
            else:
                conn.execute(query)
        finally:
            conn.close()

    def close(self):
        """关闭数据库连接"""
        if self.engine:
            self.engine.dispose()
            self._initialized = False
            logger.debug("DuckDB ORM 连接已关闭")


# 全局单例
_duckdb_orm_instance: Optional[SQLAlchemyDuckDBManager] = None


def get_duckdb_orm_manager() -> SQLAlchemyDuckDBManager:
    """
    获取 DuckDB ORM 管理器单例

    Returns:
        SQLAlchemyDuckDBManager: 全局唯一的管理器实例
    """
    global _duckdb_orm_instance

    if _duckdb_orm_instance is None:
        _duckdb_orm_instance = SQLAlchemyDuckDBManager()

    return _duckdb_orm_instance
