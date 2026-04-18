"""
Intent 数据模型

定义意图确认相关的数据结构
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from src.utils.timezone import utc_now_naive
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

    def cancel(self):
        """取消意图"""
        self.status = IntentStatus.CANCELLED
        self.updated_at = utc_now_naive()
