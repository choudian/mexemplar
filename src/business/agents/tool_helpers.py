"""
工具辅助函数

消除工具定义中的重复模式：
- make_tool_schema：构建 OpenAI function calling 格式的工具 Schema
- make_signal_handler：创建只返回 ToolSignal 的简单工具 handler
- error_json：构造工具执行失败的 JSON 字符串
"""

import json
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
    - web_search 等工具返回的 ``{"success": false, "error": ...}``
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
            if obj.get("success") is False and isinstance(obj.get("error"), str) and obj["error"]:
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

# 注：原先这里有一个模块级 ``_vision_client_cache`` 字典做双检锁复用，但它没有
# 失效机制——改了 vision 配置后旧 entry 仍被命中，导致连接方式不更新。改为每次
# 基于最新配置现组装，使配置变更在下一次多模态调用立即生效。vision 调用低频，
# 多一次 provider 构造的代价可接受。


def get_vision_llm_client(model: str | None = None) -> Any:
    from src.business.ai.llm_client import LangChainLLMClient
    from src.data.unified_config import get_unified_config

    config = get_unified_config()
    return LangChainLLMClient(
        provider=config.get_ai_vision_provider(),
        model=model or config.get_ai_vision_model(),
        api_key=config.get_ai_vision_api_key(),
        base_url=config.get_ai_vision_base_url(),
        temperature=config.get_ai_temperature(),
        max_tokens=1024,
        timeout=config.get_ai_request_timeout(),
    )


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
