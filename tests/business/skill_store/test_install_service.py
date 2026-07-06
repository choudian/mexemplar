"""InstallService 安装编排行为测试（029 T010，mock 外部取数）。"""

from __future__ import annotations

import pytest

from src.business.skill_store import file_store
from src.business.skill_store.install_service import InstallService, SkillInstallError
from src.business.skill_store.skills_sh_client import (
    StoreSkillDetail,
    StoreSkillSummary,
)
from src.data.models_sqlite import BrainSkill
from src.data.repos.external_skill_install_repository import (
    ExternalSkillInstallRepository,
)
from src.data.repos.skill_repository import SkillRepository

_SKILL_MD = """---
name: frontend-design
description: Distinctive design guidance
---

# Frontend Design

Do good design.
"""


def _detail(source_ref="vercel-labs/frontend-design", files=None):
    return StoreSkillDetail(
        summary=StoreSkillSummary(
            source_ref=source_ref,
            name=source_ref.rsplit("/", 1)[-1],
            source=source_ref.rsplit("/", 1)[0],
            installs=1200,
            source_url=f"https://skills.sh/{source_ref}",
        ),
        files=(
            files
            if files is not None
            else [
                {"path": "SKILL.md", "content": _SKILL_MD},
                {"path": "references/palette.md", "content": "colors"},
            ]
        ),
    )


class _FakeSkillsSh:
    def __init__(self, detail=None):
        self._detail = detail or _detail()

    def detail(self, source_ref):
        return self._detail

    def audit(self, source_ref):
        return {"status": "available", "result": {"verdict": "clean"}}

    def search(self, query, limit=30):
        return [self._detail.summary]


@pytest.fixture(autouse=True)
def _redirect_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(tmp_path))
    yield


def _service(detail=None) -> InstallService:
    return InstallService(skills_sh_client=_FakeSkillsSh(detail))


class TestInstall:
    def test_install_creates_triple_atomically(self, in_memory_db):
        result = _service().install("skills_sh", "vercel-labs/frontend-design")

        # 1) 方法论行
        skill = SkillRepository().get(result["skillId"])
        assert skill is not None
        assert skill.origin == "external_import"
        assert skill.name == "frontend-design"
        assert "Do good design" in skill.body_markdown
        # 2) 安装记录
        row = ExternalSkillInstallRepository().get_by_install_id(result["installId"])
        assert row is not None and row.uninstalled_at is None
        assert row.source_ref == "vercel-labs/frontend-design"
        # 3) 受管目录
        install_dir = file_store.external_skills_root() / result["installId"]
        assert (install_dir / "SKILL.md").exists()
        assert (install_dir / "references" / "palette.md").exists()

    def test_install_idempotent_same_source(self, in_memory_db):
        service = _service()
        first = service.install("skills_sh", "vercel-labs/frontend-design")
        second = service.install("skills_sh", "vercel-labs/frontend-design")
        assert second["installId"] == first["installId"]
        assert len(ExternalSkillInstallRepository().list_active()) == 1

    def test_install_without_skill_md_rejected(self, in_memory_db):
        detail = _detail(files=[{"path": "README.md", "content": "no skill here"}])
        with pytest.raises(SkillInstallError):
            _service(detail).install("skills_sh", "x/y")
        assert ExternalSkillInstallRepository().list_active() == []

    def test_install_failure_leaves_zero_residue(self, in_memory_db, monkeypatch):
        """SkillService.create 失败 → 文件目录与安装记录都不存在（FR-443）。"""
        service = _service()

        def _boom(**kwargs):
            raise RuntimeError("db unavailable")

        from src.business.brain.skill_service import SkillService

        monkeypatch.setattr(SkillService, "create", staticmethod(_boom))
        with pytest.raises(RuntimeError):
            service.install("skills_sh", "vercel-labs/frontend-design")

        assert ExternalSkillInstallRepository().list_active() == []
        root = file_store.external_skills_root()
        assert not any(p.is_dir() for p in root.iterdir())

    def test_name_conflict_appends_source_suffix(self, in_memory_db):
        service = _service()
        # 先占用同名方法论
        from src.business.brain.skill_service import SkillService

        SkillService().create(
            name="frontend-design",
            description="occupied",
            trigger_conditions=["x"],
            required_tools=[],
            body_markdown="body",
            source_segments=[],
            origin="external_import",
            caller_type="user",
            caller_id="test",
            change_reason="seed",
        )
        result = service.install("skills_sh", "vercel-labs/frontend-design")
        skill = SkillRepository().get(result["skillId"])
        assert skill.name == "frontend-design (skills.sh)"


