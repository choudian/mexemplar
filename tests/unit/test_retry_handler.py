"""
重试处理器单元测试
"""

import pytest
import asyncio
from src.execution.retry_handler import RetryHandler, RetryConfig, RetryResult


class TestRetryConfig:
    """重试配置测试类"""

    def test_default_config(self):
        """测试默认配置"""
        config = RetryConfig()

        assert config.max_attempts == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.exponential_backoff
        assert config.jitter

    def test_custom_config(self):
        """测试自定义配置"""
        config = RetryConfig(
            max_attempts=5, base_delay=2.0, max_delay=30.0, exponential_backoff=False, jitter=False
        )

        assert config.max_attempts == 5
        assert config.base_delay == 2.0
        assert config.max_delay == 30.0
        assert not config.exponential_backoff
        assert not config.jitter


class TestRetryResult:
    """重试结果测试类"""

    def test_success_result(self):
        """测试成功结果"""
        result = RetryResult(success=True, attempts=1, result="test_result")

        assert result.success
        assert result.attempts == 1
        assert result.result == "test_result"
        assert result.error is None

    def test_failure_result(self):
        """测试失败结果"""
        error = ValueError("测试错误")
        result = RetryResult(success=False, attempts=3, error=error)

        assert not result.success
        assert result.attempts == 3
        assert result.error == error
        assert result.result is None


class TestRetryHandler:
    """重试处理器测试类"""

    @pytest.mark.asyncio
    async def test_successful_operation_no_retry(self):
        """测试一次成功的操作"""
        handler = RetryHandler()

        async def success_operation():
            return "success"

        result = await handler.execute(success_operation)

        assert result.success
        assert result.attempts == 1
        assert result.result == "success"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_operation_fails_all_attempts(self):
        """测试所有尝试都失败"""
        config = RetryConfig(max_attempts=3, base_delay=0.01)
        handler = RetryHandler(config)

        call_count = 0

        async def failing_operation():
            nonlocal call_count
            call_count += 1
            raise ValueError("操作失败")

        result = await handler.execute(failing_operation)

        assert not result.success
        assert result.attempts == 3
        assert result.error is not None
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_operation_succeeds_on_retry(self):
        """测试重试后成功"""
        config = RetryConfig(max_attempts=5, base_delay=0.01)
        handler = RetryHandler(config)

        call_count = 0

        async def eventually_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("暂时失败")
            return "success"

        result = await handler.execute(eventually_success)

        assert result.success
        assert result.attempts == 3
        assert result.result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """测试指数退避延迟计算"""
        config = RetryConfig(max_attempts=5, base_delay=0.1, exponential_backoff=True, jitter=False)
        handler = RetryHandler(config)

        # 计算各次重试的延迟
        delay_1 = handler._calculate_delay(1)  # 第1次重试
        delay_2 = handler._calculate_delay(2)  # 第2次重试
        delay_3 = handler._calculate_delay(3)  # 第3次重试

        # 指数退避：base_delay * 2^(attempt-1)
        # delay_1 = 0.1 * 2^0 = 0.1
        # delay_2 = 0.1 * 2^1 = 0.2
        # delay_3 = 0.1 * 2^2 = 0.4
        assert abs(delay_1 - 0.1) < 0.01
        assert abs(delay_2 - 0.2) < 0.01
        assert abs(delay_3 - 0.4) < 0.01

    @pytest.mark.asyncio
    async def test_linear_backoff(self):
        """测试线性延迟"""
        config = RetryConfig(
            max_attempts=5, base_delay=0.1, exponential_backoff=False, jitter=False
        )
        handler = RetryHandler(config)

        delay_1 = handler._calculate_delay(1)
        delay_2 = handler._calculate_delay(2)
        delay_3 = handler._calculate_delay(3)

        # 线性延迟：始终是 base_delay
        assert abs(delay_1 - 0.1) < 0.01
        assert abs(delay_2 - 0.1) < 0.01
        assert abs(delay_3 - 0.1) < 0.01

    @pytest.mark.asyncio
    async def test_max_delay_limit(self):
        """测试最大延迟限制"""
        config = RetryConfig(
            max_attempts=10, base_delay=10.0, max_delay=2.0, exponential_backoff=True, jitter=False
        )
        handler = RetryHandler(config)

        # 即使计算出的延迟超过 max_delay，也应该被限制
        delay = handler._calculate_delay(5)  # 10.0 * 2^4 = 160.0，但应该被限制为 2.0

        assert delay <= 2.0

    @pytest.mark.asyncio
    async def test_with_timeout_success(self):
        """测试带超时的成功操作"""
        handler = RetryHandler()

        async def quick_operation():
            return "done"

        result = await handler.execute_with_timeout(quick_operation, timeout=5.0)

        assert result.success
        assert result.result == "done"

    @pytest.mark.asyncio
    async def test_with_timeout_failure(self):
        """测试带超时的失败操作"""
        handler = RetryHandler()

        async def slow_operation():
            await asyncio.sleep(10)  # 超过超时时间
            return "done"

        result = await handler.execute_with_timeout(slow_operation, timeout=0.5)

        assert not result.success
        assert isinstance(result.error, TimeoutError)

    @pytest.mark.asyncio
    async def test_pass_arguments(self):
        """测试传递参数"""
        handler = RetryHandler()

        async def operation_with_args(a, b, c=None):
            return {"a": a, "b": b, "c": c}

        result = await handler.execute(operation_with_args, 1, 2, c=3)

        assert result.success
        assert result.result == {"a": 1, "b": 2, "c": 3}

    @pytest.mark.asyncio
    async def test_total_delay_tracking(self):
        """测试总延迟时间追踪"""
        config = RetryConfig(
            max_attempts=3, base_delay=0.05, exponential_backoff=False, jitter=False
        )
        handler = RetryHandler(config)

        async def failing_operation():
            raise ValueError("失败")

        result = await handler.execute(failing_operation)

        assert not result.success
        # 应该有 2 次延迟（第1次失败后延迟，第2次失败后延迟）
        # 每次 0.05 秒
        assert abs(result.total_delay - 0.1) < 0.02

    def test_config_from_step_default(self):
        """测试从步骤提取配置（默认）"""
        step = {"step_name": "test_step"}

        config = RetryHandler.config_from_step(step)

        assert config.max_attempts == 3
        assert config.base_delay == 1.0  # 默认 1000ms 转换为秒

    def test_config_from_step_custom(self):
        """测试从步骤提取配置（自定义）"""
        step = {
            "step_name": "test_step",
            "error_handling": {
                "retry_times": 5,
                "retry_interval": 2000,  # 毫秒
                "max_delay": 30,
                "exponential_backoff": False,
                "jitter": False,
            },
        }

        config = RetryHandler.config_from_step(step)

        assert config.max_attempts == 5
        assert config.base_delay == 2.0  # 2000ms 转换为秒
        assert config.max_delay == 30
        assert not config.exponential_backoff
        assert not config.jitter
