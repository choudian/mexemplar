"""技能商店 API（029）——搜索/发现/预览/安装/卸载。

预览零持久化；安装零执行（CC-170）；search 外部失败降级为
sourceAvailable=false（不抛 5xx），商店 tab 降级不影响其他路由。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.business.skill_store.install_service import (
    InstallService,
    SkillInstallError,
    SkillNotFoundError,
)
from src.business.skill_store.skills_sh_client import (
    SkillsShAuthenticationError,
    SkillsShUnavailableError,
)
from src.business.services.skill_store_market_service import SkillStoreMarketService
from src.execution.skills_cli import SkillsCliUnavailableError

router = APIRouter(prefix="/api/skill-store", tags=["skill-store"])

SourceType = Literal["skills_sh", "github"]


class StoreSkillSummaryDto(BaseModel):
    sourceRef: str
    name: str
    source: str
    installs: int
    sourceUrl: str
    installed: bool


class SearchResponse(BaseModel):
    items: list[StoreSkillSummaryDto]
    sourceAvailable: bool
    message: str | None = None


class DiscoverGithubBody(BaseModel):
    repo: str


class DiscoveredSkillDto(BaseModel):
    sourceRef: str
    name: str
    path: str


class DiscoverGithubResponse(BaseModel):
    skills: list[DiscoveredSkillDto]
    message: str | None = None


class PreviewBody(BaseModel):
    sourceType: SourceType
    sourceRef: str


class PreviewResponse(BaseModel):
    sourceType: str
    sourceRef: str
    name: str
    sourceUrl: str
    skillMd: str
    files: list[dict[str, Any]]
    audit: dict[str, Any]
    installable: bool
    reason: str | None = None
    installed: bool


class InstallResponse(BaseModel):
    installId: str
    skillId: str


class InstalledExternalSkillDto(BaseModel):
    installId: str
    skillId: str
    name: str
    sourceType: str
    sourceRef: str
    sourceUrl: str
    installedAt: str


class InstalledListResponse(BaseModel):
    items: list[InstalledExternalSkillDto]


@router.get("/search", response_model=SearchResponse)
def search_store(
    q: str = Query(default=""),
    limit: int = Query(default=30, ge=1, le=50),
) -> SearchResponse:
    service = InstallService()
    try:
        result = SkillStoreMarketService().search(q, limit=limit)
    except SkillsCliUnavailableError as exc:
        return SearchResponse(items=[], sourceAvailable=False, message=str(exc))
    summaries = result.items
    installed_refs = service.installed_source_refs("skills_sh")
    items = [
        StoreSkillSummaryDto(
            sourceRef=s.source_ref,
            name=s.name,
            source=s.source,
            installs=s.installs,
            sourceUrl=s.source_url,
            installed=s.source_ref in installed_refs,
        )
        for s in summaries
    ]
    return SearchResponse(items=items, sourceAvailable=True, message=result.message)


@router.post("/discover-github", response_model=DiscoverGithubResponse)
def discover_github(body: DiscoverGithubBody) -> DiscoverGithubResponse:
    from src.business.skill_store.github_discovery import (
        GithubFetcher,
        GithubRepoInputError,
        GithubUnavailableError,
    )

    try:
        discovered = GithubFetcher().discover(body.repo)
    except GithubRepoInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except GithubUnavailableError as exc:
        return DiscoverGithubResponse(skills=[], message=str(exc))
    if not discovered:
        return DiscoverGithubResponse(skills=[], message="仓库不存在或不包含技能文件")
    return DiscoverGithubResponse(
        skills=[
            DiscoveredSkillDto(sourceRef=d["sourceRef"], name=d["name"], path=d["path"])
            for d in discovered
        ]
    )


@router.post("/preview", response_model=PreviewResponse)
def preview_skill(body: PreviewBody) -> PreviewResponse:
    try:
        return PreviewResponse(**InstallService().preview(body.sourceType, body.sourceRef))
    except SkillNotFoundError:
        raise HTTPException(status_code=404, detail="技能不存在")
    except SkillsShAuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except SkillsShUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except SkillInstallError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/install", response_model=InstallResponse)
def install_skill(body: PreviewBody) -> InstallResponse:
    from src.business.skill_store.install_service import InstallNameConflictError

    try:
        result = InstallService().install(body.sourceType, body.sourceRef)
    except SkillNotFoundError:
        raise HTTPException(status_code=404, detail="技能不存在")
    except InstallNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except SkillsShAuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except SkillsShUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except SkillInstallError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return InstallResponse(**result)


@router.get("/installed", response_model=InstalledListResponse)
def list_installed() -> InstalledListResponse:
    items = InstallService().list_installed()
    return InstalledListResponse(items=[InstalledExternalSkillDto(**item) for item in items])


@router.post("/{install_id}/uninstall")
def uninstall_skill(install_id: str) -> dict[str, bool]:
    if not InstallService().uninstall(install_id):
        raise HTTPException(status_code=404, detail="安装记录不存在或已卸载")
    return {"removed": True}
