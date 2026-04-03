"""
SQLAlchemy 数据库管理器 - SQLite

替代原来的 DatabaseManager，使用 ORM 操作数据库
"""

import logging
from pathlib import Path
from typing import Optional
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.data.models_sqlite import (
    Base,
)

logger = logging.getLogger(__name__)


class SQLAlchemyManager:
    """
    SQLAlchemy 数据库管理器（SQLite）

    使用 ORM 操作数据库，替代原生 SQL
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化 SQLAlchemy 管理器

        Args:
            db_path: 数据库文件路径，如果为None则使用默认路径
        """
        if db_path is None:
            project_root = Path(__file__).parent.parent.parent
            data_dir = project_root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "mexemplar.db")

        self.db_path = db_path
        self.engine = None
        self.SessionLocal = None
        self._initialized = False

        logger.debug(f"SQLAlchemy Manager initialized: {self.db_path}")

    def initialize(self):
        """
        初始化数据库连接和表结构
        """
        if self._initialized:
            return

        try:
            # 创建 SQLite 引擎
            # check_same_thread=False 允许多线程访问
            # StaticPool 避免连接被关闭
            self.engine = create_engine(
                f"sqlite:///{self.db_path}",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False,  # 设置为 True 可以查看 SQL 语句
            )

            # 注册连接事件：每个新连接加载 sqlite-vec 扩展（可选）
            @event.listens_for(self.engine, "connect")
            def _load_sqlite_vec(dbapi_conn, connection_record):
                try:
                    import sqlite_vec

                    dbapi_conn.enable_load_extension(True)
                    dbapi_conn.load_extension(sqlite_vec.loadable_path())
                    dbapi_conn.enable_load_extension(False)
                except (ImportError, Exception):
                    pass  # sqlite-vec 未安装，向量搜索将降级为 FTS

            # 创建会话工厂
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

            # 创建所有表
            Base.metadata.create_all(self.engine)

            # 迁移：为已有安装补充新列
            with self.engine.connect() as conn:
                try:
                    conn.execute(
                        text("ALTER TABLE tools ADD COLUMN dependencies JSON DEFAULT '[]'")
                    )
                    conn.commit()
                except Exception:
                    pass  # 列已存在，忽略

            self._initialized = True
            logger.info(f"SQLAlchemy 数据库已初始化: {self.db_path}")

        except Exception as e:
            logger.error(f"SQLAlchemy 初始化失败: {e}")
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

    def close(self):
        """关闭数据库连接"""
        if self.engine:
            self.engine.dispose()
            self._initialized = False
            logger.debug("SQLAlchemy 连接已关闭")


# 全局单例
_sqlalchemy_instance: Optional[SQLAlchemyManager] = None


def get_sqlalchemy_manager() -> SQLAlchemyManager:
    """
    获取 SQLAlchemy 管理器单例

    Returns:
        SQLAlchemyManager: 全局唯一的管理器实例
    """
    global _sqlalchemy_instance

    if _sqlalchemy_instance is None:
        _sqlalchemy_instance = SQLAlchemyManager()

    return _sqlalchemy_instance
