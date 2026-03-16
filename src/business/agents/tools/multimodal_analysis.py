"""
多模态分析工具

使用 LLM 进行图像、截图等多模态内容分析。
"""

from src.business.agents.tool_registry import agent_tool
from src.business.agents.validation import validate_parameters
from typing import Optional, List
import json
import logging

logger = logging.getLogger(__name__)


@agent_tool(
    name="multimodal_analysis",
    description="分析图像或截图内容，提取关键信息。支持分析网页截图、UI 元素等。",
    parameters_schema={
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "图片文件路径"},
            "question": {"type": "string", "description": "分析问题，如 '这是什么页面？'、'找到登录按钮的位置'"},
            "detail": {"type": "string", "description": "分析详细程度，可选 'low'、'high'，默认 'low'"}
        },
        "required": ["image_path", "question"]
    }
)
@validate_parameters({
    "type": "object",
    "required": ["image_path", "question"],
    "properties": {
        "image_path": {"type": "string"},
        "question": {"type": "string"}
    }
})
def multimodal_analysis(
    image_path: str,
    question: str,
    detail: str = "low"
) -> str:
    """
    多模态分析

    Args:
        image_path: 图片文件路径
        question: 分析问题
        detail: 分析详细程度

    Returns:
        JSON 格式的分析结果
    """
    # TODO: 实现实际的多模态分析逻辑
    # 当前返回模拟数据
    result = {
        "image_path": image_path,
        "question": question,
        "answer": "模拟分析结果：图片内容待实际实现",
        "detail": detail
    }
    logger.debug(f"[多模态分析] image_path={image_path}, question={question}")
    return json.dumps(result, ensure_ascii=False)