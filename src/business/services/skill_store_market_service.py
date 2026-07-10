"""skills.sh marketplace search facade.

Search uses the official Skills CLI so users do not need to manage short-lived
Vercel OIDC tokens. Preview and install still go through the existing skill_store
business module.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.business.skill_store.skills_sh_client import StoreSkillSummary
from src.execution.skills_cli import SkillsCliUnavailableError, search_skills_with_cli


@dataclass(frozen=True)
class SkillStoreSearchResult:
    items: list[StoreSkillSummary]
    message: str | None = None


class SkillStoreMarketService:
    def search(self, query: str, *, limit: int = 30) -> SkillStoreSearchResult:
        normalized_query = " ".join(str(query or "").split())
        if not normalized_query:
            return SkillStoreSearchResult(
                items=[],
                message="输入关键词后使用 skills CLI 搜索技能市场。",
            )
        try:
            cli_items = search_skills_with_cli(normalized_query, limit=limit)
        except SkillsCliUnavailableError:
            raise
        items = [
            StoreSkillSummary(
                source_ref=item.source_ref,
                name=item.name,
                source=item.source,
                installs=item.installs,
                source_url=item.source_url,
            )
            for item in cli_items
        ]
        return SkillStoreSearchResult(items=items)
