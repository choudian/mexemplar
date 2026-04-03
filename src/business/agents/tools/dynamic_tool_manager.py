"""
动态工具管理器

管理用户工具的懒加载 FC 注入：
- search_tools: 搜索匹配的用户工具
- get_tool_detail: 查看工具参数详情，同时激活该工具的 FC schema
- LRU 淘汰机制：最多同时激活 MAX_ACTIVATED 个用户工具
"""

import json
import logging
from collections import OrderedDict
from typing import Callable, List, Optional, Set

from src.business.agents.config import ToolDefinition
from src.business.agents.tool_helpers import make_tool_schema, error_json
from src.data.repositories import ToolRepository
from src.execution.tool_executor import run_tool_code

logger = logging.getLogger(__name__)

# =============================================================================
# 常量
# =============================================================================

# 重复模式检测参数
SUGGESTION_THRESHOLD = 3   # 执行 N 次后建议工具化
SUGGESTION_COOLDOWN = 5    # 拒绝后冷却 N 次才再次建议


def _check_tool_suggestion(tool_name: str) -> Optional[str]:
    """
    检测重复模式：工具执行成功时更新计数，达到阈值时返回建议文本。
    纯代码逻辑，不走 LLM。

    Returns:
        建议文本（如有），或 None
    """
    try:
        from src.data.repositories import ToolSuggestionRepository, ToolRepository

        repo = ToolSuggestionRepository()
        record = repo.get_by_pattern(tool_name)

        if record is None:
            repo.create(tool_name)
            return None

        repo.increment(record)

        # 已有对应已发布工具则不建议
        tool = ToolRepository().get_by_name(tool_name)
        if tool and tool.status == "published":
            return None

        # 冷却期检查：如果最近已被拒绝，等待 SUGGESTION_COOLDOWN 次执行后再建议
        if record.accepted is False:
            if record.times_seen < SUGGESTION_COOLDOWN:
                return None
            # 冷却期结束，重置拒绝状态，允许再次建议
            repo.reset_accepted(record)

        # 是否达到阈值
        if record.times_seen < SUGGESTION_THRESHOLD:
            return None

        logger.info(f"[重复模式检测] 工具 {tool_name} 已执行 {record.times_seen} 次，建议工具化")
        return (
            f"（提示：你已使用这个操作 {record.times_seen} 次了。"
            f"要不要把它做成一个工具？以后直接调用会更快。）"
        )

    except Exception as e:
        logger.warning(f"[_check_tool_suggestion] 失败: {e}")
        return None


# FC schema 定义
SEARCH_TOOLS_SCHEMA = make_tool_schema(
    name="search_tools",
    description="按关键词搜索可用的用户工具。当不确定该用哪个工具时使用。",
    properties={
        "query": {"type": "string", "description": "搜索关键词或意图描述"},
    },
    required=["query"],
)

GET_TOOL_DETAIL_SCHEMA = make_tool_schema(
    name="get_tool_detail",
    description="获取指定用户工具的完整参数说明。调用不熟悉的工具前，先用这个查看参数格式。",
    properties={
        "tool_name": {"type": "string", "description": "工具名称"},
    },
    required=["tool_name"],
)


