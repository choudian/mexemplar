from src.data.config_models import RecordingDesktopConfig
from src.ui.widgets.settings.desktop_recording_settings import DesktopRecordingSettings


def test_vision_model_missing_is_represented_by_none():
    config = RecordingDesktopConfig()

    assert config.vision_model is None
    assert config.enable_clip is True


class _Config:
    def __init__(self):
        self.calls = []

    def get_recording_desktop_config(self):
        return RecordingDesktopConfig(vision_model="vision-x", enable_clip=True)

    def get_ai_api_key(self):
        return ""

    def get(self, key, default=None):
        return default

    def get_websocket_port(self):
        return 8765

    def set(self, key, value, value_type="string"):
        self.calls.append((key, value, value_type))


def test_desktop_settings_use_supported_config_types():
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    config = _Config()
    widget = DesktopRecordingSettings(config=config)

    widget.vision_model_input.setText("")
    widget._save_vision_model()
    widget._save_enable_clip(False)
    app.processEvents()

    assert config.calls == [
        ("recording.desktop.vision_model", None, "json"),
        ("recording.desktop.enable_clip", False, "bool"),
    ]


def test_settings_page_wires_desktop_recording_settings(monkeypatch):
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from src.ui.widgets import settings_page

    app = QApplication.instance() or QApplication(sys.argv)
    config = _Config()
    monkeypatch.setattr(settings_page, "get_unified_config", lambda: config)

    page = settings_page.SettingsPage()

    assert isinstance(page.desktop_recording_settings, DesktopRecordingSettings)
    assert page.desktop_recording_settings.vision_model_input.text() == "vision-x"
    app.processEvents()