class TestPreview:
    def test_preview_zero_persistence(self, in_memory_db):
        service = _service()
        preview = service.preview("skills_sh", "vercel-labs/frontend-design")

        assert preview["skillMd"].startswith("---")
        assert preview["audit"]["status"] == "available"
        assert preview["installable"] is True
        assert preview["installed"] is False
        # 零持久化
        assert ExternalSkillInstallRepository().list_active() == []
        from src.data.models_sqlite import ExternalSkillInstall  # noqa: F401

        root = file_store.external_skills_root()
        assert not any(p.is_dir() for p in root.iterdir())

    def test_preview_flags_oversized_as_not_installable(self, in_memory_db):
        big = "x" * (file_store.MAX_FILE_BYTES + 1)
        detail = _detail(files=[{"path": "SKILL.md", "content": big}])
        preview = _service(detail).preview("skills_sh", "x/big")
        assert preview["installable"] is False
        assert preview["reason"]


class TestUninstall:
    def test_uninstall_full_cleanup(self, in_memory_db):
        service = _service()
        result = service.install("skills_sh", "vercel-labs/frontend-design")
        install_dir = file_store.external_skills_root() / result["installId"]
        assert install_dir.exists()

        assert service.uninstall(result["installId"]) is True

        # 方法论软删（active 查询不可见，行保留）
        skill = SkillRepository().get(result["skillId"])
        assert skill is not None and skill.status == "soft_deleted"
        # 安装记录置 uninstalled_at
        row = ExternalSkillInstallRepository().get_by_install_id(result["installId"])
        assert row.uninstalled_at is not None
        # 目录清理
        assert not install_dir.exists()

    def test_uninstall_unknown_returns_false(self, in_memory_db):
        assert _service().uninstall("esi_missing") is False

    def test_reinstall_after_uninstall_creates_new_entry(self, in_memory_db):
        """US3：卸载后重装为新条目，旧条目在软删历史（T022）。"""
        service = _service()
        first = service.install("skills_sh", "vercel-labs/frontend-design")
        service.uninstall(first["installId"])

        second = service.install("skills_sh", "vercel-labs/frontend-design")

        assert second["installId"] != first["installId"]
        assert second["skillId"] != first["skillId"]
        active = ExternalSkillInstallRepository().list_active()
        assert [r.install_id for r in active] == [second["installId"]]
        # 旧方法论仍在（软删历史）
        old = SkillRepository().get(first["skillId"])
        assert old is not None and old.status == "soft_deleted"


def test_installed_skill_loads_with_external_warning(in_memory_db):
    """SC-441：安装的技能可被 load_skill_methodology 渲染且附外部来源警示。"""
    result = _service().install("skills_sh", "vercel-labs/frontend-design")
    from src.business.agents.tools.skill_methodology_tools import _render_skill_md

    skill = SkillRepository().get(result["skillId"])
    rendered = _render_skill_md(skill)
    assert "来自外部导入的技能" in rendered
    assert "# frontend-design" in rendered

    # 对照：非外部技能不带警示
    assert "来自外部导入的技能" not in _render_skill_md(
        type(
            "S",
            (),
            {
                "name": "n",
                "description": "d",
                "trigger_conditions": "[]",
                "required_tools": "[]",
                "body_markdown": "b",
                "origin": "assistant_tool_call",
            },
        )()
    )
