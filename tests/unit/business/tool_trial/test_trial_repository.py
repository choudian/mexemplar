"""
Tool Trial Repository 单元测试
"""

import pytest
from datetime import datetime
from src.data.database import DatabaseManager
from src.business.intent.intent_models import Intent
from src.business.intent.intent_repository import IntentRepository
from src.business.tool_trial.trial_models import (
    PendingTool,
    PendingToolStatus,
    ToolTrial,
    TrialStatus,
)
from src.business.tool_trial.trial_repository import (
    PendingToolRepository,
    ToolTrialRepository,
)


@pytest.fixture
def db_manager(tmp_path):
    """创建临时数据库"""
    db_path = tmp_path / "test.db"
    db_manager = DatabaseManager(str(db_path))
    db_manager.initialize()

    # 运行迁移
    from src.data.migrations import migrate_to_v2

    migrate_to_v2(db_manager)

    yield db_manager

    db_manager.close()


@pytest.fixture
def pending_tool_repository(db_manager):
    """创建 PendingToolRepository"""
    return PendingToolRepository(db_manager)


@pytest.fixture
def tool_trial_repository(db_manager):
    """创建 ToolTrialRepository"""
    return ToolTrialRepository(db_manager)


@pytest.fixture
def sample_intent(db_manager):
    """创建示例意图（满足外键约束）"""
    intent = Intent(
        recording_id="rec-001",
        core_operations=["打开登录页面"],
        target="某网站",
    )
    repo = IntentRepository(db_manager)
    return repo.create(intent)


@pytest.fixture
def sample_pending_tool(sample_intent):
    """创建示例待试用工具"""
    return PendingTool(
        intent_id=sample_intent.intent_id,  # 使用真实的 intent_id
        tool_name="自动登录",
        tool_description="自动登录到网站",
        execution_code="def login(): pass",
        execution_strategy="hybrid",
        parameters=[{"name": "username", "type": "string"}],
    )


@pytest.fixture
def sample_trial(sample_pending_tool, pending_tool_repository):
    """创建示例试用记录"""
    # 先创建 pending_tool 以满足外键约束
    pending_tool_repository.create(sample_pending_tool)

    return ToolTrial(
        pending_tool_id=sample_pending_tool.pending_tool_id,  # 使用真实的 pending_tool_id
        trial_data={"username": "test", "password": "***"},
    )


class TestPendingToolRepository:
    """PendingToolRepository 测试"""

    def test_create_pending_tool(
        self, pending_tool_repository, sample_pending_tool
    ):
        """测试创建待试用工具"""
        created = pending_tool_repository.create(sample_pending_tool)

        assert created.pending_tool_id == sample_pending_tool.pending_tool_id
        assert created.intent_id == sample_pending_tool.intent_id  # 使用真实的 intent_id
        assert created.tool_name == "自动登录"
        assert created.status == PendingToolStatus.PENDING_TRIAL

    def test_get_by_id(self, pending_tool_repository, sample_pending_tool):
        """测试根据ID获取待试用工具"""
        pending_tool_repository.create(sample_pending_tool)

        retrieved = pending_tool_repository.get_by_id(
            sample_pending_tool.pending_tool_id
        )

        assert retrieved is not None
        assert retrieved.pending_tool_id == sample_pending_tool.pending_tool_id
        assert retrieved.tool_name == "自动登录"

    def test_get_by_intent_id(
        self, pending_tool_repository, sample_pending_tool
    ):
        """测试根据意图ID获取待试用工具列表"""
        pending_tool_repository.create(sample_pending_tool)

        tools = pending_tool_repository.get_by_intent_id(sample_pending_tool.intent_id)  # 使用真实的 intent_id

        assert len(tools) >= 1
        assert any(t.pending_tool_id == sample_pending_tool.pending_tool_id for t in tools)

    def test_get_by_status(
        self, pending_tool_repository, sample_pending_tool
    ):
        """测试根据状态获取待试用工具列表"""
        pending_tool_repository.create(sample_pending_tool)

        tools = pending_tool_repository.get_by_status(PendingToolStatus.PENDING_TRIAL)

        assert len(tools) >= 1
        assert any(
            t.pending_tool_id == sample_pending_tool.pending_tool_id for t in tools
        )

    def test_update_pending_tool(
        self, pending_tool_repository, sample_pending_tool
    ):
        """测试更新待试用工具"""
        pending_tool_repository.create(sample_pending_tool)

        sample_pending_tool.tool_name = "自动登录 v2"
        sample_pending_tool.trial_count = 1

        updated = pending_tool_repository.update(sample_pending_tool)

        assert updated.tool_name == "自动登录 v2"
        assert updated.trial_count == 1

    def test_delete_pending_tool(
        self, pending_tool_repository, sample_pending_tool
    ):
        """测试删除待试用工具"""
        pending_tool_repository.create(sample_pending_tool)

        deleted = pending_tool_repository.delete(sample_pending_tool.pending_tool_id)

        assert deleted is True

        retrieved = pending_tool_repository.get_by_id(
            sample_pending_tool.pending_tool_id
        )
        assert retrieved is None

    def test_get_all(
        self, pending_tool_repository, sample_pending_tool, sample_intent
    ):
        """测试获取所有待试用工具"""
        pending_tool_repository.create(sample_pending_tool)

        # 创建第二个工具（需要先创建对应的 intent）
        intent2 = Intent(recording_id="rec-002", core_operations=["搜索商品"])
        intent_repo = IntentRepository(pending_tool_repository.db_manager)
        intent2 = intent_repo.create(intent2)

        tool2 = PendingTool(
            intent_id=intent2.intent_id,  # 使用真实的 intent_id
            tool_name="自动注册",
        )
        pending_tool_repository.create(tool2)

        all_tools = pending_tool_repository.get_all(limit=10)

        assert len(all_tools) >= 2


