"""
数据模型定义

定义数据库表的Python模型类
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime
import json
import uuid


@dataclass
class Tool:
    """工具定义模型"""

    tool_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = ""
    description: Optional[str] = None
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)

    # ⭐ 新增：代码执行相关字段
    execution_code: Optional[str] = None  # LLM 生成的可执行代码
    code_language: str = "python"  # 代码语言
    code_version: str = "1.0"  # 代码版本
    execution_strategy: Optional[str] = None  # 执行策略（api, browser, hybrid）

    # ⭐ 新增：意图和试用相关字段
    source_intent_id: Optional[str] = None  # 来源意图 ID
    source: str = "manual"  # 来源：manual（手动创建）, intent（意图生成）, trial（试用转化）
    trial_count: int = 0  # 试用次数（记录从生成到入库的试用次数）
    pending_tool_id: Optional[str] = None  # 来源待试用工具 ID

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "description": self.description,
            "parameters": self.parameters,
            "steps": self.steps,
            # ⭐ 新增字段
            "execution_code": self.execution_code,
            "code_language": self.code_language,
            "code_version": self.code_version,
            "execution_strategy": self.execution_strategy,
            # ⭐ 意图和试用相关字段
            "source_intent_id": self.source_intent_id,
            "source": self.source,
            "trial_count": self.trial_count,
            "pending_tool_id": self.pending_tool_id,
            # 时间戳
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Tool":
        """从字典创建"""
        # 解析JSON字符串
        parameters = data.get("parameters", [])
        if isinstance(parameters, str):
            parameters = json.loads(parameters)

        steps = data.get("steps", [])
        if isinstance(steps, str):
            steps = json.loads(steps)

        return cls(
            tool_id=data["tool_id"],
            tool_name=data["tool_name"],
            description=data.get("description"),
            parameters=parameters,
            steps=steps,
            # ⭐ 新增字段
            execution_code=data.get("execution_code"),
            code_language=data.get("code_language", "python"),
            code_version=data.get("code_version", "1.0"),
            execution_strategy=data.get("execution_strategy"),
            # ⭐ 意图和试用相关字段
            source_intent_id=data.get("source_intent_id"),
            source=data.get("source", "manual"),
            trial_count=data.get("trial_count", 0),
            pending_tool_id=data.get("pending_tool_id"),
            # 时间戳
            created_at=(
                datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
            ),
            updated_at=(
                datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None
            ),
        )

