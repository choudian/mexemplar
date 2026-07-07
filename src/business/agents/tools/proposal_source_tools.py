"""Assistant-only tools for inspecting improvement proposal sources."""

from __future__ import annotations

import json
from typing import Any

from src.business.agents.config import ToolDefinition
from src.business.self_improvement.proposal_source_inspector import (
    ProposalSourceForbidden,
    ProposalSourceInspector,
    ProposalSourceInvalidView,
    ProposalSourceNotFound,
)


INSPECT_PROPOSAL_SOURCE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "inspect_proposal_source",
        "description": (
            "只读查看当前改进提案讨论绑定的来源证据包。用于分析这条提案为什么会生成、"
            "证据是否充分，以及自我提升复盘提示词是否需要收紧。只能在对应提案讨论会话中使用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "proposalId": {
                    "type": "string",
                    "description": "可选；省略时使用当前讨论会话绑定的提案。若提供，必须与当前会话绑定一致。",
                },
                "view": {
                    "type": "string",
                    "enum": ["overview", "messages"],
                    "description": "overview 返回证据包地图；messages 分页返回来源会话消息预览。",
                    "default": "overview",
                },
                "cursor": {
                    "type": "string",
                    "description": "messages view 的分页游标；使用上一次返回的 page.nextCursor。",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "messages view 每页条数，默认 20。",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def discussion_source_tool_available(session_id: str) -> bool:
    """Return whether the assistant session is bound to a proposal discussion."""
    if not session_id:
        return False
    return ProposalSourceInspector().bound_proposal_id_for_session(session_id) is not None


def create_inspect_proposal_source_tool(session_id: str) -> ToolDefinition:
    def handler(
        proposalId: str | None = None,
        view: str = "overview",
        cursor: str | None = None,
        limit: int | None = None,
    ) -> str:
        try:
            package = ProposalSourceInspector().inspect(
                proposalId,
                view=view,
                cursor=cursor,
                limit=limit,
                discussion_session_id=session_id,
                enforce_discussion=True,
            )
            return json.dumps({"ok": True, "package": package}, ensure_ascii=False)
        except ProposalSourceForbidden:
            return json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "proposal_source_forbidden",
                        "message": "这个工具只能在对应改进提案的讨论会话中使用。",
                    },
                },
                ensure_ascii=False,
            )
        except ProposalSourceInvalidView:
            return json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "invalid_view",
                        "message": "不支持的来源视图。可用 view: overview, messages。",
                    },
                },
                ensure_ascii=False,
            )
        except ProposalSourceNotFound:
            return json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "proposal_source_not_found",
                        "message": "没有找到当前讨论绑定的改进提案或来源记录。",
                    },
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "proposal_source_error",
                        "message": f"读取提案来源失败：{exc.__class__.__name__}",
                    },
                },
                ensure_ascii=False,
            )

    return ToolDefinition(
        name="inspect_proposal_source",
        schema=INSPECT_PROPOSAL_SOURCE_SCHEMA,
        handler=handler,
        has_side_effects=False,
    )


__all__ = [
    "INSPECT_PROPOSAL_SOURCE_SCHEMA",
    "create_inspect_proposal_source_tool",
    "discussion_source_tool_available",
]
