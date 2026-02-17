"""
代码修复节点

当草稿工具执行出错时，自动调用 LLM 修复代码。
"""

from typing import Dict, Any
from langchain_core.messages import AIMessage
import logging

from ..state import AgentState, ToolDraft
from ..prompts.code_repair import get_code_repair_prompt

logger = logging.getLogger(__name__)


def code_repair_node(state: AgentState) -> Dict[str, Any]:
    """
    代码修复节点

    当工具执行失败时，自动修复代码并重试。

    Args:
        state: 当前状态

    Returns:
        状态更新
    """
    # 获取工具草稿和错误信息
    tool_draft = state.get("tool_draft")
    error_info = state.get("error_info")

    if not tool_draft or not error_info:
        return {
            "error_info": {
                "code": "NO_DATA_FOR_REPAIR",
                "message": "No tool draft or error info for repair"
            }
        }

    # 生成修复提示词
    prompt = get_code_repair_prompt(
        code=tool_draft.execution_code,
        error_message=error_info.get("message", str(error_info)),
        context={
            "tool_name": tool_draft.tool_name,
            "description": tool_draft.description,
            "parameters": tool_draft.parameters
        }
    )

    try:
        # 调用 LLM 修复代码
        from src.business.ai.llm_client import create_llm_client
        from src.data.unified_config import get_unified_config

        config = get_unified_config()

        client_config = {
            "provider": config.get_ai_provider(),
            "model": config.get_ai_model(),
            "api_key": config.get_ai_api_key(),
            "temperature": 0.3,  # 使用较低温度，确保修复更精确
            "max_tokens": 4096,
        }

        base_url = config.get_ai_base_url()
        if base_url:
            client_config["base_url"] = base_url

        client = create_llm_client(client_config)
        response_text = client.chat(prompt=prompt, max_tokens=4096)

        # 提取修复后的代码
        repaired_code = _extract_code(response_text)

        # 更新工具草稿
        updated_tool_draft = ToolDraft(
            tool_id=tool_draft.tool_id,
            tool_name=tool_draft.tool_name,
            description=tool_draft.description,
            execution_code=repaired_code,
            parameters=tool_draft.parameters,
            execution_strategy=tool_draft.execution_strategy
        )

        logger.info(f"代码修复完成: {tool_draft.tool_name}")

        # 清除错误信息
        return {
            "tool_draft": updated_tool_draft,
            "error_info": None,
            "messages": [AIMessage(content=f"代码已修复，准备重新执行")]
        }

    except Exception as e:
        logger.error(f"代码修复失败: {e}")
        return {
            "error_info": {
                "code": "REPAIR_FAILED",
                "message": f"Code repair failed: {str(e)}"
            },
            "messages": [AIMessage(content=f"代码修复失败: {e}")]
        }


def _extract_code(response_text: str) -> str:
    """
    从 LLM 响应中提取代码

    Args:
        response_text: LLM 响应文本

    Returns:
        提取的代码
    """
    import re

    # 查找 Python 代码块
    code_match = re.search(r"```python\s*(.*?)\s*```", response_text, re.DOTALL)
    if code_match:
        return code_match.group(1)

    # 查找任意代码块
    code_match = re.search(r"```\s*(.*?)\s*```", response_text, re.DOTALL)
    if code_match:
        return code_match.group(1)

    # 如果没有代码块，返回原始响应
    return response_text.strip()
