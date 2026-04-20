from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QLineEdit,
    QMenu,
    QPushButton,
    QTextEdit,
    QWidget,
)


class UIRobot:
    def __init__(self, window):
        self.window = window

    def click_widget(self, widget: QWidget) -> None:
        if widget is None:
            raise AssertionError("目标控件为空，无法点击")
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)

    def click_button(self, text: str, root: Optional[QWidget] = None) -> None:
        root = root or self._active_root()
        button = self._find_child(
            QPushButton,
            lambda candidate: candidate.isVisible() and candidate.text() == text,
            root=root,
        )
        if button is None:
            raise AssertionError(f"未找到文字为 '{text}' 的按钮")
        self.click_widget(button)

    def click_button_prefix(self, prefix: str, root: Optional[QWidget] = None) -> None:
        root = root or self._active_root()
        button = self._find_child(
            QPushButton,
            lambda candidate: candidate.isVisible() and candidate.text().startswith(prefix),
            root=root,
        )
        if button is None:
            raise AssertionError(f"未找到前缀为 '{prefix}' 的按钮")
        self.click_widget(button)

    def click_dialog_button(self, standard_button: QDialogButtonBox.StandardButton) -> None:
        root = self._active_root()
        box = self._find_child(
            QDialogButtonBox,
            lambda candidate: candidate.button(standard_button) is not None,
            root=root,
        )
        if box is None:
            raise AssertionError(f"未找到包含 {standard_button} 的 QDialogButtonBox")
        self.click_widget(box.button(standard_button))

    def click_menu_action(self, text: str) -> None:
        popup = QApplication.activePopupWidget()
        if not isinstance(popup, QMenu):
            raise AssertionError("当前没有激活的 QMenu")
        for action in popup.actions():
            if action.text() == text:
                rect = popup.actionGeometry(action)
                QTest.mouseClick(popup, Qt.MouseButton.LeftButton, pos=rect.center())
                return
        raise AssertionError(f"当前菜单中未找到动作 '{text}'")

    def click_sidebar_page(self, page_id: str) -> None:
        button = self.window.sidebar.nav_buttons[page_id]
        self.click_widget(button)

    def click_sidebar_action(self, action: str) -> None:
        if action != "new_chat":
            raise AssertionError(f"未知的侧边栏动作: {action}")
        self.click_widget(self.window.sidebar.new_chat_btn)

    def fill(self, widget: QWidget, text: str, clear: bool = True) -> None:
        widget.setFocus()
        if isinstance(widget, QTextEdit):
            if clear:
                widget.clear()
                widget.setPlainText(text)
            else:
                widget.insertPlainText(text)
            return
        if isinstance(widget, QLineEdit):
            if clear:
                widget.clear()
                widget.setText(text)
            else:
                widget.setText(widget.text() + text)
            return
        if clear and hasattr(widget, "clear"):
            widget.clear()
        QTest.keyClicks(widget, text)

    def press_enter(self, widget: QWidget) -> None:
        widget.setFocus()
        send_requested = getattr(widget, "send_requested", None)
        if send_requested is not None and hasattr(send_requested, "emit"):
            send_requested.emit()
            return
        QTest.keyClick(widget, Qt.Key.Key_Return)

    def find_widget(self, widget_type, label: Optional[str] = None):
        def predicate(widget):
            if not widget.isVisible():
                return False
            if label is None:
                return True
            if isinstance(widget, QLineEdit):
                return False
            text_attr = getattr(widget, "text", None)
            return callable(text_attr) and text_attr() == label

        return self._find_child(widget_type, predicate)

    def find_text_input(
        self,
        *,
        placeholder: Optional[str] = None,
        object_name: Optional[str] = None,
    ):
        def predicate(widget):
            if not widget.isVisible():
                return False
            if object_name is not None and widget.objectName() != object_name:
                return False
            if placeholder is not None and widget.placeholderText() != placeholder:
                return False
            return True

        for widget_type in (QLineEdit, QTextEdit):
            found = self._find_child(widget_type, predicate)
            if found is not None:
                return found
        return None

    def find_all(self, widget_type, predicate: Optional[Callable] = None):
        results = []
        for child in self._active_root().findChildren(widget_type):
            if not child.isVisible():
                continue
            if predicate is None or predicate(child):
                results.append(child)
        return results

    def _active_root(self) -> QWidget:
        app = QApplication.instance()
        if app is not None:
            modal = app.activeModalWidget()
            if modal is not None:
                return modal
        return self.window

    def _find_child(self, widget_type, predicate: Callable, root: Optional[QWidget] = None):
        root = root or self._active_root()
        for child in root.findChildren(widget_type):
            if predicate(child):
                return child
        return None
