"""LLM-backed helpers for skill composition authoring flows."""

from typing import Callable, List

from src.business.debug.context import TraceContext
from src.data.models import MODE_DISPLAY_TEXT
from src.utils.llm_helpers import extract_json_from_response

from .composition_normalizer import normalize_members
from .trial_snapshot_codec import normalize_generated_text
from .types import SkillCompositionError


class CompositionLLMHelper:
    """Owns prompt building for authoring-time LLM features."""

    def __init__(self, *, tool_repo, llm_factory: Callable):
        self._tool_repo = tool_repo
        self._llm_factory = llm_factory

    def recommend_execution_order(
        self,
        composition_name: str,
        description: str,
        applicability: str,
        members: List[dict],
    ) -> dict:
        normalized_members = normalize_members("ordered", members, self._tool_repo)
        tool_ids = [member["tool_id"] for member in normalized_members]
        tools = {tool.tool_id: tool for tool in self._tool_repo.get_by_ids(tool_ids)}
        if len(tools) != len(tool_ids):
            raise SkillCompositionError("推荐顺序失败：存在无效技能")

        llm = self._llm_factory(temperature=0.2, max_tokens=800)

        tool_lines = []
        for index, member in enumerate(normalized_members, start=1):
            tool = tools[member["tool_id"]]
            tool_lines.append(
                f"{index}. tool_id={tool.tool_id}\n"
                f"   名称={tool.tool_name}\n"
                f"   描述={tool.description or '无'}\n"
                f"   当前顺序={member['selected_order']}"
            )

        prompt = (
            "你是技能组合编排助手。请根据组合名称、说明、适用场景和成员技能描述，"
            "为一个顺序型技能组合推荐执行顺序。\n\n"
            "要求：\n"
            "1. 只能返回给定的 tool_id，且每个 tool_id 只能出现一次。\n"
            "2. 返回严格 JSON，不要输出额外解释。\n"
            "3. JSON 格式必须为："
            '{"ordered_tool_ids":["..."],"reason":"..."}\n\n'
            f"组合名称：{composition_name.strip()}\n"
            f"组合说明：{(description or '').strip() or '无'}\n"
            f"适用场景：{applicability.strip()}\n\n"
            "成员技能：\n"
            f"{chr(10).join(tool_lines)}"
        )
        with TraceContext(
            source="skill_composition_recommend_order",
            agent_type="composition_authoring",
            work_unit_id=composition_name.strip(),
        ):
            response = llm.chat(prompt)
        parsed = extract_json_from_response(
            response,
            log_prefix="recommend_execution_order",
        )
        ordered_tool_ids = parsed.get("ordered_tool_ids")
        if not isinstance(ordered_tool_ids, list):
            raise SkillCompositionError("推荐顺序失败：模型返回格式不正确")

        if set(ordered_tool_ids) != set(tool_ids) or len(ordered_tool_ids) != len(tool_ids):
            raise SkillCompositionError("推荐顺序失败：模型返回的技能集合不完整")

        id_to_member = {member["tool_id"]: member for member in normalized_members}
        ordered_members = []
        for execution_order, tool_id in enumerate(ordered_tool_ids, start=1):
            item = dict(id_to_member[tool_id])
            item["execution_order"] = execution_order
            ordered_members.append(item)

        return {
            "members": ordered_members,
            "reason": str(parsed.get("reason") or "").strip(),
        }

    def generate_applicability(
        self,
        composition_name: str,
        description: str,
        mode: str,
        members: List[dict],
    ) -> str:
        normalized_members = normalize_members(mode, members, self._tool_repo)
        tool_ids = [member["tool_id"] for member in normalized_members]
        tools = {tool.tool_id: tool for tool in self._tool_repo.get_by_ids(tool_ids)}
        if len(tools) != len(tool_ids):
            raise SkillCompositionError("生成适用场景失败：存在无效技能")

        llm = self._llm_factory(temperature=0.4, max_tokens=280)

        mode_text = MODE_DISPLAY_TEXT.get(mode, mode)
        tool_lines = []
        for index, member in enumerate(normalized_members, start=1):
            tool = tools[member["tool_id"]]
            order_hint = (
                f"推荐步骤={member['execution_order']}"
                if mode == "ordered"
                else f"当前选择序={member['selected_order']}"
            )
            tool_lines.append(
                f"{index}. 名称={tool.tool_name}\n"
                f"   描述={tool.description or '无'}\n"
                f"   {order_hint}"
            )

        prompt = (
            "你是技能组合产品文案助手。请根据技能组合草稿，生成一段中文“适用场景”文本。\n\n"
            "要求：\n"
            "1. 只输出一段可直接填写到表单里的中文，不要标题、编号、引号或额外解释。\n"
            "2. 长度控制在 40 到 90 个汉字左右。\n"
            "3. 说明这个组合适合处理什么任务、在什么情况下使用。\n"
            "4. 只能基于给定技能推断能力，不要编造不存在的结果。\n\n"
            f"组合名称：{composition_name.strip() or '未命名技能组合'}\n"
            f"组合说明：{(description or '').strip() or '无'}\n"
            f"组合模式：{mode_text}\n\n"
            "成员技能：\n"
            f"{chr(10).join(tool_lines)}"
        )
        with TraceContext(
            source="skill_composition_applicability",
            agent_type="composition_authoring",
            work_unit_id=composition_name.strip(),
        ):
            response = llm.chat(prompt)
        generated = normalize_generated_text(response)
        if not generated:
            raise SkillCompositionError("生成适用场景失败：模型未返回有效内容")
        return generated
