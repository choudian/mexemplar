"""
工具辅助函数

消除工具定义中的重复模式：
- make_tool_schema：构建 OpenAI function calling 格式的工具 Schema
- make_signal_handler：创建只返回 ToolSignal 的简单工具 handler
- error_json：构造工具执行失败的 JSON 字符串
"""

import json
import threading
from typing import Any

from src.business.agents.config import ResultType, ToolSignal


def make_tool_schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    """构建 OpenAI function calling 格式的工具 Schema"""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def make_signal_handler(display_text: str, result_type: ResultType = ResultType.COMPLETED):
    """创建只返回 ToolSignal 的简单工具 handler"""

    def handler(**kwargs) -> ToolSignal:
        return ToolSignal(result_type=result_type, display_text=display_text)

    return handler


def error_json(message: str) -> str:
    """构造工具执行失败的 JSON 字符串（让 LLM 决定下一步）。"""
    return json.dumps({"success": False, "message": str(message), "data": None}, ensure_ascii=False)


def make_error_result(error_code: str, message: str, **extra) -> str:
    """Return a JSON string conforming to the StandardizedErrorStructure."""
    obj = {"error": error_code, "message": message}
    obj.update(extra)
    return json.dumps(obj, ensure_ascii=False)


def to_json(value) -> str:
    """Serialize value to JSON string with ensure_ascii=False and default=str."""
    return json.dumps(value, ensure_ascii=False, default=str)


def is_standardized_error(result: str) -> bool:
    """检查工具结果是否为标准化错误结构。

    两种格式：
    - error_json 生成的 ``{"success": false, ...}``
    - make_error_result 生成的 ``{"error": "code", "message": ...}``
    """
    if not isinstance(result, str):
        return False
    # 廉价前缀预检，避免对非错误结果做 json.loads
    if not (result.startswith('{"error"') or result.startswith('{"success"')):
        return False
    try:
        obj = json.loads(result)
        if isinstance(obj, dict):
            if obj.get("success") is False and "message" in obj:
                return True
            if "error" in obj and isinstance(obj["error"], str) and obj["error"]:
                return True
    except (json.JSONDecodeError, ValueError):
        pass
    return False


__all__ = [
    "make_tool_schema",
    "make_signal_handler",
    "error_json",
    "make_error_result",
    "is_standardized_error",
    "to_json",
    "get_vision_llm_client",
    "invoke_vision_model",
]

# =============================================================================
# 多模态 LLM 客户端共享工厂
# =============================================================================

_vision_client_cache: dict[tuple, Any] = {}
_vision_client_lock = threading.Lock()


def get_vision_llm_client(model: str | None = None) -> Any:
    from src.business.ai.llm_client import LangChainLLMClient
    from src.data.credential_resolver import (
        get_real_tour_credential_resolver,
        is_real_tour_runtime,
    )
    from src.data.unified_config import get_unified_config

    config = get_unified_config()
    resolver = get_real_tour_credential_resolver() if is_real_tour_runtime() else None
    provider = config.get_ai_vision_provider()
    resolved_model = model or config.get_ai_vision_model()
    api_key = resolver.get_ai_vision_api_key() if resolver is not None else config.get_ai_vision_api_key()
    base_url = config.get_ai_vision_base_url()
    key = (provider, resolved_model, api_key, base_url)

    client = _vision_client_cache.get(key)
    if client is not None:
        return client

    with _vision_client_lock:
        client = _vision_client_cache.get(key)
        if client is not None:
            return client
        client = LangChainLLMClient(
            provider=provider,
            model=resolved_model,
            api_key=api_key,
            base_url=base_url,
            temperature=0.3,
            max_tokens=1024,
            timeout=config.get_ai_request_timeout(),
        )
        _vision_client_cache[key] = client
        return client


def invoke_vision_model(content: list[dict[str, Any]], model: str | None = None) -> str:
    from langchain_core.messages import HumanMessage

    vision_client = get_vision_llm_client(model)

    def _invoke(provider_content: list[dict[str, Any]]) -> str:
        try:
            from src.data.real_tour_audit import record_paid_call

            record_paid_call("vision_multimodal")
        except ImportError:
            pass
        response = vision_client.llm.invoke([HumanMessage(content=provider_content)])
        answer = getattr(response, "content", None)
        if not answer:
            raise RuntimeError("empty_vision_response")
        return str(answer)

    try:
        from src.business.debug.observation import observe_multimodal
        from src.business.debug.service import get_active_capture

        buffer, redactor, epoch = get_active_capture()
    except Exception:
        return _invoke(content)
    return observe_multimodal(
        buffer=buffer,
        redactor=redactor,
        epoch=epoch,
        content=content,
        invoke_fn=_invoke,
    )
