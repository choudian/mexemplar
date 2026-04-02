"""
试用 Agent — 专用工具

定义试用 Agent 专用的工具：
- execute_tool：执行工具代码，传入用户提供的参数
- submit_trial_result：提交试用结论（ToolSignal 中断循环）
"""

import json
from typing import Any, Dict

from src.business.agents.config import ResultType, ToolDefinition, ToolSignal
from src.execution.tool_executor import install_dependency_to_venv, run_tool_code


def _error_json(message: str) -> str:
    """构造工具执行失败的 JSON 字符串（让 LLM 决定下一步）。"""
    return json.dumps(
        {"success": False, "message": message, "data": None},
        ensure_ascii=False,
    )


# =============================================================================
# execute_tool schema
# =============================================================================

EXECUTE_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "execute_tool",
        "description": "执行工具，传入用户提供的参数。UI 层会显示加载状态，无需在执行前单独告知用户。",
        "parameters": {
            "type": "object",
            "properties": {
                "parameters": {
                    "type": "object",
                    "description": (
                        "工具参数，key 为参数名（英文），value 为参数值。"
                        "只传用户明确提供或有默认值的参数。"
                    ),
                },
            },
            "required": ["parameters"],
        },
    },
}


# =============================================================================
# submit_trial_result schema
# =============================================================================

SUBMIT_TRIAL_RESULT_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_trial_result",
        "description": "提交试用结论。在询问用户是否满意并得到明确回复后调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                    "description": "true = 用户确认结果符合预期；false = 用户反馈结果不对",
                },
                "feedback": {
                    "type": "string",
                    "description": "失败时用户的反馈内容（具体哪里不对）。成功时可不填。",
                },
            },
            "required": ["success"],
        },
    },
}


# =============================================================================
# install_dependency schema
# =============================================================================

INSTALL_DEPENDENCY_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "install_dependency",
        "description": (
            "安装缺失的 Python 依赖包到工具执行环境。"
            "仅在 execute_tool 报错提示缺少模块（如 ModuleNotFoundError、ImportError）时调用。"
            "安装完成后应重新调用 execute_tool 重试。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "package_name": {
                    "type": "string",
                    "description": (
                        "pip 包名（如 requests）或 import 名（如 bs4），系统会自动映射为正确的 pip 包名。"
                    ),
                },
            },
            "required": ["package_name"],
        },
    },
}


# =============================================================================
# 工厂函数
# =============================================================================


def create_trial_tools(workflow_id: str) -> list[ToolDefinition]:
    """创建试用工具列表，workflow_id 通过闭包绑定。"""

    # 自修复计数器：生命周期 = 单次 run_agent("trial") 调用
    # 每次 Orchestrator 启动试用 Agent 时都会重置
    _install_attempts: dict[str, int] = {}  # package_name -> 安装尝试次数（含失败）
    _total_install_attempts = 0  # 安装尝试总次数（上限 3，含失败）

    def _execute_tool_handler(parameters: dict) -> str:
        from src.data.repositories import ToolRepository

        tool_repo = ToolRepository()
        tool = tool_repo.get_by_workflow_id(workflow_id)
        if not tool:
            return _error_json(f"未找到工作流 {workflow_id} 对应的工具")
        if not tool.execution_code:
            return _error_json("工具代码为空")

        dependencies = tool.dependencies or []
        result = run_tool_code(tool.execution_code, parameters, dependencies=dependencies)
        result.setdefault("message", "工具执行失败")
        result.setdefault("data", None)
        return json.dumps(result, ensure_ascii=False, default=str)

    def _submit_trial_result_handler(success: bool, feedback: str = "") -> ToolSignal:
        # success / feedback 不需要在这里处理。
        # AgentLoop 在检测到 ToolSignal 时，会将 LLM 函数调用的原始 args dict
        # （{"success": ..., "feedback": ...}）存入 AgentResult.signal_tool.args，
        # Orchestrator 直接从那里读取，无需 handler 转传。
        return ToolSignal(
            result_type=ResultType.COMPLETED,
            display_text="[试用结果已提交]",
        )

    def _install_dependency_handler(package_name: str) -> str:
        nonlocal _total_install_attempts
        count = _install_attempts.get(package_name, 0)
        if count >= 2:
            return _error_json(f"依赖 {package_name} 已尝试安装 2 次，不再重试")
        if _total_install_attempts >= 3:
            return _error_json("依赖安装总次数已达上限（3次），请直接报告失败")
        _install_attempts[package_name] = count + 1
        _total_install_attempts += 1

        result = install_dependency_to_venv(package_name)
        return json.dumps(result, ensure_ascii=False)

    return [
        ToolDefinition(
            name="execute_tool",
            schema=EXECUTE_TOOL_SCHEMA,
            handler=_execute_tool_handler,
        ),
        ToolDefinition(
            name="submit_trial_result",
            schema=SUBMIT_TRIAL_RESULT_SCHEMA,
            handler=_submit_trial_result_handler,
        ),
        ToolDefinition(
            name="install_dependency",
            schema=INSTALL_DEPENDENCY_SCHEMA,
            handler=_install_dependency_handler,
        ),
    ]


__all__ = [
    "create_trial_tools",
    "EXECUTE_TOOL_SCHEMA",
    "SUBMIT_TRIAL_RESULT_SCHEMA",
    "INSTALL_DEPENDENCY_SCHEMA",
]
