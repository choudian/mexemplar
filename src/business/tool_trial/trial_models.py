"""
Tool Trial 数据模型

定义工具试用相关的数据结构
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime
import json
import uuid
from enum import Enum


class PendingToolStatus(str, Enum):
    """待试用工具状态枚举"""
    PENDING_TRIAL = "pending_trial"  # 等待试用
    TRIALING = "trialing"  # 试用中
    TRIAL_SUCCESS = "trial_success"  # 试用成功
    TRIAL_FAILED = "trial_failed"  # 试用失败
    AWAITING_REAL_DATA = "awaiting_real_data"  # 等待真实数据
    PROMOTED = "promoted"  # 已提升为正式工具
    FAILED = "failed"  # 最终失败


class TrialStatus(str, Enum):
    """试用执行状态枚举"""
    RUNNING = "running"  # 执行中
    SUCCESS = "success"  # 成功
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消


@dataclass
class PendingTool:
    """
    待试用工具模型

    表示已生成但尚未确认的工具
    """

    pending_tool_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    intent_id: str = ""  # 关联的意图 ID

    # 工具基本信息
    tool_name: str = ""
    tool_description: Optional[str] = None

    # 代码相关
    execution_code: Optional[str] = None  # LLM 生成的代码
    code_language: str = "python"
    execution_strategy: Optional[str] = None  # api, browser, hybrid

    # 参数定义
    parameters: List[Dict[str, Any]] = field(default_factory=list)

    # 状态管理
    status: PendingToolStatus = PendingToolStatus.PENDING_TRIAL
    trial_count: int = 0  # 试用次数
    max_trials: int = 3  # 最大试用次数

    # 试用结果
    last_trial_result: Optional[str] = None  # 最后一次试用结果
    last_error: Optional[str] = None  # 最后一次错误信息

    # 时间戳
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    promoted_at: Optional[datetime] = None  # 提升为正式工具的时间

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "pending_tool_id": self.pending_tool_id,
            "intent_id": self.intent_id,
            "tool_name": self.tool_name,
            "tool_description": self.tool_description,
            "execution_code": self.execution_code,
            "code_language": self.code_language,
            "execution_strategy": self.execution_strategy,
            "parameters": self.parameters,
            "status": self.status.value if isinstance(self.status, PendingToolStatus) else self.status,
            "trial_count": self.trial_count,
            "max_trials": self.max_trials,
            "last_trial_result": self.last_trial_result,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "promoted_at": self.promoted_at.isoformat() if self.promoted_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PendingTool":
        """从字典创建"""
        # 解析 JSON 字符串
        parameters = data.get("parameters", [])
        if isinstance(parameters, str):
            parameters = json.loads(parameters)

        # 解析状态
        status = data.get("status", PendingToolStatus.PENDING_TRIAL)
        if isinstance(status, str):
            status = PendingToolStatus(status)

        return cls(
            pending_tool_id=data["pending_tool_id"],
            intent_id=data["intent_id"],
            tool_name=data["tool_name"],
            tool_description=data.get("tool_description"),
            execution_code=data.get("execution_code"),
            code_language=data.get("code_language", "python"),
            execution_strategy=data.get("execution_strategy"),
            parameters=parameters,
            status=status,
            trial_count=data.get("trial_count", 0),
            max_trials=data.get("max_trials", 3),
            last_trial_result=data.get("last_trial_result"),
            last_error=data.get("last_error"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            promoted_at=datetime.fromisoformat(data["promoted_at"]) if data.get("promoted_at") else None,
        )

    def can_trial(self) -> bool:
        """是否可以继续试用"""
        return self.trial_count < self.max_trials and self.status in [
            PendingToolStatus.PENDING_TRIAL,
            PendingToolStatus.TRIAL_FAILED,
            PendingToolStatus.AWAITING_REAL_DATA,
        ]

    def increment_trial_count(self):
        """增加试用次数"""
        self.trial_count += 1
        self.updated_at = datetime.now()

    def promote(self):
        """提升为正式工具"""
        self.status = PendingToolStatus.PROMOTED
        self.promoted_at = datetime.now()
        self.updated_at = datetime.now()

    def mark_failed(self):
        """标记为最终失败"""
        self.status = PendingToolStatus.FAILED
        self.updated_at = datetime.now()


@dataclass
class ToolTrial:
    """
    工具试用记录模型

    记录每次工具试用的详细信息
    """

    trial_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pending_tool_id: str = ""  # 关联的待试用工具 ID

    # 试用数据
    trial_data: Dict[str, Any] = field(default_factory=dict)  # 试用时的输入数据

    # 执行结果
    status: TrialStatus = TrialStatus.RUNNING
    result: Optional[Dict[str, Any]] = None  # 执行结果
    error_message: Optional[str] = None  # 错误信息
    error_type: Optional[str] = None  # 错误类型

    # 执行日志
    execution_log: Optional[str] = None  # 执行日志
    execution_steps: List[Dict[str, Any]] = field(default_factory=list)  # 执行步骤详情

    # 自动修复信息
    fix_attempted: bool = False  # 是否尝试自动修复
    fix_successful: bool = False  # 修复是否成功
    fixed_code: Optional[str] = None  # 修复后的代码

    # 时间戳
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "trial_id": self.trial_id,
            "pending_tool_id": self.pending_tool_id,
            "trial_data": self.trial_data,
            "status": self.status.value if isinstance(self.status, TrialStatus) else self.status,
            "result": self.result,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "execution_log": self.execution_log,
            "execution_steps": self.execution_steps,
            "fix_attempted": self.fix_attempted,
            "fix_successful": self.fix_successful,
            "fixed_code": self.fixed_code,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolTrial":
        """从字典创建"""
        # 解析 JSON 字符串
        trial_data = data.get("trial_data", {})
        if isinstance(trial_data, str):
            trial_data = json.loads(trial_data) if trial_data else {}

        result = data.get("result")
        if isinstance(result, str):
            result = json.loads(result) if result else None

        execution_steps = data.get("execution_steps", [])
        if isinstance(execution_steps, str):
            execution_steps = json.loads(execution_steps)

        # 解析状态
        status = data.get("status", TrialStatus.RUNNING)
        if isinstance(status, str):
            status = TrialStatus(status)

        return cls(
            trial_id=data["trial_id"],
            pending_tool_id=data["pending_tool_id"],
            trial_data=trial_data,
            status=status,
            result=result,
            error_message=data.get("error_message"),
            error_type=data.get("error_type"),
            execution_log=data.get("execution_log"),
            execution_steps=execution_steps,
            fix_attempted=data.get("fix_attempted", False),
            fix_successful=data.get("fix_successful", False),
            fixed_code=data.get("fixed_code"),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            finished_at=datetime.fromisoformat(data["finished_at"]) if data.get("finished_at") else None,
        )

    def mark_success(self, result: Dict[str, Any]):
        """标记为成功"""
        self.status = TrialStatus.SUCCESS
        self.result = result
        self.finished_at = datetime.now()

    def mark_failed(self, error_message: str, error_type: Optional[str] = None):
        """标记为失败"""
        self.status = TrialStatus.FAILED
        self.error_message = error_message
        self.error_type = error_type
        self.finished_at = datetime.now()


@dataclass
class TrialDataTemplate:
    """
    试用数据模板模型

    用于存储和管理工具试用的数据模板,可以是模拟数据或真实数据
    """

    template_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pending_tool_id: str = ""  # 关联的待试用工具 ID

    # 模板信息
    template_name: Optional[str] = None  # 模板名称
    template_data: Dict[str, Any] = field(default_factory=dict)  # 模板数据
    is_real_data: bool = False  # 是否为真实数据(False 表示模拟数据)

    # 描述信息
    description: Optional[str] = None  # 模板描述
    data_source: Optional[str] = None  # 数据来源(user_generated, ai_generated, recording)

    # 时间戳
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "template_id": self.template_id,
            "pending_tool_id": self.pending_tool_id,
            "template_name": self.template_name,
            "template_data": json.dumps(self.template_data) if self.template_data else None,
            "is_real_data": 1 if self.is_real_data else 0,
            "description": self.description,
            "data_source": self.data_source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrialDataTemplate":
        """从字典创建"""
        # 解析 JSON 字符串
        template_data = data.get("template_data", {})
        if isinstance(template_data, str):
            template_data = json.loads(template_data) if template_data else {}

        # 解析 is_real_data
        is_real_data = data.get("is_real_data", 0)
        if isinstance(is_real_data, int):
            is_real_data = bool(is_real_data)

        return cls(
            template_id=data["template_id"],
            pending_tool_id=data["pending_tool_id"],
            template_name=data.get("template_name"),
            template_data=template_data,
            is_real_data=is_real_data,
            description=data.get("description"),
            data_source=data.get("data_source"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
        )
