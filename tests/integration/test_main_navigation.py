"""
主界面导航集成测试

验证意图确认和待试用工具页面是否正确集成到主窗口中
"""

import pytest
from PyQt6.QtWidgets import QApplication
import sys


@pytest.fixture(scope="module")
def app():
    """创建 QApplication 实例"""
    application = QApplication.instance()
    if application is None:
        application = QApplication(sys.argv)
    yield application
    # 不要退出 QApplication，因为它可能被其他测试使用


def test_main_window_imports(app):
    """测试主窗口和相关组件能否正确导入"""
    from src.ui.main_window import MainWindow
    from src.ui.intent_confirmation_ui import IntentConfirmationUI
    from src.ui.tools_management_ui import ToolsManagementUI

    # 如果没有抛出异常，说明导入成功
    assert MainWindow is not None
    assert IntentConfirmationUI is not None
    assert ToolsManagementUI is not None


def test_main_window_creation(app):
    """测试主窗口能否正确创建"""
    from src.ui.main_window import MainWindow

    window = MainWindow()

    # 验证主窗口创建成功
    assert window is not None
    assert window.windowTitle() == "Mexemplar"


def test_pages_registered(app):
    """测试所有页面是否正确注册"""
    from src.ui.main_window import MainWindow

    window = MainWindow()
    page_names = list(window.main_content.pages.keys())

    # 验证所有必需的页面都已注册
    assert "chat" in page_names
    assert "recording" in page_names
    assert "tools" in page_names
    assert "intent_confirmation" in page_names
    assert "pending_tools" in page_names
    assert "settings" in page_names


def test_page_switching(app):
    """测试页面切换功能"""
    from src.ui.main_window import MainWindow

    window = MainWindow()

    # 测试切换到意图确认页面
    window.main_content.switch_page("intent_confirmation")
    assert window.main_content.current_page == "intent_confirmation"

    # 测试切换到待试用工具页面
    window.main_content.switch_page("pending_tools")
    assert window.main_content.current_page == "pending_tools"

    # 测试切换回其他页面
    window.main_content.switch_page("chat")
    assert window.main_content.current_page == "chat"


def test_intent_confirmation_page_widget(app):
    """测试意图确认页面是否是正确的组件"""
    from src.ui.main_window import MainWindow
    from src.ui.intent_confirmation_ui import IntentConfirmationUI

    window = MainWindow()
    intent_page = window.main_content.pages.get("intent_confirmation")

    assert intent_page is not None
    assert isinstance(intent_page, IntentConfirmationUI)


def test_pending_tools_page_widget(app):
    """测试待试用工具页面是否是正确的组件"""
    from src.ui.main_window import MainWindow
    from src.ui.tools_management_ui import ToolsManagementUI

    window = MainWindow()
    pending_tools_page = window.main_content.pages.get("pending_tools")

    assert pending_tools_page is not None
    assert isinstance(pending_tools_page, ToolsManagementUI)


def test_sidebar_navigation_buttons(app):
    """测试侧边栏是否有正确的导航按钮"""
    from src.ui.main_window import MainWindow

    window = MainWindow()
    sidebar = window.sidebar

    # 验证侧边栏有待试用工具按钮
    assert hasattr(sidebar, "pending_tools_btn")

    # 验证按钮的 page_name 属性
    assert sidebar.pending_tools_btn.property("page_name") == "pending_tools"

    # 验证意图确认按钮已从侧边栏移除（因为它是录制流程的一部分）
    assert not hasattr(sidebar, "intent_btn")


def test_navigation_signal_connection(app):
    """测试导航信号是否正确连接"""
    from src.ui.main_window import MainWindow

    window = MainWindow()

    # 模拟点击待试用工具按钮
    window.sidebar.pending_tools_btn.click()

    # 验证页面已切换
    assert window.main_content.current_page == "pending_tools"

    # 模拟点击其他按钮
    window.sidebar.tools_btn.click()

    # 验证页面已切换
    assert window.main_content.current_page == "tools"

    # 注意：意图确认页面只能通过录制流程触发，不是通过侧边栏导航


if __name__ == "__main__":
    # 直接运行此文件进行快速测试
    app_instance = QApplication(sys.argv)

    print("=" * 60)
    print("主界面导航集成测试")
    print("=" * 60)

    try:
        from src.ui.main_window import MainWindow

        window = MainWindow()
        page_names = list(window.main_content.pages.keys())

        print(f"\n已注册页面: {page_names}")

        # 测试页面切换
        for page_name in page_names:
            window.main_content.switch_page(page_name)
            print(f"[OK] 切换到页面: {page_name}")

        # 测试侧边栏导航
        print("\n测试侧边栏导航:")
        window.sidebar.intent_btn.click()
        print(f"[OK] 点击意图确认按钮，当前页面: {window.main_content.current_page}")

        window.sidebar.pending_tools_btn.click()
        print(f"[OK] 点击待试用工具按钮，当前页面: {window.main_content.current_page}")

        print("\n" + "=" * 60)
        print("所有测试通过!")
        print("=" * 60)

    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
