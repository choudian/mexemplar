"""
UI 工具函数
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter


def create_svg_icon(svg_string: str, color: str = "#666666", size: int = 20) -> QIcon:
    """从 SVG 字符串创建 QIcon

    Args:
        svg_string: SVG 字符串
        color: 图标颜色（十六进制）
        size: 图标尺寸

    Returns:
        QIcon 对象
    """
    try:
        from PyQt6.QtSvg import QSvgRenderer

        svg_with_color = svg_string.replace('fill="currentColor"', f'fill="{color}"')
        renderer = QSvgRenderer(svg_with_color.encode())

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()

        return QIcon(pixmap)
    except ImportError:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        return QIcon(pixmap)
