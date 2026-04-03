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

logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
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
        # 🔧 验证 API 密钥
        if not api_key or not isinstance(api_key, str) or not api_key.strip():
            raise ValueError(
                "API 密钥未配置或为空。请通过「设置」界面配置 AI 密钥，"
                "或在初始化时传入有效的 api_key 参数。"
            )

        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key.strip()  # 移除首尾空格
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens

        # 初始化 LangChain LLM 实例
        self.llm = self._create_llm()

        logger.info(
            f"[LLM客户端] 已初始化: {provider}/{model} "
            f"(温度={temperature}, max_tokens={max_tokens})"
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
        sensitive_keys = ['api_key', 'authorization', 'token', 'password', 'secret']

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

            # 如果有自定义 endpoint（用于代理）
            if self.base_url:
                kwargs["base_url"] = self.base_url

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

    def chat(self, prompt: str, **kwargs) -> str:
        """
        发送聊天请求

        Args:
            prompt: 提示词
            **kwargs: 额外参数（覆盖初始化参数）

        Returns:
            模型响应文本
        """
        try:
            from langchain_core.messages import HumanMessage

            # 创建消息
            message = HumanMessage(content=prompt)

            # 调用模型
            response = self.llm.invoke([message], **kwargs)

            # 返回文本内容
            return response.content

        except Exception as e:
            logger.error(f"[LLM客户端] 调用失败: {e}")
            raise

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
        try:
            # 转换为 LangChain 消息对象
            lc_messages = self._convert_to_langchain_messages(messages)

            # DEBUG: 打印消息总数 + 最新一条
            if logger.isEnabledFor(logging.DEBUG) and messages:
                last = messages[-1]
                role = last.get("role", "?")
                content = str(last.get("content") or "")
                logger.debug(f"[LLM→] ({len(messages)} msgs) {role}: {content}")

            # 绑定工具（单工具调用模式）
            llm_with_tools = self.llm.bind_tools(
                tools, parallel_tool_calls=False
            )

            # 调用模型
            ai_message = llm_with_tools.invoke(lc_messages, **kwargs)

            # 提取响应
            response = self._extract_response(ai_message)

            # DEBUG: 打印 LLM 返回结果
            if logger.isEnabledFor(logging.DEBUG):
                if response.has_tool_calls:
                    tc = response.tool_calls[0]
                    import json as _json
                    args_str = _json.dumps(tc.args, ensure_ascii=False)
                    logger.debug(f"[←LLM] tool_call={tc.name} args={args_str}")
                else:
                    logger.debug(f"[←LLM] text={response.content or ''}")

            return response

        except Exception as e:
            logger.error(f"[LLM客户端] 工具调用失败: {e}")
            raise

    def _convert_to_langchain_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Any]:
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
            content = msg.get("content")

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
                        langchain_tool_calls.append({
                            "id": tc["id"],
                            "name": tc["name"],
                            "args": tc["args"],
                        })
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


def create_llm_client(config: Dict[str, Any]) -> LangChainLLMClient:
    """
    工厂函数：从配置创建 LLM 客户端

    Args:
        config: 配置字典，包含：
            - provider: 提供商类型
            - model: 模型名称
            - api_key: API 密钥
            - base_url: 自定义 endpoint（可选）
            - temperature: 温度（可选）
            - max_tokens: 最大 tokens（可选）

    Returns:
        LLM 客户端实例
    """
    return LangChainLLMClient(
        provider=config.get("provider", "anthropic"),
        model=config.get("model", "claude-3-5-haiku-20241022"),
        api_key=config.get("api_key"),
        base_url=config.get("base_url"),
        temperature=config.get("temperature", 0.5),
        max_tokens=config.get("max_tokens", 1024),
    )
