"""
Tool Trial 数据模型单元测试
"""

import pytest
from datetime import datetime
from src.business.tool_trial.trial_models import (
    PendingTool,
    PendingToolStatus,
    ToolTrial,
    TrialStatus,
)


class TestPendingTool:
    """PendingTool 模型测试"""

    def test_create_pending_tool(self):
        """测试创建待试用工具"""
        tool = PendingTool(
            intent_id="intent-001",
            tool_name="自动登录",
            tool_description="自动登录到网站",
            execution_code="def login(): pass",
            parameters=[{"name": "username", "type": "string"}],
        )

        assert tool.pending_tool_id is not None
        assert tool.intent_id == "intent-001"
        assert tool.tool_name == "自动登录"
        assert tool.status == PendingToolStatus.PENDING_TRIAL
        assert tool.trial_count == 0

    def test_pending_tool_to_dict(self):
        """测试转换为字典"""
        tool = PendingTool(
            intent_id="intent-001",
            tool_name="自动登录",
            execution_code="def login(): pass",
        )

        data = tool.to_dict()

        assert isinstance(data, dict)
        assert data["pending_tool_id"] == tool.pending_tool_id
        assert data["intent_id"] == "intent-001"
        assert data["tool_name"] == "自动登录"
        assert data["status"] == "pending_trial"

    def test_pending_tool_from_dict(self):
        """测试从字典创建"""
        data = {
            "pending_tool_id": "pt-001",
            "intent_id": "intent-001",
            "tool_name": "自动登录",
            "tool_description": "自动登录到网站",
            "execution_code": "def login(): pass",
            "code_language": "python",
            "execution_strategy": "hybrid",
            "parameters": '[{"name": "username"}]',
            "status": "trial_success",
            "trial_count": 2,
            "max_trials": 3,
            "last_trial_result": "执行成功",
            "last_error": None,
            "created_at": "2026-02-10T10:00:00",
            "updated_at": "2026-02-10T10:05:00",
            "promoted_at": None,
        }

        tool = PendingTool.from_dict(data)

        assert tool.pending_tool_id == "pt-001"
        assert tool.intent_id == "intent-001"
        assert tool.execution_code == "def login(): pass"
        assert tool.status == PendingToolStatus.TRIAL_SUCCESS
        assert tool.trial_count == 2

    def test_can_trial(self):
        """测试是否可以继续试用"""
        tool = PendingTool(
            intent_id="intent-001",
            tool_name="自动登录",
            trial_count=2,
            max_trials=3,
            status=PendingToolStatus.TRIAL_FAILED,
        )

        assert tool.can_trial() is True

        tool.trial_count = 3
        assert tool.can_trial() is False

        tool.status = PendingToolStatus.PROMOTED
        assert tool.can_trial() is False

    def test_increment_trial_count(self):
        """测试增加试用次数"""
        tool = PendingTool(intent_id="intent-001", tool_name="自动登录")

        assert tool.trial_count == 0

        tool.increment_trial_count()
        assert tool.trial_count == 1
        assert tool.updated_at is not None

    def test_promote(self):
        """测试提升为正式工具"""
        tool = PendingTool(intent_id="intent-001", tool_name="自动登录")

        tool.promote()

        assert tool.status == PendingToolStatus.PROMOTED
        assert tool.promoted_at is not None
        assert tool.updated_at is not None

    def test_mark_failed(self):
        """测试标记为最终失败"""
        tool = PendingTool(intent_id="intent-001", tool_name="自动登录")

        tool.mark_failed()

        assert tool.status == PendingToolStatus.FAILED
        assert tool.updated_at is not None


