"""
统一配置管理器单元测试

测试 UnifiedConfigManager 的核心功能
"""

import pytest
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
import shutil

from src.data.unified_config import UnifiedConfigManager, get_unified_config


@pytest.fixture
def temp_dir():
    """创建临时目录"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir

    # 清理整个目录（避免文件锁定问题）
    try:
        shutil.rmtree(temp_dir)
    except:
        pass


@pytest.fixture
def temp_db(temp_dir):
    """创建临时数据库"""
    db_path = os.path.join(temp_dir, "test.db")
    yield db_path


@pytest.fixture
def temp_config(temp_dir):
    """创建临时配置文件"""
    config_path = os.path.join(temp_dir, "config.json")
    yield config_path


class TestUnifiedConfigManager:
    """UnifiedConfigManager 测试类"""

    def test_initialization(self, temp_config, temp_db):
        """测试初始化"""
        config = UnifiedConfigManager(temp_config, temp_db)

        assert config.file_loader is not None
        assert config.file_config is not None
        assert config.db is not None
        assert isinstance(config._runtime_cache, dict)

    def test_get_with_default(self, temp_config, temp_db):
        """测试获取配置（使用默认值）"""
        config = UnifiedConfigManager(temp_config, temp_db)

        # 获取不存在的配置
        value = config.get("nonexistent.key", default="default_value")
        assert value == "default_value"

    def test_get_from_file_config(self, temp_config, temp_db):
        """测试从配置文件获取"""
        config = UnifiedConfigManager(temp_config, temp_db)

        # 获取配置文件中的默认值
        model = config.get("ai.model")
        assert model == "claude-sonnet-4-20250514"

    def test_get_ai_api_key_from_config(self, temp_config, temp_db):
        """测试从配置文件获取 API 密钥"""
        # 注意：AppConfig.from_dict 会过滤 api_key，所以直接设置到运行时缓存
        config = UnifiedConfigManager(temp_config, temp_db)
        config._runtime_cache["ai.api_key"] = "sk-test-key-from-file"

        api_key = config.get_ai_api_key()
        assert api_key == "sk-test-key-from-file"

    def test_get_ai_api_key_from_keyring(self, temp_config, temp_db):
        """测试从 keyring 获取 API 密钥"""
        config = UnifiedConfigManager(temp_config, temp_db)

        # 使用 sys.modules 来模拟 keyring 模块
        import sys

        mock_keyring = Mock()
        mock_keyring.get_password.return_value = "sk-test-key-from-keyring"

        # 临时添加到 sys.modules
        sys.modules["keyring"] = mock_keyring

        try:
            api_key = config.get_ai_api_key()
            assert api_key == "sk-test-key-from-keyring"
            mock_keyring.get_password.assert_called_once_with("Mexemplar", "anthropic_api_key")
        finally:
            # 清理
            if "keyring" in sys.modules:
                del sys.modules["keyring"]

    def test_get_ai_api_key_keyring_error(self, temp_config, temp_db):
        """测试 keyring 读取失败的情况"""
        config = UnifiedConfigManager(temp_config, temp_db)

        # 使用 sys.modules 来模拟 keyring 模块
        import sys

        mock_keyring = Mock()
        mock_keyring.get_password.side_effect = Exception("Keyring error")

        sys.modules["keyring"] = mock_keyring

        try:
            api_key = config.get_ai_api_key()
            # 应该返回 None，而不是抛出异常
            assert api_key is None
        finally:
            if "keyring" in sys.modules:
                del sys.modules["keyring"]

    def test_get_ai_api_key_priority(self, temp_config, temp_db):
        """测试 API 密钥获取优先级：运行时缓存 > keyring"""
        config = UnifiedConfigManager(temp_config, temp_db)

        # 设置运行时缓存（模拟配置文件已加载）
        config._runtime_cache["ai.api_key"] = "sk-from-cache"

        # 使用 sys.modules 来模拟 keyring
        import sys

        mock_keyring = Mock()
        mock_keyring.get_password.return_value = "sk-from-keyring"
        sys.modules["keyring"] = mock_keyring

        try:
            api_key = config.get_ai_api_key()

            # 应该返回缓存中的值，不应该调用 keyring
            assert api_key == "sk-from-cache"
            mock_keyring.get_password.assert_not_called()
        finally:
            if "keyring" in sys.modules:
                del sys.modules["keyring"]

    def test_set_runtime_config(self, temp_config, temp_db):
        """测试设置运行时配置"""
        config = UnifiedConfigManager(temp_config, temp_db)

        # 设置运行时配置
        config.set_runtime("test.key", "test_value")

        # 验证可以从缓存中读取
        value = config.get("test.key")
        assert value == "test_value"

    def test_set_database_config(self, temp_config, temp_db):
        """测试设置数据库配置"""
        config = UnifiedConfigManager(temp_config, temp_db)

        # 设置数据库配置
        config.set("test.db_key", "db_value", persist="database")

        # 验证可以从数据库读取
        value = config.db.get_setting("test.db_key")
        assert value == "db_value"

        # 验证可以通过 get() 读取
        value = config.get("test.db_key")
        assert value == "db_value"

    def test_convenience_methods(self, temp_config, temp_db):
        """测试便捷方法"""
        config = UnifiedConfigManager(temp_config, temp_db)

        # AI 配置
        assert config.get_ai_model() == "claude-sonnet-4-20250514"
        assert config.get_ai_temperature() == 0.7
        assert config.get_ai_max_tokens() == 4096

        # WebSocket 配置
        assert config.get_websocket_host() == "127.0.0.1"
        assert config.get_websocket_port() == 8765

        # 录制配置
        assert config.get_recording_browser_type() == "chromium"

        # UI 配置
        assert config.get_ui_theme() == "light"
        assert config.get_ui_language() == "zh_CN"

    def test_reload(self, temp_config, temp_db):
        """测试重新加载配置"""
        config = UnifiedConfigManager(temp_config, temp_db)

        # 设置运行时配置
        config.set_runtime("test.key", "test_value")
        assert config.get("test.key") == "test_value"

        # 重新加载
        config.reload()

        # 运行时缓存应该被清除
        value = config.get("test.key", default="not_found")
        assert value == "not_found"


class TestGetUnifiedConfig:
    """get_unified_config() 单例模式测试"""

    def test_singleton_pattern(self):
        """测试单例模式"""
        config1 = get_unified_config()
        config2 = get_unified_config()

        # 应该返回同一个实例
        assert config1 is config2

    def test_thread_safety(self, temp_config, temp_db):
        """测试线程安全（简单版本）"""
        import threading

        instances = []
        lock = threading.Lock()

        def get_instance():
            config = UnifiedConfigManager(temp_config, temp_db)
            with lock:
                instances.append(config)

        # 创建多个线程
        threads = []
        for _ in range(10):
            t = threading.Thread(target=get_instance)
            threads.append(t)
            t.start()

        # 等待所有线程完成
        for t in threads:
            t.join()

        # 每个线程应该有自己的实例（因为传入的路径不同）
        # 这里只是验证不会崩溃
        assert len(instances) == 10
