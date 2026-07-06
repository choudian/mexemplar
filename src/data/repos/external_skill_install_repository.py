"""Repository for external_skill_installs — 技能商店安装记录（029）。"""

from __future__ import annotations

from src.data.models_sqlite import ExternalSkillInstall
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id


class ExternalSkillInstallRepository(BaseRepository):
    """CRUD for external skill install records.

    "活跃安装" = ``uninstalled_at IS NULL``；卸载置时间戳软记录（审计保留），
    受管文件目录的物理清理由业务层负责。
    """

    def create(
        self,
        *,
        skill_id: str,
        source_type: str,
        source_ref: str,
        source_url: str,
        local_dir: str,
    ) -> ExternalSkillInstall:
        row = ExternalSkillInstall(
            install_id=generate_id("esi"),
            skill_id=skill_id,
            source_type=source_type,
            source_ref=source_ref,
            source_url=source_url,
            local_dir=local_dir,
            installed_at=utc_now_naive().isoformat(),
        )
        self.session.add(row)
        self._commit()
        return row

    def get_by_install_id(self, install_id: str) -> ExternalSkillInstall | None:
        return (
            self.session.query(ExternalSkillInstall)
            .filter(ExternalSkillInstall.install_id == install_id)
            .one_or_none()
        )

    def get_active_by_source(
        self, source_type: str, source_ref: str
    ) -> ExternalSkillInstall | None:
        return (
            self.session.query(ExternalSkillInstall)
            .filter(
                ExternalSkillInstall.source_type == source_type,
                ExternalSkillInstall.source_ref == source_ref,
                ExternalSkillInstall.uninstalled_at.is_(None),
            )
            .one_or_none()
        )

    def get_active_by_skill_id(self, skill_id: str) -> ExternalSkillInstall | None:
        return (
            self.session.query(ExternalSkillInstall)
            .filter(
                ExternalSkillInstall.skill_id == skill_id,
                ExternalSkillInstall.uninstalled_at.is_(None),
            )
            .one_or_none()
        )

    def list_active(self) -> list[ExternalSkillInstall]:
        return (
            self.session.query(ExternalSkillInstall)
            .filter(ExternalSkillInstall.uninstalled_at.is_(None))
            .order_by(ExternalSkillInstall.installed_at.desc())
            .all()
        )

    def mark_uninstalled(self, install_id: str) -> bool:
        """置卸载时间戳；已卸载或不存在返回 False（条件 UPDATE + rowcount）。"""
        updated = (
            self.session.query(ExternalSkillInstall)
            .filter(
                ExternalSkillInstall.install_id == install_id,
                ExternalSkillInstall.uninstalled_at.is_(None),
            )
            .update(
                {"uninstalled_at": utc_now_naive().isoformat()},
                synchronize_session=False,
            )
        )
        self._commit()
        return updated == 1

    def delete_row(self, install_id: str) -> None:
        """物理删除（仅供安装失败逆序清理使用，正常卸载走 mark_uninstalled）。"""
        self.session.query(ExternalSkillInstall).filter(
            ExternalSkillInstall.install_id == install_id
        ).delete(synchronize_session=False)
        self._commit()
