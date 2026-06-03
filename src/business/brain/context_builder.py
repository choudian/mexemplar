"""
Brain Context Builder - 构建多分区上下文并渲染 assistant prompt 注入段。

热区排名使用复合评分（relevance + recency + effectiveness + exploration），
复用会话时已加载条目会获得额外加权。潜意识区按 recency、effectiveness
和 exploration 复合评分排序；prediction zone 仅用于系统自校准，不注入
assistant 上下文。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from src.business.brain.models import EntryStatus, Zone
from src.business.brain.scoring import (
    EXPLORATION_LOADED_THRESHOLD as _EXPLORATION_LOADED_THRESHOLD,
    HOT_EFFECTIVENESS_WEIGHT as _HOT_EFFECTIVENESS_WEIGHT,
    HOT_EXPLORATION_WEIGHT as _HOT_EXPLORATION_WEIGHT,
    HOT_RECENCY_WEIGHT as _HOT_RECENCY_WEIGHT,
    HOT_RELEVANCE_WEIGHT as _HOT_RELEVANCE_WEIGHT,
    HOT_REVIVED_SESSION_BONUS as _REVIVED_LOADED_BONUS,
    SUBCONSCIOUS_EFFECTIVENESS_WEIGHT as _SUBCONSCIOUS_EFFECTIVENESS_WEIGHT,
    SUBCONSCIOUS_EXPLORATION_WEIGHT as _SUBCONSCIOUS_EXPLORATION_WEIGHT,
    SUBCONSCIOUS_RECENCY_WEIGHT as _SUBCONSCIOUS_RECENCY_WEIGHT,
    compute_recency_score,
)
from src.data.repos.skill_equipment_repository import ASSISTANT_ENTITY_ID
from src.utils.events import emit

logger = logging.getLogger(__name__)

_HOT_VISIBLE_STATUSES = (EntryStatus.ACTIVE.value, EntryStatus.FADING.value)


@dataclass
class BrainContext:
    """构建完成的大脑上下文"""

    entries: list[Any] = field(default_factory=list)
    persistent_entries: list[dict] = field(default_factory=list)
    hot_entries: list[dict] = field(default_factory=list)
    subconscious_entries: list[dict] = field(default_factory=list)
    specialists: list[dict] = field(default_factory=list)
    equipped_skills: list[dict] = field(default_factory=list)
    context_warnings: list[str] = field(default_factory=list)
    is_cold_start: bool = True
    injected_entry_ids: list[str] = field(default_factory=list)


class BrainContextBuilder:
    """会话启动时构建大脑上下文"""

    def __init__(self, repo=None, specialist_repo=None, config=None):
        self._repo = repo
        self._specialist_repo = specialist_repo
        self._config = config

    def _get_repo(self):
        if self._repo is None:
            from src.data.repos.brain_repository import BrainRepository

            self._repo = BrainRepository()
        return self._repo

    def _get_specialist_repo(self):
        if self._specialist_repo is None:
            from src.data.repos.specialist_repository import SpecialistRepository

            self._specialist_repo = SpecialistRepository()
        return self._specialist_repo

    def _get_config(self):
        if self._config is None:
            from src.data.unified_config import get_unified_config

            self._config = get_unified_config()
        return self._config

    def build_context(
        self,
        session_id: Optional[str] = None,
        is_revived_session: bool = False,
        track_loaded: bool = True,
    ) -> BrainContext:
        """构建大脑上下文（同步，用于 assistant 首轮回复前）。

        Args:
            session_id: 当前会话 ID
            is_revived_session: 是否为复用会话（之前已有上下文注入过）

        Returns:
            BrainContext 包含所有要注入的分区条目
        """
        repo = self._get_repo()
        persistent_entries = []
        hot_entries = []
        subconscious_entries = []
        specialist_list = []
        equipped_skills = []
        context_warnings = []
        injected_ids = []
        selected_entries = []

        config = self._get_config()
        hot_top_n = self._config_int(config, "get_brain_injection_hot_zone_top_n", 20)
        persistent_top_n = self._config_int(
            config,
            "get_brain_injection_persistent_top_n",
            50,
        )
        subconscious_top_n = self._config_int(
            config,
            "get_brain_injection_subconscious_top_n",
            10,
        )

        # 持久区：长期事实也要有上限，避免高频沉淀撑爆 prompt。
        persistent_rows = self._entries_for_zone(
            repo,
            Zone.PERSISTENT.value,
            status=EntryStatus.ACTIVE.value,
            limit=persistent_top_n,
        )
        for entry in persistent_rows:
            persistent_entries.append(self._entry_to_prompt_dict(entry))
            selected_entries.append(entry)
            injected_ids.append(self._entry_attr(entry, "entry_id", ""))

        # 热区：active 与 fading 都仍对 assistant 可见，然后用复合评分选取 top-N
        hot_rows = self._entries_for_zone(
            repo,
            Zone.HOT.value,
            status=_HOT_VISIBLE_STATUSES,
        )
        scored_hot = []
        for entry in hot_rows:
            entry_data = self._entry_to_scoring_dict(entry)
            scored_hot.append(
                (
                    self._compute_hot_composite_score(entry_data, is_revived_session),
                    entry,
                )
            )
        scored_hot.sort(key=lambda item: item[0], reverse=True)
        for _, entry in scored_hot[:hot_top_n]:
            hot_entries.append(self._entry_to_prompt_dict(entry))
            selected_entries.append(entry)
            injected_ids.append(self._entry_attr(entry, "entry_id", ""))

        # 专员列表（active）
        try:
            specialist_repo = self._get_specialist_repo()
            specialists_result = specialist_repo.list_specialists(active_only=True)
            specialists = (
                specialists_result[0]
                if isinstance(specialists_result, tuple)
                else specialists_result
            )
            specialist_list = [self._specialist_to_prompt_dict(item) for item in specialists]
            specialist_list.sort(key=lambda item: item["name"])
        except Exception as exc:
            logger.warning("Failed to load brain specialists for prompt context: %s", exc)
            context_warnings.append("可用专员列表暂时不可用；本轮不要假定专员能力清单完整。")

        try:
            equipped_skills = self.equipped_skills_for_entity(ASSISTANT_ENTITY_ID)
        except Exception as exc:
            logger.warning("Failed to load assistant methodology equipment: %s", exc)
            context_warnings.append("方法论装备清单暂时不可用；本轮不要假定自己没有可用方法论。")

        # 潜意识区：以新近度为主的复合评分 top-N（仅 active，不含 prediction zone）
        subconscious_rows = self._entries_for_zone(
            repo,
            Zone.SUBCONSCIOUS.value,
            status=EntryStatus.ACTIVE.value,
            limit=None,
        )
        scored_subconscious = [
            (
                self._compute_subconscious_composite_score(
                    self._entry_to_scoring_dict(entry),
                ),
                entry,
            )
            for entry in subconscious_rows
        ]
        scored_subconscious.sort(key=lambda item: item[0], reverse=True)
        for _, entry in scored_subconscious[:subconscious_top_n]:
            subconscious_entries.append(self._entry_to_prompt_dict(entry))
            selected_entries.append(entry)
            injected_ids.append(self._entry_attr(entry, "entry_id", ""))

        # 批量更新 loaded_count
        if track_loaded and injected_ids:
            try:
                repo.batch_increment_loaded_count(injected_ids)
            except Exception as exc:
                logger.warning(
                    "Failed to update brain loaded_count; continuing without metric update: %s",
                    exc,
                )

        is_cold_start = len(persistent_rows) == 0 and len(hot_rows) == 0

        context = BrainContext(
            entries=selected_entries,
            persistent_entries=persistent_entries,
            hot_entries=hot_entries,
            subconscious_entries=subconscious_entries,
            specialists=specialist_list,
            equipped_skills=equipped_skills,
            context_warnings=context_warnings,
            is_cold_start=is_cold_start,
            injected_entry_ids=injected_ids,
        )

        if session_id:
            emit("brain_context_ready", session_id=session_id)
        logger.info(
            "Brain context built for session %s: %d persistent, %d hot, %d specialists, "
            "cold_start=%s, revived=%s",
            session_id,
            len(persistent_entries),
            len(hot_entries),
            len(specialist_list),
            is_cold_start,
            is_revived_session,
        )

        return context

    def _entries_for_zone(
        self,
        repo,
        zone: str,
        *,
        status: Optional[str | tuple[str, ...] | list[str]] = None,
        limit: Optional[int] = 50,
        offset: int = 0,
    ) -> list[Any]:
        result = repo.get_entries_by_zone(zone, status=status, limit=limit, offset=offset)
        if isinstance(result, tuple):
            return list(result[0])
        return list(result)

    def equipped_skills_for_entity(self, entity_id: str) -> list[dict]:
        from src.business.brain.skill_equipment_service import SkillEquipmentService

        session = self._get_repo().session if self._repo else None
        equipment = SkillEquipmentService(session=session).get_equipment_for_entity(entity_id)
        return list(equipment.get("active_equipment", []))

    def _config_int(self, config, method_name: str, default: int) -> int:
        getter = getattr(config, method_name, None)
        if getter is None:
            return default
        try:
            value = getter()
            if not isinstance(value, (int, float, str)):
                return default
            parsed = int(value)
            return parsed if parsed >= 0 else default
        except (TypeError, ValueError):
            return default

    def _entry_attr(self, entry, name: str, default=None):
        return getattr(entry, name, default)

    def _entry_to_prompt_dict(self, entry) -> dict:
        return {
            "entry_id": self._entry_attr(entry, "entry_id", ""),
            "content": self._entry_attr(entry, "content", ""),
            "zone": self._entry_attr(entry, "zone", ""),
            "entry_type": self._entry_attr(entry, "entry_type", None),
            "reason": self._entry_attr(entry, "reason", ""),
            "scope": self._entry_attr(entry, "scope", None),
            "relevance_score": self._entry_attr(entry, "relevance_score", 0.0) or 0.0,
            "loaded_count": self._entry_attr(entry, "loaded_count", 0) or 0,
            "referenced_count": self._entry_attr(entry, "referenced_count", 0) or 0,
        }

    def _entry_to_scoring_dict(self, entry) -> dict:
        created_at = self._entry_attr(entry, "created_at", "") or ""
        updated_at = self._entry_attr(entry, "updated_at", "") or ""
        return {
            "entry_id": self._entry_attr(entry, "entry_id", ""),
            "relevance_score": self._entry_attr(entry, "relevance_score", 0.0) or 0.0,
            "loaded_count": self._entry_attr(entry, "loaded_count", 0) or 0,
            "referenced_count": self._entry_attr(entry, "referenced_count", 0) or 0,
            "created_at": str(created_at),
            "updated_at": str(updated_at),
        }

    def _specialist_to_prompt_dict(self, specialist) -> dict:
        import json

        whitelist = self._entry_attr(specialist, "tool_whitelist", [])
        if isinstance(whitelist, str):
            try:
                whitelist = json.loads(whitelist)
            except json.JSONDecodeError:
                whitelist = []
        return {
            "specialist_id": self._entry_attr(specialist, "specialist_id", ""),
            "name": self._entry_attr(specialist, "name", ""),
            "description": self._entry_attr(specialist, "description", ""),
            "role_definition": self._entry_attr(specialist, "role_definition", ""),
            "tool_whitelist": whitelist,
        }

    def _compute_hot_composite_score(self, entry: dict, is_revived_session: bool) -> float:
        """计算热区条目的复合评分。

        composite = relevance_w * relevance
                  + recency_w * recency
                  + effectiveness_w * effectiveness
                  + exploration_w * exploration
                  + (revived_session ? loaded_bonus : 0)
        """
        relevance = entry.get("relevance_score", 0.0)

        # recency: 基于创建时间的衰减
        recency_score = self._compute_recency_score(entry.get("created_at", ""))

        # effectiveness: referenced_count / max(loaded_count, 1)
        loaded = max(entry.get("loaded_count", 0), 1)
        referenced = entry.get("referenced_count", 0)
        effectiveness_score = min(referenced / loaded, 1.0)

        # exploration: loaded_count 很低的条目获得加分
        loaded_count = entry.get("loaded_count", 0)
        if loaded_count < _EXPLORATION_LOADED_THRESHOLD:
            exploration_bonus = 1.0 - (loaded_count / _EXPLORATION_LOADED_THRESHOLD)
        else:
            exploration_bonus = 0.0

        composite = (
            _HOT_RELEVANCE_WEIGHT * relevance
            + _HOT_RECENCY_WEIGHT * recency_score
            + _HOT_EFFECTIVENESS_WEIGHT * effectiveness_score
            + _HOT_EXPLORATION_WEIGHT * exploration_bonus
        )

        # 复用会话：之前被加载过的条目获得正向加权
        if is_revived_session and loaded_count > 0:
            composite += _REVIVED_LOADED_BONUS * min(loaded_count / 3.0, 1.0)

        return round(composite, 4)

    def _compute_subconscious_composite_score(self, entry: dict) -> float:
        """计算潜意识区复合评分，以更新时间代表隐性特征演化的新近度。"""
        timestamp = entry.get("updated_at") or entry.get("created_at", "")
        recency_score = self._compute_recency_score(timestamp)

        loaded_count = entry.get("loaded_count", 0)
        loaded = max(loaded_count, 1)
        referenced = entry.get("referenced_count", 0)
        effectiveness_score = min(referenced / loaded, 1.0)

        if loaded_count < _EXPLORATION_LOADED_THRESHOLD:
            exploration_bonus = 1.0 - (loaded_count / _EXPLORATION_LOADED_THRESHOLD)
        else:
            exploration_bonus = 0.0

        composite = (
            _SUBCONSCIOUS_RECENCY_WEIGHT * recency_score
            + _SUBCONSCIOUS_EFFECTIVENESS_WEIGHT * effectiveness_score
            + _SUBCONSCIOUS_EXPLORATION_WEIGHT * exploration_bonus
        )
        return composite

    def _compute_recency_score(self, created_at_str: str) -> float:
        """基于创建时间计算新近度评分（0-1）。"""
        return compute_recency_score(created_at_str, half_life_days=30)

    def compute_composite_scores(
        self,
        entries: list,
        is_revived_session: bool = False,
    ) -> list[dict]:
        """为条目列表计算复合评分（公开方法，供测试使用）。

        Args:
            entries: MemoryEntryData 列表
            is_revived_session: 是否为复用会话

        Returns:
            包含 entry_id 和 composite_score 的字典列表
        """
        results = []
        for entry in entries:
            entry_data = {
                "entry_id": getattr(entry, "entry_id", ""),
                "relevance_score": getattr(entry, "relevance_score", 0.0),
                "loaded_count": getattr(entry, "loaded_count", 0),
                "referenced_count": getattr(entry, "referenced_count", 0),
                "created_at": getattr(entry, "created_at", "") or "",
            }
            composite = self._compute_hot_composite_score(entry_data, is_revived_session)
            results.append(
                {
                    "entry_id": entry_data["entry_id"],
                    "composite_score": composite,
                }
            )
        return results

    def format_context_for_prompt(self, context: BrainContext) -> str:
        """将 BrainContext 格式化为可注入 prompt 的文本"""
        sections = []

        if context.persistent_entries:
            sections.append("## 持久记忆（用户长期偏好与重要事实）")
            for entry in context.persistent_entries:
                scope_note = f" [{entry['scope']}]" if entry.get("scope") else ""
                id_note = self._format_entry_id_note(entry)
                sections.append(f"- {id_note}{entry['content']}{scope_note}")

        if context.hot_entries:
            sections.append("## 近期记忆（最近对话中的重要信息）")
            for entry in context.hot_entries:
                type_icon = "[事件]" if entry.get("entry_type") == "event" else "[洞察]"
                scope_note = f" [{entry['scope']}]" if entry.get("scope") else ""
                id_note = self._format_entry_id_note(entry)
                sections.append(f"- {type_icon} {id_note}{entry['content']}{scope_note}")

        if context.subconscious_entries:
            sections.append("## 潜意识记忆（偏好、价值观、风格）")
            for entry in context.subconscious_entries:
                scope_note = f" [{entry['scope']}]" if entry.get("scope") else ""
                id_note = self._format_entry_id_note(entry)
                sections.append(f"- {id_note}{entry['content']}{scope_note}")

        if context.specialists:
            sections.append("## 可用专员")
            for spec in context.specialists:
                tools = ", ".join(spec["tool_whitelist"][:3])
                if len(spec["tool_whitelist"]) > 3:
                    tools += f" (+{len(spec['tool_whitelist']) - 3} more)"
                sections.append(f"- **{spec['name']}**: {spec['description']} [工具: {tools}]")

        if context.equipped_skills:
            sections.append(self.format_equipped_skills_for_prompt(context.equipped_skills))

        if context.context_warnings:
            sections.append("## 上下文加载警告")
            sections.extend(f"- {warning}" for warning in context.context_warnings)

        if context.is_cold_start:
            sections.insert(
                0,
                "（这是你与用户的首次对话或大脑记忆为空。请主动了解用户，可以问 1-2 个问题来建立初步了解。）",
            )

        return "\n\n".join(sections) if sections else ""

    @staticmethod
    def format_equipped_skills_for_prompt(equipped_skills: list[dict]) -> str:
        lines = [
            "## 你已装备的方法论清单",
            "",
            "当用户请求触发某条方法论的 trigger_conditions 时，调用 "
            "`load_skill_methodology(skill_id)` 拉取完整正文后再执行。不要无差别加载全部方法论。",
            "",
            "equipped_skills:",
        ]
        for skill in equipped_skills:
            lines.extend(
                [
                    f"  - id: {skill.get('skill_id', '')}",
                    f"    name: {skill.get('name', '')}",
                    f"    description: {skill.get('description', '')}",
                    "    trigger_conditions:",
                ]
            )
            triggers = skill.get("trigger_conditions") or []
            for trigger in triggers:
                lines.append(f"      - {trigger}")
            if not triggers:
                lines.append("      - （未配置）")
        return "\n".join(lines)

    @staticmethod
    def _format_entry_id_note(entry: dict) -> str:
        entry_id = str(entry.get("entry_id") or "").strip()
        return f"[entry_id: {entry_id}] " if entry_id else ""
