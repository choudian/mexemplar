"""
TrialExecutor 边界条件测试

测试试用执行器的各种边界条件和异常场景
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
import asyncio

from src.business.tool_trial.trial_executor import (
    TrialExecutor,
    ExecutionResult,
    ExecutionStatus,
)
from src.business.tool_trial.trial_models import (
    PendingTool,
    PendingToolStatus,
    ToolTrial,
    TrialStatus,
)
from src.data.models import Tool
from src.execution.code_executor import CodeExecutor


class TestExecutionResultEdgeCases:
    """ExecutionResult 边界测试"""

    def test_execution_result_with_minimal_data(self):
        """测试最小数据的结果"""
        result = ExecutionResult(success=False)

        assert result.success is False
        assert result.data is None
        assert result.error is None
        assert result.execution_log is None
        assert result.duration == 0.0

    def test_execution_result_with_empty_data(self):
        """测试空数据的结果"""
        result = ExecutionResult(
            success=True, data={}, execution_log="", duration=0.0
        )

        assert result.success is True
        assert result.data == {}
        assert result.execution_log == ""

    def test_execution_result_with_large_data(self):
        """测试大数据量的结果"""
        large_data = {f"key_{i}": f"value_{i}" * 100 for i in range(1000)}
        result = ExecutionResult(success=True, data=large_data)

        assert result.success is True
        assert len(result.data) == 1000


class TestExecutionStatusEdgeCases:
    """ExecutionStatus 边界测试"""

    def test_execution_status_with_zero_progress(self):
        """测试零进度"""
        status = ExecutionStatus(
            trial_id="test_id", status="running", progress=0.0
        )

        assert status.progress == 0.0

    def test_execution_status_with_full_progress(self):
        """测试完成进度"""
        status = ExecutionStatus(
            trial_id="test_id", status="completed", progress=1.0
        )

        assert status.progress == 1.0

    def test_execution_status_with_invalid_progress(self):
        """测试无效的进度值"""
        # 超过 1.0 的进度
        status = ExecutionStatus(
            trial_id="test_id", status="running", progress=1.5
        )

        # 注意：这里应该在实际代码中添加验证
        assert status.progress == 1.5

    def test_execution_status_with_negative_progress(self):
        """测试负进度"""
        status = ExecutionStatus(
            trial_id="test_id", status="running", progress=-0.1
        )

        assert status.progress == -0.1

    def test_execution_status_with_zero_steps(self):
        """测试零步骤"""
        status = ExecutionStatus(
            trial_id="test_id",
            status="running",
            progress=0.0,
            current_step=0,
            total_steps=0,
        )

        assert status.current_step == 0
        assert status.total_steps == 0


class TestTrialExecutorEdgeCases:
    """TrialExecutor 边界条件测试"""

    @pytest.fixture
    def executor(self):
        """创建 TrialExecutor 实例"""
        mock_trial_manager = Mock()
        mock_trial_manager.get_trial_by_id = Mock()
        mock_trial_manager.update_trial_status = Mock()

        executor = TrialExecutor(trial_manager=mock_trial_manager)
        return executor

    @pytest.mark.asyncio
    async def test_execute_tool_with_invalid_tool_id(self, executor):
        """测试无效的工具 ID"""
        # Mock 返回 None
        executor.trial_manager.get_trial_by_id.return_value = None

        result = await executor.execute_tool_async("non_existent_id")

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_execute_tool_with_empty_execution_code(self, executor):
        """测试空的执行代码"""
        # 创建一个没有执行代码的工具
        pending_tool = PendingTool(
            pending_tool_id="test_id",
            recording_id="recording_1",
            tool_name="测试工具",
            description="测试工具描述",
            parameters=[],
            execution_code=None,  # 没有执行代码
            execution_strategy=None,
            status=PendingToolStatus.PENDING,
            created_at=0.0,
        )

        trial = ToolTrial(
            trial_id="trial_1",
            pending_tool_id="test_id",
            status=TrialStatus.PENDING,
            test_data={},
            started_at=0.0,
        )

        executor.trial_manager.get_trial_by_id.return_value = (
            trial,
            pending_tool,
            None,
        )

        result = await executor.execute_tool_async("trial_1")

        # 应该失败，因为没有执行代码
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_tool_with_syntax_error_code(self, executor):
        """测试包含语法错误的代码"""
        pending_tool = PendingTool(
            pending_tool_id="test_id",
            recording_id="recording_1",
            tool_name="测试工具",
            description="测试工具描述",
            parameters=[],
            execution_code="def execute_tool():\n    return invalid syntax here",
            execution_strategy="api",
            status=PendingToolStatus.PENDING,
            created_at=0.0,
        )

        trial = ToolTrial(
            trial_id="trial_1",
            pending_tool_id="test_id",
            status=TrialStatus.PENDING,
            test_data={},
            started_at=0.0,
        )

        executor.trial_manager.get_trial_by_id.return_value = (
            trial,
            pending_tool,
            None,
        )

        result = await executor.execute_tool_async("trial_1")

        # 应该失败
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_execute_tool_with_dangerous_code(self, executor):
        """测试包含危险函数的代码"""
        dangerous_code = """
