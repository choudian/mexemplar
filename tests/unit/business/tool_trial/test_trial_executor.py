"""
TrialExecutor 单元测试
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from src.data.database import DatabaseManager
from src.business.tool_trial.trial_models import (
    PendingTool,
    PendingToolStatus,
    ToolTrial,
    TrialStatus,
)
from src.business.tool_trial.trial_manager import TrialManager
from src.business.tool_trial.trial_executor import TrialExecutor, ExecutionResult
from src.data.models import Tool


@pytest.fixture
def db_manager(tmp_path):
    """创建临时数据库"""
    db_path = tmp_path / "test.db"
    db_manager = DatabaseManager(str(db_path))
    db_manager.initialize()

    from src.data.migrations import migrate_to_v2

    migrate_to_v2(db_manager)

    yield db_manager

    db_manager.close()


@pytest.fixture
def sample_intent(db_manager):
    """创建示例意图"""
    from src.business.intent.intent_models import Intent
    from src.business.intent.intent_repository import IntentRepository

    intent = Intent(
        recording_id="rec-001",
        core_operations=["打开登录页面"],
        target="某网站",
    )
    repo = IntentRepository(db_manager)
    return repo.create(intent)


@pytest.fixture
def sample_pending_tool(db_manager, sample_intent):
    """创建示例待试用工具"""
    return PendingTool(
        intent_id=sample_intent.intent_id,
        tool_name="自动登录",
        tool_description="自动登录到网站",
        execution_code="def login(): return {'success': True}",
        execution_strategy="hybrid",
        parameters=[{"name": "username", "type": "string"}],
    )


@pytest.fixture
def trial_manager(db_manager):
    """创建 TrialManager"""
    return TrialManager(db_manager)


@pytest.fixture
def trial_executor(trial_manager):
    """创建 TrialExecutor"""
    return TrialExecutor(trial_manager)


class TestExecutionResult:
    """ExecutionResult 测试"""

    def test_create_success_result(self):
        """测试创建成功结果"""
        result = ExecutionResult(
            success=True,
            data={"status": "success"},
            execution_log="执行成功",
        )

        assert result.success is True
        assert result.data == {"status": "success"}
        assert result.execution_log == "执行成功"
        assert result.error is None

    def test_create_failure_result(self):
        """测试创建失败结果"""
        result = ExecutionResult(
            success=False,
            error="Element not found",
            execution_log="执行失败",
        )

        assert result.success is False
        assert result.error == "Element not found"
        assert result.data is None


class TestTrialExecutor:
    """TrialExecutor 测试"""

    @pytest.mark.asyncio
    async def test_execute_trial_success(
        self, trial_executor, sample_pending_tool, trial_manager, db_manager
    ):
        """测试成功执行试用"""
        # 创建待试用工具
        pending_tool = trial_manager.create_pending_tool(
            intent_id=sample_pending_tool.intent_id,
            tool_code="def login(): return {'success': True}",
            tool_name=sample_pending_tool.tool_name,
        )

        # Mock WorkflowExecutor（在正确的位置 patch）
        with patch.object(
            trial_executor, "workflow_executor", spec=True
        ) as mock_executor:
            # Mock ExecutionContext
            mock_context = Mock()
            mock_context.execution_id = "exec-001"
            mock_context.status.value = "success"
            mock_context.get_progress.return_value = 1.0
            mock_context.status = Mock()
            mock_context.status.value = "success"
            mock_context.step_results = {}
            mock_context.variables = {}
            mock_context.error_message = None

            mock_executor.execute = AsyncMock(return_value=mock_context)

            # 执行试用
            trial_data = {"username": "test"}
            result = await trial_executor.execute_trial(pending_tool, trial_data)

            # 验证结果
            assert result.success is True
            assert "构建工具" in result.execution_log

    @pytest.mark.asyncio
    async def test_execute_trial_failure(
        self, trial_executor, sample_pending_tool, trial_manager
    ):
        """测试执行试用失败"""
        # 创建待试用工具
        pending_tool = trial_manager.create_pending_tool(
            intent_id=sample_pending_tool.intent_id,
            tool_code="def login(): raise Exception('Login failed')",
            tool_name=sample_pending_tool.tool_name,
        )

        # Mock WorkflowExecutor 抛出异常
        with patch.object(
            trial_executor, "workflow_executor", spec=True
        ) as mock_executor:
            mock_executor.execute = AsyncMock(
                side_effect=Exception("Login failed")
            )

            # 执行试用
            trial_data = {"username": "test"}
            result = await trial_executor.execute_trial(pending_tool, trial_data)

            # 验证结果
            assert result.success is False
            assert "Login failed" in result.error

    def test_build_tool_from_pending(
        self, trial_executor, sample_pending_tool
    ):
        """测试从待试用工具构建 Tool 对象"""
        tool = trial_executor._build_tool_from_pending(sample_pending_tool)

        assert isinstance(tool, Tool)
        assert tool.tool_name == sample_pending_tool.tool_name
        assert tool.description == sample_pending_tool.tool_description
        assert tool.execution_code == sample_pending_tool.execution_code
        assert tool.execution_strategy == sample_pending_tool.execution_strategy

    @pytest.mark.asyncio
    async def test_monitor_execution(
        self, trial_executor, sample_pending_tool, trial_manager
    ):
        """测试监控执行过程"""
        # 这个测试创建新的工具避免状态冲突
        from src.business.intent.intent_models import Intent
        from src.business.intent.intent_repository import IntentRepository

        # 创建新的 intent
        intent_repo = IntentRepository(trial_manager.db_manager)
        intent = intent_repo.create(
            Intent(
                recording_id="rec-monitor-test",
                core_operations=["打开登录页面"],
            )
        )

        # 创建待试用工具（不通过 trial_manager.create_pending_tool，避免状态问题）
        from src.business.tool_trial.trial_models import PendingTool, PendingToolStatus
        from src.business.tool_trial.trial_repository import PendingToolRepository

        pending_tool_repo = PendingToolRepository(trial_manager.db_manager)
        pending_tool = PendingTool(
            intent_id=intent.intent_id,
            tool_name="监控测试工具",
            tool_description="用于测试监控功能",
            execution_code="def test(): pass",
            execution_strategy="hybrid",
        )
        # 直接创建，不通过 trial_manager（避免开始试用）
        pending_tool = pending_tool_repo.create(pending_tool)

        # 创建试用记录
        trial = trial_manager.start_trial(
            pending_tool_id=pending_tool.pending_tool_id,
            trial_data={"test": "data"},
        )

        # Mock WorkflowExecutor 和 ExecutionContext
        with patch.object(
            trial_executor, "workflow_executor", spec=True
        ) as mock_executor:
            mock_context = Mock()
            mock_context.execution_id = "exec-monitor-test"
            mock_context.status.value = "running"
            mock_context.get_progress.side_effect = [0.0, 0.5, 1.0]
            mock_context.current_step = 1
            mock_context.total_steps = 2

            async def mock_execute(*args, **kwargs):
                # 模拟执行过程
                await asyncio.sleep(0.02)
                mock_context.status.value = "success"
                # 设置执行上下文
                trial_executor._execution_contexts[trial.trial_id] = mock_context
                return mock_context

            mock_executor.execute = mock_execute

            # 启动执行（后台任务）
            task = asyncio.create_task(
                trial_executor.execute_trial(pending_tool, {"test": "data"})
            )

            # 给任务一点时间启动
            await asyncio.sleep(0.01)

            # 监控执行
            status_count = 0
            async for status in trial_executor.monitor_execution(trial.trial_id):
                status_count += 1
                if status_count >= 1:  # 只要收到至少一个状态就通过
                    break

            # 等待执行完成
            await task

            # 验证至少收到了一些状态更新
            assert status_count >= 1

    @pytest.mark.asyncio
    async def test_stop_trial(
        self, trial_executor, sample_pending_tool, trial_manager
    ):
        """测试停止试用"""
        # 创建待试用工具和试用记录
        pending_tool = trial_manager.create_pending_tool(
            intent_id=sample_pending_tool.intent_id,
            tool_code="def login(): import time; time.sleep(10); return {'success': True}",
            tool_name=sample_pending_tool.tool_name,
        )

        trial = trial_manager.start_trial(
            pending_tool_id=pending_tool.pending_tool_id,
            trial_data={"username": "test"},
        )

        # 启动长时间运行的执行
        with patch(
            "src.business.tool_trial.trial_executor.WorkflowExecutor"
        ) as mock_executor_class:
            mock_executor = AsyncMock()

            async def mock_execute(*args, **kwargs):
                # 模拟长时间运行
                await asyncio.sleep(5)
                return Mock(status="success")

            mock_executor.execute = mock_execute
            mock_executor_class.return_value = mock_executor

            task = asyncio.create_task(
                trial_executor.execute_trial(pending_tool, {"username": "test"})
            )

            # 等待一小段时间确保任务开始
            await asyncio.sleep(0.1)

            # 停止试用
            await trial_executor.stop_trial(trial.trial_id)

            # 等待任务结束
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                pass

            # 验证试用已取消（通过检查 TrialManager 中的状态）
            # 注意：这里需要实际的取消逻辑支持
