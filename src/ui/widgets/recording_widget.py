"""
技能教学界面组件

提供技能教学功能的用户界面，包括：
- 教学模式选择（浏览器操作、桌面操作）
- 起始 URL 输入
- 教学控制（开始/结束）
- 状态信息显示
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFrame,
    QTextEdit,
    QSizePolicy,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from src.data.unified_config import get_unified_config


class _ModeCard(QFrame):
    """模式选择卡片"""

    clicked = pyqtSignal()

    def __init__(self, icon: str, title: str, desc: str, parent=None):
        super().__init__(parent)
        self._selected = False
        self.setObjectName("mode_card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(90)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        # 图标
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 28px; background: transparent;")
        icon_label.setFixedWidth(40)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # 文字区
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            "font-size: 15px; font-weight: 600; color: #1a1a2e; background: transparent;"
        )
        text_layout.addWidget(title_label)

        desc_label = QLabel(desc)
        desc_label.setStyleSheet(
            "font-size: 12px; color: #6c757d; background: transparent;"
        )
        desc_label.setWordWrap(True)
        text_layout.addWidget(desc_label)

        layout.addLayout(text_layout, 1)

        # 选中指示器
        self._check = QLabel("✓")
        self._check.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #5b6abf; background: transparent;"
        )
        self._check.setFixedWidth(24)
        self._check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._check.setVisible(False)
        layout.addWidget(self._check)

        self._apply_style()

    def set_selected(self, selected: bool):
        self._selected = selected
        self._check.setVisible(selected)
        self._apply_style()

    def _apply_style(self):
        if self._selected:
            self.setStyleSheet("""
                QFrame#mode_card {
                    background-color: #f0f1ff;
                    border: 2px solid #5b6abf;
                    border-radius: 10px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame#mode_card {
                    background-color: #f8f9fa;
                    border: 1.5px solid #e0e0e0;
                    border-radius: 10px;
                }
                QFrame#mode_card:hover {
                    background-color: #f0f1ff;
                    border-color: #b0b5e0;
                }
            """)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class RecordingWidget(QWidget):
    """技能教学界面组件"""

    # 信号（保持兼容）
    recording_started = pyqtSignal(str, str)  # (mode, url)
    recording_stopped = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_unified_config()
        self.is_recording = False
        self._current_mode = "browser"
        self.init_ui()
        self.load_config()

    def init_ui(self):
        """初始化用户界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 外层滚动容器
        content = QWidget()
        content.setStyleSheet("background-color: #ffffff;")
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # ── Hero 区域 ──
        hero = QWidget()
        hero.setStyleSheet("background-color: #fafbff;")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(40, 36, 40, 28)
        hero_layout.setSpacing(10)

        title = QLabel("技能教学")
        title.setObjectName("recording_title")
        title.setStyleSheet(
            "font-size: 26px; font-weight: 700; color: #1a1a2e; background: transparent;"
        )
        hero_layout.addWidget(title)

        subtitle = QLabel("像教新同事一样，演示一遍操作，AI 就能学会并帮你重复执行")
        subtitle.setStyleSheet(
            "font-size: 14px; color: #6c757d; background: transparent;"
        )
        subtitle.setWordWrap(True)
        hero_layout.addWidget(subtitle)

        content_layout.addWidget(hero)

        # ── 分隔线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #eef0f4; max-height: 1px;")
        content_layout.addWidget(sep)

        # ── 主体设置区 ──
        body = QWidget()
        body.setStyleSheet("background-color: #ffffff;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(40, 28, 40, 28)
        body_layout.setSpacing(24)

        # 步骤 1: 选择模式
        step1_label = QLabel("选择教学方式")
        step1_label.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #1a1a2e;"
        )
        body_layout.addWidget(step1_label)

        # 模式卡片
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        self.browser_card = _ModeCard(
            "🌐", "浏览器操作", "在浏览器中演示网页操作流程"
        )
        self.browser_card.clicked.connect(lambda: self._select_mode("browser"))
        cards_layout.addWidget(self.browser_card)

        self.desktop_card = _ModeCard(
            "🖥️", "桌面操作", "演示桌面应用的操作流程"
        )
        self.desktop_card.clicked.connect(lambda: self._select_mode("desktop"))
        cards_layout.addWidget(self.desktop_card)

        body_layout.addLayout(cards_layout)

        # URL 输入区
        self.url_container = QWidget()
        self.url_container.setStyleSheet("background: transparent;")
        url_layout = QVBoxLayout(self.url_container)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.setSpacing(8)

        url_label = QLabel("起始网址")
        url_label.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #1a1a2e;"
        )
        url_layout.addWidget(url_label)

        self.url_input = QLineEdit()
        self.url_input.setObjectName("url_input")
        self.url_input.setPlaceholderText("输入要打开的网址，留空则打开空白页")
        self.url_input.setStyleSheet("""
            QLineEdit {
                border: 1.5px solid #e0e0e0;
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 14px;
                background-color: #f8f9fa;
            }
            QLineEdit:focus {
                border-color: #5b6abf;
                background-color: #ffffff;
            }
        """)
        url_layout.addWidget(self.url_input)

        body_layout.addWidget(self.url_container)

        # ── 操作按钮 ──
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.record_btn = QPushButton("开始教学")
        self.record_btn.setObjectName("record_btn")
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setFixedHeight(44)
        self.record_btn.setStyleSheet("""
            QPushButton {
                font-size: 15px;
                font-weight: 600;
                padding: 0 32px;
                background-color: #5b6abf;
                color: white;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #4a58a8;
            }
            QPushButton:pressed {
                background-color: #3d4a91;
            }
            QPushButton:disabled {
                background-color: #c5c9e0;
            }
        """)
        self.record_btn.clicked.connect(self.on_record_clicked)
        btn_layout.addWidget(self.record_btn)

        self.stop_btn = QPushButton("结束教学")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setFixedHeight(44)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                font-size: 15px;
                font-weight: 600;
                padding: 0 32px;
                background-color: #ffffff;
                color: #e74c3c;
                border: 1.5px solid #e74c3c;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #fdf0ee;
            }
            QPushButton:pressed {
                background-color: #fbe3df;
            }
            QPushButton:disabled {
                color: #c5c9e0;
                border-color: #e0e0e0;
                background-color: #f8f9fa;
            }
        """)
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        btn_layout.addWidget(self.stop_btn)

        btn_layout.addStretch()
        body_layout.addLayout(btn_layout)

        # ── 教学中状态指示 ──
        self.recording_indicator = QWidget()
        self.recording_indicator.setVisible(False)
        self.recording_indicator.setStyleSheet("""
            QWidget {
                background-color: #fff8f0;
                border: 1px solid #ffd6a5;
                border-radius: 8px;
            }
        """)
        indicator_layout = QHBoxLayout(self.recording_indicator)
        indicator_layout.setContentsMargins(16, 12, 16, 12)
        indicator_layout.setSpacing(10)

        self._pulse_dot = QLabel("●")
        self._pulse_dot.setStyleSheet(
            "font-size: 14px; color: #e67e22; background: transparent;"
        )
        self._pulse_dot.setFixedWidth(20)
        indicator_layout.addWidget(self._pulse_dot)

        indicator_text = QLabel("教学进行中 — 请在打开的窗口中演示操作，完成后点击「结束教学」")
        indicator_text.setStyleSheet(
            "font-size: 13px; color: #8a6d3b; background: transparent;"
        )
        indicator_text.setWordWrap(True)
        indicator_layout.addWidget(indicator_text, 1)

        body_layout.addWidget(self.recording_indicator)

        # ── 状态日志（折叠区域）──
        self.status_section = QWidget()
        self.status_section.setVisible(False)
        self.status_section.setStyleSheet("background: transparent;")
        status_layout = QVBoxLayout(self.status_section)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)

        status_header = QHBoxLayout()
        status_title = QLabel("运行日志")
        status_title.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #868e96;"
        )
        status_header.addWidget(status_title)
        status_header.addStretch()
        status_layout.addLayout(status_header)

        self.status_text = QTextEdit()
        self.status_text.setObjectName("status_text")
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(120)
        self.status_text.setStyleSheet("""
            QTextEdit {
                border: 1px solid #e9ecef;
                border-radius: 6px;
                padding: 8px 10px;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: 11px;
                background-color: #f8f9fa;
                color: #495057;
            }
        """)
        status_layout.addWidget(self.status_text)

        body_layout.addWidget(self.status_section)

        body_layout.addStretch()
        content_layout.addWidget(body, 1)

        main_layout.addWidget(content)

        # 兼容旧代码：保留 mode_combo 接口（内部用 _current_mode 管理）
        self._mode_data_map = {"browser": 0, "desktop": 1}

    # ── 模式选择 ──

    def _select_mode(self, mode: str):
        """选择教学模式"""
        if self.is_recording:
            return
        self._current_mode = mode
        self.browser_card.set_selected(mode == "browser")
        self.desktop_card.set_selected(mode == "desktop")
        self.url_container.setVisible(mode == "browser")
        if mode == "desktop":
            self.url_input.clear()

    # ── 配置加载 ──

    def load_config(self):
        """从配置加载初始值"""
        try:
            default_mode = self.config.get(
                "recording.default_recording_mode", default="browser"
            )
            self._select_mode(default_mode)

            default_url = self.config.get("recording.browser_start_url", default="")
            if default_url:
                self.url_input.setText(default_url)
        except Exception as e:
            self.append_status(f"⚠️ 加载配置失败: {str(e)}")

    # ── 按钮事件 ──

    def on_record_clicked(self):
        """开始教学"""
        mode = self._current_mode
        url = self.url_input.text().strip()

        self.is_recording = True
        self.record_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.url_input.setEnabled(False)
        self.browser_card.setEnabled(False)
        self.desktop_card.setEnabled(False)

        # 显示进行中状态
        self.recording_indicator.setVisible(True)
        self.status_section.setVisible(True)

        self.recording_started.emit(mode, url)

        mode_name = "浏览器" if mode == "browser" else "桌面"
        self.append_status(f"开始{mode_name}教学")
        if mode == "browser":
            display_url = url if url else "about:blank（空白页）"
            self.append_status(f"起始 URL: {display_url}")

    def on_stop_clicked(self):
        """结束教学"""
        self.is_recording = False
        self.record_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.url_input.setEnabled(True)
        self.browser_card.setEnabled(True)
        self.desktop_card.setEnabled(True)

        self.recording_indicator.setVisible(False)

        self.recording_stopped.emit()
        self.append_status("教学已结束")

    # ── 公共方法（保持兼容）──

    def append_status(self, message: str):
        """追加状态消息"""
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_text.append(f"[{timestamp}] {message}")
        # 有日志时自动显示日志区
        if not self.status_section.isVisible():
            self.status_section.setVisible(True)

    def update_progress(self, value: int, message: str = ""):
        """更新进度（保持接口兼容，通过日志展示）"""
        if message:
            self.append_status(message)

    def reset(self):
        """重置界面状态"""
        self.is_recording = False
        self.record_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.url_input.setEnabled(True)
        self.browser_card.setEnabled(True)
        self.desktop_card.setEnabled(True)

        self.recording_indicator.setVisible(False)
        self.status_section.setVisible(False)
        self.status_text.clear()

        # 恢复 URL 区域可见性
        self.url_container.setVisible(self._current_mode == "browser")
