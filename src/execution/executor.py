# ⚠️ TODO: 执行引擎正在开发中（40% 完成）
# 本模块是工作流执行引擎的核心，负责编排整个工作流的执行
# 尚未集成到主工作流中

"""
工作流执行器

本模块是工作流执行引擎的核心，负责编排整个工作流的执行。
"""

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .execution_context import ExecutionContext, ExecutionStatus, StepResult
from .parameter_resolver import ParameterResolver
from .action_executor import ActionExecutor
from .execution_monitor import ExecutionMonitor, get_global_monitor
from ..data.models import Tool
from ..utils.logger import get_logger

logger = get_logger(__name__)


class WorkflowExecutor:
    """
    工作流执行器

    负责编排整个工作流的执行，包括：
    - 初始化执行上下文
    - 管理浏览器/桌面驱动
    - 按顺序执行步骤
    - 处理错误和重试
    - 保存执行记录
    """

    def __init__(self, monitor: Optional[ExecutionMonitor] = None):
        """
        初始化工作流执行器

        Args:
            monitor: 执行监控器，如果为 None 则使用全局监控器
        """
        self.monitor = monitor or get_global_monitor()
        self.parameter_resolver = ParameterResolver()

        # Playwright 相关
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def execute(
        self, tool: Tool, parameters: Dict[str, Any], execution_id: Optional[str] = None
    ) -> ExecutionContext:
        """
        执行工作流（异步版本）

        Args:
            tool: 要执行的工具定义
            parameters: 用户提供的参数
            execution_id: 执行 ID，如果为 None 则自动生成

        Returns:
            ExecutionContext 执行上下文
        """
        # 创建执行上下文
        context = ExecutionContext(
            execution_id=execution_id or str(uuid.uuid4()),
            tool_id=tool.tool_id,
            tool_name=tool.tool_name,
            parameters=parameters,
            total_steps=len(tool.steps),
        )

        # 开始执行
        context.start()
        self.monitor.emit_workflow_started(context)

        try:
            # 初始化浏览器
            await self._initialize_browser(context)

            # 执行步骤
            await self._execute_steps(context, tool.steps, parameters)

            # 完成执行
            context.complete(success=True)
            self.monitor.emit_workflow_finished(context)

        except Exception as e:
            # 执行失败
            error_message = f"执行失败: {str(e)}"
            context.complete(success=False, error_message=error_message)
            self.monitor.emit_workflow_failed(context)
            logger.error(f"工作流执行失败: {e}", exc_info=True)

        finally:
            # 清理资源
            await self._cleanup()

            # 保存执行记录到数据库
            await self._save_execution_record(context)

        return context

    def execute_sync(
        self, tool: Tool, parameters: Dict[str, Any], execution_id: Optional[str] = None
    ) -> ExecutionContext:
        """
        执行工作流（同步包装器）

        Args:
            tool: 要执行的工具定义
            parameters: 用户提供的参数
            execution_id: 执行 ID，如果为 None 则自动生成

        Returns:
            ExecutionContext 执行上下文
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.execute(tool, parameters, execution_id))

    async def _initialize_browser(self, context: ExecutionContext):
        """
        初始化浏览器

        Args:
            context: 执行上下文
        """
        try:
            self._playwright = await async_playwright().start()

            # 启动浏览器（非 headless 模式以便调试）
            self._browser = await self._playwright.chromium.launch(
                headless=False, slow_mo=100  # 稍微减速以便观察
            )

            # 创建上下文
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )

            # 创建页面
            self._page = await self._context.new_page()

            # 设置到上下文
            context.browser_page = self._page

            logger.info("浏览器初始化成功")

        except Exception as e:
            logger.error(f"浏览器初始化失败: {e}")
            raise RuntimeError(f"浏览器初始化失败: {e}")

    async def _execute_steps(
        self, context: ExecutionContext, steps: List[Dict[str, Any]], parameters: Dict[str, Any]
    ):
        """
        执行所有步骤

        Args:
            context: 执行上下文
            steps: 步骤列表
            parameters: 用户参数

        Raises:
            Exception: 步骤执行失败且不允许继续时抛出
        """
        action_executor = ActionExecutor(context)

        for step in steps:
            # 检查是否被取消
            if context.status == ExecutionStatus.CANCELLED:
                context.log("执行已被取消")
                break

            # 解析步骤参数
            resolved_step = self.parameter_resolver.resolve_step(step, context)

            # 执行步骤
            step_result = await action_executor.execute(resolved_step)

            # 保存结果
            context.add_step_result(step_result)

            # 发射事件
            if step_result.success:
                self.monitor.emit_step_completed(context, step_result)
            else:
                self.monitor.emit_step_failed(context, step_result)

            # 发射进度更新
            self.monitor.emit_progress(context)

            # 检查错误处理策略
            error_handling = step.get("error_handling", {})
            on_failure = error_handling.get("on_failure", "abort")

            if not step_result.success and on_failure == "abort":
                raise Exception(f"步骤执行失败: {step_result.error_message}")

    async def _cleanup(self):
        """清理资源"""
        try:
            # 关闭页面
            if self._page:
                await self._page.close()
                self._page = None

            # 关闭上下文
            if self._context:
                await self._context.close()
                self._context = None

            # 关闭浏览器
            if self._browser:
                await self._browser.close()
                self._browser = None

            # 停止 Playwright
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

            logger.info("资源清理完成")

        except Exception as e:
            logger.warning(f"资源清理时出现错误: {e}")

    async def _save_execution_record(self, context: ExecutionContext):
        """
        保存执行记录到数据库

        Args:
            context: 执行上下文
        """
        try:
            from ..data.repositories import TaskExecutionRepository

            repo = TaskExecutionRepository()

            # 构建执行记录
            execution_record = {
                "execution_id": context.execution_id,
                "tool_id": context.tool_id,
                "parameters": context.parameters,
                "status": (
                    context.status.value
                    if isinstance(context.status, ExecutionStatus)
                    else context.status
                ),
                "result": {
                    "step_results": {
                        name: {
                            "success": r.success,
                            "result": r.result,
                            "error_message": r.error_message,
                        }
                        for name, r in context.step_results.items()
                    }
                },
                "error_message": context.error_message,
                "started_at": context.started_at,
                "finished_at": context.finished_at,
                "execution_log": context.execution_log,
            }

            # 保存到数据库
            repo.create(execution_record)

            logger.info(f"执行记录已保存: {context.execution_id}")

        except Exception as e:
            logger.error(f"保存执行记录失败: {e}")

    async def cancel(self, context: ExecutionContext):
        """
        取消正在执行的工作流

        Args:
            context: 执行上下文
        """
        context.cancel()
        self.monitor.emit_workflow_cancelled(context)
        await self._cleanup()


# 便捷函数
async def execute_workflow(
    tool: Tool, parameters: Dict[str, Any], execution_id: Optional[str] = None
) -> ExecutionContext:
    """
    执行工作流的便捷函数

    Args:
        tool: 要执行的工具定义
        parameters: 用户提供的参数
        execution_id: 执行 ID，如果为 None 则自动生成

    Returns:
        ExecutionContext 执行上下文
    """
    executor = WorkflowExecutor()
    return await executor.execute(tool, parameters, execution_id)


def execute_workflow_sync(
    tool: Tool, parameters: Dict[str, Any], execution_id: Optional[str] = None
) -> ExecutionContext:
    """
    执行工作流的便捷函数（同步版本）

    Args:
        tool: 要执行的工具定义
        parameters: 用户提供的参数
        execution_id: 执行 ID，如果为 None 则自动生成

    Returns:
        ExecutionContext 执行上下文
    """
    executor = WorkflowExecutor()
    return executor.execute_sync(tool, parameters, execution_id)
