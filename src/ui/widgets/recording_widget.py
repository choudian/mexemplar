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
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from src.data.unified_config import get_unified_config
from src.recording.browser_recorder import RecordingMode
from src.ui.style_constants import (
    PRIMARY_COLOR,
    TITLE_COLOR,
    SUBTITLE_COLOR,
    HERO_BG_COLOR,
    DIVIDER_COLOR,
)


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
            f"font-size: 15px; font-weight: 600; color: {TITLE_COLOR}; background: transparent;"
        )
        text_layout.addWidget(title_label)

        desc_label = QLabel(desc)
        desc_label.setStyleSheet(f"font-size: 12px; color: {SUBTITLE_COLOR}; background: transparent;")
        desc_label.setWordWrap(True)
        text_layout.addWidget(desc_label)

        layout.addLayout(text_layout, 1)

        # 选中指示器
        self._check = QLabel("✓")
        self._check.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {PRIMARY_COLOR}; background: transparent;"
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
            self.setStyleSheet(
                f"""
                QFrame#mode_card {{
                    background-color: #f0f1ff;
                    border: 2px solid {PRIMARY_COLOR};
                    border-radius: 10px;
                }}
            """
            )
        else:
            self.setStyleSheet(
                """
                QFrame#mode_card {
                    background-color: #f8f9fa;
                    border: 1.5px solid #e0e0e0;
                    border-radius: 10px;
                }
                QFrame#mode_card:hover {
                    background-color: #f0f1ff;
                    border-color: #b0b5e0;
                }
            """
            )

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
        self._current_mode = RecordingMode.BROWSER
        self._awaiting_extension_start = False
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
        hero.setStyleSheet(f"background-color: {HERO_BG_COLOR};")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(40, 36, 40, 28)
        hero_layout.setSpacing(10)

        title = QLabel("技能教学")
        title.setObjectName("recording_title")
        title.setStyleSheet(
            f"font-size: 26px; font-weight: 700; color: {TITLE_COLOR}; background: transparent;"
        )
        hero_layout.addWidget(title)

        subtitle = QLabel("像教新同事一样，演示一遍操作，AI 就能学会并帮你重复执行")
        subtitle.setStyleSheet(f"font-size: 14px; color: {SUBTITLE_COLOR}; background: transparent;")
        subtitle.setWordWrap(True)
        hero_layout.addWidget(subtitle)

        content_layout.addWidget(hero)

        # ── 分隔线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {DIVIDER_COLOR}; max-height: 1px;")
        content_layout.addWidget(sep)

        # ── 主体设置区 ──
        body = QWidget()
        body.setStyleSheet("background-color: #ffffff;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(40, 28, 40, 28)
        body_layout.setSpacing(24)

        # 步骤 1: 选择模式
        step1_label = QLabel("选择教学方式")
        step1_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {TITLE_COLOR};")
        body_layout.addWidget(step1_label)

        # 模式卡片
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        self.browser_card = _ModeCard("🌐", "浏览器操作", "在浏览器中演示网页操作流程")
        self.browser_card.clicked.connect(lambda: self._select_mode(RecordingMode.BROWSER))
        cards_layout.addWidget(self.browser_card)

        self.desktop_card = _ModeCard("🖥️", "桌面操作", "演示桌面应用的操作流程")
        self.desktop_card.clicked.connect(lambda: self._select_mode(RecordingMode.DESKTOP))
        cards_layout.addWidget(self.desktop_card)

        self.extension_card = _ModeCard(
            "🧩",
            "扩展触发",
            "在你自己的 Chrome 中通过扩展弹窗开始/停止录制",
        )
        self.extension_card.clicked.connect(lambda: self._select_mode(RecordingMode.EXTENSION_TRIGGERED))
        cards_layout.addWidget(self.extension_card)

        body_layout.addLayout(cards_layout)

        # URL 输入区
        self.url_container = QWidget()
        self.url_container.setStyleSheet("background: transparent;")
        url_layout = QVBoxLayout(self.url_container)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.setSpacing(8)

        url_label = QLabel("起始网址")
        url_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {TITLE_COLOR};")
        url_layout.addWidget(url_label)

        self.url_input = QLineEdit()
        self.url_input.setObjectName("url_input")
        self.url_input.setPlaceholderText("输入要打开的网址，留空则打开空白页")
        self.url_input.setStyleSheet(
            f"""
            QLineEdit {{
                border: 1.5px solid #e0e0e0;
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 14px;
                background-color: #f8f9fa;
            }}
            QLineEdit:focus {{
                border-color: {PRIMARY_COLOR};
                background-color: #ffffff;
            }}
        """
        )
        url_layout.addWidget(self.url_input)

        body_layout.addWidget(self.url_container)

        self.extension_container = QWidget()
        self.extension_container.setVisible(False)
        self.extension_container.setStyleSheet(
            """
            QWidget {
                background-color: #fffaf0;
                border: 1px solid #f3d8a6;
                border-radius: 10px;
            }
        """
        )
        extension_layout = QVBoxLayout(self.extension_container)
        extension_layout.setContentsMargins(16, 14, 16, 14)
        extension_layout.setSpacing(10)

        extension_hint = QLabel("请保持 Mexemplar 运行，然后在 Chrome 扩展弹窗中点击开始/停止录制。")
        extension_hint.setWordWrap(True)
        extension_hint.setStyleSheet("font-size: 13px; color: #8a6d3b; background: transparent;")
        extension_layout.addWidget(extension_hint)

        self.cert_status = QLabel("")
        self.cert_status.setWordWrap(True)
        self.cert_status.setStyleSheet("font-size: 12px; color: #8a6d3b; background: transparent;")
        extension_layout.addWidget(self.cert_status)

        cert_actions = QHBoxLayout()
        cert_actions.setContentsMargins(0, 0, 0, 0)
        cert_actions.setSpacing(8)

        self.install_cert_btn = QPushButton("安装证书")
        self.install_cert_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_cert_btn.setFixedHeight(34)
        self.install_cert_btn.setStyleSheet(
            """
            QPushButton {
                padding: 0 16px;
                border-radius: 6px;
                border: 1px solid #d6a34f;
                background-color: #fff3d9;
                color: #8a5a00;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #ffedc0;
            }
        """
        )
        self.install_cert_btn.clicked.connect(self._install_certificate)
        cert_actions.addWidget(self.install_cert_btn)
        cert_actions.addStretch()

        extension_layout.addLayout(cert_actions)
        body_layout.addWidget(self.extension_container)

        # ── 操作按钮 ──
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.record_btn = QPushButton("开始教学")
        self.record_btn.setObjectName("record_btn")
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setFixedHeight(44)
        self.record_btn.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 15px;
                font-weight: 600;
                padding: 0 32px;
                background-color: {PRIMARY_COLOR};
                color: white;
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: #4a58a8;
            }}
            QPushButton:pressed {{
                background-color: #3d4a91;
            }}
            QPushButton:disabled {{
                background-color: #c5c9e0;
            }}
        """
        )
        self.record_btn.clicked.connect(self.on_record_clicked)
        btn_layout.addWidget(self.record_btn)

        self.stop_btn = QPushButton("结束教学")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setFixedHeight(44)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            """
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
        """
        )
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        btn_layout.addWidget(self.stop_btn)

        btn_layout.addStretch()
        body_layout.addLayout(btn_layout)

        # ── 教学中状态指示 ──
        self.recording_indicator = QWidget()
        self.recording_indicator.setVisible(False)
        self.recording_indicator.setStyleSheet(
            """
            QWidget {
                background-color: #fff8f0;
                border: 1px solid #ffd6a5;
                border-radius: 8px;
            }
        """
        )
        indicator_layout = QHBoxLayout(self.recording_indicator)
        indicator_layout.setContentsMargins(16, 12, 16, 12)
        indicator_layout.setSpacing(10)

        self._pulse_dot = QLabel("●")
        self._pulse_dot.setStyleSheet("font-size: 14px; color: #e67e22; background: transparent;")
        self._pulse_dot.setFixedWidth(20)
        indicator_layout.addWidget(self._pulse_dot)

        indicator_text = QLabel("教学进行中 — 请在打开的窗口中演示操作，完成后点击「结束教学」")
        indicator_text.setStyleSheet("font-size: 13px; color: #8a6d3b; background: transparent;")
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
        status_title.setStyleSheet("font-size: 12px; font-weight: 600; color: #868e96;")
        status_header.addWidget(status_title)
        status_header.addStretch()
        status_layout.addLayout(status_header)

        self.status_text = QTextEdit()
        self.status_text.setObjectName("status_text")
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(120)
        self.status_text.setStyleSheet(
            """
            QTextEdit {
                border: 1px solid #e9ecef;
                border-radius: 6px;
                padding: 8px 10px;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: 11px;
                background-color: #f8f9fa;
                color: #495057;
            }
        """
        )
        status_layout.addWidget(self.status_text)

        body_layout.addWidget(self.status_section)

        body_layout.addStretch()
        content_layout.addWidget(body, 1)

        main_layout.addWidget(content)

    # ── 模式选择 ──

    def _select_mode(self, mode: str):
        """选择教学模式"""
        if self.is_recording:
            return
        self._current_mode = mode
        self.browser_card.set_selected(mode == RecordingMode.BROWSER)
        self.desktop_card.set_selected(mode == RecordingMode.DESKTOP)
        self.extension_card.set_selected(mode == RecordingMode.EXTENSION_TRIGGERED)
        self.url_container.setVisible(mode == RecordingMode.BROWSER)
        self.extension_container.setVisible(mode == RecordingMode.EXTENSION_TRIGGERED)
        if mode == RecordingMode.DESKTOP:
            self.url_input.clear()
        if mode == RecordingMode.EXTENSION_TRIGGERED:
            self.refresh_certificate_status()

    # ── 配置加载 ──

    def load_config(self):
        """从配置加载初始值"""
        try:
            default_mode = self.config.get("recording.default_recording_mode", default=RecordingMode.BROWSER)
            self._select_mode(default_mode)

            default_url = self.config.get("recording.browser_start_url", default="")
            if default_url:
                self.url_input.setText(default_url)
        except Exception as e:
            self.append_status(f"⚠️ 加载配置失败: {str(e)}")

    def refresh_certificate_status(self):
        """刷新 mitmproxy CA 证书状态。"""
        try:
            from src.recording.cert_manager import CertManager

            installed = CertManager().is_installed()
        except Exception as e:
            installed = False
            self.append_status(f"⚠️ 检查证书状态失败: {str(e)}")

        if installed:
            self.cert_status.setText("CA 证书状态：已安装。HTTPS 请求可被 mitmproxy 捕获。")
            self.cert_status.setStyleSheet("font-size: 12px; color: #2e7d32; background: transparent;")
            self.install_cert_btn.setEnabled(False)
            self.install_cert_btn.setText("已安装")
        else:
            self.cert_status.setText("CA 证书状态：未安装。未安装时 HTTPS 请求无法被代理录制。")
            self.cert_status.setStyleSheet("font-size: 12px; color: #b26a00; background: transparent;")
            self.install_cert_btn.setEnabled(True)
            self.install_cert_btn.setText("安装证书")

    def _install_certificate(self):
        """安装 mitmproxy CA 证书。"""
        try:
            from src.recording.cert_manager import CertManager

            ok = CertManager().ensure_installed()
        except Exception as e:
            ok = False
            self.append_status(f"⚠️ 安装证书失败: {str(e)}")

        self.refresh_certificate_status()
        if ok:
            QMessageBox.information(self, "证书安装", "mitmproxy CA 证书已安装或已存在。")
        else:
            QMessageBox.warning(
                self,
                "证书安装失败",
                "证书安装失败。请确认 mitmproxy 已生成证书，并以管理员权限运行安装。",
            )

    def _set_ui_state(self, *, recording: bool = False, awaiting: bool = False, show_log: bool = False):
        """统一设置录制相关的 UI 控件启用/可见状态。"""
        locked = recording or awaiting
        self.record_btn.setEnabled(not locked)
        self.stop_btn.setEnabled(locked)
        self.url_input.setEnabled(not locked)
        for card in (self.browser_card, self.desktop_card, self.extension_card):
            card.setEnabled(not locked)
        self.recording_indicator.setVisible(recording)
        self.status_section.setVisible(show_log or recording)

    def on_record_clicked(self):
        """开始教学"""
        mode = self._current_mode
        url = self.url_input.text().strip()

        if mode == RecordingMode.EXTENSION_TRIGGERED:
            self._awaiting_extension_start = True
            self.is_recording = False
            self._set_ui_state(awaiting=True, show_log=True)
            self.append_status(
                "扩展触发模式已就绪，请在 Chrome 扩展弹窗中点击开始录制。开始前可点击「结束教学」取消等待。"
            )
            self.recording_started.emit(mode, url)
            return

        self.is_recording = True
        self._set_ui_state(recording=True, show_log=True)

        self.recording_started.emit(mode, url)

        mode_name = {RecordingMode.BROWSER: "浏览器", RecordingMode.DESKTOP: "桌面", RecordingMode.EXTENSION_TRIGGERED: "扩展触发"}.get(mode, mode)
        self.append_status(f"开始{mode_name}教学")
        if mode == RecordingMode.BROWSER:
            display_url = url if url else "about:blank（空白页）"
            self.append_status(f"起始 URL: {display_url}")

    def on_stop_clicked(self):
        """结束教学"""
        if self._awaiting_extension_start and not self.is_recording:
            self._awaiting_extension_start = False
            self._set_ui_state()
            self.append_status("已取消等待扩展开始录制")
            return

        self.is_recording = False
        self._awaiting_extension_start = False
        self._set_ui_state()

        self.recording_stopped.emit()
        self.append_status("教学已结束")

    def on_extension_recording_started(self, recording_id: str = ""):
        """扩展实际开始录制后，同步更新界面状态。"""
        self._awaiting_extension_start = False
        self.is_recording = True
        self._set_ui_state(recording=True, show_log=True)

        if recording_id:
            self.append_status(f"扩展录制已开始：{recording_id}")
        else:
            self.append_status("扩展录制已开始")

    def on_extension_recording_stopped(self):
        """扩展实际停止录制后，同步恢复界面可操作状态。"""
        if not self._awaiting_extension_start and not self.is_recording:
            return

        self._awaiting_extension_start = False
        self.is_recording = False
        self._set_ui_state(show_log=True)
        self.append_status("扩展录制已结束")

    # ── 公共方法（保持兼容）──

    def append_status(self, message: str):
        """追加状态消息"""
        from src.utils.timezone import format_local, utc_now_naive

        timestamp = format_local(utc_now_naive(), "%H:%M:%S")
        self.status_text.append(f"[{timestamp}] {message}")
        # 有日志时自动显示日志区
        if not self.status_section.isVisible():
            self.status_section.setVisible(True)

    def reset(self):
        """重置界面状态"""
        self.is_recording = False
        self._awaiting_extension_start = False
        self._set_ui_state()
        self.status_text.clear()

        # 恢复 URL 区域可见性
        self.url_container.setVisible(self._current_mode == RecordingMode.BROWSER)
        self.extension_container.setVisible(self._current_mode == RecordingMode.EXTENSION_TRIGGERED)
