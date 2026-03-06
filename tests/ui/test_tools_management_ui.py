"""
工具管理 UI 测试示例

演示如何使用 ToolsManagementUI 组件
"""

import sys
from datetime import datetime, timedelta
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt6.QtCore import QTimer
from src.ui.tools_management_ui import ToolsManagementUI
from src.business.tool_trial.trial_models import PendingTool, PendingToolStatus
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
        self.setWindowTitle("工具管理 UI 测试")
        self.setMinimumSize(1200, 800)

        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 创建工具管理 UI
        self.tools_ui = ToolsManagementUI()

        # 连接信号
        self.tools_ui.tool_promoted.connect(self._on_tool_promoted)

        main_layout.addWidget(self.tools_ui)

        # 加载测试数据
        QTimer.singleShot(1000, self._load_test_data)

    def _load_test_data(self):
        """加载测试数据"""
        # 创建不同状态的测试工具
        now = datetime.now()

        test_tools = [
            # 1. 等待试用
            PendingTool(
                tool_name="网页登录",
                tool_description="自动登录到指定网站，支持用户名密码登录",
                status=PendingToolStatus.PENDING_TRIAL,
                trial_count=0,
                max_trials=3,
                created_at=now,
            ),

            # 2. 试用成功
            PendingTool(
                tool_name="数据提取",
                tool_description="从网页中提取表格数据并导出为 Excel",
                status=PendingToolStatus.TRIAL_SUCCESS,
                trial_count=1,
                max_trials=3,
                created_at=now - timedelta(hours=2),
            ),

            # 3. 试用失败
            PendingTool(
                tool_name="表单填写",
                tool_description="自动填写并提交注册表单",
                status=PendingToolStatus.TRIAL_FAILED,
                trial_count=2,
                max_trials=3,
                last_error="找不到元素：#submit-button",
                created_at=now - timedelta(hours=5),
            ),

            # 4. 等待真实数据
            PendingTool(
                tool_name="文件下载",
                tool_description="从网站下载指定文件",
                status=PendingToolStatus.AWAITING_REAL_DATA,
                trial_count=1,
                max_trials=3,
                created_at=now - timedelta(days=1),
            ),

            # 5. 试用中
            PendingTool(
                tool_name="页面滚动",
                tool_description="控制页面滚动到指定位置",
                status=PendingToolStatus.TRIALING,
                trial_count=1,
                max_trials=3,
                created_at=now - timedelta(minutes=30),
            ),

            # 6. 已提升
            PendingTool(
                tool_name="截图工具",
                tool_description="截取网页截图",
                status=PendingToolStatus.PROMOTED,
                trial_count=1,
                max_trials=3,
                promoted_at=now - timedelta(days=2),
                created_at=now - timedelta(days=2),
            ),

            # 7. 最终失败
            PendingTool(
                tool_name="视频播放",
                tool_description="自动播放网页视频",
                status=PendingToolStatus.FAILED,
                trial_count=3,
                max_trials=3,
                last_error="无法自动播放视频，需要用户交互",
                created_at=now - timedelta(days=3),
            ),

            # 8. 更多工具
            PendingTool(
                tool_name="搜索查询",
                tool_description="在搜索引擎中执行查询",
                status=PendingToolStatus.PENDING_TRIAL,
                trial_count=0,
                max_trials=3,
                created_at=now,
            ),

            PendingTool(
                tool_name="链接点击",
                tool_description="点击页面上的链接",
                status=PendingToolStatus.PENDING_TRIAL,
                trial_count=0,
                max_trials=3,
                created_at=now,
            ),

            PendingTool(
                tool_name="文本复制",
                tool_description="复制页面上的文本内容",
                status=PendingToolStatus.TRIAL_SUCCESS,
                trial_count=1,
                max_trials=3,
                created_at=now - timedelta(hours=1),
            ),
        ]

        self.tools_ui.update_tools(test_tools)
        self.logger.info(f"已加载 {len(test_tools)} 个测试工具")

    def _on_tool_promoted(self, pending_tool_id: str):
        """工具提升回调"""
        self.logger.info(f"工具已提升: {pending_tool_id}")

    def closeEvent(self, event):
        """窗口关闭事件"""
        self.logger.info("正在关闭窗口...")
        # 清理资源
        self.tools_ui.cleanup()
        event.accept()


def main():
    """主函数"""
    from PyQt6.QtCore import QTimer

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
