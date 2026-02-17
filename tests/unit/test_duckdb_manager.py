"""
DuckDB 管理器单元测试
"""

import pytest
import os
import tempfile
import shutil
from pathlib import Path

from src.data.duckdb_manager import DuckDBManager, init_duckdb


class TestDuckDBManager:
    """DuckDB 管理器测试"""

    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        # 清理
        try:
            shutil.rmtree(temp_dir)
        except:
            pass

    @pytest.fixture
    def temp_db_path(self, temp_dir):
        """创建临时数据库文件路径"""
        db_path = os.path.join(temp_dir, "test.duckdb")
        yield db_path

    @pytest.fixture
    def db_manager(self, temp_db_path):
        """创建数据库管理器实例"""
        manager = DuckDBManager(temp_db_path)
        manager.initialize()
        yield manager
        manager.close()

    def test_database_creation(self, temp_db_path):
        """测试数据库创建"""
        manager = DuckDBManager(temp_db_path)
        manager.initialize()

        # 检查数据库文件是否存在
        assert Path(temp_db_path).exists()

        manager.close()

    def test_table_initialization(self, db_manager):
        """测试表结构初始化"""
        tables = db_manager.get_tables()

        # 检查所有表是否创建成功
        expected_tables = {
            "recording_sessions",
            "actions",
            "network_requests",
            "sibling_snapshots",
            "list_contexts",
        }

        assert expected_tables.issubset(set(tables))

    def test_insert_and_query(self, db_manager):
        """测试插入和查询"""
        # 插入测试数据
        recording_id = "test-recording-001"
        db_manager.insert(
            "recording_sessions",
            {
                "recording_id": recording_id,
                "status": "stopped",
                "recording_mode": "browser",
                "browser_type": "chromium",
                "start_time": None,
                "end_time": None,
                "metadata": '{"test": true}',
            },
        )

        # 查询数据
        result = db_manager.fetchone(
            "SELECT * FROM recording_sessions WHERE recording_id = ?", (recording_id,)
        )

        assert result is not None
        assert result[0] == recording_id
        assert result[1] == "stopped"

    def test_batch_insert(self, db_manager):
        """测试批量插入"""
        recording_id = "test-recording-batch"

        # 批量插入操作
        actions = []
        for i in range(10):
            actions.append(
                {
                    "recording_id": recording_id,
                    "sequence_number": i + 1,
                    "action_type": "click",
                    "recording_mode": "browser",
                    "app_name": None,
                    "process_name": None,
                    "window_title": None,
                    "parameters": "{}",
                    "url": None,
                    "dom_element": None,
                    "dom_tree_snapshot": None,
                    "visual_features": None,
                    "screenshot_before": None,
                    "screenshot_after": None,
                    "timestamp": None,
                }
            )

        row_ids = db_manager.insert_many("actions", actions)

        assert len(row_ids) == 10

        # 验证数据
        count = db_manager.get_table_count("actions")
        assert count >= 10

    def test_json_field_query(self, db_manager):
        """测试 JSON 字段查询"""
        # 插入带 JSON 字段的数据
        recording_id = "test-json-query"
        db_manager.insert(
            "actions",
            {
                "recording_id": recording_id,
                "sequence_number": 1,
                "action_type": "click",
                "recording_mode": "browser",
                "app_name": None,
                "process_name": None,
                "window_title": None,
                "parameters": '{"x": 100, "y": 200}',
                "url": None,
                "dom_element": '{"tag": "button", "id": "submit"}',
                "dom_tree_snapshot": None,
                "visual_features": None,
                "screenshot_before": None,
                "screenshot_after": None,
                "timestamp": None,
            },
        )

        # 查询并验证 JSON 字段
        result = db_manager.fetchone(
            "SELECT parameters, dom_element FROM actions WHERE recording_id = ?", (recording_id,)
        )

        assert result is not None
        # DuckDB 自动将 JSON 字符串解析为 JSON 类型
        assert '"x": 100' in str(result[0]) or '{"x":100}' in str(result[0])

    def test_context_manager(self, temp_db_path):
        """测试上下文管理器"""
        with DuckDBManager(temp_db_path) as manager:
            manager.initialize()
            tables = manager.get_tables()
            assert len(tables) > 0

        # 确保连接已关闭
        assert manager.conn is None

    def test_init_duckdb_function(self, temp_db_path):
        """测试 init_duckdb 辅助函数"""
        manager = init_duckdb(temp_db_path)

        assert manager is not None
        assert isinstance(manager, DuckDBManager)
        assert len(manager.get_tables()) > 0

        manager.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
