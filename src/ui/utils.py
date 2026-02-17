"""
UI 工具函数
"""

from PyQt6.QtWidgets import QWidget


def center_widget(widget: QWidget) -> None:
    """将窗口居中显示"""
    widget.adjustSize()
    screen = widget.screen()
    if screen:
        geo = screen.availableGeometry()
        x = (geo.width() - widget.width()) // 2
        y = (geo.height() - widget.height()) // 2
        widget.move(x, y)
