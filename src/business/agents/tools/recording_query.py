"""
录制数据查询工具

用于查询录制会话中的数据。
"""

from src.business.agents.tool_registry import agent_tool
from src.business.agents.validation import validate_parameters
from typing import List, Optional, Dict
import json
import logging

logger = logging.getLogger(__name__)


@agent_tool(
    name="query_recording_data",
    description="查询录制数据，支持字段过滤和数量限制。返回录制会话中的事件数据。",
    parameters_schema={
        "type": "object",
        "properties": {
            "recording_id": {"type": "string", "description": "录制会话 ID"},
            "fields": {"type": "array", "items": {"type": "string"}, "description": "要返回的字段列表，如 ['action_type', 'url', 'selector']"},
            "filters": {"type": "object", "description": "过滤条件，如 {'action_type': 'click'}"},
            "limit": {"type": "integer", "description": "返回数量限制，默认 100"}
        },
        "required": ["recording_id"]
    }
)
@validate_parameters({
    "type": "object",
    "required": ["recording_id"],
    "properties": {
        "recording_id": {"type": "string"},
        "limit": {"type": "integer"}
    }
})
def query_recording_data(
    recording_id: str,
    fields: Optional[List[str]] = None,
    filters: Optional[Dict] = None,
    limit: int = 100
) -> str:
    """
    查询录制数据

    Args:
        recording_id: 录制会话 ID
        fields: 要返回的字段列表
        filters: 过滤条件
        limit: 返回数量限制

    Returns:
        JSON 格式的查询结果
    """
    # TODO: 实现实际查询逻辑
    # 当前返回模拟数据
    result = {
        "recording_id": recording_id,
        "count": 0,
        "data": [],
        "fields": fields,
        "filters": filters,
        "limit": limit
    }
    logger.debug(f"[录制数据查询] recording_id={recording_id}, limit={limit}")
    return json.dumps(result, ensure_ascii=False)