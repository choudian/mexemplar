"""
PM Agent — 多模态分析工具

使用 LLM 分析操作截图，辅助 PM 理解页面视觉布局。
这是非常规手段，兜底用。截图数据需要先通过 query_recording_data（query_type=screenshot）获取。

当前状态：截图功能仅桌面录制实现，浏览器录制模式下此工具实质上不可用。
实现为占位，配置就绪后可直接启用。
"""

import logging
from typing import Any, Dict

from src.business.agents.config import ToolDefinition

logger = logging.getLogger(__name__)

# =============================================================================
# Function Calling Schema
# =============================================================================

MULTIMODAL_ANALYSIS_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "multimodal_analysis",
        "description": (
            "分析操作截图，理解页面视觉布局。"
            "这是一个消耗大量 token 的操作，只在文本信息不够时才使用。"
            "截图数据需要先通过 query_recording_data（query_type=screenshot）获取。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "screenshot_data": {
                    "type": "string",
                    "description": (
                        "截图的 base64 数据"
                        "（从 query_recording_data 的 screenshot 查询结果中获取）"
                    ),
                },
                "question": {
                    "type": "string",
                    "description": (
                        "分析问题，如"
                        "'这个页面上有什么表单元素？'、"
                        "'用户点击的是页面的哪个区域？'"
                    ),
                },
            },
            "required": ["screenshot_data", "question"],
        },
    },
}


# =============================================================================
# Handler
# =============================================================================


def _multimodal_analysis(screenshot_data: str, question: str) -> str:
    """
    多模态截图分析 handler。

    使用 compression_model（Haiku 级别）分析截图，控制成本。
    当前为占位实现：截图功能仅桌面录制实现，浏览器录制模式下截图始终为空。

    Args:
        screenshot_data: 截图 base64 数据（data:image/png;base64,... 格式）
        question: 分析问题

    Returns:
        分析结果字符串
    """
    logger.debug(f"[PM 多模态分析] question={question[:50]}")

    if not screenshot_data:
        return (
            "截图数据为空。浏览器录制模式下截图功能尚未实现，"
            "请依赖文本数据（操作描述、元素属性）进行分析。"
        )

    # TODO: 截图功能就绪后，取消注释以下实现
    # from src.data.unified_config import get_unified_config
    # config = get_unified_config()
    # llm = LangChainLLMClient(
    #     provider=config.get_compression_model_provider(),
    #     model=config.get_compression_model_name(),
    #     api_key=config.get_compression_model_api_key(),
    # )
    # messages = [
    #     {
    #         "role": "user",
    #         "content": [
    #             {
    #                 "type": "image",
    #                 "source": {
    #                     "type": "base64",
    #                     "media_type": "image/png",
    #                     "data": screenshot_data.replace("data:image/png;base64,", ""),
    #                 },
    #             },
    #             {"type": "text", "text": question},
    #         ],
    #     }
    # ]
    # return llm.chat_with_messages(messages)

    return (
        "多模态分析功能尚未就绪（截图采集功能仅桌面录制实现）。"
        "请依赖文本数据（操作描述、元素属性、兄弟元素信息）进行需求分析。"
    )


# =============================================================================
# ToolDefinition 实例（由 Orchestrator 组装后传入 loop.run()）
# =============================================================================

multimodal_analysis = ToolDefinition(
    name="multimodal_analysis",
    schema=MULTIMODAL_ANALYSIS_SCHEMA,
    handler=_multimodal_analysis,
)

__all__ = ["multimodal_analysis", "MULTIMODAL_ANALYSIS_SCHEMA"]
