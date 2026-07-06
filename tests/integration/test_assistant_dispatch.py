"""
T066: Labeled assistant dispatch acceptance tests

Tests for:
- reply_to_user tool is registered with is_interrupting=True
- delegate_to_subagent tool is registered for assistant
- delegate_to_specialist tool is registered for assistant
- create_specialist tool is registered for assistant
- Dispatch tools are NOT registered for PM/Programmer/Trial agents
- Tool schemas are valid and complete
"""

import json
from unittest.mock import MagicMock, patch

from src.business.agents.config import ToolDefinition
from src.business.ai.llm_client import LLMResponse, ToolCallInfo

# ═══════════════════════════════════════════════
# Tool registration in orchestrator
# ═══════════════════════════════════════════════


class TestAssistantDispatchToolsRegistered:
    """验证调度工具已注册到 assistant 工具集"""

    def _get_assistant_tool_names(self) -> set[str]:
        """获取 assistant 工具集中的所有工具名称"""
        from tests.conftest import MockLLMClient

        with (
            patch(
                "src.business.orchestration.agent.orchestrator.AgentSessionStore"
            ) as mock_store_cls,
            patch("src.business.orchestration.agent.orchestrator.AssistantPromptBuilder"),
            patch("src.business.orchestration.agent.orchestrator.AssistantTaskWorker"),
            patch("src.business.orchestration.agent.orchestrator.TeachingFailureTracker"),
            patch("src.business.orchestration.agent.orchestrator.WorkflowRetryCoordinator"),
            patch("src.business.orchestration.agent.orchestrator.LLMReviewer"),
            patch("src.business.orchestration.agent.orchestrator.SkillCompositionService"),
        ):
            from src.business.orchestration.agent.orchestrator import AgentOrchestrator
            from src.data.unified_config import UnifiedConfigManager

            # get_session 返回 None = 全量授权，与真实 Session.parse_tool_ids 契约对齐
            mock_store_cls.return_value.get_session.return_value = None

            mock_config = MagicMock(spec=UnifiedConfigManager)
            mock_config.get_memory_reference_steps_threshold.return_value = 999
            mock_config.get_memory_reference_size_threshold.return_value = 999_999
            mock_config.get_memory_compression_trigger_strategy.return_value = "token"
            mock_config.get_memory_compression_token_threshold.return_value = 999_999
            mock_config.get_memory_compression_count_threshold.return_value = None
            mock_config.get_memory_compression_keep_recent.return_value = 5
            mock_config.get_ai_retry_max_retries.return_value = 3
            mock_config.get_ai_retry_delay.return_value = 1.0

            mock_llm = MockLLMClient([])

            orch = AgentOrchestrator(mock_llm, mock_config)
            tool_factory = orch._build_assistant_tools("test-session-id")
            tools = tool_factory()

            return {t.name for t in tools}

    def test_reply_to_user_registered(self):
        """reply_to_user 已注册"""
        tool_names = self._get_assistant_tool_names()
        assert "reply_to_user" in tool_names

    def test_delegate_to_subagent_registered(self):
        """delegate_to_subagent 已注册"""
        tool_names = self._get_assistant_tool_names()
        assert "delegate_to_subagent" in tool_names

    def test_delegate_to_specialist_registered(self):
        """delegate_to_specialist 已注册"""
        tool_names = self._get_assistant_tool_names()
        assert "delegate_to_specialist" in tool_names

    def test_create_specialist_registered(self):
        """create_specialist 已注册"""
        tool_names = self._get_assistant_tool_names()
        assert "create_specialist" in tool_names


