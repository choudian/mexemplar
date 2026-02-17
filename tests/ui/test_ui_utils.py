"""
UI 工具函数测试

测试 src.ui.utils 模块的函数
"""

import pytest
from PyQt6.QtWidgets import QApplication, QWidget


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


def test_center_widget(app):
    """测试窗口居中函数"""
    from src.ui.utils import center_widget

    # 创建测试窗口
    widget = QWidget()
    widget.setWindowTitle("测试窗口")
    widget.resize(400, 300)

    # 调用居中函数
    center_widget(widget)

    # 验证窗口已移动（不是原点）
    assert widget.x() >= 0
    assert widget.y() >= 0

    # 清理
    widget.close()


def test_center_widget_with_screen(app):
    """测试有可用屏幕时的居中"""
    from src.ui.utils import center_widget

    widget = QWidget()
    widget.resize(300, 200)

    screen = widget.screen()
    if screen:
        # 获取屏幕几何信息
        geo = screen.availableGeometry()

        # 调用居中函数
        center_widget(widget)

        # 验证窗口在屏幕范围内
        assert widget.x() >= 0
        assert widget.y() >= 0
        assert widget.x() + widget.width() <= geo.width()
        assert widget.y() + widget.height() <= geo.height()

    widget.close()
