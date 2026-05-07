from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class HotkeyRegistrationResult:
    ok: bool
    reason: str | None = None


class DesktopStopHotkey:
    def __init__(self, on_stop: Callable[[], None] | None = None):
        self._on_stop = on_stop
        self._hotkey = None

    def register(self) -> HotkeyRegistrationResult:
        try:
            from pynput import keyboard

            self._hotkey = keyboard.GlobalHotKeys({"<ctrl>+<alt>+s": self._handle_stop})
            self._hotkey.start()
            return HotkeyRegistrationResult(ok=True)
        except Exception:
            self._hotkey = None
            return HotkeyRegistrationResult(ok=False, reason="hotkey_register_failed")

    def unregister(self) -> None:
        if self._hotkey is not None:
            self._hotkey.stop()
            self._hotkey = None

    def _handle_stop(self) -> None:
        from src.utils.events import desktop_stop_requested

        desktop_stop_requested.send(self)
