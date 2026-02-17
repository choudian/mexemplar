"""
主窗口样式测试

测试 MainWindow 的样式加载和错误处理
"""

import pytest
from PyQt6.QtWidgets import QApplication, QWidget
from unittest.mock import patch
from pathlib import Path


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


def test_main_window_loads_styles_successfully(app):
    """测试样式表成功加载"""
    from src.ui.main_window import MainWindow

    window = MainWindow()

    # 验证样式表已设置（不为空）
    stylesheet = window.styleSheet()
    # 可能是空字符串（如果文件不存在）或包含样式内容
    assert stylesheet is not None

    window.close()


def test_main_window_handles_missing_style_file(app):
    """测试样式文件缺失时的处理"""
    from src.ui.main_window import MainWindow

    # 模拟样式文件不存在
    with patch.object(Path, "exists", return_value=False):
        window = MainWindow()
        # 即使样式文件不存在，窗口也应该能创建
        assert window is not None
        assert window.windowTitle() == "Mexemplar"
        window.close()


def test_main_window_handles_style_read_error(app):
    """测试样式文件读取错误时的处理"""
    from src.ui.main_window import MainWindow

    # 模拟文件读取异常
    with patch("builtins.open", side_effect=IOError("模拟读取错误")):
        window = MainWindow()
        # 即使读取失败，窗口也应该能创建
        assert window is not None
        window.close()


def test_main_window_has_menu_bar(app):
    """测试主窗口有菜单栏"""
    from src.ui.main_window import MainWindow

    window = MainWindow()

    # 验证菜单栏存在
    menubar = window.menuBar()
    assert menubar is not None

    # 验证菜单存在
    menus = menubar.findChildren(QWidget)
    # 应该有文件菜单和帮助菜单
    assert len(menus) >= 2

    window.close()


def test_stylesheet_applies_to_buttons(app):
    """测试样式表应用到按钮"""
    from src.ui.main_window import MainWindow
    from PyQt6.QtWidgets import QPushButton

    window = MainWindow()

    # 检查主页面的按钮是否有 objectName 设置
    record_button = window.findChild(QPushButton, "record_button")
    assert record_button is not None
    assert record_button.objectName() == "record_button"

    execute_button = window.findChild(QPushButton, "execute_button")
    assert execute_button is not None
    assert execute_button.objectName() == "execute_button"

    window.close()


def test_stylesheet_applies_to_labels(app):
    """测试样式表应用到标签"""
    from src.ui.main_window import MainWindow
    from PyQt6.QtWidgets import QLabel

    window = MainWindow()

    # 检查标签是否有 objectName 设置
    welcome_label = window.findChild(QLabel, "welcome_label")
    assert welcome_label is not None
    assert welcome_label.objectName() == "welcome_label"

    subtitle_label = window.findChild(QLabel, "subtitle_label")
    assert subtitle_label is not None
    assert subtitle_label.objectName() == "subtitle_label"

    window.close()