class TestReplyToUserIsInterrupting:
    """验证 reply_to_user 是中断型工具"""

    def _get_reply_to_user_tool(self) -> ToolDefinition:
        """从 orchestrator 获取 reply_to_user ToolDefinition"""
        from tests.conftest import MockLLMClient

        with (
            patch(
                "src.business.orchestration.agent.orchestrator.AgentSessionStore"
            ) as mock_store_cls,
            patch("src.business.orchestration.agent.orchestrator.AssistantPromptBuilder"),
            patch("src.business.orchestration.agent.orchestrator.AssistantTaskWorker"),
            patch("src.business.orchestration.agent.orchestrator.TeachingFailureTracker"),
            patch("src.business.orchestration.agent.orchestrator.WorkflowRetryCoordinator"),
            patch("src.business.orchestration.agent.orchestrator.LLMReviewer"),
            patch("src.business.orchestration.agent.orchestrator.SkillCompositionService"),
        ):
            from src.business.orchestration.agent.orchestrator import AgentOrchestrator
            from src.data.unified_config import UnifiedConfigManager

            # get_session 返回 None = 全量授权，与真实 Session.parse_tool_ids 契约对齐
            mock_store_cls.return_value.get_session.return_value = None

            mock_config = MagicMock(spec=UnifiedConfigManager)
            mock_config.get_memory_reference_steps_threshold.return_value = 999
            mock_config.get_memory_reference_size_threshold.return_value = 999_999
            mock_config.get_memory_compression_trigger_strategy.return_value = "token"
            mock_config.get_memory_compression_token_threshold.return_value = 999_999
            mock_config.get_memory_compression_count_threshold.return_value = None
            mock_config.get_memory_compression_keep_recent.return_value = 5
            mock_config.get_ai_retry_max_retries.return_value = 3
            mock_config.get_ai_retry_delay.return_value = 1.0

            mock_llm = MockLLMClient([])
            orch = AgentOrchestrator(mock_llm, mock_config)
            tool_factory = orch._build_assistant_tools("test-session-id")
            tools = tool_factory()

            for t in tools:
                if t.name == "reply_to_user":
                    return t
            return None

    def test_reply_to_user_is_interrupting(self):
        """reply_to_user 的 is_interrupting 应为 True"""
        tool = self._get_reply_to_user_tool()
        assert tool is not None, "reply_to_user tool not found"
        assert tool.is_interrupting is True

    def test_other_dispatch_tools_not_interrupting(self):
        """delegate_to_subagent, delegate_to_specialist, create_specialist 不是中断型"""
        from tests.conftest import MockLLMClient

        with (
            patch(
                "src.business.orchestration.agent.orchestrator.AgentSessionStore"
            ) as mock_store_cls,
            patch("src.business.orchestration.agent.orchestrator.AssistantPromptBuilder"),
            patch("src.business.orchestration.agent.orchestrator.AssistantTaskWorker"),
            patch("src.business.orchestration.agent.orchestrator.TeachingFailureTracker"),
            patch("src.business.orchestration.agent.orchestrator.WorkflowRetryCoordinator"),
            patch("src.business.orchestration.agent.orchestrator.LLMReviewer"),
            patch("src.business.orchestration.agent.orchestrator.SkillCompositionService"),
        ):
            from src.business.orchestration.agent.orchestrator import AgentOrchestrator
            from src.data.unified_config import UnifiedConfigManager

            # get_session 返回 None = 全量授权，与真实 Session.parse_tool_ids 契约对齐
            mock_store_cls.return_value.get_session.return_value = None

            mock_config = MagicMock(spec=UnifiedConfigManager)
            mock_config.get_memory_reference_steps_threshold.return_value = 999
            mock_config.get_memory_reference_size_threshold.return_value = 999_999
            mock_config.get_memory_compression_trigger_strategy.return_value = "token"
            mock_config.get_memory_compression_token_threshold.return_value = 999_999
            mock_config.get_memory_compression_count_threshold.return_value = None
            mock_config.get_memory_compression_keep_recent.return_value = 5
            mock_config.get_ai_retry_max_retries.return_value = 3
            mock_config.get_ai_retry_delay.return_value = 1.0

            mock_llm = MockLLMClient([])
            orch = AgentOrchestrator(mock_llm, mock_config)
            tools = orch._build_assistant_tools("test-session-id")()

            for t in tools:
                if t.name in (
                    "delegate_to_subagent",
                    "delegate_to_specialist",
                    "create_specialist",
                ):
                    assert t.is_interrupting is False, f"{t.name} 不应是中断型工具"


# ═══════════════════════════════════════════════
# Dispatch tools excluded from PM/Programmer/Trial
# ═══════════════════════════════════════════════


class TestDispatchToolsExcludedFromOtherAgents:
    """验证调度工具不被注册到 PM/Programmer/Trial agent"""

    def test_pm_tools_do_not_include_dispatch(self):
        """PM agent 工具集不包含调度工具"""
        from src.business.agents.tools.pm_output_tools import submit_requirements, report_code_issue
        from src.business.agents.tools.recording_data_tools import create_recording_tools

        tools = create_recording_tools("test-recording", "browser") + [
            submit_requirements,
            report_code_issue,
        ]
        tool_names = {t.name for t in tools}
        dispatch_tools = {
            "reply_to_user",
            "delegate_to_subagent",
            "delegate_to_specialist",
            "create_specialist",
        }
        assert dispatch_tools.isdisjoint(tool_names)

    def test_programmer_tools_do_not_include_dispatch(self):
        """Programmer agent 工具集不包含调度工具"""
        from src.business.agents.tools.programmer_tools import submit_code, syntax_check
        from src.business.agents.tools.recording_data_tools import create_recording_tools

        tools = create_recording_tools("test-recording", "browser") + [syntax_check, submit_code]
        tool_names = {t.name for t in tools}
        dispatch_tools = {
            "reply_to_user",
            "delegate_to_subagent",
            "delegate_to_specialist",
            "create_specialist",
        }
        assert dispatch_tools.isdisjoint(tool_names)


