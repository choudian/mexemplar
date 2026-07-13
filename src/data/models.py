"""
数据模型定义

定义数据库表的Python模型类。

注意：ORM 版本在 src.data.models_sqlite，此 dataclass 主要用于 UI 层的轻量传递。
字段应与 ORM 版本保持同步。
"""

from dataclasses import dataclass, field, asdict
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
    is_builtin: bool = False
    is_read_only: bool = False
    trial_supported: bool = True
    members: List[SkillCompositionMember] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# =============================================================================
# 共享工具函数
# =============================================================================

MODE_DISPLAY_TEXT = {"ordered": "顺序型", "range": "范围型"}
"""组合模式到中文显示名的映射"""


def sort_composition_members(
    members: List[SkillCompositionMember],
    mode: str,
) -> List[SkillCompositionMember]:
    """按 mode 排序组合成员。ordered 模式按 execution_order 优先，其余按 selected_order。"""
    if mode == "ordered":
        return sorted(
            members,
            key=lambda m: (
                m.execution_order if m.execution_order is not None else 10**9,
                m.selected_order,
            ),
        )
    return sorted(members, key=lambda m: m.selected_order)


def serialize_tool(tool: Optional[Tool]) -> Optional[dict]:
    """将 Tool dataclass 序列化为 JSON 安全的 dict（datetime 转 ISO 字符串）"""
    if tool is None:
        return None
    d = asdict(tool)
    for key in ("created_at", "updated_at"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = val.isoformat()
    return d
