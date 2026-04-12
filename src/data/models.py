"""
数据模型定义

定义数据库表的Python模型类。

注意：ORM 版本在 src.data.models_sqlite，此 dataclass 主要用于 UI 层的轻量传递。
字段应与 ORM 版本保持同步。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime
import uuid


@dataclass
class Tool:
    """工具定义模型（与 ORM 版本 models_sqlite.Tool 字段同步）"""

    tool_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = ""
    description: Optional[str] = None
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)

    # 代码执行相关字段
    execution_code: Optional[str] = None
    code_language: str = "python"
    code_version: str = "1.0"
    execution_strategy: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)

    # 意图和试用相关字段
    source_intent_id: Optional[str] = None
    source: str = "manual"
    trial_count: int = 0
    pending_tool_id: Optional[str] = None

    # Agent 工作流相关字段
    workflow_id: Optional[str] = None
    trial_success_count: int = 0
    status: str = "pending"

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class SkillCompositionMember:
    """技能组合成员模型"""

    member_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    composition_id: str = ""
    tool_id: str = ""
    selected_order: int = 0
    execution_order: Optional[int] = None
    tool: Optional[Tool] = None
    created_at: Optional[datetime] = None


@dataclass
class SkillComposition:
    """技能组合模型"""

    composition_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    composition_name: str = ""
    description: Optional[str] = None
    applicability: str = ""
    mode: str = "range"
    status: str = "draft"
    assistant_enabled: bool = True
    recommend_order: bool = False
    needs_review: bool = False
    members: List[SkillCompositionMember] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
