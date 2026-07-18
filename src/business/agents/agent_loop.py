"""
Agent Loop 核心

提供简洁的 while 循环驱动的 Agent 运行引擎。
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from contextvars import copy_context
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from src.business.ai.llm_client import LangChainLLMClient, LLMResponse, ToolCallInfo
from src.business.debug.context import TraceContext
from src.data.unified_config import UnifiedConfigManager
from src.business.memory.context_manager import ContextManager
from src.data.repositories import MessageRepository, SessionRepository
from src.utils.events import emit
from src.utils.helpers import safe_format_template, walk_exception_chain

from . import run_context
from .config import (
    AgentConfig,
    AgentResult,
    AgentType,
    ResultType,
    RetryConfig,
    ToolDefinition,
    ToolSignal,
)
from .builtin_tools import LOAD_REFERENCE_SCHEMA
from .delegation_context import use_llm_messages_snapshot
from .hook_models import ToolCallContext, ToolExecutionOutcome, freeze_tool_args
from .tool_helpers import is_standardized_error, make_error_result
from .tools.builtin_contracts import (
    UPGRADED_BUILTIN_TOOL_NAMES,
    is_tool_failure_result,
    use_tool_runtime,
)
from .tools.builtin_config import get_config_int
from .tools.builtin_general_tools import ALL_BUILTIN_GENERAL_TOOL_NAMES
from .tools.output_governance import (
    govern_tool_result,
    governance_double_failure_fallback,
    governance_failure_fallback,
)

logger = logging.getLogger(__name__)

_INJECTED_TOOL_NAMES = frozenset({"load_reference"})
_DEFAULT_PARALLEL_WORKERS = 4
_ASSISTANT_FORBIDDEN_DYNAMIC_TOOL_PREFIXES = ("utool_", "comp_")

# 活动事件文本截断上限（projector 还会再走 009 payload allowlist 脱敏）。
_ACTIVITY_TEXT_LIMIT = 2000


def _activity_payload_text(value: Any) -> Any:
    """Preserve structured values so the UI-event safety layer can inspect keys."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:_ACTIVITY_TEXT_LIMIT]
    return value


# LLM 调用最终失败的"可恢复性"分类标记。
# 仅账户配额/限流/网络这类"需等外部恢复"的失败才允许转可唤回暂停（见 spec Assumptions）；
# 不可恢复错误（400 bad request、认证/校验、序列化或代码 bug）仍按既有 ERROR 处理，
# 避免把永久性错误误标为"等账单/网络恢复后续跑"，造成主代理无效等待。
_RECOVERABLE_LLM_ERROR_MARKERS = (
    "429",
    "rate limit",
    "ratelimit",
    "too many requests",
    "quota",
    "insufficient_quota",
    "billing",
    "credit balance",
    "insufficient credit",
    "overloaded",
    "529",
    "timeout",
    "temporarily unavailable",
    "service unavailable",
    "502",
    "503",
    "504",
)
_RECOVERABLE_LLM_ERROR_TYPES = (
    "ratelimiterror",
    "apiconnectionerror",
    "apitimeouterror",
    "internalservererror",
    "serviceunavailable",
    "overloadederror",
    "connectionerror",
    "connecttimeout",
    "readtimeout",
    "timeout",
)


def _is_recoverable_llm_failure(exc: BaseException) -> bool:
    """判断 LLM 调用最终失败是否属于"需等外部恢复"的账户配额/限流/网络类。

    遍历异常链（`__cause__` / `__context__`），按异常类型名与消息文本做标记匹配。
    无法确定时保守返回 False（按不可恢复处理），宁可如实失败也不误导主代理等待。
    """
    for node in walk_exception_chain(exc):
        type_name = type(node).__name__.lower()
        if any(marker in type_name for marker in _RECOVERABLE_LLM_ERROR_TYPES):
            return True
        message = str(node).lower()
        if any(marker in message for marker in _RECOVERABLE_LLM_ERROR_MARKERS):
            return True
    return False


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


def _serialize_tool_calls(tool_calls: List[ToolCallInfo]) -> str:
    """序列化 assistant tool_calls 为持久化 JSON（id/name/args，与 005/003 配对口径一致）。"""
    return json.dumps(
        [{"id": tc.id, "name": tc.name, "args": tc.args} for tc in tool_calls],
        ensure_ascii=False,
    )


