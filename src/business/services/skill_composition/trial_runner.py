"""Trial session execution helpers for skill compositions."""

import json
import uuid
from typing import Any, Callable, Optional, Sequence

from src.business.agents.config import ASSISTANT_CONFIG, ResultType
from src.business.debug.context import TraceContext
from src.data.models import SkillComposition, SkillCompositionMember, sort_composition_members
from src.data.models_sqlite import Session

from .composition_normalizer import (
    VALID_MODES,
    is_published_available,
    to_composition_model,
    to_tool_model,
)
from .trial_prompt_builder import (
    build_trial_system_prompt,
    build_trial_user_input,
    normalize_trial_dialog_input,
)
from .trial_snapshot_codec import (
    build_trial_session_snapshot_payload,
    coerce_snapshot_int,
    deserialize_trial_session_tool,
    parse_trial_session_snapshot,
)
from .types import (
    SkillCompositionError,
    SkillCompositionTrialResult,
    SkillCompositionTrialSessionStart,
)


class TrialRunner:
    """Owns skill composition trial session lifecycle and execution."""

    def __init__(
        self,
        *,
        composition_repo,
        tool_repo,
        session_repo,
        message_repo,
        llm_factory: Callable,
        loop_cls,
        config_provider: Callable[[], Any],
        general_tools: Sequence[Any],
    ):
        self._composition_repo = composition_repo
        self._tool_repo = tool_repo
        self._session_repo = session_repo
        self._message_repo = message_repo
        self._llm_factory = llm_factory
        self._loop_cls = loop_cls
        self._config_provider = config_provider
        self._general_tools = list(general_tools)

    def run_trial(
        self,
        composition_id: str,
        task: str,
        context: str = "",
    ) -> SkillCompositionTrialResult:
        composition = self.get_execution_snapshot(
            composition_id,
            require_published=False,
            require_assistant_enabled=False,
        )
        if composition is None:
            raise SkillCompositionError("技能组合不存在")
        if not task.strip():
            raise SkillCompositionError("试用任务不能为空")

        user_input = build_trial_user_input(
            composition=composition,
            task=task,
            context=context,
        )
        return self.run_trial_session(
            composition=composition,
            user_input=user_input,
            include_member_tools=False,
        )

    def start_trial_session(
        self,
        composition_id: str,
    ) -> SkillCompositionTrialSessionStart:
        composition = self.get_execution_snapshot(
            composition_id,
            require_published=False,
            require_assistant_enabled=False,
        )
        if composition is None:
            raise SkillCompositionError("技能组合不存在")

        session_id = self.create_trial_session(composition)
        return SkillCompositionTrialSessionStart(
            composition_id=composition.composition_id,
            composition_name=composition.composition_name,
            session_id=session_id,
        )

    def continue_trial(
        self,
        composition_id: str,
        session_id: str,
        user_input: Any,
    ) -> SkillCompositionTrialResult:
        if not session_id.strip():
            raise SkillCompositionError("试用会话不存在")
        normalized_input = normalize_trial_dialog_input(user_input)

        existing_session = self._session_repo.get_by_id(session_id)
        if existing_session is None or existing_session.agent_type != "composition_trial":
            raise SkillCompositionError("试用会话不存在")
        if existing_session.workflow_id != composition_id:
            raise SkillCompositionError("试用会话不属于当前技能组合")
        composition = self.get_trial_session_composition(existing_session)
        if composition is None:
            raise SkillCompositionError("技能组合不存在")

        return self.run_trial_session(
            composition=composition,
            user_input=normalized_input,
            session_id=session_id,
            include_member_tools=self.session_has_started_composition(
                session_id,
                composition.composition_id,
            ),
        )

    def get_execution_snapshot(
        self,
        composition_id: str,
        require_published: bool = True,
        require_assistant_enabled: bool = True,
    ) -> Optional[SkillComposition]:
        composition = self._composition_repo.get_by_id(composition_id)
        if composition is None:
            return None
        if require_published and not is_published_available(composition):
            return None
        if require_assistant_enabled and not composition.assistant_enabled:
            return None
        members = self._composition_repo.get_members(composition_id)
        return to_composition_model(composition, members, self._tool_repo)

    def run_trial_session(
        self,
        composition: SkillComposition,
        user_input: Any,
        session_id: Optional[str] = None,
        include_member_tools: bool = False,
    ) -> SkillCompositionTrialResult:
        config = self._config_provider()
        llm = self._llm_factory(config=config, temperature=0.4, max_tokens=1200)
        loop = self._loop_cls(ASSISTANT_CONFIG, llm, config)

        manager = self.build_trial_manager(
            composition,
            include_member_tools=include_member_tools,
        )

        def tool_factory():
            return [*self._general_tools, *manager.get_activated_tools()]

        if session_id is None:
            session_id = self.create_trial_session(composition)

        with TraceContext(
            source="skill_composition_trial",
            agent_type="composition_trial",
            session_id=session_id,
            workflow_id=composition.composition_id,
            work_unit_id=composition.composition_id,
        ):
            result = loop.run(
                session_id=session_id,
                user_input=user_input,
                tools=tool_factory,
                system_prompt_override=build_trial_system_prompt(composition),
            )
        return self.to_trial_result(result, session_id)

    def build_trial_manager(
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

    def create_trial_session(self, composition: SkillComposition) -> str:
        session_id = f"comptrial_{uuid.uuid4().hex[:12]}"
        self._session_repo.create(
            Session(
                session_id=session_id,
                workflow_id=composition.composition_id,
                agent_type="composition_trial",
                status="active",
                tool_ids=json.dumps(
                    build_trial_session_snapshot_payload(composition),
                    ensure_ascii=False,
                ),
            )
        )
        return session_id

    def session_has_started_composition(
        self,
        session_id: str,
        composition_id: str,
    ) -> bool:
        entity_id = composition_id
        candidates = {f"comp_{entity_id[:8]}", f"comp_{entity_id[:12]}"}
        messages = self._message_repo.get_context(session_id)
        return any(message.tool_name in candidates for message in messages)

    def to_trial_result(self, result, session_id: str) -> SkillCompositionTrialResult:
        if result.result_type == ResultType.NEEDS_USER_INPUT:
            return SkillCompositionTrialResult(
                success=False,
                reply=result.question or "",
                result_type=result.result_type.value,
                session_id=session_id,
            )
        if result.result_type == ResultType.COMPLETED:
            return SkillCompositionTrialResult(
                success=True,
                reply=self.get_last_assistant_reply(session_id),
                result_type=result.result_type.value,
                session_id=session_id,
            )

        error = result.error or "技能组合试用失败"
        return SkillCompositionTrialResult(
            success=False,
            reply=self.get_last_assistant_reply(session_id),
            result_type=result.result_type.value,
            error=error,
            session_id=session_id,
        )

    def get_last_assistant_reply(self, session_id: str) -> str:
        messages = self._message_repo.get_context(session_id)
        for message in reversed(messages):
            if message.role == "assistant" and message.content:
                return message.content
        return ""

    def get_trial_session_composition(
        self,
        session: Session,
    ) -> Optional[SkillComposition]:
        live_composition = (
            self.get_execution_snapshot(
                session.workflow_id, require_published=False, require_assistant_enabled=False
            )
            if session.workflow_id
            else None
        )
        snapshot = parse_trial_session_snapshot(session.tool_ids)
        snapshot_members = snapshot.get("members") or []
        member_tool_ids = snapshot.get("member_tool_ids") or (
            [member.tool_id for member in live_composition.members] if live_composition else []
        )
        if not member_tool_ids and live_composition is None:
            return None

        mode = str(
            snapshot.get("mode") or (live_composition.mode if live_composition else "range")
        ).strip()
        if mode not in VALID_MODES:
            mode = live_composition.mode if live_composition else "range"

        live_tool_map = {
            tool.tool_id: to_tool_model(tool)
            for tool in self._tool_repo.get_by_ids(member_tool_ids)
        }
        composition_id = snapshot.get("composition_id") or (
            live_composition.composition_id if live_composition else session.workflow_id or ""
        )
        if snapshot_members:
            member_models = []
            for index, payload in enumerate(snapshot_members, start=1):
                tool_id = payload["tool_id"]
                execution_order = payload.get("execution_order")
                member_models.append(
                    SkillCompositionMember(
                        member_id=payload.get("member_id")
                        or f"snapshot_{session.session_id}_{index}",
                        composition_id=composition_id,
                        tool_id=tool_id,
                        selected_order=coerce_snapshot_int(
                            payload.get("selected_order"),
                            index,
                        ),
                        execution_order=(
                            (
                                coerce_snapshot_int(execution_order, index)
                                if mode == "ordered"
                                else None
                            )
                            if execution_order is not None
                            else (index if mode == "ordered" else None)
                        ),
                        tool=deserialize_trial_session_tool(payload.get("tool"))
                        or live_tool_map.get(tool_id),
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
            status=snapshot.get("status")
            or (live_composition.status if live_composition else "draft"),
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
