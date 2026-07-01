from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import text

from src.data.sqlalchemy_manager import get_sqlalchemy_manager
from src.data.unified_config import get_unified_config

logger = logging.getLogger(__name__)

HealthStatus = Literal["ok", "degraded", "failed"]
BackendStatus = Literal["starting", "ready", "degraded", "failed", "shutting_down"]


@dataclass(frozen=True)
class DesktopHealthCheck:
    name: str
    status: HealthStatus
    message: str = ""
    critical: bool = True

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
        }


class DesktopHealthService:
    """Business-level health probes for the desktop sidecar."""

    def get_connection_state(
        self,
        *,
        event_stream_available: bool = True,
        extra_checks: Iterable[DesktopHealthCheck] | None = None,
    ) -> dict[str, object]:
        checks = [
            self._probe_config(),
            self._probe_sqlite(),
            self._event_check(event_stream_available),
            DesktopHealthCheck("sidecar", "ok", "Python sidecar is running."),
        ]
        checks.extend(extra_checks or [])

        critical_failed = any(check.status == "failed" and check.critical for check in checks)
        any_problem = any(check.status != "ok" for check in checks)
        status: BackendStatus = (
            "failed" if critical_failed else "degraded" if any_problem else "ready"
        )
        message = {
            "ready": "Desktop backend is ready.",
            "degraded": "Desktop backend is running with recoverable issues.",
            "failed": "Desktop backend is not ready.",
        }[status]
        return {
            "status": status,
            "message": message,
            "checks": [check.to_dict() for check in checks],
            "serverTime": datetime.now(timezone.utc),
        }

    def _probe_config(self) -> DesktopHealthCheck:
        try:
            config = get_unified_config()
            config.get("ui.theme", default="light")
            return DesktopHealthCheck("config", "ok", "Unified configuration available.")
        except Exception as exc:
            logger.exception("Desktop health config probe failed")
            return DesktopHealthCheck(
                "config",
                "failed",
                f"Unified configuration is unavailable: {type(exc).__name__}",
            )

    def _probe_sqlite(self) -> DesktopHealthCheck:
        try:
            manager = get_sqlalchemy_manager()
            manager.initialize()
            session = manager.get_session()
            try:
                session.execute(text("SELECT 1"))
            finally:
                session.close()
            return DesktopHealthCheck("sqlite", "ok", "Business repositories available.")
        except Exception as exc:
            logger.exception("Desktop health SQLite probe failed")
            return DesktopHealthCheck(
                "sqlite",
                "failed",
                f"Business repositories are unavailable: {type(exc).__name__}",
            )

    @staticmethod
    def _event_check(event_stream_available: bool) -> DesktopHealthCheck:
        if event_stream_available:
            return DesktopHealthCheck(
                "events",
                "ok",
                "Desktop event stream available.",
                critical=False,
            )
        return DesktopHealthCheck(
            "events",
            "degraded",
            "Desktop event stream is not currently available.",
            critical=False,
        )
