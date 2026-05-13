from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from src.recording.desktop import DESKTOP_ACTION_TYPES

_MOUSE_LEFT, _MOUSE_RIGHT, _MOUSE_MIDDLE, _WHEEL, _DRAG, _TYPING, _HOTKEY = DESKTOP_ACTION_TYPES

_BUTTON_TO_ACTION = {
    "left": _MOUSE_LEFT,
    "right": _MOUSE_RIGHT,
    "middle": _MOUSE_MIDDLE,
}

_MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "control": "ctrl",
    "control_l": "ctrl",
    "control_r": "ctrl",
    "alt": "alt",
    "alt_l": "alt",
    "alt_r": "alt",
    "alt_gr": "alt",
    "cmd": "win",
    "cmd_l": "win",
    "cmd_r": "win",
    "win": "win",
    "win_l": "win",
    "win_r": "win",
    "shift": "shift",
    "shift_l": "shift",
    "shift_r": "shift",
}
_SHORTCUT_MODIFIERS = {"ctrl", "alt", "win"}
_MODIFIER_ORDER = ("ctrl", "alt", "shift", "win")
_DRAG_PIXEL_THRESHOLD = 5
_DRAG_DURATION_THRESHOLD_MS = 200


class RecorderStartFailed(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class DesktopActionEvent:
    type: str
    timestamp: float
    coord_x: int | None = None
    coord_y: int | None = None
    monitor_index: int = 0
    text_content: str | None = None
    duration_ms: int | None = None
    metadata: dict = field(default_factory=dict)


class DesktopPynputHook:
    def __init__(self, on_action: Callable[[DesktopActionEvent], None] | None = None):
        self._on_action = on_action
        self._mouse_listener = None
        self._keyboard_listener = None
        self._typing_buffer: list[str] = []
        self._typing_started_at: float | None = None
        self._last_key_at: float | None = None
        self._mouse_down_at: float | None = None
        self._mouse_down_x: int | None = None
        self._mouse_down_y: int | None = None
        self._mouse_down_button: str | None = None
        self._monitor_geoms: list[dict] | None = None
        self._active_modifiers: set[str] = set()
        self._shortcut_consumed_modifiers: set[str] = set()

    def start(self) -> None:
        try:
            import mss

            with mss.mss() as sct:
                self._monitor_geoms = list(sct.monitors[1:])
        except Exception:
            self._monitor_geoms = []
        try:
            from pynput import keyboard, mouse

            self._mouse_listener = mouse.Listener(
                on_click=self._on_click, on_scroll=self._on_scroll
            )
            self._keyboard_listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._mouse_listener.start()
            self._keyboard_listener.start()
        except Exception as exc:
            raise RecorderStartFailed("hook_register_failed") from exc

    def stop(self) -> None:
        self.flush_typing()
        for listener in (self._mouse_listener, self._keyboard_listener):
            if listener is not None:
                listener.stop()
        self._mouse_listener = None
        self._keyboard_listener = None

    def classify_key(self, key: object) -> str:
        char = getattr(key, "char", None)
        if char:
            return _TYPING
        if self._modifier_name(key) == "shift":
            return _TYPING
        return _HOTKEY

    def feed_key(self, key: object, *, timestamp: float | None = None) -> None:
        now = timestamp or time.time()
        modifier = self._modifier_name(key)
        if modifier:
            if modifier in _SHORTCUT_MODIFIERS:
                self.flush_typing(now)
            elif self._typing_buffer:
                self._last_key_at = now
            self._active_modifiers.add(modifier)
            return

        kind = self.classify_key(key)
        char = getattr(key, "char", None)
        shortcut_modifiers = self._active_modifiers & _SHORTCUT_MODIFIERS
        if shortcut_modifiers:
            self.flush_typing(now)
            self._shortcut_consumed_modifiers.update(shortcut_modifiers)
            self._emit(
                DesktopActionEvent(
                    type=_HOTKEY,
                    timestamp=now,
                    metadata={"key": self._format_hotkey(key)},
                )
            )
            return

        if kind == _TYPING:
            if not char:
                if self._typing_buffer:
                    self._last_key_at = now
                return
            if self._last_key_at is not None and now - self._last_key_at > 1.0:
                self.flush_typing(now)
            if self._typing_started_at is None:
                self._typing_started_at = now
            self._typing_buffer.append(char)
            self._last_key_at = now
            return

        self.flush_typing(now)
        self._emit(
            DesktopActionEvent(
                type=_HOTKEY,
                timestamp=now,
                metadata={"key": self._key_label(key)},
            )
        )

    def feed_key_release(self, key: object, *, timestamp: float | None = None) -> None:
        now = timestamp or time.time()
        modifier = self._modifier_name(key)
        if not modifier:
            return
        was_active = modifier in self._active_modifiers
        self._active_modifiers.discard(modifier)
        if not was_active:
            return
        if modifier in _SHORTCUT_MODIFIERS and modifier not in self._shortcut_consumed_modifiers:
            self.flush_typing(now)
            self._emit(
                DesktopActionEvent(
                    type=_HOTKEY,
                    timestamp=now,
                    metadata={"key": modifier},
                )
            )
        self._shortcut_consumed_modifiers.discard(modifier)

    def flush_typing(self, timestamp: float | None = None) -> None:
        if not self._typing_buffer:
            return
        end = timestamp or self._last_key_at or time.time()
        start = self._typing_started_at or end
        self._emit(
            DesktopActionEvent(
                type=_TYPING,
                timestamp=start,
                text_content="".join(self._typing_buffer),
                duration_ms=int(max(0.0, end - start) * 1000),
            )
        )
        self._typing_buffer.clear()
        self._typing_started_at = None
        self._last_key_at = None

    def _on_press(self, key) -> None:
        self.feed_key(key)

    def _on_release(self, key) -> None:
        self.feed_key_release(key)

    def _on_click(self, x, y, button, pressed) -> None:
        now = time.time()
        button_name = getattr(button, "name", "left")
        monitor_index = self._resolve_monitor_index(x, y)

        if pressed:
            self.flush_typing()
            self._mouse_down_at = now
            self._mouse_down_x = x
            self._mouse_down_y = y
            self._mouse_down_button = button_name
            return

        if self._mouse_down_at is None:
            return

        down_x, down_y = self._mouse_down_x, self._mouse_down_y
        down_at = self._mouse_down_at
        duration_ms = int(max(0.0, now - down_at) * 1000)
        self._mouse_down_at = None
        self._mouse_down_x = None
        self._mouse_down_y = None
        self._mouse_down_button = None

        action_type = _BUTTON_TO_ACTION.get(str(button_name), _MOUSE_LEFT)

        moved = (
            down_x is not None
            and down_y is not None
            and (abs(x - down_x) > _DRAG_PIXEL_THRESHOLD or abs(y - down_y) > _DRAG_PIXEL_THRESHOLD)
        )
        held = duration_ms > _DRAG_DURATION_THRESHOLD_MS
        if down_x is not None and down_y is not None and (moved or held):
            self._emit(
                DesktopActionEvent(
                    type=_DRAG,
                    timestamp=now,
                    coord_x=x,
                    coord_y=y,
                    monitor_index=monitor_index,
                    duration_ms=duration_ms,
                    metadata={
                        "start_x": down_x,
                        "start_y": down_y,
                        "end_x": x,
                        "end_y": y,
                    },
                )
            )
        else:
            self._emit(
                DesktopActionEvent(
                    type=action_type,
                    timestamp=now,
                    coord_x=x,
                    coord_y=y,
                    monitor_index=monitor_index,
                )
            )

    def _on_scroll(self, x, y, dx, dy) -> None:
        self.flush_typing()
        self._emit(
            DesktopActionEvent(
                type=_WHEEL,
                timestamp=time.time(),
                coord_x=x,
                coord_y=y,
                monitor_index=self._resolve_monitor_index(x, y),
                metadata={"dx": dx, "dy": dy},
            )
        )

    def _resolve_monitor_index(self, x: int, y: int) -> int:
        geoms = self._monitor_geoms or []
        for i, mon in enumerate(geoms):
            if (
                mon["left"] <= x < mon["left"] + mon["width"]
                and mon["top"] <= y < mon["top"] + mon["height"]
            ):
                return i
        return 0

    def _modifier_name(self, key: object) -> str | None:
        name = getattr(key, "name", None)
        if not name:
            return None
        return _MODIFIER_ALIASES.get(str(name).lower())

    def _key_label(self, key: object) -> str:
        char = getattr(key, "char", None)
        if char:
            if len(char) == 1 and 1 <= ord(char) <= 26 and "ctrl" in self._active_modifiers:
                return chr(ord(char) + 96)
            return str(char).lower()
        name = getattr(key, "name", None)
        if name:
            return str(name).lower()
        return str(key)

    def _format_hotkey(self, key: object) -> str:
        label = self._key_label(key)
        parts = [modifier for modifier in _MODIFIER_ORDER if modifier in self._active_modifiers]
        parts.append(label)
        return "+".join(parts)

    def _emit(self, event: DesktopActionEvent) -> None:
        if self._on_action is not None:
            self._on_action(event)
