"""
Agent Loop 核心

提供简洁的 while 循环驱动的 Agent 运行引擎。
"""

import json
import logging
import time
from typing import Optional, Dict

from src.business.ai.llm_client import LangChainLLMClient, LLMResponse
from src.data.unified_config import UnifiedConfigManager
from src.business.memory.context_manager import ContextManager
from src.data.repositories import MessageRepository

from .config import AgentConfig, AgentResult, ResultType, RetryConfig
from .tool_registry import get_tool_schemas, execute_tool
from .builtin_tools import TALK_TO_USER_SCHEMA, LOAD_REFERENCE_SCHEMA

logger = logging.getLogger(__name__)


class AgentLoop:
    """
    Agent Loop 运行时引擎

    简洁的 while 循环驱动，支持：
    - 单工具调用模式（parallel_tool_calls=False）
    - talk_to_user 哨兵机制
    - 工具执行错误不终止循环
    - LLM 调用重试
    - 与记忆机制（ContextManager）集成
    - 工具装饰器注册
    - 配置缓存
    """

    def __init__(
        self,
        config: AgentConfig,
        llm_client: LangChainLLMClient,
        unified_config: UnifiedConfigManager,
    ):
        """
        初始化 Agent Loop

        Args:
            config: Agent 配置
            llm_client: LLM 客户端
            unified_config: 统一配置管理器
        """
        self._config = config
        self._llm = llm_client
        self._unified_config = unified_config
        self._ctx_cache: Dict[str, ContextManager] = {}

        logger.debug(
            f"[Agent Loop] 初始化: {config.agent_type.value}, "
            f"max_iterations={config.max_iterations}"
        )

    def _get_context_manager(self, session_id: str) -> ContextManager:
        """
        获取或创建 ContextManager（带缓存）

        Args:
            session_id: 会话 ID

        Returns:
            ContextManager 实例
        """
        if session_id not in self._ctx_cache:
            self._ctx_cache[session_id] = ContextManager(session_id, self._unified_config)
        return self._ctx_cache[session_id]

    def _has_system_prompt(self, session_id: str) -> bool:
        """
        检查会话是否已有 system prompt

        Args:
            session_id: 会话 ID

        Returns:
            是否已有 system prompt
        """
        msg_repo = MessageRepository()
        first_msg = msg_repo.get_first(session_id)
        return first_msg and first_msg.role == "system"

    def _is_retryable_error(self, error: Exception) -> bool:
        """
        判断错误是否可重试

        使用字符串子串匹配而非异常类型匹配：LangChain 将底层 API 错误包装为
        通用 Exception，原始异常类型丢失，类型匹配无法命中。字符串匹配覆盖
        Anthropic/OpenAI API 的实际错误消息（如 "rate_limit_exceeded"、"timeout"）。

        Args:
            error: 异常对象

        Returns:
            是否可重试
        """
        error_str = str(error).lower()
        for retryable in self._config.retry.retryable_errors:
            if retryable.lower() in error_str:
                return True
        return False

    def _call_llm_with_retry(
        self,
        messages: list,
        tools: list,
        iteration: int,
    ) -> Optional[LLMResponse]:
        """
        调用 LLM（带重试机制）

        Args:
            messages: 消息列表
            tools: 工具列表
            iteration: 当前迭代次数

        Returns:
            LLMResponse 对象，失败返回 None
        """
        retry_config: RetryConfig = self._config.retry

        for retry_count in range(retry_config.max_retries + 1):
            try:
                response = self._llm.chat_with_tools(messages, tools)
                logger.debug(f"[Agent Loop] LLM 调用成功 (iteration={iteration})")
                return response

            except Exception as e:
                if retry_count < retry_config.max_retries and self._is_retryable_error(e):
                    delay = retry_config.retry_delay
                    logger.warning(
                        f"[Agent Loop] LLM 调用失败（可重试）: {e}, "
                        f"等待 {delay}s 后重试 ({retry_count + 1}/{retry_config.max_retries})"
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"[Agent Loop] LLM 调用失败: {e}")
                    return None

        return None

    def clear_cache(self, session_id: Optional[str] = None):
        """
        清除缓存

        Args:
            session_id: 会话 ID，为 None 时清除所有缓存
        """
        if session_id:
            self._ctx_cache.pop(session_id, None)
            logger.debug(f"[Agent Loop] 清除会话缓存: {session_id}")
        else:
            self._ctx_cache.clear()
            logger.debug("[Agent Loop] 清除所有缓存")

    def run(
        self,
        session_id: str,
        user_input: Optional[str] = None,
    ) -> AgentResult:
        """
        执行 Agent 循环

        Args:
            session_id: 会话 ID
            user_input: 用户输入（可选）

        Returns:
            AgentResult 对象
        """
        # 使用缓存的 ContextManager
        ctx = self._get_context_manager(session_id)

        # 初始化检查
        if not self._has_system_prompt(session_id):
            ctx.save_message(role="system", content=self._config.system_prompt)
            logger.debug(f"[Agent Loop] 已设置 system prompt: {session_id}")

        if ctx.get_session_status() in ("suspended", "completed"):
            ctx.update_session_status("active")
            logger.debug(f"[Agent Loop] 会话恢复: {session_id}")

        if user_input is not None:
            ctx.save_user_message(user_input)
            logger.debug(f"[Agent Loop] 用户输入: {user_input[:50]}...")

        # 构建工具列表（使用注册表 + 内置工具）
        all_tool_schemas = get_tool_schemas() + [TALK_TO_USER_SCHEMA, LOAD_REFERENCE_SCHEMA]

        # 主循环
        iteration = 0
        while iteration < self._config.max_iterations:
            iteration += 1

            # 组装上下文
            messages = ctx.assemble_context()
            logger.debug(f"[Agent Loop] 迭代 {iteration}: 组装了 {len(messages)} 条消息")

            # 调用 LLM（带重试）
            response = self._call_llm_with_retry(messages, all_tool_schemas, iteration)
            if response is None:
                ctx.update_session_status("failed")
                return AgentResult(result_type=ResultType.ERROR, error="LLM 调用失败")

            # 保存 assistant 消息
            ctx.save_assistant_message(
                content=response.content or "",
                tool_calls=(
                    json.dumps(
                        [
                            {"id": tc.id, "name": tc.name, "args": tc.args}
                            for tc in response.tool_calls
                        ]
                    )
                    if response.has_tool_calls
                    else None
                ),
            )

            # 如果没有工具调用，循环结束
            if not response.has_tool_calls:
                ctx.update_session_status("completed")
                logger.info(f"[Agent Loop] 完成（无工具调用）: {session_id}")
                return AgentResult(
                    result_type=ResultType.COMPLETED,
                    final_output=response.content,
                )

            # 执行工具调用（单工具模式）
            tool_call = response.tool_calls[0]
            logger.debug(
                f"[Agent Loop] 工具调用: {tool_call.name} " f"(args: {list(tool_call.args.keys())})"
            )

            # 检查 talk_to_user 哨兵
            if tool_call.name == "talk_to_user":
                ctx.save_tool_result(
                    tool_call_id=tool_call.id, tool_name="talk_to_user", content="[等待用户回复]"
                )
                ctx.update_session_status("suspended")
                question = tool_call.args.get("message", "")
                logger.info(f"[Agent Loop] 需要用户输入: {question[:50]}...")
                return AgentResult(
                    result_type=ResultType.NEEDS_USER_INPUT,
                    question=question,
                )

            # 执行工具
            try:
                if tool_call.name == "load_reference":
                    # load_reference 由 AgentLoop 内部处理
                    result = ctx.load_reference(tool_call.args["message_id"])
                else:
                    # 执行注册表中的工具
                    result = execute_tool(tool_call.name, tool_call.args)

                ctx.save_tool_result(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    content=result,
                )
                logger.debug(f"[Agent Loop] 工具执行成功: {tool_call.name}")

            except Exception as e:
                error_msg = f"工具执行错误: {str(e)}"
                ctx.save_tool_result(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    content=error_msg,
                )
                logger.warning(f"[Agent Loop] {error_msg}")
                # 不终止循环，让 LLM 决定下一步

        # 超过最大迭代次数
        ctx.update_session_status("failed")
        logger.error(f"[Agent Loop] 超过最大迭代次数: {session_id}")
        return AgentResult(
            result_type=ResultType.MAX_ITERATIONS_REACHED,
            error=f"超过最大迭代次数 ({self._config.max_iterations})",
        )
