"""
工具执行功能测试示例

演示如何使用已发布工具的执行功能
"""

import sys
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt6.QtCore import QTimer
from src.ui.tools_management_ui import ToolsManagementUI
from src.data.models import Tool
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
        self.setWindowTitle("工具执行功能测试")
        self.setMinimumSize(1400, 900)

        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 创建工具管理 UI
        self.tools_ui = ToolsManagementUI()

        main_layout.addWidget(self.tools_ui)

        # 延迟加载测试数据
        QTimer.singleShot(1000, self._load_test_data)

    def _load_test_data(self):
        """加载测试数据"""
        now = datetime.now()

        # 待试用工具
        pending_tools = []

        # 已发布工具（包含不同类型）
        published_tools = [
            # 1. 无参数工具（可以直接执行）
            Tool(
                tool_name="截图工具",
                description="截取当前页面的截图",
                source="trial",
                execution_strategy="browser",
                parameters=[],  # 无参数
                created_at=now,
            ),

            # 2. 有参数工具
            Tool(
                tool_name="数据提取",
                description="从网页提取指定数据",
                source="intent",
                execution_strategy="api",
                parameters=[
                    {
                        "name": "url",
                        "type": "text",
                        "description": "目标网页 URL",
                        "required": True,
                        "default": "https://example.com",
                    },
                    {
                        "name": "selector",
                        "type": "text",
                        "description": "CSS 选择器",
                        "required": True,
                    },
                ],
                created_at=now,
            ),

            # 3. 多参数工具
            Tool(
                tool_name="表单填写",
                description="自动填写并提交表单",
                source="trial",
                execution_strategy="browser",
                parameters=[
                    {
                        "name": "username",
                        "type": "text",
                        "description": "用户名",
                        "required": True,
                    },
                    {
                        "name": "password",
                        "type": "password",
                        "description": "密码",
                        "required": True,
                    },
                    {
                        "name": "remember_me",
                        "type": "text",
                        "description": "记住登录状态",
                        "required": False,
                        "default": "false",
                    },
                ],
                created_at=now,
            ),

            # 4. 有执行代码的工具
            Tool(
                tool_name="文本搜索",
                description="在页面中搜索文本",
                source="manual",
                execution_strategy="browser",
                parameters=[
                    {
                        "name": "search_text",
                        "type": "text",
                        "description": "要搜索的文本",
                        "required": True,
                    },
                ],
                execution_code="""
# 在页面中搜索文本
def search_text(page, search_text):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto("https://example.com")

        # 搜索文本
        found = page.content().__contains__(search_text)

        browser.close()
        return {"found": found, "search_text": search_text}
""",
                created_at=now,
            ),
        ]

        self.tools_ui.update_pending_tools(pending_tools)
        self.tools_ui.update_published_tools(published_tools)

        self.logger.info(f"已加载 {len(published_tools)} 个已发布工具")

    def closeEvent(self, event):
        """窗口关闭事件"""
        self.logger.info("正在关闭窗口...")
        # 清理资源
        self.tools_ui.cleanup()
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
