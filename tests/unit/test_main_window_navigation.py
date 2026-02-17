"""
主窗口导航功能测试

测试主窗口的页面切换功能：
- 主窗口创建
- 页面切换（主页 -> 录制页）
- 返回主页（录制页 -> 主页）
"""

import pytest
from PyQt6.QtWidgets import QApplication, QStackedWidget
from src.ui.main_window import MainWindow


@pytest.fixture
def app(qtbot):
    """创建 QApplication 实例"""
    if not QApplication.instance():
        app_instance = QApplication([])
    else:
        app_instance = QApplication.instance()
    yield app_instance
    # 不调用 quit()，避免影响其他测试


def test_main_window_creation(app):
    """测试主窗口创建"""
    window = MainWindow()

    # 验证基本属性
    assert window.windowTitle() == "Mexemplar"
    assert window.minimumSize().width() == 900
    assert window.minimumSize().height() == 600

    # 验证 stack 存在
    assert hasattr(window, "stack")
    assert isinstance(window.stack, QStackedWidget)

    # 验证页面存在
    assert hasattr(window, "home_page")
    assert hasattr(window, "record_page")
    assert window.home_page is not None
    assert window.record_page is not None


def test_initial_page_is_home(app):
    """测试初始页面是主页面"""
    window = MainWindow()

    # 初始应该显示主页面
    assert window.stack.currentWidget() == window.home_page
    assert window.stack.currentIndex() == 0  # 主页面是第一个添加的


def test_record_button_switches_to_recording_page(app):
    """测试录制按钮切换到录制页面"""
    window = MainWindow()

    # 点击录制按钮
    window._on_record_clicked()

    # 应该切换到录制页面
    assert window.stack.currentWidget() == window.record_page
    assert window.stack.currentIndex() == 1  # 录制页面是第二个添加的


def test_go_back_to_home(app):
    """测试返回主页面功能"""
    window = MainWindow()

    # 先切换到录制页面
    window._on_record_clicked()
    assert window.stack.currentWidget() == window.record_page

    # 返回主页面
    window.go_back_to_home()

    # 应该回到主页面
    assert window.stack.currentWidget() == window.home_page
    assert window.stack.currentIndex() == 0


def test_record_page_back_signal(app):
    """测试录制页面的返回信号"""
    window = MainWindow()

    # 切换到录制页面
    window._on_record_clicked()
    assert window.stack.currentWidget() == window.record_page

    # 触发录制页面的返回信号
    window.record_page.back_requested.emit()

    # 应该回到主页面
    assert window.stack.currentWidget() == window.home_page


def test_multiple_navigation_cycles(app):
    """测试多次导航循环"""
    window = MainWindow()

    # 第一次循环
    assert window.stack.currentWidget() == window.home_page
    window._on_record_clicked()
    assert window.stack.currentWidget() == window.record_page
    window.go_back_to_home()
    assert window.stack.currentWidget() == window.home_page

    # 第二次循环
    window._on_record_clicked()
    assert window.stack.currentWidget() == window.record_page
    window.go_back_to_home()
    assert window.stack.currentWidget() == window.home_page

    # 第三次循环（使用信号）
    window._on_record_clicked()
    assert window.stack.currentWidget() == window.record_page
    window.record_page.back_requested.emit()
    assert window.stack.currentWidget() == window.home_page


def test_stack_widget_count(app):
    """测试 stack 中有两个页面"""
    window = MainWindow()

    # 应该有 2 个页面：主页和录制页
    assert window.stack.count() == 2


def test_home_page_has_buttons(app):
    """测试主页面有所有功能按钮"""
    window = MainWindow()
    window.show()  # 需要显示窗口才能使按钮可见

    # 验证所有按钮存在
    assert hasattr(window, "record_button")
    assert hasattr(window, "execute_button")
    assert hasattr(window, "tools_button")
    assert hasattr(window, "settings_button")

    # 验证按钮存在（不需要验证 isVisible，因为在没有显示的窗口中按钮默认不可见）
    assert window.record_button is not None
    assert window.execute_button is not None
    assert window.tools_button is not None
    assert window.settings_button is not None


def test_record_page_widgets(app):
    """测试录制页面的组件"""
    window = MainWindow()

    # 录制页面应该有必要的组件
    assert hasattr(window.record_page, "mode_combo")
    assert hasattr(window.record_page, "url_input")
    assert hasattr(window.record_page, "record_btn")
    assert hasattr(window.record_page, "stop_btn")
    assert hasattr(window.record_page, "progress_bar")
    assert hasattr(window.record_page, "status_text")
    assert hasattr(window.record_page, "back_button")


def test_back_button_in_record_page(app):
    """测试录制页面有返回按钮"""
    window = MainWindow()

    # 返回按钮应该存在
    assert window.record_page.back_button is not None
    # 注意：不检查 isVisible，因为在未显示的窗口中按钮默认不可见

    # 点击返回按钮应该触发信号
    window._on_record_clicked()
    assert window.stack.currentWidget() == window.record_page

    # 模拟按钮点击
    window.record_page.back_button.click()

    # 应该返回主页面
    assert window.stack.currentWidget() == window.home_page
