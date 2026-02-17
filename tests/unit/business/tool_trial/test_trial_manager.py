"""
TrialManager 单元测试
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch
from src.data.database import DatabaseManager
from src.business.intent.intent_models import Intent, IntentStatus
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
from src.business.tool_trial.trial_manager import TrialManager
from src.data.models import Tool


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
def trial_manager(db_manager):
    """创建 TrialManager"""
    return TrialManager(db_manager)


@pytest.fixture
def sample_intent(db_manager):
    """创建示例意图"""
    intent = Intent(
        recording_id="rec-001",
        core_operations=["打开登录页面", "输入用户名", "输入密码"],
        target="某网站",
        business_scenario="用户登录",
        status=IntentStatus.CONFIRMED,
    )
    repo = IntentRepository(db_manager)
    return repo.create(intent)


@pytest.fixture
def sample_pending_tool(sample_intent):
    """创建示例待试用工具"""
    return PendingTool(
        intent_id=sample_intent.intent_id,
        tool_name="自动登录",
        tool_description="自动登录到网站",
        execution_code="def login(): pass",
        execution_strategy="hybrid",
        parameters=[{"name": "username", "type": "string"}],
    )


class TestTrialManager:
    """TrialManager 测试"""

    def test_create_pending_tool(
        self, trial_manager, sample_intent, sample_pending_tool
    ):
        """测试创建待试用工具"""
        tool_code = "def login(): pass"
        tool_name = "自动登录"
        tool_description = "自动登录到网站"
        parameters = [{"name": "username", "type": "string"}]

        pending_tool = trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code=tool_code,
            tool_name=tool_name,
            tool_description=tool_description,
            parameters=parameters,
        )

        assert pending_tool is not None
        assert pending_tool.intent_id == sample_intent.intent_id
        assert pending_tool.tool_name == tool_name
        assert pending_tool.execution_code == tool_code
        assert pending_tool.status == PendingToolStatus.PENDING_TRIAL

    def test_create_pending_tool_invalid_intent(self, trial_manager):
        """测试使用无效 intent_id 创建待试用工具"""
        with pytest.raises(ValueError, match="Intent not found"):
            trial_manager.create_pending_tool(
                intent_id="invalid-intent-id",
                tool_code="def test(): pass",
                tool_name="测试工具",
            )

    def test_get_pending_tool(
        self, trial_manager, sample_intent, sample_pending_tool
    ):
        """测试获取待试用工具"""
        # 先创建
        created = trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code="def login(): pass",
            tool_name="自动登录",
        )

        # 获取
        retrieved = trial_manager.get_pending_tool(created.pending_tool_id)

        assert retrieved is not None
        assert retrieved.pending_tool_id == created.pending_tool_id
        assert retrieved.tool_name == "自动登录"

    def test_get_pending_tools_by_intent(
        self, trial_manager, sample_intent
    ):
        """测试根据 intent_id 获取待试用工具列表"""
        # 创建多个工具
        trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code="def login(): pass",
            tool_name="自动登录",
        )
        trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code="def register(): pass",
            tool_name="自动注册",
        )

        # 获取列表
        tools = trial_manager.get_pending_tools_by_intent(sample_intent.intent_id)

        assert len(tools) == 2

    def test_get_pending_tools_by_status(
        self, trial_manager, sample_intent
    ):
        """测试根据状态获取待试用工具列表"""
        # 创建工具
        trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code="def login(): pass",
            tool_name="自动登录",
        )

        # 获取等待试用的工具
        tools = trial_manager.get_pending_tools_by_status(
            PendingToolStatus.PENDING_TRIAL
        )

        assert len(tools) >= 1
        assert any(t.status == PendingToolStatus.PENDING_TRIAL for t in tools)

    def test_update_pending_tool(
        self, trial_manager, sample_intent
    ):
        """测试更新待试用工具"""
        # 创建工具
        created = trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code="def login(): pass",
            tool_name="自动登录",
        )

        # 更新
        created.tool_name = "自动登录 v2"
        updated = trial_manager.update_pending_tool(created)

        assert updated.tool_name == "自动登录 v2"

    def test_delete_pending_tool(
        self, trial_manager, sample_intent
    ):
        """测试删除待试用工具"""
        # 创建工具
        created = trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code="def login(): pass",
            tool_name="自动登录",
        )

        # 删除
        deleted = trial_manager.delete_pending_tool(created.pending_tool_id)

        assert deleted is True

        # 验证已删除
        retrieved = trial_manager.get_pending_tool(created.pending_tool_id)
        assert retrieved is None

    def test_start_trial(self, trial_manager, sample_intent):
        """测试开始试用"""
        # 创建待试用工具
        pending_tool = trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code="def login(): pass",
            tool_name="自动登录",
        )

        # 开始试用
        trial_data = {"username": "test", "password": "***"}
        trial = trial_manager.start_trial(
            pending_tool_id=pending_tool.pending_tool_id,
            trial_data=trial_data,
        )

        assert trial is not None
        assert trial.pending_tool_id == pending_tool.pending_tool_id
        assert trial.status == TrialStatus.RUNNING

        # 验证待试用工具状态已更新
        updated_tool = trial_manager.get_pending_tool(pending_tool.pending_tool_id)
        assert updated_tool.status == PendingToolStatus.TRIALING

    def test_start_trial_invalid_tool(self, trial_manager):
        """测试开始试用时使用无效的 pending_tool_id"""
        with pytest.raises(ValueError, match="Pending tool not found"):
            trial_manager.start_trial(
                pending_tool_id="invalid-tool-id",
                trial_data={},
            )

    def test_handle_trial_result_success(self, trial_manager, sample_intent):
        """测试处理试用结果（成功）"""
        # 创建待试用工具和试用记录
        pending_tool = trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code="def login(): pass",
            tool_name="自动登录",
        )

        trial = trial_manager.start_trial(
            pending_tool_id=pending_tool.pending_tool_id,
            trial_data={"username": "test"},
        )

        # 处理成功结果
        result = {"status": "success", "data": "logged in"}
        trial_manager.handle_trial_result(
            trial_id=trial.trial_id,
            result=result,
            success=True,
        )

        # 验证试用记录状态
        updated_trial = trial_manager.get_trial(trial.trial_id)
        assert updated_trial.status == TrialStatus.SUCCESS
        assert updated_trial.result == result

        # 验证待试用工具状态
        updated_tool = trial_manager.get_pending_tool(pending_tool.pending_tool_id)
        assert updated_tool.status == PendingToolStatus.TRIAL_SUCCESS

    def test_handle_trial_result_failure(self, trial_manager, sample_intent):
        """测试处理试用结果（失败）"""
        # 创建待试用工具和试用记录
        pending_tool = trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code="def login(): pass",
            tool_name="自动登录",
        )

        trial = trial_manager.start_trial(
            pending_tool_id=pending_tool.pending_tool_id,
            trial_data={},
        )

        # 处理失败结果
        error = "Element not found"
        trial_manager.handle_trial_result(
            trial_id=trial.trial_id,
            error=error,
            success=False,
        )

        # 验证试用记录状态
        updated_trial = trial_manager.get_trial(trial.trial_id)
        assert updated_trial.status == TrialStatus.FAILED
        assert updated_trial.error_message == error

        # 验证待试用工具状态
        updated_tool = trial_manager.get_pending_tool(pending_tool.pending_tool_id)
        assert updated_tool.status == PendingToolStatus.TRIAL_FAILED

    def test_promote_to_tool_set(self, trial_manager, sample_intent):
        """测试提升为正式工具"""
        # 创建待试用工具
        pending_tool = trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code="def login(): pass",
            tool_name="自动登录",
        )

        # 提升为正式工具
        tool = trial_manager.promote_to_tool_set(
            pending_tool_id=pending_tool.pending_tool_id
        )

        assert tool is not None
        assert tool.tool_name == "自动登录"
        assert tool.execution_code == "def login(): pass"
        assert tool.source == "trial"
        assert tool.source_intent_id == sample_intent.intent_id
        assert tool.pending_tool_id == pending_tool.pending_tool_id

        # 验证待试用工具状态
        updated_tool = trial_manager.get_pending_tool(pending_tool.pending_tool_id)
        assert updated_tool.status == PendingToolStatus.PROMOTED

    def test_get_trial(self, trial_manager, sample_intent):
        """测试获取试用记录"""
        # 创建待试用工具和试用记录
        pending_tool = trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code="def login(): pass",
            tool_name="自动登录",
        )

        trial = trial_manager.start_trial(
            pending_tool_id=pending_tool.pending_tool_id,
            trial_data={},
        )

        # 获取试用记录
        retrieved = trial_manager.get_trial(trial.trial_id)

        assert retrieved is not None
        assert retrieved.trial_id == trial.trial_id

    def test_get_trials_by_pending_tool(
        self, trial_manager, sample_intent
    ):
        """测试获取待试用工具的所有试用记录"""
        # 创建待试用工具
        pending_tool = trial_manager.create_pending_tool(
            intent_id=sample_intent.intent_id,
            tool_code="def login(): pass",
            tool_name="自动登录",
        )

        # 创建第一个试用记录
        trial1 = trial_manager.start_trial(
            pending_tool_id=pending_tool.pending_tool_id,
            trial_data={"attempt": 1},
        )

        # 处理第一次试用结果（失败），这样工具才能再次试用
        trial_manager.handle_trial_result(
            trial_id=trial1.trial_id,
            success=False,
            error="Test error",
        )

        # 创建第二个试用记录
        trial2 = trial_manager.start_trial(
            pending_tool_id=pending_tool.pending_tool_id,
            trial_data={"attempt": 2},
        )

        # 获取试用记录列表
        trials = trial_manager.get_trials_by_pending_tool(
            pending_tool.pending_tool_id
        )

        assert len(trials) == 2
