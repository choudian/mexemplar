"""
待试用工具列表 UI 组件

提供待试用工具管理界面，包括：
1. 工具卡片展示（名称、描述、状态、创建时间、试用次数）
2. 操作：试用、删除、编辑名称/描述
3. 实时状态更新
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QGridLayout,
    QInputDialog,
    QMessageBox,
    QMenu,
    QTabWidget,
    QDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QAction
from typing import List, Optional
from datetime import datetime

from src.business.tool_trial.trial_models import PendingTool, PendingToolStatus
from src.utils.logger import get_logger
from src.data.models import Tool


class PendingToolCard(QWidget):
    """待试用工具卡片组件"""

    # 定义信号
    trial_requested = pyqtSignal(str)  # pending_tool_id
    delete_requested = pyqtSignal(str)  # pending_tool_id
    edit_requested = pyqtSignal(str)  # pending_tool_id

    def __init__(self, pending_tool: PendingTool, parent=None):
        super().__init__(parent)
        self.pending_tool = pending_tool
        self.logger = get_logger(__name__)
        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        self.setObjectName("pending_tool_card")
        self.setFixedSize(300, 220)  # 固定高度，确保所有卡片一致

        # 创建主布局
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # === 顶部：状态标签 + 更多操作 ===
        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)

        # 状态标签
        self.status_label = QLabel(self._get_status_text())
        self.status_label.setObjectName(f"pending_tool_status_{self.pending_tool.status.value}")
        top_layout.addWidget(self.status_label)

        top_layout.addStretch()

        # 更多操作按钮
        more_btn = QPushButton("⋮")
        more_btn.setObjectName("pending_tool_more_button")
        more_btn.setFixedSize(24, 24)
        more_btn.clicked.connect(self._show_more_menu)
        top_layout.addWidget(more_btn)

        layout.addLayout(top_layout)

        # === 工具名称（单行，超出省略）===
        name_label = QLabel(self.pending_tool.tool_name)
        name_label.setObjectName("pending_tool_name")
        name_label.setWordWrap(False)
        name_label.setProperty("elide", "right")  # 添加省略号标记
        layout.addWidget(name_label)

        # === 工具描述（固定高度，超出省略）===
        desc_label = QLabel(self.pending_tool.tool_description or "暂无描述")
        desc_label.setObjectName("pending_tool_description")
        desc_label.setWordWrap(True)
        desc_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        desc_label.setMaximumHeight(60)  # 固定最大高度
        layout.addWidget(desc_label)

        # 弹性空间（推动底部内容向下）
        layout.addStretch()

        # === 底部信息 ===
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(12)

        # 试用次数
        trial_count_label = QLabel(f"试用 {self.pending_tool.trial_count}/{self.pending_tool.max_trials}")
        trial_count_label.setObjectName("pending_tool_trial_count")
        bottom_layout.addWidget(trial_count_label)

        bottom_layout.addStretch()

        # 创建时间
        if self.pending_tool.created_at:
            time_str = self._format_time(self.pending_tool.created_at)
            time_label = QLabel(time_str)
            time_label.setObjectName("pending_tool_time")
            bottom_layout.addWidget(time_label)

        layout.addLayout(bottom_layout)

        # === 操作按钮（固定在底部）===
        if self._can_trial():
            trial_btn = QPushButton("开始试用")
            trial_btn.setObjectName("pending_tool_trial_button")
            trial_btn.setFixedHeight(36)  # 固定按钮高度
            trial_btn.clicked.connect(lambda: self.trial_requested.emit(self.pending_tool.pending_tool_id))
            layout.addWidget(trial_btn)
        elif self.pending_tool.status == PendingToolStatus.TRIAL_SUCCESS:
            promoted_label = QLabel("✅ 可提升为正式工具")
            promoted_label.setObjectName("pending_tool_promoted_label")
            promoted_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            promoted_label.setFixedHeight(36)
            layout.addWidget(promoted_label)
        elif self.pending_tool.status == PendingToolStatus.FAILED:
            failed_label = QLabel("❌ 试用失败")
            failed_label.setObjectName("pending_tool_failed_label")
            failed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            failed_label.setFixedHeight(36)
            layout.addWidget(failed_label)

    def _get_status_text(self) -> str:
        """获取状态文本"""
        status_map = {
            PendingToolStatus.PENDING_TRIAL: "⏳ 等待试用",
            PendingToolStatus.TRIALING: "🔄 试用中",
            PendingToolStatus.TRIAL_SUCCESS: "✅ 试用成功",
            PendingToolStatus.TRIAL_FAILED: "❌ 试用失败",
            PendingToolStatus.AWAITING_REAL_DATA: "📊 等待数据",
            PendingToolStatus.PROMOTED: "🎉 已提升",
            PendingToolStatus.FAILED: "💀 最终失败",
        }
        return status_map.get(self.pending_tool.status, "❓ 未知状态")

    def _format_time(self, dt: datetime) -> str:
        """格式化时间"""
        now = datetime.now()
        delta = now - dt

        if delta.days > 0:
            return f"{delta.days}天前"
        elif delta.seconds >= 3600:
            hours = delta.seconds // 3600
            return f"{hours}小时前"
        elif delta.seconds >= 60:
            minutes = delta.seconds // 60
            return f"{minutes}分钟前"
        else:
            return "刚刚"

    def _can_trial(self) -> bool:
        """是否可以试用"""
        return self.pending_tool.can_trial()

    def _show_more_menu(self):
        """显示更多操作菜单"""
        menu = QMenu(self)
        menu.setObjectName("pending_tool_more_menu")

        # 编辑操作
        edit_action = QAction("✏️ 编辑", self)
        edit_action.triggered.connect(lambda: self.edit_requested.emit(self.pending_tool.pending_tool_id))
        menu.addAction(edit_action)

        # 删除操作
        delete_action = QAction("🗑️ 删除", self)
        delete_action.triggered.connect(lambda: self.delete_requested.emit(self.pending_tool.pending_tool_id))
        menu.addAction(delete_action)

        # 显示菜单
        more_btn = self.findChild(QPushButton, "pending_tool_more_button")
        if more_btn:
            menu.exec(more_btn.mapToGlobal(more_btn.rect().bottomLeft()))

    def update_tool(self, pending_tool: PendingTool):
        """更新工具信息"""
        self.pending_tool = pending_tool

        # 更新状态标签
        self.status_label.setText(self._get_status_text())
        self.status_label.setObjectName(f"pending_tool_status_{pending_tool.status.value}")

        # 更新名称和描述
        name_label = self.findChild(QLabel, "pending_tool_name")
        if name_label:
            name_label.setText(pending_tool.tool_name)

        desc_label = self.findChild(QLabel, "pending_tool_description")
        if desc_label:
            desc_label.setText(pending_tool.tool_description or "暂无描述")

        # 重新初始化 UI（更新按钮状态）
        # 简单起见，重新创建整个布局
        layout = self.layout()
        if layout:
            while layout.count():
                child = layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            self.init_ui()


class PublishedToolCard(QWidget):
    """已发布工具卡片组件"""

    # 定义信号
    execute_requested = pyqtSignal(str)  # tool_id
    delete_requested = pyqtSignal(str)  # tool_id
    edit_requested = pyqtSignal(str)  # tool_id

    def __init__(self, tool: Tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.logger = get_logger(__name__)
        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        self.setObjectName("published_tool_card")
        self.setFixedSize(320, 200)

        # 创建主布局
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # === 顶部：更多操作 ===
        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)

        # 来源标签
        source_text = {
            "manual": "手动创建",
            "intent": "意图生成",
            "trial": "试用转化",
        }.get(self.tool.source, "未知")

        source_label = QLabel(f"📌 {source_text}")
        source_label.setObjectName("published_tool_source")
        top_layout.addWidget(source_label)

        top_layout.addStretch()

        # 更多操作按钮
        more_btn = QPushButton("⋮")
        more_btn.setObjectName("published_tool_more_button")
        more_btn.setFixedSize(24, 24)
        more_btn.clicked.connect(self._show_more_menu)
        top_layout.addWidget(more_btn)

        layout.addLayout(top_layout)

        # === 工具名称 ===
        name_label = QLabel(self.tool.tool_name)
        name_label.setObjectName("published_tool_name")
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        # === 工具描述 ===
        desc_label = QLabel(self.tool.description or "暂无描述")
        desc_label.setObjectName("published_tool_description")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label, 1)  # stretch=1

        # === 底部信息 ===
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(12)

        # 参数数量
        param_count = len(self.tool.parameters)
        param_label = QLabel(f"参数: {param_count}")
        param_label.setObjectName("published_tool_param_count")
        bottom_layout.addWidget(param_label)

        bottom_layout.addStretch()

        # 创建时间
        if self.tool.created_at:
            time_str = self._format_time(self.tool.created_at)
            time_label = QLabel(time_str)
            time_label.setObjectName("published_tool_time")
            bottom_layout.addWidget(time_label)

        layout.addLayout(bottom_layout)

        # === 操作按钮 ===
        # 检查工具参数
        param_count = len(self.tool.parameters)

        if param_count == 0:
            # 无参数工具：显示执行按钮
            execute_btn = QPushButton("▶️ 执行")
            execute_btn.setObjectName("published_tool_execute_button")
            execute_btn.clicked.connect(lambda: self.execute_requested.emit(self.tool.tool_id))
            layout.addWidget(execute_btn)
        else:
            # 有参数工具：显示配置按钮（禁用）
            config_btn = QPushButton("⚙️ 配置")
            config_btn.setObjectName("published_tool_config_button")
            config_btn.setEnabled(False)
            config_btn.setToolTip(f"该工具需要 {param_count} 个参数\n参数配置功能开发中")
            layout.addWidget(config_btn)

    def _format_time(self, dt: datetime) -> str:
        """格式化时间"""
        now = datetime.now()
        delta = now - dt

        if delta.days > 0:
            return f"{delta.days}天前"
        elif delta.seconds >= 3600:
            hours = delta.seconds // 3600
            return f"{hours}小时前"
        elif delta.seconds >= 60:
            minutes = delta.seconds // 60
            return f"{minutes}分钟前"
        else:
            return "刚刚"

    def _show_more_menu(self):
        """显示更多操作菜单"""
        menu = QMenu(self)
        menu.setObjectName("published_tool_more_menu")

        # 编辑操作
        edit_action = QAction("✏️ 编辑", self)
        edit_action.triggered.connect(lambda: self.edit_requested.emit(self.tool.tool_id))
        menu.addAction(edit_action)

        # 删除操作
        delete_action = QAction("🗑️ 删除", self)
        delete_action.triggered.connect(lambda: self.delete_requested.emit(self.tool.tool_id))
        menu.addAction(delete_action)

        # 显示菜单
        more_btn = self.findChild(QPushButton, "published_tool_more_button")
        if more_btn:
            menu.exec(more_btn.mapToGlobal(more_btn.rect().bottomLeft()))

    def update_tool(self, tool: Tool):
        """更新工具信息"""
        self.tool = tool

        # 更新名称和描述
        name_label = self.findChild(QLabel, "published_tool_name")
        if name_label:
            name_label.setText(tool.tool_name)

        desc_label = self.findChild(QLabel, "published_tool_description")
        if desc_label:
            desc_label.setText(tool.description or "暂无描述")

        # 重新初始化 UI
        layout = self.layout()
        if layout:
            while layout.count():
                child = layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            self.init_ui()


class PendingToolsUI(QWidget):
    """待试用工具列表 UI 组件（带 Tab 切换）"""

    # 定义信号
    tool_promoted = pyqtSignal(str)  # pending_tool_id

    # 新增：用于与后端通信的信号
    trial_start_request = pyqtSignal(str)  # pending_tool_id
    tool_delete_request = pyqtSignal(str)  # pending_tool_id
    tool_update_request = pyqtSignal(str, str, str)  # pending_tool_id, name, description

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)

        # 待试用工具列表
        self.pending_tools: List[PendingTool] = []
        self.pending_tool_cards: List[PendingToolCard] = []

        # 已发布工具列表
        self.published_tools: List[Tool] = []
        self.published_tool_cards: List[PublishedToolCard] = []

        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # === Tab Widget ===
        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("tools_management_tabs")

        # Tab 1: 待试用工具
        self.pending_tab = self._create_pending_tab()
        self.pending_tab_index = self.tab_widget.addTab(self.pending_tab, "⏳ 待试用")

        # Tab 2: 已发布工具
        self.published_tab = self._create_published_tab()
        self.published_tab_index = self.tab_widget.addTab(self.published_tab, "✅ 已发布")

        # 添加刷新按钮到 Tab 右上角（corner widget）
        refresh_btn = QPushButton()
        refresh_btn.setObjectName("tools_refresh_button")
        refresh_btn.setFixedSize(32, 32)
        refresh_btn.setText("🔄")
        refresh_btn.setToolTip("刷新列表")
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        self.tab_widget.setCornerWidget(refresh_btn, Qt.Corner.TopRightCorner)

        main_layout.addWidget(self.tab_widget, 1)  # stretch=1

        # 初始加载
        self._load_tools()

    def _create_pending_tab(self) -> QWidget:
        """创建待试用工具 Tab"""
        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setSpacing(20)
        tab_layout.setContentsMargins(20, 20, 20, 20)

        # 工具卡片网格
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setObjectName("pending_tools_scroll")
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 滚动内容
        scroll_content = QWidget()
        self.pending_tools_grid = QGridLayout(scroll_content)
        self.pending_tools_grid.setSpacing(16)
        self.pending_tools_grid.setContentsMargins(0, 0, 0, 0)
        self.pending_tools_grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll_area.setWidget(scroll_content)
        tab_layout.addWidget(scroll_area, 1)  # stretch=1

        # 空状态提示
        self.pending_empty_label = QLabel("📭\n\n暂无待试用工具\n\n完成 Intent 确认后，生成的工具会显示在这里")
        self.pending_empty_label.setObjectName("pending_tools_empty_label")
        self.pending_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pending_empty_label.setVisible(False)
        tab_layout.addWidget(self.pending_empty_label)

        return tab_widget

    def _create_published_tab(self) -> QWidget:
        """创建已发布工具 Tab"""
        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setSpacing(20)
        tab_layout.setContentsMargins(20, 20, 20, 20)

        # 工具卡片网格
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setObjectName("published_tools_scroll")
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 滚动内容
        scroll_content = QWidget()
        self.published_tools_grid = QGridLayout(scroll_content)
        self.published_tools_grid.setSpacing(16)
        self.published_tools_grid.setContentsMargins(0, 0, 0, 0)
        self.published_tools_grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll_area.setWidget(scroll_content)
        tab_layout.addWidget(scroll_area, 1)  # stretch=1

        # 空状态提示
        self.published_empty_label = QLabel("📭\n\n暂无已发布工具\n\n试用通过的工具会显示在这里")
        self.published_empty_label.setObjectName("published_tools_empty_label")
        self.published_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.published_empty_label.setVisible(False)
        tab_layout.addWidget(self.published_empty_label)

        return tab_widget

    def _load_tools(self):
        """加载工具列表（待试用 + 已发布）"""
        try:
            from src.data.repositories import ToolRepository
            from src.business.tool_trial.trial_models import PendingTool, PendingToolStatus
            from src.data.models import Tool

            repo = ToolRepository()
            all_tools = repo.get_all()

            # 分离待试用工具和已发布工具
            pending_tools_list = []
            published_tools_list = []

            for tool in all_tools:
                # 待试用工具：从意图生成且试用次数小于 3
                if tool.source == "intent" and tool.trial_count < 3:
                    pending_tools_list.append(PendingTool(
                        pending_tool_id=tool.tool_id,
                        tool_name=tool.tool_name,
                        tool_description=tool.description,
                        execution_code=tool.execution_code,
                        execution_strategy=tool.execution_strategy,
                        parameters=tool.parameters if tool.parameters else [],
                        status=PendingToolStatus.PENDING_TRIAL,
                        trial_count=tool.trial_count,
                        max_trials=3,
                        created_at=tool.created_at,
                        updated_at=tool.updated_at,
                    ))
                # 已发布工具：手动创建或试用成功的工具
                else:
                    published_tools_list.append(tool)

            self.update_pending_tools(pending_tools_list)
            self.update_published_tools(published_tools_list)

            self.logger.info(f"从数据库加载工具: {len(pending_tools_list)} 个待试用, {len(published_tools_list)} 个已发布")

        except Exception as e:
            self.logger.error(f"从数据库加载工具失败: {e}", exc_info=True)
            # 如果数据库加载失败，加载示例数据
            self._load_sample_tools()

    def load_tools(self):
        """加载工具列表（公开方法）"""
        self._load_tools()

    def _load_sample_tools(self):
        """加载示例工具（测试用）"""
        # 待试用工具
        sample_pending_tools = [
            PendingTool(
                tool_name="网页登录",
                tool_description="自动登录到指定网站",
                status=PendingToolStatus.PENDING_TRIAL,
                trial_count=0,
                max_trials=3,
                created_at=datetime.now(),
            ),
            PendingTool(
                tool_name="数据提取",
                tool_description="从网页提取表格数据",
                status=PendingToolStatus.TRIAL_SUCCESS,
                trial_count=1,
                max_trials=3,
                created_at=datetime.now(),
            ),
            PendingTool(
                tool_name="表单填写",
                tool_description="自动填写并提交表单",
                status=PendingToolStatus.TRIAL_FAILED,
                trial_count=2,
                max_trials=3,
                last_error="找不到元素：#submit-button",
                created_at=datetime.now(),
            ),
            PendingTool(
                tool_name="文件下载",
                tool_description="下载指定文件",
                status=PendingToolStatus.AWAITING_REAL_DATA,
                trial_count=1,
                max_trials=3,
                created_at=datetime.now(),
            ),
        ]

        # 已发布工具
        sample_published_tools = [
            Tool(
                tool_name="邮件发送",
                description="自动发送邮件通知",
                source="intent",
                created_at=datetime.now(),
            ),
            Tool(
                tool_name="数据备份",
                description="自动备份重要数据到云盘",
                source="trial",
                created_at=datetime.now(),
            ),
            Tool(
                tool_name="报表生成",
                description="自动生成周报和月报",
                source="manual",
                created_at=datetime.now(),
            ),
        ]

        self.update_pending_tools(sample_pending_tools)
        self.update_published_tools(sample_published_tools)

    def update_pending_tools(self, pending_tools: List[PendingTool]):
        """
        更新待试用工具列表

        Args:
            pending_tools: 待试用工具列表
        """
        self.pending_tools = pending_tools

        # 清空现有卡片
        self._clear_pending_cards()

        # 更新 Tab 标题显示计数
        self.tab_widget.setTabText(self.pending_tab_index, f"⏳ 待试用 ({len(pending_tools)})")

        # 显示/隐藏空状态提示
        self.pending_empty_label.setVisible(len(pending_tools) == 0)

        # 创建新卡片
        for i, tool in enumerate(pending_tools):
            card = PendingToolCard(tool)
            card.trial_requested.connect(self._on_trial_requested)
            card.delete_requested.connect(self._on_delete_requested)
            card.edit_requested.connect(self._on_edit_requested)

            # 添加到网格布局 (3列)
            row = i // 3
            col = i % 3
            self.pending_tools_grid.addWidget(card, row, col)

            self.pending_tool_cards.append(card)

        # 添加弹性空间
        for col in range(3):
            self.pending_tools_grid.setColumnStretch(col, 1)

    def update_published_tools(self, published_tools: List[Tool]):
        """
        更新已发布工具列表

        Args:
            published_tools: 已发布工具列表
        """
        self.published_tools = published_tools

        # 清空现有卡片
        self._clear_published_cards()

        # 更新 Tab 标题显示计数
        self.tab_widget.setTabText(self.published_tab_index, f"✅ 已发布 ({len(published_tools)})")

        # 显示/隐藏空状态提示
        self.published_empty_label.setVisible(len(published_tools) == 0)

        # 创建新卡片
        for i, tool in enumerate(published_tools):
            card = PublishedToolCard(tool)
            card.execute_requested.connect(self._on_execute_requested)
            card.delete_requested.connect(self._on_published_delete_requested)
            card.edit_requested.connect(self._on_published_edit_requested)

            # 添加到网格布局 (3列)
            row = i // 3
            col = i % 3
            self.published_tools_grid.addWidget(card, row, col)

            self.published_tool_cards.append(card)

        # 添加弹性空间
        for col in range(3):
            self.published_tools_grid.setColumnStretch(col, 1)

    def _clear_pending_cards(self):
        """清空待试用工具卡片"""
        self.pending_tool_cards.clear()

        while self.pending_tools_grid.count():
            child = self.pending_tools_grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _clear_published_cards(self):
        """清空已发布工具卡片"""
        self.published_tool_cards.clear()

        while self.published_tools_grid.count():
            child = self.published_tools_grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _on_refresh_clicked(self):
        """刷新按钮点击"""
        self.logger.info("刷新工具列表")
        self._load_tools()

    def _on_trial_requested(self, pending_tool_id: str):
        """试用请求"""
        self.logger.info(f"试用工具: {pending_tool_id}")

        # 发送试用请求信号
        self.trial_start_request.emit(pending_tool_id)

        # 更新工具状态为试用中
        for tool in self.pending_tools:
            if tool.pending_tool_id == pending_tool_id:
                tool.status = PendingToolStatus.TRIALING
                break

        self._refresh_pending_cards()

    def _on_delete_requested(self, pending_tool_id: str):
        """删除待试用工具请求"""
        self.logger.info(f"删除待试用工具: {pending_tool_id}")

        # 确认对话框
        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定要删除这个工具吗？\n\n此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            # 发送删除请求信号
            self.tool_delete_request.emit(pending_tool_id)

            # 从列表中移除
            self.pending_tools = [
                tool for tool in self.pending_tools
                if tool.pending_tool_id != pending_tool_id
            ]

            self._refresh_pending_cards()

    def _on_edit_requested(self, pending_tool_id: str):
        """编辑待试用工具请求"""
        self.logger.info(f"编辑待试用工具: {pending_tool_id}")

        # 查找工具
        tool = None
        for t in self.pending_tools:
            if t.pending_tool_id == pending_tool_id:
                tool = t
                break

        if not tool:
            return

        # 编辑名称对话框
        name, ok = QInputDialog.getText(
            self,
            "编辑工具名称",
            "工具名称:",
            text=tool.tool_name,
        )

        if ok and name:
            # 编辑描述对话框
            desc, ok = QInputDialog.getText(
                self,
                "编辑工具描述",
                "工具描述:",
                text=tool.tool_description or "",
            )

            if ok:
                # 更新工具信息
                tool.tool_name = name
                tool.tool_description = desc

                # 发送更新请求信号
                self.tool_update_request.emit(pending_tool_id, name, desc)

                # 刷新卡片
                self._refresh_pending_cards()

    def _on_execute_requested(self, tool_id: str):
        """执行已发布工具请求"""
        self.logger.info(f"执行已发布工具: {tool_id}")

        # 查找工具
        tool = None
        for t in self.published_tools:
            if t.tool_id == tool_id:
                tool = t
                break

        if not tool:
            self.logger.error(f"未找到工具: {tool_id}")
            QMessageBox.warning(self, "工具未找到", f"未找到工具 ID: {tool_id}")
            return

        # 显示参数输入对话框
        from src.ui.tool_execution_dialog import ToolExecutionDialog, ExecutionResultDialog
        from src.ui.tool_execution_thread import ToolExecutionThread, ToolExecutionProgressDialog

        dialog = ToolExecutionDialog(tool, self)
        result = dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            # 用户点击了"执行"按钮
            parameters = dialog.get_parameters()
            self.logger.info(f"开始执行工具: {tool.tool_name}, 参数: {parameters}")

            # 使用后台线程执行工具（避免阻塞 UI）
            execution_thread = ToolExecutionThread(tool, parameters)

            # 创建进度对话框
            progress_dialog = ToolExecutionProgressDialog(tool.tool_name, self)
            progress_dialog.set_execution_thread(execution_thread)

            # 显示进度对话框并等待执行完成
            progress_dialog.exec()

            # 获取执行结果
            success, exec_result, error = progress_dialog.get_result()

            # 显示执行结果对话框
            ExecutionResultDialog(
                tool_name=tool.tool_name,
                success=success,
                result=result,
                error=error,
                parent=self
            ).exec()

    def _on_published_delete_requested(self, tool_id: str):
        """删除已发布工具请求"""
        self.logger.info(f"删除已发布工具: {tool_id}")

        # 确认对话框
        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定要删除这个工具吗？\n\n此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            # 从列表中移除
            self.published_tools = [
                tool for tool in self.published_tools
                if tool.tool_id != tool_id
            ]

            self._refresh_published_cards()

    def _on_published_edit_requested(self, tool_id: str):
        """编辑已发布工具请求"""
        self.logger.info(f"编辑已发布工具: {tool_id}")

        # 查找工具
        tool = None
        for t in self.published_tools:
            if t.tool_id == tool_id:
                tool = t
                break

        if not tool:
            return

        # 编辑名称对话框
        name, ok = QInputDialog.getText(
            self,
            "编辑工具名称",
            "工具名称:",
            text=tool.tool_name,
        )

        if ok and name:
            # 编辑描述对话框
            desc, ok = QInputDialog.getText(
                self,
                "编辑工具描述",
                "工具描述:",
                text=tool.description or "",
            )

            if ok:
                # 更新工具信息
                tool.tool_name = name
                tool.description = desc

                # 刷新卡片
                self._refresh_published_cards()

    def _refresh_pending_cards(self):
        """刷新待试用工具卡片"""
        # 重新创建卡片
        self.update_pending_tools(self.pending_tools)

    def _refresh_published_cards(self):
        """刷新已发布工具卡片"""
        # 重新创建卡片
        self.update_published_tools(self.published_tools)

    # ===== WebSocket 消息处理 =====

    def on_trial_status_update(self, data: dict):
        """
        处理试用状态更新消息（公共方法，供外部调用）

        Args:
            data: 包含 pending_tool_id, status 等的字典
        """
        try:
            pending_tool_id = data.get("pending_tool_id")
            status = data.get("status")
            progress = data.get("progress", 0.0)
            current_step = data.get("current_step")
            log_message = data.get("log_message")
            error = data.get("error")

            self.logger.info(f"收到试用状态更新: {pending_tool_id}, status={status}")

            # 更新工具状态
            for tool in self.pending_tools:
                if tool.pending_tool_id == pending_tool_id:
                    # 更新状态
                    if status == "running":
                        tool.status = PendingToolStatus.TRIALING
                    elif status == "success":
                        tool.status = PendingToolStatus.TRIAL_SUCCESS
                    elif status == "failed":
                        tool.status = PendingToolStatus.TRIAL_FAILED
                        tool.last_error = error

                    # 刷新卡片
                    QTimer.singleShot(0, self._refresh_pending_cards)
                    break

        except Exception as e:
            self.logger.error(f"处理试用状态更新消息失败: {e}")

    def add_pending_tool(self, pending_tool: PendingTool):
        """
        添加新的待试用工具

        Args:
            pending_tool: PendingTool 对象
        """
        self.pending_tools.append(pending_tool)
        self._refresh_pending_cards()

    def promote_tool(self, pending_tool_id: str, published_tool: Tool):
        """
        将待试用工具提升为已发布工具

        Args:
            pending_tool_id: 待试用工具 ID
            published_tool: 已发布工具对象
        """
        # 从待试用列表中移除
        self.pending_tools = [
            tool for tool in self.pending_tools
            if tool.pending_tool_id != pending_tool_id
        ]

        # 添加到已发布列表
        self.published_tools.insert(0, published_tool)  # 插入到开头

        # 刷新两个列表
        self._refresh_pending_cards()
        self._refresh_published_cards()

        # 切换到已发布 Tab
        self.tab_widget.setCurrentIndex(1)

        # 发送信号
        self.tool_promoted.emit(pending_tool_id)

    def cleanup(self):
        """清理资源"""
        # 不再需要清理 WebSocket 客户端
        pass
