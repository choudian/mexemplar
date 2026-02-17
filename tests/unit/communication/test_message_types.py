"""
WebSocket 消息类型单元测试
"""

import pytest
import json
from src.communication.message_types import (
    MessageType,
    WebSocketMessage,
    TrialStatusUpdate,
    IntentConfirmationData,
)


class TestMessageType:
    """MessageType 测试"""

    def test_message_type_values(self):
        """测试消息类型枚举值"""
        assert MessageType.ANALYZE_INTENT == "analyze_intent"
        assert MessageType.INTENT_ANALYZED == "intent_analyzed"
        assert MessageType.START_TRIAL == "start_trial"
        assert MessageType.PING == "ping"
        assert MessageType.PONG == "pong"


class TestWebSocketMessage:
    """WebSocketMessage 测试"""

    def test_create_message(self):
        """测试创建消息"""
        msg = WebSocketMessage(
            type=MessageType.ANALYZE_INTENT,
            data={"recording_id": "rec-001"},
        )

        assert msg.type == MessageType.ANALYZE_INTENT
        assert msg.data == {"recording_id": "rec-001"}
        assert msg.status == "success"
        assert msg.request_id is None

    def test_to_dict(self):
        """测试转换为字典"""
        msg = WebSocketMessage(
            type=MessageType.ANALYZE_INTENT,
            data={"recording_id": "rec-001"},
            request_id="req-001",
        )

        data = msg.to_dict()

        assert data["type"] == "analyze_intent"
        assert data["data"] == {"recording_id": "rec-001"}
        assert data["request_id"] == "req-001"
        assert data["status"] == "success"
        assert "timestamp" in data

    def test_to_json(self):
        """测试转换为 JSON"""
        msg = WebSocketMessage(
            type=MessageType.ANALYZE_INTENT,
            data={"recording_id": "rec-001"},
        )

        json_str = msg.to_json()
        parsed = json.loads(json_str)

        assert parsed["type"] == "analyze_intent"
        assert parsed["data"] == {"recording_id": "rec-001"}

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "type": "analyze_intent",
            "data": {"recording_id": "rec-001"},
            "request_id": "req-001",
            "status": "success",
            "error": None,
            "timestamp": 1234567890.0,
        }

        msg = WebSocketMessage.from_dict(data)

        assert msg.type == MessageType.ANALYZE_INTENT
        assert msg.data == {"recording_id": "rec-001"}
        assert msg.request_id == "req-001"
        assert msg.timestamp == 1234567890.0

    def test_from_json(self):
        """测试从 JSON 创建"""
        json_str = '{"type": "analyze_intent", "data": {"recording_id": "rec-001"}}'

        msg = WebSocketMessage.from_json(json_str)

        assert msg.type == MessageType.ANALYZE_INTENT
        assert msg.data == {"recording_id": "rec-001"}

    def test_create_request(self):
        """测试创建请求消息"""
        msg = WebSocketMessage.create_request(
            MessageType.ANALYZE_INTENT,
            {"recording_id": "rec-001"},
        )

        assert msg.type == MessageType.ANALYZE_INTENT
        assert msg.request_id is not None
        assert msg.status == "pending"

    def test_create_response_success(self):
        """测试创建成功响应"""
        request = WebSocketMessage.create_request(
            MessageType.ANALYZE_INTENT,
            {"recording_id": "rec-001"},
        )

        response = WebSocketMessage.create_response(
            request,
            {"intent_id": "intent-001"},
            success=True,
        )

        assert response.type == MessageType.ANALYZE_INTENT
        assert response.request_id == request.request_id
        assert response.status == "success"
        assert response.data == {"intent_id": "intent-001"}

    def test_create_response_error(self):
        """测试创建错误响应"""
        request = WebSocketMessage.create_request(
            MessageType.ANALYZE_INTENT,
            {"recording_id": "rec-001"},
        )

        response = WebSocketMessage.create_response(
            request,
            {"error": "分析失败"},
            success=False,
        )

        assert response.status == "error"

    def test_create_error_message(self):
        """测试创建错误消息"""
        request = WebSocketMessage.create_request(
            MessageType.ANALYZE_INTENT,
            {"recording_id": "rec-001"},
        )

        error_msg = WebSocketMessage.create_error(request, "处理失败")

        assert error_msg.type == MessageType.ERROR
        assert error_msg.status == "error"
        assert error_msg.error == "处理失败"
        assert error_msg.request_id == request.request_id

    def test_create_error_message_without_request(self):
        """测试创建无请求的错误消息"""
        error_msg = WebSocketMessage.create_error(None, "系统错误")

        assert error_msg.type == MessageType.ERROR
        assert error_msg.status == "error"
        assert error_msg.error == "系统错误"
        assert error_msg.request_id is None


class TestTrialStatusUpdate:
    """TrialStatusUpdate 测试"""

    def test_create_status_update(self):
        """测试创建状态更新"""
        update = TrialStatusUpdate(
            trial_id="trial-001",
            status="running",
            progress=0.5,
            current_step="打开登录页面",
            log_message="正在执行...",
        )

        assert update.trial_id == "trial-001"
        assert update.status == "running"
        assert update.progress == 0.5
        assert update.current_step == "打开登录页面"
        assert update.log_message == "正在执行..."

    def test_to_dict(self):
        """测试转换为字典"""
        update = TrialStatusUpdate(
            trial_id="trial-001",
            status="success",
        )

        data = update.to_dict()

        assert data["trial_id"] == "trial-001"
        assert data["status"] == "success"
        assert data["progress"] == 0.0

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "trial_id": "trial-001",
            "status": "failed",
            "progress": 0.8,
            "error": "Element not found",
        }

        update = TrialStatusUpdate.from_dict(data)

        assert update.trial_id == "trial-001"
        assert update.status == "failed"
        assert update.progress == 0.8
        assert update.error == "Element not found"


class TestIntentConfirmationData:
    """IntentConfirmationData 测试"""

    def test_create_confirmation_data(self):
        """测试创建确认数据"""
        data = IntentConfirmationData(
            intent_id="intent-001",
            core_operations=["打开登录页面", "输入用户名"],
            target="某网站",
            business_scenario="用户登录",
        )

        assert data.intent_id == "intent-001"
        assert len(data.core_operations) == 2
        assert data.target == "某网站"

    def test_to_dict(self):
        """测试转换为字典"""
        data = IntentConfirmationData(
            intent_id="intent-001",
            core_operations=["打开登录页面"],
            user_message="还需要记住密码",
        )

        dict_data = data.to_dict()

        assert dict_data["intent_id"] == "intent-001"
        assert dict_data["core_operations"] == ["打开登录页面"]
        assert dict_data["user_message"] == "还需要记住密码"

    def test_from_dict(self):
        """测试从字典创建"""
        dict_data = {
            "intent_id": "intent-001",
            "core_operations": ["打开登录页面", "输入密码"],
            "target": "某网站",
            "business_scenario": "用户登录",
            "expected_results": ["登录成功"],
        }

        data = IntentConfirmationData.from_dict(dict_data)

        assert data.intent_id == "intent-001"
        assert len(data.core_operations) == 2
        assert data.target == "某网站"
        assert data.expected_results == ["登录成功"]
