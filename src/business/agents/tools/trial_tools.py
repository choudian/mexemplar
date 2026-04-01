"""
试用 Agent — 专用工具

定义试用 Agent 专用的工具：
- execute_tool：执行工具代码，传入用户提供的参数
- submit_trial_result：提交试用结论（ToolSignal 中断循环）
"""

import json
from typing import Any, Dict

from src.business.agents.config import ResultType, ToolDefinition, ToolSignal
from src.execution.tool_executor import run_tool_code


def _error_signal(message: str, data=None, *, save_result: bool = True) -> ToolSignal:
    """构造工具执行失败的 ToolSignal（统一格式）"""
    return ToolSignal(
        result_type=ResultType.COMPLETED,
        display_text=json.dumps(
            {"success": False, "message": message, "data": data},
            ensure_ascii=False,
        ),
        save_result=save_result,
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
# 工厂函数
# =============================================================================


def create_trial_tools(workflow_id: str) -> list[ToolDefinition]:
    """创建试用工具列表，workflow_id 通过闭包绑定。"""

    def _execute_tool_handler(parameters: dict) -> str | ToolSignal:
        from src.data.repositories import ToolRepository

        tool_repo = ToolRepository()
        tool = tool_repo.get_by_workflow_id(workflow_id)
        if not tool:
            return _error_signal(f"未找到工作流 {workflow_id} 对应的工具")
        if not tool.execution_code:
            return _error_signal("工具代码为空")

        dependencies = tool.dependencies or []
        result = run_tool_code(tool.execution_code, parameters, dependencies=dependencies)
        result_json = json.dumps(result, ensure_ascii=False, default=str)

        if not result.get("success", False):
            return _error_signal(
                result.get("message", "工具执行失败"),
                result.get("data"),
                save_result=False,
            )

        return result_json

    def _submit_trial_result_handler(success: bool, feedback: str = "") -> ToolSignal:
        # success / feedback 不需要在这里处理。
        # AgentLoop 在检测到 ToolSignal 时，会将 LLM 函数调用的原始 args dict
        # （{"success": ..., "feedback": ...}）存入 AgentResult.signal_tool.args，
        # Orchestrator 直接从那里读取，无需 handler 转传。
        return ToolSignal(
            result_type=ResultType.COMPLETED,
            display_text="[试用结果已提交]",
        )

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
    ]


__all__ = [
    "create_trial_tools",
    "EXECUTE_TOOL_SCHEMA",
    "SUBMIT_TRIAL_RESULT_SCHEMA",
]
