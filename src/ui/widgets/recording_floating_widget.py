from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class RecordingFloatingWidget(QWidget):
    stopRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            parent,
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint,
        )
        self._drag_origin: QPoint | None = None
        self._count_label = QLabel("录制中 0 个动作")
        self._stop_button = QPushButton("停止")
        self._stop_button.clicked.connect(self.stopRequested.emit)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.addWidget(QLabel("REC"))
        layout.addWidget(self._count_label)
        layout.addWidget(self._stop_button)
        self.setFixedSize(160, 40)

    def set_action_count(self, count: int) -> None:
        self._count_label.setText(f"录制中 {count} 个动作")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_origin = None
        super().mouseReleaseEvent(event)
