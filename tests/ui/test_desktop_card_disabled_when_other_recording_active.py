from src.recording.desktop_recorder import ActiveDesktopRecorderRegistry


def test_desktop_active_state_supports_ui_guard():
    ActiveDesktopRecorderRegistry._active.clear()
    assert ActiveDesktopRecorderRegistry.state()["active"] is False

    ActiveDesktopRecorderRegistry.start("rec-1")
    assert ActiveDesktopRecorderRegistry.state()["active"] is True

    ActiveDesktopRecorderRegistry.stop("rec-1")
    assert ActiveDesktopRecorderRegistry.state()["active"] is False
