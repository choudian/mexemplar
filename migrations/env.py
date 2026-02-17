"""Alembic 环境配置 - 支持双数据库（SQLite + DuckDB）"""

import asyncio
import os
from pathlib import Path
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# 导入模型
from src.data.models_sqlite import Base as SQLiteBase
from src.data.models_duckdb import Base as DuckDBBase

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 目标元数据（用于自动生成迁移）
target_sqlite_metadata = SQLiteBase.metadata
target_duckdb_metadata = DuckDBBase.metadata

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 数据库路径
SQLITE_DB_PATH = PROJECT_ROOT / "data" / "mexemplar.db"
DUCKDB_DB_PATH = PROJECT_ROOT / "data" / "mexemplar.duckdb"


# 从环境变量或命令行参数获取数据库类型
def get_db_type():
    """获取当前操作的数据库类型"""
    # 优先从环境变量读取
    db_type = os.environ.get("ALEMBIC_DB_TYPE")
    if db_type:
        return db_type

    # 其次从命令行参数读取
    try:
        db_arg = context.get_x_argument(as_dictionary=True)
        return db_arg.get("db", "sqlite")
    except:
        return "sqlite"


def get_database_url(db_type: str = "sqlite") -> str:
    """
    获取数据库连接 URL

    Args:
        db_type: 'sqlite' 或 'duckdb'
    """
    if db_type == "sqlite":
        # SQLite 数据库 URL
        return f"sqlite:///{SQLITE_DB_PATH}"
    elif db_type == "duckdb":
        # DuckDB 数据库 URL
        return f"duckdb:///{DUCKDB_DB_PATH}"
    else:
        raise ValueError(f"Unknown database type: {db_type}")


def run_migrations_offline() -> None:
    """
    离线模式运行迁移（生成 SQL 脚本）
    """
    db_type = get_db_type()
    url = get_database_url(db_type)

    context.configure(
        url=url,
        target_metadata=target_sqlite_metadata if db_type == "sqlite" else target_duckdb_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite 需要
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """执行迁移"""
    db_type = get_db_type()

    if db_type == "sqlite":
        context.configure(
            connection=connection,
            target_metadata=target_sqlite_metadata,
            render_as_batch=True,  # SQLite 需要
        )
    else:  # duckdb
        context.configure(
            connection=connection,
            target_metadata=target_duckdb_metadata,
            render_as_batch=False,
        )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    在线模式运行迁移（直接连接数据库）
    """
    db_type = get_db_type()

    if db_type == "duckdb":
        # DuckDB 特殊处理：直接使用 duckdb 连接
        import duckdb

        # 创建原生 DuckDB 连接
        connection = duckdb.connect(str(DUCKDB_DB_PATH))

        # 包装为 SQLAlchemy 连接
        from sqlalchemy import create_engine
        from sqlalchemy.engine import Connection

        engine = create_engine(f"duckdb:///{DUCKDB_DB_PATH}")

        with engine.connect() as conn:
            # 直接执行迁移，不使用 Alembic 的方言
            do_run_migrations(conn)
    else:
        # SQLite 使用标准方式
        url = get_database_url(db_type)
        engine = engine_from_config(
            {"sqlalchemy.url": url},
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        with engine.connect() as connection:
            do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