import os
def execute_tool():
    os.system("rm -rf /")  # 危险操作
    return {"result": "deleted"}
"""

        pending_tool = PendingTool(
            pending_tool_id="test_id",
            recording_id="recording_1",
            tool_name="危险工具",
            description="包含危险代码的工具",
            parameters=[],
            execution_code=dangerous_code,
            execution_strategy="api",
            status=PendingToolStatus.PENDING,
            created_at=0.0,
        )

        trial = ToolTrial(
            trial_id="trial_1",
            pending_tool_id="test_id",
            status=TrialStatus.PENDING,
            test_data={},
            started_at=0.0,
        )

        executor.trial_manager.get_trial_by_id.return_value = (
            trial,
            pending_tool,
            None,
        )

        result = await executor.execute_tool_async("trial_1")

        # CodeExecutor 应该阻止危险代码
        assert result.success is False
        assert "dangerous" in result.error.lower() or "not allowed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_tool_with_infinite_loop(self, executor):
        """测试包含无限循环的代码（带超时）"""
        infinite_loop_code = """
def execute_tool():
    result = 0
    while True:  # 无限循环
        result += 1
    return {"result": result}
"""

        pending_tool = PendingTool(
            pending_tool_id="test_id",
            recording_id="recording_1",
            tool_name="无限循环工具",
            description="包含无限循环的工具",
            parameters=[],
            execution_code=infinite_loop_code,
            execution_strategy="api",
            status=PendingToolStatus.PENDING,
            created_at=0.0,
        )

        trial = ToolTrial(
            trial_id="trial_1",
            pending_tool_id="test_id",
            status=TrialStatus.PENDING,
            test_data={},
            started_at=0.0,
        )

        executor.trial_manager.get_trial_by_id.return_value = (
            trial,
            pending_tool,
            None,
        )

        # 应该超时
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                executor.execute_tool_async("trial_1"), timeout=2.0
            )

    @pytest.mark.asyncio
    async def test_execute_tool_with_empty_test_data(self, executor):
        """测试空的测试数据"""
        pending_tool = PendingTool(
            pending_tool_id="test_id",
            recording_id="recording_1",
            tool_name="测试工具",
            description="测试工具描述",
            parameters=[],
            execution_code='def execute_tool():\n    return {"result": "success"}',
            execution_strategy="api",
            status=PendingToolStatus.PENDING,
            created_at=0.0,
        )

        trial = ToolTrial(
            trial_id="trial_1",
            pending_tool_id="test_id",
            status=TrialStatus.PENDING,
            test_data={},  # 空的测试数据
            started_at=0.0,
        )

        executor.trial_manager.get_trial_by_id.return_value = (
            trial,
            pending_tool,
            None,
        )

        result = await executor.execute_tool_async("trial_1")

        # 应该成功执行（使用空参数）
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_tool_with_large_parameters(self, executor):
        """测试大参数"""
        large_params = {f"param_{i}": "x" * 1000 for i in range(100)}

        pending_tool = PendingTool(
            pending_tool_id="test_id",
            recording_id="recording_1",
            tool_name="大参数工具",
            description="接受大参数的工具",
            parameters=[],
            execution_code='def execute_tool(**kwargs):\n    return {"received": len(kwargs)}',
            execution_strategy="api",
            status=PendingToolStatus.PENDING,
            created_at=0.0,
        )

        trial = ToolTrial(
            trial_id="trial_1",
            pending_tool_id="test_id",
            status=TrialStatus.PENDING,
            test_data=large_params,
            started_at=0.0,
        )

        executor.trial_manager.get_trial_by_id.return_value = (
            trial,
            pending_tool,
            None,
        )

        result = await executor.execute_tool_async("trial_1")

        assert result.success is True
        assert result.data["received"] == 100

    @pytest.mark.asyncio
    async def test_execute_tool_concurrently(self, executor):
        """测试并发执行多个工具"""
        # 创建 3 个工具
        tools = []
        trials = []

        for i in range(3):
            pending_tool = PendingTool(
                pending_tool_id=f"tool_{i}",
                recording_id="recording_1",
                tool_name=f"工具{i}",
                description=f"工具{i}描述",
                parameters=[],
                execution_code=f'def execute_tool():\n    return {{"result": "success_{i}"}}',
                execution_strategy="api",
                status=PendingToolStatus.PENDING,
                created_at=0.0,
            )

            trial = ToolTrial(
                trial_id=f"trial_{i}",
                pending_tool_id=f"tool_{i}",
                status=TrialStatus.PENDING,
                test_data={},
                started_at=0.0,
            )

            tools.append(pending_tool)
            trials.append(trial)

        # Mock 返回
        def get_trial_side_effect(trial_id):
            index = int(trial_id.split("_")[1])
            return trials[index], tools[index], None

        executor.trial_manager.get_trial_by_id.side_effect = get_trial_side_effect

        # 并发执行
        results = await asyncio.gather(
            executor.execute_tool_async("trial_0"),
            executor.execute_tool_async("trial_1"),
            executor.execute_tool_async("trial_2"),
        )

        assert len(results) == 3
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_execute_tool_with_exception_in_code(self, executor):
        """测试代码中抛出异常"""
        exception_code = """
