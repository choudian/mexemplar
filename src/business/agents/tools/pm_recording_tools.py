"""
PM Agent — 录制数据查询工具

PM 版本的 query_recording_data：支持 action_summary / action_detail /
element_context / screenshot 四种查询类型。不支持网络请求查询（需求分析阶段
网络请求噪声大，由程序员 Agent 负责）。

数据库访问通过 RecordingRepository，遵守 CLAUDE.md 约束。
"""

import json
import logging
from typing import Any, Dict, Optional

from src.data.recording_repository import RecordingRepository
from src.business.agents.config import ToolDefinition

logger = logging.getLogger(__name__)

# =============================================================================
# Function Calling Schema
# =============================================================================

PM_QUERY_RECORDING_DATA_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_recording_data",
        "description": (
            "查询录制数据。支持查询操作流程、操作详情、元素上下文、截图等。"
            "不支持查询网络请求（那是程序员的职责）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "recording_id": {
                    "type": "string",
                    "description": "录制会话 ID",
                },
                "query_type": {
                    "type": "string",
                    "enum": ["action_summary", "action_detail", "element_context", "screenshot"],
                    "description": (
                        "查询类型：action_summary=操作流程概览, "
                        "action_detail=单个操作详情, "
                        "element_context=元素上下文（兄弟元素、列表信息）, "
                        "screenshot=操作截图"
                    ),
                },
                "action_index": {
                    "type": "integer",
                    "description": (
                        "操作序号（从1开始）。" "action_detail、element_context、screenshot 时必填"
                    ),
                },
            },
            "required": ["recording_id", "query_type"],
        },
    },
}


# =============================================================================
# 内部辅助函数
# =============================================================================


def _generate_action_description(action: Dict[str, Any]) -> str:
    """
    根据 action 字段生成一句可读描述（用于 action_summary 的 description 字段）。

    Args:
        action: 来自 RecordingRepository.get_actions() 的单条操作字典

    Returns:
        可读描述字符串
    """
    action_type = action.get("action_type", "")
    params = action.get("parameters") or {}
    element = action.get("dom_element") or {}
    url = action.get("url", "")

    if action_type == "navigate":
        return f"打开 {url}"

    if action_type in ("keyboard_input", "fill"):
        text = params.get("text") or params.get("value", "")
        if text:
            return f"输入 '{str(text)[:30]}'"
        key = params.get("key", "")
        return f"按键 {key}"

    if action_type == "click":
        text = element.get("text_content", "")
        if text and len(str(text)) <= 30:
            return f"点击 '{text}'"
        tag = element.get("tag_name", "").lower()
        return f"点击 {tag} 元素"

    if action_type == "change":
        value = params.get("value", "")
        tag = element.get("tag_name", "").lower()
        return f"选择/修改 {tag}（值: {value}）"

    if action_type == "submit":
        return "提交表单"

    if action_type == "dblclick":
        text = element.get("text_content", "")
        return f"双击 '{text}'" if text else "双击元素"

    if action_type == "keydown":
        key = params.get("key", "")
        modifiers = []
        if params.get("ctrlKey"):
            modifiers.append("Ctrl")
        if params.get("altKey"):
            modifiers.append("Alt")
        if params.get("shiftKey"):
            modifiers.append("Shift")
        prefix = "+".join(modifiers) + "+" if modifiers else ""
        return f"按键 {prefix}{key}"

    return f"{action_type} 操作"


def _has_input(action: Dict[str, Any]) -> bool:
    """判断操作是否包含用户输入"""
    action_type = action.get("action_type", "")
    if action_type in ("keyboard_input", "fill"):
        return True
    element = action.get("dom_element") or {}
    tag = element.get("tag_name", "").lower()
    if action_type == "change" and tag in ("input", "textarea", "select"):
        return True
    return False


# =============================================================================
# 查询处理函数
# =============================================================================


def _query_action_summary(repo: RecordingRepository, recording_id: str) -> Dict[str, Any]:
    """
    操作流程概览查询。

    遍历 actions 表，为每个操作生成一行摘要，并标记 has_input / has_siblings。
    """
    actions = repo.get_actions(recording_id)
    summary_items = []

    for idx, action in enumerate(actions, start=1):
        action_id = action.get("action_id")
        sibling = repo.get_sibling_snapshot(action_id) if action_id else None

        summary_items.append(
            {
                "index": idx,
                "action_type": action.get("action_type", ""),
                "url": action.get("url", ""),
                "description": _generate_action_description(action),
                "has_input": _has_input(action),
                "has_siblings": sibling is not None,
            }
        )

    return {
        "recording_id": recording_id,
        "total_actions": len(actions),
        "actions": summary_items,
    }


def _query_action_detail(
    repo: RecordingRepository,
    recording_id: str,
    action_index: int,
) -> Dict[str, Any]:
    """
    单个操作详情查询。

    返回操作的完整字段（不含 dom_tree_snapshot 和 visual_features，那是技术细节）。
    """
    actions = repo.get_actions(recording_id)
    if action_index < 1 or action_index > len(actions):
        return {"error": f"操作序号 {action_index} 超出范围（共 {len(actions)} 步）"}

    action = actions[action_index - 1]

    return {
        "index": action_index,
        "action_type": action.get("action_type", ""),
        "url": action.get("url", ""),
        "timestamp": str(action.get("timestamp", "")),
        "parameters": action.get("parameters") or {},
        "dom_element": action.get("dom_element"),
    }


