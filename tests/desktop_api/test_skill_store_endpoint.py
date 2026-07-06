"""技能商店 API 契约测试（029 T011/T018，contracts/store-api.md）。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.business.skill_store.skills_sh_client import (
    SkillsShClient,
    SkillsShUnavailableError,
    StoreSkillDetail,
    StoreSkillSummary,
)

_SKILL_MD = """---
name: api-test-skill
description: API contract skill
---

Body.
"""


def _summary(source_ref="acme/api-test-skill"):
    return StoreSkillSummary(
        source_ref=source_ref,
        name="api-test-skill",
        source="acme",
        installs=7,
        source_url=f"https://skills.sh/{source_ref}",
    )


def _detail(source_ref="acme/api-test-skill"):
    return StoreSkillDetail(
        summary=_summary(source_ref),
        files=[{"path": "SKILL.md", "content": _SKILL_MD}],
    )


@pytest.fixture(autouse=True)
def _redirect_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(tmp_path))
    yield


@pytest.fixture()
def _mock_skills_sh(monkeypatch):
    monkeypatch.setattr(SkillsShClient, "search", lambda self, q, limit=30: [_summary()])
    monkeypatch.setattr(SkillsShClient, "curated", lambda self, limit=30: [_summary()])
    monkeypatch.setattr(SkillsShClient, "detail", lambda self, ref: _detail(ref))
    monkeypatch.setattr(SkillsShClient, "audit", lambda self, ref: {"status": "unavailable"})
    yield


def test_search_degrades_when_source_unavailable(in_memory_db, monkeypatch):
    """约束 1：外部失败 → sourceAvailable=false，不抛 5xx。"""
    from src.desktop_api.routers.skill_store import search_store

    def _down(self, q, limit=30):
        raise SkillsShUnavailableError()

    monkeypatch.setattr(SkillsShClient, "search", _down)
    response = search_store(q="anything", limit=10)
    assert response.sourceAvailable is False
    assert response.items == []
    assert response.message


def test_preview_has_no_persistence(in_memory_db, _mock_skills_sh):
    """约束 2：preview 不产生 DB 行或文件。"""
    from src.business.skill_store import file_store
    from src.data.repos.external_skill_install_repository import (
        ExternalSkillInstallRepository,
    )
    from src.desktop_api.routers.skill_store import PreviewBody, preview_skill

    response = preview_skill(PreviewBody(sourceType="skills_sh", sourceRef="acme/api-test-skill"))
    assert response.skillMd.startswith("---")
    assert response.audit["status"] == "unavailable"
    assert ExternalSkillInstallRepository().list_active() == []
    assert not any(p.is_dir() for p in file_store.external_skills_root().iterdir())


def test_install_triple_and_idempotency(in_memory_db, _mock_skills_sh):
    """约束 3+4：安装三件套原子成对；重复安装同 installId 行数不增。"""
    from src.business.skill_store import file_store
    from src.data.repos.external_skill_install_repository import (
        ExternalSkillInstallRepository,
    )
    from src.data.repos.skill_repository import SkillRepository
    from src.desktop_api.routers.skill_store import PreviewBody, install_skill

    body = PreviewBody(sourceType="skills_sh", sourceRef="acme/api-test-skill")
    first = install_skill(body)

    skill = SkillRepository().get(first.skillId)
    assert skill is not None and skill.origin == "external_import"
    row = ExternalSkillInstallRepository().get_by_install_id(first.installId)
    assert row is not None and row.uninstalled_at is None
    assert (file_store.external_skills_root() / first.installId / "SKILL.md").exists()

    second = install_skill(body)
    assert second.installId == first.installId
    assert len(ExternalSkillInstallRepository().list_active()) == 1


def test_uninstall_flips_installed_flag(in_memory_db, _mock_skills_sh):
    """约束 5：卸载后软删、目录清理、installed 标识翻转。"""
    from src.business.skill_store import file_store
    from src.desktop_api.routers.skill_store import (
        PreviewBody,
        install_skill,
        search_store,
        uninstall_skill,
    )

    body = PreviewBody(sourceType="skills_sh", sourceRef="acme/api-test-skill")
    installed = install_skill(body)
    assert search_store(q="x", limit=10).items[0].installed is True

    assert uninstall_skill(installed.installId) == {"removed": True}

    assert search_store(q="x", limit=10).items[0].installed is False
    assert not (file_store.external_skills_root() / installed.installId).exists()

    with pytest.raises(HTTPException) as exc_info:
        uninstall_skill(installed.installId)
    assert exc_info.value.status_code == 404


def test_install_rejects_traversal_with_zero_residue(in_memory_db, monkeypatch):
    """约束 6：路径穿越样本 → 拒绝且零残留。"""
    from src.business.skill_store import file_store
    from src.data.repos.external_skill_install_repository import (
        ExternalSkillInstallRepository,
    )
    from src.desktop_api.routers.skill_store import PreviewBody, install_skill

    evil = StoreSkillDetail(
        summary=_summary("acme/evil"),
        files=[
            {"path": "SKILL.md", "content": _SKILL_MD},
            {"path": "../escape.md", "content": "evil"},
        ],
    )
    monkeypatch.setattr(SkillsShClient, "detail", lambda self, ref: evil)
    monkeypatch.setattr(SkillsShClient, "audit", lambda self, ref: {"status": "unavailable"})

    with pytest.raises(HTTPException) as exc_info:
        install_skill(PreviewBody(sourceType="skills_sh", sourceRef="acme/evil"))
    assert exc_info.value.status_code == 422
    assert ExternalSkillInstallRepository().list_active() == []
    root = file_store.external_skills_root()
    assert not any(p.is_dir() for p in root.iterdir())
    assert not (root.parent / "escape.md").exists()


def test_discover_github_contract(in_memory_db, monkeypatch):
    """US2 契约：发现多技能 / 无技能 / 非法输入 422。"""
    from src.business.skill_store.github_discovery import GithubFetcher
    from src.desktop_api.routers.skill_store import DiscoverGithubBody, discover_github

    monkeypatch.setattr(
        GithubFetcher,
        "discover",
        lambda self, repo: [
            {"sourceRef": "o/r", "name": "r", "path": "SKILL.md"},
            {"sourceRef": "o/r/skills/x", "name": "x", "path": "skills/x/SKILL.md"},
        ],
    )
    response = discover_github(DiscoverGithubBody(repo="o/r"))
    assert len(response.skills) == 2

    monkeypatch.setattr(GithubFetcher, "discover", lambda self, repo: [])
    empty = discover_github(DiscoverGithubBody(repo="o/empty"))
    assert empty.skills == [] and empty.message

    from src.business.skill_store.github_discovery import GithubRepoInputError

    def _bad(self, repo):
        raise GithubRepoInputError("请输入 owner/repo 或完整 GitHub 仓库链接")

    monkeypatch.setattr(GithubFetcher, "discover", _bad)
    with pytest.raises(HTTPException) as exc_info:
        discover_github(DiscoverGithubBody(repo="not a repo"))
    assert exc_info.value.status_code == 422
