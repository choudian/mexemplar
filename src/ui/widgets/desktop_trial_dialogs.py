from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.business.utils.high_risk_api_detector import detect_high_risk_apis
from src.execution.desktop_trial_models import TrialResult


class DesktopTrialPreviewDialog(QDialog):
    def __init__(self, code: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("试用提示")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("试用代码即将在桌面真实执行（最长 120s）"))

        preview = QPlainTextEdit("\n".join(code.splitlines()[:20]))
        preview.setReadOnly(True)
        layout.addWidget(preview)

        labels = detect_high_risk_apis(code)
        label_text = "、".join(labels) if labels else "未检测到"
        layout.addWidget(QLabel(f"检测到的高危 API：{label_text}"))

        buttons = QHBoxLayout()
        start = QPushButton("开始")
        cancel = QPushButton("取消")
        start.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(start)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)


def trial_toast_payload(result: TrialResult) -> tuple[str, str]:
    if result.timed_out:
        return "试用超时", "代码执行超过 120 秒已被终止"
    if result.ok and result.exit_code == 0:
        return "试用成功", result.summary
    return "试用失败", result.summary
