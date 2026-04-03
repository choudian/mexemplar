"""
意图分析数据模型

定义意图分析相关的数据结构
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum
import json


class BusinessScenario(Enum):
    """业务场景类型"""

    AUTH = "auth"  # 用户认证（登录、注册、登出）
    QUERY = "query"  # 数据查询（搜索、筛选、查看详情）
    ENTRY = "entry"  # 数据录入（表单填写、创建记录、上传文件）
    PROCESSING = "processing"  # 数据处理（编辑、删除、导出、批量操作）
    COLLECTION = "collection"  # 数据采集（爬虫、数据抓取、信息收集）
    WORKFLOW = "workflow"  # 流程自动化（多步骤工作流、审批流程）
    OTHER = "other"  # 其他


class ParameterType(Enum):
    """参数类型"""

    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    URL = "url"
    SELECTION = "selection"
    BOOLEAN = "boolean"
    FILE = "file"
    JSON = "json"


@dataclass
class CoreOperation:
    """核心操作"""

    operation: str  # 操作描述
    action_index: int  # 对应的操作索引
    importance: float = 1.0  # 重要性评分（0.0-1.0）
    parameters: Dict[str, Any] = field(default_factory=dict)  # 关键参数

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "operation": self.operation,
            "action_index": self.action_index,
            "importance": self.importance,
            "parameters": self.parameters,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoreOperation":
        """从字典创建"""
        return cls(
            operation=data["operation"],
            action_index=data["action_index"],
            importance=data.get("importance", 1.0),
            parameters=data.get("parameters", {}),
        )


@dataclass
class SuggestedParameter:
    """智能参数"""

    name: str  # 参数名（英文，snake_case）
    type: ParameterType  # 参数类型
    description: str  # 参数说明
    required: bool = True  # 是否必填
    default_value: Any = None  # 默认值
    options: Optional[List[str]] = None  # 可选值（仅 selection 类型）

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "type": self.type.value if isinstance(self.type, ParameterType) else self.type,
            "description": self.description,
            "required": self.required,
            "default_value": self.default_value,
            "options": self.options,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SuggestedParameter":
        """从字典创建"""
        # 处理 type 字段：可能是字符串或枚举
        type_value = data.get("type", "text")
        if isinstance(type_value, str):
            try:
                param_type = ParameterType(type_value)
            except ValueError:
                param_type = ParameterType.TEXT
        else:
            param_type = type_value

        return cls(
            name=data["name"],
            type=param_type,
            description=data["description"],
            required=data.get("required", True),
            default_value=data.get("default_value"),
            options=data.get("options"),
        )


@dataclass
class IntentAnalysisResult:
    """意图分析结果"""

    # 核心信息
    core_operations: List[CoreOperation]  # 核心操作列表
    target: str  # 操作目标（网站/应用名称）
    business_scenario: str  # 业务场景（场景类型 - 说明）
    expected_results: List[str]  # 预期结果列表
    suggested_parameters: List[SuggestedParameter]  # 智能参数列表

    # 元数据
    confidence: float = 0.8  # 置信度（0.0-1.0）
    reasoning: str = ""  # 分析推理过程

    # 关联信息
    recording_id: str = ""  # 录制ID
    status: str = "analyzing"  # 状态（analyzing, pending_confirmation, confirmed）

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "core_operations": [op.to_dict() for op in self.core_operations],
            "target": self.target,
            "business_scenario": self.business_scenario,
            "expected_results": self.expected_results,
            "suggested_parameters": [param.to_dict() for param in self.suggested_parameters],
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "recording_id": self.recording_id,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntentAnalysisResult":
        """从字典创建"""
        # 解析 core_operations
        core_operations = [
            CoreOperation.from_dict(op) for op in data.get("core_operations", [])
        ]

        # 解析 suggested_parameters
        suggested_parameters = [
            SuggestedParameter.from_dict(param) for param in data.get("suggested_parameters", [])
        ]

        return cls(
            core_operations=core_operations,
            target=data.get("target", ""),
            business_scenario=data.get("business_scenario", ""),
            expected_results=data.get("expected_results", []),
            suggested_parameters=suggested_parameters,
            confidence=data.get("confidence", 0.8),
            reasoning=data.get("reasoning", ""),
            recording_id=data.get("recording_id", ""),
            status=data.get("status", "analyzing"),
        )

    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "IntentAnalysisResult":
        """从 JSON 字符串创建"""
        data = json.loads(json_str)
        return cls.from_dict(data)


@dataclass
class IntentConfirmationTurn:
    """意图确认对话轮次"""

    turn_id: str  # 轮次ID
    intent_id: str  # 意图ID
    user_feedback: str  # 用户反馈
    assistant_response: str  # 助手回复
    updated_intent: IntentAnalysisResult  # 更新后的意图
    timestamp: float  # 时间戳

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "turn_id": self.turn_id,
            "intent_id": self.intent_id,
            "user_feedback": self.user_feedback,
            "assistant_response": self.assistant_response,
            "updated_intent": self.updated_intent.to_dict(),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntentConfirmationTurn":
        """从字典创建"""
        updated_intent_data = data.get("updated_intent", {})
        updated_intent = IntentAnalysisResult.from_dict(updated_intent_data)

        return cls(
            turn_id=data["turn_id"],
            intent_id=data["intent_id"],
            user_feedback=data["user_feedback"],
            assistant_response=data["assistant_response"],
            updated_intent=updated_intent,
            timestamp=data["timestamp"],
        )


@dataclass
class Intent:
    """意图实体（数据库模型）"""

    intent_id: str  # 意图ID
    recording_id: str  # 录制ID
    analysis_result: IntentAnalysisResult  # 分析结果

    # 确认流程
    confirmation_turns: List[IntentConfirmationTurn] = field(default_factory=list)
    status: str = "analyzing"  # 状态（analyzing, pending_confirmation, confirmed, failed）
    max_turns: int = 5  # 最大对话轮数

    # 时间戳
    created_at: float = 0.0
    updated_at: float = 0.0
    confirmed_at: Optional[float] = None  # 确认时间

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "intent_id": self.intent_id,
            "recording_id": self.recording_id,
            "analysis_result": self.analysis_result.to_dict(),
            "confirmation_turns": [turn.to_dict() for turn in self.confirmation_turns],
            "status": self.status,
            "max_turns": self.max_turns,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "confirmed_at": self.confirmed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Intent":
        """从字典创建"""
        # 解析 analysis_result
        analysis_result_data = data.get("analysis_result", {})
        analysis_result = IntentAnalysisResult.from_dict(analysis_result_data)

        # 解析 confirmation_turns
        confirmation_turns = [
            IntentConfirmationTurn.from_dict(turn) for turn in data.get("confirmation_turns", [])
        ]

        return cls(
            intent_id=data["intent_id"],
            recording_id=data["recording_id"],
            analysis_result=analysis_result,
            confirmation_turns=confirmation_turns,
            status=data.get("status", "analyzing"),
            max_turns=data.get("max_turns", 5),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
            confirmed_at=data.get("confirmed_at"),
        )

    def add_confirmation_turn(self, turn: IntentConfirmationTurn) -> None:
        """添加确认对话轮次"""
        self.confirmation_turns.append(turn)
        self.updated_at = turn.timestamp

