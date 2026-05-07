from types import SimpleNamespace

from src.recording.desktop.pynput_hook import DesktopActionEvent
from src.recording.desktop.pynput_hook import DesktopPynputHook


def test_desktop_drag_event_uses_release_endpoint_fields():
    event = DesktopActionEvent(
        type="drag", timestamp=3.0, coord_x=200, coord_y=300, monitor_index=1
    )

    assert event.type == "drag"
    assert event.coord_x == 200
    assert event.coord_y == 300
    assert event.monitor_index == 1


def test_desktop_pynput_drag_emits_release_endpoint_fields():
    events = []
    hook = DesktopPynputHook(events.append)
    hook._monitor_geoms = [{"left": 0, "top": 0, "width": 500, "height": 500}]
    button = SimpleNamespace(name="left")

    hook._on_click(10, 20, button, True)
    hook._on_click(200, 300, button, False)

    assert len(events) == 1
    event = events[0]
    assert event.type == "drag"
    assert event.coord_x == 200
    assert event.coord_y == 300
    assert event.metadata["start_x"] == 10
    assert event.metadata["start_y"] == 20


def test_desktop_drag_thresholds_require_more_than_five_pixels_or_held_duration(monkeypatch):
    button = SimpleNamespace(name="left")

    events = []
    hook = DesktopPynputHook(events.append)
    hook._monitor_geoms = [{"left": 0, "top": 0, "width": 500, "height": 500}]
    timestamps = iter([10.0, 10.05])
    monkeypatch.setattr("src.recording.desktop.pynput_hook.time.time", lambda: next(timestamps))

    hook._on_click(10, 10, button, True)
    hook._on_click(15, 10, button, False)

    assert events[0].type == "mouse_left"

    events = []
    hook = DesktopPynputHook(events.append)
    hook._monitor_geoms = [{"left": 0, "top": 0, "width": 500, "height": 500}]
    timestamps = iter([20.0, 20.201])
    monkeypatch.setattr("src.recording.desktop.pynput_hook.time.time", lambda: next(timestamps))

    hook._on_click(10, 10, button, True)
    hook._on_click(10, 10, button, False)

    assert events[0].type == "drag"
    assert events[0].duration_ms == 201