class AgentLoop:
    """
    Agent Loop 运行时引擎

    简洁的 while 循环驱动，支持：
    - 单工具调用模式（parallel_tool_calls=False）
    - 中断型工具哨兵机制（如 reply_to_user / ask_parent）
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
        # 优先从 unified_config 读取 retry 配置；getter 自带默认值与边界校验。
        # AgentConfig.retry 仅保留为构造签名的一部分，运行时不再消费。
        self._retry = RetryConfig(
            max_retries=unified_config.get_ai_retry_max_retries(),
            retry_delay=unified_config.get_ai_retry_delay(),
        )
        self._current_tool_defs: Dict[str, ToolDefinition] = {}
        self._ctx_cache: Dict[str, ContextManager] = {}
        self._max_ctx_cache = 20  # 限制缓存大小，防止内存泄漏
        self._system_prompt_checked: Dict[str, bool] = {}  # 缓存 system prompt 检查结果
        self._msg_repo = MessageRepository()  # 复用 MessageRepository，避免每次重建
        self._session_repo = SessionRepository()

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

    def _call_llm_with_retry(
        self,
        messages: list,
        tools: list,
        iteration: int,
        session_id: str = "",
        workflow_id: str | None = None,
    ) -> tuple[Optional[LLMResponse], bool]:
        """
        调用 LLM（带重试机制）

        任何异常都会触发重试，最多 max_retries 次。退避策略为指数：
        delay = retry_delay * 2 ** retry_count。

        Args:
            messages: 消息列表
            tools: 工具列表
            iteration: 当前迭代次数

        Returns:
            (LLMResponse 或 None, 最终失败是否为可恢复失败)。
            可恢复失败指账户配额/限流/网络类"需等外部恢复"的失败。
        """
        retry_config: RetryConfig = self._retry

        for retry_count in range(retry_config.max_retries + 1):
            try:
                with TraceContext(
                    source="agent_loop",
                    agent_type=self._config.agent_type.value,
                    session_id=session_id,
                    workflow_id=workflow_id or "",
                    iteration=iteration,
                ):
                    response = self._llm.chat_with_tools(messages, tools)
                logger.debug(
                    "[Agent Loop] LLM 回复: iteration=%s text_chars=%s tool_calls=%s",
                    iteration,
                    len(response.content or ""),
                    len(response.tool_calls),
                )
                if response.has_tool_calls:
                    logger.debug(f"[Agent Loop] LLM 工具调用: {response.tool_calls[0].name}")
                return response, False

            except Exception as e:
                if retry_count >= retry_config.max_retries:
                    recoverable = _is_recoverable_llm_failure(e)
                    logger.error(
                        "[Agent Loop] LLM 调用最终失败: error_type=%s recoverable=%s",
                        type(e).__name__,
                        recoverable,
                    )
                    return None, recoverable
                delay = retry_config.retry_delay * (2**retry_count)
                logger.warning(
                    "[Agent Loop] LLM 调用失败: error_type=%s, 等待 %ss 后重试 (%s/%s)",
                    type(e).__name__,
                    delay,
                    retry_count + 1,
                    retry_config.max_retries,
                )
                # 走可中断 sleep：用户在退避窗口里点 Stop 时，cancel_event 立刻唤醒，
                # 让外层 _cancellation_result 在下一轮迭代起点收敛到 suspended，
                # 而不是先白等满指数退避（最多 4s+）再触发取消检查。
                run_ctx = run_context.get_current()
                if run_ctx is not None:
                    run_ctx.cancel_event.wait(timeout=delay)
                else:
                    time.sleep(delay)

        return None, False

    def _get_workflow_id(self, session_id: str) -> str | None:
        session = self._session_repo.get_by_id(session_id)
        return getattr(session, "workflow_id", None) if session else None

    def _cancellation_result(self, ctx: ContextManager) -> Optional[AgentResult]:
        """协作式取消检查（014）。

        命中当前运行上下文的 cancel_event → 置会话 suspended 并返回 CANCELLED。
        非助理流程从不 begin 运行上下文 → get_current() 为 None → 恒不取消（零行为变化）。
        同线程同步派出的子 loop 读到的是父的 cancel_event，故父被停时子 loop 也在安全节点退出。
        """
        run_ctx = run_context.get_current()
        if run_ctx is not None and run_ctx.cancel_event.is_set():
            ctx.update_session_status("suspended")
            logger.info("[Agent Loop] 协作式取消命中，会话置 suspended: %s", ctx.session_id)
            return AgentResult(result_type=ResultType.CANCELLED)
        return None

    def _emit_activity(
        self,
        ctx: ContextManager,
        kind: str,
        *,
        tool_name: Optional[str] = None,
        text: Any = "",
    ) -> None:
        """逐步活动事件 emit（014，best-effort）。

        仅在可观测运行（run_context 存在，即助理/子代理/专员链路）时发出——非助理流程
        （PM/Programmer/Trial）ContextVar 空 → 零 emit、零行为变化（E4/CC-005）。
        session_id 取 root（子代理活动也归到父会话），subagent_id 为自身 session（≠root 时）。
        """
        run_ctx = run_context.get_current()
        if run_ctx is None:
            return
        seq = run_context.next_activity_seq()
        if seq is None or seq > run_context.MAX_ACTIVITY_EVENTS_PER_RUN:
            return  # 单回合上限，防极端长回合刷爆前端 store
        subagent_id = ctx.session_id if ctx.session_id != run_ctx.root_session_id else None
        emit(
            "assistant_agent_step",
            session_id=run_ctx.root_session_id,
            subagent_id=subagent_id,
            agent_type=self._config.agent_type.value,
            kind=kind,
            tool_name=tool_name,
            text=_activity_payload_text(text),
            seq=seq,
        )

    def _execute_tool_call(
        self,
        tool_call: ToolCallInfo,
        tool_def: ToolDefinition,
        session_id: str,
        iteration: int,
    ) -> ToolExecutionOutcome:
        """
        Execute one ToolDefinition call with tool/global hook semantics.

        The returned failure flag reflects the original execution outcome and is
        intentionally independent from any post-hook rewrite.
        """
        run_hooks = self._has_hooks(tool_def)
        context = None
        skip_post_hooks = False

        runtime_context = (
            use_tool_runtime(
                session_id=session_id,
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                workspace_root=self._config.workspace_root or Path.cwd(),
            )
            if tool_call.name in UPGRADED_BUILTIN_TOOL_NAMES
            else nullcontext()
        )

        handler_result: Union[str, ToolSignal]
        failed = False
        failure_code: str | None = None

        try:
            with runtime_context:
                # pre_hook 必须在 tool runtime context 内执行，使其 permission 检查与
                # handler 用同一个 workspace_root（注入值）；否则 pre_hook 回退 cwd，
                # 会让注入的 workspace 重定向在 pre_hook 层失效（D4 承重假设）。
                if run_hooks:
                    context = self._build_tool_context(tool_call, session_id, iteration)
                    rejected, pre_hook_exc = self._run_pre_hooks(tool_def, context)
                    if rejected is not None:
                        return rejected
                    skip_post_hooks = pre_hook_exc
                handler_result = tool_def.handler(**tool_call.args)
        except Exception as exc:
            failure_code = "handler_exception"
            failed = True
            message = f"工具 '{tool_call.name}' 执行异常: {exc}"
            logger.warning(
                "[Agent Loop] 工具执行异常: tool=%s error_type=%s",
                tool_call.name,
                type(exc).__name__,
            )
            handler_result = make_error_result(failure_code, message)

        if isinstance(handler_result, ToolSignal):
            if tool_def.is_interrupting:
                return ToolExecutionOutcome(handler_result, failed=False)
            return ToolExecutionOutcome(
                make_error_result(
                    "handler_contract_violation",
                    f"工具 '{tool_call.name}' 声明为普通工具但返回了 ToolSignal。",
                ),
                failed=True,
                failure_code="handler_contract_violation",
            )

        if tool_def.is_interrupting and failed:
            return ToolExecutionOutcome(
                handler_result,
                failed=True,
                failure_code=failure_code,
            )

        if tool_def.is_interrupting:
            return ToolExecutionOutcome(
                make_error_result(
                    "handler_contract_violation",
                    f"中断型工具 '{tool_call.name}' 返回了 str 而非 ToolSignal。",
                ),
                failed=True,
                failure_code="handler_contract_violation",
            )

        if not isinstance(handler_result, str):
            return ToolExecutionOutcome(
                make_error_result(
                    "handler_contract_violation",
                    f"工具 '{tool_call.name}' handler 返回了不支持的结果类型。",
                ),
                failed=True,
                failure_code="handler_contract_violation",
            )

        if is_standardized_error(handler_result) or is_tool_failure_result(handler_result):
            failed = True
            failure_code = failure_code or "standardized_error"

        final_result = handler_result
        if run_hooks and not skip_post_hooks and context is not None:
            final_result = self._run_post_hooks(tool_def, context, handler_result)

        return ToolExecutionOutcome(final_result, failed=failed, failure_code=failure_code)

    def _build_tool_context(
        self,
        tool_call: ToolCallInfo,
        session_id: str,
        iteration: int,
    ) -> ToolCallContext:
        return ToolCallContext(
            tool_name=tool_call.name,
            args=freeze_tool_args(tool_call.args),
            session_id=session_id,
            agent_type=self._config.agent_type,
            iteration=iteration,
        )

    def _assistant_forbidden_tool_reason(self, tool_name: str) -> str | None:
        if self._config.agent_type != AgentType.ASSISTANT:
            return None
        if tool_name in ALL_BUILTIN_GENERAL_TOOL_NAMES:
            return (
                f"主助理不能直接调用工具 '{tool_name}'。读取、抓取、进程和执行类能力"
                "必须先委派给临时子代理或固定专员。"
            )
        if tool_name.startswith(_ASSISTANT_FORBIDDEN_DYNAMIC_TOOL_PREFIXES):
            return (
                f"主助理不能直接调用动态执行工具 '{tool_name}'。"
                "请使用 delegate_to_subagent 或 delegate_to_specialist 派执行体完成。"
            )
        return None

    def _reject_assistant_forbidden_tool_calls(
        self,
        classified: List[tuple],
        ctx: ContextManager,
    ) -> bool:
        reasons = {
            tc.id: reason
            for tc, _, _ in classified
            if (reason := self._assistant_forbidden_tool_reason(tc.name)) is not None
        }
        if not reasons:
            return False
        for tc, _, _ in classified:
            reason = reasons.get(tc.id)
            if reason is not None:
                self._save_error(tc, ctx, "assistant_tool_forbidden", reason)
            else:
                self._save_error(
                    tc,
                    ctx,
                    "invalid_model_output",
                    "同轮响应包含主助理禁止直接调用的工具，本批次不执行任何工具。"
                    "请先委派给临时子代理或固定专员。",
                )
        return True

    def _has_hooks(self, tool_def: ToolDefinition) -> bool:
        if tool_def.name in _INJECTED_TOOL_NAMES:
            return False
        return (
            tool_def.pre_hook is not None
            or tool_def.post_hook is not None
            or bool(self._config.global_pre_hooks)
            or bool(self._config.global_post_hooks)
        )

    def _run_pre_hooks(
        self,
        tool_def: ToolDefinition,
        context: ToolCallContext,
    ) -> tuple[ToolExecutionOutcome | None, bool]:
        hooks = []
        if tool_def.pre_hook is not None:
            hooks.append(("tool pre_hook", tool_def.pre_hook))
        hooks.extend(("global pre_hook", hook) for hook in self._config.global_pre_hooks)

        for label, hook in hooks:
            try:
                result = hook(context)
            except Exception as exc:
                logger.warning(
                    "[Agent Loop] %s 异常: %s -> %s",
                    label,
                    context.tool_name,
                    exc,
                    exc_info=True,
                )
                return (
                    ToolExecutionOutcome(
                        make_error_result(
                            "pre_hook_exception",
                            f"工具 '{context.tool_name}' 执行前检查异常，已拒绝执行。",
                        ),
                        failed=True,
                        failure_code="pre_hook_exception",
                    ),
                    False,
                )
            if result is not None and result.error is not None:
                error_code = result.error_code or "pre_hook_rejected"
                return (
                    ToolExecutionOutcome(
                        make_error_result(error_code, result.error),
                        failed=True,
                        failure_code=error_code,
                    ),
                    False,
                )
        return None, False

    def _run_post_hooks(
        self,
        tool_def: ToolDefinition,
        context: ToolCallContext,
        handler_result: str,
    ) -> str:
        final_result = handler_result
        hooks = []
        if tool_def.post_hook is not None:
            hooks.append(("tool post_hook", tool_def.post_hook))
        hooks.extend(("global post_hook", hook) for hook in self._config.global_post_hooks)

        for label, hook in hooks:
            try:
                result = hook(context, handler_result)
            except Exception as exc:
                logger.warning(
                    "[Agent Loop] %s 异常: %s -> %s",
                    label,
                    context.tool_name,
                    exc,
                    exc_info=True,
                )
                return handler_result
            if result is not None and result.result is not None:
                final_result = result.result
        return final_result

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
            self._persist_tool_result(tool_call, ctx, content)
            # 携带 ToolSignal 的 display_text 到 ToolCallInfo
            signal_call_info = ToolCallInfo(
                id=tool_call.id,
                name=tool_call.name,
                args=tool_call.args,
                display_text=result.display_text,
            )
            if result.result_type == ResultType.NEEDS_USER_INPUT:
                ctx.update_session_status("suspended")
                question = (
                    tool_call.args.get("message")
                    or tool_call.args.get("text")
                    or result.display_text
                    or ""
                )
                if tool_call.name == "reply_to_user" and result.display_text:
                    ctx.save_assistant_message(content=result.display_text)
                logger.info("[Agent Loop] 需要用户输入: chars=%s", len(question))
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
        self._persist_tool_result(tool_call, ctx, result)
        logger.debug(
            "[Agent Loop] 工具结果: tool=%s result_chars=%s",
            tool_call.name,
            len(str(result)),
        )
        return None

    def _persist_tool_result(
        self,
        tool_call: ToolCallInfo,
        ctx: ContextManager,
        content: str,
    ) -> str:
        """Govern and persist exactly one tool result for a tool call."""
        final_content = self._govern_tool_result(tool_call, ctx, content)
        self._save_governed_tool_result(tool_call, ctx, final_content)
        return final_content

    def _govern_tool_result(
        self,
        tool_call: ToolCallInfo,
        ctx: ContextManager,
        content: str,
    ) -> str:
        """Apply output governance without mutating conversation state."""
        final_content = content
        if isinstance(content, str):
            try:
                final_content = govern_tool_result(
                    tool_name=tool_call.name,
                    tool_call_id=tool_call.id,
                    session_id=ctx.session_id,
                    content=content,
                    tool_args=tool_call.args,
                    workspace_root=self._config.workspace_root or Path.cwd(),
                )
            except Exception:
                logger.warning(
                    "[Agent Loop] tool result governance failed: tool=%s",
                    tool_call.name,
                    exc_info=True,
                )
                try:
                    final_content = governance_failure_fallback(
                        tool_name=tool_call.name,
                        content=content,
                    )
                except Exception:
                    final_content = governance_double_failure_fallback(
                        tool_name=tool_call.name,
                    )
        return final_content

    def _save_governed_tool_result(
        self,
        tool_call: ToolCallInfo,
        ctx: ContextManager,
        content: str,
    ) -> None:
        """Persist one already-governed result and emit its ordered activity event."""
        ctx.save_tool_result(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            content=content,
        )
        self._emit_activity(ctx, "tool_result", tool_name=tool_call.name, text=content)

    def _execute_and_govern_tool_call(
        self,
        tool_call: ToolCallInfo,
        tool_def: ToolDefinition,
        ctx: ContextManager,
        session_id: str,
        iteration: int,
    ) -> tuple[ToolExecutionOutcome, str]:
        """Execute and govern a safe call in a worker without persisting it."""
        outcome = self._execute_tool_call(tool_call, tool_def, session_id, iteration)
        governed = self._govern_tool_result(tool_call, ctx, outcome.result)
        return outcome, governed

    @staticmethod
    def _partition_tool_calls(
        classified: List[tuple],
    ) -> List[tuple[bool, List[tuple]]]:
        """Group contiguous concurrency-safe read calls while keeping serial barriers.

        Partition items share the classified-item shape ``(tool_call, kind, tool_def)``;
        order is preserved by construction, so no positional index is carried.
        """
        partitions: List[tuple[bool, List[tuple]]] = []
        current_parallel: List[tuple] = []

        for item in classified:
            _, kind, tool_def = item
            concurrency_safe = (
                kind == "ordinary"
                and tool_def is not None
                and tool_def.is_concurrency_safe
                and not tool_def.has_side_effects
            )
            if concurrency_safe:
                current_parallel.append(item)
                continue

            if current_parallel:
                partitions.append((True, current_parallel))
                current_parallel = []
            partitions.append((False, [item]))

        if current_parallel:
            partitions.append((True, current_parallel))
        return partitions

    def _execute_parallel_partition(
        self,
        partition: List[tuple],
        ctx: ContextManager,
        session_id: str,
        iteration: int,
        executor: ThreadPoolExecutor,
    ) -> List[tuple]:
        """Execute and govern one safe partition on a shared executor.

        ``executor`` is owned by the caller (one per batch, not one per
        partition); results are returned in input order.
        """
        tool_names = [tool_call.name for tool_call, _, _ in partition]
        started = time.monotonic()
        logger.info("[Agent Loop] 并发工具分区开始: tools=%s", tool_names)
        futures = []
        for tool_call, _, tool_def in partition:
            context = copy_context()
            future = executor.submit(
                context.run,
                self._execute_and_govern_tool_call,
                tool_call,
                tool_def,
                ctx,
                session_id,
                iteration,
            )
            futures.append((tool_call, future))

        results = []
        for tool_call, future in futures:
            try:
                outcome, governed = future.result()
            except Exception as exc:
                logger.warning(
                    "[Agent Loop] 并发工具执行异常: tool=%s error_type=%s",
                    tool_call.name,
                    type(exc).__name__,
                    exc_info=True,
                )
                raw_result = make_error_result(
                    "handler_exception",
                    f"工具 '{tool_call.name}' 执行异常: {exc}",
                )
                outcome = ToolExecutionOutcome(
                    raw_result,
                    failed=True,
                    failure_code="handler_exception",
                )
                governed = self._govern_tool_result(tool_call, ctx, raw_result)
            results.append((tool_call, outcome, governed))

        logger.info(
            "[Agent Loop] 并发工具分区完成: tools=%s elapsed_ms=%s",
            tool_names,
            int((time.monotonic() - started) * 1000),
        )
        return results

    def _log_tool_result(self, tc, outcome) -> None:
        """统一的工具结果 debug 日志（并发与串行路径共用，避免格式漂移）。"""
        logger.debug(
            "[Agent Loop] 工具结果: tool=%s result_chars=%s",
            tc.name,
            len(str(outcome.result)),
        )

    def _execute_tool_batch(
        self,
        tool_calls: List,
        ctx: ContextManager,
        session_id: str,
        iteration: int,
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

        if self._reject_assistant_forbidden_tool_calls(classified, ctx):
            logger.warning(
                "[Agent Loop] 主助理越权工具调用已拒绝: %s",
                [tc.name for tc, _, _ in classified],
            )
            return None

        # Invalid-output batch check.
        if batch_size > 1 and interrupting_count > 0:
            logger.info(
                f"[Agent Loop] 非法混合工具调用: {batch_size} 个调用中有 "
                f"{interrupting_count} 个中断型，拒绝执行"
            )
            for tc, _, _ in classified:
                self._save_error(
                    tc,
                    ctx,
                    "invalid_model_output",
                    "同轮响应包含中断型工具与其他工具调用，不执行任何工具。请重新输出合法工具调用。",
                )
            return None

        # Exclusive-call batch check: an exclusive tool (e.g. ask_user_question) must be the
        # only call in its batch. Mixed with anything else → reject the entire batch as invalid
        # output with full pairing, leaving the loop to retry. Mirrors the interrupting check.
        exclusive_count = sum(
            1 for _, _, td in classified if td is not None and td.requires_exclusive_call
        )
        if batch_size > 1 and exclusive_count > 0:
            logger.info(
                f"[Agent Loop] 非法混合工具调用: {batch_size} 个调用中有 "
                f"{exclusive_count} 个需独占调用，拒绝执行"
            )
            for tc, _, _ in classified:
                self._save_error(
                    tc,
                    ctx,
                    "invalid_model_output",
                    "同轮响应包含需独占调用的工具与其他工具调用，不执行任何工具。"
                    "请单独调用该工具后再继续。",
                )
            return None

        # Solo interrupting tool
        if batch_size == 1 and interrupting_count == 1:
            tc, _, tool_def = classified[0]
            return self._execute_solo_interrupt(tc, tool_def, ctx, session_id, iteration)

        # Ordinary batch (all ordinary or unknown). Contiguous concurrency-safe
        # reads overlap on one shared executor, but serial barriers and persistence
        # retain model-provided order. A single side-effect/unknown failure cascades
        # `not_executed` onto every later call (tracked by its tool_call_id).
        failure_upstream_id: Optional[str] = None
        partitions = self._partition_tool_calls(classified)
        max_workers = get_config_int(
            "get_agent_tools_max_parallel_workers",
            _DEFAULT_PARALLEL_WORKERS,
            maximum=16,
        )
        executor: Optional[ThreadPoolExecutor] = None
        try:
            for is_parallel, partition in partitions:
                if failure_upstream_id is not None:
                    for tc, _, _ in partition:
                        self._save_error(
                            tc,
                            ctx,
                            "not_executed",
                            "前序副作用工具失败，跳过执行。请基于已有结果重新规划。",
                            upstream_tool_call_id=failure_upstream_id,
                        )
                    continue

                if is_parallel and len(partition) > 1:
                    if executor is None:
                        executor = ThreadPoolExecutor(
                            max_workers=max_workers,
                            thread_name_prefix="agent-tool",
                        )
                    for tc, outcome, governed in self._execute_parallel_partition(
                        partition,
                        ctx,
                        session_id,
                        iteration,
                        executor,
                    ):
                        self._save_governed_tool_result(tc, ctx, governed)
                        if outcome.failed:
                            logger.info(
                                "[Agent Loop] 并发分区中无副作用工具 %s 失败，不影响其他工具",
                                tc.name,
                            )
                        else:
                            self._log_tool_result(tc, outcome)
                    continue

                tc, kind, tool_def = partition[0]

                # Unknown tool — 模型幻觉，后续工具参数可能基于错误上下文，触发级联
                if kind == "unknown":
                    self._save_error(tc, ctx, "unknown_tool", f"未知工具 '{tc.name}'，无法执行。")
                    failure_upstream_id = tc.id
                    continue

                outcome = self._execute_tool_call(tc, tool_def, session_id, iteration)
                self._persist_tool_result(tc, ctx, outcome.result)
                if outcome.failed:
                    # Only cascade failure for tools with side effects
                    if tool_def.has_side_effects:
                        failure_upstream_id = tc.id
                    else:
                        logger.info(f"[Agent Loop] 无副作用工具 {tc.name} 失败，继续执行后续调用")
                else:
                    self._log_tool_result(tc, outcome)
        finally:
            if executor is not None:
                executor.shutdown(wait=True)

        if failure_upstream_id is not None:
            logger.info(
                f"[Agent Loop] 批次执行中断: 调用 {failure_upstream_id} 失败，级联跳过后续工具"
            )
        else:
            logger.info(f"[Agent Loop] 批次执行完成: {batch_size} 个调用全部处理")

        return None

    def _save_error(
        self, tc: ToolCallInfo, ctx: ContextManager, error_code: str, message: str, **extra
    ):
        """Save a standardized error result for a tool call."""
        self._persist_tool_result(tc, ctx, make_error_result(error_code, message, **extra))

    def _execute_solo_interrupt(
        self,
        tc: ToolCallInfo,
        tool_def: ToolDefinition,
        ctx: ContextManager,
        session_id: str,
        iteration: int,
    ) -> Optional[AgentResult]:
        """Execute a solo interrupting tool with contract validation."""
        outcome = self._execute_tool_call(tc, tool_def, session_id, iteration)
        if not isinstance(outcome.result, ToolSignal):
            self._persist_tool_result(tc, ctx, outcome.result)
            return None

        # Valid interrupt: use existing _handle_tool_result path
        return self._handle_tool_result(outcome.result, tc, ctx)

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
        # 有工具调用时，content 是 LLM 在调工具时附带的"思考旁白"，不应作为独立
        # 消息呈现给用户（否则和中断型工具如 reply_to_user 产生的 display message
        # 重复，用户一秒内看到两条内容几乎相同的消息）。与下方 _initial_tool_calls
        # 路径 content="" 的既有模式对齐；实时 reasoning 事件仍记录这段文本。
        ctx.save_assistant_message(
            content="" if response.has_tool_calls else (response.content or ""),
            tool_calls=(
                _serialize_tool_calls(response.tool_calls) if response.has_tool_calls else None
            ),
        )

        # 逐步活动事件（014）：仅随【带工具调用的中间消息】一同产生 reasoning，
        # 与历史重建口径一致（C2-E4）；最终无工具调用的回复走既有 display-message，不进时间线。
        if response.has_tool_calls:
            if response.content:
                self._emit_activity(ctx, "reasoning", text=response.content)
            for tc in response.tool_calls:
                self._emit_activity(
                    ctx,
                    "tool_call",
                    tool_name=tc.name,
                    text=tc.args,
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
        resume_existing_turn: bool = False,
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
        if user_input is None and not resume_existing_turn:
            last_msg = ctx.get_last_message()
            if last_msg and last_msg.role == "assistant" and last_msg.content:
                ctx.update_session_status("suspended")
                logger.info(f"[Agent Loop] 最后一条是 assistant，等待用户输入: {session_id}")
                return AgentResult(
                    result_type=ResultType.NEEDS_USER_INPUT,
                    question=last_msg.content,
                )

        # 恢复已完成/失败/挂起的会话
        session_status = ctx.get_session_status()
        if session_status in ("completed", "failed", "suspended"):
            ctx.update_session_status("active")
            logger.debug(f"[Agent Loop] 会话恢复（{session_status} → active）: {session_id}")

        # 保存用户输入
        if user_input is not None and not resume_existing_turn:
            if isinstance(user_input, dict):
                role = user_input.get("role")
                content = user_input.get("content")
                if not role or not content:
                    logger.warning(
                        "[Agent Loop] dict user_input 缺少 'role' 或 'content': keys=%s",
                        sorted(str(key) for key in user_input),
                    )
                    return AgentResult(
                        result_type=ResultType.ERROR,
                        error="user_input dict 缺少 'role' 或 'content'",
                    )
                ctx.save_message(role=role, content=content)
                logger.debug("[Agent Loop] 输入: role=%s chars=%s", role, len(content))
            else:
                ctx.save_user_message(user_input)
                logger.debug("[Agent Loop] 用户输入: chars=%s", len(user_input))

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
        initial_tool_calls: Optional[List[ToolCallInfo]] = None,
        resume_existing_turn: bool = False,
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
            initial_tool_calls: 由业务层确定性注入的首批工具调用。会按普通工具调用
                语义保存 assistant(tool_calls) 与 tool result，再进入下一轮 LLM。

        Returns:
            AgentResult 对象
        """
        # 使用缓存的 ContextManager
        ctx = self._get_context_manager(session_id)
        workflow_id = self._get_workflow_id(session_id)

        # 会话初始化（设置 prompt、处理输入、恢复状态）
        init_result = self._initialize_session(
            ctx,
            session_id,
            user_input,
            system_prompt_override,
            resume_existing_turn=resume_existing_turn,
        )
        if init_result is not None:
            return init_result

        # 构建工具 schemas 和执行定义的辅助函数
        def _build_tool_registry(
            tool_defs: List[ToolDefinition],
            ctx: ContextManager,
        ) -> Dict[str, ToolDefinition]:
            registry = {td.name: td for td in tool_defs}
            # ContextManager.load_reference 内部对其共享 Repository session 加锁，
            # 因此可被并发工具安全调用。
            registry["load_reference"] = ToolDefinition(
                name="load_reference",
                schema=LOAD_REFERENCE_SCHEMA,
                handler=ctx.load_reference,
                is_interrupting=False,
                has_side_effects=False,
                is_concurrency_safe=True,
            )
            # talk_to_user 已整体移除：主助理走 reply_to_user，PM/Trial 走
            # text_as_user_input=True 的纯文本对话，子代理/专员向上沟通走 ask_parent。
            # 历史会话中已存的 talk_to_user tool_calls 仅由展示层反查兼容。
            return registry

        def _refresh_tool_defs(tool_defs: List[ToolDefinition], ctx: ContextManager):
            self._current_tool_defs = _build_tool_registry(tool_defs, ctx)

        def _rebuild_tools(tool_defs: List[ToolDefinition], ctx: ContextManager):
            nonlocal all_tool_schemas
            _refresh_tool_defs(tool_defs, ctx)
            all_tool_schemas = [td.schema for td in tool_defs] + [
                self._current_tool_defs["load_reference"].schema
            ]

        _tools_callable = callable(tools)
        all_tool_schemas: list = []
        _last_tool_names: Optional[frozenset] = None
        if not _tools_callable:
            _rebuild_tools(tools or [], ctx)

        # 检查是否有待重试的工具调用（多工具恢复）
        _pending_tcs = ctx.get_pending_tool_calls()
        _initial_tool_calls = list(initial_tool_calls or [])
        _initial_tool_calls_executed = False
        if _pending_tcs:
            logger.info(
                f"[Agent Loop] 恢复待执行工具: {len(_pending_tcs)} 个未配对调用 "
                f"({', '.join(tc.get('name', '?') for tc in _pending_tcs)})"
            )

        # 主循环
        iteration = 0
        while iteration < self._config.max_iterations:
            iteration += 1

            # 取消检查点①：每轮迭代开头。覆盖续跑/恢复路径与父子深度取消链。
            cancelled = self._cancellation_result(ctx)
            if cancelled is not None:
                return cancelled

            if _tools_callable:
                new_tools = tools()
                new_names = frozenset(td.name for td in new_tools)
                if new_names != _last_tool_names:
                    _rebuild_tools(new_tools, ctx)
                    _last_tool_names = new_names
                else:
                    _refresh_tool_defs(new_tools, ctx)

            if _pending_tcs:
                # 恢复：将所有待重试的工具调用作为单个批次处理
                tool_call_list = [
                    self._resolve_pending_tool_call(tc_dict) for tc_dict in _pending_tcs
                ]
                _pending_tcs = None
                signal = self._execute_tool_batch(tool_call_list, ctx, session_id, iteration)
                if signal is not None:
                    return signal
                continue
            elif _initial_tool_calls and not _initial_tool_calls_executed:
                _initial_tool_calls_executed = True
                ctx.save_assistant_message(
                    content="",
                    tool_calls=_serialize_tool_calls(_initial_tool_calls),
                )
                for tc in _initial_tool_calls:
                    self._emit_activity(
                        ctx,
                        "tool_call",
                        tool_name=tc.name,
                        text=tc.args,
                    )
                signal = self._execute_tool_batch(
                    _initial_tool_calls,
                    ctx,
                    session_id,
                    iteration,
                )
                if signal is not None:
                    return signal
                continue
            else:
                # 组装上下文，调用 LLM
                messages = ctx.assemble_context()
                logger.debug(f"[Agent Loop] 迭代 {iteration}: 组装了 {len(messages)} 条消息")

                response, llm_failure_recoverable = self._call_llm_with_retry(
                    messages,
                    all_tool_schemas,
                    iteration,
                    session_id,
                    workflow_id,
                )
                if response is None:
                    if self._config.resumable_on_failure and llm_failure_recoverable:
                        # 账户配额/限流/网络等"需等外部恢复"的失败：不丢工作，转可唤回暂停。
                        # 不可恢复错误（如 400/认证/校验）落入下方 ERROR，避免误导主代理等待。
                        ctx.update_session_status("suspended")
                        logger.info(
                            "[Agent Loop] 子代理暂停可唤回（LLM 调用失败，账单或网络）: %s",
                            session_id,
                        )
                        return AgentResult(
                            result_type=ResultType.PAUSED,
                            error="LLM 调用失败（账单或网络），可恢复后续跑",
                        )
                    ctx.update_session_status("failed")
                    return AgentResult(result_type=ResultType.ERROR, error="LLM 调用失败")

                llm_outcome = self._process_llm_response(response, ctx)
                if isinstance(llm_outcome, AgentResult):
                    return llm_outcome
                tool_call_list = llm_outcome

            # 取消检查点②：LLM 返回后、执行工具批次前。停止在此即时生效，避免再触发副作用工具。
            cancelled = self._cancellation_result(ctx)
            if cancelled is not None:
                return cancelled

            # 多工具调用：执行列表中的所有工具调用。
            # 快照仅在此 LLM 响应路径设置：下标引用（context_message_indexes）必须
            # 对着模型产生本批 tool_calls 时看到的 messages 解析；恢复/initial 路径
            # 原快照不可复现，不设快照（委派 fail-closed）。
            with use_llm_messages_snapshot(messages):
                signal = self._execute_tool_batch(tool_call_list, ctx, session_id, iteration)
            if signal is not None:
                return signal

        # 超过最大迭代次数
        if self._config.resumable_on_failure:
            # 可唤回 Agent（临时子代理）：撞迭代上限不算失败，转可唤回暂停，保留工作历史。
            ctx.update_session_status("suspended")
            logger.info(
                "[Agent Loop] 子代理暂停可唤回（已达迭代上限 %s 轮）: %s",
                self._config.max_iterations,
                session_id,
            )
            return AgentResult(
                result_type=ResultType.PAUSED,
                error=f"已达迭代上限（{self._config.max_iterations} 轮）",
            )
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
