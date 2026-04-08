"""
统一配置管理模块

实现三层配置优先级：
1. 数据库配置（最高优先级，用户自定义）
2. 配置文件（默认值）
3. 代码默认值（fallback）

【架构约束】所有配置必须通过本模块管理，敏感信息（API Key等）使用 keyring 存储。
不要硬编码配置，不要直接读取 config.json 文件。
详见 CLAUDE.md 核心约束 #4、#5
"""

import logging
import threading
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass

from src.data.config_models import AppConfig, ConfigFileLoader
from src.data.sqlalchemy_manager import SQLAlchemyManager, get_sqlalchemy_manager

logger = logging.getLogger(__name__)


@dataclass
class UnifiedConfigManager:
    """
    统一配置管理器

    配置优先级：
    1. 数据库配置（用户自定义，运行时修改）
    2. 配置文件（默认值）
    3. 代码默认值（fallback）
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化统一配置管理器

        Args:
            config_path: 配置文件路径
        """
        # 1. 加载配置文件（默认值）
        self.file_loader = ConfigFileLoader(config_path)
        self.file_config: AppConfig = self.file_loader.load()

        # 2. 初始化数据库（固定默认路径）
        self._sa: SQLAlchemyManager = get_sqlalchemy_manager()
        self._sa.initialize()

        # 缓存运行时配置
        self._runtime_cache: Dict[str, Any] = {}
        self._cache_lock = threading.RLock()

        # ⭐ 配置变化观察者列表
        self._observers: List[Callable[[str, Any, Any], None]] = []
        self._observer_lock = threading.Lock()

    # ===== 配置读取（核心方法）=====

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值（三层优先级）

        Args:
            key: 配置键，支持点分隔的路径（如 'ai.model', 'recording.browser_type'）
            default: 默认值（最低优先级）

        Returns:
            配置值

        优先级：
            1. 运行时缓存（_runtime_cache）
            2. 数据库配置（app_settings 表）
            3. 配置文件（config.json）
            4. 默认值
        """
        # 1. 检查运行时缓存
        with self._cache_lock:
            if key in self._runtime_cache:
                logger.debug(f"[配置] 从缓存读取: {key} = {self._runtime_cache[key]}")
                return self._runtime_cache[key]

        # 2. 检查数据库配置
        db_value = self._sa.get_setting(key)
        if db_value is not None:
            with self._cache_lock:
                self._runtime_cache[key] = db_value
            logger.debug(f"[配置] 从数据库读取: {key} = {db_value}")
            return db_value

        # 3. 从配置文件读取（支持点分隔路径）
        file_value = self._get_from_file_config(key)
        if file_value is not None:
            with self._cache_lock:
                self._runtime_cache[key] = file_value
            return file_value

        # 4. 返回默认值
        return default

    def set(self, key: str, value: Any, persist: str = "database", value_type: str = "string"):
        """
        设置配置值

        Args:
            key: 配置键
            value: 配置值
            persist: 存储位置
                - 'database': 保存到数据库（运行时修改，立即生效）
                - 'runtime': 仅缓存（重启后失效）
            value_type: 值类型（用于数据库存储）
        """
        # ⭐ 保存旧值（用于通知观察者）
        with self._cache_lock:
            old_value = self._runtime_cache.get(key)

        if persist == "runtime":
            # 仅缓存
            with self._cache_lock:
                self._runtime_cache[key] = value
            logger.info(f"[配置] 已缓存: {key} = {value}")
        elif persist == "database":
            # 保存到数据库
            self._sa.set_setting(key, value, value_type)
            # 同时更新缓存
            with self._cache_lock:
                self._runtime_cache[key] = value
            logger.info(f"[配置] 已保存到数据库: {key} = {value}")
        else:
            raise ValueError(f"未知的 persist 类型: {persist!r}，可选 'database' 或 'runtime'")

        # ⭐ 触发观察者（如果值发生变化）
        if old_value != value:
            self._notify_observers(key, old_value, value)

    # ===== 便捷方法：AI 配置 =====

    def get_ai_model(self) -> str:
        """获取 AI 模型"""
        return self.get("ai.model", default="claude-sonnet-4-20250514")

    def get_ai_vision_model(self) -> str:
        """获取 AI Vision 模型"""
        return self.get("ai.vision_model", default="claude-3-5-sonnet-20241022")

    def get_ai_vision_provider(self) -> str:
        """获取视觉模型提供商（为空则跟随主模型 provider）"""
        return self.get("ai.vision_provider", default=None) or self.get_ai_provider()

    def get_ai_vision_api_key(self) -> Optional[str]:
        """获取视觉模型 API key（为空则跟随主模型）"""
        return self.get("ai.vision_api_key", default=None) or self.get_ai_api_key()

    def get_ai_vision_base_url(self) -> Optional[str]:
        """获取视觉模型 endpoint（为空则返回 None，由 LangChain 根据 provider 自动选择默认 endpoint）"""
        return self.get("ai.vision_base_url", default=None)

    def get_ai_provider(self) -> str:
        """获取 AI 提供商"""
        return self.get("ai.provider", default="anthropic")

    def get_ai_api_key(self) -> Optional[str]:
        """获取 Anthropic API 密钥（优先 keyring，回退数据库）"""
        # 优先从 keyring 读取
        try:
            import keyring

            api_key = keyring.get_password("Mexemplar", "anthropic_api_key")
            if api_key:
                logger.debug("[配置] 从 keyring 读取 API 密钥")
                return api_key
        except ImportError:
            logger.warning("[配置] keyring 模块未安装，无法读取加密存储的 API 密钥")
        except Exception as e:
            logger.warning(f"[配置] 从 keyring 读取 API 密钥失败: {e}")

        # 回退到数据库（兼容未迁移的旧数据）
        api_key = self.get("ai.api_key", default=None)
        return api_key or None

    def set_ai_api_key(self, api_key: str) -> None:
        """安全写入 API 密钥到 keyring，并清除数据库中的明文副本"""
        try:
            import keyring

            keyring.set_password("Mexemplar", "anthropic_api_key", api_key)
            logger.info("[配置] API 密钥已安全写入 keyring")
        except Exception as e:
            logger.warning(
                "[配置] keyring 写入失败，无法安全存储 API 密钥。"
                "请检查 keyring 模块是否正确安装（pip install keyring）。"
                "API 密钥不会被存储到数据库中以避免明文泄露。"
            )
            raise RuntimeError(
                f"无法安全存储 API 密钥: {e}。" "请确保 keyring 模块已安装且可用。"
            ) from e
        # 成功写入 keyring 后，清除数据库中的明文密钥
        try:
            self.set("ai.api_key", "")
        except Exception as e:
            logger.warning(f"[配置] 清除数据库明文密钥失败: {e}")

    def clear_ai_api_key(self) -> None:
        """清除 API 密钥（keyring + 数据库）"""
        try:
            import keyring

            keyring.delete_password("Mexemplar", "anthropic_api_key")
        except Exception:
            pass
        self.set("ai.api_key", "")

    def get_ai_base_url(self) -> Optional[str]:
        """获取主 LLM 自定义 endpoint（用于代理）"""
        return self.get("ai.base_url", default=None)

    def get_embedding_api_key(self) -> Optional[str]:
        """获取 embedding 服务 API 密钥（用于向量搜索）"""
        # 优先从配置文件获取
        api_key = self.get("ai.embedding_api_key", default=None)
        if api_key:
            return api_key

        # 从 keyring 读取
        try:
            import keyring

            return keyring.get_password("Mexemplar", "openai_api_key")
        except Exception:
            return None

    # ===== 便捷方法：数据压缩模型配置（网络请求智能过滤）=====

    def get_compression_model_provider(self) -> str:
        """获取压缩模型提供商"""
        return self.get("ai.compression_model_provider", default="anthropic")

    def get_compression_model_name(self) -> str:
        """获取压缩模型名称"""
        return self.get("ai.compression_model_name", default="claude-3-5-haiku-20241022")

    def get_compression_model_api_key(
        self,
    ) -> Optional[str]:
        """
        获取压缩模型 API key

        优先级：
        1. 专用的压缩模型 API key
        2. 主 API key（fallback）
        """
        # 先尝试获取专用的压缩模型 API key
        compression_key = self.get("ai.compression_model_api_key", default=None)
        if compression_key:
            return compression_key

        # fallback 到主 API key
        return self.get_ai_api_key()

    def get_compression_model_base_url(self) -> Optional[str]:
        """获取压缩模型自定义 endpoint（用于代理）"""
        return self.get("ai.compression_model_base_url", default=None)

    def get_compression_model_temperature(self) -> float:
        """获取压缩模型温度"""
        return self.get("ai.compression_model_temperature", default=0.5)

    def get_compression_model_max_tokens(self) -> int:
        """获取压缩模型最大 tokens"""
        return self.get("ai.compression_model_max_tokens", default=1024)

    # ===== 便捷方法：记忆机制配置 =====

    def get_memory_reference_steps_threshold(self) -> int:
        """tool result 被引用替换前需要的 assistant 消息数"""
        return self.get("memory.reference_steps_threshold", default=3)

    def get_memory_reference_size_threshold(self) -> int:
        """触发引用替换的最小字符数"""
        return self.get("memory.reference_size_threshold", default=2000)

    def get_memory_compression_token_threshold(self) -> int:
        """token 估算触发压缩的阈值"""
        return self.get("memory.compression_token_threshold", default=80000)

    def get_memory_compression_count_threshold(self) -> Optional[int]:
        """消息条数触发压缩的阈值（可选）"""
        return self.get("memory.compression_count_threshold", default=None)

    def get_memory_compression_keep_recent(self) -> int:
        """压缩时保留的最近消息数"""
        return self.get("memory.compression_keep_recent", default=20)

    def get_memory_compression_trigger_strategy(self) -> str:
        """压缩触发策略："token" | "count" | "combined" """
        return self.get("memory.compression_trigger_strategy", default="token")

    # ===== 便捷方法：录制配置 =====

    def get_websocket_host(self) -> str:
        """获取 WebSocket 主机"""
        return self.get("recording.websocket.host", default="127.0.0.1")

    def get_websocket_port(self) -> int:
        """获取 WebSocket 端口"""
        return self.get("recording.websocket.port", default=8765)

    def get_websocket_max_message_size(self) -> int:
        """获取 WebSocket 最大消息大小（字节）"""
        return self.get(
            "recording.websocket.max_message_size", default=50 * 1024 * 1024
        )  # 默认 50 MB

    def get_websocket_max_response_body_size(
        self,
    ) -> int:
        """获取 WebSocket 最大响应体大小（字节，用于扩展端截断）"""
        return self.get(
            "recording.websocket.max_response_body_size", default=5 * 1024 * 1024
        )  # 默认 5 MB

    def get_debug_log_enabled(self) -> bool:
        """是否启用调试日志"""
        return self.get("recording.debug_log_enabled", default=False)

    # ===== 内部方法 =====

    def _get_from_file_config(self, key: str) -> Any:
        """
        从配置文件读取（支持点分隔路径）

        Args:
            key: 配置键（如 'ai.model'）

        Returns:
            配置值，如果不存在返回 None
        """
        parts = key.split(".")
        value = self.file_config

        try:
            for part in parts:
                if hasattr(value, part):
                    value = getattr(value, part)
                elif isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return None
            return value
        except (AttributeError, KeyError, TypeError):
            return None

    # ===== 观察者模式（配置变化通知）=====

    def register_observer(
        self,
        callback: Callable[[str, Any, Any], None],
        keys: Optional[List[str]] = None,
    ):
        """
        注册配置变化观察者

        Args:
            callback: 回调函数，签名为 callback(key, old_value, new_value)
            keys: 要监听的配置键列表，如果为 None 则监听所有配置

        示例:
            def on_config_change(key, old_value, new_value):
                print(f"配置变化: {key}: {old_value} -> {new_value}")

            config.register_observer(
                on_config_change, keys=['recording.websocket.port']
            )
        """
        with self._observer_lock:
            self._observers.append({"callback": callback, "keys": keys, "id": id(callback)})
            logger.info(f"[配置] 已注册观察者: {callback.__name__} (监听: {keys or '所有配置'})")

    def _notify_observers(self, key: str, old_value: Any, new_value: Any):
        """
        通知所有观察者配置变化

        Args:
            key: 配置键
            old_value: 旧值
            new_value: 新值
        """
        with self._observer_lock:
            for observer in self._observers:
                # 如果观察者指定了要监听的键，检查是否匹配
                if observer["keys"] is None or key in observer["keys"]:
                    try:
                        observer["callback"](key, old_value, new_value)
                    except Exception as e:
                        logger.error(
                            f"[配置] 观察者回调失败 " f"({observer['callback'].__name__}): {e}"
                        )

    def close(self):
        """SQLAlchemyManager 是全局单例，此处不关闭"""


# ===== 全局单例（线程安全）=====

_unified_config_manager: Optional[UnifiedConfigManager] = None
_init_lock = threading.Lock()


def get_unified_config() -> UnifiedConfigManager:
    """
    获取统一配置管理器（单例模式，线程安全）

    使用双重检查锁定（Double-Checked Locking）确保线程安全：
    1. 第一次检查（无锁）：快速路径，避免每次调用都加锁
    2. 加锁：确保只有一个线程能初始化
    3. 第二次检查（有锁）：防止其他线程在等待锁时已经初始化

    Returns:
        UnifiedConfigManager 实例

    示例:
        >>> config = get_unified_config()
        >>> model = config.get_ai_model()
    """
    global _unified_config_manager

    # 第一次检查：快速路径（无锁）
    if _unified_config_manager is not None:
        return _unified_config_manager

    # 加锁并初始化
    with _init_lock:
        # 第二次检查：防止其他线程已经初始化
        if _unified_config_manager is None:
            _unified_config_manager = UnifiedConfigManager()
            logger.info("[配置] 统一配置管理器已初始化（线程安全）")

    return _unified_config_manager

