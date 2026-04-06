"""
设置页面 (Claude 风格)

提供配置管理界面，包括：
- AI 配置
- 录制配置
- 数据库配置
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QPushButton,
    QGroupBox,
    QScrollArea,
)
from src.data.unified_config import get_unified_config
from src.utils.logger import get_logger


class SettingsPage(QWidget):
    """设置页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)
        self.config = get_unified_config()
        self.init_ui()
        self.load_config()

    def init_ui(self):
        """初始化用户界面"""
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # 页面标题
        title_label = QLabel("设置")
        title_label.setObjectName("settings_title")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        main_layout.addWidget(title_label)

        # 创建滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(16)
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        # ============ AI 配置组 ============
        ai_group = QGroupBox("AI 配置")
        ai_group.setObjectName("settings_group")
        ai_layout = QVBoxLayout()
        ai_layout.setSpacing(12)

        # API Key
        api_key_layout = QHBoxLayout()
        api_key_label = QLabel("API Key:")
        api_key_label.setMinimumWidth(120)
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("输入 Claude API Key")
        self.api_key_input.setObjectName("settings_input")
        api_key_layout.addWidget(api_key_label)
        api_key_layout.addWidget(self.api_key_input)
        ai_layout.addLayout(api_key_layout)

        # 模型选择
        model_layout = QHBoxLayout()
        model_label = QLabel("模型:")
        model_label.setMinimumWidth(120)
        self.model_combo = QComboBox()
        self.model_combo.setObjectName("settings_combo")
        self.model_combo.addItem("claude-sonnet-4-5-20250929", "claude-sonnet-4-5-20250929")
        self.model_combo.addItem("claude-opus-4-5-20251101", "claude-opus-4-5-20251101")
        self.model_combo.addItem("claude-haiku-4-5-20250929", "claude-haiku-4-5-20250929")
        model_layout.addWidget(model_label)
        model_layout.addWidget(self.model_combo)
        ai_layout.addLayout(model_layout)

        # 超时时间
        timeout_layout = QHBoxLayout()
        timeout_label = QLabel("超时时间 (秒):")
        timeout_label.setMinimumWidth(120)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setObjectName("settings_spin")
        self.timeout_spin.setRange(10, 300)
        self.timeout_spin.setValue(60)
        timeout_layout.addWidget(timeout_label)
        timeout_layout.addWidget(self.timeout_spin)
        ai_layout.addLayout(timeout_layout)

        ai_group.setLayout(ai_layout)
        scroll_layout.addWidget(ai_group)

        # ============ 录制配置组 ============
        recording_group = QGroupBox("教学配置")
        recording_group.setObjectName("settings_group")
        recording_layout = QVBoxLayout()
        recording_layout.setSpacing(12)

        # 默认录制模式
        rec_mode_layout = QHBoxLayout()
        rec_mode_label = QLabel("默认教学模式:")
        rec_mode_label.setMinimumWidth(120)
        self.rec_mode_combo = QComboBox()
        self.rec_mode_combo.setObjectName("settings_combo")
        self.rec_mode_combo.addItem("浏览器操作", "browser")
        self.rec_mode_combo.addItem("桌面操作", "desktop")
        rec_mode_layout.addWidget(rec_mode_label)
        rec_mode_layout.addWidget(self.rec_mode_combo)
        recording_layout.addLayout(rec_mode_layout)

        # 起始 URL
        start_url_layout = QHBoxLayout()
        start_url_label = QLabel("起始 URL:")
        start_url_label.setMinimumWidth(120)
        self.start_url_input = QLineEdit()
        self.start_url_input.setPlaceholderText("https://example.com")
        self.start_url_input.setObjectName("settings_input")
        start_url_layout.addWidget(start_url_label)
        start_url_layout.addWidget(self.start_url_input)
        recording_layout.addLayout(start_url_layout)

        # WebSocket 端口
        ws_port_layout = QHBoxLayout()
        ws_port_label = QLabel("WebSocket 端口:")
        ws_port_label.setMinimumWidth(120)
        self.ws_port_spin = QSpinBox()
        self.ws_port_spin.setObjectName("settings_spin")
        self.ws_port_spin.setRange(1024, 65535)
        self.ws_port_spin.setValue(8765)
        ws_port_layout.addWidget(ws_port_label)
        ws_port_layout.addWidget(self.ws_port_spin)
        recording_layout.addLayout(ws_port_layout)

        recording_group.setLayout(recording_layout)
        scroll_layout.addWidget(recording_group)

        # ============ 数据压缩配置组 ============
        compression_group = QGroupBox("数据压缩")
        compression_group.setObjectName("settings_group")
        compression_layout = QVBoxLayout()
        compression_layout.setSpacing(12)

        # 压缩级别
        comp_level_layout = QHBoxLayout()
        comp_level_label = QLabel("压缩级别:")
        comp_level_label.setMinimumWidth(120)
        self.comp_level_combo = QComboBox()
        self.comp_level_combo.setObjectName("settings_combo")
        self.comp_level_combo.addItem("无压缩", "NONE")
        self.comp_level_combo.addItem("保守", "CONSERVATIVE")
        self.comp_level_combo.addItem("中等", "MODERATE")
        self.comp_level_combo.addItem("激进", "AGGRESSIVE")
        comp_level_layout.addWidget(comp_level_label)
        comp_level_layout.addWidget(self.comp_level_combo)
        compression_layout.addLayout(comp_level_layout)

        compression_group.setLayout(compression_layout)
        scroll_layout.addWidget(compression_group)

        # 添加弹性空间
        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll, 1)  # stretch=1

        # ============ 保存按钮 ============
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.save_button = QPushButton("保存设置")
        self.save_button.setObjectName("settings_save_button")
        self.save_button.clicked.connect(self.save_config)
        button_layout.addWidget(self.save_button)

        main_layout.addLayout(button_layout)

    def load_config(self):
        """从配置加载值"""
        try:
            # AI 配置
            api_key = self.config.get_ai_api_key() or ""
            if api_key:
                self.api_key_input.setText(api_key)

            model = self.config.get("ai.model", default="claude-sonnet-4-5-20250929")
            index = self.model_combo.findData(model)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)

            timeout = self.config.get("ai.timeout", default=60)
            self.timeout_spin.setValue(timeout)

            # 录制配置
            rec_mode = self.config.get("recording.default_recording_mode", default="browser")
            index = self.rec_mode_combo.findData(rec_mode)
            if index >= 0:
                self.rec_mode_combo.setCurrentIndex(index)

            start_url = self.config.get("recording.browser_start_url", default="")
            if start_url:
                self.start_url_input.setText(start_url)

            ws_port = self.config.get_websocket_port()
            self.ws_port_spin.setValue(ws_port)

            # 压缩配置
            comp_level = self.config.get("ai.compression_level", default="MODERATE")
            index = self.comp_level_combo.findData(comp_level)
            if index >= 0:
                self.comp_level_combo.setCurrentIndex(index)

            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)

            self.logger.info("已加载配置")

        except Exception as e:
            self.logger.error(f"加载配置失败: {e}", exc_info=True)

    def save_config(self):
        """保存配置到数据库"""
        try:
            # AI 配置
            api_key = self.api_key_input.text().strip()
            current_key = self.config.get_ai_api_key() or ""
            if api_key and api_key != current_key:
                self.config.set_ai_api_key(api_key)
            elif not api_key:
                self.config.clear_ai_api_key()
            self.config.set("ai.model", self.model_combo.currentData())
            self.config.set("ai.timeout", self.timeout_spin.value())

            # 录制配置
            self.config.set("recording.default_recording_mode", self.rec_mode_combo.currentData())
            self.config.set("recording.browser_start_url", self.start_url_input.text().strip())
            self.config.set("recording.websocket.port", self.ws_port_spin.value())

            # 压缩配置
            self.config.set("ai.compression_level", self.comp_level_combo.currentData())

            self.logger.info("配置已保存")
            self._show_success_message()

        except Exception as e:
            self.logger.error(f"保存配置失败: {e}", exc_info=True)
            self._show_error_message(str(e))

    def _show_success_message(self):
        """显示成功消息"""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(self, "成功", "配置已保存")

    def _show_error_message(self, error: str):
        """显示错误消息"""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "错误", f"保存配置失败：\n{error}")
