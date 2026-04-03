"""
WebSocket 消息类型定义
"""

from enum import Enum
from typing import Dict, Any, Optional
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

    # 系统相关
    PING = "ping"
    PONG = "pong"
    ACK = "ack"  # 消息确认
    ERROR = "error"

    # 连接管理
    CONNECT = "connect"


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
    timestamp: float = field(default_factory=lambda: __import__("time").time())
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
    def create_request(msg_type: MessageType, data: Dict[str, Any]) -> "WebSocketMessage":
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
