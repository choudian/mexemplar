"""
TrialDataTemplateRepository 单元测试
"""

import pytest
import sqlite3
from datetime import datetime
from unittest.mock import Mock, patch

from src.data.database import DatabaseManager
from src.business.tool_trial.trial_models import TrialDataTemplate
from src.business.tool_trial.trial_data_template_repository import (
    TrialDataTemplateRepository,
)


@pytest.fixture
def db_manager():
    """创建测试用的数据库管理器"""
    import tempfile
    import os

    # 使用临时文件而不是内存数据库
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    db_manager = DatabaseManager(temp_path)
    db_manager.initialize()

    # 创建 trial_data_templates 表
    conn = db_manager.connect()
    cursor = conn.cursor()

    # 创建关联表（外键依赖）
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_tools (
            pending_tool_id TEXT PRIMARY KEY,
            intent_id TEXT,
            tool_name TEXT,
            tool_description TEXT,
            execution_code TEXT,
            code_language TEXT,
            execution_strategy TEXT,
            status TEXT,
            trial_count INTEGER DEFAULT 0,
            max_trials INTEGER DEFAULT 3,
            created_at REAL,
            updated_at REAL
        )
    """
    )

    # 创建 trial_data_templates 表
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS trial_data_templates (
            template_id TEXT PRIMARY KEY,
            pending_tool_id TEXT NOT NULL,
            template_name TEXT,
            template_data TEXT,
            is_real_data INTEGER DEFAULT 0,
            description TEXT,
            data_source TEXT,
            created_at REAL,
            updated_at REAL,
            FOREIGN KEY (pending_tool_id) REFERENCES pending_tools(pending_tool_id)
        )
    """
    )

    conn.commit()

    yield db_manager

    # 清理
    db_manager.close()
    # 删除临时文件
    try:
        os.unlink(temp_path)
    except:
        pass


@pytest.fixture
def sample_pending_tool(db_manager):
    """创建示例待试用工具"""
    conn = db_manager.connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO pending_tools
        (pending_tool_id, intent_id, tool_name, tool_description, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "pt-001",
            "intent-001",
            "测试工具",
            "测试描述",
            "pending_trial",
            datetime.now().timestamp(),
            datetime.now().timestamp(),
        ),
    )

    conn.commit()

    return "pt-001"


@pytest.fixture
def template_repository(db_manager):
    """创建 TrialDataTemplateRepository 实例"""
    return TrialDataTemplateRepository(db_manager)


