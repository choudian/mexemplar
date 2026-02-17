"""
录制界面组件单元测试

测试 RecordingWidget 类的基本功能
"""

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture
def app():
    """创建 QApplication 实例"""
    if not QApplication.instance():
        app_instance = QApplication([])
    else:
        app_instance = QApplication.instance()
    yield app_instance
    # 清理
    app_instance.quit()


def test_recording_widget_creation(app):
    """测试录制界面创建"""
    from src.ui.widgets.recording_widget import RecordingWidget

    widget = RecordingWidget()
    assert widget is not None
    assert widget.record_btn is not None
    assert widget.stop_btn is not None


def test_recording_widget_initial_state(app):
    """测试初始状态"""
    from src.ui.widgets.recording_widget import RecordingWidget

    widget = RecordingWidget()
    assert widget.record_btn.isEnabled()
    assert not widget.stop_btn.isEnabled()


def test_recording_widget_has_title(app):
    """测试录制界面有标题"""
    from src.ui.widgets.recording_widget import RecordingWidget
    from PyQt6.QtWidgets import QLabel

    widget = RecordingWidget()
    labels = widget.findChildren(QLabel)

    # 应该有标题标签
    label_texts = [label.text() for label in labels]
    assert any("录制操作" in text for text in label_texts)


def test_recording_widget_has_mode_selector(app):
    """测试录制界面有模式选择器"""
    from src.ui.widgets.recording_widget import RecordingWidget
    from PyQt6.QtWidgets import QComboBox

    widget = RecordingWidget()
    combo_boxes = widget.findChildren(QComboBox)

    # 应该有模式选择下拉框
    assert len(combo_boxes) > 0


def test_recording_widget_has_url_input(app):
    """测试录制界面有 URL 输入框"""
    from src.ui.widgets.recording_widget import RecordingWidget
    from PyQt6.QtWidgets import QLineEdit

    widget = RecordingWidget()
    line_edits = widget.findChildren(QLineEdit)

    # 应该有 URL 输入框
    assert len(line_edits) > 0


def test_recording_widget_has_progress_bar(app):
    """测试录制界面有进度条"""
    from src.ui.widgets.recording_widget import RecordingWidget
    from PyQt6.QtWidgets import QProgressBar

    widget = RecordingWidget()
    progress_bars = widget.findChildren(QProgressBar)

    # 应该有进度条
    assert len(progress_bars) > 0


def test_recording_widget_mode_options(app):
    """测试录制模式选项"""
    from src.ui.widgets.recording_widget import RecordingWidget
    from PyQt6.QtWidgets import QComboBox

    widget = RecordingWidget()
    combo_boxes = widget.findChildren(QComboBox)

    # 找到模式选择器
    mode_combo = None
    for combo in combo_boxes:
        if "browser" in combo.objectName().lower() or "mode" in combo.objectName().lower():
            mode_combo = combo
            break

    if mode_combo is None and len(combo_boxes) > 0:
        mode_combo = combo_boxes[0]

    assert mode_combo is not None
    assert mode_combo.count() >= 2


def test_recording_widget_buttons_count(app):
    """测试录制界面按钮数量"""
    from src.ui.widgets.recording_widget import RecordingWidget
    from PyQt6.QtWidgets import QPushButton

    widget = RecordingWidget()
    buttons = widget.findChildren(QPushButton)

    # 应该有开始和停止按钮
    assert len(buttons) >= 2


def test_recording_widget_has_status_text(app):
    """测试录制界面有状态文本区域"""
    from src.ui.widgets.recording_widget import RecordingWidget
    from PyQt6.QtWidgets import QTextEdit

    widget = RecordingWidget()
    text_edits = widget.findChildren(QTextEdit)

    # 应该有状态文本显示区域
    assert len(text_edits) > 0
