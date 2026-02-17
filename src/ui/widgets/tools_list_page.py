"""
工具列表页面 (Claude 风格)

提供工具管理界面，包括：
- 搜索框
- 工具卡片网格布局
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QGridLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal
from src.utils.logger import get_logger


class ToolCard(QWidget):
    """工具卡片组件"""

    execute_requested = pyqtSignal(str)  # 执行请求信号

    def __init__(self, tool_name: str, tool_description: str, parent=None):
        super().__init__(parent)
        self.tool_name = tool_name
        self.tool_description = tool_description
        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        self.setObjectName("tool_card")
        self.setFixedSize(300, 150)

        # 创建主布局
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 工具名称
        name_label = QLabel(self.tool_name)
        name_label.setObjectName("tool_name")
        name_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50;")
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        # 工具描述
        desc_label = QLabel(self.tool_description)
        desc_label.setObjectName("tool_description")
        desc_label.setStyleSheet("font-size: 13px; color: #7f8c8d;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label, 1)  # stretch=1

        # 执行按钮
        execute_btn = QPushButton("▶️ 执行")
        execute_btn.setObjectName("tool_execute_button")
        execute_btn.clicked.connect(lambda: self.execute_requested.emit(self.tool_name))
        layout.addWidget(execute_btn)


class ToolsListPage(QWidget):
    """工具列表页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tool_cards = []
        self.init_ui()
        self._load_sample_tools()

    def init_ui(self):
        """初始化用户界面"""
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # 页面标题
        title_label = QLabel("工具列表")
        title_label.setObjectName("tools_title")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        main_layout.addWidget(title_label)

        # 搜索框
        search_layout = QHBoxLayout()
        search_layout.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索工具...")
        self.search_input.setObjectName("tools_search_input")
        self.search_input.setFixedWidth(400)
        self.search_input.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_input)

        search_layout.addStretch()
        main_layout.addLayout(search_layout)

        # 创建滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setObjectName("tools_scroll")

        # 滚动内容
        scroll_content = QWidget()
        self.tools_grid = QGridLayout(scroll_content)
        self.tools_grid.setSpacing(16)
        self.tools_grid.setContentsMargins(0, 0, 0, 0)

        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll, 1)  # stretch=1

    def _load_sample_tools(self):
        """加载示例工具"""
        sample_tools = [
            {
                "name": "网页截图",
                "description": "截取指定 URL 的网页截图，支持整页和可视区域截图。"
            },
            {
                "name": "数据提取",
                "description": "从网页中提取结构化数据，支持表格、列表等格式。"
            },
            {
                "name": "表单填写",
                "description": "自动填写网页表单，支持文本输入、下拉选择、复选框等。"
            },
            {
                "name": "点击操作",
                "description": "模拟鼠标点击操作，支持多种定位策略。"
            },
            {
                "name": "文本输入",
                "description": "在输入框中自动输入文本内容。"
            },
            {
                "name": "页面滚动",
                "description": "控制页面滚动到指定位置或元素。"
            },
        ]

        for i, tool in enumerate(sample_tools):
            card = ToolCard(tool["name"], tool["description"])
            card.execute_requested.connect(self._on_tool_execute)

            # 添加到网格布局 (2列)
            row = i // 2
            col = i % 2
            self.tools_grid.addWidget(card, row, col)

            self.tool_cards.append(card)

        # 添加弹性空间到右侧
        self.tools_grid.setColumnStretch(0, 1)
        self.tools_grid.setColumnStretch(1, 1)

    def _on_search_changed(self, text: str):
        """搜索框内容变化"""
        search_text = text.lower()

        for card in self.tool_cards:
            # 显示或隐藏卡片
            should_show = (
                search_text in card.tool_name.lower() or
                search_text in card.tool_description.lower()
            )
            card.setVisible(should_show)

    def _on_tool_execute(self, tool_name: str):
        """工具执行请求"""
        self.logger.info(f"执行工具: {tool_name}")
        # TODO: 实现工具执行逻辑
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "执行工具",
            f"执行「{tool_name}」功能即将推出！\n\n请使用命令行模式：\nuv run python -m src.main interactive"
        )

    @property
    def logger(self):
        """日志记录器属性"""
        return get_logger(__name__)

