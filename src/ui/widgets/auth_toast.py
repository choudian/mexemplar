"""
Assistant 高危工具确认浮层。

该组件只负责展示与发出终态决策，不直接写业务状态。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

AUTH_TOAST_OBJECT_NAME = "auth_confirmation_toast"
AUTH_TOAST_TITLE_NAME = "auth_confirmation_title"
AUTH_TOAST_SUMMARY_NAME = "auth_confirmation_summary"
AUTH_TOAST_HINT_NAME = "auth_confirmation_hint"
AUTH_TOAST_ALLOW_ALL_BUTTON_NAME = "auth_confirmation_allow_all_button"
AUTH_TOAST_ACCEPT_BUTTON_NAME = "auth_confirmation_accept_button"
AUTH_TOAST_REJECT_BUTTON_NAME = "auth_confirmation_reject_button"

AUTH_TOAST_STATE_IDLE = "idle"
AUTH_TOAST_STATE_RESOLVED = "resolved"

DECISION_ALLOW_ALL = "allow_all"
DECISION_ACCEPT = "accept"
DECISION_REJECT = "reject"
DECISION_TIMEOUT = "timeout"


class AuthToastSurface(QFrame):
    """右下角非模态确认浮层。"""

    decision_made = pyqtSignal(str, str)

    def __init__(
        self,
        request_id: str,
        tool_name: str,
        summary: str,
        timeout_ms: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self.tool_name = tool_name
        self.summary = summary
        self._timeout_ms = max(int(timeout_ms), 1)
        self._state = AUTH_TOAST_STATE_IDLE
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName(AUTH_TOAST_OBJECT_NAME)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        title = QLabel(f"高危操作确认 · {self.tool_name}")
        title.setObjectName(AUTH_TOAST_TITLE_NAME)
        root.addWidget(title)

        summary_label = QLabel(self.summary)
        summary_label.setObjectName(AUTH_TOAST_SUMMARY_NAME)
        summary_label.setWordWrap(True)
        root.addWidget(summary_label)

        hint = QLabel("仅影响当前会话；不展示完整文件内容或完整命令体。")
        hint.setObjectName(AUTH_TOAST_HINT_NAME)
        hint.setWordWrap(True)
        root.addWidget(hint)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        allow_all_button = QPushButton("全部允许")
        allow_all_button.setObjectName(AUTH_TOAST_ALLOW_ALL_BUTTON_NAME)
        allow_all_button.clicked.connect(lambda: self._emit_decision(DECISION_ALLOW_ALL))
        button_row.addWidget(allow_all_button)

        accept_button = QPushButton("同意")
        accept_button.setObjectName(AUTH_TOAST_ACCEPT_BUTTON_NAME)
        accept_button.clicked.connect(lambda: self._emit_decision(DECISION_ACCEPT))
        button_row.addWidget(accept_button)

        reject_button = QPushButton("拒绝")
        reject_button.setObjectName(AUTH_TOAST_REJECT_BUTTON_NAME)
        reject_button.clicked.connect(lambda: self._emit_decision(DECISION_REJECT))
        button_row.addWidget(reject_button)

        root.addLayout(button_row)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if self._state == AUTH_TOAST_STATE_IDLE and not self._timer.isActive():
            self._timer.start(self._timeout_ms)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._state == AUTH_TOAST_STATE_IDLE:
            event.ignore()
            return
        super().closeEvent(event)

    def _emit_decision(self, decision: str) -> None:
        if self._state == AUTH_TOAST_STATE_RESOLVED:
            return
        self._state = AUTH_TOAST_STATE_RESOLVED
        if self._timer.isActive():
            self._timer.stop()
        self.decision_made.emit(self.request_id, decision)

    def _on_timeout(self) -> None:
        self._emit_decision(DECISION_TIMEOUT)
