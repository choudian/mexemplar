"""
侧边栏组件 (Claude 风格)

提供左侧导航栏，包括：
- 应用头部 (Logo + 标题)
- 导航按钮 (会话列表、录制、工具、设置)
- 底部用户信息
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont
from src.ui.resources.icons.sidebar_icons import (
    NEW_CHAT_ICON,
    CHAT_ICON,
    RECORDING_ICON,
    SETTINGS_ICON,
    USER_ICON,
    PENDING_TOOLS_ICON,
)
from src.ui.page_ids import CONVERSATIONS, TEACHING, SKILLS, SETTINGS
from src.ui.utils import create_svg_icon
from src.utils.logger import get_logger


class SidebarWidget(QWidget):
    """侧边栏组件"""

    # 定义信号
    navigation_requested = pyqtSignal(str)  # 导航请求 (page_name)
    new_chat_requested = pyqtSignal()  # 新建对话请求

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)
        self.current_page = None  # 启动时不选中任何页面
        self.nav_buttons = {}  # 导航按钮字典
        self.init_ui()

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

        # 会话列表按钮
        self.chat_btn = self._create_nav_button(
            CHAT_ICON,
            "会话列表",
            CONVERSATIONS
        )
        nav_layout.addWidget(self.chat_btn)

        # 录制按钮
        self.recording_btn = self._create_nav_button(
            RECORDING_ICON,
            "技能教学",
            TEACHING
        )
        nav_layout.addWidget(self.recording_btn)

        # 工具列表按钮（待试用工具）
        self.pending_tools_btn = self._create_nav_button(
            PENDING_TOOLS_ICON,
            "技能列表",
            SKILLS
        )
        nav_layout.addWidget(self.pending_tools_btn)

        # 设置按钮
        self.settings_btn = self._create_nav_button(
            SETTINGS_ICON,
            "设置",
            SETTINGS
        )
        nav_layout.addWidget(self.settings_btn)

        main_layout.addWidget(nav_container)

        # 弹性空间 — 将底部用户信息推到最下方
        main_layout.addStretch(1)

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
        user_avatar_btn.setIcon(create_svg_icon(USER_ICON, "#666666", size=16))
        user_avatar_btn.setIconSize(QSize(20, 20))
        user_avatar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        footer_layout.addWidget(user_avatar_btn)

        # 用户信息
        user_info = QLabel("用户")
        user_info.setObjectName("user_info")
        user_info.setFont(QFont("Microsoft YaHei", 10))
        footer_layout.addWidget(user_info, 1)  # stretch=1

        main_layout.addWidget(footer)

    def _create_nav_button(self, icon: str, text: str, page_name: str) -> QPushButton:
        """创建导航按钮"""
        button = QPushButton(text)
        button.setObjectName("nav_button")
        button.setCheckable(True)
        button.setProperty("page_name", page_name)
        button.setIcon(create_svg_icon(icon, "#666666", size=16))
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
        # 取消所有按钮的选中状态（新建对话是动作按钮，不是菜单项）
        for button in self.nav_buttons.values():
            button.setChecked(False)
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