class DynamicToolManager:
    """管理用户工具的懒加载 FC 注入"""

    MAX_ACTIVATED = 10

    def __init__(self, allowed_tool_ids: Optional[Set[str]] = None):
        """
        Args:
            allowed_tool_ids: 允许使用的工具 ID 集合。None 表示全部已发布工具。
        """
        self._activated_tools: OrderedDict[str, ToolDefinition] = OrderedDict()
        self._short_id_to_tool_id: dict[str, str] = {}  # utool_xxx → tool_id
        self._tool_id_to_short_id: dict[str, str] = {}  # tool_id → utool_xxx
        self._allowed_tool_ids = allowed_tool_ids

    def _is_allowed(self, tool) -> bool:
        """检查工具是否在允许范围内"""
        if self._allowed_tool_ids is None:
            return tool.status == "published"
        return tool.tool_id in self._allowed_tool_ids and tool.status == "published"

    def _make_short_id(self, tool_id: str) -> str:
        """生成规范化短名称，碰撞时取更长前缀"""
        short = f"utool_{tool_id[:8]}"
        if short in self._short_id_to_tool_id and self._short_id_to_tool_id[short] != tool_id:
            short = f"utool_{tool_id[:12]}"
        return short

    def search_tools(self, query: str) -> str:
        """按关键词搜索已发布的用户工具"""
        repo = ToolRepository()
        tools = repo.search_published(query)
        if self._allowed_tool_ids is not None:
            tools = [t for t in tools if t.tool_id in self._allowed_tool_ids]
        if not tools:
            return "没有找到匹配的工具。"
        lines = [f"- {t.tool_name}：{t.description or '（无描述）'}" for t in tools[:10]]
        return "找到以下工具：\n" + "\n".join(lines)

    def get_tool_detail(self, tool_name: str) -> str:
        """查看工具详情，同时激活该工具的 FC schema"""
        repo = ToolRepository()
        tool = repo.get_by_name(tool_name)
        if not tool or not self._is_allowed(tool):
            return f"工具 '{tool_name}' 不存在或未发布"

        # 构建 FC schema 并标记为已激活
        tool_def = self._build_tool_definition(tool)
        short_id = self._make_short_id(tool.tool_id)
        if short_id in self._activated_tools:
            self._activated_tools.move_to_end(short_id)
        self._activated_tools[short_id] = tool_def
        self._short_id_to_tool_id[short_id] = tool.tool_id
        self._tool_id_to_short_id[tool.tool_id] = short_id

        # 超出上限时淘汰最久未使用的工具
        while len(self._activated_tools) > self.MAX_ACTIVATED:
            oldest, _ = self._activated_tools.popitem(last=False)
            old_tool_id = self._short_id_to_tool_id.pop(oldest, None)
            if old_tool_id:
                self._tool_id_to_short_id.pop(old_tool_id, None)

        return self._format_detail(tool)

    def get_activated_tools(self) -> List[ToolDefinition]:
        """获取已激活的用户工具列表，供 AgentLoop 在下一轮注入 FC schema"""
        return list(self._activated_tools.values())

    def _build_tool_definition(self, tool) -> ToolDefinition:
        """从 Tool 模型构建 ToolDefinition"""
        short_id = self._make_short_id(tool.tool_id)
        schema = self._build_tool_schema(tool, short_id)
        handler = self._create_tool_handler(tool.tool_id)
        return ToolDefinition(name=short_id, schema=schema, handler=handler)

    def _build_tool_schema(self, tool, short_id: str) -> dict:
        """从 Tool 模型构建 FC schema"""
        properties = {}
        required = []
        for param in (tool.parameters or []):
            properties[param["name"]] = {
                "type": param.get("type", "string"),
                "description": param.get("description", ""),
            }
            if param.get("required", False):
                required.append(param["name"])

        return make_tool_schema(
            name=short_id,
            description=tool.description or "",
            properties=properties,
            required=required,
        )

    def _create_tool_handler(self, tool_id: str) -> Callable:
        """为指定工具创建执行 handler（闭包绑定 tool_id，创建时缓存工具信息）"""
        repo = ToolRepository()
        tool = repo.get_by_id(tool_id)
        # 创建时缓存 execution_code 和 dependencies，避免每次执行都查 DB
        if not tool or not tool.execution_code:
            def _unavailable_handler(**kwargs) -> str:
                return error_json("工具不可用")
            return _unavailable_handler

        cached_code = tool.execution_code
        cached_deps = tool.dependencies or []
        cached_name = tool.tool_name

        def handler(**kwargs) -> str:
            result = run_tool_code(cached_code, kwargs, cached_deps)

            # 执行成功时检测重复模式，可能追加工具化建议
            if result.get("success"):
                suggestion = _check_tool_suggestion(cached_name)
                if suggestion:
                    result["_suggestion"] = suggestion

            return json.dumps(result, ensure_ascii=False, default=str)

        return handler

    def _format_detail(self, tool) -> str:
        """格式化工具详情供 LLM 阅读"""
        lines = [f"工具名称：{tool.tool_name}"]
        if tool.description:
            lines.append(f"描述：{tool.description}")
        lines.append("参数列表：")
        for param in (tool.parameters or []):
            req = "（必填）" if param.get("required") else "（选填）"
            lines.append(
                f"  - {param['name']}{req}：{param.get('description', '无描述')} "
                f"[类型: {param.get('type', 'string')}]"
            )
        if not tool.parameters:
            lines.append("  （无参数）")
        lines.append("\n工具已激活，你现在可以直接调用它了。")
        return "\n".join(lines)


def create_assistant_search_tools(manager: "DynamicToolManager") -> List[ToolDefinition]:
    """创建 search_tools 和 get_tool_detail 工具定义（闭包绑定 manager 实例）"""
    return [
        ToolDefinition(
            name="search_tools",
            schema=SEARCH_TOOLS_SCHEMA,
            handler=lambda query: manager.search_tools(query),
        ),
        ToolDefinition(
            name="get_tool_detail",
            schema=GET_TOOL_DETAIL_SCHEMA,
            handler=lambda tool_name: manager.get_tool_detail(tool_name),
        ),
    ]
