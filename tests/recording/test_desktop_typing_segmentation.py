from types import SimpleNamespace

from src.recording.desktop.pynput_hook import DesktopPynputHook


def test_desktop_typing_segmentation_splits_on_non_character_key():
    events = []
    hook = DesktopPynputHook(events.append)

    hook.feed_key(SimpleNamespace(char="中"), timestamp=1.0)
    hook.feed_key(SimpleNamespace(name="enter"), timestamp=1.1)

    assert events[0].type == "typing"
    assert events[0].text_content == "中"
    assert events[1].type == "hotkey"


def test_desktop_typing_ignores_shift_modifier():
    events = []
    hook = DesktopPynputHook(events.append)

    hook.feed_key(SimpleNamespace(name="shift"), timestamp=1.0)
    hook.feed_key(SimpleNamespace(char="A"), timestamp=1.1)
    hook.feed_key(SimpleNamespace(name="shift_r"), timestamp=1.2)
    hook.flush_typing(1.3)

    assert len(events) == 1
    assert events[0].type == "typing"
    assert events[0].text_content == "A"
