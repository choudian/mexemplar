"""
WebSocket 消息类型定义
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
import json
import uuid


class MessageType(str, Enum):
    """WebSocket 消息类型枚举"""

    # Intent 相关
    ANALYZE_INTENT = "analyze_intent"
    INTENT_ANALYZED = "intent_analyzed"
    CONFIRM_INTENT = "confirm_intent"
    INTENT_UPDATED = "intent_updated"
    INTENT_CONFIRMED = "intent_confirmed"

    # Trial 相关
    START_TRIAL = "start_trial"
    TRIAL_STATUS_UPDATE = "trial_status_update"
    TRIAL_COMPLETED = "trial_completed"
    STOP_TRIAL = "stop_trial"

    # Pending Tool 相关
    GET_PENDING_TOOLS = "get_pending_tools"
    PENDING_TOOLS_LIST = "pending_tools_list"
    UPDATE_PENDING_TOOL = "update_pending_tool"
    DELETE_PENDING_TOOL = "delete_pending_tool"
    PENDING_TOOL_UPDATED = "pending_tool_updated"
    PENDING_TOOL_DELETED = "pending_tool_deleted"
    PROMOTE_PENDING_TOOL = "promote_pending_tool"
    PENDING_TOOL_PROMOTED = "pending_tool_promoted"

    # Published Tool 相关
    GET_PUBLISHED_TOOLS = "get_published_tools"
    PUBLISHED_TOOLS_LIST = "published_tools_list"
    DELETE_PUBLISHED_TOOL = "delete_published_tool"
    PUBLISHED_TOOL_DELETED = "published_tool_deleted"
    EXECUTE_TOOL = "execute_tool"
    TOOL_EXECUTION_STARTED = "tool_execution_started"

    # 系统相关
    PING = "ping"
    PONG = "pong"
    ACK = "ack"  # 消息确认
    ERROR = "error"

    # 连接管理
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    RECONNECT = "reconnect"


@dataclass
class WebSocketMessage:
    """
    WebSocket 消息数据类

    Attributes:
        type: 消息类型
        data: 消息数据
        request_id: 请求 ID（用于请求-响应匹配）
        timestamp: 时间戳
        status: 状态（success, error, pending）
        error: 错误信息（如果 status 为 error）
    """

    type: MessageType
    data: Dict[str, Any]
    request_id: Optional[str] = None
    timestamp: float = field(default_factory=lambda: __import__('time').time())
    status: str = "success"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "type": self.type.value if isinstance(self.type, MessageType) else self.type,
            "data": self.data,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "status": self.status,
            "error": self.error,
        }

    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebSocketMessage":
        """从字典创建"""
        msg_type = data.get("type")
        if isinstance(msg_type, str):
            try:
                msg_type = MessageType(msg_type)
            except ValueError:
                # 如果不是有效的 MessageType，保持原样
                pass

        return cls(
            type=msg_type,
            data=data.get("data", {}),
            request_id=data.get("request_id"),
            timestamp=data.get("timestamp"),
            status=data.get("status", "success"),
            error=data.get("error"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "WebSocketMessage":
        """从 JSON 字符串创建"""
        data = json.loads(json_str)
        return cls.from_dict(data)

    @staticmethod
    def create_request(
        msg_type: MessageType, data: Dict[str, Any]
    ) -> "WebSocketMessage":
        """创建请求消息（自动生成 request_id）"""
        return WebSocketMessage(
            type=msg_type,
            data=data,
            request_id=str(uuid.uuid4()),
            status="pending",
        )

    @staticmethod
    def create_response(
        request: "WebSocketMessage", data: Dict[str, Any], success: bool = True
    ) -> "WebSocketMessage":
        """创建响应消息"""
        return WebSocketMessage(
            type=request.type,
            data=data,
            request_id=request.request_id,
            status="success" if success else "error",
        )

    @staticmethod
    def create_error(
        request: Optional["WebSocketMessage"], error_message: str
    ) -> "WebSocketMessage":
        """创建错误消息"""
        return WebSocketMessage(
            type=MessageType.ERROR,
            data={"error": error_message},
            request_id=request.request_id if request else None,
            status="error",
            error=error_message,
        )


@dataclass
class TrialStatusUpdate:
    """试用状态更新数据"""

    trial_id: str
    status: str  # running, success, failed, cancelled
    progress: float = 0.0  # 0.0 - 1.0
    current_step: Optional[str] = None
    log_message: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "trial_id": self.trial_id,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step,
            "log_message": self.log_message,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrialStatusUpdate":
        """从字典创建"""
        return cls(
            trial_id=data["trial_id"],
            status=data["status"],
            progress=data.get("progress", 0.0),
            current_step=data.get("current_step"),
            log_message=data.get("log_message"),
            error=data.get("error"),
        )


@dataclass
class IntentConfirmationData:
    """意图确认数据"""

    intent_id: str
    core_operations: List[str]
    target: Optional[str] = None
    business_scenario: Optional[str] = None
    expected_results: List[str] = field(default_factory=list)
    user_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "intent_id": self.intent_id,
            "core_operations": self.core_operations,
            "target": self.target,
            "business_scenario": self.business_scenario,
            "expected_results": self.expected_results,
            "user_message": self.user_message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntentConfirmationData":
        """从字典创建"""
        return cls(
            intent_id=data["intent_id"],
            core_operations=data.get("core_operations", []),
            target=data.get("target"),
            business_scenario=data.get("business_scenario"),
            expected_results=data.get("expected_results", []),
            user_message=data.get("user_message"),
        )
