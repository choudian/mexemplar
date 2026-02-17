"""
SQLite Checkpointer

使用 SQLite 持久化 Agent 状态。

与现有数据库系统集成：
- 业务数据：data/mexemplar.db
- 录制数据：data/recordings/exemplar.duckdb
- Agent 状态：data/agent_checkpoints.db（本模块）

推荐用法：使用 get_checkpointer_context() 配合 with 语句
"""

import sqlite3
from typing import Optional, Iterator
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def get_checkpointer_db_path() -> Path:
    """
    获取 Checkpointer 数据库路径

    Returns:
        数据库文件路径（data/agent_checkpoints.db）
    """
    project_root = Path(__file__).parent.parent.parent.parent.parent
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "agent_checkpoints.db"


@contextmanager
def get_checkpointer_context(db_path: Optional[str] = None) -> Iterator[SqliteSaver]:
    """
    获取 Checkpointer 上下文管理器（推荐方式）

    使用官方的 SqliteSaver.from_conn_string() 方法，
    内部自动配置 check_same_thread=False，线程安全。

    Args:
        db_path: 数据库路径（可选，默认使用 data/agent_checkpoints.db）

    Yields:
        SqliteSaver 实例

    Usage:
        with get_checkpointer_context() as checkpointer:
            app = graph.compile(checkpointer=checkpointer)
            result = app.invoke(input, config)
    """
    if db_path is None:
        db_path = str(get_checkpointer_db_path())

    # 使用官方方法，内部已配置 check_same_thread=False
    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        yield checkpointer


def get_checkpointer(db_path: Optional[str] = None) -> SqliteSaver:
    """
    获取 Checkpointer 实例（直接返回，用于特殊场景）

    注意：推荐使用 get_checkpointer_context() 配合 with 语句。
    此方法保持向后兼容，用于无法使用上下文管理器的场景。

    Args:
        db_path: 数据库路径（可选）

    Returns:
        SqliteSaver 实例
    """
    if db_path is None:
        db_path = str(get_checkpointer_db_path())

    conn = sqlite3.connect(db_path, check_same_thread=False)
    return SqliteSaver(conn)


def create_sqlite_checkpointer(db_path: Optional[str] = None) -> SqliteSaver:
    """
    创建 SQLite Checkpointer（直接返回实例）

    注意：推荐使用 get_checkpointer_context() 配合 with 语句。

    Args:
        db_path: 数据库路径（可选）

    Returns:
        SqliteSaver 实例
    """
    return get_checkpointer(db_path)


@asynccontextmanager
async def get_async_checkpointer(db_path: Optional[str] = None):
    """
    获取异步 Checkpointer（上下文管理器）

    用于需要异步操作的场景。

    Args:
        db_path: 数据库路径（可选）

    Yields:
        AsyncSqliteSaver 实例

    Usage:
        async with get_async_checkpointer() as checkpointer:
            app = graph.compile(checkpointer=checkpointer)
            result = await app.ainvoke(input, config)
    """
    if db_path is None:
        db_path = str(get_checkpointer_db_path())

    # 使用 aiosqlite 创建异步连接
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        yield checkpointer


def check_checkpointer_tables(db_path: Optional[str] = None) -> bool:
    """
    检查 Checkpointer 表是否正常

    Args:
        db_path: 数据库路径

    Returns:
        表是否存在
    """
    if db_path is None:
        db_path = str(get_checkpointer_db_path())

    if not Path(db_path).exists():
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 检查 checkpoints 表是否存在
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='checkpoints'
    """)
    exists = cursor.fetchone() is not None

    conn.close()
    return exists


# 内存 Checkpointer（用于测试）
def get_memory_checkpointer():
    """
    获取内存 Checkpointer（用于测试）

    Returns:
        MemorySaver 实例

    Usage:
        checkpointer = get_memory_checkpointer()
        app = graph.compile(checkpointer=checkpointer)
    """
    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()
