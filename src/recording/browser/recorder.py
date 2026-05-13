from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol


class RecordingMode:
    BROWSER = "browser"
    DESKTOP = "desktop"
    EXTENSION_TRIGGERED = "extension_triggered"

    @classmethod
    def display_defaults(cls, mode: str) -> dict:
        if mode == cls.EXTENSION_TRIGGERED:
            return {"browser_type": "chrome", "app_name": "Chrome", "process_name": "chrome"}
        return {"browser_type": "chromium", "app_name": "Browser", "process_name": "browser"}


@dataclass
class BrowserAction:
    action_type: str
    timestamp: float
    dom_element: Optional[Dict[str, Any]] = None
    network_requests: List[Dict[str, Any]] = field(default_factory=list)
    url: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecordingRuntimeState:
    recording_id: Optional[str]
    action_queue_path: Optional[Path]
    active_recording_mode: str
    startup_in_progress: bool
    playwright_ws_client: Any = None
    is_recording: bool = False


@dataclass(frozen=True)
class ControlStartResult:
    status: str
    recording_id: Optional[str] = None
    error: Optional[str] = None


class RecordingControlPort(Protocol):
    async def begin_extension_recording(self, websocket=None) -> ControlStartResult: ...

    async def finish_extension_recording(self, websocket=None) -> Dict[str, Any]: ...

    def emit_browser_action(self, message: Dict[str, Any]) -> None: ...
