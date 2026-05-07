from types import SimpleNamespace

from src.recording.desktop.pynput_hook import DesktopPynputHook


def test_desktop_pynput_hook_classifies_typing_and_hotkey():
    events = []
    hook = DesktopPynputHook(events.append)

    hook.feed_key(SimpleNamespace(char="a"), timestamp=1.0)
    hook.feed_key(SimpleNamespace(char="b"), timestamp=1.5)
    hook.feed_key(SimpleNamespace(name="ctrl"), timestamp=1.6)
    hook.feed_key_release(SimpleNamespace(name="ctrl"), timestamp=1.7)

    assert events[0].type == "typing"
    assert events[0].text_content == "ab"
    assert events[1].type == "hotkey"
    assert events[1].metadata["key"] == "ctrl"


def test_desktop_pynput_hook_records_modifier_shortcut_as_one_hotkey():
    events = []
    hook = DesktopPynputHook(events.append)

    hook.feed_key(SimpleNamespace(name="ctrl"), timestamp=1.0)
    hook.feed_key(SimpleNamespace(char="s"), timestamp=1.1)
    hook.feed_key_release(SimpleNamespace(name="ctrl"), timestamp=1.2)

    assert len(events) == 1
    assert events[0].type == "hotkey"
    assert events[0].metadata["key"] == "ctrl+s"


def test_desktop_pynput_hook_decodes_control_character_shortcut():
    events = []
    hook = DesktopPynputHook(events.append)

    hook.feed_key(SimpleNamespace(name="ctrl"), timestamp=1.0)
    hook.feed_key(SimpleNamespace(char="\x13"), timestamp=1.1)
    hook.feed_key_release(SimpleNamespace(name="ctrl"), timestamp=1.2)

    assert len(events) == 1
    assert events[0].metadata["key"] == "ctrl+s"


def test_typing_pause_splits_sequence():
    events = []
    hook = DesktopPynputHook(events.append)

    hook.feed_key(SimpleNamespace(char="a"), timestamp=1.0)
    hook.feed_key(SimpleNamespace(char="b"), timestamp=2.2)
    hook.flush_typing(2.3)

    assert [event.text_content for event in events] == ["a", "b"]
