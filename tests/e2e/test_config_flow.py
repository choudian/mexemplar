import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QDialogButtonBox, QLineEdit, QPushButton

from src.ui.page_ids import SETTINGS

pytestmark = pytest.mark.e2e


def test_main_window_startup(main_window, robot):
    assert main_window.isVisible()
    assert robot.ui.find_widget(QPushButton, "新建对话") is not None
    assert robot.ui.find_widget(QPushButton, "会话列表") is not None
    assert robot.ui.find_widget(QPushButton, "技能教学") is not None
    assert robot.ui.find_widget(QPushButton, "技能列表") is not None
    assert robot.ui.find_widget(QPushButton, "设置") is not None


def test_api_key_round_trip(main_window, robot, isolated_runtime):
    robot.ui.click_sidebar_page(SETTINGS)
    settings_page = main_window.main_content.get_page(SETTINGS)

    assert settings_page.api_key_input.echoMode() == QLineEdit.EchoMode.Password

    robot.ui.fill(settings_page.api_key_input, "sk-test-key")
    QTimer.singleShot(
        100,
        lambda: robot.ui.click_dialog_button(QDialogButtonBox.StandardButton.Ok),
    )
    robot.ui.click_button("保存设置")

    assert (
        isolated_runtime.keyring.get_password(
            isolated_runtime.keyring_service_name,
            "anthropic_api_key",
        )
        == "sk-test-key"
    )

    robot.ui.fill(settings_page.api_key_input, "")
    QTimer.singleShot(
        100,
        lambda: robot.ui.click_dialog_button(QDialogButtonBox.StandardButton.Ok),
    )
    robot.ui.click_button("保存设置")

    assert (
        isolated_runtime.keyring.get_password(
            isolated_runtime.keyring_service_name,
            "anthropic_api_key",
        )
        is None
    )


def test_settings_persistence(main_window, robot):
    from src.ui.main_window import MainWindow
    import src.data.unified_config as unified_config_module

    robot.ui.click_sidebar_page(SETTINGS)
    settings_page = main_window.main_content.get_page(SETTINGS)

    target_model = "claude-opus-4-5-20251101"
    model_index = settings_page.model_combo.findData(target_model)
    assert model_index >= 0
    rec_mode_index = settings_page.rec_mode_combo.findData("desktop")
    assert rec_mode_index >= 0

    settings_page.model_combo.setCurrentIndex(model_index)
    settings_page.timeout_spin.setValue(90)
    settings_page.rec_mode_combo.setCurrentIndex(rec_mode_index)
    settings_page.start_url_input.setText("https://example.com/persisted")

    QTimer.singleShot(
        100,
        lambda: robot.ui.click_dialog_button(QDialogButtonBox.StandardButton.Ok),
    )
    robot.ui.click_button("保存设置")

    main_window.close()
    QTest.qWait(400)

    unified_config_module._unified_config_manager = None

    reloaded_window = MainWindow()
    reloaded_window.show()
    reloaded_window.resize(1280, 800)
    QTest.qWait(600)

    try:
        reloaded_window.main_content.switch_page(SETTINGS)
        reloaded_settings = reloaded_window.main_content.get_page(SETTINGS)
        assert reloaded_settings.model_combo.currentData() == target_model
        assert reloaded_settings.timeout_spin.value() == 90
        assert reloaded_settings.rec_mode_combo.currentData() == "desktop"
        assert reloaded_settings.start_url_input.text() == "https://example.com/persisted"
    finally:
        reloaded_window.close()
        QTest.qWait(400)
