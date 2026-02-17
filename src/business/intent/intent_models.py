"""
Intent 数据模型

定义意图确认相关的数据结构
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime
import json
import uuid
from enum import Enum


class IntentStatus(str, Enum):
    """意图状态枚举"""
    ANALYZING = "analyzing"  # 分析中
    PENDING_CONFIRMATION = "pending_confirmation"  # 等待确认
    CONFIRMED = "confirmed"  # 已确认
    CANCELLED = "cancelled"  # 已取消


@dataclass
class Intent:
    """
    意图模型

    表示从录制数据中提取的用户意图
    """

    intent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recording_id: str = ""  # 关联的录制 ID

    # 核心信息
    core_operations: List[str] = field(default_factory=list)  # 核心操作列表
    target: Optional[str] = None  # 操作目标（网站/应用名称）
    business_scenario: Optional[str] = None  # 业务场景（登录、注册、爬虫等）
    expected_results: List[str] = field(default_factory=list)  # 预期结果列表

    # 状态管理
    status: IntentStatus = IntentStatus.ANALYZING
    confirmed_operations: List[str] = field(default_factory=list)  # 用户确认的操作
    user_message: Optional[str] = None  # 用户补充说明

    # 分析元数据
    analysis_confidence: float = 0.0  # 分析置信度 (0.0 - 1.0)
    llm_model_used: Optional[str] = None  # 使用的 LLM 模型

    # 时间戳
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "intent_id": self.intent_id,
            "recording_id": self.recording_id,
            "core_operations": self.core_operations,
            "target": self.target,
            "business_scenario": self.business_scenario,
            "expected_results": self.expected_results,
            "status": self.status.value if isinstance(self.status, IntentStatus) else self.status,
            "confirmed_operations": self.confirmed_operations,
            "user_message": self.user_message,
            "analysis_confidence": self.analysis_confidence,
            "llm_model_used": self.llm_model_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Intent":
        """从字典创建"""
        # 解析 JSON 字符串
        core_operations = data.get("core_operations", [])
        if isinstance(core_operations, str):
            core_operations = json.loads(core_operations)

        expected_results = data.get("expected_results", [])
        if isinstance(expected_results, str):
            expected_results = json.loads(expected_results)

        confirmed_operations = data.get("confirmed_operations", [])
        if isinstance(confirmed_operations, str):
            confirmed_operations = json.loads(confirmed_operations)

        # 解析状态
        status = data.get("status", IntentStatus.ANALYZING)
        if isinstance(status, str):
            status = IntentStatus(status)

        return cls(
            intent_id=data["intent_id"],
            recording_id=data["recording_id"],
            core_operations=core_operations,
            target=data.get("target"),
            business_scenario=data.get("business_scenario"),
            expected_results=expected_results,
            status=status,
            confirmed_operations=confirmed_operations,
            user_message=data.get("user_message"),
            analysis_confidence=data.get("analysis_confidence", 0.0),
            llm_model_used=data.get("llm_model_used"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            confirmed_at=datetime.fromisoformat(data["confirmed_at"]) if data.get("confirmed_at") else None,
        )

    def confirm(self, confirmed_operations: List[str], user_message: Optional[str] = None):
        """
        确认意图

        Args:
            confirmed_operations: 用户确认的操作列表
            user_message: 用户补充说明
        """
        self.status = IntentStatus.CONFIRMED
        self.confirmed_operations = confirmed_operations
        self.user_message = user_message
        self.updated_at = datetime.now()
        self.confirmed_at = datetime.now()

    def cancel(self):
        """取消意图"""
        self.status = IntentStatus.CANCELLED
        self.updated_at = datetime.now()
