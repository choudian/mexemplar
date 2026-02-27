"""
代码生成节点

根据确认的意图生成可执行代码。
"""

from typing import Dict, Any
from langchain_core.messages import AIMessage
import logging
import uuid

from ..state import AgentState, ToolDraft
from ..prompts.code_generation import get_code_generation_prompt

logger = logging.getLogger(__name__)


def code_generation_node(state: AgentState) -> Dict[str, Any]:
    """
    代码生成节点

    根据意图生成可执行的自动化代码。

    Args:
        state: 当前状态

    Returns:
        状态更新
    """
    # 获取意图和录制数据
    current_intent = state.get("current_intent")
    recording_data = state.get("recording_data")

    if not current_intent or not recording_data:
        return {
            "error_info": {
                "code": "MISSING_DATA",
                "message": "Missing intent or recording data"
            }
        }

    # 提取 actions
    actions = recording_data.get("actions", [])

    # 生成提示词
    prompt = get_code_generation_prompt(
        intent_data={
            "intent_type": current_intent.intent_type,
            "description": current_intent.description,
            "parameters": current_intent.parameters,
            "raw_analysis": current_intent.raw_analysis
        },
        actions=actions
    )

    try:
        # 调用 LLM 生成代码
        from src.business.ai.llm_client import create_llm_client
        from src.data.unified_config import get_unified_config

        config = get_unified_config()

        client_config = {
            "provider": config.get_ai_provider(),
            "model": config.get_ai_model(),
            "api_key": config.get_ai_api_key(),
            "temperature": config.get_ai_temperature(),
            "max_tokens": 8192,
        }

        base_url = config.get_ai_base_url()
        if base_url:
            client_config["base_url"] = base_url

        client = create_llm_client(client_config)
        response_text = client.chat(prompt=prompt, max_tokens=8192)

        # 解析响应
        workflow_result = _parse_workflow_response(response_text)

        # 创建 ToolDraft
        tool_draft = ToolDraft(
            tool_id=str(uuid.uuid4()),
            tool_name=workflow_result.get("tool_name", "未命名工具"),
            description=workflow_result.get("description", current_intent.description),
            execution_code=_generate_execution_code(workflow_result),
            parameters=workflow_result.get("parameters", []),
            execution_strategy=_determine_execution_strategy(workflow_result)
        )

        # 保存工具到数据库
        _save_tool_draft(tool_draft, recording_data.get("recording_id"))

        logger.info(f"代码生成完成: {tool_draft.tool_name}")

        # 返回状态更新
        return {
            "tool_draft": tool_draft,
            "messages": [AIMessage(
                content=f"已生成工具草稿：{tool_draft.tool_name}\n\n"
                        f"描述：{tool_draft.description}\n"
                        f"策略：{tool_draft.execution_strategy}"
            )]
        }

    except Exception as e:
        logger.error(f"代码生成失败: {e}")
        # 返回默认草稿
        tool_draft = ToolDraft(
            tool_id=str(uuid.uuid4()),
            tool_name="示例工具",
            description=current_intent.description,
            execution_code="# 代码生成失败\nasync def execute(**kwargs):\n    pass",
            parameters=current_intent.parameters,
            execution_strategy="browser"
        )
        return {
            "tool_draft": tool_draft,
            "messages": [AIMessage(content=f"代码生成失败，使用默认草稿：{e}")]
        }


def _parse_workflow_response(response_text: str) -> Dict[str, Any]:
    """解析 LLM 响应"""
    import json
    import re

    # 查找 JSON 代码块
    json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试直接解析
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    return {}


def _generate_execution_code(workflow: Dict[str, Any]) -> str:
    """根据工作流定义生成执行代码"""
    steps = workflow.get("steps", [])

    code_lines = [
        "async def execute(**kwargs):",
        '    """执行工具"""',
        "    from src.execution.executor import Executor",
        "    from src.drivers.locator.multi_layer_locator import MultiLayerLocator",
        "",
        "    executor = Executor()",
        "    locator = MultiLayerLocator()",
        "",
    ]

    for step in steps:
        step_name = step.get("step_name", "未命名步骤")
        action_type = step.get("action_type", "unknown")
        params = step.get("parameters", {})

        code_lines.append(f"    # {step_name}")
        code_lines.append(f"    # 类型: {action_type}")

        # 根据步骤类型生成代码
        if "browser_navigate" in action_type:
            url = params.get("url", "")
            code_lines.append(f'    await executor.navigate("{url}")')
        elif "browser_click" in action_type:
            selector = params.get("selector", "")
            code_lines.append(f'    await executor.click("{selector}")')
        elif "browser_input" in action_type:
            selector = params.get("selector", "")
            text = params.get("text", "")
            code_lines.append(f'    await executor.input_text("{selector}", "{text}")')

        code_lines.append("")

    code_lines.extend([
        '    return {"success": True, "message": "执行完成"}',
        ""
    ])

    return "\n".join(code_lines)


def _determine_execution_strategy(workflow: Dict[str, Any]) -> str:
    """确定执行策略"""
    metadata = workflow.get("metadata", {})
    category = metadata.get("category", "").lower()

    if "api" in category:
        return "api"
    elif "browser" in category:
        return "browser"
    else:
        return "hybrid"


def _save_tool_draft(tool_draft: ToolDraft, recording_id: str = None):
    """保存工具草稿到数据库"""
    try:
        from src.data.repositories import ToolRepository
        from src.data.database import DatabaseManager
        from src.data.models import Tool

        db_manager = DatabaseManager()
        repo = ToolRepository(db_manager)

        # 创建 Tool 对象
        tool = Tool(
            tool_id=tool_draft.tool_id,
            tool_name=tool_draft.tool_name,
            description=tool_draft.description,
            parameters=tool_draft.parameters if isinstance(tool_draft.parameters, list) else [],
            steps=[],  # 步骤信息可以在后续补充
            execution_code=tool_draft.execution_code,
            execution_strategy=tool_draft.execution_strategy,
            source="intent",  # 标记来源为意图生成
        )

        repo.create(tool)
        logger.info(f"工具草稿已保存: {tool_draft.tool_id}")

    except Exception as e:
        logger.error(f"保存工具草稿失败: {e}")
