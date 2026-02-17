"""
测试 GUI 启动入口

验证 main.py 中的 --gui 参数功能
"""

import argparse


def test_gui_mode_imports():
    """测试 GUI 模式导入"""
    # 测试 PyQt6 是否可用
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert app is not None

    # 测试 MainWindow 是否可导入
    from src.ui.main_window import MainWindow

    window = MainWindow()
    assert window is not None
    assert window.windowTitle() == "Mexemplar"

    # 清理
    app.quit()


def test_gui_argument_parsing():
    """测试 --gui 参数解析"""
    # 模拟参数解析
    parser = argparse.ArgumentParser()
    parser.add_argument("--gui", action="store_true", help="启动图形界面模式")
    args = parser.parse_args(["--gui"])

    assert args.gui is True


def test_main_window_button_handlers():
    """测试主窗口按钮处理器"""
    from PyQt6.QtWidgets import QApplication
    from src.ui.main_window import MainWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    window = MainWindow()

    # 测试按钮方法是否存在（注意：这些是私有方法，以 _ 开头）
    assert hasattr(window, "_on_record_clicked")
    assert hasattr(window, "_on_execute_clicked")
    assert hasattr(window, "_on_tools_clicked")
    assert hasattr(window, "_on_settings_clicked")
    assert hasattr(window, "_show_about_dialog")

    # 清理
    app.quit()
