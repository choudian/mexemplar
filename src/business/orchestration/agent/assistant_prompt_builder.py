import logging
from typing import Optional

from src.business.agents.config import AgentConfig, AgentType
from src.data.models import MODE_DISPLAY_TEXT
from src.data.repositories import AssistantProfileRepository
from src.utils.helpers import safe_format_template


class AssistantPromptBuilder:
    def __init__(
        self,
        llm_client,
        session_store,
        tool_repo,
        composition_catalog,
        *,
        profile_repo=None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._llm = llm_client
        self._session_store = session_store
        self._tool_repo = tool_repo
        self._composition_catalog = composition_catalog
        self._profile_repo = profile_repo or AssistantProfileRepository()
        self._logger = logger or logging.getLogger(__name__)

    def format_assistant_prompt(self, session_id: str) -> str:
        from src.business.agents.prompts.assistant_prompt import format_assistant_prompt

        profile = self.get_assistant_profile()
        session = self._session_store.get_session(session_id)
        allowed_tool_ids = session.get_tool_id_set() if session else None

        all_published = self._tool_repo.get_published_summaries()
        all_compositions = self._composition_catalog.get_assistant_published_summaries()
        if allowed_tool_ids is not None:
            tools = [tool for tool in all_published if tool["tool_id"] in allowed_tool_ids]
            compositions = [
                composition
                for composition in all_compositions
                if set(composition["member_tool_ids"]).issubset(allowed_tool_ids)
            ]
        else:
            tools = all_published
            compositions = all_compositions

        tool_list = [
            {"name": f"[技能] {tool['tool_name']}", "description": tool["description"]}
            for tool in tools
        ]
        tool_list.extend(
            {
                "name": f"[技能组合/{MODE_DISPLAY_TEXT.get(comp['mode'], comp['mode'])}] "
                f"{comp['composition_name']}",
                "description": comp["description"] or comp["applicability"],
            }
            for comp in compositions
        )

        # Build brain context (new path)
        brain_context_text = ""
        try:
            from src.business.brain.context_builder import BrainContextBuilder
            builder = BrainContextBuilder()
            context = builder.build_context(
                session_id,
                is_revived_session=self._is_revived_session(session_id),
            )
            brain_context_text = builder.format_context_for_prompt(context)
        except Exception as exc:
            self._logger.warning(f"[Orchestrator] 构建大脑上下文失败，使用旧路径: {exc}")

        # Fallback to legacy memory summary if brain context is empty
        memory_summary = None
        if not brain_context_text:
            try:
                from src.business.memory.assistant_memory import get_memory_manager

                memory_manager = get_memory_manager(llm_client=self._llm)
                memory_summary = memory_manager.get_global_summary()
            except Exception as exc:
                self._logger.warning(f"[Orchestrator] 获取全局摘要失败: {exc}")

        return format_assistant_prompt(
            profile=profile,
            tools=tool_list if tool_list else None,
            memory_summary=memory_summary,
            brain_context=brain_context_text if brain_context_text else None,
        )

    def _is_revived_session(self, session_id: str) -> bool:
        """Return true when prompt construction is for an existing assistant session."""
        try:
            return bool(self._session_store.count_messages(session_id) > 0)
        except Exception as exc:
            self._logger.warning("[Orchestrator] 判断复活会话失败: %s", exc)
            return False

    def get_assistant_profile(self) -> Optional[dict]:
        try:
            profile = self._profile_repo.get_default()
            if profile:
                return {
                    "display_name": profile.display_name,
                    "style": profile.style,
                    "notes": profile.notes,
                }
        except Exception as exc:
            self._logger.warning(f"[Orchestrator] 获取 assistant profile 失败: {exc}")
        return None

    def build_trial_config(self, workflow_id: str) -> AgentConfig:
        from src.business.agents.prompts.trial_prompt import (
            TRIAL_SYSTEM_PROMPT_TEMPLATE,
            format_parameters_text,
        )

        tool = self._tool_repo.get_by_workflow_id(workflow_id)
        if not tool:
            raise ValueError(f"未找到 workflow_id={workflow_id} 对应的工具")

        parameters_text = format_parameters_text(tool.parameters or [])
        system_prompt = safe_format_template(
            TRIAL_SYSTEM_PROMPT_TEMPLATE,
            tool_name=tool.tool_name,
            description=tool.description or "（无描述）",
            parameters_text=parameters_text,
        )
        return AgentConfig(
            agent_type=AgentType.TRIAL,
            system_prompt=system_prompt,
            max_iterations=20,
            text_as_user_input=True,
        )
