"""
SkillCompositionRepository -- 技能组合定义与成员关系仓库
"""

import logging
from typing import Dict, Iterable, List, Optional

from ..models_sqlite import SkillComposition, SkillCompositionMember
from .base_repository import BaseRepository
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)


class SkillCompositionRepository(BaseRepository):
    """技能组合仓库"""

    def create(
        self,
        composition: SkillComposition,
        members: Optional[List[SkillCompositionMember]] = None,
    ) -> SkillComposition:
        """创建技能组合及其成员"""
        try:
            self.session.add(composition)
            if members:
                self.session.add_all(members)
            self.session.commit()
            self.session.refresh(composition)
            logger.info(
                f"技能组合已创建: {composition.composition_name} ({composition.composition_id})"
            )
            return composition
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建技能组合失败: {e}")
            raise

    def update(self, composition: SkillComposition) -> SkillComposition:
        """更新技能组合"""
        try:
            composition.updated_at = utc_now_naive()
            self.session.commit()
            self.session.refresh(composition)
            logger.info(
                f"技能组合已更新: {composition.composition_name} ({composition.composition_id})"
            )
            return composition
        except Exception as e:
            self.session.rollback()
            logger.error(f"更新技能组合失败: {e}")
            raise

    def replace_members(
        self,
        composition_id: str,
        members: List[SkillCompositionMember],
    ) -> List[SkillCompositionMember]:
        """替换技能组合成员"""
        try:
            (
                self.session.query(SkillCompositionMember)
                .filter(SkillCompositionMember.composition_id == composition_id)
                .delete(synchronize_session=False)
            )
            if members:
                self.session.add_all(members)
            self.session.commit()
            logger.info(f"技能组合成员已替换: {composition_id}, count={len(members)}")
            return members
        except Exception as e:
            self.session.rollback()
            logger.error(f"替换技能组合成员失败: {e}")
            raise

    def delete(self, composition_id: str) -> bool:
        """删除技能组合及其成员"""
        composition = self.get_by_id(composition_id)
        if composition is None:
            return False
        try:
            (
                self.session.query(SkillCompositionMember)
                .filter(SkillCompositionMember.composition_id == composition_id)
                .delete(synchronize_session=False)
            )
            self.session.delete(composition)
            self.session.commit()
            logger.info(f"技能组合已删除: {composition.composition_name} ({composition_id})")
            return True
        except Exception as e:
            self.session.rollback()
            logger.error(f"删除技能组合失败: {e}")
            raise

    def get_by_id(self, composition_id: str) -> Optional[SkillComposition]:
        """根据 ID 获取技能组合"""
        return (
            self.session.query(SkillComposition)
            .filter(SkillComposition.composition_id == composition_id)
            .first()
        )

    def get_all(self) -> List[SkillComposition]:
        """获取所有技能组合"""
        return (
            self.session.query(SkillComposition)
            .order_by(SkillComposition.updated_at.desc(), SkillComposition.created_at.desc())
            .all()
        )

    def get_members(self, composition_id: str) -> List[SkillCompositionMember]:
        """获取组合成员"""
        return (
            self.session.query(SkillCompositionMember)
            .filter(SkillCompositionMember.composition_id == composition_id)
            .order_by(
                SkillCompositionMember.execution_order.asc().nullslast(),
                SkillCompositionMember.selected_order.asc(),
            )
            .all()
        )

    def get_members_for_compositions(
        self, composition_ids: Iterable[str]
    ) -> Dict[str, List[SkillCompositionMember]]:
        """批量读取多个组合的成员"""
        composition_ids = list(composition_ids)
        if not composition_ids:
            return {}
        rows = (
            self.session.query(SkillCompositionMember)
            .filter(SkillCompositionMember.composition_id.in_(composition_ids))
            .order_by(
                SkillCompositionMember.composition_id.asc(),
                SkillCompositionMember.execution_order.asc().nullslast(),
                SkillCompositionMember.selected_order.asc(),
            )
            .all()
        )
        grouped: Dict[str, List[SkillCompositionMember]] = {cid: [] for cid in composition_ids}
        for row in rows:
            grouped.setdefault(row.composition_id, []).append(row)
        return grouped

    def get_by_name(self, name: str) -> Optional[SkillComposition]:
        """按组合名称精确查询"""
        return (
            self.session.query(SkillComposition)
            .filter(SkillComposition.composition_name == name)
            .first()
        )

    def has_name_conflict(
        self,
        name: str,
        exclude_composition_id: Optional[str] = None,
    ) -> bool:
        """判断是否存在同名技能组合。"""
        query = self.session.query(SkillComposition).filter(
            SkillComposition.composition_name == name
        )
        if exclude_composition_id:
            query = query.filter(SkillComposition.composition_id != exclude_composition_id)
        return query.first() is not None

    def search_published(self, query: str) -> List[SkillComposition]:
        """搜索已发布且可供 Assistant 使用的技能组合"""
        escaped = query.replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        return (
            self.session.query(SkillComposition)
            .filter(
                SkillComposition.status == "published",
                SkillComposition.assistant_enabled.is_(True),
                SkillComposition.needs_review.is_(False),
                (SkillComposition.composition_name.like(pattern, escape="\\"))
                | (SkillComposition.description.like(pattern, escape="\\"))
                | (SkillComposition.applicability.like(pattern, escape="\\")),
            )
            .order_by(SkillComposition.updated_at.desc(), SkillComposition.created_at.desc())
            .all()
        )

    def get_published_assistant_enabled(self) -> List[SkillComposition]:
        """获取所有已发布且可供 Assistant 使用的技能组合"""
        return (
            self.session.query(SkillComposition)
            .filter(
                SkillComposition.status == "published",
                SkillComposition.assistant_enabled.is_(True),
                SkillComposition.needs_review.is_(False),
            )
            .order_by(SkillComposition.updated_at.desc(), SkillComposition.created_at.desc())
            .all()
        )

    def update_status(self, composition_id: str, status: str) -> None:
        """更新技能组合状态"""
        composition = self.get_by_id(composition_id)
        if not composition:
            raise KeyError("composition_not_found")
        try:
            composition.status = status
            composition.updated_at = utc_now_naive()
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.error(f"更新技能组合状态失败: {e}")
            raise

    def clear_needs_review(self, composition_id: str) -> None:
        """清除待复核标记"""
        composition = self.get_by_id(composition_id)
        if not composition:
            raise KeyError("composition_not_found")
        try:
            composition.needs_review = False
            composition.updated_at = utc_now_naive()
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.error(f"清除待复核标记失败: {e}")
            raise

    def mark_needs_review_by_tool(self, tool_id: str) -> List[SkillComposition]:
        """标记引用某个技能的组合需要复核"""
        compositions = self.get_referencing_compositions(tool_id)
        if not compositions:
            return []
        try:
            now = utc_now_naive()
            for composition in compositions:
                composition.needs_review = True
                composition.updated_at = now
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.error(f"标记组合待复核失败: {e}")
            raise
        return compositions

    def get_referencing_compositions(
        self,
        tool_id: str,
        statuses: Optional[Iterable[str]] = None,
    ) -> List[SkillComposition]:
        """查询引用指定技能的组合"""
        query = (
            self.session.query(SkillComposition)
            .join(
                SkillCompositionMember,
                SkillComposition.composition_id == SkillCompositionMember.composition_id,
            )
            .filter(SkillCompositionMember.tool_id == tool_id)
            .distinct()
            .order_by(SkillComposition.updated_at.desc(), SkillComposition.created_at.desc())
        )
        if statuses:
            query = query.filter(SkillComposition.status.in_(list(statuses)))
        return query.all()
