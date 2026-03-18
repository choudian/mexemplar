"""
测试 Agent Loop 核心
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.business.agents import (
    AgentLoop,
    AgentConfig,
    AgentResult,
    ResultType,
    AgentType,
    RetryConfig,
)
from src.business.agents.config import ToolDefinition
from src.business.ai.llm_client import LLMResponse, ToolCallInfo


class TestAgentLoop:
    """Agent Loop 测试"""

    def setup_method(self):
        """每个测试前准备 Mock 对象"""
        # Mock LLM 客户端
        self.mock_llm = Mock()

        # Mock 配置管理器
        self.mock_config = Mock()

        # 创建测试配置
        self.test_config = AgentConfig(
            agent_type=AgentType.PM,
            system_prompt="你是一个测试 Agent。",
            max_iterations=5,
            retry=RetryConfig(max_retries=2, retry_delay=0.1),
        )

    @patch("src.business.agents.agent_loop.ContextManager")
    @patch("src.business.agents.agent_loop.MessageRepository")
    def test_normal_completion_no_tools(self, mock_msg_repo_cls, mock_ctx_cls):
        """测试正常完成流程（无工具调用）"""
        # Mock ContextManager
        mock_ctx = MagicMock()
        mock_ctx_cls.return_value = mock_ctx
        mock_ctx.get_session_status.return_value = None
        mock_ctx.assemble_context.return_value = [
            {"role": "system", "content": "测试 prompt"},
            {"role": "user", "content": "测试输入"},
        ]
        mock_ctx.save_message.return_value = None
        mock_ctx.update_session_status.return_value = None

        # Mock MessageRepository
        mock_msg_repo = MagicMock()
        mock_msg_repo.get_first.return_value = None
        mock_msg_repo_cls.return_value = mock_msg_repo

        # Mock LLM 响应（无工具调用）
        self.mock_llm.chat_with_tools.return_value = LLMResponse(content="测试回复", tool_calls=[])

        # 创建并运行 Agent Loop
        loop = AgentLoop(self.test_config, self.mock_llm, self.mock_config)
        result = loop.run("test-session", "测试输入")

        # 验证结果
        assert result.result_type == ResultType.COMPLETED
        assert result.final_output == "测试回复"
        assert mock_ctx.update_session_status.called

    @patch("src.business.agents.agent_loop.ContextManager")
    @patch("src.business.agents.agent_loop.MessageRepository")
    def test_talk_to_user_interrupt(self, mock_msg_repo_cls, mock_ctx_cls):
        """测试 talk_to_user 中断流程"""
        # Mock ContextManager
        mock_ctx = MagicMock()
        mock_ctx_cls.return_value = mock_ctx
        mock_ctx.get_session_status.return_value = None
        mock_ctx.assemble_context.return_value = [{"role": "system", "content": "测试 prompt"}]
        mock_ctx.save_message.return_value = None
        mock_ctx.update_session_status.return_value = None

        # Mock MessageRepository
        mock_msg_repo = MagicMock()
        mock_msg_repo.get_first.return_value = None
        mock_msg_repo_cls.return_value = mock_msg_repo

        # Mock LLM 响应（包含 talk_to_user 工具调用）
        self.mock_llm.chat_with_tools.return_value = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(id="call_123", name="talk_to_user", args={"message": "请问你的姓名？"})
            ],
        )

        # 创建并运行 Agent Loop
        loop = AgentLoop(self.test_config, self.mock_llm, self.mock_config)
        result = loop.run("test-session")

        # 验证结果
        assert result.result_type == ResultType.NEEDS_USER_INPUT
        assert result.question == "请问你的姓名？"
        assert mock_ctx.update_session_status.called
        mock_ctx.update_session_status.assert_called_with("suspended")

    @patch("src.business.agents.agent_loop.ContextManager")
    @patch("src.business.agents.agent_loop.MessageRepository")
    def test_tool_execution_success(self, mock_msg_repo_cls, mock_ctx_cls):
        """测试工具执行成功"""
        # Mock ContextManager
        mock_ctx = MagicMock()
        mock_ctx_cls.return_value = mock_ctx
        mock_ctx.get_session_status.return_value = None
        mock_ctx.assemble_context.return_value = [{"role": "system", "content": "测试 prompt"}]
        mock_ctx.save_message.return_value = None
        mock_ctx.update_session_status.return_value = None

        # Mock MessageRepository
        mock_msg_repo = MagicMock()
        mock_msg_repo.get_first.return_value = None
        mock_msg_repo_cls.return_value = mock_msg_repo

        # 定义测试工具（通过 ToolDefinition 传入）
        mock_handler = Mock(return_value="工具执行成功")
        test_tool = ToolDefinition(
            name="test_tool",
            schema={"type": "function", "function": {"name": "test_tool", "parameters": {}}},
            handler=mock_handler,
        )

        # 第一次 LLM 调用返回工具调用，第二次返回最终结果
        self.mock_llm.chat_with_tools.side_effect = [
            LLMResponse(
                content=None,
                tool_calls=[ToolCallInfo(id="call_123", name="test_tool", args={"id": "456"})],
            ),
            LLMResponse(content="基于工具结果的回复", tool_calls=[]),
        ]

        # 创建并运行 Agent Loop（传入 tools 参数）
        loop = AgentLoop(self.test_config, self.mock_llm, self.mock_config)
        result = loop.run("test-session", tools=[test_tool])

        # 验证结果
        assert result.result_type == ResultType.COMPLETED
        assert result.final_output == "基于工具结果的回复"
        mock_handler.assert_called_once_with(id="456")

    @patch("src.business.agents.agent_loop.ContextManager")
    @patch("src.business.agents.agent_loop.MessageRepository")
    def test_tool_execution_error_continues(self, mock_msg_repo_cls, mock_ctx_cls):
        """测试工具执行错误（异常）不终止循环"""
        # Mock ContextManager
        mock_ctx = MagicMock()
        mock_ctx_cls.return_value = mock_ctx
        mock_ctx.get_session_status.return_value = None
        mock_ctx.assemble_context.return_value = [{"role": "system", "content": "测试 prompt"}]
        mock_ctx.save_message.return_value = None
        mock_ctx.update_session_status.return_value = None

        # Mock MessageRepository
        mock_msg_repo = MagicMock()
        mock_msg_repo.get_first.return_value = None
        mock_msg_repo_cls.return_value = mock_msg_repo

        # 工具 handler 抛出异常
        def raising_handler():
            raise RuntimeError("工具执行失败")

        error_tool = ToolDefinition(
            name="error_tool",
            schema={"type": "function", "function": {"name": "error_tool", "parameters": {}}},
            handler=raising_handler,
        )

        # LLM 调用：工具调用 -> 最终回复
        self.mock_llm.chat_with_tools.side_effect = [
            LLMResponse(
                content=None, tool_calls=[ToolCallInfo(id="call_123", name="error_tool", args={})]
            ),
            LLMResponse(content="理解错误，继续处理", tool_calls=[]),
        ]

        # 创建并运行 Agent Loop
        loop = AgentLoop(self.test_config, self.mock_llm, self.mock_config)
        result = loop.run("test-session", tools=[error_tool])

        # 验证结果：循环没有终止，继续处理
        assert result.result_type == ResultType.COMPLETED

    @patch("src.business.agents.agent_loop.ContextManager")
    @patch("src.business.agents.agent_loop.MessageRepository")
    def test_llm_call_retry(self, mock_msg_repo_cls, mock_ctx_cls):
        """测试 LLM 调用重试机制"""
        # Mock ContextManager
        mock_ctx = MagicMock()
        mock_ctx_cls.return_value = mock_ctx
        mock_ctx.get_session_status.return_value = None
        mock_ctx.assemble_context.return_value = [{"role": "system", "content": "测试 prompt"}]
        mock_ctx.save_message.return_value = None
        mock_ctx.update_session_status.return_value = None

        # Mock MessageRepository
        mock_msg_repo = MagicMock()
        mock_msg_repo.get_first.return_value = None
        mock_msg_repo_cls.return_value = mock_msg_repo

        # 配置：允许重试 3 次
        self.test_config.retry.max_retries = 3

        # 前两次调用失败（可重试错误），第三次成功
        self.mock_llm.chat_with_tools.side_effect = [
            Exception("rate_limit_exceeded"),
            Exception("timeout"),
            LLMResponse(content="重试成功", tool_calls=[]),
        ]

        # 创建并运行 Agent Loop
        loop = AgentLoop(self.test_config, self.mock_llm, self.mock_config)
        result = loop.run("test-session")

        # 验证结果：重试后成功
        assert result.result_type == ResultType.COMPLETED
        assert result.final_output == "重试成功"
        assert self.mock_llm.chat_with_tools.call_count == 3

    @patch("src.business.agents.agent_loop.ContextManager")
    @patch("src.business.agents.agent_loop.MessageRepository")
    def test_llm_call_retry_exhausted(self, mock_msg_repo_cls, mock_ctx_cls):
        """测试 LLM 重试全部耗尽后返回 ERROR"""
        mock_ctx = MagicMock()
        mock_ctx_cls.return_value = mock_ctx
        mock_ctx.get_session_status.return_value = None
        mock_ctx.assemble_context.return_value = [{"role": "system", "content": "测试 prompt"}]
        mock_ctx.save_message.return_value = None
        mock_ctx.update_session_status.return_value = None

        mock_msg_repo = MagicMock()
        mock_msg_repo.get_first.return_value = None
        mock_msg_repo_cls.return_value = mock_msg_repo

        # 配置：允许重试 2 次（共 3 次尝试）
        self.test_config.retry.max_retries = 2

        # 所有调用都失败（可重试错误）
        self.mock_llm.chat_with_tools.side_effect = Exception("rate_limit_exceeded")

        loop = AgentLoop(self.test_config, self.mock_llm, self.mock_config)
        result = loop.run("test-session")

        # 验证结果：重试耗尽后返回 ERROR
        assert result.result_type == ResultType.ERROR
        assert "LLM 调用失败" in result.error
        # max_retries=2 时，循环 range(3) 即尝试 3 次
        assert self.mock_llm.chat_with_tools.call_count == 3

    @patch("src.business.agents.agent_loop.ContextManager")
    @patch("src.business.agents.agent_loop.MessageRepository")
    def test_max_iterations_reached(self, mock_msg_repo_cls, mock_ctx_cls):
        """测试超过最大迭代次数"""
        # Mock ContextManager
        mock_ctx = MagicMock()
        mock_ctx_cls.return_value = mock_ctx
        mock_ctx.get_session_status.return_value = None
        mock_ctx.assemble_context.return_value = [{"role": "system", "content": "测试 prompt"}]
        mock_ctx.save_message.return_value = None
        mock_ctx.update_session_status.return_value = None

        # Mock MessageRepository
        mock_msg_repo = MagicMock()
        mock_msg_repo.get_first.return_value = None
        mock_msg_repo_cls.return_value = mock_msg_repo

        # 配置：最大迭代次数 3
        self.test_config.max_iterations = 3

        # LLM 始终返回工具调用
        self.mock_llm.chat_with_tools.return_value = LLMResponse(
            content=None, tool_calls=[ToolCallInfo(id="call_123", name="infinite_tool", args={})]
        )

        # 定义一个无限循环工具（返回普通 str，不中断）
        infinite_tool = ToolDefinition(
            name="infinite_tool",
            schema={"type": "function", "function": {"name": "infinite_tool", "parameters": {}}},
            handler=lambda: "工具结果",
        )

        # 创建并运行 Agent Loop
        loop = AgentLoop(self.test_config, self.mock_llm, self.mock_config)
        result = loop.run("test-session", tools=[infinite_tool])

        # 验证结果：达到最大迭代次数
        assert result.result_type == ResultType.MAX_ITERATIONS_REACHED
        assert "超过最大迭代次数" in result.error

    def test_config_cache(self):
        """测试配置缓存"""
        # 创建两个 Agent Loop
        loop1 = AgentLoop(self.test_config, self.mock_llm, self.mock_config)
        loop2 = AgentLoop(self.test_config, self.mock_llm, self.mock_config)

        # 验证配置对象相同（缓存）
        assert loop1._unified_config is loop2._unified_config

    @patch("src.business.agents.agent_loop.ContextManager")
    def test_clear_cache(self, mock_ctx_cls):
        """测试清除缓存"""
        # Mock ContextManager
        mock_ctx = MagicMock()
        mock_ctx_cls.return_value = mock_ctx

        # 创建 Agent Loop
        loop = AgentLoop(self.test_config, self.mock_llm, self.mock_config)

        # 添加缓存
        loop._ctx_cache["session1"] = mock_ctx
        loop._ctx_cache["session2"] = mock_ctx

        # 清除单个会话缓存
        loop.clear_cache("session1")
        assert "session1" not in loop._ctx_cache
        assert "session2" in loop._ctx_cache

        # 清除所有缓存
        loop.clear_cache()
        assert len(loop._ctx_cache) == 0

    @patch("src.business.agents.agent_loop.ContextManager")
    @patch("src.business.agents.agent_loop.MessageRepository")
    def test_no_events_emitted_by_loop(self, mock_msg_repo_cls, mock_ctx_cls):
        """Loop 是纯执行引擎，不发任何业务事件（事件由 Orchestrator 发）"""
        mock_ctx = MagicMock()
        mock_ctx_cls.return_value = mock_ctx
        mock_ctx.get_session_status.return_value = None
        mock_ctx.assemble_context.return_value = [{"role": "system", "content": "测试 prompt"}]
        mock_ctx.save_message.return_value = None
        mock_ctx.save_assistant_message.return_value = None
        mock_ctx.update_session_status.return_value = None

        mock_msg_repo = MagicMock()
        mock_msg_repo.get_first.return_value = None
        mock_msg_repo_cls.return_value = mock_msg_repo

        self.mock_llm.chat_with_tools.return_value = LLMResponse(content="完成", tool_calls=[])

        with patch("src.utils.events.emit") as mock_emit:
            loop = AgentLoop(self.test_config, self.mock_llm, self.mock_config)
            loop.run("test-session")
            mock_emit.assert_not_called()
