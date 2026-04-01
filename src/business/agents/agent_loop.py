"""
Agent Loop 核心

提供简洁的 while 循环驱动的 Agent 运行引擎。
"""

import json
import logging
import time
from typing import Callable, Dict, List, Optional, Union

from src.business.ai.llm_client import LangChainLLMClient, LLMResponse, ToolCallInfo
from src.data.unified_config import UnifiedConfigManager
from src.business.memory.context_manager import ContextManager
from src.data.repositories import MessageRepository

from .config import AgentConfig, AgentResult, ResultType, RetryConfig, ToolDefinition, ToolSignal
from .builtin_tools import TALK_TO_USER_SCHEMA, LOAD_REFERENCE_SCHEMA, talk_to_user

logger = logging.getLogger(__name__)


class _PartialFormatMap(dict):
    """
    支持部分替换的 format_map 映射。

    用于 str.format_map()：已知键正常替换，未知键保留原占位符（不抛 KeyError）。
    """

    def __missing__(self, key):
        return "{" + key + "}"


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

    def format_system_prompt(self, **kwargs) -> str:
        """
        格式化 system prompt 模板变量（如 {recording_id}）。

        Orchestrator 在首次启动 Agent 前调用，避免直接访问 _config 私有属性。
        只替换明确传入的占位符（如 {recording_id}），其余内容原样保留。
        使用 str.replace 而非 format_map，避免 prompt 中的代码示例（含 {…} 的 JSON/Python
        片段）触发 ValueError: Invalid format specifier。
        """
        prompt = self._config.system_prompt
        for key, value in kwargs.items():
            prompt = prompt.replace("{" + key + "}", str(value))
        return prompt

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
                logger.debug(f"[Agent Loop] LLM 回复 (iteration={iteration}): {response.content or ''}")
                if response.has_tool_calls:
                    logger.debug(f"[Agent Loop] LLM 工具调用: {response.tool_calls[0].name}")
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
        tools: Optional[Union[List[ToolDefinition], Callable[[], List[ToolDefinition]]]] = None,
        system_prompt_override: Optional[str] = None,
    ) -> AgentResult:
        """
        执行 Agent 循环

        Args:
            session_id: 会话 ID
            user_input: 用户输入（可选）
            tools: 工具列表或工厂函数（由调用方组装传入）。
                传入 list 时直接使用（兼容现有 PM/程序员/试用）。
                传入 callable 时每轮迭代调用获取最新列表（支持助理的动态工具懒加载）。
                为 None 时只有内置工具可用。
            system_prompt_override: 系统提示覆盖（用于注入模板变量如 {recording_id}）。
                仅在会话首次初始化时生效，已有 system prompt 时忽略。

        Returns:
            AgentResult 对象
        """
        # 使用缓存的 ContextManager
        ctx = self._get_context_manager(session_id)

        # 初始化检查
        if not self._has_system_prompt(session_id):
            prompt = system_prompt_override or self._config.system_prompt
            ctx.save_message(role="system", content=prompt)
            logger.debug(f"[Agent Loop] 已设置 system prompt: {session_id}")

        session_status = ctx.get_session_status()
        if session_status == "suspended" and user_input is None:
            # suspended 且无用户输入 = 会话处于等待状态，Agent 不应启动
            logger.info(f"[Agent Loop] 会话处于等待状态，不进入循环: {session_id}")
            return AgentResult(result_type=ResultType.STILL_WAITING)
        if session_status in ("completed", "failed"):
            ctx.update_session_status("active")
            logger.debug(f"[Agent Loop] 会话恢复（{session_status} → active）: {session_id}")

        if user_input is not None:
            ctx.save_user_message(user_input)
            logger.debug(f"[Agent Loop] 用户输入: {user_input[:50]}...")

        # 构建工具 schemas 和 handlers 的辅助函数
        def _rebuild_tools(tool_defs: List[ToolDefinition]):
            nonlocal all_tool_schemas, tool_handlers
            all_tool_schemas = [td.schema for td in tool_defs] + [
                TALK_TO_USER_SCHEMA,
                LOAD_REFERENCE_SCHEMA,
            ]
            tool_handlers = {td.name: td.handler for td in tool_defs}
            tool_handlers["talk_to_user"] = talk_to_user

        _tools_callable = callable(tools)
        all_tool_schemas: list = []
        tool_handlers: Dict[str, Callable] = {}
        _last_tool_names: Optional[frozenset] = None
        if not _tools_callable:
            _rebuild_tools(tools or [])

        # 检查是否有待重试的工具调用（execute_tool 失败未保存 result，session 最后是 assistant tool_call）
        _pending_tc = ctx.get_pending_tool_call()

        # 主循环
        iteration = 0
        while iteration < self._config.max_iterations:
            iteration += 1

            if _tools_callable:
                new_tools = tools()
                new_names = frozenset(td.name for td in new_tools)
                if new_names != _last_tool_names:
                    _rebuild_tools(new_tools)
                    _last_tool_names = new_names

            if _pending_tc is not None:
                # 待重试：直接使用上次的工具调用，跳过 LLM
                tc_dict = _pending_tc
                _pending_tc = None
                tool_call: ToolCallInfo = ToolCallInfo(
                    id=tc_dict.get("id", ""),
                    name=tc_dict["name"],
                    args=tc_dict.get("args", {}),
                )
                logger.debug(f"[Agent Loop] 重试待执行工具: {tool_call.name}")
            else:
                # 组装上下文，调用 LLM
                messages = ctx.assemble_context()
                logger.debug(f"[Agent Loop] 迭代 {iteration}: 组装了 {len(messages)} 条消息")

                response = self._call_llm_with_retry(messages, all_tool_schemas, iteration)
                if response is None:
                    ctx.update_session_status("failed")
                    return AgentResult(result_type=ResultType.ERROR, error="LLM 调用失败")

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

                if not response.has_tool_calls:
                    if self._config.text_as_user_input and response.content:
                        ctx.update_session_status("suspended")
                        logger.info(f"[Agent Loop] 文字回复转为用户输入等待: {session_id}")
                        return AgentResult(
                            result_type=ResultType.NEEDS_USER_INPUT,
                            question=response.content,
                        )
                    ctx.update_session_status("completed")
                    logger.info(f"[Agent Loop] 完成（无工具调用）: {session_id}")
                    return AgentResult(
                        result_type=ResultType.COMPLETED,
                        final_output=response.content or "",
                    )

                tool_call = response.tool_calls[0]
                logger.debug(
                    f"[Agent Loop] 工具调用: {tool_call.name} args={json.dumps(tool_call.args, ensure_ascii=False)}"
                )

            # 执行工具（统一路径，不区分内置/注册）
            try:
                if tool_call.name == "load_reference":
                    result = ctx.load_reference(tool_call.args["reference_id"])
                else:
                    handler = tool_handlers.get(tool_call.name)
                    if handler is None:
                        result = f"错误：未知工具 '{tool_call.name}'"
                    else:
                        result = handler(**tool_call.args)

                # 检查是否为 ToolSignal（工具要求中断循环）
                if isinstance(result, ToolSignal):
                    if result.save_result:
                        ctx.save_tool_result(
                            tool_call_id=tool_call.id,
                            tool_name=tool_call.name,
                            content=result.display_text,
                        )
                    else:
                        # save_result=False 时仍需保存占位结果，否则下次 run()
                        # get_pending_tool_call() 会再次检测到悬空的 assistant tool_call，
                        # 导致无限重试循环
                        ctx.save_tool_result(
                            tool_call_id=tool_call.id,
                            tool_name=tool_call.name,
                            content="[工具执行失败，已提交分诊处理]",
                        )
                    # 携带 ToolSignal 的 display_text 到 ToolCallInfo
                    signal_call_info = ToolCallInfo(
                        id=tool_call.id,
                        name=tool_call.name,
                        args=tool_call.args,
                        display_text=result.display_text,
                    )
                    if result.result_type == ResultType.NEEDS_USER_INPUT:
                        ctx.update_session_status("suspended")
                        question = tool_call.args.get("message", "")
                        logger.info(f"[Agent Loop] 需要用户输入: {question[:50]}...")
                        return AgentResult(
                            result_type=ResultType.NEEDS_USER_INPUT,
                            question=question,
                            signal_tool=signal_call_info,
                        )
                    else:
                        ctx.update_session_status("completed")
                        return AgentResult(
                            result_type=result.result_type,
                            signal_tool=signal_call_info,
                        )

                # 普通工具结果，保存并继续迭代
                ctx.save_tool_result(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    content=result,
                )
                logger.debug(f"[Agent Loop] 工具结果: {tool_call.name} -> {result}")

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
        if self._config.text_as_user_input:
            # 持续对话类 Agent（assistant 等）：标记 suspended，用户下条消息可恢复
            ctx.update_session_status("suspended")
        else:
            ctx.update_session_status("failed")
        logger.error(f"[Agent Loop] 超过最大迭代次数: {session_id}")
        return AgentResult(
            result_type=ResultType.MAX_ITERATIONS_REACHED,
            error=f"超过最大迭代次数 ({self._config.max_iterations})",
        )
