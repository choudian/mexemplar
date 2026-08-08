"""
T062: Assistant dispatch tool behavior tests

Tests for:
- reply_to_user: interrupting tool, returns ToolSignal, updates referenced_count
- delegate_to_subagent: creates delegation, returns success JSON
- delegate_to_specialist: delegates to named specialist, validates existence
- create_specialist: creates specialist via service, validates params
"""

import json
from unittest.mock import patch, MagicMock

from src.business.agents.config import ResultType, ToolSignal

SESSION_ID = "test-session-001"


# ═══════════════════════════════════════════════
# reply_to_user
# ═══════════════════════════════════════════════


class TestReplyToUser:
    def test_returns_tool_signal(self):
        """reply_to_user 返回 ToolSignal，而不是 str"""
        from src.business.agents.tools.assistant_tools import create_reply_to_user_handler

        handler = create_reply_to_user_handler(SESSION_ID)
        result = handler(text="你好！")

        assert isinstance(result, ToolSignal)
        assert result.result_type == ResultType.NEEDS_USER_INPUT
        assert result.display_text == "你好！"

    def test_updates_referenced_count(self):
        """reply_to_user 应更新 memory_entries_referenced 的 referenced_count"""
        from src.business.agents.tools.assistant_tools import create_reply_to_user_handler

        handler = create_reply_to_user_handler(SESSION_ID)

        with patch(
            "src.business.agents.tools.assistant_tools.AssistantMemoryToolFacade"
        ) as MockFacade:
            facade = MagicMock()
            MockFacade.return_value = facade

            result = handler(
                text="基于你的偏好...",
                memory_entries_referenced=["entry-1", "entry-2"],
            )

            assert isinstance(result, ToolSignal)
            facade.record_memory_references.assert_called_once_with(["entry-1", "entry-2"])

    def test_no_referenced_entries_skips_update(self):
        """不传 memory_entries_referenced 时不更新 referenced_count"""
        from src.business.agents.tools.assistant_tools import create_reply_to_user_handler

        handler = create_reply_to_user_handler(SESSION_ID)

        with patch(
            "src.business.agents.tools.assistant_tools.AssistantMemoryToolFacade"
        ) as MockFacade:
            result = handler(text="简单回复")

            assert isinstance(result, ToolSignal)
            MockFacade.assert_not_called()

    def test_empty_referenced_list_skips_update(self):
        """空列表 memory_entries_referenced 不触发更新"""
        from src.business.agents.tools.assistant_tools import create_reply_to_user_handler

        handler = create_reply_to_user_handler(SESSION_ID)

        with patch(
            "src.business.agents.tools.assistant_tools.AssistantMemoryToolFacade"
        ) as MockFacade:
            result = handler(text="简单回复", memory_entries_referenced=[])

            assert isinstance(result, ToolSignal)
            MockFacade.assert_not_called()

    def test_malformed_referenced_entries_skips_update(self):
        """memory_entries_referenced 结构错误时静默跳过计量更新。"""
        from src.business.agents.tools.assistant_tools import create_reply_to_user_handler

        handler = create_reply_to_user_handler(SESSION_ID)

        with patch(
            "src.business.agents.tools.assistant_tools.AssistantMemoryToolFacade"
        ) as MockFacade:
            result = handler(
                text="简单回复",
                memory_entries_referenced="entry-1",  # type: ignore[arg-type]
            )

            assert isinstance(result, ToolSignal)
            MockFacade.assert_not_called()

        with patch(
            "src.business.agents.tools.assistant_tools.AssistantMemoryToolFacade"
        ) as MockFacade:
            result = handler(
                text="简单回复",
                memory_entries_referenced=["entry-1", 42],  # type: ignore[list-item]
            )

            assert isinstance(result, ToolSignal)
            MockFacade.assert_not_called()

    def test_schema_has_correct_name(self):
        """Schema 名称应为 reply_to_user"""
        from src.business.agents.tools.assistant_tools import REPLY_TO_USER_SCHEMA

        assert REPLY_TO_USER_SCHEMA["function"]["name"] == "reply_to_user"

    def test_schema_requires_text(self):
        """text 参数是必需的"""
        from src.business.agents.tools.assistant_tools import REPLY_TO_USER_SCHEMA

        assert "text" in REPLY_TO_USER_SCHEMA["function"]["parameters"]["required"]


# ═══════════════════════════════════════════════
# delegate_to_subagent
# ═══════════════════════════════════════════════


class TestDelegateToSubagent:
    def test_returns_success_json(self):
        """delegate_to_subagent 返回成功 JSON"""
        from src.business.agents.tools.assistant_tools import create_delegate_to_subagent_handler

        handler = create_delegate_to_subagent_handler(SESSION_ID)
        result = handler(task_description="查询明天天气")

        data = json.loads(result)
        assert data["success"] is True
        assert data["delegation_type"] == "ephemeral_subagent"

    def test_schema_has_correct_name(self):
        """Schema 名称为 delegate_to_subagent"""
        from src.business.agents.tools.assistant_tools import DELEGATE_TO_SUBAGENT_SCHEMA

        assert DELEGATE_TO_SUBAGENT_SCHEMA["function"]["name"] == "delegate_to_subagent"

    def test_schema_requires_task_description(self):
        """task_description 是必需参数"""
        from src.business.agents.tools.assistant_tools import DELEGATE_TO_SUBAGENT_SCHEMA

        assert (
            "task_description" in DELEGATE_TO_SUBAGENT_SCHEMA["function"]["parameters"]["required"]
        )


