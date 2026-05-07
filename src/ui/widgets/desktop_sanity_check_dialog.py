from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from src.recording.desktop import DESKTOP_ACTION_TYPES
from src.recording.desktop_recorder import DesktopRecorderHealth

_UIA_HIT_RATIO_THRESHOLD = 0.5
_CLIP_FAILURE_RATE_THRESHOLD = 0.2


def determine_health_color(stats: DesktopRecorderHealth, enable_clip: bool) -> str:
    if stats.action_total == 0:
        return "red"
    if stats.uia_total > 0 and stats.uia_hit / stats.uia_total < _UIA_HIT_RATIO_THRESHOLD:
        return "yellow"
    if enable_clip and stats.clip_total > 0:
        failure_rate = (stats.clip_total - stats.clip_success) / stats.clip_total
        if failure_rate > _CLIP_FAILURE_RATE_THRESHOLD:
            return "yellow"
    return "green"


class DesktopSanityCheckDialog(QDialog):
    continueAnalysisRequested = pyqtSignal(str)
    abandonRequested = pyqtSignal(str)
    rerecordRequested = pyqtSignal(str)

    def __init__(
        self,
        recording_id: str,
        stats: DesktopRecorderHealth | dict | None = None,
        enable_clip: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.recording_id = recording_id
        if isinstance(stats, dict):
            self.stats = DesktopRecorderHealth.from_value(stats)
        else:
            self.stats = stats or DesktopRecorderHealth()
        self.enable_clip = enable_clip
        self.setWindowTitle("录制健康反馈")
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        color = determine_health_color(self.stats, self.enable_clip)
        layout.addWidget(QLabel(f"状态：{color}"))
        layout.addWidget(QLabel(f"动作总数：{self.stats.action_total}"))
        layout.addWidget(QLabel(f"帧总数：{self.stats.frame_total}"))
        layout.addWidget(QLabel(f"clip 数：{self.stats.clip_success}/{self.stats.clip_total}"))
        layout.addWidget(QLabel(f"剪贴板事件：{self.stats.clipboard_event_count}"))
        layout.addWidget(QLabel(f"UIA 命中率：{self.stats.uia_hit}/{self.stats.uia_total}"))
        layout.addWidget(QLabel(f"录制时长：{self.stats.duration_seconds:.1f} 秒"))
        for action_type in DESKTOP_ACTION_TYPES:
            layout.addWidget(QLabel(f"{action_type}: {self.stats.action_type_counts.get(action_type, 0)}"))

        buttons = QHBoxLayout()
        continue_button = QPushButton("继续分析")
        abandon_button = QPushButton("放弃录制")
        rerecord_button = QPushButton("重新录制")
        continue_button.clicked.connect(self._continue_analysis)
        abandon_button.clicked.connect(self._abandon)
        rerecord_button.clicked.connect(self._rerecord)
        buttons.addWidget(continue_button)
        buttons.addWidget(abandon_button)
        buttons.addWidget(rerecord_button)
        layout.addLayout(buttons)

    def _continue_analysis(self) -> None:
        self.continueAnalysisRequested.emit(self.recording_id)
        self.accept()

    def _abandon(self) -> None:
        self.abandonRequested.emit(self.recording_id)
        self.reject()

    def _rerecord(self) -> None:
        self.rerecordRequested.emit(self.recording_id)
        self.reject()
