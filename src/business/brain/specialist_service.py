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

from src.data.repositories import ToolRepository
from src.data.repos.specialist_repository import SpecialistRepository
from src.utils.events import emit


def parse_tool_whitelist(raw) -> list[str]:
    """Parse a tool_whitelist value from JSON string or list to a clean list of strings."""
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


logger = logging.getLogger(__name__)

RECRUITMENT_DELEGATION_THRESHOLD = 3


class SpecialistService:
    """专员业务逻辑服务"""

    def __init__(self, repo: Optional[SpecialistRepository] = None):
        self._repo = repo or SpecialistRepository()

    def create_specialist(
        self,
        name: str,
        description: str,
        role_definition: str,
        tool_whitelist: list[str],
        origin: str = "user_conversation",
        reason: str = "",
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

        Returns:
            创建的专员信息 dict

        Raises:
            ValueError: 名称已存在或白名单验证失败
        """
        # 检查名称唯一性
        existing = self._repo.get_specialist_by_name(name)
        if existing is not None:
            raise ValueError(f"专员名称已存在: {name}")

        # 验证白名单子集
        self._validate_whitelist(tool_whitelist)

        specialist_id = self._repo.create_specialist(
            name=name,
            description=description,
            role_definition=role_definition,
            tool_whitelist=tool_whitelist,
            origin=origin,
            reason=reason,
        )

        specialist = self._repo.get_specialist(specialist_id)
        emit("brain_specialist_changed", specialist_id=specialist_id, operation="create")

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
    ) -> dict:
        """更新专员信息，自动创建新版本记录。"""
        specialist = self._repo.get_specialist(specialist_id)
        if specialist is None:
            raise ValueError(f"专员不存在: {specialist_id}")

        # 如果修改了名称，检查新名称唯一性
        if name is not None and name != specialist.name:
            existing = self._repo.get_specialist_by_name(name)
            if existing is not None:
                raise ValueError(f"专员名称已存在: {name}")

        # 如果修改了白名单，验证子集
        if tool_whitelist is not None:
            self._validate_whitelist(tool_whitelist)

        success = self._repo.update_specialist(
            specialist_id=specialist_id,
            name=name,
            description=description,
            role_definition=role_definition,
            tool_whitelist=tool_whitelist,
            changed_by=changed_by,
            change_reason=change_reason,
        )

        if not success:
            raise ValueError(f"更新专员失败: {specialist_id}")

        updated = self._repo.get_specialist(specialist_id)
        self._record_specialist_feedback(
            operation="edit",
            specialist_id=specialist_id,
            context_summary=self._specialist_feedback_summary(specialist),
        )
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
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """列出专员，返回 (specialist_dicts, total_count)。"""
        specialists, total = self._repo.list_specialists(
            active_only=active_only,
            limit=limit,
            offset=offset,
        )
        return [self._to_dict(s) for s in specialists], total

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
        """Return the assistant skill pool used as the specialist whitelist superset."""
        tool_repo = ToolRepository()
        try:
            all_tools = tool_repo.get_all_published()
        finally:
            tool_repo.close()
        removed_identifiers = self._removed_skill_pool_identifiers()
        return [
            {
                "tool_id": getattr(tool, "tool_id", ""),
                "name": getattr(tool, "tool_name", "") or getattr(tool, "name", ""),
                "description": getattr(tool, "description", ""),
            }
            for tool in all_tools
            if getattr(tool, "tool_id", "") not in removed_identifiers
            and (getattr(tool, "tool_name", "") or getattr(tool, "name", ""))
            not in removed_identifiers
        ]

    # ------------------------------------------------------------------
    # Auto Recruitment (T102)
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

        threshold = self._recruitment_threshold()
        signals = brain_repo.get_recruitment_signals_for_scan(threshold)

        created: list[dict] = []
        for signal in signals:
            try:
                specialist_dict = self._recruit_from_signal(signal)
                if specialist_dict is not None:
                    created.append(specialist_dict)
            except Exception as e:
                logger.error("Auto-recruitment failed for signal %s: %s", signal.signal_id, e)

        return created

    def _recruit_from_signal(self, signal) -> Optional[dict]:
        """
        从招募信号生成专员。使用模式摘要直接构建专员定义。

        Args:
            signal: BrainRecruitmentSignal ORM 对象

        Returns:
            创建的专员信息 dict，如果跳过则返回 None
        """
        from src.data.repos.brain_repository import BrainRepository

        task_pattern = signal.task_pattern
        summaries = self._decode_examples(signal.example_delegation_summaries)
        reason = f"检测到持续委托模式: {task_pattern} (委托次数: {signal.delegation_count})"

        name = self._generate_specialist_name(task_pattern)
        description = f"自动招募的专员，负责处理: {task_pattern}"
        role_definition = self._generate_role_definition(task_pattern, summaries)
        feedback_guidance = self._recent_feedback_guidance()
        if feedback_guidance:
            role_definition += "\n\n近期用户反馈参考：\n" + feedback_guidance

        specialist_dict = self.create_specialist(
            name=name,
            description=description,
            role_definition=role_definition,
            tool_whitelist=[],
            origin="auto_recruitment",
            reason=reason,
        )

        # 更新 signal 记录关联 specialist_id
        brain_repo = BrainRepository()
        brain_repo.mark_recruitment_signal_consumed(
            signal.signal_id,
            specialist_dict["specialist_id"],
        )

        return specialist_dict

    @staticmethod
    def _generate_specialist_name(task_pattern: str) -> str:
        """根据任务模式生成专员名称。"""
        pattern = task_pattern[:50]
        return f"{pattern}专员"

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

            return int(get_unified_config().get_brain_recruitment_min_delegation_count())
        except Exception:
            return RECRUITMENT_DELEGATION_THRESHOLD

    def _recent_feedback_guidance(self) -> str:
        try:
            from src.data.repos.brain_repository import BrainRepository

            signals = BrainRepository().get_recent_feedback_signals(zone="specialist", limit=5)
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
    def _record_specialist_feedback(
        *,
        operation: str,
        specialist_id: str,
        context_summary: str,
    ) -> None:
        try:
            from src.data.repos.brain_repository import BrainRepository

            BrainRepository().create_feedback_signal(
                zone="specialist",
                operation=operation,
                target_id=specialist_id,
                context_summary=context_summary,
            )
        except Exception as exc:
            logger.warning("Failed to record specialist feedback signal: %s", exc)

    # ------------------------------------------------------------------
    # Skill Pool Management (T117)
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

        for specialist_info in affected:
            specialist_id = specialist_info["specialist_id"]
            try:
                current_whitelist = specialist_info["tool_whitelist"]
                new_whitelist = [t for t in current_whitelist if t not in identifiers]
                self.update_specialist(
                    specialist_id=specialist_id,
                    tool_whitelist=new_whitelist,
                    changed_by="system_skill_pool_removal",
                    change_reason=f"技能 {tool_id} 已从技能池移除，自动裁剪白名单",
                )
                pruned_specialists.append(specialist_info)
            except Exception as e:
                logger.error(
                    "Failed to prune tool %s from specialist %s: %s",
                    tool_id,
                    specialist_id,
                    e,
                )

        self._mark_skill_pool_removed(tool_id, identifiers)
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
        specialists_by_id: dict[str, dict] = {
            specialist["specialist_id"]: specialist
            for specialist in self.list_specialists(active_only=True)[0]
        }
        repo = SpecialistRepository()
        try:
            for specialist in repo.list_specialists(active_only=True)[0]:
                specialist_dict = self._to_dict(specialist)
                specialists_by_id[specialist_dict["specialist_id"]] = specialist_dict
        finally:
            repo.close()
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
        except Exception:
            logger.warning("Failed to resolve skill identifiers for %s", tool_id_or_name)
        return {item for item in identifiers if item}

    @staticmethod
    def _removed_skill_pool_identifiers() -> set[str]:
        try:
            from src.data.repos.brain_repository import BrainRepository

            repo = BrainRepository()
            try:
                return repo.get_removed_skill_pool_identifiers()
            finally:
                repo.close()
        except Exception as exc:
            logger.warning("Failed to load skill-pool exclusions: %s", exc)
            return set()

    @staticmethod
    def _mark_skill_pool_removed(tool_id: str, identifiers: set[str]) -> None:
        from src.data.repos.brain_repository import BrainRepository

        repo = BrainRepository()
        try:
            repo.mark_skill_pool_removed(tool_id, identifiers)
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
        published_names -= self._removed_skill_pool_identifiers()

        invalid_tools = [t for t in tool_whitelist if t not in published_names]
        if invalid_tools:
            raise ValueError(f"白名单包含不存在的工具: {', '.join(invalid_tools)}")

    @staticmethod
    def _to_dict(specialist) -> dict:
        """将 ORM 对象转为 API 响应 dict。"""
        return {
            "specialist_id": getattr(specialist, "specialist_id", ""),
            "name": getattr(specialist, "name", ""),
            "description": getattr(specialist, "description", ""),
            "role_definition": getattr(specialist, "role_definition", ""),
            "tool_whitelist": parse_tool_whitelist(getattr(specialist, "tool_whitelist", "[]")),
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
            "changed_by": getattr(version, "changed_by", ""),
            "change_reason": getattr(version, "change_reason", None),
            "changed_at": getattr(version, "changed_at", None),
        }
