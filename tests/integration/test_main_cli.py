import pytest
import subprocess
import sys


@pytest.mark.skip(reason="CLI 功能尚未完全实现，需要 PyQt6 支持")
def test_cli_help():
    """测试 CLI 帮助信息"""
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "Mexemplar" in result.stdout


def test_cli_version():
    """测试版本信息"""
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "--version"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "0.1.0" in result.stdout
