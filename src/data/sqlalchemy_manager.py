"""
SQLAlchemy 数据库管理器 - SQLite

唯一的 SQLite 数据库管理器，负责：
- 建表（Base.metadata.create_all）
- 运行迁移（migrations.run_migrations）
- 提供会话工厂（get_session）
- 全局配置读写（get_setting / set_setting）
"""

import json
import logging
import threading
from typing import Any, Optional
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from src.data.models_sqlite import AppSettings, Base
from src.utils.helpers import get_default_data_dir

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
            db_path = str(get_default_data_dir() / "mexemplar.db")

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
            # :memory: 数据库必须用 StaticPool（否则每次新连接创建空数据库）
            # 文件数据库用 NullPool 避免多线程共享同一连接导致 InterfaceError
            is_memory = self.db_path == ":memory:"
            self.engine = create_engine(
                f"sqlite:///{self.db_path}",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool if is_memory else NullPool,
                echo=False,  # 设置为 True 可以查看 SQL 语句
            )

            # 注册连接事件：每个新连接加载 sqlite-vec 扩展（可选）
            @event.listens_for(self.engine, "connect")
            def _load_sqlite_vec(dbapi_conn, _connection_record):
                try:
                    import sqlite_vec

                    dbapi_conn.enable_load_extension(True)
                    dbapi_conn.load_extension(sqlite_vec.loadable_path())
                    dbapi_conn.enable_load_extension(False)
                except (ImportError, Exception):
                    pass  # sqlite-vec 未安装，向量搜索将降级为 FTS

            # 创建会话工厂
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

            # 创建所有 ORM 表（新安装直接获得最新 schema）
            Base.metadata.create_all(self.engine)

            # 确保 schema_version 有初始行（新安装时表为空）
            with self.engine.connect() as conn:
                conn.execute(
                    text(
                        "INSERT INTO schema_version (version) "
                        "SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM schema_version)"
                    )
                )
                conn.commit()

            # 运行增量迁移（为旧版安装补充缺失列/表）
            from src.data.migrations import run_migrations

            run_migrations(self.engine)

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

    # ===== 全局配置读写（替代 DatabaseManager.get_setting/set_setting）=====

    def get_setting(self, key: str, default: Any = None) -> Any:
        """读取 app_settings 中的配置值，自动按 setting_type 转换类型"""
        if not self._initialized:
            self.initialize()
        with self.SessionLocal() as session:
            setting = session.get(AppSettings, key)
            if setting is None:
                return default
            value, value_type = setting.setting_value, setting.setting_type
            if value is None:
                return default
            if value_type == "json":
                return json.loads(value)
            elif value_type == "int":
                return int(value)
            elif value_type == "float":
                return float(value)
            elif value_type == "bool":
                return value.lower() == "true"
            return value

    def set_setting(
        self, key: str, value: Any, value_type: str = "string", description: str = None
    ) -> None:
        """写入 app_settings，UPSERT 语义"""
        if not self._initialized:
            self.initialize()
        if value_type == "json":
            value_str = json.dumps(value, ensure_ascii=False)
        elif value_type == "bool":
            value_str = "true" if value else "false"
        else:
            value_str = str(value)

        with self.SessionLocal() as session:
            setting = session.get(AppSettings, key)
            if setting is None:
                setting = AppSettings(
                    setting_key=key,
                    setting_value=value_str,
                    setting_type=value_type,
                    description=description,
                )
                session.add(setting)
            else:
                setting.setting_value = value_str
                setting.setting_type = value_type
                if description is not None:
                    setting.description = description
            session.commit()


# 全局单例
_sqlalchemy_instance: Optional[SQLAlchemyManager] = None
_sa_lock = threading.Lock()


def get_sqlalchemy_manager(db_path: Optional[str] = None) -> SQLAlchemyManager:
    """
    获取 SQLAlchemy 管理器单例（双重检查锁定，线程安全）

    db_path 仅在首次调用时生效；后续调用忽略该参数。
    """
    global _sqlalchemy_instance

    if _sqlalchemy_instance is not None:
        return _sqlalchemy_instance

    with _sa_lock:
        if _sqlalchemy_instance is None:
            _sqlalchemy_instance = SQLAlchemyManager(db_path)

    return _sqlalchemy_instance
