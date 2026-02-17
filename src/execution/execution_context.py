"""
工作流执行上下文

本模块定义执行上下文数据类，用于封装工作流执行过程中的状态和运行时数据。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from enum import Enum


class ExecutionStatus(Enum):
    """执行状态枚举"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class StepResult:
    """单步执行结果"""

    step_name: str
    step_number: int
    success: bool
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    retry_count: int = 0

    @property
    def duration(self) -> Optional[float]:
        """获取执行时长（秒）"""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


@dataclass
class ExecutionContext:
    """
    工作流执行上下文

    负责存储和管理工作流执行过程中的所有状态和运行时数据。
    包括用户参数、步骤结果、驱动句柄、进度追踪等。
    """

    # 基本信息
    execution_id: str
    tool_id: str
    tool_name: str = ""

    # 执行状态
    status: ExecutionStatus = ExecutionStatus.PENDING

    # 用户提供的参数
    parameters: Dict[str, Any] = field(default_factory=dict)

    # 进度追踪
    current_step: int = 0
    total_steps: int = 0

    # 运行时变量存储（支持步骤间数据传递）
    variables: Dict[str, Any] = field(default_factory=dict)

    # 驱动句柄
    browser_page: Optional[Any] = None  # Playwright Page 对象
    desktop_window: Optional[Any] = None  # pywinauto Window 对象

    # 步骤执行结果（按 step_name 索引）
    step_results: Dict[str, StepResult] = field(default_factory=dict)

    # 时间追踪
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    # 错误信息
    error_message: Optional[str] = None

    # 执行日志
    execution_log: str = ""

    def __post_init__(self):
        """初始化后处理"""
        if isinstance(self.status, str):
            self.status = ExecutionStatus(self.status)

    @property
    def duration(self) -> Optional[float]:
        """获取总执行时长（秒）"""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    @property
    def progress(self) -> float:
        """获取执行进度（0.0 - 1.0）"""
        if self.total_steps == 0:
            return 0.0
        return self.current_step / self.total_steps

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self.status == ExecutionStatus.RUNNING

    @property
    def is_completed(self) -> bool:
        """是否已完成（成功或失败）"""
        return self.status in (
            ExecutionStatus.SUCCESS,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        )

    def start(self):
        """开始执行"""
        self.status = ExecutionStatus.RUNNING
        self.started_at = datetime.now()
        self.log("执行开始")

    def complete(self, success: bool = True, error_message: Optional[str] = None):
        """完成执行"""
        self.finished_at = datetime.now()
        if success:
            self.status = ExecutionStatus.SUCCESS
            self.log("执行成功完成")
        else:
            self.status = ExecutionStatus.FAILED
            self.error_message = error_message
            self.log(f"执行失败: {error_message}")

    def cancel(self):
        """取消执行"""
        self.status = ExecutionStatus.CANCELLED
        self.finished_at = datetime.now()
        self.log("执行已取消")

    def add_step_result(self, result: StepResult):
        """添加步骤执行结果"""
        self.step_results[result.step_name] = result
        self.current_step = result.step_number

    def get_step_result(self, step_name: str) -> Optional[StepResult]:
        """获取指定步骤的执行结果"""
        return self.step_results.get(step_name)

    def get_step_output(self, step_name: str, output_key: str) -> Any:
        """
        获取指定步骤的输出值

        Args:
            step_name: 步骤名称
            output_key: 输出键名

        Returns:
            输出值，如果不存在则返回 None
        """
        result = self.step_results.get(step_name)
        if result and result.result:
            return result.result.get(output_key)
        return None

    def set_variable(self, key: str, value: Any):
        """设置运行时变量"""
        self.variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        """获取运行时变量"""
        return self.variables.get(key, default)

    def log(self, message: str):
        """记录执行日志"""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        self.execution_log += log_entry

    def get_parameter(self, key: str, default: Any = None) -> Any:
        """获取用户提供的参数"""
        return self.parameters.get(key, default)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于数据库存储）"""
        return {
            "execution_id": self.execution_id,
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "status": (
                self.status.value if isinstance(self.status, ExecutionStatus) else self.status
            ),
            "parameters": self.parameters,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "variables": self.variables,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error_message": self.error_message,
            "execution_log": self.execution_log,
            "step_results": {
                name: {
                    "step_name": r.step_name,
                    "step_number": r.step_number,
                    "success": r.success,
                    "result": r.result,
                    "error_message": r.error_message,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "retry_count": r.retry_count,
                    "duration": r.duration,
                }
                for name, r in self.step_results.items()
            },
            "duration": self.duration,
            "progress": self.progress,
        }
