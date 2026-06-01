"""
SkillReferenceCounterService -- reply 元数据中的方法论引用计数。
"""

from __future__ import annotations

import logging

from src.data.repos.skill_repository import SkillRepository

logger = logging.getLogger(__name__)


class SkillReferenceCounterService:
    """处理 skills_referenced 元数据与 loaded_count 更新。"""

    def __init__(self, repo: SkillRepository | None = None):
        self._repo = repo or SkillRepository()

    def close(self) -> None:
        self._repo.close()

    def process_reply_metadata(self, skills_referenced) -> int:
        """按 chain_root 归一化引用计数；坏格式静默跳过。"""
        if not isinstance(skills_referenced, list):
            return 0
        normalized_roots: set[str] = set()
        for raw in skills_referenced:
            if not isinstance(raw, str) or not raw.strip():
                continue
            root = self._repo.resolve_chain_root(raw.strip())
            if root:
                normalized_roots.add(root)
        updated = 0
        for root in normalized_roots:
            try:
                if self._repo.increment_referenced_count_for_root(root):
                    updated += 1
            except Exception as exc:
                logger.warning("跳过方法论引用计数更新: root=%s error=%s", root, exc)
        return updated

    def increment_loaded_count(self, skill_id: str) -> bool:
        try:
            return self._repo.increment_loaded_count(skill_id)
        except Exception as exc:
            logger.warning("跳过方法论加载计数更新: skill_id=%s error=%s", skill_id, exc)
            return False
