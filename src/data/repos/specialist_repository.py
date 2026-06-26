"""
SpecialistRepository -- 专员 + 版本历史数据仓库

负责 BrainSpecialist 和 BrainSpecialistVersion 的 CRUD 操作。
"""

import json
import logging
from enum import StrEnum
from typing import Optional
from src.utils.ids import new_id

from ..models_sqlite import BrainSpecialist, BrainSpecialistVersion
from .base_repository import BaseRepository

logger = logging.getLogger(__name__)


class RoleKind(StrEnum):
    """Specialist role classification (024): executor performs tasks, planner only builds graphs.

    Defined in the data layer to avoid circular imports (task_collaboration.models →
    ui_event_safety_service → chat_service → data.repos → specialist_repository).
    Business code should import from here or from task_collaboration.models (re-exported).
    """
    EXECUTOR = "executor"
    PLANNER = "planner"


class SpecialistRepository(BaseRepository):
    """专员数据仓库"""

    # ------------------------------------------------------------------
    # Specialist CRUD
    # ------------------------------------------------------------------

    def create_specialist(
        self,
        name: str,
        description: str,
        role_definition: str,
        tool_whitelist: list[str],
        origin: str,
        reason: str,
        *,
        commit: bool = True,
        role_kind: str = "executor",
    ) -> str:
        """创建一个新专员，同时创建第一条版本记录。返回 specialist_id。"""
        if role_kind not in (RoleKind.EXECUTOR, RoleKind.PLANNER):
            raise ValueError(
                f"invalid role_kind {role_kind!r}: must be '{RoleKind.EXECUTOR}' or '{RoleKind.PLANNER}'"
            )
        specialist_id = new_id()
        whitelist_json = json.dumps(tool_whitelist, ensure_ascii=False)
        specialist = BrainSpecialist(
            specialist_id=specialist_id,
            name=name,
            description=description,
            role_definition=role_definition,
            tool_whitelist=whitelist_json,
            origin=origin,
            reason=reason,
            current_version=1,
            is_active=True,
            role_kind=role_kind,
        )
        try:
            self.session.add(specialist)
            self.session.flush()

            # 创建版本 1
            version_id = new_id()
            version = BrainSpecialistVersion(
                version_id=version_id,
                specialist_id=specialist_id,
                version=1,
                name=name,
                description=description,
                role_definition=role_definition,
                tool_whitelist=whitelist_json,
                changed_by=origin,
                change_reason=reason,
            )
            self.session.add(version)
            self.session.flush()
            if commit:
                self.session.commit()
                self.session.expire_all()

            logger.info("Specialist 已创建: %s (name=%s)", specialist_id, name)
            return specialist_id
        except Exception as e:
            self.session.rollback()
            logger.error("创建 Specialist 失败: %s", e)
            raise

    def get_specialist(self, specialist_id: str) -> Optional[BrainSpecialist]:
        """按 ID 查询专员。"""
        return (
            self.session.query(BrainSpecialist)
            .filter(BrainSpecialist.specialist_id == specialist_id)
            .first()
        )

    def get_specialist_by_name(self, name: str) -> Optional[BrainSpecialist]:
        """按名称查询活跃专员（大小写不敏感）。软删除专员不参与重名检查。
        Python 侧 lower() 对比以正确处理 Unicode 字符，避免 SQLite lower() 仅支持 ASCII 的限制。
        """
        name_lower = name.lower()
        candidates = (
            self.session.query(BrainSpecialist).filter(BrainSpecialist.is_active.is_(True)).all()
        )
        return next((s for s in candidates if s.name.lower() == name_lower), None)

    def list_specialists(
        self,
        active_only: bool = True,
        limit: Optional[int] = 50,
        offset: int = 0,
    ) -> tuple[list[BrainSpecialist], int]:
        """列出专员，返回 (specialists, total_count)。"""
        query = self.session.query(BrainSpecialist)
        if active_only:
            query = query.filter(BrainSpecialist.is_active.is_(True))

        total = query.count()
        query = query.order_by(BrainSpecialist.created_at.desc()).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        specialists = query.all()
        return specialists, total

    def update_specialist(
        self,
        specialist_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        role_definition: Optional[str] = None,
        tool_whitelist: Optional[list[str]] = None,
        changed_by: str = "user",
        change_reason: Optional[str] = None,
        *,
        commit: bool = True,
    ) -> bool:
        """更新专员信息，同时创建新版本记录。返回 True 表示成功。"""
        specialist = self.get_specialist(specialist_id)
        if specialist is None:
            return False

        new_name = name if name is not None else specialist.name
        new_description = description if description is not None else specialist.description
        new_role = role_definition if role_definition is not None else specialist.role_definition
        new_whitelist_json = (
            json.dumps(tool_whitelist, ensure_ascii=False)
            if tool_whitelist is not None
            else specialist.tool_whitelist
        )

        new_version = specialist.current_version + 1

        try:
            specialist.name = new_name
            specialist.description = new_description
            specialist.role_definition = new_role
            specialist.tool_whitelist = new_whitelist_json
            specialist.current_version = new_version

            version_id = new_id()
            version = BrainSpecialistVersion(
                version_id=version_id,
                specialist_id=specialist_id,
                version=new_version,
                name=new_name,
                description=new_description,
                role_definition=new_role,
                tool_whitelist=new_whitelist_json,
                changed_by=changed_by,
                change_reason=change_reason,
            )
            self.session.add(version)
            if commit:
                self.session.commit()
            else:
                self.session.flush()

            logger.info("Specialist %s updated to version %d", specialist_id, new_version)
            return True
        except Exception as e:
            self.session.rollback()
            logger.error("更新 Specialist 失败: %s", e)
            raise

    def deactivate_specialist(self, specialist_id: str) -> bool:
        """软删除专员（is_active=False）。返回 True 表示成功。"""
        specialist = self.get_specialist(specialist_id)
        if specialist is None:
            return False
        try:
            specialist.is_active = False
            self.session.commit()
            logger.info("Specialist %s deactivated", specialist_id)
            return True
        except Exception as e:
            self.session.rollback()
            logger.error("Deactivate specialist 失败: %s", e)
            raise

    def delete_specialist(self, specialist_id: str) -> bool:
        """Compatibility alias for deleting a specialist via soft delete."""
        return self.deactivate_specialist(specialist_id)

    # ------------------------------------------------------------------
    # Version history
    # ------------------------------------------------------------------

    def get_version_history(
        self,
        specialist_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[BrainSpecialistVersion]:
        """获取专员的版本历史，按版本号降序。"""
        return (
            self.session.query(BrainSpecialistVersion)
            .filter(BrainSpecialistVersion.specialist_id == specialist_id)
            .order_by(BrainSpecialistVersion.version.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

