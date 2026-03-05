"""
代码生成节点

根据确认的意图（执行蓝图）生成可执行代码。
"""

from typing import Dict, Any
from langchain_core.messages import AIMessage
import logging
import uuid

from ..state import AgentState, ToolDraft, ExecutionBlueprint
from ..prompts.code_generation import get_code_generation_prompt

logger = logging.getLogger(__name__)


def code_generation_node(state: AgentState) -> Dict[str, Any]:
    """
    代码生成节点

    根据意图分析中的执行蓝图生成可执行的自动化代码。

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

    # 获取执行蓝图
    full_analysis = current_intent.full_analysis
    if not full_analysis or not full_analysis.execution_blueprint:
        return {
            "error_info": {
                "code": "NO_EXECUTION_BLUEPRINT",
                "message": "No execution blueprint found in intent analysis"
            }
        }

    blueprint = full_analysis.execution_blueprint

    # 生成提示词
    prompt = get_code_generation_prompt(
        blueprint=blueprint,
        recording_data=recording_data
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

        logger.info(f"代码生成响应长度: {len(response_text)} 字符")

        # 解析代码响应
        execution_code = _parse_code_response(response_text)

        # 创建 ToolDraft
        tool_draft = ToolDraft(
            tool_id=str(uuid.uuid4()),
            tool_name=blueprint.tool_name,
            description=blueprint.tool_summary,
            execution_code=execution_code,
            parameters=_convert_blueprint_parameters(blueprint.input_parameters),
            execution_strategy=_determine_execution_strategy(blueprint.category)
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
        logger.error(f"代码生成失败: {e}", exc_info=True)
        # 返回默认草稿
        tool_draft = ToolDraft(
            tool_id=str(uuid.uuid4()),
            tool_name=blueprint.tool_name or "示例工具",
            description=blueprint.tool_summary or "代码生成失败",
            execution_code=_generate_fallback_code(blueprint),
            parameters=_convert_blueprint_parameters(blueprint.input_parameters),
            execution_strategy="browser"
        )
        return {
            "tool_draft": tool_draft,
            "messages": [AIMessage(content=f"代码生成失败，使用默认草稿：{e}")]
        }


def _parse_code_response(response_text: str) -> str:
    """解析代码响应，提取 Python 代码"""
    # 查找 Python 代码块
    import re
    python_match = re.search(r"```python\s*(.*?)\s*```", response_text, re.DOTALL)
    if python_match:
        return python_match.group(1).strip()

    # 尝试查找没有语言标识的代码块
    code_match = re.search(r"```\s*(.*?)\s*```", response_text, re.DOTALL)
    if code_match:
        code = code_match.group(1).strip()
        # 简单判断是否是 Python 代码（包含 import 或 def）
        if "import " in code or "def " in code:
            return code

    # 直接返回整个响应
    return response_text.strip()


def _convert_blueprint_parameters(input_parameters: list) -> Dict[str, Any]:
    """将输入参数转换为旧格式"""
    params = {}
    for param in input_parameters:
        params[param.name] = {
            "type": param.type,
            "default": param.default_value,
            "description": param.description,
            "required": param.required
        }
    return params


def _determine_execution_strategy(category: str) -> str:
    """根据类别确定执行策略"""
    category_lower = category.lower()
    if "api" in category_lower:
        return "api"
    elif "browser" in category_lower:
        return "browser"
    else:
        return "hybrid"


def _generate_fallback_code(blueprint: ExecutionBlueprint) -> str:
    """生成备用代码"""
    return """# -*- coding: utf-8 -*-
import asyncio
import json
import sys
from playwright.async_api import async_playwright

async def execute(**kwargs) -> dict:
    '''执行工具'''
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            # TODO: 实现具体功能
            result = {"success": False, "message": "功能未实现", "data": None}

        except Exception as e:
            result = {"success": False, "message": str(e), "data": None}

        finally:
            await browser.close()

    return result


if __name__ == '__main__':
    params = {}
    for arg in sys.argv[1:]:
        if '=' in arg:
            key, value = arg.split('=', 1)
            params[key] = value

    result = asyncio.run(execute(**params))
    print(json.dumps(result, ensure_ascii=False))
"""


def _save_tool_draft(tool_draft: ToolDraft, recording_id: str = None):
    """保存工具草稿到数据库"""
    try:
        from src.data.repositories import ToolRepository
        from src.data.models_sqlite import Tool

        repo = ToolRepository()

        # 创建 Tool 对象
        tool = Tool(
            tool_id=tool_draft.tool_id,
            tool_name=tool_draft.tool_name,
            description=tool_draft.description,
            parameters=tool_draft.parameters if isinstance(tool_draft.parameters, list) else [],
            steps=[],
            execution_code=tool_draft.execution_code,
            code_language="python",
            code_version="1.0",
            execution_strategy=tool_draft.execution_strategy,
            source="intent",
            trial_count=0,
        )

        repo.create(tool)
        logger.info(f"工具草稿已保存: {tool_draft.tool_id}")

    except Exception as e:
        logger.error(f"保存工具草稿失败: {e}")