import pytest
import subprocess
import sys


@pytest.mark.skip(reason="CLI 子命令尚未完全实现，需要 PyQt6 支持")
def test_record_command():
    """测试 record 子命令"""
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "record", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "录制" in result.stdout


@pytest.mark.skip(reason="CLI 子命令尚未完全实现，需要 PyQt6 支持")
def test_execute_command():
    """测试 execute 子命令"""
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "execute", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "工具" in result.stdout


@pytest.mark.skip(reason="CLI 子命令尚未完全实现，需要 PyQt6 支持")
def test_config_command():
    """测试 config 子命令"""
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "config", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "配置" in result.stdout
