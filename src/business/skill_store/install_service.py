"""技能安装编排（029 D5）——预览零持久化、安装原子成对、卸载全清理。

安装顺序：文件先落受管目录（file_store 原子写）→ SkillService.create
（origin='external_import'）→ 伴生表落安装记录；任一步失败按逆序清理，
不留半安装状态（FR-443）。本模块零执行（CC-170）。
"""

from __future__ import annotations

import logging
from typing import Any

from src.business.skill_store.file_store import (
    SkillFile,
    SkillFileStoreError,
    remove_install_dir,
    validate_files,
    write_install_dir,
)
from src.business.skill_store.skill_md_parser import parse_skill_md
from src.business.skill_store.skills_sh_client import (
    SkillsShClient,
    SkillsShNotFoundError,
    StoreSkillDetail,
)
from src.data.repos.base_repository import generate_id
from src.data.repos.external_skill_install_repository import (
    ExternalSkillInstallRepository,
)

logger = logging.getLogger(__name__)

_SOURCE_LABELS = {"skills_sh": "skills.sh", "github": "GitHub"}


class SkillInstallError(RuntimeError):
    """安装失败——消息面向用户可读。"""


class SkillNotFoundError(KeyError):
    """来源上找不到该技能。"""


class InstallNameConflictError(SkillInstallError):
    """方法论重名且加来源后缀后仍冲突。"""


