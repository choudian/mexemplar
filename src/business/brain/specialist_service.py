"""
SpecialistService -- 专员 CRUD + 白名单验证 + 用户对话创建 + 自动招募

业务逻辑层：
- 创建/更新/删除专员
- 白名单子集验证（tool_whitelist 必须是技能池的子集）
- 专员查询
- 持续委托模式扫描 + 自动招募
- 技能池强制移除 + 白名单裁剪
"""

import json
import logging
from typing import Optional

from src.business.brain.builtin_tools import BUILTIN_TOOL_CATALOG
from src.data.repositories import ToolRepository
from src.data.repos.specialist_repository import SpecialistRepository
from src.utils.events import emit


class WhitelistValidationError(ValueError):
    """白名单验证失败：工具不在技能池中。"""


class CompositionValidationError(ValueError):
    """技能组合验证失败：组合不存在、未发布或当前不可用。"""


def _parse_identifier_list(raw) -> list[str]:
    """Parse a JSON/list identifier collection into a stable, de-duplicated list."""
    if isinstance(raw, list):
        parsed = raw
    elif not raw:
        return []
    else:
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(parsed, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        identifier = str(item).strip()
        if identifier and identifier not in seen:
            result.append(identifier)
            seen.add(identifier)
    return result


def parse_tool_whitelist(raw) -> list[str]:
    """Parse a tool_whitelist value from JSON string or list."""
    return _parse_identifier_list(raw)


def parse_composition_ids(raw) -> list[str]:
    """Parse specialist skill-composition assignments from JSON string or list."""
    return _parse_identifier_list(raw)


logger = logging.getLogger(__name__)

RECRUITMENT_DELEGATION_THRESHOLD = 3


class SpecialistService:
    """专员业务逻辑服务"""

    def __init__(
        self,
        repo: Optional[SpecialistRepository] = None,
        composition_service=None,
    ):
        self._repo = repo or SpecialistRepository()
        self._composition_service = composition_service

    def _get_composition_service(self):
        if self._composition_service is None:
            from src.business.services.skill_composition.service import SkillCompositionService

            self._composition_service = SkillCompositionService()
        return self._composition_service

    def create_specialist(
        self,
        name: str,
        description: str,
        role_definition: str,
        tool_whitelist: list[str],
        origin: str = "user_conversation",
        reason: str = "",
        caller_type: Optional[str] = None,
        role_kind: str = "executor",
        composition_ids: Optional[list[str]] = None,
    ) -> dict:
        """
        创建新专员。

        Args:
            name: 专员名称（唯一）
            description: 专员描述
            role_definition: 角色定义
            tool_whitelist: 工具白名单
            origin: 创建来源（auto_recruitment / user_conversation / user_management_ui）
            reason: 创建原因
            caller_type: UI/API 调用者类型；提供时由 Service 生成审计来源和默认原因
            role_kind: 角色类型（executor / planner）。024 新增。
            composition_ids: 专员可激活的已发布技能组合 ID

        Returns:
            创建的专员信息 dict

        Raises:
            ValueError: 名称已存在或白名单验证失败
        """
        if caller_type is not None:
            origin = caller_type
            reason = reason or self._default_audit_reason(caller_type, operation="create")
        return self._create_specialist_record(
            name=name,
            description=description,
            role_definition=role_definition,
            tool_whitelist=tool_whitelist,
            composition_ids=composition_ids or [],
            origin=origin,
            reason=reason,
            commit=True,
            emit_events=True,
            role_kind=role_kind,
        )

    def _create_specialist_record(
        self,
        *,
        name: str,
        description: str,
        role_definition: str,
        tool_whitelist: list[str],
        composition_ids: list[str],
        origin: str,
        reason: str,
        commit: bool,
        emit_events: bool,
        role_kind: str = "executor",
    ) -> dict:
        """Create a specialist using this service repository and optional outer transaction."""
        # 检查名称唯一性
        existing = self._repo.get_specialist_by_name(name)
        if existing is not None:
            raise ValueError(f"专员名称已存在: {name}")

        # 验证白名单子集
        self._validate_whitelist(tool_whitelist)
        normalized_composition_ids = parse_composition_ids(composition_ids)
        self._validate_compositions(normalized_composition_ids)

        try:
            specialist_id = self._repo.create_specialist(
                name=name,
                description=description,
                role_definition=role_definition,
                tool_whitelist=tool_whitelist,
                composition_ids=normalized_composition_ids,
                origin=origin,
                reason=reason,
                commit=False,
                role_kind=role_kind,
            )
            specialist = self._repo.get_specialist(specialist_id)
            from src.business.brain.skill_equipment_service import SkillEquipmentService

            equipped_skill_ids = SkillEquipmentService(
                session=self._repo.session
            ).default_equip_all(
                specialist_id,
                commit=False,
                emit_events=False,
            )
        except Exception as exc:
            if commit:
                self._repo.session.rollback()
            logger.error("默认装备方法论失败，已取消创建 Specialist: %s", exc)
            raise
        if commit:
            self._repo.session.commit()
        if emit_events:
            emit("brain_specialist_changed", specialist_id=specialist_id, operation="create")
            for skill_id in equipped_skill_ids:
                emit(
                    "brain_skill_equipment_changed",
                    change_type="default_propagate",
                    entity_type="specialist",
                    entity_id=specialist_id,
                    skill_id=skill_id,
                    unequipped_reason=None,
                )

        return self._to_dict(specialist)

    def update_specialist(
        self,
        specialist_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        role_definition: Optional[str] = None,
        tool_whitelist: Optional[list[str]] = None,
        changed_by: str = "user",
        change_reason: Optional[str] = None,
        caller_type: Optional[str] = None,
        composition_ids: Optional[list[str]] = None,
    ) -> dict:
        """更新专员信息，自动创建新版本记录。"""
        if caller_type is not None:
            changed_by = caller_type
            change_reason = change_reason or self._default_audit_reason(
                caller_type,
                operation="update",
            )
        specialist = self._repo.get_specialist(specialist_id)
        if specialist is None:
            raise KeyError("specialist_not_found")

        # 如果修改了名称（忽略大小写后确实不同），检查新名称唯一性
        if name is not None and name.lower() != specialist.name.lower():
            existing = self._repo.get_specialist_by_name(name)
            if existing is not None:
                raise ValueError(f"专员名称已存在: {name}")

        # 如果修改了白名单，验证子集
        if tool_whitelist is not None:
            self._validate_whitelist(tool_whitelist)
        normalized_composition_ids = None
        if composition_ids is not None:
            normalized_composition_ids = parse_composition_ids(composition_ids)
            self._validate_compositions(normalized_composition_ids)

        success = self._repo.update_specialist(
            specialist_id=specialist_id,
            name=name,
            description=description,
            role_definition=role_definition,
            tool_whitelist=tool_whitelist,
            composition_ids=normalized_composition_ids,
            changed_by=changed_by,
            change_reason=change_reason,
        )

        if not success:
            raise KeyError("specialist_not_found")

        updated = self._repo.get_specialist(specialist_id)
        self._record_specialist_feedback(
            operation="edit",
            specialist_id=specialist_id,
            context_summary=self._specialist_feedback_summary(specialist),
        )
        emit("brain_specialist_changed", specialist_id=specialist_id, operation="update")
        return self._to_dict(updated)

    def delete_specialist(self, specialist_id: str) -> bool:
        """软删除专员，保留版本历史供管理界面追溯。"""
        specialist = self._repo.get_specialist(specialist_id)
        success = self._repo.deactivate_specialist(specialist_id)
        if success and specialist is not None:
            self._record_specialist_feedback(
                operation="delete",
                specialist_id=specialist_id,
                context_summary=self._specialist_feedback_summary(specialist),
            )
            emit("brain_specialist_changed", specialist_id=specialist_id, operation="deactivate")
        return success

    def get_specialist(self, specialist_id: str) -> Optional[dict]:
        """按 ID 查询专员。"""
        specialist = self._repo.get_specialist(specialist_id)
        if specialist is None:
            return None
        return self._to_dict(specialist)

    def get_specialist_by_name(self, name: str) -> Optional[dict]:
        """按名称查询专员。"""
        specialist = self._repo.get_specialist_by_name(name)
        if specialist is None:
            return None
        return self._to_dict(specialist)

    def list_specialists(
        self,
        active_only: bool = True,
        limit: Optional[int] = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """列出专员，返回 (specialist_dicts, total_count)。"""
        specialists, total = self._repo.list_specialists(
            active_only=active_only,
            limit=limit,
            offset=offset,
        )
        return [self._to_dict(s) for s in specialists], total

    def seed_builtin_specialists(self) -> None:
        """启动时补齐内置专员，并把用户没动过的升级到最新定义。

        新装的应用必须自带这些专员，否则"外部 Coding"这类内置能力组合会变成
        十一个没有合法执行者的工具——只有配置了该组合的固定 executor 专员才被
        允许激活它们。

        三条规则：

        - **没有就建。**
        - **用户没改过就升级。** 提示词改进要能到达已装用户手里，否则等于
          只有重装才能拿到修复。
        - **用户改过就再也不动。** 判据是种子当时写入的内容摘要与当前内容是否
          仍然一致；不一致即视为用户接管，此后升级一律跳过。

        软删除的内置专员算"已存在"：停用是用户的决定，不能每次启动都撤销。
        但其定义仍会被升级，以便重新启用时拿到的是当前版本。
        """
        from src.business.brain.specialist_presets import (
            compute_fingerprint,
            load_specialist_presets,
        )

        for preset in load_specialist_presets():
            try:
                self._seed_one_specialist(preset, compute_fingerprint)
            except Exception:
                # 种子失败不能拖垮启动：其余功能仍可用，用户也能手工建。
                logger.warning(
                    "[Specialist] 内置专员种子失败: %s", preset.name, exc_info=True
                )

    def _seed_one_specialist(self, preset, compute_fingerprint) -> None:
        existing = self._repo.get_specialist_by_preset_key(preset.key)
        if existing is None:
            # 本次刚认领的专员只记归属，不在同一轮里顺手升级：认领时写入的指纹
            # 就是它当前的内容，内容与种子不同即说明是用户自建的同名专员，
            # 继续走升级会当场覆盖掉人家的定义。
            self._adopt_untagged_preset(preset, compute_fingerprint)
            if self._repo.get_specialist_by_preset_key(preset.key) is None:
                self._create_preset_specialist(preset)
            return

        current = compute_fingerprint(
            role_definition=existing.role_definition or "",
            description=existing.description or "",
            composition_ids=parse_composition_ids(existing.composition_ids or "[]"),
        )
        if current != existing.preset_fingerprint:
            logger.debug(
                "[Specialist] 内置专员 %s 已被用户修改，跳过升级", preset.name
            )
            return

        target = preset.fingerprint()
        if current == target:
            return

        self._repo.update_specialist(
            specialist_id=existing.specialist_id,
            description=preset.description,
            role_definition=preset.load_role_definition(),
            composition_ids=list(preset.composition_ids),
            changed_by="system",
            change_reason="内置专员定义升级",
        )
        self._repo.mark_as_preset(existing.specialist_id, preset.key, target)
        logger.info("[Specialist] 已升级内置专员定义: %s", preset.name)

    def _adopt_untagged_preset(self, preset, compute_fingerprint):
        """认领同名但还没打过种子标记的专员。

        覆盖两种情况：v35 之前手工建的，以及用户自己建了同名专员。前者内容与
        当前种子一致，认领后即可继续接收升级；后者内容不同，认领只是记下归属，
        指纹按其当前内容写入，因而此后被视为用户接管、不再自动更新。
        """
        existing = self._repo.get_specialist_by_name(preset.name)
        if existing is None:
            return None
        fingerprint = compute_fingerprint(
            role_definition=existing.role_definition or "",
            description=existing.description or "",
            composition_ids=parse_composition_ids(existing.composition_ids or "[]"),
        )
        self._repo.mark_as_preset(existing.specialist_id, preset.key, fingerprint)
        logger.info("[Specialist] 已认领同名专员为内置: %s", preset.name)
        return self._repo.get_specialist_by_preset_key(preset.key)

    def _create_preset_specialist(self, preset) -> None:
        result = self.create_specialist(
            name=preset.name,
            description=preset.description,
            role_definition=preset.load_role_definition(),
            tool_whitelist=list(preset.tool_whitelist),
            origin="user_management_ui",
            reason=preset.reason,
            role_kind=preset.role_kind,
            composition_ids=list(preset.composition_ids),
        )
        specialist_id = result.get("specialist_id")
        if not specialist_id:
            logger.warning(
                "[Specialist] 内置专员未创建: %s (%s)",
                preset.name,
                result.get("message") or result.get("error"),
            )
            return
        self._repo.mark_as_preset(specialist_id, preset.key, preset.fingerprint())
        logger.info("[Specialist] 已创建内置专员: %s", preset.name)

    def get_version_history(
        self,
        specialist_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """获取专员的版本历史。"""
        versions = self._repo.get_version_history(
            specialist_id=specialist_id,
            limit=limit,
            offset=offset,
        )
        return [self._version_to_dict(v) for v in versions]

    def list_skill_pool(self) -> list[dict]:
        """Return the assistant skill pool: built-in tools followed by user-created tools."""
        with ToolRepository() as tool_repo:
            all_tools = tool_repo.get_all_published()
            removed_identifiers = self._removed_skill_pool_identifiers(session=tool_repo.session)
        user_tools = [
            {
                "tool_id": getattr(tool, "tool_id", ""),
                "name": getattr(tool, "tool_name", "") or getattr(tool, "name", ""),
                "description": getattr(tool, "description", ""),
                "is_builtin": False,
            }
            for tool in all_tools
            if getattr(tool, "tool_id", "") not in removed_identifiers
            and (getattr(tool, "tool_name", "") or getattr(tool, "name", ""))
            not in removed_identifiers
        ]
        builtin_tools = [{**entry, "is_builtin": True} for entry in BUILTIN_TOOL_CATALOG]
        return builtin_tools + user_tools

    # ------------------------------------------------------------------
    # Auto Recruitment
    # ------------------------------------------------------------------

    def scan_and_recruit(self) -> list[dict]:
        """
        扫描 brain_recruitment_signals 表，找出达到阈值的委托模式，
        使用 LLM 生成专员定义并创建专员。

        Returns:
            新创建的专员列表
        """
        from src.data.repos.brain_repository import BrainRepository

        try:
            brain_repo = BrainRepository()
        except ImportError:
            return []

        try:
            threshold = self._recruitment_threshold()
            signals = brain_repo.get_recruitment_signals_for_scan(threshold)

            created: list[dict] = []
            for signal in signals:
                try:
                    specialist_dict = self._recruit_from_signal(signal, brain_repo=brain_repo)
                    if specialist_dict is not None:
                        created.append(specialist_dict)
                except Exception as e:
                    logger.error("Auto-recruitment failed for signal %s: %s", signal.signal_id, e)

            return created
        finally:
            brain_repo.close()

    def ensure_planner_specialist(self) -> dict:
        """024: 确保规划专员存在（幂等）。若不存在则自动注册一个默认规划专员。

        首版用配置/手动注册一个 planner 专员（避免依赖信号阈值冷启动），
        后续接 brain 累计信号自动招募。
        """
        from src.data.unified_config import get_unified_config

        config = get_unified_config()
        planner_name = config.get_assistant_tasks_planner_specialist_name()

        existing = self._repo.get_specialist_by_name(planner_name)
        if existing is not None:
            return {
                "specialist_id": existing.specialist_id,
                "name": existing.name,
                "role_kind": existing.role_kind,
            }

        # 角色定义取自 PLANNER 种子，与 seed_builtin_specialists 同源——两条路径
        # 各写一份文案的话，先跑到的那条会决定 planner 拿到哪个版本。创建后打上
        # 种子标记，使其此后能正常接收定义升级。
        from src.business.brain.specialist_presets import PLANNER

        created = self.create_specialist(
            name=planner_name,
            description=PLANNER.description,
            role_definition=PLANNER.load_role_definition(),
            tool_whitelist=list(PLANNER.tool_whitelist),
            origin="auto_planner_registration",
            reason=PLANNER.reason,
            role_kind="planner",
        )
        specialist_id = created.get("specialist_id")
        if specialist_id and planner_name == PLANNER.name:
            self._repo.mark_as_preset(specialist_id, PLANNER.key, PLANNER.fingerprint())
        return created

    def _recruit_from_signal(self, signal, brain_repo) -> Optional[dict]:
        """
        从招募信号生成专员。使用模式摘要直接构建专员定义。

        Args:
            signal: BrainRecruitmentSignal ORM 对象
            brain_repo: 调用方持有的 BrainRepository，共享同一事务

        Returns:
            创建的专员信息 dict，如果跳过则返回 None
        """
        task_pattern = signal.task_pattern
        summaries = self._decode_examples(signal.example_delegation_summaries)
        reason = f"检测到持续委托模式: {task_pattern} (委托次数: {signal.delegation_count})"

        name = self._generate_specialist_name(task_pattern)
        description = f"自动招募的专员，负责处理: {task_pattern}"
        role_definition = self._generate_role_definition(task_pattern, summaries)
        feedback_guidance = self._recent_feedback_guidance(brain_repo=brain_repo)
        if feedback_guidance:
            role_definition += "\n\n近期用户反馈参考：\n" + feedback_guidance

        specialist_repo = SpecialistRepository(session=brain_repo.session)
        existing = specialist_repo.get_specialist_by_name(name)
        if existing is not None:
            try:
                brain_repo.mark_recruitment_signal_consumed(
                    signal.signal_id,
                    existing.specialist_id,
                    commit=False,
                )
                brain_repo.session.commit()
            except Exception as exc:
                brain_repo.session.rollback()
                logger.error(
                    "Auto-recruitment signal consume failed for existing specialist %s: %s",
                    getattr(signal, "signal_id", ""),
                    exc,
                    exc_info=True,
                )
                raise
            logger.info(
                "Auto-recruitment signal %s consumed by existing specialist %s",
                getattr(signal, "signal_id", ""),
                existing.specialist_id,
            )
            return None

        recruitment_service = SpecialistService(repo=specialist_repo)
        try:
            specialist_dict = recruitment_service._create_specialist_record(
                name=name,
                description=description,
                role_definition=role_definition,
                tool_whitelist=[],
                composition_ids=[],
                origin="auto_recruitment",
                reason=reason,
                commit=False,
                emit_events=False,
            )
            brain_repo.mark_recruitment_signal_consumed(
                signal.signal_id,
                specialist_dict["specialist_id"],
                commit=False,
            )
            brain_repo.session.commit()
        except Exception as exc:
            brain_repo.session.rollback()
            logger.error(
                "Auto-recruitment transaction failed for signal %s: %s",
                getattr(signal, "signal_id", ""),
                exc,
                exc_info=True,
            )
            raise

        emit(
            "brain_specialist_changed",
            specialist_id=specialist_dict["specialist_id"],
            operation="create",
        )

        return specialist_dict

    @staticmethod
    def _generate_specialist_name(task_pattern: str) -> str:
        """根据任务模式生成专员名称。添加短哈希后缀避免截断碰撞。"""
        import hashlib

        pattern = task_pattern[:50]
        suffix = hashlib.sha256(task_pattern.encode()).hexdigest()[:6]
        return f"{pattern}专员_{suffix}"

    @staticmethod
    def _generate_role_definition(task_pattern: str, summaries: list[str]) -> str:
        """根据任务模式和摘要生成角色定义。"""
        definition = f"你是一名专门负责「{task_pattern}」任务的专员。\n\n"
        definition += "你的职责是高效、准确地完成主助理分配给你的任务。\n"
        if summaries:
            definition += "\n历史任务示例:\n"
            for line in summaries[:3]:
                line = line.strip()
                if line:
                    definition += f"- {line}\n"
        return definition

    @staticmethod
    def _decode_examples(raw: Optional[str]) -> list[str]:
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return [line.strip() for line in str(raw).splitlines() if line.strip()]
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [str(parsed).strip()] if str(parsed).strip() else []

    @staticmethod
    def _recruitment_threshold() -> int:
        try:
            from src.data.unified_config import get_unified_config

            config = get_unified_config()
        except (ImportError, AttributeError) as exc:
            logger.warning("Failed to load recruitment config, using default: %s", exc)
            return RECRUITMENT_DELEGATION_THRESHOLD
        try:
            return int(config.get_brain_recruitment_min_delegation_count())
        except (AttributeError, TypeError, ValueError) as exc:
            logger.warning("Invalid recruitment threshold config, using default: %s", exc)
            return RECRUITMENT_DELEGATION_THRESHOLD

    def _recent_feedback_guidance(self, brain_repo=None) -> str:
        try:
            if brain_repo is not None:
                signals = brain_repo.get_recent_feedback_signals(zone="specialist", limit=5)
            else:
                from src.data.repos.brain_repository import BrainRepository

                owned = BrainRepository()
                try:
                    signals = owned.get_recent_feedback_signals(zone="specialist", limit=5)
                finally:
                    owned.close()
        except Exception as exc:
            logger.warning("Failed to load feedback signals for recruitment prompt: %s", exc)
            return ""
        lines = []
        for signal in signals:
            operation = getattr(signal, "operation", "")
            summary = getattr(signal, "context_summary", "")
            if operation and summary:
                lines.append(f"- [{operation}] {summary}")
        return "\n".join(lines)

    @staticmethod
    def _specialist_feedback_summary(specialist) -> str:
        name = str(getattr(specialist, "name", "") or "")
        description = str(getattr(specialist, "description", "") or "")
        reason = str(getattr(specialist, "reason", "") or "")
        parts = [part for part in (name, description, reason) if part]
        return " | ".join(parts)[:500] or "specialist changed"

    @staticmethod
    def _default_audit_reason(caller_type: str, *, operation: str) -> str:
        if caller_type != "user_management_ui":
            return ""
        if operation == "create":
            return "通过管理界面创建"
        if operation == "update":
            return "通过管理界面更新"
        return ""

    @staticmethod
    def _record_specialist_feedback(
        *,
        operation: str,
        specialist_id: str,
        context_summary: str,
    ) -> None:
        try:
            from src.data.repos.brain_repository import BrainRepository

            fb_repo = BrainRepository()
            try:
                fb_repo.create_feedback_signal(
                    zone="specialist",
                    operation=operation,
                    target_id=specialist_id,
                    context_summary=context_summary,
                )
            finally:
                fb_repo.close()
        except Exception as exc:
            logger.warning("Failed to record specialist feedback signal: %s", exc)

    # ------------------------------------------------------------------
    # Skill Pool Management
    # ------------------------------------------------------------------

    def force_remove_skill_from_pool(self, tool_id: str) -> dict:
        """
        从技能池强制移除工具，并自动裁剪所有专员白名单中的引用。

        Returns:
            {"removed": True, "pruned_specialists": [...]} 或
            {"removed": False, "affected_specialists": [...]}
        """
        identifiers = self._skill_identifiers(tool_id)
        affected = self._find_specialists_using_tool(tool_id, identifiers=identifiers)
        pruned_specialists: list[dict] = []

        try:
            for specialist_info in affected:
                specialist_id = specialist_info["specialist_id"]
                current_whitelist = specialist_info["tool_whitelist"]
                new_whitelist = [t for t in current_whitelist if t not in identifiers]
                success = self._repo.update_specialist(
                    specialist_id=specialist_id,
                    tool_whitelist=new_whitelist,
                    changed_by="system_skill_pool_removal",
                    change_reason=f"技能 {tool_id} 已从技能池移除，自动裁剪白名单",
                    commit=False,
                )
                if not success:
                    raise KeyError("specialist_not_found")
                pruned_specialists.append(specialist_info)
            self._mark_skill_pool_removed(
                tool_id,
                identifiers,
                session=self._repo.session,
                commit=False,
            )
            self._repo.session.commit()
        except Exception as exc:
            self._repo.session.rollback()
            logger.error("Failed to force-remove tool %s from skill pool: %s", tool_id, exc)
            raise
        for specialist_info in pruned_specialists:
            emit(
                "brain_specialist_changed",
                specialist_id=specialist_info["specialist_id"],
                operation="update",
            )
        return {
            "removed": True,
            "pruned_specialists": pruned_specialists,
        }

    def remove_skill_from_pool(self, tool_id: str, *, force: bool = False) -> dict:
        """Remove a skill from the assistant skill pool, optionally pruning specialists."""
        identifiers = self._skill_identifiers(tool_id)
        affected = self._find_specialists_using_tool(tool_id, identifiers=identifiers)
        if affected and not force:
            return {
                "removed": False,
                "affected_specialists": affected,
            }
        if force:
            return self.force_remove_skill_from_pool(tool_id)
        self._mark_skill_pool_removed(tool_id, identifiers)
        return {
            "removed": True,
            "pruned_specialists": [],
        }

    def check_skill_in_use(self, tool_id: str) -> list[dict]:
        """检查哪些专员白名单引用了指定工具。"""
        return self._find_specialists_using_tool(
            tool_id, identifiers=self._skill_identifiers(tool_id)
        )

    def _find_specialists_using_tool(
        self,
        tool_id: str,
        *,
        identifiers: Optional[set[str]] = None,
    ) -> list[dict]:
        """查找白名单中包含指定工具的活跃专员。"""
        identifiers = identifiers or {tool_id}
        specialists_by_id: dict[str, dict] = {}
        for specialist in self._repo.list_specialists(active_only=True, limit=None)[0]:
            specialist_dict = self._to_dict(specialist)
            specialists_by_id[specialist_dict["specialist_id"]] = specialist_dict
        affected: list[dict] = []
        for s in specialists_by_id.values():
            whitelist = s.get("tool_whitelist", [])
            if any(item in identifiers for item in whitelist):
                affected.append(
                    {
                        "specialist_id": s["specialist_id"],
                        "name": s["name"],
                        "tool_whitelist": whitelist,
                    }
                )
        return affected

    @staticmethod
    def _skill_identifiers(tool_id_or_name: str) -> set[str]:
        identifiers = {tool_id_or_name}
        try:
            tool_repo = ToolRepository()
            try:
                tool = tool_repo.get_by_id(tool_id_or_name) or tool_repo.get_by_name(
                    tool_id_or_name
                )
            finally:
                tool_repo.close()
            if tool is not None:
                identifiers.add(getattr(tool, "tool_id", ""))
                identifiers.add(getattr(tool, "tool_name", ""))
        except Exception as exc:
            logger.warning(
                "Failed to resolve skill identifiers for %s: %s",
                tool_id_or_name,
                exc,
            )
        return {item for item in identifiers if item}

    @staticmethod
    def _removed_skill_pool_identifiers(session=None) -> set[str]:
        try:
            from src.data.repos.brain_repository import BrainRepository

            with BrainRepository(session=session) as repo:
                return repo.get_removed_skill_pool_identifiers()
        except Exception as exc:
            logger.warning("Failed to load skill-pool exclusions: %s", exc)
            return set()

    @staticmethod
    def _mark_skill_pool_removed(
        tool_id: str,
        identifiers: set[str],
        *,
        session=None,
        commit: bool = True,
    ) -> None:
        from src.data.repos.brain_repository import BrainRepository

        repo = BrainRepository(session=session)
        try:
            repo.mark_skill_pool_removed(tool_id, identifiers, commit=commit)
        finally:
            repo.close()

    def _validate_whitelist(self, tool_whitelist: list[str]) -> None:
        """
        验证白名单是技能池的子集。

        获取所有已发布工具的名称，确保白名单中的每个工具都在技能池中。
        如果工具不在池中，抛出 ValueError。
        """
        if not tool_whitelist:
            return

        tool_repo = ToolRepository()
        try:
            all_tools = tool_repo.get_all_published()
        finally:
            tool_repo.close()
        published_names = {
            identifier
            for tool in all_tools
            for identifier in (getattr(tool, "tool_name", None), getattr(tool, "tool_id", None))
            if identifier
        }
        # 先移除已从技能池移除的工具，再并入 builtin（builtin 不受技能池移除影响）
        published_names -= self._removed_skill_pool_identifiers()
        builtin_names = {
            identifier
            for entry in BUILTIN_TOOL_CATALOG
            for identifier in (entry.get("name"), entry.get("tool_id"))
            if identifier
        }
        published_names |= builtin_names

        invalid_tools = [t for t in tool_whitelist if t not in published_names]
        if invalid_tools:
            raise WhitelistValidationError(f"白名单包含不存在的工具: {', '.join(invalid_tools)}")

    def _validate_compositions(self, composition_ids: list[str]) -> None:
        """Only published, review-clean compositions can become specialist authority."""
        if not composition_ids:
            return
        service = self._get_composition_service()
        invalid: list[str] = []
        for composition_id in composition_ids:
            composition = service.get_composition(composition_id)
            if (
                composition is None
                or getattr(composition, "status", None) != "published"
                or bool(getattr(composition, "needs_review", False))
                or not bool(getattr(composition, "assistant_enabled", False))
            ):
                invalid.append(composition_id)
        if invalid:
            raise CompositionValidationError(f"技能组合不存在或未发布/不可用: {', '.join(invalid)}")

    @staticmethod
    def _to_dict(specialist) -> dict:
        """将 ORM 对象转为 API 响应 dict。"""
        return {
            "specialist_id": getattr(specialist, "specialist_id", ""),
            "name": getattr(specialist, "name", ""),
            "description": getattr(specialist, "description", ""),
            "role_definition": getattr(specialist, "role_definition", ""),
            "tool_whitelist": parse_tool_whitelist(getattr(specialist, "tool_whitelist", "[]")),
            "composition_ids": parse_composition_ids(getattr(specialist, "composition_ids", "[]")),
            "origin": getattr(specialist, "origin", ""),
            "reason": getattr(specialist, "reason", ""),
            "current_version": getattr(specialist, "current_version", 1),
            "is_active": bool(getattr(specialist, "is_active", 1)),
            "created_at": getattr(specialist, "created_at", None),
            "updated_at": getattr(specialist, "updated_at", None),
        }

    @staticmethod
    def _version_to_dict(version) -> dict:
        """将版本 ORM 对象转为 API 响应 dict。"""
        return {
            "version_id": getattr(version, "version_id", ""),
            "specialist_id": getattr(version, "specialist_id", ""),
            "version": getattr(version, "version", 0),
            "name": getattr(version, "name", ""),
            "description": getattr(version, "description", ""),
            "role_definition": getattr(version, "role_definition", ""),
            "tool_whitelist": parse_tool_whitelist(getattr(version, "tool_whitelist", "[]")),
            "composition_ids": parse_composition_ids(getattr(version, "composition_ids", "[]")),
            "changed_by": getattr(version, "changed_by", ""),
            "change_reason": getattr(version, "change_reason", None),
            "changed_at": getattr(version, "changed_at", None),
        }