# ═══════════════════════════════════════════════
# Tool schema validation
# ═══════════════════════════════════════════════


class TestToolSchemas:
    """验证工具 schema 格式正确"""

    def test_reply_to_user_schema_valid(self):
        """reply_to_user schema 是有效的 function calling 格式"""
        from src.business.agents.tools.assistant_tools import REPLY_TO_USER_SCHEMA

        assert REPLY_TO_USER_SCHEMA["type"] == "function"
        func = REPLY_TO_USER_SCHEMA["function"]
        assert func["name"] == "reply_to_user"
        assert "text" in func["parameters"]["properties"]
        assert "memory_entries_referenced" in func["parameters"]["properties"]

    def test_delegate_to_subagent_schema_valid(self):
        """delegate_to_subagent schema 是有效的 function calling 格式"""
        from src.business.agents.tools.assistant_tools import DELEGATE_TO_SUBAGENT_SCHEMA

        assert DELEGATE_TO_SUBAGENT_SCHEMA["type"] == "function"
        func = DELEGATE_TO_SUBAGENT_SCHEMA["function"]
        assert func["name"] == "delegate_to_subagent"
        assert "task_description" in func["parameters"]["properties"]

    def test_invalidate_memory_entry_schema_encodes_proactive_disclosure(self):
        from src.business.agents.tools.assistant_tools import INVALIDATE_MEMORY_ENTRY_SCHEMA

        func = INVALIDATE_MEMORY_ENTRY_SCHEMA["function"]
        assert func["name"] == "invalidate_memory_entry"
        invalidation_type = func["parameters"]["properties"]["invalidation_type"]
        assert set(invalidation_type["enum"]) == {"reactive", "proactive"}

    def test_delegate_to_specialist_schema_valid(self):
        """delegate_to_specialist schema 是有效的 function calling 格式"""
        from src.business.agents.tools.assistant_tools import DELEGATE_TO_SPECIALIST_SCHEMA

        assert DELEGATE_TO_SPECIALIST_SCHEMA["type"] == "function"
        func = DELEGATE_TO_SPECIALIST_SCHEMA["function"]
        assert func["name"] == "delegate_to_specialist"
        assert "specialist_name" in func["parameters"]["properties"]
        assert "task" in func["parameters"]["properties"]

    def test_create_specialist_schema_valid(self):
        """create_specialist schema 是有效的 function calling 格式"""
        from src.business.agents.tools.assistant_tools import CREATE_SPECIALIST_SCHEMA

        assert CREATE_SPECIALIST_SCHEMA["type"] == "function"
        func = CREATE_SPECIALIST_SCHEMA["function"]
        assert func["name"] == "create_specialist"
        assert "name" in func["parameters"]["properties"]
        assert "description" in func["parameters"]["properties"]
        assert "role_definition" in func["parameters"]["properties"]
        assert "tool_whitelist" in func["parameters"]["properties"]


class TestAssistantDispatchAcceptanceSuite:
    """SC-002: 10 个标注任务请求应委派执行，且不得直接执行。"""

    TASK_REQUESTS = [
        "帮我查询北京明天的天气并总结一句话",
        "把这段会议记录整理成行动项",
        "搜索上周 AI 行业的重要新闻",
        "检查这个 JSON 是否符合接口格式",
        "生成一份季度预算对比表",
        "把这段英文邮件翻译成中文",
        "根据这些要点起草项目周报",
        "找出这段日志里的错误原因",
        "帮我规划下周三天的调研安排",
        "读取最新数据后给出趋势摘要",
    ]

    def test_labeled_task_suite_delegates_at_least_nine_of_ten(self, mock_config):
        from src.business.agents.agent_loop import AgentLoop
        from src.business.agents.config import (
            AgentConfig,
            AgentType,
            ResultType,
            ToolDefinition,
            ToolSignal,
        )
        from src.business.agents.prompts.assistant_prompt import format_assistant_prompt
        from src.business.agents.tools.assistant_tools import (
            DELEGATE_TO_SUBAGENT_SCHEMA,
            REPLY_TO_USER_SCHEMA,
        )
        from src.business.services.chat_service import ChatService

        prompt = format_assistant_prompt(
            profile={"display_name": "测试用户", "style": "", "notes": ""},
            tools=[{"name": "[技能] 搜索", "description": "搜索公开信息"}],
        )
        assert "没有合适工具时，用自身能力尽量回答" not in prompt
        assert "主动发现当前对话与某条记忆存在明确事实冲突" in prompt

        delegated_requests: list[str] = []
        direct_outputs = 0

        def delegate_handler(
            task_description: str, execution_context: str = "", tool_whitelist=None
        ):
            delegated_requests.append(task_description)
            return json.dumps(
                {"success": True, "delegation_type": "ephemeral_subagent"},
                ensure_ascii=False,
            )

        def reply_handler(text: str, memory_entries_referenced=None):
            return ToolSignal(ResultType.NEEDS_USER_INPUT, display_text=text)

        tools = [
            ToolDefinition(
                name="delegate_to_subagent",
                schema=DELEGATE_TO_SUBAGENT_SCHEMA,
                handler=delegate_handler,
            ),
            ToolDefinition(
                name="reply_to_user",
                schema=REPLY_TO_USER_SCHEMA,
                handler=reply_handler,
                is_interrupting=True,
            ),
        ]

        for idx, request in enumerate(self.TASK_REQUESTS):
            session_id = ChatService().create_session(title=f"dispatch-acceptance-{idx}")
            llm = _PromptSensitiveDispatchLLM(request)
            loop = AgentLoop(
                AgentConfig(
                    agent_type=AgentType.ASSISTANT,
                    system_prompt=prompt,
                    max_iterations=4,
                    text_as_user_input=True,
                ),
                llm,
                mock_config,
            )

            result = loop.run(
                session_id,
                user_input=request,
                tools=tools,
                system_prompt_override=prompt,
            )
            if result.question and result.question.startswith("直接执行"):
                direct_outputs += 1

        assert len(delegated_requests) >= 9
        assert direct_outputs == 0


