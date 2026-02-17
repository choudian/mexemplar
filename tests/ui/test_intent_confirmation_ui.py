"""
Intent 确认 UI 测试示例

演示如何使用 IntentConfirmationUI 组件
"""

import sys
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget
from src.business.intent.intent_models import Intent, IntentStatus
from src.ui.intent_confirmation_ui import IntentConfirmationUI
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TestMainWindow(QMainWindow):
    """测试主窗口"""

    def __init__(self):
        super().__init__()
        self.logger = get_logger(__name__)
        self.init_ui()

    def init_ui(self):
        """初始化 UI"""
        self.setWindowTitle("Intent 确认 UI 测试")
        self.setMinimumSize(1200, 800)

        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # 创建测试按钮
        button_layout = QVBoxLayout()

        btn1 = QPushButton("测试：分析中状态")
        btn1.clicked.connect(self._test_analyzing_state)
        button_layout.addWidget(btn1)

        btn2 = QPushButton("测试：确认状态（完整数据）")
        btn2.clicked.connect(self._test_confirmation_state_full)
        button_layout.addWidget(btn2)

        btn3 = QPushButton("测试：确认状态（最小数据）")
        btn3.clicked.connect(self._test_confirmation_state_minimal)
        button_layout.addWidget(btn3)

        main_layout.addLayout(button_layout)

        # 创建 Intent 确认 UI
        self.intent_ui = IntentConfirmationUI()
        self.intent_ui.intent_confirmed.connect(self._on_intent_confirmed)
        self.intent_ui.intent_cancelled.connect(self._on_intent_cancelled)

        main_layout.addWidget(self.intent_ui, 1)

    def _test_analyzing_state(self):
        """测试：分析中状态"""
        intent = Intent(
            intent_id="test-intent-001",
            recording_id="recording-001",
            status=IntentStatus.ANALYZING,
            created_at=datetime.now(),
        )
        self.intent_ui.load_intent(intent)
        self.logger.info("已加载分析中状态")

    def _test_confirmation_state_full(self):
        """测试：确认状态（完整数据）"""
        intent = Intent(
            intent_id="test-intent-002",
            recording_id="recording-002",
            core_operations=[
                "打开网站：https://example.com",
                "输入用户名和密码",
                "点击登录按钮",
                "验证登录成功",
                "导航到个人中心",
            ],
            target="Example 网站",
            business_scenario="用户登录",
            expected_results=[
                "成功登录到网站",
                "显示用户个人信息",
            ],
            status=IntentStatus.PENDING_CONFIRMATION,
            analysis_confidence=0.95,
            llm_model_used="claude-sonnet-4.5",
            created_at=datetime.now(),
        )
        self.intent_ui.load_intent(intent)
        self.logger.info("已加载确认状态（完整数据）")

    def _test_confirmation_state_minimal(self):
        """测试：确认状态（最小数据）"""
        intent = Intent(
            intent_id="test-intent-003",
            recording_id="recording-003",
            core_operations=[
                "点击按钮",
                "等待页面加载",
            ],
            target=None,
            business_scenario=None,
            expected_results=[],
            status=IntentStatus.PENDING_CONFIRMATION,
            analysis_confidence=0.75,
            created_at=datetime.now(),
        )
        self.intent_ui.load_intent(intent)
        self.logger.info("已加载确认状态（最小数据）")

    def _on_intent_confirmed(self, intent_id: str):
        """Intent 确认回调"""
        self.logger.info(f"Intent 已确认: {intent_id}")
        confirmed_ops = self.intent_ui.get_confirmed_operations()
        self.logger.info(f"确认的操作: {confirmed_ops}")

    def _on_intent_cancelled(self, intent_id: str):
        """Intent 取消回调"""
        self.logger.info(f"Intent 已取消: {intent_id}")

    def closeEvent(self, event):
        """窗口关闭事件"""
        self.logger.info("正在关闭窗口...")
        # 清理资源
        self.intent_ui.cleanup()
        event.accept()


def main():
    """主函数"""
    app = QApplication(sys.argv)

    # 加载样式表
    from pathlib import Path
    style_path = Path(__file__).parent.parent.parent / "src" / "ui" / "resources" / "styles.qss"
    if style_path.exists():
        with open(style_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
            logger.info(f"已加载样式表: {style_path}")

    # 创建并显示主窗口
    window = TestMainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
