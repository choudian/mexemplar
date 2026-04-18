from __future__ import annotations

from src.business.ai.llm_client import LLMResponse, ToolCallInfo

SAMPLE_CODE = (
    "async def execute(**kwargs):\n"
    "    return {'success': True, 'message': 'ok', 'data': kwargs}\n"
)

SAMPLE_CODE_V2 = (
    "async def execute(**kwargs):\n"
    "    return {'success': True, 'message': 'fixed', 'data': kwargs}\n"
)


def text_reply(content: str) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[])


def tool_call_response(
    name: str,
    args: dict,
    *,
    tc_id: str = "tc-tool-1",
    content: str | None = None,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=[ToolCallInfo(id=tc_id, name=name, args=args)],
    )


def dynamic_tool_short_name(entity_id: str, prefix: str = "utool") -> str:
    return f"{prefix}_{entity_id[:8]}"


def pm_submit_requirements(recording_id: str, tc_id: str = "tc-pm-1") -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallInfo(
                id=tc_id,
                name="submit_requirements",
                args={
                    "goal": "测试目标：自动填写并提交表单",
                    "recording_id": recording_id,
                    "parameters": [
                        {
                            "name": "keyword",
                            "type": "text",
                            "description": "搜索关键词",
                            "required": True,
                        }
                    ],
                },
            )
        ],
    )


def programmer_submit_code(code: str = SAMPLE_CODE, tc_id: str = "tc-prog-1") -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallInfo(
                id=tc_id,
                name="submit_code",
                args={
                    "tool_name": "auto_submit_form",
                    "description": "自动填写并提交表单",
                    "code": code,
                    "execution_strategy": "api",
                    "parameters": [
                        {
                            "name": "keyword",
                            "type": "text",
                            "description": "搜索关键词",
                            "required": True,
                        }
                    ],
                },
            )
        ],
    )


def review_passed() -> str:
    return '{"passed": true, "feedback": "代码符合规范，可以入库"}'


def review_failed(msg: str = "函数签名错误") -> str:
    return f'{{"passed": false, "feedback": "{msg}"}}'


def trial_submit_result(success: bool, feedback: str = "", tc_id: str = "tc-trial-1") -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallInfo(
                id=tc_id,
                name="submit_trial_result",
                args={"success": success, "feedback": feedback},
            )
        ],
    )


def pm_report_code_issue(
    feedback: str = "输出结果不对，代码逻辑有误",
    tc_id: str = "tc-pm-triage",
) -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallInfo(
                id=tc_id,
                name="report_code_issue",
                args={"feedback": feedback},
            )
        ],
    )
