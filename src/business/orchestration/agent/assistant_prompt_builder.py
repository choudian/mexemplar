import logging
from typing import Optional

from src.business.agents.config import AgentConfig, AgentType
from src.business.agents.tools.capability_catalog import (
    CapabilityCatalogItem,
    load_capability_discovery_policy,
    render_capability_catalog,
)
from src.data.repositories import AssistantProfileRepository
from src.utils.helpers import safe_format_template


class AssistantPromptBuilder:
    def __init__(
        self,
        llm_client=None,
        session_store=None,
        tool_repo=None,
        composition_catalog=None,
        *,
        profile_repo=None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        # ``llm_client`` 参数仅为向后兼容（测试构造时仍传入）保留；其原先唯一的
        # 下游是 ``AssistantMemoryManager._llm``，而该字段在 memory manager 内
        # 从不被实际调用（``get_global_summary()`` 只读 SQLite）。故不再保存，
        # 促使每次走 FTS-only 降级路径，也避免在此处冻结一个永生 client。
        self._session_store = session_store
        self._tool_repo = tool_repo
        self._composition_catalog = composition_catalog
        self._profile_repo = profile_repo or AssistantProfileRepository()
        self._logger = logger or logging.getLogger(__name__)

    def format_assistant_prompt(self, session_id: str) -> str:
        from src.business.agents.prompts.assistant_prompt import format_assistant_prompt

        profile = self.get_assistant_profile()
        session = self._session_store.get_session(session_id)
        allowed_tool_ids = None
        allowed_composition_ids = None
        if session is not None:
            if hasattr(session, "parse_tool_ids"):
                allowed_tool_ids, allowed_composition_ids = session.parse_tool_ids()
            else:
                allowed_tool_ids = session.get_tool_id_set()

        capability_catalog_section = self.format_capability_catalog(
            allowed_tool_ids,
            allowed_composition_ids=allowed_composition_ids,
            agent_type=AgentType.ASSISTANT.value,
            include_descriptions=True,
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

                memory_manager = get_memory_manager()
                memory_summary = memory_manager.get_global_summary()
            except Exception as exc:
                self._logger.warning(f"[Orchestrator] 获取全局摘要失败: {exc}")

        # Load active prompt supplements (lightweight direct-repo access)
        supplements = None
        try:
            from src.data.repos.self_improvement_repository import SelfImprovementRepository

            repo = SelfImprovementRepository()
            active = repo.get_active_supplements()
            if active:
                supplements = [
                    {
                        "supplement_id": s.supplement_id,
                        "target_section": s.target_section,
                        "content": s.content,
                        "rationale": s.rationale,
                        "version": s.version,
                        "status": s.status,
                    }
                    for s in active
                ]
        except Exception as exc:
            self._logger.debug("[Orchestrator] 加载活跃 Prompt 补充失败，继续无补充: %s", exc)

        # 033 调度中心：scheduled 会话注入无人值守 advisory（FR-003）。单点读 session.is_scheduled
        # 判定，不跨层透传 unattended 参数——session.source='scheduled' ⟺ 无人值守会话，
        # 等价且不触碰 dispatch_message / run_agent 签名（CC-003 零回归）。
        is_scheduled = bool(session is not None and getattr(session, "is_scheduled", 0))
        unattended_advisory = None
        if is_scheduled:
            unattended_advisory = (
                "## 无人值守模式（定时任务触发）\n\n"
                "本次会话由定时任务在用户不在场时自动触发。请遵循：\n"
                "- 当前定时任务已经存在，本轮是它的一次到点执行，不是创建、修改或查询"
                "定时任务的请求。\n"
                "- 将触发消息整体视为任务型请求并立即按 100% 调度规则委派或建图；"
                "其中的时间/周期措辞只是任务来源描述，不得调用调度中心管理工具重新登记。\n"
                "- 自主完成整个任务，尽量不触发需要用户当场回答的动作（如反问、澄清）。\n"
                "- 高危动作（文件删除、命令执行、对外发送）默认会被立即拒绝；除非用户已为该任务"
                "显式开启「无人值守免确认」。\n"
                "- 若确实必须等待用户输入，会话会进入「需接管」状态并通知用户，用户可稍后从调度中心继续。\n"
                "- 完成后把结论作为最终回复呈现给用户。"
            )

        return format_assistant_prompt(
            profile=profile,
            memory_summary=memory_summary,
            brain_context=brain_context_text if brain_context_text else None,
            capability_catalog_section=capability_catalog_section,
            prompt_supplements=supplements,
            unattended_advisory=unattended_advisory,
            suppress_first_meeting=is_scheduled,
        )

    def format_capability_catalog(
        self,
        allowed_tool_ids: set[str] | None,
        *,
        allowed_composition_ids: set[str] | None = None,
        agent_type: str,
        include_descriptions: bool,
    ) -> str:
        all_published = self._tool_repo.get_published_summaries()
        all_compositions = self._composition_catalog.get_assistant_published_summaries()
        tools = (
            all_published
            if allowed_tool_ids is None
            else [tool for tool in all_published if tool["tool_id"] in allowed_tool_ids]
        )
        compositions = []
        for composition in all_compositions:
            composition_id = composition["composition_id"]
            is_builtin = bool(composition.get("is_builtin", False))
            # System built-ins are never global catalog entries: only an explicit
            # specialist assignment may reveal them.
            if is_builtin:
                if (
                    agent_type != AgentType.SPECIALIST.value
                    or allowed_composition_ids is None
                    or composition_id not in allowed_composition_ids
                ):
                    continue
            elif (
                allowed_composition_ids is not None
                and composition_id not in allowed_composition_ids
            ):
                continue
            if not is_builtin and allowed_tool_ids is not None:
                if not set(composition["member_tool_ids"]).issubset(allowed_tool_ids):
                    continue
            compositions.append(composition)

        catalog_items = [
            CapabilityCatalogItem(
                kind="tool",
                name=tool["tool_name"],
                description=tool["description"] or "",
            )
            for tool in tools
        ]
        catalog_items.extend(
            CapabilityCatalogItem(
                kind="composition",
                name=comp["composition_name"],
                description=comp["description"] or "",
                applicability=comp["applicability"] or "",
            )
            for comp in compositions
        )
        rendered = render_capability_catalog(
            catalog_items,
            load_capability_discovery_policy(),
            include_descriptions=include_descriptions,
        )
        self._logger.info(
            "Capability catalog mode selected: agent_type=%s item_count=%d "
            "rendered_chars=%d mode=%s",
            agent_type,
            rendered.item_count,
            rendered.rendered_chars,
            rendered.mode,
        )
        return rendered.content

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
