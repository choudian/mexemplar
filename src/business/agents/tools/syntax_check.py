"""
语法检查工具

检查代码的语法正确性。
"""

from src.business.agents.tool_registry import agent_tool
from src.business.agents.validation import validate_parameters
from typing import Optional
import json
import logging

logger = logging.getLogger(__name__)


@agent_tool(
    name="syntax_check",
    description="检查代码语法错误。支持 Python、JavaScript 等语言。返回错误列表（如有）。",
    parameters_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "要检查的代码"},
            "language": {"type": "string", "description": "编程语言，如 'python'、'javascript'、默认 'python'"}
        },
        "required": ["code"]
    }
)
@validate_parameters({
    "type": "object",
    "required": ["code"],
    "properties": {
        "code": {"type": "string"},
        "language": {"type": "string"}
    }
})
def syntax_check(
    code: str,
    language: str = "python"
) -> str:
    """
    语法检查

    Args:
        code: 要检查的代码
        language: 编程语言

    Returns:
        JSON 格式的检查结果
    """
    # TODO: 实现实际的语法检查逻辑
    # 当前返回模拟数据
    result = {
        "language": language,
        "code_preview": code[:100] + "..." if len(code) > 100 else code,
        "errors": [],
        "warnings": [],
        "status": "valid"
    }
    logger.debug(f"[语法检查] language={language}, code_length={len(code)}")
    return json.dumps(result, ensure_ascii=False)