"""
侧边栏组件 (Claude 风格)

提供左侧导航栏，包括：
- 应用头部 (Logo + 标题)
- 导航按钮 (AI对话、录制、工具、设置)
- 对话历史区域 (仅在 AI 对话页面显示)
- 底部用户信息
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPainter
from src.ui.resources.icons.sidebar_icons import (
    NEW_CHAT_ICON,
    CHAT_ICON,
    RECORDING_ICON,
    SETTINGS_ICON,
    USER_ICON,
    PENDING_TOOLS_ICON,
)


class SidebarWidget(QWidget):
    """侧边栏组件"""

    # 定义信号
    navigation_requested = pyqtSignal(str)  # 导航请求 (page_name)
    new_chat_requested = pyqtSignal()  # 新建对话请求

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_page = "chat"  # 当前页面
        self.nav_buttons = {}  # 导航按钮字典
        self.init_ui()

    def _create_svg_icon(self, svg_string: str, color: str = "#ffffff") -> QIcon:
        """从 SVG 字符串创建 QIcon

        Args:
            svg_string: SVG 字符串
            color: 图标颜色（十六进制）

        Returns:
            QIcon 对象
        """
        try:
            from PyQt6.QtSvg import QSvgRenderer

            # 替换 currentColor 为指定颜色
            svg_with_color = svg_string.replace('fill="currentColor"', f'fill="{color}"')

            # 创建 SVG 渲染器
            renderer = QSvgRenderer(svg_with_color.encode())

            # 创建 pixmap
            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.GlobalColor.transparent)

            # 渲染 SVG
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()

            return QIcon(pixmap)
        except ImportError:
            # 如果没有 QSvgRenderer，返回空图标
            self.logger.warning("QSvgRenderer 不可用，使用空图标")
            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.GlobalColor.transparent)
            return QIcon(pixmap)

    def init_ui(self):
        """初始化用户界面"""
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 8, 0, 0)

        # ============ 导航按钮 ============
        nav_container = QWidget()
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setSpacing(0)
        nav_layout.setContentsMargins(0, 8, 0, 8)
        nav_layout.setAlignment(Qt.AlignmentFlag.AlignTop)  # 顶部对齐，防止被拉伸

        # 新建对话按钮
        self.new_chat_btn = self._create_nav_button(
            NEW_CHAT_ICON,
            "新建对话",
            "new_chat"
        )
        # 覆盖点击事件，发射 new_chat_requested 信号
        self.new_chat_btn.clicked.disconnect()
        self.new_chat_btn.clicked.connect(self._on_new_chat_clicked)
        nav_layout.addWidget(self.new_chat_btn)

        # AI 对话按钮
        self.chat_btn = self._create_nav_button(
            CHAT_ICON,
            "AI 对话",
            "chat"
        )
        nav_layout.addWidget(self.chat_btn)

        # 录制按钮
        self.recording_btn = self._create_nav_button(
            RECORDING_ICON,
            "技能教学",
            "recording"
        )
        nav_layout.addWidget(self.recording_btn)

        # 工具列表按钮（待试用工具）
        self.pending_tools_btn = self._create_nav_button(
            PENDING_TOOLS_ICON,
            "技能列表",
            "pending_tools"
        )
        nav_layout.addWidget(self.pending_tools_btn)

        # 设置按钮
        self.settings_btn = self._create_nav_button(
            SETTINGS_ICON,
            "设置",
            "settings"
        )
        nav_layout.addWidget(self.settings_btn)

        main_layout.addWidget(nav_container)

        # 分隔线
        separator2 = QFrame()
        separator2.setObjectName("sidebar_separator")
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(separator2)

        # ============ 对话历史区域 ============
        self.chat_history_container = QWidget()
        self.chat_history_container.setObjectName("chat_history_container")
        history_layout = QVBoxLayout(self.chat_history_container)
        history_layout.setContentsMargins(12, 8, 12, 8)
        history_layout.setSpacing(8)

        # 对话历史标题
        history_title = QLabel("对话历史")
        history_title.setObjectName("history_title")
        history_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #7f8c8d;")
        history_layout.addWidget(history_title)

        # 对话历史列表
        self.chat_history_list = QListWidget()
        self.chat_history_list.setObjectName("chat_history_list")

        # 添加示例对话
        self._load_sample_chats()

        history_layout.addWidget(self.chat_history_list, 1)  # stretch=1

        main_layout.addWidget(self.chat_history_container)  # 移除 stretch，避免布局重分配

        # ============ 底部用户信息 ============
        footer = QWidget()
        footer.setObjectName("sidebar_footer")
        footer.setFixedHeight(50)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 8, 12, 8)

        # 用户头像（使用 SVG 图标）
        user_avatar_btn = QPushButton()
        user_avatar_btn.setObjectName("user_avatar_button")
        user_avatar_btn.setFixedSize(28, 28)
        user_avatar_btn.setIcon(self._create_svg_icon(USER_ICON, "#666666"))
        user_avatar_btn.setIconSize(QSize(20, 20))
        user_avatar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        footer_layout.addWidget(user_avatar_btn)

        # 用户信息
        user_info = QLabel("用户")
        user_info.setObjectName("user_info")
        user_info.setFont(QFont("Microsoft YaHei", 10))
        footer_layout.addWidget(user_info, 1)  # stretch=1

        main_layout.addWidget(footer)

        # 设置初始选中状态
        self._set_active_page("chat")

    def _create_nav_button(self, icon: str, text: str, page_name: str) -> QPushButton:
        """创建导航按钮"""
        button = QPushButton(text)
        button.setObjectName("nav_button")
        button.setCheckable(True)
        button.setProperty("page_name", page_name)
        button.setIcon(self._create_svg_icon(icon, "#666666"))
        button.setIconSize(QSize(20, 20))
        button.clicked.connect(lambda: self._on_nav_clicked(page_name))

        # 保存到字典
        self.nav_buttons[page_name] = button

        return button

    def _on_nav_clicked(self, page_name: str):
        """导航按钮点击"""
        self.logger.info(f"导航到页面: {page_name}")
        self._set_active_page(page_name)
        self.navigation_requested.emit(page_name)

    def _on_new_chat_clicked(self):
        """新建对话按钮点击"""
        self.logger.info("点击新建对话")
        # 取消所有导航按钮的选中状态
        for name, button in self.nav_buttons.items():
            button.setChecked(False)
        self.new_chat_btn.setChecked(True)  # 只选中"新建对话"
        self.new_chat_requested.emit()

    def _set_active_page(self, page_name: str):
        """设置当前活动页面"""
        self.current_page = page_name

        # 更新按钮状态（不包括"新建对话"按钮）
        for name, button in self.nav_buttons.items():
            if name != "new_chat":  # "新建对话"不是页面导航按钮
                button.setChecked(name == page_name)

        # 如果切换到其他页面，取消"新建对话"的选中状态
        if page_name != "new_chat":
            self.new_chat_btn.setChecked(False)

        # 控制对话历史区域显示/隐藏（使用 setVisible 保持布局稳定）
        if page_name == "chat":
            self.chat_history_container.setVisible(True)
        else:
            self.chat_history_container.setVisible(False)

    def _load_sample_chats(self):
        """加载示例对话历史"""
        sample_chats = [
            "技能教学帮助",
            "如何执行工具?",
            "配置 API Key",
            "浏览器设置",
        ]

        for chat_title in sample_chats:
            item = QListWidgetItem(chat_title)
            self.chat_history_list.addItem(item)

    def get_logger(self):
        """获取日志记录器"""
        from src.utils.logger import get_logger
        return get_logger(__name__)

    @property
    def logger(self):
        """日志记录器属性"""
        return self.get_logger()
