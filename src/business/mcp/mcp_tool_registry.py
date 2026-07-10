"""
McpToolRegistry — 进程级 MCP 工具注册表。

双轨注册（N8）：
- 轨道 A：预置 server 全量注入（保住"配置即可用"承诺）
- 轨道 B：用户自定义 server 走独立 LRU + search_tools 按需发现

线程安全：所有 getter 返回 snapshot，内部用 RLock 保护。
"""

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

from src.business.agents.config import ToolDefinition

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpCatalogItem:
    """MCP 工具目录项（用于 search_tools）。"""

    kind: str  # "mcp"
    name: str  # mcp__<server>__<tool>
    description: str = ""


class McpToolRegistry:
    """进程级 MCP 工具注册表，维护所有 running server 的工具。

    双轨：预置全量 + 自定义激活。线程安全 snapshot 语义。
    """

    MAX_ACTIVATED_CUSTOM = 10  # 独立 LRU，不与 DynamicToolManager 争用

    def __init__(self):
        self._all_tools: dict[str, ToolDefinition] = {}
        self._server_tool_map: dict[str, set[str]] = {}  # server_id → tool full names
        self._preset_tool_names: set[str] = set()
        self._activated_custom: OrderedDict[str, ToolDefinition] = OrderedDict()
        # 已知限制：_activated_custom 仅在进程内存中，sidecar 重启后清空。
        # 用户需重新 search + activate 自定义 server 工具。后续可考虑持久化到 SQLite。
        self._catalog_items: dict[str, McpCatalogItem] = {}
        self._lock = threading.RLock()

    def register_server_tools(
        self,
        server_id: str,
        slug: str,
        tools: list[Any],  # list[McpToolInfo]
        is_preset: bool,
        build_tool_definition_fn: Callable | None = None,
    ) -> list[ToolDefinition]:
        """注册一个 server 的所有工具（线程安全）。

        先清旧工具再注册新工具，返回注册的 ToolDefinition 列表。

        Args:
            server_id: server ID
            slug: 规范化后的 server slug（用于 mcp__ 前缀）
            tools: McpToolInfo 列表
            is_preset: 是否为预置 server
            build_tool_definition_fn: 可选的工具定义构建函数
        """
        with self._lock:
            # 清理旧工具
            old_names = self._server_tool_map.pop(server_id, set())
            for name in old_names:
                self._all_tools.pop(name, None)
                self._catalog_items.pop(name, None)
                self._preset_tool_names.discard(name)
                self._activated_custom.pop(name, None)

            # 注册新工具
            new_names: set[str] = set()
            registered: list[ToolDefinition] = []

            for tool in tools:
                full_name = f"mcp__{slug}__{tool.name}"
                description = (tool.description or "")[:500]  # N11: 截断 500 字符

                # 构建目录项
                self._catalog_items[full_name] = McpCatalogItem(
                    kind="mcp",
                    name=full_name,
                    description=description,
                )
                new_names.add(full_name)

                if is_preset:
                    self._preset_tool_names.add(full_name)

                # ToolDefinition 需要外部构建（因为需要 handler/pre_hook）
                # 如果提供了构建函数则使用，否则创建占位
                if build_tool_definition_fn is not None:
                    tool_def = build_tool_definition_fn(server_id, tool.name, full_name, tool)
                    self._all_tools[full_name] = tool_def
                    registered.append(tool_def)

            self._server_tool_map[server_id] = new_names
            return registered

    def unregister_server_tools(self, server_id: str) -> set[str]:
        """按映射表注销 server 的所有工具（不依赖前缀匹配）。"""
        with self._lock:
            names = self._server_tool_map.pop(server_id, set())
            for name in names:
                self._all_tools.pop(name, None)
                self._catalog_items.pop(name, None)
                self._preset_tool_names.discard(name)
                self._activated_custom.pop(name, None)
            return names

    def get_preset_tools(self) -> list[ToolDefinition]:
        """轨道 A：预置 server 工具全量注入（snapshot）。"""
        with self._lock:
            return [
                self._all_tools[n] for n in sorted(self._preset_tool_names) if n in self._all_tools
            ]

    def get_activated_custom_tools(self) -> list[ToolDefinition]:
        """轨道 B：已激活的自定义 server 工具（snapshot）。"""
        with self._lock:
            return list(self._activated_custom.values())

    def activate_custom_tool(self, full_name: str) -> bool:
        """get_tool_detail 激活自定义 MCP 工具（独立 LRU 淘汰）。"""
        with self._lock:
            if full_name in self._preset_tool_names:
                return True  # 预置工具已全量注入，无需激活

            tool = self._all_tools.get(full_name)
            if tool is None:
                return False

            self._activated_custom[full_name] = tool
            # LRU 淘汰
            while len(self._activated_custom) > self.MAX_ACTIVATED_CUSTOM:
                self._activated_custom.popitem(last=False)
            return True

    def get_catalog_items(self) -> list[McpCatalogItem]:
        """snapshot，供 search_tools 搜索。"""
        with self._lock:
            return list(self._catalog_items.values())

    def find_tool(self, full_name: str) -> ToolDefinition | None:
        """按全名查找工具定义。"""
        with self._lock:
            return self._all_tools.get(full_name)

    def get_tool_count(self) -> tuple[int, int]:
        """返回 (preset_count, custom_count)。"""
        with self._lock:
            preset_count = len(self._preset_tool_names)
            total_count = len(self._all_tools)
            custom_count = max(0, total_count - preset_count)
            return preset_count, custom_count

    def register_tool_definition(
        self,
        full_name: str,
        tool_def: ToolDefinition,
        server_id: str,
        is_preset: bool,
    ) -> None:
        """注册已构建好的 ToolDefinition（供 Service 使用）。"""
        with self._lock:
            self._all_tools[full_name] = tool_def
            if is_preset:
                self._preset_tool_names.add(full_name)
            # 确保 server_tool_map 中有该 server
            if server_id not in self._server_tool_map:
                self._server_tool_map[server_id] = set()
            self._server_tool_map[server_id].add(full_name)


class NullRegistry:
    """SDK 不可用时的空实现（RC10）。

    所有方法返回空 list/False，tool_factory() 不抛异常，agent 正常跑。
    """

    def register_server_tools(self, *args, **kwargs) -> list:
        return []

    def unregister_server_tools(self, *args, **kwargs) -> set:
        return set()

    def get_preset_tools(self) -> list:
        return []

    def get_activated_custom_tools(self) -> list:
        return []

    def activate_custom_tool(self, full_name: str) -> bool:
        return False

    def get_catalog_items(self) -> list:
        return []

    def find_tool(self, full_name: str) -> None:
        return None

    def get_tool_count(self) -> tuple[int, int]:
        return 0, 0

    def register_tool_definition(self, *args, **kwargs) -> None:
        pass
