"""
TrialManager 试用数据模板功能测试
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from src.data.database import DatabaseManager
from src.business.tool_trial.trial_manager import TrialManager
from src.business.intent.intent_models import Intent, IntentStatus
from src.business.tool_trial.trial_models import (
    PendingTool,
    PendingToolStatus,
    TrialDataTemplate,
)


@pytest.fixture
def db_manager():
    """创建测试用的数据库管理器"""
    import tempfile
    import os

    # 使用临时文件数据库
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    db_manager = DatabaseManager(temp_path)

    # 先初始化基础表结构
    db_manager.initialize()

    # 再运行迁移
    from src.data.migrations import run_migrations

    run_migrations(db_manager)

    yield db_manager

    # 清理
    db_manager.close()
    try:
        os.unlink(temp_path)
    except:
        pass


@pytest.fixture
def trial_manager(db_manager):
    """创建 TrialManager 实例"""
    return TrialManager(db_manager)


@pytest.fixture
def sample_intent(trial_manager):
    """创建示例意图"""
    intent = Intent(
        recording_id="recording-001",
        core_operations=["点击登录按钮", "输入用户名密码"],
        target="https://example.com/login",
        business_scenario="用户登录",
        expected_results=["登录成功"],
        status=IntentStatus.CONFIRMED,
    )

    return trial_manager.intent_repo.create(intent)


@pytest.fixture
def sample_pending_tool(trial_manager, sample_intent):
    """创建示例待试用工具"""
    pending_tool = PendingTool(
        intent_id=sample_intent.intent_id,
        tool_name="登录工具",
        tool_description="自动登录功能",
        execution_code="def login(username, password):\n    pass",
        execution_strategy="browser",
        parameters=[
            {"name": "username", "type": "string", "required": True},
            {"name": "password", "type": "string", "required": True},
        ],
    )

    return trial_manager.create_pending_tool(
        intent_id=pending_tool.intent_id,
        tool_code=pending_tool.execution_code,
        tool_name=pending_tool.tool_name,
        tool_description=pending_tool.tool_description,
        execution_strategy=pending_tool.execution_strategy,
        parameters=pending_tool.parameters,
    )


class TestTrialManagerTemplates:
    """TrialManager 试用数据模板功能测试"""

    def test_save_trial_data_template(
        self, trial_manager, sample_pending_tool
    ):
        """测试保存试用数据模板"""
        template_data = {
            "username": "testuser",
            "password": "testpass123",
            "login_url": "https://example.com/login",
        }

        template = trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data=template_data,
            template_name="测试登录数据",
            is_real_data=False,
            description="AI 生成的模拟数据",
            data_source="ai_generated",
        )

        assert template.template_id is not None
        assert template.template_name == "测试登录数据"
        assert template.template_data == template_data
        assert template.is_real_data is False
        assert template.data_source == "ai_generated"

    def test_save_real_data_template(self, trial_manager, sample_pending_tool):
        """测试保存真实数据模板"""
        template_data = {
            "username": "realuser",
            "password": "realpass123",
        }

        template = trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data=template_data,
            template_name="真实登录数据",
            is_real_data=True,
            description="用户提供的真实数据",
            data_source="user_generated",
        )

        assert template.is_real_data is True
        assert template.data_source == "user_generated"

    def test_save_template_invalid_pending_tool(self, trial_manager):
        """测试保存模板到不存在的待试用工具"""
        with pytest.raises(ValueError, match="Pending tool not found"):
            trial_manager.save_trial_data_template(
                pending_tool_id="non-existent-id",
                template_data={},
            )

    def test_get_trial_data_templates(
        self, trial_manager, sample_pending_tool
    ):
        """测试获取待试用工具的所有数据模板"""
        # 创建多个模板
        template1 = trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data={"username": "user1"},
            template_name="模板1",
            is_real_data=False,
        )

        template2 = trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data={"username": "user2"},
            template_name="模板2",
            is_real_data=True,
        )

        templates = trial_manager.get_trial_data_templates(
            sample_pending_tool.pending_tool_id
        )

        assert len(templates) == 2
        template_names = [t.template_name for t in templates]
        assert "模板1" in template_names
        assert "模板2" in template_names

    def test_get_real_data_templates_only(self, trial_manager, sample_pending_tool):
        """测试只获取真实数据模板"""
        # 创建模拟数据和真实数据
        trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data={"username": "mock"},
            template_name="模拟数据",
            is_real_data=False,
        )

        trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data={"username": "real"},
            template_name="真实数据",
            is_real_data=True,
        )

        real_templates = trial_manager.get_trial_data_templates(
            sample_pending_tool.pending_tool_id, only_real_data=True
        )

        assert len(real_templates) == 1
        assert real_templates[0].is_real_data is True
        assert real_templates[0].template_name == "真实数据"

    def test_get_trial_data_template_by_id(
        self, trial_manager, sample_pending_tool
    ):
        """测试根据 ID 获取模板"""
        created = trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data={"username": "test"},
            template_name="测试模板",
        )

        found = trial_manager.get_trial_data_template(created.template_id)

        assert found is not None
        assert found.template_id == created.template_id
        assert found.template_name == "测试模板"

    def test_get_trial_data_template_not_found(self, trial_manager):
        """测试获取不存在的模板"""
        found = trial_manager.get_trial_data_template("non-existent-id")
        assert found is None

    def test_update_trial_data_template(
        self, trial_manager, sample_pending_tool
    ):
        """测试更新试用数据模板"""
        created = trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data={"username": "old"},
            template_name="旧名称",
            is_real_data=False,
        )

        # 更新
        created.template_name = "新名称"
        created.template_data = {"username": "new"}
        created.is_real_data = True
        created.description = "更新后的描述"

        updated = trial_manager.update_trial_data_template(created)

        assert updated.template_name == "新名称"
        assert updated.template_data == {"username": "new"}
        assert updated.is_real_data is True
        assert updated.description == "更新后的描述"

    def test_delete_trial_data_template(
        self, trial_manager, sample_pending_tool
    ):
        """测试删除试用数据模板"""
        created = trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data={"username": "test"},
            template_name="测试模板",
        )

        template_id = created.template_id

        # 删除
        success = trial_manager.delete_trial_data_template(template_id)
        assert success is True

        # 验证删除
        found = trial_manager.get_trial_data_template(template_id)
        assert found is None

    def test_get_available_trial_data_with_real_data(
        self, trial_manager, sample_pending_tool
    ):
        """测试获取可用试用数据（优先使用真实数据）"""
        # 创建模拟数据
        trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data={"username": "mock", "password": "mockpass"},
            template_name="模拟数据",
            is_real_data=False,
        )

        # 创建真实数据
        real_data = {"username": "real", "password": "realpass"}
        trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data=real_data,
            template_name="真实数据",
            is_real_data=True,
        )

        # 获取可用数据
        available = trial_manager.get_available_trial_data(
            sample_pending_tool.pending_tool_id
        )

        assert available is not None
        # 应该返回真实数据
        assert available == real_data
        assert available["username"] == "real"

    def test_get_available_trial_data_only_mock(
        self, trial_manager, sample_pending_tool
    ):
        """测试获取可用试用数据（只有模拟数据）"""
        mock_data = {"username": "mock", "password": "mockpass"}
        trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data=mock_data,
            template_name="模拟数据",
            is_real_data=False,
        )

        available = trial_manager.get_available_trial_data(
            sample_pending_tool.pending_tool_id
        )

        assert available is not None
        assert available == mock_data

    def test_get_available_trial_data_no_templates(
        self, trial_manager, sample_pending_tool
    ):
        """测试获取可用试用数据（没有模板）"""
        available = trial_manager.get_available_trial_data(
            sample_pending_tool.pending_tool_id
        )

        assert available is None

    def test_template_integration_with_trial_workflow(
        self, trial_manager, sample_pending_tool
    ):
        """测试模板与试用工作流的集成"""
        # 1. 保存模拟数据
        mock_data = {"username": "test", "password": "test123"}
        trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data=mock_data,
            template_name="模拟数据",
            is_real_data=False,
        )

        # 2. 获取可用数据
        available_data = trial_manager.get_available_trial_data(
            sample_pending_tool.pending_tool_id
        )

        assert available_data == mock_data

        # 3. 开始试用（使用可用数据）
        trial = trial_manager.start_trial(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            trial_data=available_data,
        )

        assert trial.trial_data == mock_data
        assert trial.status.value == "running"

    def test_multiple_pending_tools_templates(
        self, trial_manager, sample_intent, sample_pending_tool
    ):
        """测试多个待试用工具的模板管理"""
        # 创建第二个待试用工具
        pending_tool2 = trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code="def register(): pass",
            tool_name="注册工具",
            tool_description="用户注册",
        )

        # 为第一个工具保存模板
        trial_manager.save_trial_data_template(
            pending_tool_id=sample_pending_tool.pending_tool_id,
            template_data={"action": "login"},
            template_name="登录数据",
        )

        # 为第二个工具保存模板
        trial_manager.save_trial_data_template(
            pending_tool_id=pending_tool2.pending_tool_id,
            template_data={"action": "register"},
            template_name="注册数据",
        )

        # 获取第一个工具的模板
        templates1 = trial_manager.get_trial_data_templates(
            sample_pending_tool.pending_tool_id
        )
        assert len(templates1) == 1
        assert templates1[0].template_data["action"] == "login"

        # 获取第二个工具的模板
        templates2 = trial_manager.get_trial_data_templates(
            pending_tool2.pending_tool_id
        )
        assert len(templates2) == 1
        assert templates2[0].template_data["action"] == "register"
