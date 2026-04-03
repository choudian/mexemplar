"""
试用 Agent — 专用工具

定义试用 Agent 专用的工具：
- execute_tool：执行工具代码，传入用户提供的参数
- submit_trial_result：提交试用结论（ToolSignal 中断循环）
- run_command：在工具执行环境中运行命令（自修复用）
"""

import json
import logging
from typing import Any, Dict

from src.business.agents.config import ResultType, ToolDefinition, ToolSignal
from src.execution.tool_executor import run_command_in_venv, run_tool_code

logger = logging.getLogger(__name__)


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
# run_command schema
# =============================================================================

RUN_COMMAND_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": (
            "在工具执行环境中运行命令。"
            "当 execute_tool 报错时，根据错误信息自行判断需要执行什么命令来修复。"
            "例如：pip install requests、playwright install chromium 等。"
            "命令执行成功后，重新调用 execute_tool 重试。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的命令，如 pip install requests、playwright install chromium",
                },
            },
            "required": ["command"],
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
    _command_attempts = 0
    _max_command_attempts = 5

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
        if result.get("success", False):
            return json.dumps(result, ensure_ascii=False, default=str)

        result.setdefault("message", "工具执行失败")
        result.setdefault("data", None)
        return json.dumps(result, ensure_ascii=False, default=str)

    def _submit_trial_result_handler(success: bool, feedback: str = "") -> ToolSignal:
        return ToolSignal(
            result_type=ResultType.COMPLETED,
            display_text="[试用结果已提交]",
        )

    def _run_command_handler(command: str) -> str:
        nonlocal _command_attempts
        _command_attempts += 1
        if _command_attempts > _max_command_attempts:
            return _error_json(f"命令执行总次数已达上限（{_max_command_attempts}次），请直接报告失败")
        result = run_command_in_venv(command)
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
            name="run_command",
            schema=RUN_COMMAND_SCHEMA,
            handler=_run_command_handler,
        ),
    ]


__all__ = [
    "create_trial_tools",
    "EXECUTE_TOOL_SCHEMA",
    "SUBMIT_TRIAL_RESULT_SCHEMA",
    "RUN_COMMAND_SCHEMA",
]