def _query_element_context(
    repo: RecordingRepository,
    recording_id: str,
    action_index: int,
) -> Dict[str, Any]:
    """
    元素上下文（兄弟元素）查询。

    PM 用来判断操作是否为列表操作。
    兄弟元素超过 10 个时，只返回前 5 + 后 5 并标注 truncated。
    """
    actions = repo.get_actions(recording_id)
    if action_index < 1 or action_index > len(actions):
        return {"error": f"操作序号 {action_index} 超出范围（共 {len(actions)} 步）"}

    action = actions[action_index - 1]
    action_id = action.get("action_id")
    snapshot = repo.get_sibling_snapshot(action_id) if action_id else None

    if not snapshot:
        return {"index": action_index, "has_siblings": False}

    raw_siblings = snapshot.get("siblings") or []
    if not isinstance(raw_siblings, list):
        raw_siblings = []

    total = len(raw_siblings)
    truncated = False

    # 截断：超过 10 个时保留前 5 + 后 5（含 clicked 项）
    if total > 10:
        keep = raw_siblings[:5] + raw_siblings[-5:]
        truncated = True
    else:
        keep = raw_siblings

    clicked_index = snapshot.get("clicked_index")

    items = []
    for sib in keep:
        if not isinstance(sib, dict):
            continue
        items.append(
            {
                "index": sib.get("index"),
                "text_summary": sib.get("text_summary", ""),
                "has_link": bool(sib.get("has_link")),
                "clicked": sib.get("index") == clicked_index,
            }
        )

    sibling_info: Dict[str, Any] = {
        "container_selector": snapshot.get("container_selector", ""),
        "item_selector": snapshot.get("item_selector", ""),
        "list_type": snapshot.get("list_type", ""),
        "total_count": total,
        "clicked_index": clicked_index,
        "items": items,
    }
    if truncated:
        sibling_info["truncated"] = True

    return {
        "index": action_index,
        "has_siblings": True,
        "siblings": sibling_info,
    }


def _query_screenshot(
    repo: RecordingRepository,
    recording_id: str,
    action_index: int,
) -> Dict[str, Any]:
    """
    操作截图查询。

    注意：浏览器录制模式下截图始终为空，PM 应依赖文本数据分析。
    """
    actions = repo.get_actions(recording_id)
    if action_index < 1 or action_index > len(actions):
        return {"error": f"操作序号 {action_index} 超出范围（共 {len(actions)} 步）"}

    action = actions[action_index - 1]
    screenshot_before = action.get("screenshot_before")
    screenshot_after = action.get("screenshot_after")

    return {
        "index": action_index,
        "has_screenshot_before": bool(screenshot_before),
        "has_screenshot_after": bool(screenshot_after),
        "screenshot_before": screenshot_before,
        "screenshot_after": screenshot_after,
    }


# =============================================================================
# Handler
# =============================================================================


def _pm_query_recording_data(
    recording_id: str,
    query_type: str,
    action_index: Optional[int] = None,
) -> str:
    """
    PM Agent 录制数据查询 handler。

    数据库访问通过 RecordingRepository，不直接执行 SQL。

    Args:
        recording_id: 录制会话 ID
        query_type: 查询类型（action_summary / action_detail / element_context / screenshot）
        action_index: 操作序号（从 1 开始），action_detail / element_context / screenshot 时必填

    Returns:
        JSON 字符串
    """
    repo = RecordingRepository()
    logger.debug(f"[PM 录制查询] recording_id={recording_id}, query_type={query_type}")

    try:
        if query_type == "action_summary":
            result = _query_action_summary(repo, recording_id)

        elif query_type == "action_detail":
            if action_index is None:
                result = {"error": "action_detail 查询需要提供 action_index"}
            else:
                result = _query_action_detail(repo, recording_id, action_index)

        elif query_type == "element_context":
            if action_index is None:
                result = {"error": "element_context 查询需要提供 action_index"}
            else:
                result = _query_element_context(repo, recording_id, action_index)

        elif query_type == "screenshot":
            if action_index is None:
                result = {"error": "screenshot 查询需要提供 action_index"}
            else:
                result = _query_screenshot(repo, recording_id, action_index)

        else:
            result = {"error": f"不支持的 query_type: {query_type}"}

    except Exception as e:
        logger.error(f"[PM 录制查询] 查询失败: {e}", exc_info=True)
        result = {"error": f"查询失败: {str(e)}"}

    return json.dumps(result, ensure_ascii=False, default=str)


# =============================================================================
# ToolDefinition 实例（由 Orchestrator 组装后传入 loop.run()）
# =============================================================================

pm_query_recording_data = ToolDefinition(
    name="query_recording_data",
    schema=PM_QUERY_RECORDING_DATA_SCHEMA,
    handler=_pm_query_recording_data,
)

__all__ = ["pm_query_recording_data", "PM_QUERY_RECORDING_DATA_SCHEMA"]