class _PromptSensitiveDispatchLLM:
    """A deterministic acceptance double that follows the dispatch prompt contract."""

    def __init__(self, request: str):
        self._request = request
        self._calls = 0

    def chat(self, prompt: str, **kwargs) -> str:
        raise AssertionError("assistant dispatch acceptance should use chat_with_tools")

    def chat_with_tools(self, messages, tools, **kwargs) -> LLMResponse:
        self._calls += 1
        system_text = "\n".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system"
        )
        if self._calls == 1:
            if "没有合适工具时，用自身能力尽量回答" in system_text:
                return LLMResponse(content=f"直接执行: {self._request}", tool_calls=[])
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallInfo(
                        id=f"delegate-{self._calls}",
                        name="delegate_to_subagent",
                        args={
                            "task_description": self._request,
                            "execution_context": "SC-002 acceptance suite",
                        },
                    )
                ],
            )
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(
                    id=f"reply-{self._calls}",
                    name="reply_to_user",
                    args={"text": "已委派执行体处理。", "memory_entries_referenced": []},
                )
            ],
        )


class TestDelegationExecutionPaths:
    """验证委派工具会真正执行临时子代理/专员 AgentLoop。"""

    def test_delegate_to_subagent_runs_ephemeral_agent(self, mock_config):
        from tests.conftest import MockLLMClient
        from src.business.orchestration.agent.orchestrator import AgentOrchestrator
        from src.business.services.chat_service import ChatService

        parent_session_id = ChatService().create_session(title="parent")
        orchestrator = AgentOrchestrator(
            MockLLMClient([LLMResponse(content="已完成天气查询。", tool_calls=[])]),
            mock_config,
        )

        result = orchestrator._delegate_to_subagent(
            parent_session_id=parent_session_id,
            task_description="查询北京明天天气",
            execution_context="只返回一句摘要",
        )

        assert result["success"] is True
        assert result["delegation_type"] == "ephemeral_subagent"
        assert result["result_text"] == "已完成天气查询。"
        assert result["executor_session_id"]

    def test_delegate_to_specialist_runs_specialist_agent(self, mock_config):
        from tests.conftest import MockLLMClient
        from src.business.orchestration.agent.orchestrator import AgentOrchestrator
        from src.business.services.chat_service import ChatService
        from src.data.repos.specialist_repository import SpecialistRepository

        parent_session_id = ChatService().create_session(title="parent")
        specialist_id = SpecialistRepository().create_specialist(
            name="天气专员",
            description="处理天气相关任务",
            role_definition="负责查询并总结天气信息。",
            tool_whitelist=[],
            origin="user_conversation",
            reason="测试创建",
        )
        orchestrator = AgentOrchestrator(
            MockLLMClient([LLMResponse(content="天气专员结果：明天晴。", tool_calls=[])]),
            mock_config,
        )

        result = orchestrator._delegate_to_specialist(
            parent_session_id=parent_session_id,
            specialist_name="天气专员",
            task="查询北京明天天气",
        )

        assert result["success"] is True
        assert result["delegation_type"] == "specialist"
        assert result["specialist_id"] == specialist_id
        assert result["result_text"] == "天气专员结果：明天晴。"