class InstallService:
    """技能商店安装/卸载编排；外部取数 client 可注入便于测试。"""

    def __init__(
        self,
        *,
        skills_sh_client: SkillsShClient | None = None,
        github_fetcher: Any | None = None,
    ):
        self._skills_sh = skills_sh_client or SkillsShClient()
        self._github = github_fetcher  # US2 注入 github_discovery.GithubFetcher

    # -- Preview（零持久化） ---------------------------------------------------

    def preview(self, source_type: str, source_ref: str) -> dict[str, Any]:
        detail = self._fetch_detail(source_type, source_ref)
        skill_md = self._find_skill_md(detail)
        files_meta = [
            {"path": f["path"], "size": len(str(f.get("content") or "").encode("utf-8"))}
            for f in detail.files
        ]
        installable = True
        reason = None
        try:
            validate_files(self._as_skill_files(detail))
        except SkillFileStoreError as exc:
            installable = False
            reason = str(exc)
        if source_type == "skills_sh" and not self._is_cli_market_ref(source_ref):
            audit = self._skills_sh.audit(source_ref)
        else:
            audit = {"status": "unaudited"}
        active = ExternalSkillInstallRepository().get_active_by_source(source_type, source_ref)
        return {
            "sourceType": source_type,
            "sourceRef": detail.summary.source_ref,
            "name": detail.summary.name,
            "sourceUrl": detail.summary.source_url,
            "skillMd": skill_md,
            "files": files_meta,
            "audit": audit,
            "installable": installable,
            "reason": reason,
            "installed": active is not None,
        }

    # -- Install（原子成对 + 幂等） ---------------------------------------------

    def install(self, source_type: str, source_ref: str) -> dict[str, Any]:
        repo = ExternalSkillInstallRepository()
        existing = repo.get_active_by_source(source_type, source_ref)
        if existing is not None:
            return self._install_response(existing)

        detail = self._fetch_detail(source_type, source_ref)
        skill_files = self._as_skill_files(detail)
        skill_md = self._find_skill_md(detail)
        if not skill_md:
            raise SkillInstallError("该技能不包含 SKILL.md，无法安装")
        parsed = parse_skill_md(skill_md, fallback_slug=detail.summary.name)

        install_id = generate_id("esi")
        try:
            local_dir = write_install_dir(install_id, skill_files)
        except SkillFileStoreError as exc:
            raise SkillInstallError(str(exc)) from exc

        skill_id: str | None = None
        try:
            skill_id = self._create_methodology(parsed, source_type, detail)
            row = repo.create(
                install_id=install_id,
                skill_id=skill_id,
                source_type=source_type,
                source_ref=detail.summary.source_ref,
                source_url=detail.summary.source_url,
                local_dir=str(local_dir),
            )
            return self._install_response(row)
        except Exception:
            # 逆序清理：先回收方法论，再删文件目录（FR-443 零半安装残留）
            if skill_id is not None:
                self._rollback_methodology(skill_id)
            remove_install_dir(install_id)
            raise

    # -- Uninstall --------------------------------------------------------------

    def uninstall(self, install_id: str) -> bool:
        repo = ExternalSkillInstallRepository()
        row = repo.get_by_install_id(install_id)
        if row is None or row.uninstalled_at is not None:
            return False
        from src.business.brain.skill_service import SkillService

        try:
            SkillService().force_soft_delete(row.skill_id)
        except KeyError:
            logger.info("Uninstall %s: methodology already gone", install_id)
        if not repo.mark_uninstalled(install_id):
            return False
        remove_install_dir(install_id)
        return True

    # -- Query ------------------------------------------------------------------

    def list_installed(self) -> list[dict[str, Any]]:
        from src.data.repos.skill_repository import SkillRepository

        repo = ExternalSkillInstallRepository()
        skill_repo = SkillRepository()
        items = []
        for row in repo.list_active():
            skill = skill_repo.get(row.skill_id)
            items.append(
                {
                    "installId": row.install_id,
                    "skillId": row.skill_id,
                    "name": skill.name if skill is not None else row.source_ref,
                    "sourceType": row.source_type,
                    "sourceRef": row.source_ref,
                    "sourceUrl": row.source_url,
                    "installedAt": row.installed_at,
                }
            )
        return items

    def installed_source_refs(self, source_type: str) -> set[str]:
        repo = ExternalSkillInstallRepository()
        return {row.source_ref for row in repo.list_active() if row.source_type == source_type}

    # -- Internal -----------------------------------------------------------------

    def _fetch_detail(self, source_type: str, source_ref: str) -> StoreSkillDetail:
        if source_type == "skills_sh":
            if self._is_cli_market_ref(source_ref):
                if self._github is None:
                    from src.business.skill_store.github_discovery import GithubFetcher

                    self._github = GithubFetcher()
                try:
                    return self._github.fetch_cli_skill_detail(source_ref)
                except Exception as exc:
                    from src.business.skill_store.github_discovery import (
                        GithubSkillNotFoundError,
                        GithubUnavailableError,
                    )

                    if isinstance(exc, GithubSkillNotFoundError):
                        raise SkillNotFoundError(source_ref) from exc
                    if isinstance(exc, GithubUnavailableError):
                        raise SkillInstallError(str(exc)) from exc
                    raise
            try:
                return self._skills_sh.detail(source_ref)
            except SkillsShNotFoundError as exc:
                raise SkillNotFoundError(source_ref) from exc
        if source_type == "github":
            if self._github is None:
                from src.business.skill_store.github_discovery import GithubFetcher

                self._github = GithubFetcher()
            return self._github.fetch_detail(source_ref)
        raise SkillInstallError(f"不支持的来源类型：{source_type}")

    @staticmethod
    def _is_cli_market_ref(source_ref: str) -> bool:
        from src.business.skill_store.github_discovery import is_cli_skill_ref

        return is_cli_skill_ref(source_ref)

    @staticmethod
    def _as_skill_files(detail: StoreSkillDetail) -> list[SkillFile]:
        return [
            SkillFile(path=str(f["path"]), content=str(f.get("content") or ""))
            for f in detail.files
        ]

    @staticmethod
    def _find_skill_md(detail: StoreSkillDetail) -> str:
        candidates = [
            f for f in detail.files if str(f.get("path", "")).split("/")[-1] == "SKILL.md"
        ]
        if not candidates:
            return ""
        # 取路径最浅的 SKILL.md（根优先）
        best = min(candidates, key=lambda f: str(f["path"]).count("/"))
        return str(best.get("content") or "")

    def _create_methodology(
        self,
        parsed,
        source_type: str,
        detail: StoreSkillDetail,
    ) -> str:
        from src.business.brain.skill_service import SkillService

        label = _SOURCE_LABELS.get(source_type, source_type)
        change_reason = f"external install from {label}: {detail.summary.source_ref}"
        service = SkillService()
        for candidate in (parsed.name, f"{parsed.name} ({label})"):
            try:
                created = service.create(
                    name=candidate,
                    description=parsed.description,
                    trigger_conditions=[parsed.description],
                    required_tools=[],
                    body_markdown=parsed.body,
                    source_segments=[],
                    origin="external_import",
                    caller_type="user",
                    caller_id="skill_store",
                    change_reason=change_reason,
                )
                return str(created["skill_id"])
            except ValueError as exc:
                if str(exc).startswith("skill_name_collision"):
                    continue
                raise
        raise InstallNameConflictError(f"已存在同名方法论「{parsed.name}」，请先处理重名后重试")

    @staticmethod
    def _rollback_methodology(skill_id: str) -> None:
        try:
            from src.business.brain.skill_service import SkillService

            SkillService().force_soft_delete(skill_id)
        except Exception:
            logger.warning("Rollback methodology %s failed", skill_id, exc_info=True)

    @staticmethod
    def _install_response(row) -> dict[str, Any]:
        return {"installId": row.install_id, "skillId": row.skill_id}
