"""
pytest 配置文件

用于处理测试环境和特殊情况
"""

import sys
import os
import pytest
from unittest.mock import MagicMock

# 检查是否在 CI 环境（无图形界面）
# 通过检查 DISPLAY 环境变量或尝试导入 pynput 来判断
def is_headless_environment():
    """检查是否在无图形界面环境"""
    # 检查 DISPLAY 环境变量（Linux）
    if os.environ.get('DISPLAY') is None and sys.platform == 'linux':
        return True
    # 检查是否在 CI 环境
    if os.environ.get('CI') == 'true':
        return True
    return False

# 如果在无图形界面环境，mock 掉需要图形界面的模块
if is_headless_environment():
    # Mock pynput
    sys.modules['pynput'] = MagicMock()
    sys.modules['pynput.mouse'] = MagicMock()
    sys.modules['pynput.keyboard'] = MagicMock()

    # Mock pywinauto
    sys.modules['pywinauto'] = MagicMock()
    sys.modules['pywinauto.application'] = MagicMock()
    sys.modules['pywinauto.keyboard'] = MagicMock()
    sys.modules['pywinauto.mouse'] = MagicMock()

    # Mock PyQt6
    sys.modules['PyQt6'] = MagicMock()
    sys.modules['PyQt6.QtCore'] = MagicMock()
    sys.modules['PyQt6.QtGui'] = MagicMock()
    sys.modules['PyQt6.QtWidgets'] = MagicMock()


@pytest.fixture(autouse=True, scope="function")
def cleanup_database_connections():
    """
    自动 fixture：每个测试函数执行后，清理所有数据库连接

    这个 fixture 解决以下问题：
    1. 测试使用了真实数据库文件（data/mexemplar.duckdb）
    2. 测试没有正确关闭连接
    3. pytest 进程持有文件句柄，导致文件被锁定

    使用方式：自动应用到所有测试函数（autouse=True）
    """
    # 测试执行前的准备
    yield

    # 测试执行后的清理
    try:
        # 关闭 DuckDB 连接（单例）
        try:
            from src.data.duckdb_manager import DuckDBManager
            if hasattr(DuckDBManager, '_duckdb_instance') and DuckDBManager._duckdb_instance:
                DuckDBManager._duckdb_instance.close()
                # 重置单例，避免后续测试复用已关闭的连接
                DuckDBManager._duckdb_instance = None
        except Exception as e:
            print(f"清理 DuckDB 连接失败: {e}")

        # 关闭 SQLAlchemy 连接
        try:
            from src.data.sqlalchemy_manager import SQLAlchemyManager
            if hasattr(SQLAlchemyManager, '_instance') and SQLAlchemyManager._instance:
                SQLAlchemyManager._instance.close()
                SQLAlchemyManager._instance = None
        except Exception as e:
            print(f"清理 SQLAlchemy 连接失败: {e}")

        # 关闭 RecordingRepository 中的 DuckDB 连接
        try:
            from src.data.recording_repository import RecordingRepository
            # RecordingRepository 使用单例 DuckDB，已在上面处理
            RecordingRepository._auto_recover_done = False
        except Exception as e:
            print(f"清理 RecordingRepository 失败: {e}")

    except Exception as e:
        print(f"数据库连接清理出错: {e}")
