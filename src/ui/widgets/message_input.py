"""
共享消息输入框组件

支持 Enter 发送、Shift+Enter / Ctrl+Enter 换行的 QTextEdit 子类。
"""

from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent


class MessageInputEdit(QTextEdit):
    """支持 Enter 发送、Shift+Enter / Ctrl+Enter 换行的自定义输入框"""

    send_requested = pyqtSignal()  # 发送请求信号

    def keyPressEvent(self, event: QKeyEvent):
        """处理按键事件：Enter 发送，Shift/Ctrl+Enter 换行"""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Ctrl+Enter 或 Shift+Enter 换行
            if event.modifiers() & (
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
            ):
                self.insertPlainText("\n")
                return
            # 无修饰符（或仅 KeypadModifier）的 Enter 发送消息
            if event.modifiers() in (
                Qt.KeyboardModifier.NoModifier,
                Qt.KeyboardModifier.KeypadModifier,
            ):
                self.send_requested.emit()
                return
        # 其他按键正常处理
        super().keyPressEvent(event)
