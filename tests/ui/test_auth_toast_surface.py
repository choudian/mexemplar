import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton  # noqa: E402

from src.ui.widgets.auth_toast import (  # noqa: E402
    AUTH_TOAST_ACCEPT_BUTTON_NAME,
    AUTH_TOAST_ALLOW_ALL_BUTTON_NAME,
    AUTH_TOAST_REJECT_BUTTON_NAME,
    DECISION_ACCEPT,
    DECISION_ALLOW_ALL,
    DECISION_REJECT,
    DECISION_TIMEOUT,
    AuthToastSurface,
)


@pytest.fixture(scope="module")
def app():
    try:
        return QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用或无法创建 QApplication")


def _button(surface: AuthToastSurface, object_name: str) -> QPushButton:
    button = surface.findChild(QPushButton, object_name)
    assert button is not None
    return button


def test_auth_toast_surface_accept_emits_terminal_signal(app):
    surface = AuthToastSurface("req-1", "write_file", "目标文件: demo.txt", 1000)
    events = []
    surface.decision_made.connect(
        lambda request_id, decision: events.append((request_id, decision))
    )
    surface.show()
    app.processEvents()

    try:
        QTest.mouseClick(_button(surface, AUTH_TOAST_ACCEPT_BUTTON_NAME), Qt.MouseButton.LeftButton)
        app.processEvents()
        assert events == [("req-1", DECISION_ACCEPT)]
    finally:
        surface.deleteLater()


def test_auth_toast_surface_has_exactly_three_actions(app):
    surface = AuthToastSurface("req-2", "edit_file", "目标文件: demo.txt", 1000)
    surface.show()
    app.processEvents()

    try:
        button_names = sorted(button.objectName() for button in surface.findChildren(QPushButton))
        assert button_names == [
            AUTH_TOAST_ACCEPT_BUTTON_NAME,
            AUTH_TOAST_ALLOW_ALL_BUTTON_NAME,
            AUTH_TOAST_REJECT_BUTTON_NAME,
        ]
    finally:
        surface.deleteLater()


def test_auth_toast_surface_allow_all_and_reject_emit_expected_decisions(app):
    allow_all_surface = AuthToastSurface("req-3", "write_file", "目标文件: demo.txt", 1000)
    allow_all_events = []
    allow_all_surface.decision_made.connect(
        lambda request_id, decision: allow_all_events.append((request_id, decision))
    )
    allow_all_surface.show()
    app.processEvents()

    try:
        QTest.mouseClick(
            _button(allow_all_surface, AUTH_TOAST_ALLOW_ALL_BUTTON_NAME),
            Qt.MouseButton.LeftButton,
        )
        app.processEvents()
        assert allow_all_events == [("req-3", DECISION_ALLOW_ALL)]
    finally:
        allow_all_surface.deleteLater()

    reject_surface = AuthToastSurface("req-4", "exec", "命令首行: python --version", 1000)
    reject_events = []
    reject_surface.decision_made.connect(
        lambda request_id, decision: reject_events.append((request_id, decision))
    )
    reject_surface.show()
    app.processEvents()

    try:
        QTest.mouseClick(
            _button(reject_surface, AUTH_TOAST_REJECT_BUTTON_NAME),
            Qt.MouseButton.LeftButton,
        )
        app.processEvents()
        assert reject_events == [("req-4", DECISION_REJECT)]
    finally:
        reject_surface.deleteLater()


def test_auth_toast_surface_timeout_is_single_shot(app):
    surface = AuthToastSurface("req-5", "exec", "命令首行: python --version", 40)
    events = []
    surface.decision_made.connect(
        lambda request_id, decision: events.append((request_id, decision))
    )
    surface.show()
    app.processEvents()

    try:
        QTest.qWait(80)
        app.processEvents()
        assert events == [("req-5", DECISION_TIMEOUT)]
    finally:
        surface.deleteLater()


def test_auth_toast_surface_ignores_second_terminal_action(app):
    surface = AuthToastSurface("req-6", "write_file", "目标文件: demo.txt", 1000)
    events = []
    surface.decision_made.connect(
        lambda request_id, decision: events.append((request_id, decision))
    )
    surface.show()
    app.processEvents()

    try:
        QTest.mouseClick(_button(surface, AUTH_TOAST_ACCEPT_BUTTON_NAME), Qt.MouseButton.LeftButton)
        QTest.mouseClick(_button(surface, AUTH_TOAST_REJECT_BUTTON_NAME), Qt.MouseButton.LeftButton)
        app.processEvents()
        assert events == [("req-6", DECISION_ACCEPT)]
    finally:
        surface.deleteLater()


def test_auth_toast_surface_rejects_manual_close_while_pending(app):
    surface = AuthToastSurface("req-7", "exec", "命令首行: python --version", 1000)
    surface.show()
    app.processEvents()

    try:
        surface.close()
        app.processEvents()
        assert surface.isVisible() is True
    finally:
        surface.deleteLater()
