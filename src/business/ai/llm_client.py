"""
通用 LLM 客户端（基于 LangChain）

支持多种提供商：
- Anthropic (Claude) - 使用专用 API
- OpenAI (GPT-4, GPT-3.5)
- DeepSeek - OpenAI 兼容 API
- 通义千问 (Qwen) - OpenAI 兼容 API
- 智谱 AI (GLM) - OpenAI 兼容 API
- Moonshot (Kimi) - OpenAI 兼容 API
- 其他兼容 OpenAI API 的服务

用于网络请求智能过滤的数据压缩模型
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from src.utils.llm_helpers import sanitize_text_for_llm
from src.utils.helpers import normalize_thinking_level

logger = logging.getLogger(__name__)

_LLM_MESSAGE_MAX_CHARS = 120_000


@dataclass
class ToolCallInfo:
    """工具调用信息"""

    id: str
    name: str
    args: Dict[str, Any]
    display_text: Optional[str] = None  # ToolSignal 时携带执行结果


@dataclass
class LLMResponse:
    """LLM 响应"""

    content: Optional[str]
    tool_calls: List[ToolCallInfo]

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class LangChainLLMClient:
    """
    基于 LangChain 的通用 LLM 客户端

    架构原则：
    1. Anthropic 使用专用 ChatAnthropic 类（API 格式不同）
    2. 其他所有提供商使用 ChatOpenAI 的 OpenAI 兼容模式
    3. 通过 base_url 参数区分不同的提供商 endpoint

    支持的提供商：
    - Anthropic (Claude)
    - OpenAI (GPT-4, GPT-3.5)
    - DeepSeek (兼容 OpenAI API)
    - Qwen (通义千问，兼容 OpenAI API)
    - Zhipu (智谱 AI，兼容 OpenAI API)
    - Moonshot (Kimi，兼容 OpenAI API)
    - 其他兼容 OpenAI API 的服务
    """

    # OpenAI 兼容提供商的默认 endpoints
    OPENAI_COMPATIBLE_ENDPOINTS = {
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "moonshot": "https://api.moonshot.cn/v1",
    }

    # 推理强度 → Anthropic budget_tokens 映射
    _ANTHROPIC_THINKING_BUDGET = {"low": 2048, "medium": 8192, "high": 16384}
    # 推理强度 → OpenAI reasoning_effort 映射（直传枚举）
    _OPENAI_REASONING_EFFORT = {"low": "low", "medium": "medium", "high": "high"}
    # 已知支持 reasoning_effort 的 provider
    _OPENAI_REASONING_PROVIDERS = {"openai"}

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        thinking_level: str = "off",
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        audit_source: Optional[str] = None,
    ):
        """
        初始化 LLM 客户端

        Args:
            provider: 提供商类型（"anthropic", "openai", "deepseek",
                      "qwen", "zhipu", "moonshot"）
            model: 模型名称
            api_key: API 密钥
            base_url: 自定义 endpoint（可选，用于代理或自定义服务）
            temperature: 温度参数
            max_tokens: 最大 tokens

        Raises:
            ValueError: 如果 API 密钥为空
        """
        if not api_key or not isinstance(api_key, str) or not api_key.strip():
            raise ValueError(
                "API 密钥未配置或为空。请通过「设置」界面配置 AI 密钥，"
                "或在初始化时传入有效的 api_key 参数。"
            )

        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key.strip()
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.thinking_level = normalize_thinking_level(thinking_level)
        self.timeout = timeout
        self.max_retries = max_retries
        self.audit_source = audit_source

        try:
            from src.business.debug.service import get_debug_service

            get_debug_service().register_secret(self.api_key)
        except Exception:
            logger.debug("debug redactor secret registration failed", exc_info=True)

        # 初始化 LangChain LLM 实例
        self.llm = self._create_llm()

        logger.info(
            f"[LLM客户端] 已初始化: {provider}/{model} "
            f"(温度={temperature}, max_tokens={max_tokens}, "
            f"thinking={self.thinking_level}, timeout={self.timeout})"
        )

    def _get_default_endpoint(self, provider: str) -> Optional[str]:
        """
        获取提供商的默认 endpoint

        Args:
            provider: 提供商名称

        Returns:
            endpoint URL，如果提供商不在列表中则返回 None
        """
        return self.OPENAI_COMPATIBLE_ENDPOINTS.get(provider)

    @staticmethod
    def _sanitize_for_logging(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        清理敏感信息用于日志记录

        Args:
            data: 原始数据字典

        Returns:
            清理后的数据字典（敏感信息被遮蔽）
        """
        sanitized = data.copy()
        sensitive_keys = ["api_key", "authorization", "token", "password", "secret"]

        for key in list(sanitized.keys()):
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                value = sanitized[key]
                if isinstance(value, str) and len(value) > 8:
                    # 只显示前4位和后4位
                    sanitized[key] = f"{value[:4]}...{value[-4:]}"
                else:
                    sanitized[key] = "***REDACTED***"

        return sanitized

    def _create_llm(self) -> Any:
        """
        创建 LangChain LLM 实例

        架构：
        - Anthropic 使用 ChatAnthropic（专用 API）
        - 其他所有提供商使用 ChatOpenAI（OpenAI 兼容）
        """
        try:
            from langchain_anthropic import ChatAnthropic
            from langchain_openai import ChatOpenAI
        except ImportError as e:
            raise ImportError(
                "请安装 LangChain 相关包: " "uv add langchain-anthropic langchain-openai"
            ) from e

        # Anthropic 使用专用类（API 格式不同）
        if self.provider == "anthropic":
            kwargs = {
                "model": self.model,
                "api_key": self.api_key,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if self.timeout is not None:
                kwargs["timeout"] = self.timeout
            if self.max_retries is not None:
                kwargs["max_retries"] = max(0, int(self.max_retries))

            # 如果有自定义 endpoint（用于代理）
            if self.base_url:
                kwargs["base_url"] = self.base_url

            # 注入推理（Anthropic 启用 thinking 时 temperature 必须为 1，
            # 且 max_tokens 必须严格大于 budget_tokens）
            budget = self._ANTHROPIC_THINKING_BUDGET.get(self.thinking_level)
            if budget is not None:
                if kwargs["max_tokens"] <= budget:
                    bumped = budget + 1024
                    logger.warning(
                        f"[LLM客户端] thinking={self.thinking_level} 需要 max_tokens > {budget}，"
                        f"自动从 {kwargs['max_tokens']} 提升到 {bumped}"
                    )
                    kwargs["max_tokens"] = bumped
                kwargs["temperature"] = 1
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}

            logger.debug(
                f"[LLM客户端] 使用 ChatAnthropic: {self.model}, "
                f"配置: {self._sanitize_for_logging(kwargs)}"
            )
            return ChatAnthropic(**kwargs)

        # 其他所有提供商使用 OpenAI 兼容模式
        else:
            kwargs = {
                "model": self.model,
                "api_key": self.api_key,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if self.timeout is not None:
                kwargs["timeout"] = self.timeout
            if self.max_retries is not None:
                kwargs["max_retries"] = max(0, int(self.max_retries))

            # 注入推理（仅对官方 OpenAI endpoint；自定义/兼容 endpoint 静默忽略）
            effort = self._OPENAI_REASONING_EFFORT.get(self.thinking_level)
            if (
                effort is not None
                and self.provider in self._OPENAI_REASONING_PROVIDERS
                and not self.base_url
            ):
                kwargs["reasoning_effort"] = effort
            elif effort is not None:
                logger.debug(
                    f"[LLM客户端] provider={self.provider} 或自定义 endpoint 暂不透传 reasoning_effort，"
                    f"已忽略 thinking_level={self.thinking_level}"
                )

            # 确定 base_url
            if self.base_url:
                # 用户自定义 endpoint（优先级最高）
                kwargs["base_url"] = self.base_url
                logger.debug(f"[LLM客户端] 使用自定义 endpoint: {self.base_url}")
            else:
                # 使用提供商默认 endpoint
                default_endpoint = self._get_default_endpoint(self.provider)
                if default_endpoint:
                    kwargs["base_url"] = default_endpoint
                    logger.debug(
                        f"[LLM客户端] 使用 {self.provider} " f"默认 endpoint: {default_endpoint}"
                    )
                else:
                    # OpenAI 官方不需要设置 base_url
                    logger.debug("[LLM客户端] 使用 OpenAI 官方 endpoint")

            logger.debug(
                f"[LLM客户端] 使用 ChatOpenAI: provider={self.provider}, "
                f"model={self.model}, "
                f"配置: {self._sanitize_for_logging(kwargs)}"
            )
            return ChatOpenAI(**kwargs)

    @staticmethod
    def _sanitize_message_content(content: Any) -> Any:
        """统一清洗发往 provider 的 message content。"""
        if isinstance(content, list):
            return content  # multimodal blocks — pass through
        text = "" if content is None else str(content)
        return sanitize_text_for_llm(text, max_chars=_LLM_MESSAGE_MAX_CHARS)

    def chat(self, prompt: str, **kwargs) -> str:
        """
        发送聊天请求

        Args:
            prompt: 提示词
            **kwargs: 额外参数（覆盖初始化参数）

        Returns:
            模型响应文本
        """

        def _invoke(raw_prompt: str) -> str:
            try:
                from src.data.real_tour_audit import record_paid_call

                record_paid_call(self.audit_source or "llm_chat")
            except ImportError:
                pass
            from langchain_core.messages import HumanMessage

            # 创建消息
            message = HumanMessage(content=raw_prompt)

            # 调用模型
            response = self.llm.invoke([message], **kwargs)

            # 返回文本内容
            return response.content

        try:
            from src.business.debug.observation import observe_chat
            from src.business.debug.service import get_active_capture

            buffer, redactor, epoch = get_active_capture()
        except Exception:
            logger.debug("debug observation unavailable for chat", exc_info=True)
            return _invoke(prompt)

        return observe_chat(
            buffer=buffer,
            redactor=redactor,
            epoch=epoch,
            prompt=prompt,
            invoke_fn=_invoke,
            method="chat",
        )

    def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        **kwargs,
    ) -> LLMResponse:
        """
        发送带工具绑定的聊天请求

        Args:
            messages: 消息列表，格式：
                [{"role": "system/user/assistant/tool", "content": "...",
                  "tool_calls": [...], "tool_call_id": "...", "tool_name": "..."}]
            tools: 工具 schema 列表，格式：[{"type": "function", "function": {...}}]
            **kwargs: 额外参数（覆盖初始化参数）

        Returns:
            LLMResponse 对象
        """

        def _invoke_provider(
            provider_messages: List[Dict[str, Any]],
            provider_tools: List[Dict[str, Any]] | None,
        ) -> LLMResponse:
            try:
                from src.data.real_tour_audit import record_paid_call

                record_paid_call(self.audit_source or "llm_chat_with_tools")
            except ImportError:
                pass
            # 转换为 LangChain 消息对象
            lc_messages = self._convert_to_langchain_messages(provider_messages)

            # DEBUG: 只记录安全摘要，避免 raw prompt/tool args 进入普通日志
            if logger.isEnabledFor(logging.DEBUG) and provider_messages:
                last = provider_messages[-1]
                role = last.get("role", "?")
                content = str(last.get("content") or "")
                logger.debug(
                    "[LLM→] messages=%s last_role=%s last_content_chars=%s tools=%s",
                    len(provider_messages),
                    role,
                    len(content),
                    len(provider_tools or []),
                )

            # 绑定工具（单工具调用模式）
            llm_with_tools = self.llm.bind_tools(provider_tools or [], parallel_tool_calls=False)

            # 调用模型
            ai_message = llm_with_tools.invoke(lc_messages, **kwargs)

            # 提取响应
            response = self._extract_response(ai_message)

            # DEBUG: 打印 LLM 返回结果
            if logger.isEnabledFor(logging.DEBUG):
                if response.has_tool_calls:
                    logger.debug(
                        "[←LLM] tool_calls=%s first_tool=%s",
                        len(response.tool_calls),
                        response.tool_calls[0].name,
                    )
                else:
                    logger.debug(
                        "[←LLM] text_chars=%s",
                        len(response.content or ""),
                    )

            return response

        try:
            from src.business.debug.observation import observe_chat_with_tools
            from src.business.debug.service import get_active_capture

            buffer, redactor, epoch = get_active_capture()
        except Exception:
            logger.debug("debug observation unavailable for tool chat", exc_info=True)
            return _invoke_provider(messages, tools)

        return observe_chat_with_tools(
            buffer=buffer,
            redactor=redactor,
            epoch=epoch,
            messages=messages,
            tools=tools,
            invoke_fn=_invoke_provider,
            method="chat_with_tools",
        )

    def _convert_to_langchain_messages(self, messages: List[Dict[str, Any]]) -> List[Any]:
        """
        转换消息格式为 LangChain 消息对象

        Args:
            messages: 消息列表

        Returns:
            LangChain 消息对象列表
        """
        from langchain_core.messages import (
            HumanMessage,
            AIMessage,
            SystemMessage,
            ToolMessage,
        )

        lc_messages = []
        for msg in messages:
            role = msg.get("role")
            content = self._sanitize_message_content(msg.get("content"))

            if role == "system":
                lc_messages.append(SystemMessage(content=content or ""))

            elif role == "user":
                lc_messages.append(HumanMessage(content=content or ""))

            elif role == "assistant":
                # 支持含 tool_calls 的 assistant 消息
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    # tool_calls 已是解析后的列表
                    # 转换为 LangChain 格式：[{"id": "...", "name": "...", "args": {...}}, ...]
                    langchain_tool_calls = []
                    for tc in tool_calls:
                        langchain_tool_calls.append(
                            {
                                "id": tc["id"],
                                "name": tc["name"],
                                "args": tc["args"],
                            }
                        )
                    lc_messages.append(
                        AIMessage(content=content or "", tool_calls=langchain_tool_calls)
                    )
                else:
                    lc_messages.append(AIMessage(content=content or ""))

            elif role == "tool":
                # tool 消息需要 tool_call_id 和 name
                tool_call_id = msg.get("tool_call_id")
                tool_name = msg.get("tool_name")
                lc_messages.append(
                    ToolMessage(
                        content=content or "",
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    )
                )

            else:
                logger.warning(f"[LLM客户端] 未知角色: {role}")

        return lc_messages

    def _extract_response(self, ai_message: Any) -> LLMResponse:
        """
        从 LangChain AIMessage 提取响应

        Args:
            ai_message: LangChain AIMessage 对象

        Returns:
            LLMResponse 对象
        """
        content = ai_message.content if ai_message.content else None

        # 提取 tool_calls
        tool_calls = []
        if hasattr(ai_message, "tool_calls") and ai_message.tool_calls:
            for tc in ai_message.tool_calls:
                tool_calls.append(
                    ToolCallInfo(
                        id=tc["id"],
                        name=tc["name"],
                        args=tc["args"],
                    )
                )

        return LLMResponse(content=content, tool_calls=tool_calls)