def execute_tool():
    raise ValueError("Test exception")
    return {"result": "unreachable"}
"""

        pending_tool = PendingTool(
            pending_tool_id="test_id",
            recording_id="recording_1",
            tool_name="异常工具",
            description="会抛出异常的工具",
            parameters=[],
            execution_code=exception_code,
            execution_strategy="api",
            status=PendingToolStatus.PENDING,
            created_at=0.0,
        )

        trial = ToolTrial(
            trial_id="trial_1",
            pending_tool_id="test_id",
            status=TrialStatus.PENDING,
            test_data={},
            started_at=0.0,
        )

        executor.trial_manager.get_trial_by_id.return_value = (
            trial,
            pending_tool,
            None,
        )

        result = await executor.execute_tool_async("trial_1")

        # 应该捕获异常并返回失败
        assert result.success is False
        assert "exception" in result.error.lower() or "error" in result.error.lower()

    @pytest.mark.asyncio
    async def test_monitor_execution_with_non_existent_trial(self, executor):
        """测试监控不存在的试用"""
        executor.trial_manager.get_trial_by_id.return_value = None

        # 应该不抛出异常，只是返回
        async for status in executor.monitor_execution("non_existent_id"):
            # 不应该到达这里
            assert False, "Should not yield any status"

    @pytest.mark.asyncio
    async def test_execute_tool_with_unicode_parameters(self, executor):
        """测试 Unicode 参数"""
        unicode_params = {
            "emoji": "😀🎉",
            "chinese": "中文测试",
            "japanese": "日本語テスト",
            "special": "©®™℠€",
        }

        pending_tool = PendingTool(
            pending_tool_id="test_id",
            recording_id="recording_1",
            tool_name="Unicode 工具",
            description="测试 Unicode 参数",
            parameters=[],
            execution_code='def execute_tool(**kwargs):\n    return kwargs',
            execution_strategy="api",
            status=PendingToolStatus.PENDING,
            created_at=0.0,
        )

        trial = ToolTrial(
            trial_id="trial_1",
            pending_tool_id="test_id",
            status=TrialStatus.PENDING,
            test_data=unicode_params,
            started_at=0.0,
        )

        executor.trial_manager.get_trial_by_id.return_value = (
            trial,
            pending_tool,
            None,
        )

        result = await executor.execute_tool_async("trial_1")

        assert result.success is True
        assert result.data["emoji"] == "😀🎉"
        assert result.data["chinese"] == "中文测试"
