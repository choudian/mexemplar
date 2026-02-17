"""
执行上下文单元测试
"""

import pytest
from datetime import datetime, timedelta
from src.execution.execution_context import ExecutionContext, ExecutionStatus, StepResult


class TestExecutionContext:
    """执行上下文测试类"""

    def test_create_context(self):
        """测试创建执行上下文"""
        context = ExecutionContext(execution_id="test-1", tool_id="tool-1", tool_name="测试工具")

        assert context.execution_id == "test-1"
        assert context.tool_id == "tool-1"
        assert context.tool_name == "测试工具"
        assert context.status == ExecutionStatus.PENDING
        assert context.current_step == 0
        assert context.total_steps == 0

    def test_start_execution(self):
        """测试开始执行"""
        context = ExecutionContext(execution_id="test-1", tool_id="tool-1", tool_name="测试工具")

        context.start()

        assert context.status == ExecutionStatus.RUNNING
        assert context.started_at is not None
        assert context.is_running
        assert not context.is_completed

    def test_complete_success(self):
        """测试成功完成"""
        context = ExecutionContext(execution_id="test-1", tool_id="tool-1", tool_name="测试工具")

        context.start()
        context.complete(success=True)

        assert context.status == ExecutionStatus.SUCCESS
        assert context.finished_at is not None
        assert context.is_completed
        assert not context.is_running

    def test_complete_failure(self):
        """测试失败完成"""
        context = ExecutionContext(execution_id="test-1", tool_id="tool-1", tool_name="测试工具")

        context.start()
        context.complete(success=False, error_message="测试错误")

        assert context.status == ExecutionStatus.FAILED
        assert context.error_message == "测试错误"
        assert context.is_completed

    def test_cancel(self):
        """测试取消执行"""
        context = ExecutionContext(execution_id="test-1", tool_id="tool-1", tool_name="测试工具")

        context.start()
        context.cancel()

        assert context.status == ExecutionStatus.CANCELLED
        assert context.finished_at is not None
        assert context.is_completed

    def test_duration(self):
        """测试执行时长计算"""
        context = ExecutionContext(execution_id="test-1", tool_id="tool-1", tool_name="测试工具")

        context.start()
        # 模拟执行时间
        context.started_at = datetime.now() - timedelta(seconds=5)
        context.complete(success=True)

        # duration 应该接近 5 秒
        assert context.duration is not None
        assert abs(context.duration - 5.0) < 0.1

    def test_progress(self):
        """测试执行进度计算"""
        context = ExecutionContext(
            execution_id="test-1", tool_id="tool-1", tool_name="测试工具", total_steps=10
        )

        assert context.progress == 0.0

        context.current_step = 5
        assert context.progress == 0.5

        context.current_step = 10
        assert context.progress == 1.0

    def test_progress_zero_steps(self):
        """测试无步骤时的进度"""
        context = ExecutionContext(
            execution_id="test-1", tool_id="tool-1", tool_name="测试工具", total_steps=0
        )

        assert context.progress == 0.0

    def test_add_step_result(self):
        """测试添加步骤结果"""
        context = ExecutionContext(execution_id="test-1", tool_id="tool-1", tool_name="测试工具")

        step_result = StepResult(step_name="step1", step_number=1, success=True)

        context.add_step_result(step_result)

        assert context.current_step == 1
        assert context.get_step_result("step1") == step_result

    def test_get_step_output(self):
        """测试获取步骤输出"""
        context = ExecutionContext(execution_id="test-1", tool_id="tool-1", tool_name="测试工具")

        step_result = StepResult(
            step_name="step1", step_number=1, success=True, result={"price": "99.99"}
        )

        context.add_step_result(step_result)

        assert context.get_step_output("step1", "price") == "99.99"
        assert context.get_step_output("step1", "unknown") is None
        assert context.get_step_output("unknown_step", "output") is None

    def test_variables(self):
        """测试变量管理"""
        context = ExecutionContext(execution_id="test-1", tool_id="tool-1", tool_name="测试工具")

        context.set_variable("var1", "value1")
        context.set_variable("var2", 123)

        assert context.get_variable("var1") == "value1"
        assert context.get_variable("var2") == 123
        assert context.get_variable("unknown") is None
        assert context.get_variable("unknown", "default") == "default"

    def test_parameters(self):
        """测试参数获取"""
        context = ExecutionContext(
            execution_id="test-1",
            tool_id="tool-1",
            tool_name="测试工具",
            parameters={"param1": "value1", "param2": 100},
        )

        assert context.get_parameter("param1") == "value1"
        assert context.get_parameter("param2") == 100
        assert context.get_parameter("unknown") is None
        assert context.get_parameter("unknown", "default") == "default"

    def test_log(self):
        """测试日志记录"""
        context = ExecutionContext(execution_id="test-1", tool_id="tool-1", tool_name="测试工具")

        context.log("测试消息1")
        context.log("测试消息2")

        assert "测试消息1" in context.execution_log
        assert "测试消息2" in context.execution_log

    def test_to_dict(self):
        """测试转换为字典"""
        context = ExecutionContext(
            execution_id="test-1",
            tool_id="tool-1",
            tool_name="测试工具",
            parameters={"param1": "value1"},
        )

        context.start()
        context.set_variable("var1", "value1")

        step_result = StepResult(step_name="step1", step_number=1, success=True)
        context.add_step_result(step_result)

        data = context.to_dict()

        assert data["execution_id"] == "test-1"
        assert data["tool_id"] == "tool-1"
        assert data["status"] == "running"
        assert data["parameters"] == {"param1": "value1"}
        assert data["variables"] == {"var1": "value1"}
        assert "step_results" in data


class TestStepResult:
    """步骤结果测试类"""

    def test_create_step_result(self):
        """测试创建步骤结果"""
        result = StepResult(step_name="step1", step_number=1, success=True)

        assert result.step_name == "step1"
        assert result.step_number == 1
        assert result.success
        assert result.error_message is None
        assert result.retry_count == 0

    def test_step_result_duration(self):
        """测试步骤执行时长"""
        result = StepResult(step_name="step1", step_number=1, success=True)

        now = datetime.now()
        result.started_at = now - timedelta(seconds=2)
        result.finished_at = now

        # duration 应该接近 2 秒
        assert result.duration is not None
        assert abs(result.duration - 2.0) < 0.1

    def test_step_result_duration_no_times(self):
        """测试无时间信息时的时长"""
        result = StepResult(step_name="step1", step_number=1, success=True)

        assert result.duration is None

    def test_step_result_with_output(self):
        """测试带输出的步骤结果"""
        result = StepResult(
            step_name="step1",
            step_number=1,
            success=True,
            result={"price": "99.99", "quantity": 10},
        )

        assert result.result == {"price": "99.99", "quantity": 10}

    def test_step_result_with_error(self):
        """测试带错误的步骤结果"""
        result = StepResult(
            step_name="step1", step_number=1, success=False, error_message="元素定位失败"
        )

        assert not result.success
        assert result.error_message == "元素定位失败"
