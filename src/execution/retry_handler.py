"""
重试和错误处理器

本模块负责处理工作流执行过程中的失败重试和超时管理。
"""

import asyncio
from typing import Any, Callable, Dict, Optional, TypeVar
from dataclasses import dataclass


T = TypeVar("T")


@dataclass
class RetryConfig:
    """重试配置"""

    max_attempts: int = 3  # 最大重试次数（包括首次尝试）
    base_delay: float = 1.0  # 基础延迟（秒）
    max_delay: float = 60.0  # 最大延迟（秒）
    exponential_backoff: bool = True  # 是否使用指数退避
    jitter: bool = True  # 是否添加随机抖动


@dataclass
class RetryResult:
    """重试结果"""

    success: bool
    attempts: int  # 实际尝试次数
    result: Optional[T] = None
    error: Optional[Exception] = None
    total_delay: float = 0.0  # 总延迟时间


class RetryHandler:
    """
    重试处理器

    提供带重试机制的异步操作执行，支持指数退避和随机抖动。
    """

    def __init__(self, config: Optional[RetryConfig] = None):
        """
        初始化重试处理器

        Args:
            config: 重试配置，如果为 None 则使用默认配置
        """
        self.config = config or RetryConfig()

    async def execute(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> RetryResult:
        """
        执行带重试的异步操作

        Args:
            func: 要执行的异步函数
            *args: 函数位置参数
            **kwargs: 函数关键字参数

        Returns:
            RetryResult 包含执行结果
        """
        attempts = 0
        last_error: Optional[Exception] = None
        total_delay = 0.0

        while attempts < self.config.max_attempts:
            attempts += 1

            try:
                result = await func(*args, **kwargs)
                return RetryResult(
                    success=True, attempts=attempts, result=result, total_delay=total_delay
                )
            except Exception as e:
                last_error = e

                # 如果是最后一次尝试，不再等待
                if attempts >= self.config.max_attempts:
                    break

                # 计算延迟时间
                delay = self._calculate_delay(attempts)
                total_delay += delay

                # 等待后重试
                await asyncio.sleep(delay)

        # 所有尝试都失败
        return RetryResult(
            success=False, attempts=attempts, error=last_error, total_delay=total_delay
        )

    def _calculate_delay(self, attempt: int) -> float:
        """
        计算延迟时间（支持指数退避和随机抖动）

        Args:
            attempt: 当前尝试次数（从 1 开始）

        Returns:
            延迟时间（秒）
        """
        import random

        # 计算基础延迟
        if self.config.exponential_backoff:
            # 指数退避：base_delay * 2^(attempt-1)
            delay = self.config.base_delay * (2 ** (attempt - 1))
        else:
            delay = self.config.base_delay

        # 限制最大延迟
        delay = min(delay, self.config.max_delay)

        # 添加随机抖动（±25%）
        if self.config.jitter:
            jitter = delay * 0.25 * (random.random() * 2 - 1)
            delay += jitter

        # 确保延迟不为负
        return max(0, delay)

    async def execute_with_timeout(
        self, func: Callable[..., T], timeout: float, *args: Any, **kwargs: Any
    ) -> RetryResult:
        """
        执行带超时的异步操作

        Args:
            func: 要执行的异步函数
            timeout: 超时时间（秒）
            *args: 函数位置参数
            **kwargs: 函数关键字参数

        Returns:
            RetryResult 包含执行结果
        """
        try:
            result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
            return RetryResult(success=True, attempts=1, result=result)
        except asyncio.TimeoutError:
            return RetryResult(
                success=False, attempts=1, error=TimeoutError(f"操作超时（{timeout}秒）")
            )
        except Exception as e:
            return RetryResult(success=False, attempts=1, error=e)

    @staticmethod
    def config_from_step(step: Dict[str, Any]) -> RetryConfig:
        """
        从步骤定义中提取重试配置

        Args:
            step: 步骤定义（可能包含 error_handling 字段）

        Returns:
            RetryConfig 重试配置
        """
        error_handling = step.get("error_handling", {})

        return RetryConfig(
            max_attempts=error_handling.get("retry_times", 3),
            base_delay=error_handling.get("retry_interval", 1000) / 1000,  # 毫秒转秒
            max_delay=error_handling.get("max_delay", 60),
            exponential_backoff=error_handling.get("exponential_backoff", True),
            jitter=error_handling.get("jitter", True),
        )
