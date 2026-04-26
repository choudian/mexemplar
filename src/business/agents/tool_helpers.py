"""
工具辅助函数

消除工具定义中的重复模式：
- make_tool_schema：构建 OpenAI function calling 格式的工具 Schema
- make_signal_handler：创建只返回 ToolSignal 的简单工具 handler
- error_json：构造工具执行失败的 JSON 字符串
"""

import json

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
]
