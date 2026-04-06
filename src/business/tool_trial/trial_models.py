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
