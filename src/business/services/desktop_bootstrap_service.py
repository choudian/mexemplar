from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.business.services.desktop_health_service import DesktopHealthCheck
from src.business.services.chat_service import ChatService
from src.business.services.skills_service import SkillsService
from src.data.unified_config import get_unified_config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BootstrapCounts:
    pending_skills: int = 0
    published_skills: int = 0
    failures: int = 0
    compositions: int = 0


class DesktopBootstrapService:
    """Builds the shell bootstrap DTO without exposing repositories to UI adapters."""

    def __init__(self) -> None:
        self._warnings: list[DesktopHealthCheck] = []

    def health_checks(self) -> list[DesktopHealthCheck]:
        return list(self._warnings)

    def _record_degraded(self, name: str, message: str, exc: Exception) -> None:
        logger.warning("%s: %s", message, exc, exc_info=True)
        self._warnings.append(
            DesktopHealthCheck(
                name=name,
                status="degraded",
                message=f"{message}: {type(exc).__name__}",
                critical=False,
            )
        )

    def get_display_name(self) -> str:
        try:
            return ChatService().get_display_name() or "本地用户"
        except Exception as exc:
            self._record_degraded("bootstrap.user", "Unable to load display profile", exc)
            return "本地用户"

    def get_navigation_counts(self) -> BootstrapCounts:
        pending_count = 0
        published_count = 0
        failure_count = 0

        try:
            pending, published = SkillsService().get_tools()
            pending_count = len(pending)
            published_count = len(published)
        except Exception as exc:
            self._record_degraded("bootstrap.skills", "Unable to load skill counts", exc)
            pending_count = 0
            published_count = 0

        try:
            failure_count = len(SkillsService().get_active_failures())
        except Exception as exc:
            self._record_degraded("bootstrap.failures", "Unable to load failure counts", exc)
            failure_count = 0

        composition_count = 0
        try:
            from src.business.services.skill_composition_service import SkillCompositionService

            service = SkillCompositionService()
            if hasattr(service, "list_compositions"):
                composition_count = len(service.list_compositions())
        except Exception as exc:
            self._record_degraded(
                "bootstrap.compositions",
                "Unable to load composition counts",
                exc,
            )
            composition_count = 0

        return BootstrapCounts(
            pending_skills=pending_count,
            published_skills=published_count,
            failures=failure_count,
            compositions=composition_count,
        )

    def get_settings_summary(self) -> dict[str, Any]:
        try:
            config = get_unified_config()
            theme = str(config.get("ui.theme", default="light") or "light")
            density = str(config.get("ui.density", default="comfy") or "comfy")
        except Exception as exc:
            self._record_degraded("bootstrap.settings", "Unable to load UI settings", exc)
            theme = "light"
            density = "comfy"

        if theme not in {"light", "dark", "system", "sage"}:
            theme = "light"
        if density not in {"compact", "comfy"}:
            density = "comfy"
        return {
            "theme": theme,
            "dark": theme == "dark",
            "density": density,
        }

    def run(self) -> dict[str, Any]:
        counts = self.get_navigation_counts()
        return {
            "user": {
                "displayName": self.get_display_name(),
                "statusLabel": "本地版 · 已就绪",
            },
            "navigation": {
                "pendingSkillCount": counts.pending_skills,
                "publishedSkillCount": counts.published_skills,
                "failureCount": counts.failures,
                "compositionCount": counts.compositions,
            },
            "settingsSummary": self.get_settings_summary(),
        }
