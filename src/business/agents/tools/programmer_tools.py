"""
程序员 Agent — 专用工具

定义程序员 Agent 专用的工具：
- syntax_check：代码语法校验（AST 解析 + 导入黑名单 + 禁止调用检查）
- submit_code：提交代码（ToolSignal 中断循环，结构化数据通过 signal_tool.args 传递）
"""

import ast
import json
from typing import Any, Dict, List

from src.business.agents.config import ToolDefinition
from src.business.agents.tool_helpers import make_tool_schema, make_signal_handler

# =============================================================================
# syntax_check
# =============================================================================

SYNTAX_CHECK_SCHEMA: Dict[str, Any] = make_tool_schema(
    name="syntax_check",
    description=(
        "检查 Python 代码的语法正确性和导入合法性。不执行代码，只做静态分析。"
        "建议在提交代码前调用。"
    ),
    properties={
        "code": {
            "type": "string",
            "description": "要检查的 Python 代码",
        },
    },
    required=["code"],
)

_BLOCKED_MODULES = frozenset(
    {
        "subprocess",
        "shutil",
        "ctypes",
        "socket",
        "multiprocessing",
        "signal",
        "pickle",
        "shelve",
        "marshal",
        "code",
        "codeop",
    }
)

_FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__"})


def _syntax_check(code: str) -> str:
    """
    语法检查 handler。

    检查项：
    1. AST 解析（语法错误）
    2. 导入合法性（黑名单校验）
    3. execute 函数签名（必须存在且建议 async）
    4. 禁止的函数调用（eval, exec 等）

    Returns:
        JSON 格式的检查结果
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1. AST 解析
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return json.dumps(
            {
                "passed": False,
                "errors": [f"语法错误（第{e.lineno}行）: {e.msg}"],
                "warnings": [],
            },
            ensure_ascii=False,
        )

    # 2-4. 单次遍历：导入检查 + execute 函数检查 + 禁止调用检查
    has_execute = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_module = alias.name.split(".")[0]
                if top_module in _BLOCKED_MODULES:
                    errors.append(f"禁止导入模块: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top_module = node.module.split(".")[0]
                if top_module in _BLOCKED_MODULES:
                    errors.append(f"禁止导入模块: {node.module}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "execute":
                has_execute = True
                if not isinstance(node, ast.AsyncFunctionDef):
                    warnings.append("execute 函数建议使用 async def")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALLS:
                errors.append(f"禁止调用: {node.func.id}()")

    if not has_execute:
        errors.append("缺少 execute 函数定义")

    passed = len(errors) == 0
    return json.dumps(
        {"passed": passed, "errors": errors, "warnings": warnings},
        ensure_ascii=False,
    )


# =============================================================================
# submit_code
# =============================================================================

SUBMIT_CODE_SCHEMA: Dict[str, Any] = make_tool_schema(
    name="submit_code",
    description="提交编写完成的代码。代码必须通过语法校验后再提交。",
    properties={
        "tool_name": {
            "type": "string",
            "description": "工具名称（英文，snake_case，如 baidu_search_scraper）",
        },
        "description": {
            "type": "string",
            "description": "工具功能描述（中文，一句话）",
        },
        "code": {
            "type": "string",
            "description": "完整的 Python 代码",
        },
        "execution_strategy": {
            "type": "string",
            "enum": ["browser", "api", "hybrid"],
            "description": ("执行策略：browser=浏览器自动化, api=直接调用API, hybrid=混合"),
        },
        "parameters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "参数名",
                    },
                    "description": {
                        "type": "string",
                        "description": "参数说明",
                    },
                    "type": {
                        "type": "string",
                        "description": "参数类型（string/integer/boolean）",
                    },
                    "required": {
                        "type": "boolean",
                        "description": "是否必填",
                    },
                    "default": {
                        "description": "默认值（可选，类型与参数类型一致）",
                    },
                },
                "required": ["name", "description", "type", "required"],
            },
            "description": ("完整参数列表（包含 PM 定义的参数和你补充的技术参数）"),
        },
    },
    required=[
        "tool_name",
        "description",
        "code",
        "execution_strategy",
        "parameters",
    ],
)


# =============================================================================
# ToolDefinition 实例（由 Orchestrator 组装后传入 loop.run()）
# =============================================================================

syntax_check = ToolDefinition(
    name="syntax_check",
    schema=SYNTAX_CHECK_SCHEMA,
    handler=_syntax_check,
)

submit_code = ToolDefinition(
    name="submit_code",
    schema=SUBMIT_CODE_SCHEMA,
    handler=make_signal_handler("[代码已提交]"),
    is_interrupting=True,
)

__all__ = [
    "syntax_check",
    "submit_code",
]
