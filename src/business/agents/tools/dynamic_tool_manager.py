"""
动态工具管理器

管理用户技能与技能组合的懒加载 FC 注入：
- search_tools: 搜索匹配的用户技能 / 技能组合
- get_tool_detail: 查看详情，同时激活对应的 FC schema
- 技能组合调用后，可动态激活其成员技能
- LRU 淘汰机制：最多同时激活 MAX_ACTIVATED 个用户能力
"""

import logging
import threading
from collections import OrderedDict
from typing import Callable, List, Optional, Set, Tuple

from src.business.agents.config import ToolDefinition
from src.business.agents.tools.capability_catalog import (
    CapabilityCatalogItem,
    load_capability_discovery_policy,
    search_capability_catalog,
)
from src.business.agents.tool_helpers import make_tool_schema, error_json, to_json
from src.business.services.skill_composition_service import SkillCompositionService
from src.data.models import MODE_DISPLAY_TEXT, sort_composition_members
from src.data.repositories import ToolRepository
from src.execution.tool_executor import run_tool_code

logger = logging.getLogger(__name__)

# =============================================================================
# 常量
# =============================================================================

# 重复模式检测参数
SUGGESTION_THRESHOLD = 3
SUGGESTION_COOLDOWN = 5

# Module-level cached repos for _check_tool_suggestion (avoids 2 new instances per tool call)
_suggestion_repo = None
_suggestion_tool_repo = None


def _get_suggestion_repos():
    global _suggestion_repo, _suggestion_tool_repo
    if _suggestion_repo is None:
        from src.data.repositories import ToolSuggestionRepository, ToolRepository

        _suggestion_repo = ToolSuggestionRepository()
        _suggestion_tool_repo = ToolRepository()
    return _suggestion_repo, _suggestion_tool_repo


def _check_tool_suggestion(tool_name: str) -> Optional[str]:
    """
    检测重复模式：工具执行成功时更新计数，达到阈值时返回建议文本。
    纯代码逻辑，不走 LLM。
    """
    try:
        repo, tool_repo = _get_suggestion_repos()

        record = repo.get_by_pattern(tool_name)

        if record is None:
            repo.create(tool_name)
            return None

        repo.increment(record)

        tool = tool_repo.get_by_name(tool_name)
        if tool and tool.status == "published":
            return None

        if record.accepted is False:
            if record.times_seen < SUGGESTION_COOLDOWN:
                return None
            repo.reset_accepted(record)

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


