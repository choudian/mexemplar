"""
试用 Agent — 专用工具

定义试用 Agent 专用的工具：
- execute_tool：执行工具代码，传入用户提供的参数
- submit_trial_result：提交试用结论（ToolSignal 中断循环）
- run_command：在工具执行环境中运行命令（自修复用）
"""

import uuid
from dataclasses import asdict
from typing import Any, Dict

from src.business.agents.config import ToolDefinition
from src.business.agents.hook_models import PreHookResult, ToolCallContext
from src.business.agents.tool_helpers import make_tool_schema, make_signal_handler, error_json, to_json
from src.execution.desktop_trial_runner import run_desktop_trial
from src.execution.tool_executor import run_command_in_venv, run_tool_code
from src.utils.events import emit, emit_collect

# =============================================================================
# execute_tool schema
# =============================================================================

EXECUTE_TOOL_SCHEMA: Dict[str, Any] = make_tool_schema(
    name="execute_tool",
    description="执行工具，传入用户提供的参数。UI 层会显示加载状态，无需在执行前单独告知用户。",
    properties={
        "parameters": {
            "type": "object",
            "description": (
                "工具参数，key 为参数名（英文），value 为参数值。"
                "只传用户明确提供或有默认值的参数。"
            ),
        },
    },
    required=["parameters"],
)


# =============================================================================
# submit_trial_result schema
# =============================================================================

SUBMIT_TRIAL_RESULT_SCHEMA: Dict[str, Any] = make_tool_schema(
    name="submit_trial_result",
    description="提交试用结论。在询问用户是否满意并得到明确回复后调用。",
    properties={
        "success": {
            "type": "boolean",
            "description": "true = 用户确认结果符合预期；false = 用户反馈结果不对",
        },
        "feedback": {
            "type": "string",
            "description": "失败时用户的反馈内容（具体哪里不对）。成功时可不填。",
        },
    },
    required=["success"],
)


# =============================================================================
# run_command schema
# =============================================================================

RUN_COMMAND_SCHEMA: Dict[str, Any] = make_tool_schema(
    name="run_command",
    description=(
        "在工具执行环境中运行命令。"
        "当 execute_tool 报错时，根据错误信息自行判断需要执行什么命令来修复。"
        "例如：pip install requests、playwright install chromium 等。"
        "命令执行成功后，重新调用 execute_tool 重试。"
    ),
    properties={
        "command": {
            "type": "string",
            "description": "要执行的命令，如 pip install requests、playwright install chromium",
        },
    },
    required=["command"],
)


# =============================================================================
# 工厂函数
# =============================================================================

_MAX_COMMAND_ATTEMPTS = 5  # 单次试用 Agent 运行中允许的 run_command 最大调用次数


def _resolve_tool_code(workflow_id: str) -> tuple[Any, str | None]:
    """Look up tool by workflow_id. Returns (tool, error_json_or_None)."""
    from src.data.repositories import ToolRepository

    tool_repo = ToolRepository()
    tool = tool_repo.get_by_workflow_id(workflow_id)
    if not tool:
        return None, error_json(f"未找到工作流 {workflow_id} 对应的工具")
    if not tool.execution_code:
        return None, error_json("工具代码为空")
    return tool, None


def _make_run_command_tools() -> tuple[ToolDefinition, ToolDefinition]:
    """Create shared run_command + submit_trial_result tool definitions."""
    _command_attempts = 0

    def _run_command_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
        nonlocal _command_attempts
        _command_attempts += 1
        if _command_attempts > _MAX_COMMAND_ATTEMPTS:
            return PreHookResult(
                error=f"命令执行总次数已达上限（{_MAX_COMMAND_ATTEMPTS}次），请直接报告失败"
            )
        return None

    def _run_command_handler(command: str) -> str:
        result = run_command_in_venv(command)
        return to_json(result)

    return (
        ToolDefinition(
            name="submit_trial_result",
            schema=SUBMIT_TRIAL_RESULT_SCHEMA,
            handler=make_signal_handler("[试用结果已提交]"),
            is_interrupting=True,
        ),
        ToolDefinition(
            name="run_command",
            schema=RUN_COMMAND_SCHEMA,
            handler=_run_command_handler,
            pre_hook=_run_command_pre_hook,
        ),
    )


def create_trial_tools(workflow_id: str) -> list[ToolDefinition]:
    """创建试用工具列表，workflow_id 通过闭包绑定。"""

    def _execute_tool_handler(parameters: dict) -> str:
        tool, err = _resolve_tool_code(workflow_id)
        if err:
            return err

        dependencies = tool.dependencies or []

        result = run_tool_code(tool.execution_code, parameters, dependencies=dependencies)
        if result.get("success", False):
            return to_json(result)

        result.setdefault("message", "工具执行失败")
        result.setdefault("data", None)
        return to_json(result)

    submit_tool, run_command_tool = _make_run_command_tools()
    return [
        ToolDefinition(
            name="execute_tool",
            schema=EXECUTE_TOOL_SCHEMA,
            handler=_execute_tool_handler,
        ),
        submit_tool,
        run_command_tool,
    ]


def create_desktop_trial_tools(workflow_id: str) -> list[ToolDefinition]:
    """创建桌面试用工具，execute_tool 使用隔离 desktop runner。"""
    _execution_approved = False

    def _preview_cancelled(responses: list[tuple[Any, Any]]) -> bool:
        return any(response is False for _receiver, response in responses)

    def _execute_tool_handler(parameters: dict | None = None) -> str:
        nonlocal _execution_approved
        del parameters
        tool, err = _resolve_tool_code(workflow_id)
        if err:
            return err

        trial_id = str(uuid.uuid4())
        if not _execution_approved:
            preview_responses = emit_collect(
                "desktop_trial_preview_ready",
                sender=None,
                workflow_id=workflow_id,
                trial_id=trial_id,
                code=tool.execution_code,
                code_preview="\n".join(tool.execution_code.splitlines()[:20]),
            )
            if _preview_cancelled(preview_responses):
                return to_json(
                    {
                        "ok": False,
                        "summary": "用户取消桌面试用",
                        "details": {"cancelled": True},
                        "exit_code": None,
                        "timed_out": False,
                        "stdout_path": None,
                        "stderr_path": None,
                        "trial_id": trial_id,
                    },
                )
            _execution_approved = True
        result = run_desktop_trial(tool.execution_code, trial_id)
        emit(
            "desktop_trial_finished",
            sender=None,
            workflow_id=workflow_id,
            trial_id=trial_id,
            result=result,
        )
        return to_json(asdict(result))

    submit_tool, run_command_tool = _make_run_command_tools()
    return [
        ToolDefinition(
            name="execute_tool",
            schema=EXECUTE_TOOL_SCHEMA,
            handler=_execute_tool_handler,
        ),
        submit_tool,
        run_command_tool,
    ]


__all__ = [
    "create_desktop_trial_tools",
    "create_trial_tools",
]
