"""
TrialExecutor - 试用执行器

负责执行待试用工具并返回执行结果
"""

import asyncio
import logging
from typing import Dict, Any, AsyncIterator, Optional
from datetime import datetime
from dataclasses import dataclass, field

from src.execution.executor import WorkflowExecutor
from src.execution.execution_context import ExecutionContext
from src.business.tool_trial.trial_models import PendingTool, ToolTrial
from src.business.tool_trial.trial_manager import TrialManager
from src.data.models import Tool
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ExecutionResult:
    """
    执行结果数据类

    Attributes:
        success: 是否成功
        data: 执行结果数据
        error: 错误信息
        execution_log: 执行日志
        duration: 执行时长（秒）
    """

    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_log: Optional[str] = None
    duration: float = 0.0


@dataclass
class ExecutionStatus:
    """
    执行状态数据类

    Attributes:
        trial_id: 试用记录 ID
        status: 执行状态
        progress: 进度（0.0 - 1.0）
        current_step: 当前步骤
        total_steps: 总步骤数
        log_message: 日志消息
        timestamp: 时间戳
    """

    trial_id: str
    status: str
    progress: float = 0.0
    current_step: int = 0
    total_steps: int = 0
    log_message: Optional[str] = None
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())


class TrialExecutor:
    """
    试用执行器

    负责执行待试用工具并返回执行结果。
    采用组合模式，复用现有的 WorkflowExecutor。
    """

    def __init__(self, trial_manager: TrialManager):
        """
        初始化试用执行器

        Args:
            trial_manager: 试用管理器
        """
        self.trial_manager = trial_manager
        self.workflow_executor = WorkflowExecutor()

        # 存储正在执行的任务（trial_id -> asyncio.Task）
        self._running_trials: Dict[str, asyncio.Task] = {}

        # 存储执行上下文（用于监控）
        self._execution_contexts: Dict[str, ExecutionContext] = {}

    def _build_tool_from_pending(self, pending_tool: PendingTool) -> Tool:
        """
        从待试用工具构建 Tool 对象

        Args:
            pending_tool: 待试用工具

        Returns:
            Tool 对象
        """
        # 从 execution_code 生成 steps（简化版）
        # 实际应用中可能需要解析代码或使用预定义的步骤模板
        steps = [
            {
                "name": "execute_code",
                "type": "code_execution",
                "code": pending_tool.execution_code,
                "parameters": pending_tool.parameters,
            }
        ]

        tool = Tool(
            tool_name=pending_tool.tool_name,
            description=pending_tool.tool_description,
            execution_code=pending_tool.execution_code,
            code_language=pending_tool.code_language,
            execution_strategy=pending_tool.execution_strategy,
            parameters=pending_tool.parameters,
            steps=steps,
        )

        logger.debug(f"从待试用工具构建 Tool: {tool.tool_name}")
        return tool

    async def execute_trial(
        self, pending_tool: PendingTool, trial_data: Dict[str, Any]
    ) -> ExecutionResult:
        """
        执行工具试用

        Args:
            pending_tool: 待试用工具
            trial_data: 试用数据

        Returns:
            执行结果
        """
        start_time = datetime.now()
        execution_log_parts = []
        trial = None

        try:
            # 1. 构建 Tool 对象
            tool = self._build_tool_from_pending(pending_tool)
            execution_log_parts.append(f"构建工具: {tool.tool_name}")

            # 2. 创建试用记录
            trial = self.trial_manager.start_trial(
                pending_tool_id=pending_tool.pending_tool_id,
                trial_data=trial_data,
            )
            execution_log_parts.append(f"创建试用记录: {trial.trial_id}")

            # 3. 执行工作流
            logger.info(f"开始执行试用: {pending_tool.tool_name} ({trial.trial_id})")

            context = await self.workflow_executor.execute(
                tool=tool,
                parameters=trial_data,
                execution_id=trial.trial_id,
            )

            # 保存执行上下文（用于监控）
            self._execution_contexts[trial.trial_id] = context

            # 4. 收集执行结果
            execution_log_parts.append(f"执行状态: {context.status.value}")

            if context.status.value == "success":
                # 执行成功
                result_data = {
                    "execution_id": context.execution_id,
                    "tool_id": tool.tool_id,
                    "step_results": {
                        name: {
                            "success": result.success,
                            "result": result.result,
                            "error": result.error_message,
                        }
                        for name, result in context.step_results.items()
                    },
                    "variables": context.variables,
                }

                # 处理试用结果
                self.trial_manager.handle_trial_result(
                    trial_id=trial.trial_id,
                    result=result_data,
                    success=True,
                )

                duration = (datetime.now() - start_time).total_seconds()
                execution_log = "\n".join(execution_log_parts)

                logger.info(f"试用执行成功: {trial.trial_id}, 耗时: {duration:.2f}秒")

                return ExecutionResult(
                    success=True,
                    data=result_data,
                    execution_log=execution_log,
                    duration=duration,
                )

            else:
                # 执行失败
                error_message = context.error_message or "执行失败"

                # 处理试用结果
                self.trial_manager.handle_trial_result(
                    trial_id=trial.trial_id,
                    error=error_message,
                    success=False,
                )

                duration = (datetime.now() - start_time).total_seconds()
                execution_log = "\n".join(execution_log_parts)

                logger.error(f"试用执行失败: {trial.trial_id}, error: {error_message}")

                return ExecutionResult(
                    success=False,
                    error=error_message,
                    execution_log=execution_log,
                    duration=duration,
                )

        except Exception as e:
            # 执行过程中发生异常
            error_message = f"执行异常: {str(e)}"
            execution_log_parts.append(error_message)
            execution_log = "\n".join(execution_log_parts)

            logger.error(f"试用执行异常: {pending_tool.tool_name}", exc_info=True)

            # 尝试处理错误结果（如果有 trial_id）
            if trial is not None:
                try:
                    self.trial_manager.handle_trial_result(
                        trial_id=trial.trial_id,
                        error=error_message,
                        success=False,
                    )
                except Exception as handle_error:
                    logger.error(f"处理试用结果失败: {handle_error}")

            duration = (datetime.now() - start_time).total_seconds()

            return ExecutionResult(
                success=False,
                error=error_message,
                execution_log=execution_log,
                duration=duration,
            )

        finally:
            # 清理执行上下文
            if trial is not None and trial.trial_id in self._execution_contexts:
                del self._execution_contexts[trial.trial_id]

    async def monitor_execution(
        self, trial_id: str
    ) -> AsyncIterator[ExecutionStatus]:
        """
        监控执行过程

        Args:
            trial_id: 试用记录 ID

        Yields:
            执行状态
        """
        # 等待执行上下文可用
        max_wait = 5  # 最多等待 5 秒
        wait_interval = 0.1
        waited = 0

        while trial_id not in self._execution_contexts and waited < max_wait:
            await asyncio.sleep(wait_interval)
            waited += wait_interval

        if trial_id not in self._execution_contexts:
            logger.warning(f"执行上下文未找到: {trial_id}")
            return

        context = self._execution_contexts[trial_id]

        # 定期发送状态更新
        while context.status.value in ["pending", "running"]:
            # 获取进度
            progress = context.get_progress()

            # 创建状态对象
            status = ExecutionStatus(
                trial_id=trial_id,
                status=context.status.value,
                progress=progress,
                current_step=context.current_step,
                total_steps=context.total_steps,
                log_message=f"执行步骤 {context.current_step}/{context.total_steps}",
            )

            yield status

            # 等待一段时间再检查
            await asyncio.sleep(0.5)

        # 发送最终状态
        final_status = ExecutionStatus(
            trial_id=trial_id,
            status=context.status.value,
            progress=context.get_progress(),
            current_step=context.current_step,
            total_steps=context.total_steps,
            log_message="执行完成"
            if context.status.value == "success"
            else "执行失败",
        )

        yield final_status

    async def stop_trial(self, trial_id: str):
        """
        停止试用执行

        Args:
            trial_id: 试用记录 ID

        Note:
            此功能的完整实现需要在 WorkflowExecutor 中支持取消操作
            当前版本仅记录日志
        """
        logger.info(f"请求停止试用: {trial_id}")

        # TODO: 实现真正的取消逻辑
        # 可能需要：
        # 1. 在 WorkflowExecutor 中添加取消方法
        # 2. 使用 asyncio.Event 或 CancellationToken
        # 3. 清理资源（关闭浏览器等）

        # 临时方案：更新试用状态为已取消
        try:
            trial = self.trial_manager.get_trial(trial_id)
            if trial and trial.status.value == "running":
                # 注意：这里只是标记，真正的停止需要 WorkflowExecutor 支持
                logger.warning(
                    f"试用 {trial_id} 停止请求已记录，"
                    f"但完整的取消功能尚未实现"
                )
        except Exception as e:
            logger.error(f"停止试用时出错: {e}")

    def get_running_trials(self) -> list[str]:
        """
        获取正在运行的试用 ID 列表

        Returns:
            正在运行的试用 ID 列表
        """
        return list(self._running_trials.keys())

    def get_execution_context(self, trial_id: str) -> Optional[ExecutionContext]:
        """
        获取执行上下文

        Args:
            trial_id: 试用记录 ID

        Returns:
            执行上下文，如果不存在则返回 None
        """
        return self._execution_contexts.get(trial_id)
