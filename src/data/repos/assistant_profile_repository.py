"""
AssistantProfileRepository -- 助理用户偏好档案仓库
"""

import logging
from typing import Optional

from ..models_sqlite import AssistantProfile
from .base_repository import BaseRepository

logger = logging.getLogger(__name__)


class AssistantProfileRepository(BaseRepository):
    """助理用户偏好档案仓库"""

    def get_default(self) -> Optional[AssistantProfile]:
        """获取默认 profile"""
        return (
            self.session.query(AssistantProfile)
            .filter(AssistantProfile.profile_id == "default")
            .first()
        )

    def save(self, display_name: str = "", style: str = "", notes: str = "") -> AssistantProfile:
        """保存或更新默认 profile"""
        existing = self.get_default()
        if existing:
            if display_name:
                existing.display_name = display_name
            if style:
                existing.style = style
            if notes:
                existing.notes = notes
            self.session.commit()
            return existing
        else:
            profile = AssistantProfile(
                profile_id="default",
                display_name=display_name or None,
                style=style or None,
                notes=notes or None,
            )
            self.session.add(profile)
            self.session.commit()
            self.session.refresh(profile)
            return profile
