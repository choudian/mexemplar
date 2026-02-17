"""
主内容区容器 (Claude 风格)

使用 QStackedWidget 管理多个页面：
- ChatPage (AI 对话)
- RecordingPage (录制)
- ToolsListPage (工具列表)
- SettingsPage (设置)
"""

from PyQt6.QtWidgets import (
    QWidget,
    QStackedWidget,
    QVBoxLayout,
)
from PyQt6.QtCore import pyqtSignal
from src.utils.logger import get_logger


class MainContentWidget(QWidget):
    """主内容区容器"""

    # 定义信号
    page_changed = pyqtSignal(str)  # 页面切换信号 (page_name)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pages = {}  # 页面字典
        self.current_page = None
        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 创建 QStackedWidget
        self.stack = QStackedWidget()
        self.stack.setObjectName("main_content_stack")
        main_layout.addWidget(self.stack)

    def add_page(self, page_name: str, page_widget: QWidget):
        """添加页面

        Args:
            page_name: 页面名称
            page_widget: 页面组件
        """
        if page_name in self.pages:
            self.logger.warning(f"页面 {page_name} 已存在，将被覆盖")

        self.pages[page_name] = page_widget
        self.stack.addWidget(page_widget)
        self.logger.info(f"已添加页面: {page_name}")

    def switch_page(self, page_name: str):
        """切换页面

        Args:
            page_name: 页面名称
        """
        if page_name not in self.pages:
            self.logger.error(f"页面 {page_name} 不存在")
            return

        # 切换页面
        page_widget = self.pages[page_name]
        self.stack.setCurrentWidget(page_widget)
        self.current_page = page_name

        # 发出信号
        self.page_changed.emit(page_name)
        self.logger.info(f"已切换到页面: {page_name}")

    def get_current_page(self) -> str:
        """获取当前页面名称"""
        return self.current_page

    def get_page(self, page_name: str) -> QWidget:
        """获取指定页面组件

        Args:
            page_name: 页面名称

        Returns:
            页面组件，如果不存在则返回 None
        """
        return self.pages.get(page_name)

    @property
    def logger(self):
        """日志记录器属性"""
        return get_logger(__name__)
