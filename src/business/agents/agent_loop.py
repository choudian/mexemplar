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
from src.utils.helpers import safe_format_template

from .config import AgentConfig, AgentResult, ResultType, RetryConfig, ToolDefinition, ToolSignal
from .builtin_tools import TALK_TO_USER_SCHEMA, LOAD_REFERENCE_SCHEMA, talk_to_user
from .tool_helpers import is_standardized_error, make_error_result

logger = logging.getLogger(__name__)


def classify_tool_calls(
    tool_calls: List,
    tool_registry: Dict[str, ToolDefinition],
) -> List[tuple]:
    """
    Classify each tool call by looking up its name in the tool registry.

    Returns a list of (ToolCallInfo, kind, ToolDefinition|None) tuples
    where kind is one of 'ordinary', 'interrupting', or 'unknown'.
    """
    result = []
    for tc in tool_calls:
        td = tool_registry.get(tc.name)
        if td is None:
            kind = "unknown"
        elif td.is_interrupting:
            kind = "interrupting"
        else:
            kind = "ordinary"
        result.append((tc, kind, td))
    return result


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
        self._current_tool_defs: Dict[str, ToolDefinition] = {}
        self._ctx_cache: Dict[str, ContextManager] = {}
        self._max_ctx_cache = 20  # 限制缓存大小，防止内存泄漏
        self._system_prompt_checked: Dict[str, bool] = {}  # 缓存 system prompt 检查结果
        self._msg_repo = MessageRepository()  # 复用 MessageRepository，避免每次重建

        logger.debug(
            f"[Agent Loop] 初始化: {config.agent_type.value}, "
            f"max_iterations={config.max_iterations}"
        )

    def format_system_prompt(self, **kwargs) -> str:
        """
        格式化 system prompt 模板变量（如 {recording_id}）。

        Orchestrator 在首次启动 Agent 前调用，避免直接访问 _config 私有属性。
        只替换明确传入的占位符（如 {recording_id}），其余内容原样保留。
        使用 safe_format_template 而非 format_map，避免 prompt 中的代码示例（含 {…} 的 JSON/Python
        片段）触发 ValueError: Invalid format specifier。
        """
        return safe_format_template(self._config.system_prompt, **kwargs)

    def _get_context_manager(self, session_id: str) -> ContextManager:
        """
        获取或创建 ContextManager（带缓存）

        Args:
            session_id: 会话 ID

        Returns:
            ContextManager 实例
        """
        if session_id not in self._ctx_cache:
            # 淘汰：超出上限时移除最早的缓存
            if len(self._ctx_cache) >= self._max_ctx_cache:
                oldest_key = next(iter(self._ctx_cache))
                del self._ctx_cache[oldest_key]
                self._system_prompt_checked.pop(oldest_key, None)  # 同步清理
            self._ctx_cache[session_id] = ContextManager(session_id, self._unified_config)
        return self._ctx_cache[session_id]

    def _has_system_prompt(self, session_id: str) -> bool:
        """
        检查会话是否已有 system prompt（结果按 session_id 缓存，含 False）

        Args:
            session_id: 会话 ID

        Returns:
            是否已有 system prompt
        """
        if session_id in self._system_prompt_checked:
            return self._system_prompt_checked[session_id]
        first_msg = self._msg_repo.get_first(session_id)
        result = first_msg is not None and first_msg.role == "system"
        self._system_prompt_checked[session_id] = result
        return result

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
                logger.debug(
                    f"[Agent Loop] LLM 回复 (iteration={iteration}): {response.content or ''}"
                )
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

    def _execute_tool_call(
        self,
        tool_call: ToolCallInfo,
        tool_handlers: Dict[str, Callable],
    ) -> Union[str, ToolSignal]:
        """
        执行单个工具调用

        查找工具 handler 并执行，处理未知工具。
        不处理 ToolSignal 判断 -- 由 _handle_tool_result 负责。

        Args:
            tool_call: 工具调用信息
            tool_handlers: 工具名称到 handler 的映射

        Returns:
            工具执行结果（str 或 ToolSignal）
        """
        handler = tool_handlers.get(tool_call.name)
        if handler is None:
            return f"错误：未知工具 '{tool_call.name}'"

        return handler(**tool_call.args)

    def _handle_tool_result(
        self,
        result: Union[str, ToolSignal],
        tool_call: ToolCallInfo,
        ctx: ContextManager,
    ) -> Optional[AgentResult]:
        """
        处理工具执行结果

        检查是否为 ToolSignal（工具要求中断循环），根据 result_type 决定
        是否提前返回 AgentResult。普通结果保存后返回 None（继续循环）。

        Args:
            result: 工具执行结果（str 或 ToolSignal）
            tool_call: 工具调用信息
            ctx: 上下文管理器

        Returns:
            AgentResult 表示应终止循环并返回，None 表示继续循环
        """
        if isinstance(result, ToolSignal):
            content = (
                result.display_text if result.save_result else "[工具执行失败，已提交分诊处理]"
            )
            ctx.save_tool_result(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=content,
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
        return None

    def _execute_tool_batch(
        self,
        tool_calls: List,
        tool_handlers: Dict[str, Callable],
        ctx: ContextManager,
    ) -> Optional[AgentResult]:
        """
        Execute a batch of tool calls with multi-tool semantics.

        - Classify all calls before execution
        - Reject mixed/interrupt batches as invalid output
        - Execute ordinary tools in order; cascade on failure
        - Handle solo interrupting tools with contract validation

        Returns AgentResult only if a solo interrupting tool succeeds;
        None otherwise (loop continues).
        """
        classified = classify_tool_calls(tool_calls, self._current_tool_defs)
        batch_size = len(classified)
        interrupting_count = sum(1 for _, k, _ in classified if k == "interrupting")

        logger.info(
            f"[Agent Loop] 工具批次: {batch_size} 个调用 "
            f"(中断型={interrupting_count}, 普通={batch_size - interrupting_count})"
        )

        # T007: Invalid-output batch check
        if batch_size > 1 and interrupting_count > 0:
            logger.info(
                f"[Agent Loop] 非法混合工具调用: {batch_size} 个调用中有 "
                f"{interrupting_count} 个中断型，拒绝执行"
            )
            for tc, _, _ in classified:
                self._save_error(tc, ctx, "invalid_model_output",
                                 "同轮响应包含中断型工具与其他工具调用，不执行任何工具。请重新输出合法工具调用。")
            return None

        # Solo interrupting tool
        if batch_size == 1 and interrupting_count == 1:
            tc, _, _ = classified[0]
            return self._execute_solo_interrupt(tc, tool_handlers, ctx)

        # Ordinary batch (all ordinary or unknown)
        first_failure = None
        for i, (tc, kind, _) in enumerate(classified):
            if first_failure is not None:
                self._save_error(tc, ctx, "not_executed",
                                 "前序工具失败，跳过执行。请基于已有结果重新规划。",
                                 upstream_tool_call_id=classified[i - 1][0].id if i > 0 else None)
                continue

            # Unknown tool
            if kind == "unknown":
                self._save_error(tc, ctx, "unknown_tool", f"未知工具 '{tc.name}'，无法执行。")
                first_failure = i + 1
                continue

            # Execute ordinary tool
            try:
                result = self._execute_tool_call(tc, tool_handlers)
            except Exception as e:
                self._save_error(tc, ctx, "handler_exception", f"工具 '{tc.name}' 执行异常: {e}")
                logger.warning(f"[Agent Loop] 工具执行异常: {tc.name} -> {e}")
                first_failure = i + 1
                continue

            # Contract validation: any ToolSignal in ordinary batch is a violation
            if isinstance(result, ToolSignal):
                self._save_error(tc, ctx, "handler_contract_violation",
                                 f"工具 '{tc.name}' 声明为普通工具但返回了 ToolSignal。")
                first_failure = i + 1
                continue

            # Persist result (standardized error or success)
            ctx.save_tool_result(tool_call_id=tc.id, tool_name=tc.name, content=result)
            if is_standardized_error(result):
                first_failure = i + 1
            else:
                logger.debug(f"[Agent Loop] 工具结果: {tc.name} -> {str(result)[:100]}")

        if first_failure is not None:
            logger.info(f"[Agent Loop] 批次执行中断: 在第 {first_failure} 个调用处失败")
        else:
            logger.info(f"[Agent Loop] 批次执行完成: {batch_size} 个调用全部处理")

        return None

    def _save_error(self, tc: ToolCallInfo, ctx: ContextManager, error_code: str, message: str, **extra):
        """Save a standardized error result for a tool call."""
        ctx.save_tool_result(
            tool_call_id=tc.id,
            tool_name=tc.name,
            content=make_error_result(error_code, message, **extra),
        )

    def _execute_solo_interrupt(
        self,
        tc,
        tool_handlers: Dict[str, Callable],
        ctx: ContextManager,
    ) -> Optional[AgentResult]:
        """Execute a solo interrupting tool with contract validation."""
        try:
            result = self._execute_tool_call(tc, tool_handlers)
        except Exception as e:
            self._save_error(tc, ctx, "handler_exception", f"中断型工具 '{tc.name}' 执行异常: {e}")
            logger.warning(f"[Agent Loop] 中断型工具异常: {tc.name} -> {e}")
            return None

        # Contract validation: is_interrupting=True must return ToolSignal
        if not isinstance(result, ToolSignal):
            self._save_error(tc, ctx, "handler_contract_violation",
                             f"中断型工具 '{tc.name}' 返回了 str 而非 ToolSignal。")
            return None

        # Valid interrupt: use existing _handle_tool_result path
        return self._handle_tool_result(result, tc, ctx)

    def _process_llm_response(
        self,
        response: LLMResponse,
        ctx: ContextManager,
    ) -> Union[AgentResult, List[ToolCallInfo]]:
        """
        处理 LLM 响应

        保存 assistant 消息，处理文本响应（转为用户输入或完成），
        解析工具调用。调用方根据返回类型判断下一步：
        - AgentResult: 终止循环并返回该结果
        - list[ToolCallInfo]: 完整的工具调用列表（可能包含多个）

        Args:
            response: LLM 响应对象
            ctx: 上下文管理器

        Returns:
            AgentResult 表示终止循环，list[ToolCallInfo] 表示需要执行的工具调用列表
        """
        ctx.save_assistant_message(
            content=response.content or "",
            tool_calls=(
                json.dumps(
                    [{"id": tc.id, "name": tc.name, "args": tc.args} for tc in response.tool_calls]
                )
                if response.has_tool_calls
                else None
            ),
        )

        if not response.has_tool_calls:
            if self._config.text_as_user_input and response.content:
                ctx.update_session_status("suspended")
                logger.info(f"[Agent Loop] 文字回复转为用户输入等待: {ctx.session_id}")
                return AgentResult(
                    result_type=ResultType.NEEDS_USER_INPUT,
                    question=response.content,
                )
            ctx.update_session_status("completed")
            logger.info(f"[Agent Loop] 完成（无工具调用）: {ctx.session_id}")
            return AgentResult(
                result_type=ResultType.COMPLETED,
            )

        tool_call_list = list(response.tool_calls)
        logger.debug(
            f"[Agent Loop] 工具调用 ({len(tool_call_list)} 个): "
            + ", ".join(tc.name for tc in tool_call_list)
        )
        return tool_call_list

    def _initialize_session(
        self,
        ctx: ContextManager,
        session_id: str,
        user_input: Optional[Union[str, dict]],
        system_prompt_override: Optional[str],
    ) -> Optional[AgentResult]:
        """
        会话初始化：设置 system prompt、处理用户输入、恢复会话状态。

        Args:
            ctx: 上下文管理器
            session_id: 会话 ID
            user_input: 用户输入
            system_prompt_override: 系统提示覆盖

        Returns:
            AgentResult 表示应提前终止循环（如等待用户输入），None 表示继续。
        """
        # 初始化 system prompt
        if not self._has_system_prompt(session_id):
            prompt = system_prompt_override or self._config.system_prompt
            ctx.save_message(role="system", content=prompt)
            self._system_prompt_checked[session_id] = True
            logger.debug(f"[Agent Loop] 已设置 system prompt: {session_id}")

        # 无新输入时检查是否需要等待用户
        if user_input is None:
            last_msg = ctx.get_last_message()
            if last_msg and last_msg.role == "assistant" and last_msg.content:
                ctx.update_session_status("suspended")
                logger.info(f"[Agent Loop] 最后一条是 assistant，等待用户输入: {session_id}")
                return AgentResult(
                    result_type=ResultType.NEEDS_USER_INPUT,
                    question=last_msg.content,
                )

        # 恢复已完成/失败的会话
        session_status = ctx.get_session_status()
        if session_status in ("completed", "failed"):
            ctx.update_session_status("active")
            logger.debug(f"[Agent Loop] 会话恢复（{session_status} → active）: {session_id}")

        # 保存用户输入
        if user_input is not None:
            if isinstance(user_input, dict):
                role = user_input.get("role")
                content = user_input.get("content")
                if not role or not content:
                    logger.warning(
                        f"[Agent Loop] dict user_input 缺少 'role' 或 'content': {user_input}"
                    )
                    return AgentResult(
                        result_type=ResultType.ERROR,
                        error="user_input dict 缺少 'role' 或 'content'",
                    )
                ctx.save_message(role=role, content=content)
                logger.debug(f"[Agent Loop] 输入({role}): {content[:50]}...")
            else:
                ctx.save_user_message(user_input)
                logger.debug(f"[Agent Loop] 用户输入: {user_input[:50]}...")

        return None

    def _resolve_pending_tool_call(self, pending_tc: dict) -> ToolCallInfo:
        """
        从会话中恢复待重试的工具调用。

        Args:
            pending_tc: 待重试的工具调用字典（包含 id/name/args）

        Returns:
            ToolCallInfo 对象
        """
        tool_call = ToolCallInfo(
            id=pending_tc.get("id", ""),
            name=pending_tc["name"],
            args=pending_tc.get("args", {}),
        )
        logger.debug(f"[Agent Loop] 重试待执行工具: {tool_call.name}")
        return tool_call

    def run(
        self,
        session_id: str,
        user_input: Optional[Union[str, dict]] = None,
        tools: Optional[Union[List[ToolDefinition], Callable[[], List[ToolDefinition]]]] = None,
        system_prompt_override: Optional[str] = None,
    ) -> AgentResult:
        """
        执行 Agent 循环

        Args:
            session_id: 会话 ID
            user_input: 用户输入（可选）。
                str: 普通用户输入，以 user 角色存储。
                dict: {"role": "program"/"agent"/"user", "content": "..."}，
                以指定角色存储（如分诊修复通知用 program 角色）。
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

        # 会话初始化（设置 prompt、处理输入、恢复状态）
        init_result = self._initialize_session(ctx, session_id, user_input, system_prompt_override)
        if init_result is not None:
            return init_result

        # 构建工具 schemas 和 handlers 的辅助函数
        def _rebuild_tools(tool_defs: List[ToolDefinition], ctx: ContextManager):
            nonlocal all_tool_schemas, tool_handlers
            # Build unified tool definitions (single source of truth)
            self._current_tool_defs = {td.name: td for td in tool_defs}
            self._current_tool_defs["load_reference"] = ToolDefinition(
                name="load_reference",
                schema=LOAD_REFERENCE_SCHEMA,
                handler=lambda reference_id: ctx.load_reference(reference_id),
                is_interrupting=False,
            )
            # text_as_user_input=True 时，LLM 直接输出文本即可与用户对话，
            # 不需要 talk_to_user 工具（避免 LLM 在该调 submit 时误调 talk_to_user）
            if not self._config.text_as_user_input:
                self._current_tool_defs["talk_to_user"] = ToolDefinition(
                    name="talk_to_user",
                    schema=TALK_TO_USER_SCHEMA,
                    handler=talk_to_user,
                    is_interrupting=True,
                )
            # Derive handlers and schemas from unified definitions
            tool_handlers = {name: td.handler for name, td in self._current_tool_defs.items()}
            all_tool_schemas = [td.schema for td in tool_defs] + [
                self._current_tool_defs[k].schema
                for k in ("load_reference", "talk_to_user")
                if k in self._current_tool_defs
            ]

        _tools_callable = callable(tools)
        all_tool_schemas: list = []
        tool_handlers: Dict[str, Callable] = {}
        _last_tool_names: Optional[frozenset] = None
        if not _tools_callable:
            _rebuild_tools(tools or [], ctx)

        # 检查是否有待重试的工具调用（多工具恢复）
        _pending_tcs = ctx.get_pending_tool_calls()
        if _pending_tcs:
            logger.info(
                f"[Agent Loop] 恢复待执行工具: {len(_pending_tcs)} 个未配对调用 "
                f"({', '.join(tc.get('name', '?') for tc in _pending_tcs)})"
            )

        # 主循环
        iteration = 0
        while iteration < self._config.max_iterations:
            iteration += 1

            if _tools_callable:
                new_tools = tools()
                new_names = frozenset(td.name for td in new_tools)
                if new_names != _last_tool_names:
                    _rebuild_tools(new_tools, ctx)
                    _last_tool_names = new_names

            if _pending_tcs:
                # 恢复：将所有待重试的工具调用作为单个批次处理
                tool_call_list = [
                    self._resolve_pending_tool_call(tc_dict) for tc_dict in _pending_tcs
                ]
                _pending_tcs = None
                signal = self._execute_tool_batch(tool_call_list, tool_handlers, ctx)
                if signal is not None:
                    return signal
                continue
            else:
                # 组装上下文，调用 LLM
                messages = ctx.assemble_context()
                logger.debug(f"[Agent Loop] 迭代 {iteration}: 组装了 {len(messages)} 条消息")

                response = self._call_llm_with_retry(messages, all_tool_schemas, iteration)
                if response is None:
                    ctx.update_session_status("failed")
                    return AgentResult(result_type=ResultType.ERROR, error="LLM 调用失败")

                llm_outcome = self._process_llm_response(response, ctx)
                if isinstance(llm_outcome, AgentResult):
                    return llm_outcome
                tool_call_list = llm_outcome

            # 多工具调用：执行列表中的所有工具调用
            signal = self._execute_tool_batch(tool_call_list, tool_handlers, ctx)
            if signal is not None:
                return signal

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
