"""
配置文件加载器单元测试

测试 ConfigFileLoader 的文件读写功能
"""

import pytest
import tempfile
import json
import os
from pathlib import Path

from src.data.config_models import ConfigFileLoader, AppConfig


@pytest.fixture
def temp_config_file():
    """创建临时配置文件"""
    fd, config_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(config_path)

    yield config_path

    # 清理
    if os.path.exists(config_path):
        os.remove(config_path)


@pytest.fixture
def sample_config_data():
    """示例配置数据"""
    return {
        "app_name": "TestApp",
        "version": "1.0.0",
        "debug": True,
        "database": {"db_path": "/tmp/test.db", "auto_init": False},
        "ai": {"provider": "anthropic", "model": "claude-sonnet-4-20250514", "temperature": 0.5},
        "recording": {"screenshot_quality": 90, "browser_type": "chromium"},
        "ui": {"theme": "dark", "language": "en_US"},
    }


class TestConfigFileLoader:
    """ConfigFileLoader 测试类"""

    def test_init_with_path(self, temp_config_file):
        """测试使用指定路径初始化"""
        loader = ConfigFileLoader(temp_config_file)
        assert loader.config_path == Path(temp_config_file)

    def test_init_without_path(self):
        """测试使用默认路径初始化"""
        loader = ConfigFileLoader()
        assert loader.config_path is not None
        assert loader.config_path.name == "config.json"

    def test_load_from_non_existent_file(self, temp_config_file):
        """测试加载不存在的配置文件"""
        loader = ConfigFileLoader(temp_config_file)
        config = loader.load()

        # 应该返回默认配置
        assert isinstance(config, AppConfig)
        assert config.app_name == "Mexemplar"
        assert config.version == "0.1.0"

    def test_load_from_valid_file(self, temp_config_file, sample_config_data):
        """测试加载有效的配置文件"""
        # 创建配置文件
        with open(temp_config_file, "w", encoding="utf-8") as f:
            json.dump(sample_config_data, f, ensure_ascii=False)

        # 加载配置
        loader = ConfigFileLoader(temp_config_file)
        config = loader.load()

        # 验证加载的配置
        assert config.app_name == "TestApp"
        assert config.version == "1.0.0"
        assert config.debug is True
        assert config.database.db_path == "/tmp/test.db"
        assert config.database.auto_init is False
        assert config.ai.provider == "anthropic"
        assert config.ai.model == "claude-sonnet-4-20250514"
        assert config.ai.temperature == 0.5
        assert config.recording.screenshot_quality == 90
        assert config.recording.browser_type == "chromium"
        assert config.ui.theme == "dark"
        assert config.ui.language == "en_US"

    def test_load_from_invalid_json(self, temp_config_file):
        """测试加载无效的 JSON 文件"""
        # 创建无效的 JSON 文件
        with open(temp_config_file, "w", encoding="utf-8") as f:
            f.write("{ invalid json }")

        loader = ConfigFileLoader(temp_config_file)
        config = loader.load()

        # 应该返回默认配置而不是抛出异常
        assert isinstance(config, AppConfig)
        assert config.app_name == "Mexemplar"

    def test_save_config(self, temp_config_file):
        """测试保存配置"""
        # 创建配置对象
        config = AppConfig()
        config.app_name = "TestApp"
        config.debug = True
        config.ai.model = "test-model"

        # 保存配置
        loader = ConfigFileLoader(temp_config_file)
        loader.save(config)

        # 验证文件已创建
        assert os.path.exists(temp_config_file)

        # 验证文件内容
        with open(temp_config_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["app_name"] == "TestApp"
        assert data["debug"] is True
        assert data["ai"]["model"] == "test-model"
        # API 密钥不应该被保存
        assert data["ai"].get("api_key") is None

    def test_save_creates_directory(self):
        """测试保存时自动创建目录"""
        # 使用一个不存在的目录
        temp_dir = tempfile.mkdtemp()
        config_path = os.path.join(temp_dir, "subdir", "config.json")

        try:
            config = AppConfig()
            loader = ConfigFileLoader(config_path)
            loader.save(config)

            # 验证目录和文件已创建
            assert os.path.exists(config_path)
        finally:
            # 清理
            import shutil

            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def test_round_trip(self, temp_config_file):
        """测试加载-保存-加载的完整流程"""
        # 创建初始配置
        config1 = AppConfig()
        config1.app_name = "TestApp"
        config1.ai.temperature = 0.9

        # 保存
        loader = ConfigFileLoader(temp_config_file)
        loader.save(config1)

        # 重新加载
        config2 = loader.load()

        # 验证数据一致性
        assert config2.app_name == "TestApp"
        assert config2.ai.temperature == 0.9
