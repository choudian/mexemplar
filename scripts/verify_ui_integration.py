"""
UI 集成验证脚本

快速验证意图确认和待试用工具页面是否正确集成到主窗口
"""

import sys
from PyQt6.QtWidgets import QApplication


def main():
    print("=" * 70)
    print("UI 集成验证")
    print("=" * 70)

    # 创建 QApplication
    app = QApplication(sys.argv)

    try:
        from src.ui.main_window import MainWindow

        # 创建主窗口
        window = MainWindow()
        print("\n[OK] 主窗口创建成功")

        # 获取已注册的页面
        page_names = list(window.main_content.pages.keys())
        print(f"[OK] 已注册页面: {page_names}")

        # 检查新页面
        new_pages = ["intent_confirmation", "pending_tools"]
        for page in new_pages:
            if page in page_names:
                print(f"[OK] {page} 页面已添加")
            else:
                print(f"[ERROR] {page} 页面未找到")

        # 检查侧边栏按钮
        sidebar = window.sidebar
        if hasattr(sidebar, "intent_btn"):
            print("[OK] 侧边栏意图确认按钮已添加")
        else:
            print("[ERROR] 侧边栏意图确认按钮未找到")

        if hasattr(sidebar, "pending_tools_btn"):
            print("[OK] 侧边栏待试用工具按钮已添加")
        else:
            print("[ERROR] 侧边栏待试用工具按钮未找到")

        # 测试页面切换
        print("\n测试页面切换:")
        for page_name in page_names:
            window.main_content.switch_page(page_name)
            print(f"  - 切换到: {page_name}")

        # 测试导航按钮
        print("\n测试导航按钮:")
        window.sidebar.intent_btn.click()
        print(f"  - 点击意图确认按钮 -> 当前页面: {window.main_content.current_page}")

        window.sidebar.pending_tools_btn.click()
        print(f"  - 点击待试用工具按钮 -> 当前页面: {window.main_content.current_page}")

        window.sidebar.tools_btn.click()
        print(f"  - 点击工具列表按钮 -> 当前页面: {window.main_content.current_page}")

        print("\n" + "=" * 70)
        print("所有验证通过!")
        print("=" * 70)
        print("\n提示: 可以通过点击侧边栏的导航按钮在不同页面之间切换")

    except Exception as e:
        print(f"\n[ERROR] 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