class TestToolTrial:
    """ToolTrial 模型测试"""

    def test_create_trial(self):
        """测试创建试用记录"""
        trial = ToolTrial(
            pending_tool_id="pt-001",
            trial_data={"username": "test", "password": "***"},
        )

        assert trial.trial_id is not None
        assert trial.pending_tool_id == "pt-001"
        assert trial.status == TrialStatus.RUNNING
        assert trial.started_at is None  # 没有自动设置

    def test_trial_to_dict(self):
        """测试转换为字典"""
        trial = ToolTrial(
            pending_tool_id="pt-001",
            trial_data={"username": "test"},
            status=TrialStatus.SUCCESS,
        )

        data = trial.to_dict()

        assert isinstance(data, dict)
        assert data["trial_id"] == trial.trial_id
        assert data["pending_tool_id"] == "pt-001"
        assert data["status"] == "success"

    def test_trial_from_dict(self):
        """测试从字典创建"""
        data = {
            "trial_id": "trial-001",
            "pending_tool_id": "pt-001",
            "trial_data": '{"username": "test"}',
            "status": "failed",
            "result": None,
            "error_message": "Element not found",
            "error_type": "LocatorError",
            "execution_log": "Step 1 failed",
            "execution_steps": '[{"step": 1, "status": "failed"}]',
            "fix_attempted": True,
            "fix_successful": False,
            "fixed_code": None,
            "started_at": "2026-02-10T10:00:00",
            "finished_at": "2026-02-10T10:01:00",
        }

        trial = ToolTrial.from_dict(data)

        assert trial.trial_id == "trial-001"
        assert trial.pending_tool_id == "pt-001"
        assert trial.status == TrialStatus.FAILED
        assert trial.error_message == "Element not found"
        assert trial.fix_attempted is True

    def test_mark_success(self):
        """测试标记为成功"""
        trial = ToolTrial(pending_tool_id="pt-001")

        result = {"status": "success", "data": "logged in"}
        trial.mark_success(result)

        assert trial.status == TrialStatus.SUCCESS
        assert trial.result == result
        assert trial.finished_at is not None

    def test_mark_failed(self):
        """测试标记为失败"""
        trial = ToolTrial(pending_tool_id="pt-001")

        trial.mark_failed("Element not found", "LocatorError")

        assert trial.status == TrialStatus.FAILED
        assert trial.error_message == "Element not found"
        assert trial.error_type == "LocatorError"
        assert trial.finished_at is not None

    def test_mark_cancelled(self):
        """测试标记为已取消"""
        trial = ToolTrial(pending_tool_id="pt-001")

        trial.mark_cancelled()

        assert trial.status == TrialStatus.CANCELLED
        assert trial.finished_at is not None

    def test_add_execution_step(self):
        """测试添加执行步骤"""
        trial = ToolTrial(pending_tool_id="pt-001")

        step1 = {"step": 1, "action": "click", "element": "login-button"}
        step2 = {"step": 2, "action": "input", "element": "username"}

        trial.add_execution_step(step1)
        trial.add_execution_step(step2)

        assert len(trial.execution_steps) == 2
        assert trial.execution_steps[0] == step1
        assert trial.execution_steps[1] == step2


class TestStatusEnums:
    """状态枚举测试"""

    def test_pending_tool_status_enum(self):
        """测试 PendingToolStatus 枚举"""
        assert PendingToolStatus.PENDING_TRIAL == "pending_trial"
        assert PendingToolStatus.TRIALING == "trialing"
        assert PendingToolStatus.TRIAL_SUCCESS == "trial_success"
        assert PendingToolStatus.TRIAL_FAILED == "trial_failed"
        assert PendingToolStatus.AWAITING_REAL_DATA == "awaiting_real_data"
        assert PendingToolStatus.PROMOTED == "promoted"
        assert PendingToolStatus.FAILED == "failed"

    def test_trial_status_enum(self):
        """测试 TrialStatus 枚举"""
        assert TrialStatus.RUNNING == "running"
        assert TrialStatus.SUCCESS == "success"
        assert TrialStatus.FAILED == "failed"
        assert TrialStatus.CANCELLED == "cancelled"
        assert TrialStatus.AWAITING_DATA == "awaiting_data"