SEARCH_TOOLS_SCHEMA = make_tool_schema(
    name="search_tools",
    description="浏览或搜索当前获授权的用户技能与技能组合，支持类型过滤和稳定分页。",
    properties={
        "query": {
            "type": "string",
            "description": "可选搜索关键词或意图描述；留空时浏览目录",
        },
        "kind": {
            "type": "string",
            "enum": ["all", "tool", "composition"],
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
    },
    required=[],
)

GET_TOOL_DETAIL_SCHEMA = make_tool_schema(
    name="get_tool_detail",
    description="获取指定用户技能或技能组合的完整说明，并激活其可调用定义。",
    properties={
        "tool_name": {
            "type": "string",
            "description": "技能名称，或使用“技能:名称”/“技能组合:名称”来消除歧义",
        },
    },
    required=["tool_name"],
)


class DynamicToolManager:
    """管理用户技能与技能组合的懒加载 FC 注入"""

    MAX_ACTIVATED = 10

    def __init__(
        self,
        allowed_tool_ids: Optional[Set[str]] = None,
        allowed_composition_ids: Optional[Set[str]] = None,
        revalidate_activated: bool = True,
    ):
        """
        Args:
            allowed_tool_ids: 允许使用的技能 ID 集合。None 表示全部已发布技能。
            allowed_composition_ids: 允许使用的技能组合 ID 集合。None 表示全部已发布组合。
        """
        self._activated_tools: OrderedDict[str, ToolDefinition] = OrderedDict()
        self._short_id_to_entity_id: dict[str, str] = {}
        self._entity_id_to_short_id: dict[str, str] = {}
        self._allowed_tool_ids = allowed_tool_ids
        self._allowed_composition_ids = allowed_composition_ids
        self._revalidate_activated = revalidate_activated
        self._search_lock = threading.Lock()
        self._tool_repo = ToolRepository()
        self._composition_service: Optional[SkillCompositionService] = None

    @property
    def composition_service(self) -> SkillCompositionService:
        if self._composition_service is None:
            self._composition_service = SkillCompositionService()
        return self._composition_service

    def _is_allowed_tool(self, tool) -> bool:
        if self._allowed_tool_ids is None:
            return tool.status == "published"
        return tool.tool_id in self._allowed_tool_ids and tool.status == "published"

    def _is_allowed_composition(self, composition) -> bool:
        if (
            composition.status != "published"
            or not composition.assistant_enabled
            or composition.needs_review
        ):
            return False
        if (
            self._allowed_composition_ids is not None
            and composition.composition_id not in self._allowed_composition_ids
        ):
            return False
        if self._allowed_tool_ids is None:
            return True
        member_tool_ids = {member.tool_id for member in composition.members}
        return member_tool_ids.issubset(self._allowed_tool_ids)

    def _make_short_id(self, entity_id: str, prefix: str) -> str:
        short = f"{prefix}_{entity_id[:8]}"
        if short in self._short_id_to_entity_id and self._short_id_to_entity_id[short] != entity_id:
            short = f"{prefix}_{entity_id[:12]}"
        if short in self._short_id_to_entity_id and self._short_id_to_entity_id[short] != entity_id:
            short = f"{prefix}_{entity_id}"
        return short

    def search_tools(
        self,
        query: str = "",
        kind: str = "all",
        offset: int = 0,
        limit: int | None = None,
    ) -> str:
        """浏览或搜索当前获授权的用户技能与技能组合。"""
        # The manager keeps Repository/Service sessions for its lifetime. Protect
        # those shared sessions while still allowing this call to overlap with
        # unrelated concurrency-safe tools in the AgentLoop.
        with self._search_lock:
            try:
                page = search_capability_catalog(
                    self._current_catalog_items(),
                    load_capability_discovery_policy(),
                    query=query,
                    kind=kind,
                    offset=offset,
                    limit=limit,
                )
            except ValueError as exc:
                return error_json(str(exc))
            return to_json(page.to_dict())

    def _current_catalog_items(self) -> list[CapabilityCatalogItem]:
        items = [
            CapabilityCatalogItem(
                kind="tool",
                name=tool.tool_name,
                description=tool.description or "",
            )
            for tool in self._tool_repo.get_all_published()
            if self._is_allowed_tool(tool)
        ]
        for composition in self.composition_service.get_assistant_published_summaries():
            member_tool_ids = set(composition["member_tool_ids"])
            if (
                self._allowed_composition_ids is not None
                and composition["composition_id"] not in self._allowed_composition_ids
            ):
                continue
            if self._allowed_tool_ids is not None and not member_tool_ids.issubset(
                self._allowed_tool_ids
            ):
                continue
            items.append(
                CapabilityCatalogItem(
                    kind="composition",
                    name=composition["composition_name"],
                    description=composition["description"] or "",
                    applicability=composition["applicability"] or "",
                )
            )
        return items

    def get_tool_detail(self, tool_name: str) -> str:
        """查看技能或技能组合详情，同时激活对应的 FC schema"""
        kind, normalized_name = self._parse_requested_name(tool_name)
        tool = self._tool_repo.get_by_name(normalized_name)
        composition = self.composition_service.get_composition_by_name(
            normalized_name,
            require_published=True,
        )

        if tool is not None and not self._is_allowed_tool(tool):
            tool = None
        if composition is not None and not self._is_allowed_composition(composition):
            composition = None

        if kind == "tool":
            if tool is None:
                return f"技能 '{normalized_name}' 不存在或当前不可用"
            return self._activate_tool_and_format_detail(tool)

        if kind == "composition":
            if composition is None:
                return f"技能组合 '{normalized_name}' 不存在或当前不可用"
            return self._activate_composition_and_format_detail(composition)

        if tool and composition:
            return (
                f"名称 '{normalized_name}' 同时匹配技能和技能组合。"
                "请改用“技能:名称”或“技能组合:名称”重新调用 get_tool_detail。"
            )
        if composition:
            return self._activate_composition_and_format_detail(composition)
        if tool:
            return self._activate_tool_and_format_detail(tool)
        return f"'{normalized_name}' 不存在或当前不可用"

    def get_activated_tools(self) -> List[ToolDefinition]:
        """获取已激活的用户能力列表，供 AgentLoop 在下一轮注入 FC schema"""
        if self._revalidate_activated:
            self._refresh_activated_definitions()
        return list(self._activated_tools.values())

    def _activate_tool_and_format_detail(self, tool) -> str:
        tool_def = self._build_tool_definition(tool)
        self._register_activated_definition(
            short_id=self._make_short_id(tool.tool_id, "utool"),
            entity_id=tool.tool_id,
            tool_def=tool_def,
        )
        return self._format_tool_detail(tool)

    def _activate_composition_and_format_detail(self, composition) -> str:
        self.activate_composition_snapshot(composition)
        return self._format_composition_detail(composition)

    def activate_composition_snapshot(self, composition, include_members: bool = False) -> None:
        """直接激活传入的组合快照，可选同时激活成员技能。"""
        tool_def = self._build_composition_definition(composition)
        self._register_activated_definition(
            short_id=self._make_short_id(composition.composition_id, "comp"),
            entity_id=composition.composition_id,
            tool_def=tool_def,
        )
        if include_members:
            self._activate_composition_members(composition)

    def _register_activated_definition(
        self,
        short_id: str,
        entity_id: str,
        tool_def: ToolDefinition,
        max_activated: Optional[int] = None,
    ) -> None:
        if short_id in self._activated_tools:
            self._activated_tools.move_to_end(short_id)
        self._activated_tools[short_id] = tool_def
        self._short_id_to_entity_id[short_id] = entity_id
        self._entity_id_to_short_id[entity_id] = short_id

        activation_limit = max_activated or self.MAX_ACTIVATED
        while len(self._activated_tools) > activation_limit:
            oldest, _ = self._activated_tools.popitem(last=False)
            old_entity_id = self._short_id_to_entity_id.pop(oldest, None)
            if old_entity_id:
                self._entity_id_to_short_id.pop(old_entity_id, None)

    def _build_tool_definition(self, tool) -> ToolDefinition:
        short_id = self._make_short_id(tool.tool_id, "utool")
        schema = self._build_tool_schema(tool, short_id)
        handler = self._create_tool_handler(tool)
        return ToolDefinition(name=short_id, schema=schema, handler=handler, has_side_effects=False)

    def _build_tool_schema(self, tool, short_id: str) -> dict:
        properties = {}
        required = []
        for param in tool.parameters or []:
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

    def _create_tool_handler(self, tool) -> Callable:
        if not tool or not tool.execution_code:

            def _unavailable_handler(**kwargs) -> str:
                return error_json("技能不可用")

            return _unavailable_handler

        cached_code = tool.execution_code
        cached_deps = tool.dependencies or []
        cached_name = tool.tool_name

        def handler(**kwargs) -> str:
            result = run_tool_code(cached_code, kwargs, cached_deps)
            if result.get("success"):
                suggestion = _check_tool_suggestion(cached_name)
                if suggestion:
                    result["_suggestion"] = suggestion
            return to_json(result)

        return handler

    def _build_composition_definition(self, composition) -> ToolDefinition:
        short_id = self._make_short_id(composition.composition_id, "comp")
        schema = make_tool_schema(
            name=short_id,
            description=(
                composition.description
                or composition.applicability
                or f"技能组合：{composition.composition_name}"
            ),
            properties={
                "task": {"type": "string", "description": "要完成的任务描述"},
                "context": {"type": "string", "description": "补充上下文（可选）"},
            },
            required=["task"],
        )
        handler = self._create_composition_handler(composition)
        return ToolDefinition(name=short_id, schema=schema, handler=handler, has_side_effects=False)

    def _create_composition_handler(self, composition) -> Callable:

        def handler(task: str, context: str = "") -> str:
            self._activate_composition_members(composition)

            return self._format_composition_call_result(
                composition,
                task=task,
                context=context or "",
            )

        return handler

    def _activate_composition_members(self, composition) -> None:
        ordered_members = self._get_ordered_members(composition)
        activatable_members = [
            member
            for member in ordered_members
            if member.tool
            and self._is_allowed_tool(member.tool)
            and member.tool.tool_id not in self._entity_id_to_short_id
        ]
        if not activatable_members:
            return
        member_activation_limit = max(
            self.MAX_ACTIVATED,
            len(activatable_members) + 1,
        )
        for member in activatable_members:
            tool_def = self._build_tool_definition(member.tool)
            self._register_activated_definition(
                short_id=self._make_short_id(member.tool.tool_id, "utool"),
                entity_id=member.tool.tool_id,
                tool_def=tool_def,
                max_activated=member_activation_limit,
            )

    @staticmethod
    def _parse_requested_name(name: str) -> Tuple[Optional[str], str]:
        raw = (name or "").strip()
        raw = raw.lstrip("-* ").strip().strip("*").strip()

        if raw.startswith("[") and "]" in raw:
            closing = raw.index("]")
            label = raw[1:closing].strip()
            normalized_name = DynamicToolManager._strip_display_description(
                raw[closing + 1 :].strip()
            )
            if label.startswith("技能组合"):
                return "composition", normalized_name
            if label == "技能":
                return "tool", normalized_name

        for prefix in ("技能组合:", "技能组合："):
            if raw.startswith(prefix):
                return "composition", raw.split(prefix, 1)[1].strip().strip("*")
        for prefix in ("组合:", "组合："):
            if raw.startswith(prefix):
                return "composition", raw.split(prefix, 1)[1].strip().strip("*")
        for prefix in ("技能:", "技能："):
            if raw.startswith(prefix):
                return "tool", raw.split(prefix, 1)[1].strip().strip("*")
        return None, raw

    @staticmethod
    def _strip_display_description(raw_name: str) -> str:
        candidate = (raw_name or "").replace("**", "").strip()
        for separator in ("：", ":"):
            if separator in candidate:
                candidate = candidate.split(separator, 1)[0].strip()
                break
        return candidate.strip().strip("*").strip()

    def _refresh_activated_definitions(self) -> None:
        stale_short_ids = []
        for short_id in list(self._activated_tools.keys()):
            entity_id = self._short_id_to_entity_id.get(short_id)
            if not entity_id:
                stale_short_ids.append(short_id)
                continue

            if short_id.startswith("comp_"):
                composition = self.composition_service.get_execution_snapshot(
                    entity_id,
                    require_published=True,
                    require_assistant_enabled=True,
                )
                if composition is None or not self._is_allowed_composition(composition):
                    stale_short_ids.append(short_id)
                    continue
                self._activated_tools[short_id] = self._build_composition_definition(composition)
                continue

            if short_id.startswith("utool_"):
                tool = self._tool_repo.get_by_id(entity_id)
                if tool is None or not self._is_allowed_tool(tool):
                    stale_short_ids.append(short_id)
                    continue
                self._activated_tools[short_id] = self._build_tool_definition(tool)

        for short_id in stale_short_ids:
            self._remove_activated_definition(short_id)

    def _remove_activated_definition(self, short_id: str) -> None:
        self._activated_tools.pop(short_id, None)
        entity_id = self._short_id_to_entity_id.pop(short_id, None)
        if entity_id:
            self._entity_id_to_short_id.pop(entity_id, None)

    @staticmethod
    def _get_ordered_members(composition):
        return sort_composition_members(composition.members, composition.mode)

    @staticmethod
    def _format_tool_detail(tool) -> str:
        lines = [f"技能名称：{tool.tool_name}"]
        if tool.description:
            lines.append(f"描述：{tool.description}")
        lines.append("参数列表：")
        for param in tool.parameters or []:
            req = "（必填）" if param.get("required") else "（选填）"
            lines.append(
                f"  - {param['name']}{req}：{param.get('description', '无描述')} "
                f"[类型: {param.get('type', 'string')}]"
            )
        if not tool.parameters:
            lines.append("  （无参数）")
        lines.append("\n技能已激活，你现在可以直接调用它了。")
        return "\n".join(lines)

    def _format_composition_detail(self, composition) -> str:
        mode_text = MODE_DISPLAY_TEXT.get(composition.mode, composition.mode)
        lines = [
            f"技能组合名称：{composition.composition_name}",
            f"类型：{mode_text}",
        ]
        if composition.description:
            lines.append(f"描述：{composition.description}")
        lines.append(f"适用场景：{composition.applicability}")
        lines.append("成员技能：")
        for member in self._get_ordered_members(composition):
            tool_name = member.tool.tool_name if member.tool else member.tool_id
            if composition.mode == "ordered":
                order_text = member.execution_order or member.selected_order
                lines.append(f"  - 第 {order_text} 步：{tool_name}")
            else:
                lines.append(f"  - {tool_name}")

        if composition.mode == "ordered":
            lines.extend(
                [
                    "",
                    "使用方式：先调用这个技能组合，再严格按推荐顺序依次调用激活后的成员技能。",
                    "如果某一步没有可消费输出，仍可尝试继续；无论成功与否，都要告知用户该组合设计可能不合适。",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "使用方式：先调用这个技能组合，再从激活后的成员技能中自主选择一个或多个去完成任务。",
                    "如成员技能不足以完成任务，可以把内置工具作为最低优先级兜底。",
                ]
            )

        lines.append("\n技能组合已激活，你现在可以直接调用它了。")
        return "\n".join(lines)

    def _format_composition_call_result(self, composition, task: str, context: str) -> str:
        lines = [
            f"技能组合“{composition.composition_name}”已启动。",
            f"任务：{task}",
        ]
        if context.strip():
            lines.append(f"上下文：{context.strip()}")

        ordered_members = self._get_ordered_members(composition)
        member_names = [
            member.tool.tool_name if member.tool else member.tool_id for member in ordered_members
        ]

        if composition.mode == "ordered":
            lines.extend(
                [
                    "执行规则：",
                    "- 按下面的顺序依次调用成员技能，并把上一步结果整理成下一步参数。",
                ]
            )
            for index, member_name in enumerate(member_names, start=1):
                lines.append(f"  {index}. {member_name}")
            lines.extend(
                [
                    "- 如果某一步没有可直接消费的输出，仍可基于已有上下文尝试继续完成任务。",
                    "- 如果最终能完成任务，也要明确告诉用户这个技能组合设计存在衔接问题。",
                    "- 如果无法继续，就明确说明是这个技能组合不合适，而不是静默失败。",
                ]
            )
        else:
            lines.extend(
                [
                    "执行规则：",
                    "- 从已激活的成员技能中自主选择最合适的一个或多个来完成任务。",
                    "- 这些成员技能只是优先范围，不是硬约束；如果不需要它们也可以不用。",
                    "- 如果成员技能不足以完成任务，可以把内置工具作为最低优先级兜底。",
                    f"- 当前可优先考虑的成员技能：{', '.join(member_names) if member_names else '无'}",
                ]
            )

        lines.append("继续执行，直到给用户明确结果。")
        return "\n".join(lines)


def create_assistant_search_tools(manager: "DynamicToolManager") -> List[ToolDefinition]:
    """创建 search_tools 和 get_tool_detail 工具定义（闭包绑定 manager 实例）"""
    return [
        ToolDefinition(
            name="search_tools",
            schema=SEARCH_TOOLS_SCHEMA,
            handler=lambda query="", kind="all", offset=0, limit=None: manager.search_tools(
                query=query,
                kind=kind,
                offset=offset,
                limit=limit,
            ),
            has_side_effects=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="get_tool_detail",
            schema=GET_TOOL_DETAIL_SCHEMA,
            handler=lambda tool_name: manager.get_tool_detail(tool_name),
            has_side_effects=False,
            # Not concurrency-safe: it mutates activation state (_register_activated_definition
            # activates the FC schema), unlike search_tools which self-guards via _search_lock.
            is_concurrency_safe=False,
        ),
    ]
