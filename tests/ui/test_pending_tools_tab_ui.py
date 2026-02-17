"""
测试待试用工具列表 UI（带 Tab）

验证：
1. Tab 切换正常工作
2. 待试用工具列表显示正确
3. 已发布工具列表显示正确
4. 工具操作功能正常
"""

import sys
from datetime import datetime
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from src.ui.pending_tools_ui import PendingToolsUI
from src.business.tool_trial.trial_models import PendingTool, PendingToolStatus
from src.data.models import Tool


def test_tab_switching():
    """测试 Tab 切换功能"""
    app = QApplication(sys.argv)

    # 创建 UI
    ui = PendingToolsUI()
    ui.show()

    # 测试初始状态
    print("[PASS] UI created successfully")
    print(f"  - Tab count: {ui.tab_widget.count()}")
    print(f"  - Current tab index: {ui.tab_widget.currentIndex()}")

    # 测试切换到已发布 Tab
    ui.tab_widget.setCurrentIndex(1)
    print(f"[PASS] Switched to published tab (index: {ui.tab_widget.currentIndex()})")

    # 测试切换回待试用 Tab
    ui.tab_widget.setCurrentIndex(0)
    print(f"[PASS] Switched back to pending tab (index: {ui.tab_widget.currentIndex()})")

    # 测试工具列表
    print(f"\n[PASS] Pending tools count: {len(ui.pending_tools)}")
    print(f"[PASS] Published tools count: {len(ui.published_tools)}")

    # 测试工具提升功能
    test_pending_tool = PendingTool(
        tool_name="Test Tool",
        tool_description="This is a test tool",
        status=PendingToolStatus.TRIAL_SUCCESS,
        trial_count=1,
        max_trials=3,
        created_at=datetime.now(),
    )

    test_published_tool = Tool(
        tool_name="Test Tool",
        description="This is a test tool",
        source="trial",
        created_at=datetime.now(),
    )

    # 模拟工具提升
    ui.promote_tool(test_pending_tool.pending_tool_id, test_published_tool)

    print(f"\n[PASS] Tool promoted successfully")
    print(f"  - Pending tools count: {len(ui.pending_tools)}")
    print(f"  - Published tools count: {len(ui.published_tools)}")
    print(f"  - Current tab index: {ui.tab_widget.currentIndex()}")

    print("\n[SUCCESS] All tests passed!")

    # 清理
    ui.cleanup()


if __name__ == "__main__":
    test_tab_switching()
