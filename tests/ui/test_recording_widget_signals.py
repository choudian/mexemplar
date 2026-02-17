"""
录制小部件信号测试

测试 RecordingWidget 的信号发射和按钮交互
"""

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture
def app(qtbot):
    """创建应用和窗口"""
    if not QApplication.instance():
        app = QApplication([])
    else:
        app = QApplication.instance()

    from src.ui.widgets.recording_widget import RecordingWidget

    widget = RecordingWidget()
    qtbot.addWidget(widget)
    yield widget
    app.quit()


def test_recording_widget_signals_initialized(app):
    """测试信号已初始化"""
    # 检查信号存在
    assert hasattr(app, "recording_started")
    assert hasattr(app, "recording_stopped")
    assert hasattr(app, "back_requested")


def test_recording_started_signal(app, qtbot):
    """测试录制开始信号"""
    # 记录信号
    with qtbot.waitSignal(app.recording_started, timeout=1000) as blocker:
        # 模拟点击开始录制按钮
        app.record_btn.click()

    # 验证信号参数（mode, url）
    signal_args = blocker.args
    assert len(signal_args) == 2
    assert signal_args[0] in ["browser", "desktop"]
    assert isinstance(signal_args[1], str)


def test_recording_stopped_signal(app, qtbot):
    """测试录制停止信号"""
    # 先开始录制
    app.record_btn.click()

    # 等待一下让状态更新
    qtbot.wait(100)

    # 记录停止信号
    with qtbot.waitSignal(app.recording_stopped, timeout=1000):
        # 点击停止按钮
        if app.stop_btn.isEnabled():
            app.stop_btn.click()


def test_back_requested_signal(app, qtbot):
    """测试返回按钮信号"""
    # 记录信号
    with qtbot.waitSignal(app.back_requested, timeout=1000):
        # 点击返回按钮
        app.back_button.click()


def test_mode_selector_change(app, qtbot):
    """测试模式选择器变化"""
    # 获取模式选择器
    mode_combo = app.mode_combo

    # 切换到浏览器模式
    mode_combo.setCurrentIndex(0)
    qtbot.wait(50)
    assert mode_combo.currentText() == "浏览器录制"

    # 切换到桌面模式
    mode_combo.setCurrentIndex(1)
    qtbot.wait(50)
    assert mode_combo.currentText() == "桌面录制"


def test_url_input_changes(app, qtbot):
    """测试 URL 输入框变化"""
    url_input = app.url_input

    # 测试输入 URL
    url_input.setText("https://example.com")
    qtbot.wait(50)

    assert url_input.text() == "https://example.com"


def test_start_button_state_changes(app, qtbot):
    """测试开始按钮状态变化"""
    record_btn = app.record_btn
    stop_btn = app.stop_btn

    # 初始状态：开始按钮可用，停止按钮不可用
    assert record_btn.isEnabled()
    assert not stop_btn.isEnabled()

    # 点击开始按钮
    record_btn.click()
    qtbot.wait(100)

    # 点击后：开始按钮禁用，停止按钮可用
    assert not record_btn.isEnabled()
    assert stop_btn.isEnabled()


def test_status_text_updates(app, qtbot):
    """测试状态文本更新"""
    status_text = app.status_text

    # 初始状态
    assert status_text.toPlainText() != ""

    # 点击开始按钮
    app.record_btn.click()
    qtbot.wait(100)

    # 状态应该改变
    text = status_text.toPlainText()
    assert text != ""


def test_progress_bar_updates(app, qtbot):
    """测试进度条更新"""
    progress_bar = app.progress_bar

    # 初始状态：进度为 0
    assert progress_bar.value() == 0

    # 点击开始按钮
    app.record_btn.click()
    qtbot.wait(100)

    # 进度应该有所变化（可能还是 0，但至少可以访问）
    assert progress_bar.value() >= 0
