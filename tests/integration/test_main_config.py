import pytest
import subprocess
import sys


@pytest.mark.skip(reason="CLI 功能尚未完全实现，需要 PyQt6 支持")
def test_config_initialization():
    """测试配置初始化"""
    result = subprocess.run(
        [sys.executable, "-m", "src.main"], capture_output=True, text=True, timeout=10
    )
    # 应该成功启动（虽然会立即退出）
    assert result.returncode == 0
