"""
SkillBootstrapService -- 内置"如何创建方法论"初始化与自愈。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from src.data.repos.skill_equipment_repository import ASSISTANT_ENTITY_ID, SkillEquipmentRepository
from src.data.repos.skill_repository import SkillRepository
from src.data.skill_bootstrap_seed import (
    BOOTSTRAP_DESCRIPTION,
    BOOTSTRAP_HOW_TO_SKILL_ID,
    BOOTSTRAP_NAME,
    BOOTSTRAP_REQUIRED_TOOLS,
    BOOTSTRAP_TRIGGERS,
    DEFAULT_SEED_FILE_PATH,
    FALLBACK_BODY,
)
from src.utils.events import emit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeedLoadResult:
    body: str
    fallback_used: bool
    reason: str | None
    seed_file_path: str

    def __post_init__(self) -> None:
        if self.fallback_used and not self.reason:
            raise ValueError("SeedLoadResult: fallback_used=True requires a non-empty reason")
        if not self.fallback_used and self.reason is not None:
            raise ValueError("SeedLoadResult: fallback_used=False must have reason=None")


class SkillBootstrapService:
    """Bootstrap the built-in skill methodology guide."""

    BOOTSTRAP_HOW_TO_SKILL_ID = BOOTSTRAP_HOW_TO_SKILL_ID
    DEFAULT_SEED_FILE_PATH = DEFAULT_SEED_FILE_PATH
    BOOTSTRAP_NAME = BOOTSTRAP_NAME
    BOOTSTRAP_DESCRIPTION = BOOTSTRAP_DESCRIPTION
    BOOTSTRAP_TRIGGERS = BOOTSTRAP_TRIGGERS
    BOOTSTRAP_REQUIRED_TOOLS = BOOTSTRAP_REQUIRED_TOOLS
    _FALLBACK_BODY = FALLBACK_BODY

    def __init__(self, session: Session | None = None, *, seed_file_path: str | None = None):
        self._session = session
        self._seed_file_path = seed_file_path

    def load_seed_or_fallback(self, *, use_unified_config: bool = True) -> SeedLoadResult:
        path_text = self._seed_file_path or self.DEFAULT_SEED_FILE_PATH
        if use_unified_config:
            try:
                from src.data.unified_config import get_unified_config

                path_text = get_unified_config().get_brain_skill_seed_file_path()
            except Exception as exc:
                logger.warning("读取 brain.skill.seed_file_path 失败，使用默认路径: %s", exc)
        path = Path(path_text)
        if not path.is_absolute():
            # 打包后 cwd 是安装目录，那里没有源码树；seed 随 exe 走。
            from src.utils.helpers import bundled_resource_path

            path = bundled_resource_path(path)
        try:
            body = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("方法论 seed 文件不存在，使用 fallback: path=%s", path)
            return self._fallback("seed_file_missing", str(path))
        except (OSError, UnicodeError) as exc:
            logger.warning("方法论 seed 文件读取失败，使用 fallback: path=%s error=%s", path, exc)
            return self._fallback("seed_file_io_error", str(path))
        if not body.strip():
            return self._fallback("seed_file_empty", str(path))
        return SeedLoadResult(
            body=body.strip(), fallback_used=False, reason=None, seed_file_path=str(path)
        )

    def bootstrap_missing_skill(
        self,
        *,
        engine=None,
        session: Session | None = None,
        use_unified_config: bool = False,
    ) -> dict[str, Any]:
        owns_session = False
        active_session = session or self._session
        if active_session is None:
            if engine is None:
                raise ValueError("engine or session is required for bootstrap")
            active_session = sessionmaker(bind=engine)()
            owns_session = True

        result = self.load_seed_or_fallback(use_unified_config=use_unified_config)
        try:
            repo = SkillRepository(active_session)
            equipment_repo = SkillEquipmentRepository(active_session)
            existing = repo.get(self.BOOTSTRAP_HOW_TO_SKILL_ID)
            if existing is None:
                skill = repo.create_skill(
                    skill_id=self.BOOTSTRAP_HOW_TO_SKILL_ID,
                    name=self.BOOTSTRAP_NAME,
                    description=self.BOOTSTRAP_DESCRIPTION,
                    trigger_conditions=self.BOOTSTRAP_TRIGGERS,
                    required_tools=self.BOOTSTRAP_REQUIRED_TOOLS,
                    body_markdown=result.body,
                    origin="system_bootstrap",
                    last_changed_by="system",
                    change_reason="bootstrap",
                    commit=False,
                )
                if (
                    equipment_repo.get_active_equipment(
                        "assistant",
                        ASSISTANT_ENTITY_ID,
                        skill.skill_id,
                    )
                    is None
                ):
                    equipment_repo.equip(
                        entity_type="assistant",
                        entity_id=ASSISTANT_ENTITY_ID,
                        skill_id=skill.skill_id,
                        equipped_order=0,
                        commit=False,
                    )
                active_session.commit()
            else:
                skill = existing
            if result.fallback_used:
                emit(
                    "brain_skill_bootstrap_fallback_used",
                    sender=skill.skill_id,
                    skill_id=skill.skill_id,
                    reason=result.reason,
                    seed_file_path=result.seed_file_path,
                )
            return {
                "bootstrap_active_skill_id": skill.skill_id,
                "fallback_used": result.fallback_used,
                "seed_file_path": result.seed_file_path,
            }
        except Exception as exc:
            active_session.rollback()
            logger.error(
                "初始化内置方法论失败: seed_file_path=%s fallback_used=%s: %s",
                result.seed_file_path,
                result.fallback_used,
                exc,
                exc_info=True,
            )
            raise
        finally:
            if owns_session:
                active_session.close()

    def ensure_bootstrap_skill(self) -> dict[str, Any]:
        result = self.load_seed_or_fallback(use_unified_config=True)
        active_session = self._session
        owns_session = False
        if active_session is None:
            from src.data.sqlalchemy_manager import get_sqlalchemy_manager

            manager = get_sqlalchemy_manager()
            manager.initialize()
            active_session = manager.get_session()
            owns_session = True
        try:
            repo = SkillRepository(active_session)
            current = repo.get_current_active_for_chain(self.BOOTSTRAP_HOW_TO_SKILL_ID)
            if current is None:
                return self.bootstrap_missing_skill(
                    session=active_session,
                    use_unified_config=True,
                )
            if (
                not result.fallback_used
                and current.body_markdown.strip() == self._FALLBACK_BODY.strip()
                and not repo.has_user_edit_in_chain(current.chain_root_id)
            ):
                # A fallback row may be created during migration. Once the configured seed
                # becomes readable, upgrade it without overwriting any user-authored revision.
                equipment_repo = SkillEquipmentRepository(active_session)
                new_skill_id = f"{self.BOOTSTRAP_HOW_TO_SKILL_ID}.v{int(current.version or 1) + 1}"
                if not repo.mark_superseded(current.skill_id, new_skill_id, commit=False):
                    raise RuntimeError("skill_bootstrap_supersede_conflict")
                new_skill = repo.create_skill(
                    skill_id=new_skill_id,
                    name=self.BOOTSTRAP_NAME,
                    description=self.BOOTSTRAP_DESCRIPTION,
                    trigger_conditions=self.BOOTSTRAP_TRIGGERS,
                    required_tools=self.BOOTSTRAP_REQUIRED_TOOLS,
                    body_markdown=result.body,
                    origin="system_bootstrap",
                    parent_skill_id=current.skill_id,
                    chain_root_id=current.chain_root_id,
                    version=int(current.version or 1) + 1,
                    last_changed_by="_system",
                    change_reason="seed file restored",
                    commit=False,
                )
                equipment_repo.transfer_active_equipment(
                    old_skill_id=current.skill_id,
                    new_skill_id=new_skill.skill_id,
                    commit=False,
                )
                active_session.commit()
                emit(
                    "brain_skill_changed",
                    sender=new_skill.skill_id,
                    skill_id=new_skill.skill_id,
                    operation="supersede",
                    chain_root_id=new_skill.chain_root_id,
                    new_skill_id=new_skill.skill_id,
                    caller_type="system",
                    caller_id="_system",
                )
                return {
                    "bootstrap_active_skill_id": new_skill.skill_id,
                    "fallback_used": False,
                    "seed_file_path": result.seed_file_path,
                }
            return {
                "bootstrap_active_skill_id": current.skill_id,
                "fallback_used": current.body_markdown.strip() == self._FALLBACK_BODY.strip(),
                "seed_file_path": result.seed_file_path,
            }
        except Exception as exc:
            active_session.rollback()
            logger.error(
                "确保内置方法论失败: seed_file_path=%s fallback_used=%s: %s",
                result.seed_file_path,
                result.fallback_used,
                exc,
                exc_info=True,
            )
            raise
        finally:
            if owns_session:
                active_session.close()

    def bootstrap_status(self) -> dict[str, Any]:
        status = self.ensure_bootstrap_skill()
        return {
            "bootstrap_active_skill_id": status.get("bootstrap_active_skill_id"),
            "fallback_used": bool(status.get("fallback_used")),
            "seed_file_path": status.get("seed_file_path") or self.DEFAULT_SEED_FILE_PATH,
            "last_seed_check_at": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def _fallback(cls, reason: str, seed_file_path: str) -> SeedLoadResult:
        return SeedLoadResult(
            body=cls._FALLBACK_BODY.strip(),
            fallback_used=True,
            reason=reason,
            seed_file_path=seed_file_path,
        )
