"""
录制界面组件

提供录制功能的用户界面，包括：
- 录制模式选择（浏览器录制、桌面录制）
- 起始 URL 输入
- 录制控制按钮（开始/停止）
- 进度显示
- 状态信息显示
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QGroupBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from src.data.unified_config import get_unified_config


class RecordingWidget(QWidget):
    """录制操作界面组件 (Claude 风格)"""

    # 定义信号
    recording_started = pyqtSignal(str, str)  # (mode, url)
    recording_stopped = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_unified_config()
        self.is_recording = False
        self.url_layout = None  # URL输入框布局（用于显示/隐藏控制）
        self.init_ui()
        self.load_config()

    def init_ui(self):
        """初始化用户界面"""
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # 页面标题
        title_label = QLabel("录制操作")
        title_label.setObjectName("recording_title")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        main_layout.addWidget(title_label)

        # 创建配置组
        config_group = QGroupBox("录制配置")
        config_layout = QVBoxLayout()

        # 录制模式选择
        mode_layout = QHBoxLayout()
        mode_label = QLabel("录制模式:")
        mode_label.setMinimumWidth(100)
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("mode_combo")
        self.mode_combo.addItem("浏览器录制", "browser")
        self.mode_combo.addItem("桌面录制", "desktop")
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        mode_layout.addWidget(mode_label)
        mode_layout.addWidget(self.mode_combo)
        config_layout.addLayout(mode_layout)

        # 起始 URL 输入
        self.url_layout = QHBoxLayout()
        url_label = QLabel("起始 URL:")
        url_label.setMinimumWidth(100)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com")
        self.url_input.setObjectName("url_input")
        self.url_layout.addWidget(url_label)
        self.url_layout.addWidget(self.url_input)
        config_layout.addLayout(self.url_layout)

        config_group.setLayout(config_layout)
        main_layout.addWidget(config_group)

        # 创建控制按钮
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.record_btn = QPushButton("▶️ 开始录制")
        self.record_btn.setObjectName("record_btn")
        self.record_btn.setStyleSheet(
            """
            QPushButton {
                font-size: 16px;
                padding: 12px 24px;
                background-color: #27ae60;
                color: white;
                border: none;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #229954;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """
        )
        self.record_btn.clicked.connect(self.on_record_clicked)
        button_layout.addWidget(self.record_btn)

        self.stop_btn = QPushButton("⏹️ 停止录制")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            """
            QPushButton {
                font-size: 16px;
                padding: 12px 24px;
                background-color: #e74c3c;
                color: white;
                border: none;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """
        )
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        button_layout.addWidget(self.stop_btn)

        button_layout.addStretch()
        main_layout.addLayout(button_layout)

        # 创建进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("progress_bar")
        self.progress_bar.setRange(0, 100)  # 0-100%
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("准备就绪")
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: 2px solid #bdc3c7;
                border-radius: 5px;
                text-align: center;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #3498db;
                border-radius: 3px;
            }
        """
        )
        main_layout.addWidget(self.progress_bar)

        # 创建状态显示区域
        status_label = QLabel("状态信息:")
        main_layout.addWidget(status_label)

        self.status_text = QTextEdit()
        self.status_text.setObjectName("status_text")
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(150)
        self.status_text.setPlaceholderText("录制状态和日志信息将显示在这里...")
        self.status_text.setStyleSheet(
            """
            QTextEdit {
                border: 1px solid #bdc3c7;
                border-radius: 5px;
                padding: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                background-color: #f8f9fa;
            }
        """
        )
        main_layout.addWidget(self.status_text)

        # 添加弹性空间
        main_layout.addStretch()

    def load_config(self):
        """从配置加载初始值"""
        try:
            # 加载默认录制模式
            default_mode = self.config.get("recording.default_recording_mode", default="browser")
            if default_mode == "desktop":
                index = self.mode_combo.findData("desktop")
            else:
                index = self.mode_combo.findData("browser")

            if index >= 0:
                self.mode_combo.setCurrentIndex(index)

            # 加载默认起始 URL
            default_url = self.config.get("recording.browser_start_url", default="")
            if default_url:
                self.url_input.setText(default_url)

            # 根据默认模式设置URL输入框的可见性
            self._update_url_visibility()

        except Exception as e:
            self.append_status(f"⚠️ 加载配置失败: {str(e)}")

    def _update_url_visibility(self):
        """根据当前模式更新URL输入框的可见性"""
        mode = self.mode_combo.currentData()
        if mode == "desktop":
            self.url_input.setVisible(False)
            if self.url_layout.itemAt(0):
                url_label = self.url_layout.itemAt(0).widget()
                if url_label:
                    url_label.setVisible(False)
        else:
            self.url_input.setVisible(True)
            if self.url_layout.itemAt(0):
                url_label = self.url_layout.itemAt(0).widget()
                if url_label:
                    url_label.setVisible(True)

    def on_mode_changed(self, index):
        """模式选择变化事件"""
        mode = self.mode_combo.currentData()
        if mode == "desktop":
            # 桌面录制模式下隐藏 URL 输入
            self.url_input.setVisible(False)
            self.url_input.clear()
            # 隐藏URL标签（布局中的第一个元素）
            if self.url_layout.itemAt(0):
                url_label = self.url_layout.itemAt(0).widget()
                if url_label:
                    url_label.setVisible(False)
            self.append_status("ℹ️ 已切换到桌面录制模式")
        else:
            # 浏览器录制模式下显示 URL 输入
            self.url_input.setVisible(True)
            # 显示URL标签（布局中的第一个元素）
            if self.url_layout.itemAt(0):
                url_label = self.url_layout.itemAt(0).widget()
                if url_label:
                    url_label.setVisible(True)
            self.append_status("ℹ️ 已切换到浏览器录制模式")

    def on_record_clicked(self):
        """开始录制按钮点击事件"""
        mode = self.mode_combo.currentData()
        url = self.url_input.text().strip()

        # 更新界面状态
        self.is_recording = True
        self.record_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.mode_combo.setEnabled(False)
        self.url_input.setEnabled(False)

        # 更新进度条
        self.progress_bar.setRange(0, 0)  # 不确定进度模式
        self.progress_bar.setFormat("录制中...")

        # 发出信号（不输入URL则传入空字符串，由录制器打开空白页）
        self.recording_started.emit(mode, url)

        # 更新状态显示
        mode_name = "浏览器" if mode == "browser" else "桌面"
        self.append_status(f"🎬 开始{mode_name}录制")
        if mode == "browser":
            display_url = url if url else "about:blank（空白页）"
            self.append_status(f"📍 起始 URL: {display_url}")

    def on_stop_clicked(self):
        """停止录制按钮点击事件"""
        # 更新界面状态
        self.is_recording = False
        self.record_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.mode_combo.setEnabled(True)

        # 恢复 URL 输入状态（根据当前模式）
        self._update_url_visibility()

        # 更新进度条
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("录制完成")

        # 发出信号
        self.recording_stopped.emit()

        # 更新状态显示
        self.append_status("⏹️ 录制已停止")

    def append_status(self, message: str):
        """追加状态消息"""
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_text.append(f"[{timestamp}] {message}")

    def update_progress(self, value: int, message: str = ""):
        """更新进度条"""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(value)
        if message:
            self.progress_bar.setFormat(message)

    def reset(self):
        """重置界面状态"""
        self.is_recording = False
        self.record_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.mode_combo.setEnabled(True)

        # 恢复 URL 输入状态（根据当前模式）
        self._update_url_visibility()

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("准备就绪")

        self.status_text.clear()