# ═══════════════════════════════════════════════
# delegate_to_specialist
# ═══════════════════════════════════════════════


class TestDelegateToSpecialist:
    def test_delegates_to_existing_specialist(self):
        """成功委派到已存在的专员"""
        from src.business.agents.tools.assistant_tools import create_delegate_to_specialist_handler

        callback = MagicMock(
            return_value={
                "success": True,
                "specialist_id": "sp-001",
                "delegation_type": "specialist",
            }
        )
        handler = create_delegate_to_specialist_handler(SESSION_ID, dispatch_callback=callback)

        result = handler(specialist_name="天气专家", task="查北京天气", taskId="utsk_test")
        data = json.loads(result)
        assert data["success"] is True
        assert data["specialist_id"] == "sp-001"
        assert data["delegation_type"] == "specialist"
        callback.assert_called_once_with(
            parent_session_id=SESSION_ID,
            specialist_name="天气专家",
            task="查北京天气",
            execution_context="",
            user_task_id="utsk_test",
        )

    def test_rejects_nonexistent_specialist(self):
        """委派到不存在的专员应返回错误"""
        from src.business.agents.tools.assistant_tools import create_delegate_to_specialist_handler

        callback = MagicMock(
            return_value={
                "success": False,
                "message": "专员不存在: 不存在的专员",
                "delegation_type": "specialist",
            }
        )
        handler = create_delegate_to_specialist_handler(SESSION_ID, dispatch_callback=callback)

        result = handler(specialist_name="不存在的专员", task="做点什么")
        data = json.loads(result)
        assert data["success"] is False

    def test_rejects_inactive_specialist(self):
        """委派到已停用的专员应返回错误"""
        from src.business.agents.tools.assistant_tools import create_delegate_to_specialist_handler

        callback = MagicMock(
            return_value={
                "success": False,
                "message": "专员已停用: 已停用的专员",
                "specialist_id": "sp-inactive",
                "delegation_type": "specialist",
            }
        )
        handler = create_delegate_to_specialist_handler(SESSION_ID, dispatch_callback=callback)

        result = handler(specialist_name="已停用的专员", task="做点什么")
        data = json.loads(result)
        assert data["success"] is False

    def test_schema_requires_specialist_name_and_task(self):
        """specialist_name 和 task 是必需参数"""
        from src.business.agents.tools.assistant_tools import DELEGATE_TO_SPECIALIST_SCHEMA

        required = DELEGATE_TO_SPECIALIST_SCHEMA["function"]["parameters"]["required"]
        assert "specialist_name" in required
        assert "task" in required


# ═══════════════════════════════════════════════
# create_specialist
# ═══════════════════════════════════════════════


class TestCreateSpecialist:
    def test_creates_specialist_successfully(self):
        """成功创建专员"""
        from src.business.agents.tools.assistant_tools import create_create_specialist_handler

        handler = create_create_specialist_handler(SESSION_ID)

        with patch(
            "src.business.agents.tools.assistant_tools.AssistantSpecialistToolFacade"
        ) as MockFacade:
            facade = MagicMock()
            MockFacade.return_value = facade
            facade.create_from_conversation.return_value = {
                "specialist_id": "sp-new-001",
                "name": "天气专家",
            }

            result = handler(
                name="天气专家",
                description="天气查询专员",
                role_definition="你负责查询天气信息",
                tool_whitelist=["get_weather"],
            )
            data = json.loads(result)
            assert data["success"] is True
            assert data["specialist_id"] == "sp-new-001"
            facade.create_from_conversation.assert_called_once()

    def test_rejects_duplicate_name(self):
        """重复名称应返回错误"""
        from src.business.agents.tools.assistant_tools import create_create_specialist_handler

        handler = create_create_specialist_handler(SESSION_ID)

        with patch(
            "src.business.agents.tools.assistant_tools.AssistantSpecialistToolFacade"
        ) as MockFacade:
            facade = MagicMock()
            MockFacade.return_value = facade
            facade.create_from_conversation.side_effect = ValueError("专员名称已存在: 天气专家")

            result = handler(
                name="天气专家",
                description="天气查询专员",
                role_definition="你负责查询天气信息",
                tool_whitelist=["get_weather"],
            )
            data = json.loads(result)
            assert data["success"] is False

    def test_schema_requires_all_fields(self):
        """所有字段都是必需的"""
        from src.business.agents.tools.assistant_tools import CREATE_SPECIALIST_SCHEMA

        required = CREATE_SPECIALIST_SCHEMA["function"]["parameters"]["required"]
        assert "name" in required
        assert "description" in required
        assert "role_definition" in required
        assert "tool_whitelist" in required
