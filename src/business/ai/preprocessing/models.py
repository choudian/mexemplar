"""
数据模型

定义预处理相关的数据结构。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class CompressionLevel(Enum):
    """压缩级别枚举"""

    NONE = "none"  # 不压缩
    CONSERVATIVE = "conservative"  # 保守（60-70%压缩率）
    MODERATE = "moderate"  # 适中（70-80%压缩率）
    AGGRESSIVE = "aggressive"  # 激进（80-90%压缩率）


@dataclass
class ProcessedAction:
    """处理后的操作"""

    original_action: Any  # Action 对象
    action_index: int
    is_key_action: bool = True  # 是否为关键操作
    action_category: Optional[str] = None  # 操作分类（navigation、interaction、input、system）
    context: Dict[str, Any] = field(default_factory=dict)  # 上下文信息

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "action_index": self.action_index,
            "is_key_action": self.is_key_action,
            "action_category": self.action_category,
            "context": self.context,
            "original_action": (
                self.original_action.to_dict()
                if hasattr(self.original_action, "to_dict")
                else self.original_action
            ),
        }


@dataclass
class PreprocessingResult:
    """预处理结果（统一版本）"""

    # 基础字段
    actions: List[ProcessedAction]
    recording_mode: str
    key_actions: List[ProcessedAction]
    screenshots: List[str]
    metadata: Dict[str, Any]

    # 分析结果（可选）
    network_analysis: Optional[List[Any]] = None  # List[NetworkRequestAnalysis]
    list_analysis: Optional[List[Any]] = None  # List[ListOperationAnalysis]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "actions": [action.to_dict() for action in self.actions],
            "recording_mode": self.recording_mode,
            "key_actions_count": len(self.key_actions),
            "screenshots_count": len(self.screenshots),
            "metadata": self.metadata,
            "network_analysis": (
                [n.to_dict() if hasattr(n, "to_dict") else n for n in self.network_analysis]
                if self.network_analysis
                else []
            ),
            "list_analysis": (
                [item.to_dict() if hasattr(item, "to_dict") else item for item in self.list_analysis]
                if self.list_analysis
                else []
            ),
        }
