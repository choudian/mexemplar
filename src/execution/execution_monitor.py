"""
执行监控器

本模块负责监控工作流执行进度，并通过事件系统发射执行事件。
"""

from typing import Any, Callable, Dict, Optional
from dataclasses import dataclass
from datetime import datetime

from .execution_context import ExecutionContext, StepResult, ExecutionStatus


@dataclass
class ExecutionEvent:
    """执行事件"""

    event_type: str  # 'started', 'step_completed', 'finished', 'failed', 'cancelled'
    execution_id: str
    tool_id: str
    tool_name: str
    timestamp: datetime
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event_type": self.event_type,
            "execution_id": self.execution_id,
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
        }


class ExecutionMonitor:
    """
    执行监控器

    监控工作流执行进度，并通过事件系统发射事件。
    使用 blinker 库实现事件总线。
    """

    # 定义事件名称
    EVENT_WORKFLOW_STARTED = "workflow_started"
    EVENT_WORKFLOW_STEP_COMPLETED = "workflow_step_completed"
    EVENT_WORKFLOW_STEP_FAILED = "workflow_step_failed"
    EVENT_WORKFLOW_FINISHED = "workflow_finished"
    EVENT_WORKFLOW_FAILED = "workflow_failed"
    EVENT_WORKFLOW_CANCELLED = "workflow_cancelled"
    EVENT_WORKFLOW_PROGRESS = "workflow_progress"

    def __init__(self):
        """初始化执行监控器"""
        self._handlers: Dict[str, list] = {}
        try:
            from blinker import Namespace

            self._signals = Namespace()
            self._started = self._signals.signal(self.EVENT_WORKFLOW_STARTED)
            self._step_completed = self._signals.signal(self.EVENT_WORKFLOW_STEP_COMPLETED)
            self._step_failed = self._signals.signal(self.EVENT_WORKFLOW_STEP_FAILED)
            self._finished = self._signals.signal(self.EVENT_WORKFLOW_FINISHED)
            self._failed = self._signals.signal(self.EVENT_WORKFLOW_FAILED)
            self._cancelled = self._signals.signal(self.EVENT_WORKFLOW_CANCELLED)
            self._progress = self._signals.signal(self.EVENT_WORKFLOW_PROGRESS)
            self._blinker_available = True
        except ImportError:
            # blinker 不可用时使用简单的回调列表
            self._blinker_available = False

    def on_workflow_started(self, handler: Callable[[ExecutionContext], None]):
        """注册工作流开始事件处理器"""
        if self._blinker_available:
            self._started.connect(handler)
        else:
            self._handlers.setdefault(self.EVENT_WORKFLOW_STARTED, []).append(handler)

    def on_step_completed(self, handler: Callable[[ExecutionContext, StepResult], None]):
        """注册步骤完成事件处理器"""
        if self._blinker_available:
            self._step_completed.connect(handler)
        else:
            self._handlers.setdefault(self.EVENT_WORKFLOW_STEP_COMPLETED, []).append(handler)

    def on_step_failed(self, handler: Callable[[ExecutionContext, StepResult], None]):
        """注册步骤失败事件处理器"""
        if self._blinker_available:
            self._step_failed.connect(handler)
        else:
            self._handlers.setdefault(self.EVENT_WORKFLOW_STEP_FAILED, []).append(handler)

    def on_workflow_finished(self, handler: Callable[[ExecutionContext], None]):
        """注册工作流完成事件处理器"""
        if self._blinker_available:
            self._finished.connect(handler)
        else:
            self._handlers.setdefault(self.EVENT_WORKFLOW_FINISHED, []).append(handler)

    def on_workflow_failed(self, handler: Callable[[ExecutionContext], None]):
        """注册工作流失败事件处理器"""
        if self._blinker_available:
            self._failed.connect(handler)
        else:
            self._handlers.setdefault(self.EVENT_WORKFLOW_FAILED, []).append(handler)

    def on_workflow_cancelled(self, handler: Callable[[ExecutionContext], None]):
        """注册工作流取消事件处理器"""
        if self._blinker_available:
            self._cancelled.connect(handler)
        else:
            self._handlers.setdefault(self.EVENT_WORKFLOW_CANCELLED, []).append(handler)

    def on_progress(self, handler: Callable[[ExecutionContext], None]):
        """注册进度更新事件处理器"""
        if self._blinker_available:
            self._progress.connect(handler)
        else:
            self._handlers.setdefault(self.EVENT_WORKFLOW_PROGRESS, []).append(handler)

    def emit_workflow_started(self, context: ExecutionContext):
        """发射工作流开始事件"""
        event = ExecutionEvent(
            event_type=self.EVENT_WORKFLOW_STARTED,
            execution_id=context.execution_id,
            tool_id=context.tool_id,
            tool_name=context.tool_name,
            timestamp=datetime.now(),
            data={"total_steps": context.total_steps, "parameters": context.parameters},
        )
        self._emit(event)

    def emit_step_completed(self, context: ExecutionContext, step_result: StepResult):
        """发射步骤完成事件"""
        event = ExecutionEvent(
            event_type=self.EVENT_WORKFLOW_STEP_COMPLETED,
            execution_id=context.execution_id,
            tool_id=context.tool_id,
            tool_name=context.tool_name,
            timestamp=datetime.now(),
            data={
                "step_name": step_result.step_name,
                "step_number": step_result.step_number,
                "success": step_result.success,
                "result": step_result.result,
                "duration": step_result.duration,
                "retry_count": step_result.retry_count,
                "progress": context.progress,
            },
        )
        self._emit(event)

    def emit_step_failed(self, context: ExecutionContext, step_result: StepResult):
        """发射步骤失败事件"""
        event = ExecutionEvent(
            event_type=self.EVENT_WORKFLOW_STEP_FAILED,
            execution_id=context.execution_id,
            tool_id=context.tool_id,
            tool_name=context.tool_name,
            timestamp=datetime.now(),
            data={
                "step_name": step_result.step_name,
                "step_number": step_result.step_number,
                "error_message": step_result.error_message,
                "retry_count": step_result.retry_count,
                "progress": context.progress,
            },
        )
        self._emit(event)

    def emit_workflow_finished(self, context: ExecutionContext):
        """发射工作流完成事件"""
        event = ExecutionEvent(
            event_type=self.EVENT_WORKFLOW_FINISHED,
            execution_id=context.execution_id,
            tool_id=context.tool_id,
            tool_name=context.tool_name,
            timestamp=datetime.now(),
            data={
                "status": (
                    context.status.value
                    if isinstance(context.status, ExecutionStatus)
                    else context.status
                ),
                "duration": context.duration,
                "total_steps": context.total_steps,
                "successful_steps": sum(1 for r in context.step_results.values() if r.success),
                "failed_steps": sum(1 for r in context.step_results.values() if not r.success),
            },
        )
        self._emit(event)

    def emit_workflow_failed(self, context: ExecutionContext):
        """发射工作流失败事件"""
        event = ExecutionEvent(
            event_type=self.EVENT_WORKFLOW_FAILED,
            execution_id=context.execution_id,
            tool_id=context.tool_id,
            tool_name=context.tool_name,
            timestamp=datetime.now(),
            data={
                "error_message": context.error_message,
                "duration": context.duration,
                "total_steps": context.total_steps,
                "completed_steps": context.current_step,
            },
        )
        self._emit(event)

    def emit_workflow_cancelled(self, context: ExecutionContext):
        """发射工作流取消事件"""
        event = ExecutionEvent(
            event_type=self.EVENT_WORKFLOW_CANCELLED,
            execution_id=context.execution_id,
            tool_id=context.tool_id,
            tool_name=context.tool_name,
            timestamp=datetime.now(),
            data={
                "duration": context.duration,
                "completed_steps": context.current_step,
            },
        )
        self._emit(event)

    def emit_progress(self, context: ExecutionContext):
        """发射进度更新事件"""
        event = ExecutionEvent(
            event_type=self.EVENT_WORKFLOW_PROGRESS,
            execution_id=context.execution_id,
            tool_id=context.tool_id,
            tool_name=context.tool_name,
            timestamp=datetime.now(),
            data={
                "current_step": context.current_step,
                "total_steps": context.total_steps,
                "progress": context.progress,
            },
        )
        self._emit(event)

    def _emit(self, event: ExecutionEvent):
        """发射事件（内部方法）"""
        if self._blinker_available:
            # 使用 blinker 发射事件
            if event.event_type == self.EVENT_WORKFLOW_STARTED:
                self._started.send(event)
            elif event.event_type == self.EVENT_WORKFLOW_STEP_COMPLETED:
                self._step_completed.send(event)
            elif event.event_type == self.EVENT_WORKFLOW_STEP_FAILED:
                self._step_failed.send(event)
            elif event.event_type == self.EVENT_WORKFLOW_FINISHED:
                self._finished.send(event)
            elif event.event_type == self.EVENT_WORKFLOW_FAILED:
                self._failed.send(event)
            elif event.event_type == self.EVENT_WORKFLOW_CANCELLED:
                self._cancelled.send(event)
            elif event.event_type == self.EVENT_WORKFLOW_PROGRESS:
                self._progress.send(event)
        else:
            # 使用简单的回调列表
            handlers = self._handlers.get(event.event_type, [])
            for handler in handlers:
                try:
                    handler(event)
                except Exception as e:
                    # 记录错误但不影响其他处理器
                    from src.utils.logger import logger

                    logger.warning(f"事件处理器执行失败: {e}")


# 全局单例
_global_monitor: Optional[ExecutionMonitor] = None


def get_global_monitor() -> ExecutionMonitor:
    """获取全局执行监控器单例"""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = ExecutionMonitor()
    return _global_monitor
