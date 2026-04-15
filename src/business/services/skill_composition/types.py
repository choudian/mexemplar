"""Shared types for skill composition services."""

from dataclasses import dataclass
from typing import Optional


class SkillCompositionError(ValueError):
    """技能组合业务异常"""


@dataclass
class SkillCompositionTrialResult:
    """技能组合试用结果"""

    success: bool
    reply: str
    result_type: str
    error: Optional[str] = None
    session_id: Optional[str] = None


@dataclass
class SkillCompositionTrialSessionStart:
    """技能组合对话式试用会话初始化结果"""

    composition_id: str
    composition_name: str
    session_id: str
