"""
Intent 数据模型单元测试
"""

import pytest
from datetime import datetime
from src.business.intent.intent_models import Intent, IntentStatus


class TestIntent:
    """Intent 模型测试"""

    def test_create_intent(self):
        """测试创建意图"""
        intent = Intent(
            recording_id="rec-001",
            core_operations=["打开登录页面", "输入用户名", "输入密码", "点击登录按钮"],
            target="某网站",
            business_scenario="用户登录",
            expected_results=["登录成功", "跳转到首页"],
        )

        assert intent.intent_id is not None
        assert intent.recording_id == "rec-001"
        assert len(intent.core_operations) == 4
        assert intent.target == "某网站"
        assert intent.status == IntentStatus.ANALYZING

    def test_intent_to_dict(self):
        """测试转换为字典"""
        intent = Intent(
            recording_id="rec-001",
            core_operations=["打开登录页面"],
            target="某网站",
        )

        data = intent.to_dict()

        assert isinstance(data, dict)
        assert data["intent_id"] == intent.intent_id
        assert data["recording_id"] == "rec-001"
        assert isinstance(data["core_operations"], list)
        assert data["status"] == "analyzing"

    def test_intent_from_dict(self):
        """测试从字典创建"""
        data = {
            "intent_id": "intent-001",
            "recording_id": "rec-001",
            "core_operations": '["打开登录页面", "输入密码"]',
            "target": "某网站",
            "business_scenario": "用户登录",
            "expected_results": '["登录成功"]',
            "status": "pending_confirmation",
            "confirmed_operations": "[]",
            "user_message": None,
            "analysis_confidence": 0.85,
            "llm_model_used": "claude-3-5-sonnet-20241022",
            "created_at": "2026-02-10T10:00:00",
            "updated_at": "2026-02-10T10:05:00",
            "confirmed_at": None,
        }

        intent = Intent.from_dict(data)

        assert intent.intent_id == "intent-001"
        assert len(intent.core_operations) == 2
        assert intent.target == "某网站"
        assert intent.status == IntentStatus.PENDING_CONFIRMATION
        assert intent.analysis_confidence == 0.85

    def test_confirm_intent(self):
        """测试确认意图"""
        intent = Intent(
            recording_id="rec-001",
            core_operations=["打开登录页面", "输入密码"],
        )

        confirmed_ops = ["打开登录页面", "输入密码", "点击登录"]
        intent.confirm(confirmed_ops, user_message="还需要记住密码")

        assert intent.status == IntentStatus.CONFIRMED
        assert intent.confirmed_operations == confirmed_ops
        assert intent.user_message == "还需要记住密码"
        assert intent.confirmed_at is not None
        assert intent.updated_at is not None

    def test_cancel_intent(self):
        """测试取消意图"""
        intent = Intent(recording_id="rec-001")

        intent.cancel()

        assert intent.status == IntentStatus.CANCELLED
        assert intent.updated_at is not None

    def test_intent_status_enum(self):
        """测试状态枚举"""
        assert IntentStatus.ANALYZING == "analyzing"
        assert IntentStatus.PENDING_CONFIRMATION == "pending_confirmation"
        assert IntentStatus.CONFIRMED == "confirmed"
        assert IntentStatus.CANCELLED == "cancelled"
