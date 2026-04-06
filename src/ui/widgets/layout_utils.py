"""
布局工具函数

提供跨组件共享的布局操作，避免在多个 UI 组件中重复相同的模式。
"""

from PyQt6.QtWidgets import QLayout, QScrollArea


def clear_layout(layout: QLayout) -> None:
    """清空布局中的所有子 widget 并安全删除。

    Args:
        layout: 要清空的布局对象
    """
    while layout.count():
        child = layout.takeAt(0)
        if child.widget():
            child.widget().deleteLater()


def scroll_to_bottom(scroll_area_name: str, parent_widget) -> None:
    """将指定名称的 QScrollArea 滚动到底部。

    Args:
        scroll_area_name: QScrollArea 的 objectName
        parent_widget: 包含该 QScrollArea 的父 widget
    """
    scroll_area = parent_widget.findChild(QScrollArea, scroll_area_name)
    if scroll_area:
        scrollbar = scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
