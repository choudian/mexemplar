"""
集成测试：GUI 启动

验证 GUI 模式可以正常启动
"""

import subprocess
import sys


def test_gui_help():
    """测试 --help 包含 GUI 选项"""
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "--help"],
        capture_output=True,
        # 不使用 text=True，避免编码问题
    )

    # 手动解码，忽略编码错误
    stdout_text = result.stdout.decode("utf-8", errors="ignore")

    assert result.returncode == 0
    assert "--gui" in stdout_text


def test_gui_import():
    """测试 GUI 模块导入"""
    from PyQt6.QtWidgets import QApplication
    from src.ui.main_window import MainWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    window = MainWindow()
    assert window is not None
    assert window.windowTitle() == "Mexemplar"
    assert window.minimumSize().width() == 900
    assert window.minimumSize().height() == 600

    # 验证主页面功能按钮存在
    from PyQt6.QtWidgets import QPushButton

    record_button = window.findChild(QPushButton, "record_button")
    execute_button = window.findChild(QPushButton, "execute_button")
    tools_button = window.findChild(QPushButton, "tools_button")
    settings_button = window.findChild(QPushButton, "settings_button")

    assert record_button is not None
    assert execute_button is not None
    assert tools_button is not None
    assert settings_button is not None

    # 验证菜单栏存在
    assert window.menuBar() is not None

    # 清理
    app.quit()


if __name__ == "__main__":
    test_gui_help()
    print("✓ test_gui_help passed")

    test_gui_import()
    print("✓ test_gui_import passed")

    print("\n所有 GUI 集成测试通过！")
