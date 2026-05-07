from __future__ import annotations

from PyQt6.QtWidgets import QCheckBox, QFormLayout, QLineEdit, QWidget

from src.data.unified_config import UnifiedConfigManager, get_unified_config


class DesktopRecordingSettings(QWidget):
    def __init__(
        self,
        config: UnifiedConfigManager | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._config = config or get_unified_config()
        layout = QFormLayout(self)

        desktop = self._config.get_recording_desktop_config()
        self.vision_model_input = QLineEdit(desktop.vision_model or "")
        self.vision_model_input.setPlaceholderText("留空则不启用桌面动作多模态分析")
        self.enable_clip_checkbox = QCheckBox()
        self.enable_clip_checkbox.setChecked(desktop.enable_clip)

        layout.addRow("vision_model", self.vision_model_input)
        layout.addRow("enable_clip", self.enable_clip_checkbox)

        self.vision_model_input.editingFinished.connect(self._save_vision_model)
        self.enable_clip_checkbox.toggled.connect(self._save_enable_clip)

    def save(self) -> None:
        self._save_vision_model()
        self._save_enable_clip(self.enable_clip_checkbox.isChecked())

    def _save_vision_model(self) -> None:
        value = self.vision_model_input.text().strip() or None
        self._config.set("recording.desktop.vision_model", value, value_type="json")

    def _save_enable_clip(self, checked: bool) -> None:
        self._config.set("recording.desktop.enable_clip", bool(checked), value_type="bool")
