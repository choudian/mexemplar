"""
SkillCompositionService — 技能组合业务服务
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import ASSISTANT_CONFIG, ResultType
from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS
from src.business.ai.llm_client import LangChainLLMClient
from src.data.models import (
    MODE_DISPLAY_TEXT,
    SkillComposition,
    SkillCompositionMember,
    Tool,
    serialize_tool,
    sort_composition_members,
)
from src.data.models_sqlite import Session
from src.utils.llm_helpers import extract_json_from_response
from src.data.repositories import (
    MessageRepository,
    SessionRepository,
    SkillCompositionRepository,
    ToolRepository,
)
from src.data.unified_config import get_unified_config

logger = logging.getLogger(__name__)


class SkillCompositionError(ValueError):
    """技能组合业务异常"""


@dataclass
class SkillCompositionTrialResult:
    """技能组合试用结果"""

    success: bool
    reply: str
    result_type: str
    error: Optional[str] = None
    session_id: Optional[str] = None


@dataclass
class SkillCompositionTrialSessionStart:
    """技能组合对话式试用会话初始化结果"""

    composition_id: str
    composition_name: str
    session_id: str


class SkillCompositionService:
    """技能组合管理与执行服务"""

    VALID_MODES = {"range", "ordered"}
    VALID_STATUSES = {"draft", "published", "offline"}
    DEFAULT_ASSISTANT_ENABLED = True
    DEFAULT_RECOMMEND_ORDER = False

    def __init__(
        self,
        composition_repo: Optional[SkillCompositionRepository] = None,
        tool_repo: Optional[ToolRepository] = None,
    ):
        self._composition_repo = composition_repo or SkillCompositionRepository()
        self._tool_repo = tool_repo or ToolRepository()
        self._session_repo = None
        self._message_repo = None

    def _create_llm(
        self,
        config=None,
        temperature: float = 0.4,
        max_tokens: int = 800,
    ) -> LangChainLLMClient:
        """创建 LLM 客户端，统一配置读取和 Key 校验"""
        if config is None:
            config = get_unified_config()
        api_key = config.get_ai_api_key()
        if not api_key:
            raise SkillCompositionError("未配置 AI Key")
        return LangChainLLMClient(
            provider=config.get_ai_provider(),
            model=config.get_ai_model(),
            api_key=api_key,
            base_url=config.get_ai_base_url(),
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @property
    def _session_repository(self):
        if self._session_repo is None:
            self._session_repo = SessionRepository()
        return self._session_repo

    @property
    def _message_repository(self):
        if self._message_repo is None:
            self._message_repo = MessageRepository()
        return self._message_repo

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_compositions(self) -> List[SkillComposition]:
        """读取全部技能组合"""
        compositions = self._composition_repo.get_all()
        members_by_comp = self._composition_repo.get_members_for_compositions(
            [composition.composition_id for composition in compositions]
        )
        return [
            self._to_composition_model(
                composition,
                members_by_comp.get(composition.composition_id, []),
            )
            for composition in compositions
        ]

    def get_published_tool_choices(self) -> List[Tool]:
        """获取可供组合选择的已发布技能"""
        return [self._to_tool_model(tool) for tool in self._tool_repo.get_all_published()]

    def get_composition(self, composition_id: str) -> Optional[SkillComposition]:
        """按 ID 读取技能组合"""
        composition = self._composition_repo.get_by_id(composition_id)
        if composition is None:
            return None
        members = self._composition_repo.get_members(composition_id)
        return self._to_composition_model(composition, members)

    def get_composition_by_name(
        self,
        name: str,
        require_published: bool = False,
    ) -> Optional[SkillComposition]:
        """按名称读取技能组合"""
        composition = self._composition_repo.get_by_name(name)
        if composition is None:
            return None
        if require_published and (
            composition.status != "published" or composition.needs_review
        ):
            return None
        members = self._composition_repo.get_members(composition.composition_id)
        return self._to_composition_model(composition, members)

    def search_published_compositions(self, query: str) -> List[SkillComposition]:
        """搜索已发布技能组合"""
        compositions = self._composition_repo.search_published(query)
        members_by_comp = self._composition_repo.get_members_for_compositions(
            [composition.composition_id for composition in compositions]
        )
        return [
            self._to_composition_model(
                composition,
                members_by_comp.get(composition.composition_id, []),
            )
            for composition in compositions
        ]

    def get_assistant_published_summaries(self) -> List[dict]:
        """获取供 Assistant 展示的已发布技能组合摘要"""
        compositions = self._composition_repo.get_published_assistant_enabled()
        members_by_comp = self._composition_repo.get_members_for_compositions(
            [composition.composition_id for composition in compositions]
        )
        summaries = []
        for composition in compositions:
            members = members_by_comp.get(composition.composition_id, [])
            summaries.append(
                {
                    "composition_id": composition.composition_id,
                    "composition_name": composition.composition_name,
                    "description": composition.description or "",
                    "applicability": composition.applicability,
                    "mode": composition.mode,
                    "member_tool_ids": [member.tool_id for member in members],
                }
            )
        return summaries

    def get_referencing_compositions(
        self,
        tool_id: str,
        statuses: Optional[Iterable[str]] = None,
    ) -> List[SkillComposition]:
        """查询引用技能的组合"""
        compositions = self._composition_repo.get_referencing_compositions(
            tool_id,
            statuses=statuses,
        )
        members_by_comp = self._composition_repo.get_members_for_compositions(
            [composition.composition_id for composition in compositions]
        )
        return [
            self._to_composition_model(
                composition,
                members_by_comp.get(composition.composition_id, []),
            )
            for composition in compositions
        ]

    # ------------------------------------------------------------------
    # 校验（供 UI 预检）
    # ------------------------------------------------------------------

    def validate_composition_payload(
        self,
        composition_id: str,
        composition_name: str,
        description: str,
        applicability: str,
        mode: str,
        status: str,
        members: List[dict],
    ) -> None:
        """校验技能组合数据，不执行写入。校验失败抛出 SkillCompositionError。"""
        self._normalize_members(mode, members)
        self._build_composition_orm(
            composition_id=composition_id,
            composition_name=composition_name,
            description=description,
            applicability=applicability,
            mode=mode,
            status=status,
            assistant_enabled=self.DEFAULT_ASSISTANT_ENABLED,
            recommend_order=self.DEFAULT_RECOMMEND_ORDER,
            needs_review=False,
        )

    # ------------------------------------------------------------------
    # 创建 / 编辑 / 状态流转
    # ------------------------------------------------------------------

    def create_composition(
        self,
        composition_name: str,
        description: str,
        applicability: str,
        mode: str,
        members: List[dict],
        assistant_enabled: bool = True,
        recommend_order: bool = False,
    ) -> SkillComposition:
        """创建草稿技能组合"""
        normalized_members = self._normalize_members(mode, members)
        orm_model = self._build_composition_orm(
            composition_id=f"comp_{uuid.uuid4().hex[:12]}",
            composition_name=composition_name,
            description=description,
            applicability=applicability,
            mode=mode,
            status="draft",
            assistant_enabled=assistant_enabled,
            recommend_order=recommend_order,
            needs_review=False,
        )
        member_models = self._build_member_orms(orm_model.composition_id, normalized_members)
        self._composition_repo.create(orm_model, member_models)
        return self.get_composition(orm_model.composition_id)

    def update_composition(
        self,
        composition_id: str,
        composition_name: str,
        description: str,
        applicability: str,
        mode: str,
        members: List[dict],
        assistant_enabled: bool = True,
        recommend_order: bool = False,
    ) -> SkillComposition:
        """编辑技能组合，发布态直接修改线上版本"""
        composition = self._composition_repo.get_by_id(composition_id)
        if composition is None:
            raise SkillCompositionError("技能组合不存在")

        normalized_members = self._normalize_members(mode, members)
        normalized_name = composition_name.strip()
        if not normalized_name:
            raise SkillCompositionError("名称不能为空")
        normalized_applicability = applicability.strip()
        if not normalized_applicability:
            raise SkillCompositionError("适用场景不能为空")
        self._ensure_unique_name(normalized_name, composition_id=composition_id)
        composition.composition_name = normalized_name
        composition.description = (description or "").strip() or None
        composition.applicability = normalized_applicability
        composition.mode = mode
        composition.assistant_enabled = assistant_enabled
        composition.recommend_order = recommend_order
        composition.needs_review = False
        self._composition_repo.update(composition)
        self._composition_repo.replace_members(
            composition_id,
            self._build_member_orms(composition_id, normalized_members),
        )
        return self.get_composition(composition_id)

    def publish_composition(self, composition_id: str) -> SkillComposition:
        """发布或重新发布技能组合"""
        composition = self._composition_repo.get_by_id(composition_id)
        if composition is None:
            raise SkillCompositionError("技能组合不存在")
        members = self._composition_repo.get_members(composition_id)
        self._normalize_members(composition.mode, [self._member_to_payload(member) for member in members])
        self._composition_repo.update_status(composition_id, "published")
        self._composition_repo.clear_needs_review(composition_id)
        return self.get_composition(composition_id)

    def offline_composition(self, composition_id: str) -> SkillComposition:
        """下线已发布技能组合"""
        composition = self._composition_repo.get_by_id(composition_id)
        if composition is None:
            raise SkillCompositionError("技能组合不存在")
        if composition.status != "published":
            raise SkillCompositionError("只有已发布的技能组合才能下线")
        self._composition_repo.update_status(composition_id, "offline")
        return self.get_composition(composition_id)

    def delete_composition(self, composition_id: str) -> None:
        """删除技能组合"""
        composition = self._composition_repo.get_by_id(composition_id)
        if composition is None:
            return
        if composition.status == "published":
            raise SkillCompositionError("已发布的技能组合请先下线再删除")
        self._composition_repo.delete(composition_id)

    def mark_needs_review_by_tool(self, tool_id: str) -> List[SkillComposition]:
        """成员技能变更后标记待复核"""
        compositions = self._composition_repo.mark_needs_review_by_tool(tool_id)
        members_by_comp = self._composition_repo.get_members_for_compositions(
            [composition.composition_id for composition in compositions]
        )
        return [
            self._to_composition_model(
                composition,
                members_by_comp.get(composition.composition_id, []),
            )
            for composition in compositions
        ]

    # ------------------------------------------------------------------
    # 顺序推荐
    # ------------------------------------------------------------------

    def recommend_execution_order(
        self,
        composition_name: str,
        description: str,
        applicability: str,
        members: List[dict],
    ) -> dict:
        """用模型为顺序型技能组合推荐执行顺序"""
        normalized_members = self._normalize_members("ordered", members)
        tool_ids = [member["tool_id"] for member in normalized_members]
        tools = {tool.tool_id: tool for tool in self._tool_repo.get_by_ids(tool_ids)}
        if len(tools) != len(tool_ids):
            raise SkillCompositionError("推荐顺序失败：存在无效技能")

        llm = self._create_llm(temperature=0.2, max_tokens=800)

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
        response = llm.chat(prompt)
        parsed = extract_json_from_response(response, log_prefix="recommend_execution_order")
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
        """根据当前技能组合草稿生成适用场景文案"""
        normalized_members = self._normalize_members(mode, members)
        tool_ids = [member["tool_id"] for member in normalized_members]
        tools = {tool.tool_id: tool for tool in self._tool_repo.get_by_ids(tool_ids)}
        if len(tools) != len(tool_ids):
            raise SkillCompositionError("生成适用场景失败：存在无效技能")

        llm = self._create_llm(temperature=0.4, max_tokens=280)

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
        response = llm.chat(prompt)
        generated = self._normalize_generated_text(response)
        if not generated:
            raise SkillCompositionError("生成适用场景失败：模型未返回有效内容")
        return generated

    # ------------------------------------------------------------------
    # 试一下
    # ------------------------------------------------------------------

    def run_trial(
        self,
        composition_id: str,
        task: str,
        context: str = "",
    ) -> SkillCompositionTrialResult:
        """真实执行一次技能组合试用"""
        composition = self.get_execution_snapshot(
            composition_id,
            require_published=False,
            require_assistant_enabled=False,
        )
        if composition is None:
            raise SkillCompositionError("技能组合不存在")
        if not task.strip():
            raise SkillCompositionError("试用任务不能为空")

        user_input = self._build_trial_user_input(
            composition=composition,
            task=task,
            context=context,
        )
        return self._run_trial_session(
            composition=composition,
            user_input=user_input,
            include_member_tools=False,
        )

    def start_trial_session(self, composition_id: str) -> SkillCompositionTrialSessionStart:
        """初始化一场新的技能组合对话式试用。"""
        composition = self.get_execution_snapshot(
            composition_id,
            require_published=False,
            require_assistant_enabled=False,
        )
        if composition is None:
            raise SkillCompositionError("技能组合不存在")

        session_id = self._create_trial_session(composition)
        return SkillCompositionTrialSessionStart(
            composition_id=composition.composition_id,
            composition_name=composition.composition_name,
            session_id=session_id,
        )

    @staticmethod
    def build_trial_bootstrap_input() -> Dict[str, str]:
        """构造会话首轮启动指令，让 Agent 主动发起自然对话。"""
        return {
            "role": "program",
            "content": (
                "现在开始这次技能组合试用对话。"
                "请你主动向用户发起第一轮沟通，不要把这条消息当成用户需求。"
                "不要复述系统规则，不要先讲长篇说明，也不要模板化寒暄。"
                "请直接根据当前技能组合情况，用自然口吻问出第一句最关键的问题。"
            ),
        }

    def continue_trial(
        self,
        composition_id: str,
        session_id: str,
        user_input: Any,
    ) -> SkillCompositionTrialResult:
        """继续一次已暂停的技能组合试用会话。"""
        if not session_id.strip():
            raise SkillCompositionError("试用会话不存在")
        normalized_input = self._normalize_trial_dialog_input(user_input)

        existing_session = self._session_repository.get_by_id(session_id)
        if existing_session is None or existing_session.agent_type != "composition_trial":
            raise SkillCompositionError("试用会话不存在")
        if existing_session.workflow_id != composition_id:
            raise SkillCompositionError("试用会话不属于当前技能组合")
        composition = self._get_trial_session_composition(existing_session)
        if composition is None:
            raise SkillCompositionError("技能组合不存在")

        return self._run_trial_session(
            composition=composition,
            user_input=normalized_input,
            session_id=session_id,
            include_member_tools=self._session_has_started_composition(
                session_id,
                composition.composition_id,
            ),
        )

    # ------------------------------------------------------------------
    # Assistant / 执行快照
    # ------------------------------------------------------------------

    def get_execution_snapshot(
        self,
        composition_id: str,
        require_published: bool = True,
        require_assistant_enabled: bool = True,
    ) -> Optional[SkillComposition]:
        """读取供执行使用的冻结快照"""
        composition = self._composition_repo.get_by_id(composition_id)
        if composition is None:
            return None
        if require_published and (
            composition.status != "published" or composition.needs_review
        ):
            return None
        if require_assistant_enabled and not composition.assistant_enabled:
            return None
        members = self._composition_repo.get_members(composition_id)
        return self._to_composition_model(composition, members)

    def _run_trial_session(
        self,
        composition: SkillComposition,
        user_input: Any,
        session_id: Optional[str] = None,
        include_member_tools: bool = False,
    ) -> SkillCompositionTrialResult:
        config = get_unified_config()
        llm = self._create_llm(config=config, temperature=0.4, max_tokens=1200)
        loop = AgentLoop(ASSISTANT_CONFIG, llm, config)

        manager = self._build_trial_manager(
            composition,
            include_member_tools=include_member_tools,
        )

        def tool_factory():
            return BUILTIN_GENERAL_TOOLS + manager.get_activated_tools()

        if session_id is None:
            session_id = self._create_trial_session(composition)

        result = loop.run(
            session_id=session_id,
            user_input=user_input,
            tools=tool_factory,
            system_prompt_override=self._build_trial_system_prompt(composition),
        )
        return self._to_trial_result(result, session_id)

    # ------------------------------------------------------------------
    # 内部帮助
    # ------------------------------------------------------------------

    def _build_trial_manager(
        self,
        composition: SkillComposition,
        include_member_tools: bool = False,
    ):
        from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager

        manager = DynamicToolManager(
            allowed_tool_ids={member.tool_id for member in composition.members},
            allowed_composition_ids={composition.composition_id},
            revalidate_activated=False,
        )
        manager.activate_composition_snapshot(
            composition,
            include_members=include_member_tools,
        )
        return manager

    def _create_trial_session(self, composition: SkillComposition) -> str:
        session_id = f"comptrial_{uuid.uuid4().hex[:12]}"
        self._session_repository.create(
            Session(
                session_id=session_id,
                workflow_id=composition.composition_id,
                agent_type="composition_trial",
                status="active",
                tool_ids=json.dumps(
                    self._build_trial_session_snapshot_payload(composition),
                    ensure_ascii=False,
                ),
            )
        )
        return session_id

    @staticmethod
    def _get_first_member_tool(composition: SkillComposition) -> Optional[Tool]:
        if not composition.members:
            return None
        ordered_members = sort_composition_members(
            composition.members, composition.mode
        )
        return ordered_members[0].tool

    @classmethod
    def _build_trial_user_input(
        cls,
        composition: SkillComposition,
        task: str,
        context: str = "",
    ) -> str:
        return "\n".join(
            [
                f"请试用技能组合“{composition.composition_name}”来完成下面的任务。",
                f"任务：{task.strip()}",
                f"上下文：{(context or '').strip() or '无'}",
            ]
        )

    @staticmethod
    def _normalize_trial_dialog_input(user_input: Any) -> Any:
        if isinstance(user_input, dict):
            role = str(user_input.get("role") or "").strip()
            content = str(user_input.get("content") or "").strip()
            if not role or not content:
                raise SkillCompositionError("补充信息不能为空")
            normalized_input = dict(user_input)
            normalized_input["role"] = role
            normalized_input["content"] = content
            return normalized_input

        text = str(user_input or "").strip()
        if not text:
            raise SkillCompositionError("补充信息不能为空")
        return text

    @staticmethod
    def _format_trial_parameter_lines(parameters: List[Dict[str, Any]]) -> List[str]:
        if not parameters:
            return ["- 第 1 步无需额外输入，可以直接开始。"]

        lines = []
        for param in parameters:
            description = str(param.get("description") or param.get("name") or "未命名输入").strip()
            internal_name = str(param.get("name") or description).strip()
            required = bool(param.get("required"))
            default = param.get("default")

            if required:
                attr = "必填"
            elif default is not None:
                attr = f"选填，默认 {default}"
            else:
                attr = "选填"

            lines.append(f"- {description}（内部名：{internal_name}，{attr}）")
        return lines

    @classmethod
    def _build_ordered_trial_guidance_lines(cls, composition: SkillComposition) -> List[str]:
        first_tool = cls._get_first_member_tool(composition)
        lines = [
            "## 顺序型组合引导要求",
            "- 顺序型组合的完整目标有四件事：先拿到用户整体想完成的任务，再拿到第 1 步启动所需信息，再按顺序完成整件事，最后把最终结果反馈给用户。",
            "- 先判断这个技能组合按当前配置是否真的适合完成用户的任务，再决定怎么往下推进。",
            "- 如果用户还没有明确说这次想通过这个技能组合完成什么任务，就先和用户沟通把整体目标问清楚。",
            "- 在真正启动技能组合前，除了整体目标，还要结合第 1 步技能的信息，判断启动第一步还缺哪些信息。",
            "- 还要判断当前顺序是否合理；如果为了完成任务，你判断更合适的路径更像是 1-3-2 而不是当前配置的 1-2-3，要明确告诉用户现在这个顺序可能不太对。",
            "- 如果顺序不理想但并不妨碍完成任务，要先征求用户意见；用户接受就继续，以完成任务为第一优先。",
            "- 跟用户沟通时不要说“参数”“字段”“变量”“内部名”这类技术词，要把问题翻译成自然语言。",
            "- 缺信息时优先一次问齐整体目标和第 1 步关键缺口，不要拆成机械式逐项盘问。",
            "- 如果用户一句话里已经把整体目标和第 1 步所需信息说全了，就直接启动，不要重复确认。",
            "- 技能组合启动后不要只停在第 1 步，要继续推进直到用户的整体任务完成，或者明确说明卡点。",
        ]

        if first_tool is None:
            lines.append("- 当前无法识别第 1 步技能，请先问清整体目标，再按既定顺序尝试启动组合。")
            return lines

        lines.extend(
            [
                f"- 第 1 步技能：{first_tool.tool_name}",
                f"- 第 1 步说明：{first_tool.description or '无'}",
                "- 第 1 步可参考的输入说明：",
                *cls._format_trial_parameter_lines(first_tool.parameters or []),
            ]
        )
        return lines

    @classmethod
    def _build_trial_system_prompt(cls, composition: SkillComposition) -> str:
        mode_text = MODE_DISPLAY_TEXT.get(composition.mode, composition.mode)
        ordered_members = sort_composition_members(
            composition.members, composition.mode
        )
        member_names = [
            member.tool.tool_name if member.tool else member.tool_id for member in ordered_members
        ]

        lines = [
            "你是 Exemplar 的试用助手。你正在帮助用户试用一个刚组装好的技能组合。",
            "",
            "⚠️ 重要说明：这个技能组合还处于验证阶段。",
            "组合衔接不顺、成员技能不匹配、结果不对、需要补信息，都是正常现象。",
            "试用的目标是尽快发现问题、验证价值，而不是硬撑着把流程跑完。",
            "",
            "## 本次试用的技能组合",
            f"**组合名称**：{composition.composition_name}",
            f"**组合类型**：{mode_text}",
            f"**组合说明**：{composition.description or composition.applicability}",
            f"**成员技能**：{', '.join(member_names) if member_names else '无'}",
            "",
            "## 你的任务",
            "1. 先获取用户这次想通过这个技能组合完成什么任务；如果目标还不明确，就先和用户沟通把目标问清楚",
            "2. 先判断这个技能组合能不能完成当前任务；如果明显不合适，要直接告诉用户，不要硬跑",
            "3. 信息不够时，用自然的话一次问清关键缺口，而不是让用户像填表一样逐项回答",
            "4. 信息够了就先调用这个技能组合本身，启动试用",
            "5. 组合启动后，根据返回情况继续执行成员技能、继续追问，直到完成用户的整体任务，或者明确指出组合设计不合适",
            "6. 把任务最终结果用用户能看懂的方式反馈给用户，再询问是否符合预期",
            "",
            "## 你的内部推进节奏",
            "你通过“获取目标 → 判断缺口 → 行动 → 观察 → 调整下一步”的循环来推进，但不要把这些内部步骤直接念给用户听。",
            "1. 获取目标：先判断用户有没有明确说出这次想完成什么任务、最后想拿到什么结果；如果没有，就先问目标。",
            "2. 判断可行性与缺口：基于整体目标，先判断这个技能组合能不能完成任务，再判断现在还缺什么信息；顺序型尤其要确认第 1 步启动所需的信息是否足够、当前顺序是否合理。",
            "3. 行动：选择当前最合适的动作，可能是继续向用户确认、提示组合或顺序问题、调用技能组合、调用成员技能，或者整理结果反馈。",
            "4. 观察：看清这一步返回了什么，任务是推进了、卡住了，还是已经完成了。",
            "5. 调整下一步：根据观察结果更新计划，直到完成用户整体任务，或者明确说明为什么暂时做不到。",
            "",
            "## 当前可用能力",
            "- 当前会话只有内置通用工具，以及这个已经预先激活的技能组合本身。",
            "- 你必须先直接调用这个技能组合本身，不要跳过它直接调用成员技能。",
            "- 成员技能只会在技能组合启动后才会出现。",
            "",
            "## 引导策略",
            "- 用户现在正在和你自然对话，不是在填写表单。",
            "- 如果这是会话开场，请优先围绕“这次到底想完成什么任务”发起第一句提问，不要先做大段说明。",
            "- 开场不要模板化寒暄，不要把规则逐条念给用户听。",
            "- 除非用户明显困惑，否则不要反复强调这是验证阶段，把提醒自然揉进对话里即可。",
            "- 用非技术语言说话，不要把“参数”“参数名”“字段名”“内部名”这类技术词直接抛给用户。",
            "- 如果你判断这个组合本身不适合当前任务，或者当前顺序不太对，要直接用用户能听懂的话说明问题。",
            "- 如果顺序不理想但仍能完成任务，要先问用户是否接受按当前组合继续尝试；用户接受就继续，不要为了顺序完美而放弃完成任务。",
            "- 缺信息时一次问齐关键内容，不要机械地一个一个盘问。",
            "- 如果用户一句话里已经把关键信息说全了，就直接开始，不要重复确认。",
            "- 如果执行报错，先判断是信息不足、临时问题，还是这个组合设计本身不合适。",
            "- 不要虚构不存在的工具或隐藏能力。",
            "",
            "## 结果处理",
            "- 任务完成后，要把最终结果解释成用户能直接判断的样子，不要只甩原始输出。",
            "- 如果是列表结果，优先提炼前几项关键信息和整体概况。",
            "- 如果组合中途卡住，要明确卡在哪一步、缺什么，或者为什么这个组合设计不合适。",
            "- 不要在只完成了中间步骤时就草草结束，要尽量把用户的整体任务推进到最终可交付的结果。",
            "",
            "## 反馈收集",
            "- 用户说“还行”“不对”“不太好用”时，不要停在模糊反馈，要追问到能定位问题的程度。",
            "- 试用结束时必须给出清晰结论：是否完成、卡在什么地方、这个组合是否适合继续保留。",
        ]

        if composition.mode == "ordered":
            lines.extend(["", *cls._build_ordered_trial_guidance_lines(composition)])
        else:
            lines.extend(
                [
                    "",
                    "## 范围型组合引导要求",
                    "- 开场优先获取整体目标，比如先问用户这次想让我帮他完成什么。",
                    "- 先问清用户这次想完成什么任务、想拿到什么结果。",
                    "- 如果用户目标已经足够明确，就直接启动组合，不要为了形式化补问无意义信息。",
                ]
            )
        return "\n".join(lines)

    def _session_has_started_composition(
        self,
        session_id: str,
        composition_id: str,
    ) -> bool:
        # DynamicToolManager._make_short_id(entity_id, prefix="comp_")
        # produces "comp_{entity_id[:8]}" with collision fallback to 12 chars.
        # composition_id itself is "comp_{hex[:12]}", so the short_id
        # becomes "comp_comp_{hex[:8]}" or "comp_comp_{hex[:12]}".
        entity_id = composition_id
        candidates = {f"comp_{entity_id[:8]}", f"comp_{entity_id[:12]}"}
        messages = self._message_repository.get_context(session_id)
        return any(
            message.tool_name in candidates
            for message in messages
        )

    def _ensure_unique_name(
        self,
        composition_name: str,
        composition_id: Optional[str] = None,
    ) -> None:
        if self._composition_repo.has_name_conflict(
            composition_name,
            exclude_composition_id=composition_id,
        ):
            raise SkillCompositionError("技能组合名称已存在")

    def _to_trial_result(
        self,
        result,
        session_id: str,
    ) -> SkillCompositionTrialResult:
        if result.result_type == ResultType.NEEDS_USER_INPUT:
            return SkillCompositionTrialResult(
                success=False,
                reply=result.question or "",
                result_type=result.result_type.value,
                session_id=session_id,
            )
        if result.result_type == ResultType.COMPLETED:
            reply = self._get_last_assistant_reply(session_id)
            return SkillCompositionTrialResult(
                success=True,
                reply=reply,
                result_type=result.result_type.value,
                session_id=session_id,
            )

        error = result.error or "技能组合试用失败"
        reply = self._get_last_assistant_reply(session_id)
        return SkillCompositionTrialResult(
            success=False,
            reply=reply,
            result_type=result.result_type.value,
            error=error,
            session_id=session_id,
        )

    def _normalize_members(self, mode: str, members: List[dict]) -> List[dict]:
        mode = (mode or "").strip()
        if mode not in self.VALID_MODES:
            raise SkillCompositionError("技能组合模式无效")
        if not members:
            raise SkillCompositionError("技能组合至少要包含一个技能")

        normalized = []
        seen_tool_ids = set()
        for index, member in enumerate(members, start=1):
            tool_id = str(member.get("tool_id") or "").strip()
            if not tool_id:
                raise SkillCompositionError("技能组合成员缺少技能 ID")
            if tool_id in seen_tool_ids:
                raise SkillCompositionError("同一个技能在同一组合中只能出现一次")
            seen_tool_ids.add(tool_id)
            normalized.append(
                {
                    "tool_id": tool_id,
                    "selected_order": int(member.get("selected_order") or index),
                    "execution_order": (
                        int(member.get("execution_order") or index)
                        if mode == "ordered"
                        else None
                    ),
                }
            )

        tool_map = {tool.tool_id: tool for tool in self._tool_repo.get_by_ids(list(seen_tool_ids))}
        missing = [tool_id for tool_id in seen_tool_ids if tool_id not in tool_map]
        if missing:
            raise SkillCompositionError(f"技能不存在：{', '.join(missing)}")

        unpublished = [
            tool.tool_name for tool in tool_map.values() if tool.status != "published"
        ]
        if unpublished:
            raise SkillCompositionError("只能将已掌握技能加入技能组合")

        if mode == "ordered":
            execution_orders = [member["execution_order"] for member in normalized]
            if sorted(execution_orders) != list(range(1, len(normalized) + 1)):
                raise SkillCompositionError("顺序型技能组合的执行顺序必须连续且唯一")

        return sorted(normalized, key=lambda item: item["selected_order"])

    def _build_composition_orm(
        self,
        composition_id: str,
        composition_name: str,
        description: str,
        applicability: str,
        mode: str,
        status: str,
        assistant_enabled: bool,
        recommend_order: bool,
        needs_review: bool,
    ):
        composition_name = (composition_name or "").strip()
        applicability = (applicability or "").strip()
        if not composition_name:
            raise SkillCompositionError("技能组合名称不能为空")
        if not applicability:
            raise SkillCompositionError("适用场景不能为空")
        if mode not in self.VALID_MODES:
            raise SkillCompositionError("技能组合模式无效")
        if status not in self.VALID_STATUSES:
            raise SkillCompositionError("技能组合状态无效")
        self._ensure_unique_name(composition_name, composition_id=composition_id)

        from src.data.models_sqlite import SkillComposition as SkillCompositionORM

        return SkillCompositionORM(
            composition_id=composition_id,
            composition_name=composition_name,
            description=(description or "").strip() or None,
            applicability=applicability,
            mode=mode,
            status=status,
            assistant_enabled=assistant_enabled,
            recommend_order=recommend_order,
            needs_review=needs_review,
        )

    def _build_member_orms(self, composition_id: str, members: List[dict]):
        from src.data.models_sqlite import SkillCompositionMember as SkillCompositionMemberORM

        return [
            SkillCompositionMemberORM(
                member_id=f"cm_{uuid.uuid4().hex[:12]}",
                composition_id=composition_id,
                tool_id=member["tool_id"],
                selected_order=member["selected_order"],
                execution_order=member["execution_order"],
            )
            for member in members
        ]

    def _to_composition_model(self, composition, members_orm) -> SkillComposition:
        tool_ids = [member.tool_id for member in members_orm]
        tool_map = {
            tool.tool_id: self._to_tool_model(tool)
            for tool in self._tool_repo.get_by_ids(tool_ids)
        }
        member_models = [
            SkillCompositionMember(
                member_id=member.member_id,
                composition_id=member.composition_id,
                tool_id=member.tool_id,
                selected_order=member.selected_order or 0,
                execution_order=member.execution_order,
                tool=tool_map.get(member.tool_id),
                created_at=member.created_at,
            )
            for member in members_orm
        ]
        member_models = sort_composition_members(member_models, composition.mode)

        return SkillComposition(
            composition_id=composition.composition_id,
            composition_name=composition.composition_name,
            description=composition.description,
            applicability=composition.applicability,
            mode=composition.mode,
            status=composition.status,
            assistant_enabled=bool(composition.assistant_enabled),
            recommend_order=bool(composition.recommend_order),
            needs_review=bool(composition.needs_review),
            members=member_models,
            created_at=composition.created_at,
            updated_at=composition.updated_at,
        )

    @staticmethod
    def _to_tool_model(tool) -> Tool:
        return Tool(
            tool_id=tool.tool_id,
            tool_name=tool.tool_name,
            description=tool.description,
            parameters=tool.parameters or [],
            steps=tool.steps or [],
            execution_code=tool.execution_code,
            code_language=tool.code_language,
            code_version=tool.code_version,
            execution_strategy=tool.execution_strategy,
            dependencies=tool.dependencies or [],
            source_intent_id=tool.source_intent_id,
            source=tool.source,
            trial_count=tool.trial_count,
            pending_tool_id=tool.pending_tool_id,
            workflow_id=tool.workflow_id,
            trial_success_count=tool.trial_success_count,
            status=tool.status,
            created_at=tool.created_at,
            updated_at=tool.updated_at,
        )

    @staticmethod
    def _member_to_payload(member) -> dict:
        return {
            "tool_id": member.tool_id,
            "selected_order": member.selected_order,
            "execution_order": member.execution_order,
        }

    def _get_last_assistant_reply(self, session_id: str) -> str:
        messages = self._message_repository.get_context(session_id)
        for message in reversed(messages):
            if message.role == "assistant" and message.content:
                return message.content
        return ""

    @staticmethod
    def _normalize_generated_text(content: str) -> str:
        cleaned = " ".join(
            line.strip() for line in (content or "").splitlines() if line.strip()
        )
        cleaned = re.sub(r"^适用场景[:：]\s*", "", cleaned)
        return cleaned.strip().strip("\"'“”")

    @staticmethod
    def _coerce_snapshot_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _deserialize_trial_session_tool(cls, payload: Any) -> Optional[Tool]:
        if not isinstance(payload, dict):
            return None
        tool_id = str(payload.get("tool_id") or "").strip()
        if not tool_id:
            return None
        return Tool(
            tool_id=tool_id,
            tool_name=str(payload.get("tool_name") or ""),
            description=payload.get("description"),
            parameters=list(payload.get("parameters") or []),
            steps=list(payload.get("steps") or []),
            execution_code=payload.get("execution_code"),
            code_language=str(payload.get("code_language") or "python"),
            code_version=str(payload.get("code_version") or "1.0"),
            execution_strategy=payload.get("execution_strategy"),
            dependencies=list(payload.get("dependencies") or []),
            source_intent_id=payload.get("source_intent_id"),
            source=str(payload.get("source") or "manual"),
            trial_count=cls._coerce_snapshot_int(payload.get("trial_count"), 0),
            pending_tool_id=payload.get("pending_tool_id"),
            workflow_id=payload.get("workflow_id"),
            trial_success_count=cls._coerce_snapshot_int(payload.get("trial_success_count"), 0),
            status=str(payload.get("status") or "pending"),
        )

    @classmethod
    def _normalize_trial_session_member_snapshot(
        cls,
        payload: Any,
        default_selected_order: int,
    ) -> Optional[dict]:
        if not isinstance(payload, dict):
            return None
        raw_tool = payload.get("tool")
        tool_payload = raw_tool if isinstance(raw_tool, dict) else None
        tool_id = str(
            payload.get("tool_id")
            or ((tool_payload or {}).get("tool_id") if tool_payload else "")
            or ""
        ).strip()
        if not tool_id:
            return None
        execution_order = payload.get("execution_order")
        normalized = dict(payload)
        normalized["tool_id"] = tool_id
        normalized["selected_order"] = cls._coerce_snapshot_int(
            payload.get("selected_order"),
            default_selected_order,
        )
        normalized["execution_order"] = (
            cls._coerce_snapshot_int(execution_order, default_selected_order)
            if execution_order not in (None, "")
            else None
        )
        normalized["tool"] = tool_payload
        return normalized

    @staticmethod
    def _build_trial_session_snapshot_payload(composition: SkillComposition) -> dict:
        return {
            "composition_id": composition.composition_id,
            "composition_name": composition.composition_name,
            "description": composition.description,
            "applicability": composition.applicability,
            "mode": composition.mode,
            "status": composition.status,
            "assistant_enabled": bool(composition.assistant_enabled),
            "recommend_order": bool(composition.recommend_order),
            "needs_review": bool(composition.needs_review),
            "member_tool_ids": [member.tool_id for member in composition.members],
            "members": [
                {
                    "member_id": member.member_id,
                    "tool_id": member.tool_id,
                    "selected_order": member.selected_order,
                    "execution_order": member.execution_order,
                    "tool": serialize_tool(member.tool),
                }
                for member in composition.members
            ],
        }

    @classmethod
    def _parse_trial_session_snapshot(cls, raw_tool_ids: Optional[str]) -> dict:
        if not raw_tool_ids:
            return {}
        try:
            parsed = json.loads(raw_tool_ids)
        except (TypeError, ValueError):
            return {}

        if isinstance(parsed, list):
            return {"member_tool_ids": [str(tool_id).strip() for tool_id in parsed if str(tool_id).strip()]}

        if isinstance(parsed, dict):
            normalized_members = []
            raw_members = parsed.get("members") or []
            if isinstance(raw_members, list):
                for index, payload in enumerate(raw_members, start=1):
                    normalized_member = cls._normalize_trial_session_member_snapshot(payload, index)
                    if normalized_member is not None:
                        normalized_members.append(normalized_member)
            member_tool_ids = parsed.get("member_tool_ids") or parsed.get("tool_ids") or []
            snapshot = dict(parsed)
            if normalized_members:
                snapshot["members"] = normalized_members
                if not member_tool_ids:
                    member_tool_ids = [member["tool_id"] for member in normalized_members]
            snapshot["member_tool_ids"] = [
                str(tool_id).strip() for tool_id in member_tool_ids if str(tool_id).strip()
            ]
            return snapshot

        return {}

    def _get_trial_session_composition(self, session: Session) -> Optional[SkillComposition]:
        live_composition = self.get_composition(session.workflow_id) if session.workflow_id else None
        snapshot = self._parse_trial_session_snapshot(session.tool_ids)
        snapshot_members = snapshot.get("members") or []
        member_tool_ids = snapshot.get("member_tool_ids") or (
            [member.tool_id for member in live_composition.members] if live_composition else []
        )
        if not member_tool_ids and live_composition is None:
            return None

        mode = str(snapshot.get("mode") or (live_composition.mode if live_composition else "range")).strip()
        if mode not in self.VALID_MODES:
            mode = live_composition.mode if live_composition else "range"

        live_tool_map = {
            tool.tool_id: self._to_tool_model(tool)
            for tool in self._tool_repo.get_by_ids(member_tool_ids)
        }
        composition_id = (
            snapshot.get("composition_id")
            or (live_composition.composition_id if live_composition else session.workflow_id or "")
        )
        if snapshot_members:
            member_models = []
            for index, payload in enumerate(snapshot_members, start=1):
                tool_id = payload["tool_id"]
                execution_order = payload.get("execution_order")
                member_models.append(
                    SkillCompositionMember(
                        member_id=payload.get("member_id") or f"snapshot_{session.session_id}_{index}",
                        composition_id=composition_id,
                        tool_id=tool_id,
                        selected_order=self._coerce_snapshot_int(
                            payload.get("selected_order"),
                            index,
                        ),
                        execution_order=(
                            self._coerce_snapshot_int(execution_order, index)
                            if mode == "ordered"
                            else None
                        )
                        if execution_order is not None
                        else (index if mode == "ordered" else None),
                        tool=(
                            self._deserialize_trial_session_tool(payload.get("tool"))
                            or live_tool_map.get(tool_id)
                        ),
                    )
                )
        else:
            member_models = [
                SkillCompositionMember(
                    member_id=f"snapshot_{session.session_id}_{index}",
                    composition_id=composition_id,
                    tool_id=tool_id,
                    selected_order=index,
                    execution_order=index if mode == "ordered" else None,
                    tool=live_tool_map.get(tool_id),
                )
                for index, tool_id in enumerate(member_tool_ids, start=1)
            ]

        member_models = sort_composition_members(member_models, mode)

        return SkillComposition(
            composition_id=composition_id,
            composition_name=(
                snapshot.get("composition_name")
                or (live_composition.composition_name if live_composition else "技能组合试用")
            ),
            description=(
                snapshot["description"]
                if "description" in snapshot
                else (live_composition.description if live_composition else None)
            ),
            applicability=(
                snapshot.get("applicability")
                or (live_composition.applicability if live_composition else "试用技能组合")
            ),
            mode=mode,
            status=snapshot.get("status") or (live_composition.status if live_composition else "draft"),
            assistant_enabled=(
                bool(snapshot["assistant_enabled"])
                if "assistant_enabled" in snapshot
                else (bool(live_composition.assistant_enabled) if live_composition else True)
            ),
            recommend_order=(
                bool(snapshot["recommend_order"])
                if "recommend_order" in snapshot
                else (bool(live_composition.recommend_order) if live_composition else False)
            ),
            needs_review=(
                bool(snapshot["needs_review"])
                if "needs_review" in snapshot
                else (bool(live_composition.needs_review) if live_composition else False)
            ),
            members=member_models,
            created_at=live_composition.created_at if live_composition else None,
            updated_at=live_composition.updated_at if live_composition else None,
        )