class TestToolTrialRepository:
    """ToolTrialRepository 测试"""

    def test_create_trial(self, tool_trial_repository, sample_trial):
        """测试创建试用记录"""
        created = tool_trial_repository.create(sample_trial)

        assert created.trial_id == sample_trial.trial_id
        assert created.pending_tool_id == sample_trial.pending_tool_id  # 使用真实的 pending_tool_id
        assert created.status == TrialStatus.RUNNING

    def test_get_by_id(self, tool_trial_repository, sample_trial):
        """测试根据ID获取试用记录"""
        tool_trial_repository.create(sample_trial)

        retrieved = tool_trial_repository.get_by_id(sample_trial.trial_id)

        assert retrieved is not None
        assert retrieved.trial_id == sample_trial.trial_id
        assert retrieved.pending_tool_id == sample_trial.pending_tool_id  # 使用真实的 pending_tool_id

    def test_get_by_pending_tool_id(
        self,
        tool_trial_repository,
        pending_tool_repository,
        sample_pending_tool,
        sample_intent,
    ):
        """测试根据待试用工具ID获取试用记录列表"""
        # 创建 pending_tool
        pending_tool_repository.create(sample_pending_tool)

        trial1 = tool_trial_repository.create(
            ToolTrial(pending_tool_id=sample_pending_tool.pending_tool_id)
        )
        trial2 = tool_trial_repository.create(
            ToolTrial(pending_tool_id=sample_pending_tool.pending_tool_id)
        )

        trials = tool_trial_repository.get_by_pending_tool_id(
            sample_pending_tool.pending_tool_id
        )

        assert len(trials) >= 2

    def test_get_by_status(self, tool_trial_repository, sample_trial):
        """测试根据状态获取试用记录列表"""
        tool_trial_repository.create(sample_trial)

        trials = tool_trial_repository.get_by_status(TrialStatus.RUNNING)

        assert len(trials) >= 1
        assert any(t.trial_id == sample_trial.trial_id for t in trials)

    def test_update_trial(self, tool_trial_repository, sample_trial):
        """测试更新试用记录"""
        tool_trial_repository.create(sample_trial)

        sample_trial.mark_success({"status": "success"})

        updated = tool_trial_repository.update(sample_trial)

        assert updated.status == TrialStatus.SUCCESS
        assert updated.result == {"status": "success"}

    def test_delete_trial(self, tool_trial_repository, sample_trial):
        """测试删除试用记录"""
        tool_trial_repository.create(sample_trial)

        deleted = tool_trial_repository.delete(sample_trial.trial_id)

        assert deleted is True

        retrieved = tool_trial_repository.get_by_id(sample_trial.trial_id)
        assert retrieved is None