class TestTrialDataTemplateRepository:
    """TrialDataTemplateRepository 测试类"""

    def test_create_template(self, template_repository, sample_pending_tool):
        """测试创建试用数据模板"""
        template = TrialDataTemplate(
            pending_tool_id=sample_pending_tool,
            template_name="测试模板",
            template_data={"username": "test", "password": "123456"},
            is_real_data=False,
            description="测试用模拟数据",
            data_source="ai_generated",
        )

        created = template_repository.create(template)

        assert created.template_id is not None
        assert created.template_name == "测试模板"
        assert created.pending_tool_id == sample_pending_tool
        assert created.is_real_data is False
        assert created.data_source == "ai_generated"
        assert created.created_at is not None

    def test_create_real_data_template(self, template_repository, sample_pending_tool):
        """测试创建真实数据模板"""
        template = TrialDataTemplate(
            pending_tool_id=sample_pending_tool,
            template_name="真实数据",
            template_data={"username": "realuser", "password": "realpass"},
            is_real_data=True,
            description="真实录制数据",
            data_source="recording",
        )

        created = template_repository.create(template)

        assert created.is_real_data is True
        assert created.data_source == "recording"

    def test_get_by_id(self, template_repository, sample_pending_tool):
        """测试根据 ID 获取模板"""
        template = TrialDataTemplate(
            pending_tool_id=sample_pending_tool,
            template_name="测试模板",
            template_data={"key": "value"},
        )

        created = template_repository.create(template)
        found = template_repository.get_by_id(created.template_id)

        assert found is not None
        assert found.template_id == created.template_id
        assert found.template_name == "测试模板"
        assert found.template_data == {"key": "value"}

    def test_get_by_id_not_found(self, template_repository):
        """测试获取不存在的模板"""
        found = template_repository.get_by_id("non-existent-id")
        assert found is None

    def test_get_by_pending_tool_id(self, template_repository, sample_pending_tool):
        """测试根据待试用工具 ID 获取模板列表"""
        # 创建多个模板
        template1 = TrialDataTemplate(
            pending_tool_id=sample_pending_tool,
            template_name="模板1",
            template_data={"data": "1"},
            is_real_data=False,
        )
        template2 = TrialDataTemplate(
            pending_tool_id=sample_pending_tool,
            template_name="模板2",
            template_data={"data": "2"},
            is_real_data=True,
        )

        template_repository.create(template1)
        template_repository.create(template2)

        templates = template_repository.get_by_pending_tool_id(sample_pending_tool)

        assert len(templates) == 2
        assert templates[0].template_name in ["模板1", "模板2"]

    def test_get_real_data_templates(self, template_repository, sample_pending_tool):
        """测试只获取真实数据模板"""
        # 创建模拟数据和真实数据
        mock_template = TrialDataTemplate(
            pending_tool_id=sample_pending_tool,
            template_name="模拟数据",
            template_data={"data": "mock"},
            is_real_data=False,
        )
        real_template = TrialDataTemplate(
            pending_tool_id=sample_pending_tool,
            template_name="真实数据",
            template_data={"data": "real"},
            is_real_data=True,
        )

        template_repository.create(mock_template)
        template_repository.create(real_template)

        real_templates = template_repository.get_real_data_templates(
            sample_pending_tool
        )

        assert len(real_templates) == 1
        assert real_templates[0].is_real_data is True
        assert real_templates[0].template_name == "真实数据"

    def test_get_all(self, template_repository, sample_pending_tool, db_manager):
        """测试获取所有模板"""
        # 创建另一个待试用工具
        conn = db_manager.connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO pending_tools
            (pending_tool_id, intent_id, tool_name, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                "pt-002",
                "intent-002",
                "测试工具2",
                "pending_trial",
                datetime.now().timestamp(),
                datetime.now().timestamp(),
            ),
        )
        conn.commit()

        # 创建多个模板
        template1 = TrialDataTemplate(
            pending_tool_id=sample_pending_tool,
            template_name="模板1",
            template_data={"data": "1"},
        )
        template2 = TrialDataTemplate(
            pending_tool_id="pt-002",
            template_name="模板2",
            template_data={"data": "2"},
        )

        template_repository.create(template1)
        template_repository.create(template2)

        all_templates = template_repository.get_all()

        assert len(all_templates) == 2

    def test_update_template(self, template_repository, sample_pending_tool):
        """测试更新模板"""
        template = TrialDataTemplate(
            pending_tool_id=sample_pending_tool,
            template_name="原始名称",
            template_data={"key": "value"},
            is_real_data=False,
        )

        created = template_repository.create(template)

        # 更新
        created.template_name = "更新后的名称"
        created.template_data = {"key": "new_value"}
        created.is_real_data = True

        updated = template_repository.update(created)

        assert updated.template_name == "更新后的名称"
        assert updated.template_data == {"key": "new_value"}
        assert updated.is_real_data is True
        assert updated.updated_at is not None

    def test_update_nonexistent_template(self, template_repository):
        """测试更新不存在的模板"""
        template = TrialDataTemplate(
            template_id="non-existent",
            pending_tool_id="pt-001",
            template_name="测试",
            template_data={},
        )

        with pytest.raises(ValueError, match="试用数据模板不存在"):
            template_repository.update(template)

    def test_delete_template(self, template_repository, sample_pending_tool):
        """测试删除模板"""
        template = TrialDataTemplate(
            pending_tool_id=sample_pending_tool,
            template_name="测试模板",
            template_data={"key": "value"},
        )

        created = template_repository.create(template)
        template_id = created.template_id

        # 删除
        success = template_repository.delete(template_id)
        assert success is True

        # 验证删除
        found = template_repository.get_by_id(template_id)
        assert found is None

    def test_delete_nonexistent_template(self, template_repository):
        """测试删除不存在的模板"""
        success = template_repository.delete("non-existent-id")
        assert success is False

    def test_count_by_pending_tool(self, template_repository, sample_pending_tool):
        """测试统计模板数量"""
        # 创建多个模板
        template1 = TrialDataTemplate(
            pending_tool_id=sample_pending_tool,
            template_name="模板1",
            template_data={"data": "1"},
        )
        template2 = TrialDataTemplate(
            pending_tool_id=sample_pending_tool,
            template_name="模板2",
            template_data={"data": "2"},
        )

        template_repository.create(template1)
        template_repository.create(template2)

        count = template_repository.count_by_pending_tool(sample_pending_tool)
        assert count == 2

    def test_template_data_serialization(
        self, template_repository, sample_pending_tool
    ):
        """测试复杂数据的序列化"""
        complex_data = {
            "user": {"name": "张三", "age": 25},
            "items": [1, 2, 3, 4, 5],
            "nested": {"a": {"b": {"c": "deep"}}},
        }

        template = TrialDataTemplate(
            pending_tool_id=sample_pending_tool,
            template_name="复杂数据",
            template_data=complex_data,
        )

        created = template_repository.create(template)
        found = template_repository.get_by_id(created.template_id)

        assert found.template_data == complex_data
        assert found.template_data["user"]["name"] == "张三"
        assert found.template_data["items"] == [1, 2, 3, 4, 5]
        assert found.template_data["nested"]["a"]["b"]["c"] == "deep"
