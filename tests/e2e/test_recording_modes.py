from __future__ import annotations

import os

import pytest
from PyQt6.QtWidgets import QMessageBox

from src.recording.browser_recorder import PLAYWRIGHT_AVAILABLE, RecordingMode
from src.ui.page_ids import INTENT_CONFIRMATION, TEACHING
from src.utils.events import event_value

pytestmark = pytest.mark.e2e


def test_extension_recording_cancel_wait(main_window, robot):
    robot.ui.click_sidebar_page(TEACHING)
    recording_page = main_window.recording_page

    robot.ui.click_widget(recording_page.extension_card)
    assert recording_page._current_mode == RecordingMode.EXTENSION_TRIGGERED
    assert recording_page.extension_container.isVisible()

    robot.ui.click_button("开始教学")

    assert recording_page._awaiting_extension_start is True
    assert recording_page.record_btn.isEnabled() is False
    assert recording_page.stop_btn.isEnabled() is True
    assert recording_page.recording_indicator.isVisible() is False

    robot.ui.click_button("结束教学")

    assert recording_page._awaiting_extension_start is False
    assert recording_page.record_btn.isEnabled() is True
    assert recording_page.stop_btn.isEnabled() is False
    assert "已取消等待扩展开始录制" in recording_page.status_text.toPlainText()


def test_desktop_recording_currently_unsupported(main_window, robot, monkeypatch):
    warnings: list[tuple[str, str]] = []

    def fake_warning(parent, title: str, text: str):
        warnings.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)

    robot.ui.click_sidebar_page(TEACHING)
    recording_page = main_window.recording_page
    robot.ui.click_widget(recording_page.desktop_card)
    assert recording_page._current_mode == RecordingMode.DESKTOP
    assert recording_page.url_container.isVisible() is False

    robot.ui.click_button("开始教学")

    assert warnings == [
        ("不支持的模式", "暂不支持 desktop 模式\n\n当前仅支持浏览器操作。")
    ]
    assert recording_page.is_recording is False
    assert recording_page.record_btn.isEnabled() is True
    assert recording_page.stop_btn.isEnabled() is False
    assert recording_page.recording_indicator.isVisible() is False


def test_browser_recording(local_test_server, main_window, robot):
    if os.environ.get("EXEMPLAR_RUN_BROWSER_E2E") != "1":
        pytest.skip("设置 EXEMPLAR_RUN_BROWSER_E2E=1 后才运行浏览器录制 smoke 用例")
    if not PLAYWRIGHT_AVAILABLE:
        pytest.skip("当前环境未安装 Playwright，跳过浏览器录制 E2E")

    robot.ui.click_sidebar_page(TEACHING)
    recording_page = main_window.recording_page
    robot.ui.click_widget(recording_page.browser_card)
    recording_page.url_input.setText(local_test_server)
    assert main_window._ensure_agent_bridge(timeout=10.0)

    try:
        main_window._agent_start_requested.disconnect(main_window._on_agent_start_requested)
    except TypeError:
        pass

    robot.ui.click_button("开始教学")
    robot.browser.wait_ready()
    robot.browser.wait_for_selector('input[name="q"]')
    robot.browser.fill('input[name="q"]', "mexemplar")
    robot.browser.click('button[type="submit"]')
    assert "mexemplar" in robot.browser.text_content("#result")

    robot.ui.click_button("结束教学")
    payload = robot.wait.wait_signal("recording_completed", timeout_ms=30_000)

    assert payload is not None, "应收到 recording_completed 事件"
    assert event_value(payload.get("event_data"), "action_count") > 0
    assert main_window.main_content.get_current_page() == INTENT_CONFIRMATION
