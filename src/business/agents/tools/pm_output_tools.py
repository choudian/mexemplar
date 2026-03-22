"""
PM Agent — 输出工具

定义 PM Agent 完成需求确认后用来输出结果的信号工具：
- submit_requirements：需求确认完毕，提交结构化需求。handler 返回 ToolSignal(COMPLETED)。
- report_code_issue：分诊场景中判定为代码问题，转交程序员。handler 返回 ToolSignal(COMPLETED)。

两个工具的 handler 都不做业务逻辑，仅返回 ToolSignal 中断循环。
结构化数据通过 AgentResult.signal_tool.args 传递给 Orchestrator。
"""

from typing import Any, Dict, List

from src.business.agents.config import ResultType, ToolDefinition, ToolSignal

# =============================================================================
# submit_requirements Schema
# =============================================================================

SUBMIT_REQUIREMENTS_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_requirements",
        "description": (
            "提交需求结果。调用前必须同时满足以下两个条件，缺一不可：\n"
            "1. 用户的最新一条消息是确认性质的（如'对'、'没错'、'就这样'、'ok'、'可以'等），"
            "而不是提出修改或反问或陈述；\n"
            "2. 该确认消息的前一条，是你通过 talk_to_user 发出的最终需求确认（列明了完整的任务目标和每次会变的地方），"
            "而不是普通的提问或沟通。\n"
            "如果用户提出了修改，应先与用户沟通，再重新调用 talk_to_user 发出更新后的最终需求确认，"
            "等用户再次确认后才能调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "任务目标的一句话描述",
                },
                "recording_id": {
                    "type": "string",
                    "description": "录制会话 ID",
                },
                "parameters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "参数名（英文，简短）",
                            },
                            "description": {
                                "type": "string",
                                "description": "参数说明（中文）",
                            },
                            "recorded_value": {
                                "type": "string",
                                "description": "录制时的实际值",
                            },
                            "type": {
                                "type": "string",
                                "enum": ["variable", "fixed"],
                                "description": "variable=每次变的，fixed=固定的",
                            },
                        },
                        "required": ["name", "description", "recorded_value", "type"],
                    },
                    "description": "参数列表",
                },
                "notes": {
                    "type": "string",
                    "description": "补充说明（用户提到的特殊要求等）",
                },
            },
            "required": ["goal", "recording_id", "parameters"],
        },
    },
}


# =============================================================================
# report_code_issue Schema
# =============================================================================

REPORT_CODE_ISSUE_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "report_code_issue",
        "description": (
            "报告代码问题。当你判断试用失败是代码层面的问题（不是需求问题）时调用此工具，"
            "将问题反馈转交给程序员。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "feedback": {
                    "type": "string",
                    "description": "问题描述，包含用户反馈和你的判断",
                },
            },
            "required": ["feedback"],
        },
    },
}


# =============================================================================
# Handlers（均返回 ToolSignal，中断循环）
# =============================================================================


def _submit_requirements(
    goal: str,
    recording_id: str,
    parameters: List[Dict[str, Any]],
    notes: str = "",
) -> ToolSignal:
    """
    提交需求，中断循环。

    handler 不做业务逻辑；结构化数据通过 AgentResult.signal_tool.args
    传递给 Orchestrator。

    Args:
        goal: 任务目标描述
        recording_id: 录制会话 ID
        parameters: 参数列表
        notes: 补充说明

    Returns:
        ToolSignal(COMPLETED)
    """
    return ToolSignal(
        result_type=ResultType.COMPLETED,
        display_text="[需求已提交]",
    )


def _report_code_issue(feedback: str) -> ToolSignal:
    """
    报告代码问题，中断循环。

    handler 不做业务逻辑；feedback 通过 AgentResult.signal_tool.args["feedback"]
    传递给 Orchestrator。

    Args:
        feedback: 问题描述（包含用户反馈和 PM 的判断）

    Returns:
        ToolSignal(COMPLETED)
    """
    return ToolSignal(
        result_type=ResultType.COMPLETED,
        display_text="[代码问题已报告]",
    )


# =============================================================================
# ToolDefinition 实例（由 Orchestrator 组装后传入 loop.run()）
# =============================================================================

submit_requirements = ToolDefinition(
    name="submit_requirements",
    schema=SUBMIT_REQUIREMENTS_SCHEMA,
    handler=_submit_requirements,
)

report_code_issue = ToolDefinition(
    name="report_code_issue",
    schema=REPORT_CODE_ISSUE_SCHEMA,
    handler=_report_code_issue,
)

__all__ = [
    "submit_requirements",
    "report_code_issue",
    "SUBMIT_REQUIREMENTS_SCHEMA",
    "REPORT_CODE_ISSUE_SCHEMA",
]
