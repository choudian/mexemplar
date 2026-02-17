"""
对话小部件测试
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

    from src.ui.widgets.chat_widget import ChatWidget

    widget = ChatWidget()
    qtbot.addWidget(widget)
    yield widget
    app.quit()


def test_chat_widget_creation(app):
    """测试对话小部件创建"""
    assert app is not None
    assert app.windowTitle() == ""  # ChatWidget 没有设置标题


def test_chat_widget_has_components(app):
    """测试对话小部件包含所有组件"""
    # 检查关键组件存在
    assert hasattr(app, "back_button")
    assert hasattr(app, "chat_history_list")
    assert hasattr(app, "message_input")
    assert hasattr(app, "send_button")
    assert hasattr(app, "new_chat_button")


def test_send_button_initially_disabled(app):
    """测试发送按钮初始状态为禁用"""
    assert not app.send_button.isEnabled()


def test_send_button_enabled_on_input(app, qtbot):
    """测试输入内容后发送按钮启用"""
    app.message_input.setPlainText("测试消息")
    qtbot.wait(50)
    assert app.send_button.isEnabled()


def test_new_chat_clears_messages(app, qtbot):
    """测试新建对话清空消息"""
    # 添加一些消息
    app._add_message("user", "测试消息")
    assert app.messages_layout.count() > 1  # 欢迎消息 + 测试消息

    # 点击新建对话
    app.on_new_chat()
    qtbot.wait(50)

    # 应该只剩下欢迎消息
    assert app.messages_layout.count() == 1


def test_back_signal_emission(app, qtbot):
    """测试返回信号发射"""
    with qtbot.waitSignal(app.back_requested, timeout=1000):
        app.back_button.click()
