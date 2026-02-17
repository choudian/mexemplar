"""
pytest 配置文件

用于处理测试环境和特殊情况
"""

import sys
import os
from unittest.mock import MagicMock

# 检查是否在 CI 环境（无图形界面）
# 通过检查 DISPLAY 环境变量或尝试导入 pynput 来判断
def is_headless_environment():
    """检查是否在无图形界面环境"""
    # 检查 DISPLAY 环境变量（Linux）
    if os.environ.get('DISPLAY') is None and sys.platform == 'linux':
        return True
    # 检查是否在 CI 环境
    if os.environ.get('CI') == 'true':
        return True
    return False

# 如果在无图形界面环境，mock 掉需要图形界面的模块
if is_headless_environment():
    # Mock pynput
    sys.modules['pynput'] = MagicMock()
    sys.modules['pynput.mouse'] = MagicMock()
    sys.modules['pynput.keyboard'] = MagicMock()

    # Mock pywinauto
    sys.modules['pywinauto'] = MagicMock()
    sys.modules['pywinauto.application'] = MagicMock()
    sys.modules['pywinauto.keyboard'] = MagicMock()
    sys.modules['pywinauto.mouse'] = MagicMock()

    # Mock PyQt6
    sys.modules['PyQt6'] = MagicMock()
    sys.modules['PyQt6.QtCore'] = MagicMock()
    sys.modules['PyQt6.QtGui'] = MagicMock()
    sys.modules['PyQt6.QtWidgets'] = MagicMock()
