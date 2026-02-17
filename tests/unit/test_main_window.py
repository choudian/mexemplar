"""
主窗口单元测试

测试 MainWindow 类的基本功能
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


def test_main_window_creation(app):
    """测试主窗口创建"""
    from src.ui.main_window import MainWindow

    window = MainWindow()
    assert window is not None
    assert window.windowTitle() == "Mexemplar"


def test_main_window_has_menu(app):
    """测试主窗口有菜单栏"""
    from src.ui.main_window import MainWindow

    window = MainWindow()
    assert window.menuBar() is not None


def test_main_window_minimum_size(app):
    """测试主窗口最小尺寸"""
    from src.ui.main_window import MainWindow

    window = MainWindow()
    min_size = window.minimumSize()
    assert min_size.width() == 900
    assert min_size.height() == 600


def test_main_window_has_buttons(app):
    """测试主窗口有 4 个功能按钮"""
    from src.ui.main_window import MainWindow
    from PyQt6.QtWidgets import QPushButton

    window = MainWindow()

    # 检查主页面的 4 个功能按钮（通过 objectName 过滤）
    record_button = window.findChild(QPushButton, "record_button")
    execute_button = window.findChild(QPushButton, "execute_button")
    tools_button = window.findChild(QPushButton, "tools_button")
    settings_button = window.findChild(QPushButton, "settings_button")

    # 验证按钮存在
    assert record_button is not None
    assert execute_button is not None
    assert tools_button is not None
    assert settings_button is not None

    # 验证按钮文本（包含 emoji）
    assert record_button.text() == "📹 开始录制"
    assert execute_button.text() == "▶️ 执行工具"
    assert tools_button.text() == "📊 工具列表"
    assert settings_button.text() == "⚙️ 设置"


def test_main_window_has_welcome_label(app):
    """测试主窗口有欢迎标签"""
    from src.ui.main_window import MainWindow
    from PyQt6.QtWidgets import QLabel

    window = MainWindow()
    labels = window.findChildren(QLabel)

    # 应该有欢迎标签
    label_texts = [label.text() for label in labels]
    assert any("欢迎使用 Mexemplar" in text for text in label_texts)


def test_main_window_menus(app):
    """测试主窗口菜单项"""
    from src.ui.main_window import MainWindow

    window = MainWindow()
    menu_bar = window.menuBar()

    # PyQt6 中菜单通过不同的方式获取
    assert menu_bar is not None


def test_main_window_about_action(app):
    """测试关于动作存在"""
    from src.ui.main_window import MainWindow

    window = MainWindow()

    # 获取帮助菜单
    help_menu = None
    for action in window.menuBar().actions():
        if action.text() == "帮助(&H)":
            help_menu = action.menu()
            break

    assert help_menu is not None

    # 查找关于动作
    about_action = None
    for action in help_menu.actions():
        if action.text() == "关于(&A)":
            about_action = action
            break

    assert about_action is not None
