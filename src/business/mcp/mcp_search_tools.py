"""
MCP-aware search_tools / get_tool_detail wrapper（RC6 路 A）。

独立 wrapper，kind enum 含 "mcp"，不碰 DynamicToolManager。
直接调 dynamic_manager._current_catalog_items() 取用户技能/组合原始 items，
合并 mcp_registry.get_catalog_items()，自己用 search_capability_catalog 做搜索。
"""

import json
import logging
from typing import Any

from src.business.agents.config import ToolDefinition
from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager

logger = logging.getLogger(__name__)


def create_mcp_aware_search_tools(
    dynamic_manager: DynamicToolManager,
    mcp_registry: Any,  # McpToolRegistry | NullRegistry
) -> list[ToolDefinition]:
    """创建 MCP-aware search_tools + get_tool_detail。

    RC6 路 A：独立 wrapper，kind enum 含 "mcp"，不碰 DynamicToolManager。
    """
    # 独立 schema，kind enum 含 "mcp"
    search_tools_schema = {
        "type": "function",
        "function": {
            "name": "search_tools",
            "description": (
                "浏览或搜索用户技能/技能组合/MCP 工具，支持类型过滤和稳定分页。"
                "kind='mcp' 可搜索 MCP 工具；server_slug 可按 server 过滤。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "可选搜索关键词或意图描述；留空时浏览目录",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["all", "tool", "composition", "mcp"],
                        "description": "能力类型过滤，默认 all",
                    },
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "分页偏移，默认 0",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "页大小；省略时使用统一配置默认值",
                    },
                    "server_slug": {
                        "type": "string",
                        "description": "可选，按 MCP server slug 过滤",
                    },
                },
                "required": [],
            },
        },
    }

    get_tool_detail_schema = {
        "type": "function",
        "function": {
            "name": "get_tool_detail",
            "description": (
                "获取指定用户技能/技能组合/MCP 工具的完整说明，并激活其可调用定义。"
                "MCP 工具使用 'mcp:工具全名' selector，如 'mcp:mcp__github__list_prs'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": (
                            "技能名称，或使用 '技能:名称'/'技能组合:名称'/'mcp:全名' 消除歧义"
                        ),
                    },
                },
                "required": ["tool_name"],
            },
        },
    }

    def _search_tools_handler(
        query: str = "",
        kind: str = "all",
        offset: int = 0,
        limit: int | None = None,
        server_slug: str | None = None,
    ) -> str:
        """MCP-aware search_tools handler。"""
        try:
            # 获取用户技能/组合 catalog items
            try:
                skill_items = dynamic_manager._current_catalog_items()
            except Exception:
                skill_items = []

            # 获取 MCP catalog items
            mcp_items = mcp_registry.get_catalog_items()

            # 合并
            all_items = list(skill_items) + list(mcp_items)

            # 按 server_slug 过滤 MCP items
            if server_slug:
                all_items = [
                    item for item in all_items if _item_matches_server_slug(item, server_slug)
                ]

            # 使用 search_capability_catalog 做搜索
            from src.business.agents.tools.capability_catalog import (
                search_capability_catalog,
                load_capability_discovery_policy,
            )

            policy = load_capability_discovery_policy()
            page = search_capability_catalog(
                all_items,
                policy,
                query=query,
                kind=kind,
                offset=offset,
                limit=limit,
            )

            return json.dumps(
                {
                    "items": [
                        {
                            "name": item.name,
                            "kind": item.kind,
                            "description": item.description[:200],
                        }
                        for item in page.items
                    ],
                    "total": page.total,
                    "offset": page.offset,
                    "limit": page.limit,
                }
            )
        except Exception as exc:
            logger.error("[MCP] search_tools error: %s", exc)
            return json.dumps({"error": str(exc)[:500]})

    def _get_tool_detail_handler(tool_name: str = "") -> str:
        """MCP-aware get_tool_detail handler。"""
        try:
            # MCP selector: "mcp:full_name"
            if tool_name.startswith("mcp:"):
                full_name = tool_name[4:]
                tool_def = mcp_registry.find_tool(full_name)
                if tool_def is None:
                    return json.dumps(
                        {
                            "error": "tool_not_found",
                            "message": f"MCP 工具 '{full_name}' 不存在",
                        }
                    )

                # 激活自定义 MCP 工具
                activated = mcp_registry.activate_custom_tool(full_name)

                return json.dumps(
                    {
                        "name": tool_def.name,
                        "description": tool_def.schema.get("description", ""),
                        "parameters": tool_def.schema.get("parameters", {}),
                        "kind": "mcp",
                        "activated": activated,
                    }
                )

            # 非 MCP：委托给 DynamicToolManager
            return dynamic_manager.get_tool_detail(tool_name)
        except Exception as exc:
            logger.error("[MCP] get_tool_detail error: %s", exc)
            return json.dumps({"error": str(exc)[:500]})

    return [
        ToolDefinition(
            name="search_tools",
            schema=search_tools_schema,
            handler=_search_tools_handler,
            has_side_effects=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="get_tool_detail",
            schema=get_tool_detail_schema,
            handler=_get_tool_detail_handler,
            has_side_effects=False,
            is_concurrency_safe=False,
        ),
    ]


def _item_matches_server_slug(item: Any, server_slug: str) -> bool:
    """检查 catalog item 是否匹配 server_slug（P3-R2）。"""
    if not hasattr(item, "name") or not hasattr(item, "kind"):
        return True  # 非 MCP item 不过滤

    if getattr(item, "kind", "") != "mcp":
        return True  # 非 MCP item 不过滤

    # MCP item: name 格式为 mcp__<server_slug>__<tool_name>
    name = getattr(item, "name", "")
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) >= 3:
            item_slug = parts[1]
            return item_slug == server_slug
        return False  # 格式不完整的 MCP 工具名，排除

    return True
