"""Alembic 环境配置 - SQLite 数据库"""

import asyncio
import os
from pathlib import Path
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# 导入模型
from src.data.models_sqlite import Base as SQLiteBase

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 目标元数据（用于自动生成迁移）
target_metadata = SQLiteBase.metadata

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 数据库路径
SQLITE_DB_PATH = PROJECT_ROOT / "data" / "mexemplar.db"


def get_database_url() -> str:
    """获取 SQLite 数据库连接 URL"""
    return f"sqlite:///{SQLITE_DB_PATH}"


def run_migrations_offline() -> None:
    """
    离线模式运行迁移（生成 SQL 脚本）
    """
    url = get_database_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite 需要
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    在线模式运行迁移（直接连接数据库）
    """
    url = get_database_url()
    engine = engine_from_config(
        {"sqlalchemy.url": url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite 需要
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
