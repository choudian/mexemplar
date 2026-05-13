from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Literal

RecordingMode = Literal["browser", "extension", "desktop"]
ReadinessStatus = Literal["ready", "needs_setup", "unavailable"]


@dataclass(frozen=True)
class ModeReadiness:
    mode: RecordingMode
    status: ReadinessStatus
    message: str = ""
    actions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "status": self.status,
            "message": self.message,
            "actions": list(self.actions),
        }


class RecordingReadinessService:
    """Mode readiness facade for the redesigned teaching flow."""

    def get_readiness(self) -> list[ModeReadiness]:
        desktop_ready = platform.system().lower() == "windows"
        return [
            ModeReadiness(
                mode="browser",
                status="ready",
                message="可录制浏览器操作。",
            ),
            ModeReadiness(
                mode="extension",
                status="ready",
                message="可通过浏览器扩展触发录制。",
                actions=("open_extension_setup",),
            ),
            ModeReadiness(
                mode="desktop",
                status="ready" if desktop_ready else "unavailable",
                message="可录制桌面操作。" if desktop_ready else "桌面录制当前仅支持 Windows。",
            ),
        ]

    def to_response(self) -> dict[str, object]:
        return {"modes": [item.to_dict() for item in self.get_readiness()]}
