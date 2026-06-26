"""
SkillCompositionService — 技能组合业务服务
"""

import uuid
from typing import Any, Dict, Iterable, List, Optional

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS
from src.business.ai.llm_client import LangChainLLMClient
from src.data.models import SkillComposition, Tool
from src.data.repositories import (
    MessageRepository,
    SessionRepository,
    SkillCompositionRepository,
    ToolRepository,
)
from src.data.unified_config import get_unified_config

from .composition_llm_helper import CompositionLLMHelper
from .composition_normalizer import (
    VALID_MODES,
    VALID_STATUSES,
    build_composition_orm,
    build_member_orms,
    is_published_available,
    member_to_payload,
    normalize_members,
    to_composition_model,
    to_tool_model,
)
from .trial_prompt_builder import (
    build_trial_bootstrap_input,
    build_trial_system_prompt,
)
from .trial_runner import TrialRunner
from .trial_snapshot_codec import (
    build_trial_session_snapshot_payload,
)
from .types import (
    SkillCompositionError,
    SkillCompositionTrialResult,
    SkillCompositionTrialSessionStart,
)


class SkillCompositionService:
    """技能组合管理与执行服务。"""

    VALID_MODES = VALID_MODES
    VALID_STATUSES = VALID_STATUSES
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
        self._composition_llm_instance = None
        self._trial_sessions_instance = None

    def _create_llm(
        self,
        config=None,
        temperature: float = 0.4,
        max_tokens: int | None = None,
    ) -> LangChainLLMClient:
        """创建 LLM 客户端，统一配置读取和 Key 校验。"""
        if config is None:
            config = get_unified_config()
        if max_tokens is None:
            max_tokens = config.get_ai_max_tokens()
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
            thinking_level=config.get_ai_thinking_level(),
            timeout=config.get_ai_request_timeout(),
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

    @property
    def _composition_llm(self) -> CompositionLLMHelper:
        if self._composition_llm_instance is None:
            self._composition_llm_instance = CompositionLLMHelper(
                tool_repo=self._tool_repo,
                llm_factory=self._create_llm,
            )
        return self._composition_llm_instance

    @property
    def _trial_sessions(self) -> TrialRunner:
        if self._trial_sessions_instance is None:
            self._trial_sessions_instance = TrialRunner(
                composition_repo=self._composition_repo,
                tool_repo=self._tool_repo,
                session_repo=self._session_repository,
                message_repo=self._message_repository,
                llm_factory=self._create_llm,
                loop_cls=AgentLoop,
                config_provider=lambda: get_unified_config(),
                general_tools=BUILTIN_GENERAL_TOOLS,
            )
        return self._trial_sessions_instance

    def _hydrate_compositions(self, compositions) -> List[SkillComposition]:
        """批量获取成员并转换为领域模型。"""
        if not compositions:
            return []
        members_by_comp = self._composition_repo.get_members_for_compositions(
            [c.composition_id for c in compositions]
        )
        return [
            self._to_composition_model(c, members_by_comp.get(c.composition_id, []))
            for c in compositions
        ]

    def list_compositions(self) -> List[SkillComposition]:
        return self._hydrate_compositions(self._composition_repo.get_all())

    def get_composition(self, composition_id: str) -> Optional[SkillComposition]:
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
        composition = self._composition_repo.get_by_name(name)
        if composition is None:
            return None
        if require_published and not is_published_available(composition):
            return None
        members = self._composition_repo.get_members(composition.composition_id)
        return self._to_composition_model(composition, members)

    def get_assistant_published_summaries(self) -> List[dict]:
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
        return self._hydrate_compositions(
            self._composition_repo.get_referencing_compositions(tool_id, statuses=statuses)
        )

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
        composition = self._composition_repo.get_by_id(composition_id)
        if composition is None:
            raise SkillCompositionError("技能组合不存在")
        members = self._composition_repo.get_members(composition_id)
        self._normalize_members(
            composition.mode,
            [self._member_to_payload(member) for member in members],
        )
        self._composition_repo.update_status(composition_id, "published")
        self._composition_repo.clear_needs_review(composition_id)
        return self.get_composition(composition_id)

    def mark_needs_review_by_tool(self, tool_id: str) -> List[SkillComposition]:
        return self._hydrate_compositions(self._composition_repo.mark_needs_review_by_tool(tool_id))

    def recommend_execution_order(
        self,
        composition_name: str,
        description: str,
        applicability: str,
        members: List[dict],
    ) -> dict:
        return self._composition_llm.recommend_execution_order(
            composition_name=composition_name,
            description=description,
            applicability=applicability,
            members=members,
        )

    def generate_applicability(
        self,
        composition_name: str,
        description: str,
        mode: str,
        members: List[dict],
    ) -> str:
        return self._composition_llm.generate_applicability(
            composition_name=composition_name,
            description=description,
            mode=mode,
            members=members,
        )

    def run_trial(
        self,
        composition_id: str,
        task: str,
        context: str = "",
    ) -> SkillCompositionTrialResult:
        return self._trial_sessions.run_trial(composition_id, task, context=context)

    def start_trial_session(self, composition_id: str) -> SkillCompositionTrialSessionStart:
        return self._trial_sessions.start_trial_session(composition_id)

    @staticmethod
    def build_trial_bootstrap_input() -> Dict[str, str]:
        return build_trial_bootstrap_input()

    def continue_trial(
        self,
        composition_id: str,
        session_id: str,
        user_input: Any,
    ) -> SkillCompositionTrialResult:
        return self._trial_sessions.continue_trial(
            composition_id,
            session_id,
            user_input,
        )

    def get_execution_snapshot(
        self,
        composition_id: str,
        require_published: bool = True,
        require_assistant_enabled: bool = True,
    ) -> Optional[SkillComposition]:
        return self._trial_sessions.get_execution_snapshot(
            composition_id,
            require_published=require_published,
            require_assistant_enabled=require_assistant_enabled,
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

    def _normalize_members(self, mode: str, members: List[dict]) -> List[dict]:
        return normalize_members(mode, members, self._tool_repo)

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
        return build_composition_orm(
            composition_id=composition_id,
            composition_name=composition_name,
            description=description,
            applicability=applicability,
            mode=mode,
            status=status,
            assistant_enabled=assistant_enabled,
            recommend_order=recommend_order,
            needs_review=needs_review,
            composition_repo=self._composition_repo,
        )

    def _build_member_orms(self, composition_id: str, members: List[dict]):
        return build_member_orms(composition_id, members)

    def _to_composition_model(self, composition, members_orm) -> SkillComposition:
        return to_composition_model(composition, members_orm, self._tool_repo)

    @staticmethod
    def _member_to_payload(member) -> dict:
        return member_to_payload(member)
