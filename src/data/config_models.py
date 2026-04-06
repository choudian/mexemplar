"""
配置数据模型定义

本文件只包含配置数据结构定义（dataclass），不提供配置访问功能。

⚠️ 重要提示：
- 配置数据类：在这里定义（用于类型提示和数据结构）
- 配置访问：请使用 `src.data.unified_config.get_unified_config()`

正确的配置访问方式：
```python
from src.data.unified_config import get_unified_config

config = get_unified_config()
model = config.get('ai.model')
```

❌ 错误的方式：
```python
from src.data.config_models import AIConfig
config = AIConfig()  # 不要这样做！
```
"""

import json
import logging
import dataclasses
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


def _filter_dataclass_fields(data: Dict[str, Any], dataclass_type: type) -> Dict[str, Any]:
    """
    过滤字典，只保留 dataclass 定义的字段

    Args:
        data: 原始字典数据
        dataclass_type: 目标 dataclass 类型

    Returns:
        只包含 dataclass 定义字段的字典

    Example:
        >>> data = {"name": "test", "extra": "value", "_comment": "注释"}
        >>> _filter_dataclass_fields(data, AIConfig)
        {"name": "test"}
    """
    fields = {f.name for f in dataclasses.fields(dataclass_type)}
    return {k: v for k, v in data.items() if k in fields}


@dataclass
class DatabaseConfig:
    """数据库配置"""

    db_path: Optional[str] = None
    auto_init: bool = True


@dataclass
class AIConfig:
    """AI配置"""

    provider: str = "anthropic"  # anthropic, openai等
    api_key: Optional[str] = None
    model: str = "claude-sonnet-4-20250514"  # Claude Sonnet 4.5
    vision_model: str = "claude-3-5-sonnet-20241022"  # 多模态视觉模型名称
    vision_provider: Optional[str] = None  # 视觉模型提供商（为空则跟随主模型 provider）
    vision_api_key: Optional[str] = None  # 视觉模型专用 API key（为空则跟随主模型）
    vision_base_url: Optional[str] = None  # 视觉模型专用 endpoint（为空则跟随主模型）
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 60
    base_url: Optional[str] = None  # 自定义 API endpoint（用于代理或兼容 API）

    # 数据压缩模型配置（用于网络请求智能过滤）
    compression_model_enabled: bool = False  # 是否启用数据压缩模型
    compression_model_provider: str = "anthropic"  # 压缩模型提供商
    compression_model_name: str = "claude-3-5-haiku-20241022"  # 压缩模型名称
    compression_model_api_key: Optional[str] = None  # 压缩模型专用 API key（可选）
    compression_model_base_url: Optional[str] = None  # 自定义 API endpoint（用于代理或兼容 API）
    compression_model_temperature: float = 0.5  # 压缩模型温度（较低以获得更确定的输出）
    compression_model_max_tokens: int = 1024  # 压缩模型最大 tokens（轻量级任务）
    compression_model_threads: int = 1  # 压缩模型线程数（1=单线程，>1=多线程并发）

    # 记忆机制配置
    memory_reference_steps_threshold: int = 3  # tool result 被引用替换前需要的 assistant 消息数
    memory_reference_size_threshold: int = 2000  # 触发引用替换的最小字符数
    memory_compression_token_threshold: int = 80000  # token 估算触发压缩的阈值
    memory_compression_count_threshold: Optional[int] = None  # 消息条数触发压缩的阈值（可选）
    memory_compression_keep_recent: int = 20  # 压缩时保留的最近消息数
    memory_compression_trigger_strategy: str = "token"  # 压缩触发策略："token" | "count" | "combined"


@dataclass
class WebSocketConfig:
    """WebSocket 配置"""

    enabled: bool = True  # 是否启用 WebSocket
    host: str = "127.0.0.1"  # 监听地址
    port: int = 8765  # 监听端口
    ping_interval: float = 30.0  # 心跳间隔（秒）
    max_reconnect_attempts: int = 10  # 最大重连次数
    reconnect_delay: float = 1.0  # 初始重连延迟（秒）
    message_queue_size: int = 1000  # 离线消息队列大小


@dataclass
class RecordingConfig:
    """录制配置"""

    screenshot_quality: int = 85  # 截图质量 (1-100)
    # 视频录制配置
    enable_video_recording: bool = True  # 是否启用视频录制
    video_fps: int = 15  # 视频帧率
    video_quality: int = 85  # 视频质量 (1-100)
    # 截图配置
    screenshot_delay_after_action: float = 0.2  # 操作后截图延迟（秒）
    record_mouse_move: bool = False  # 是否记录鼠标移动事件
    # 浏览器录制配置
    default_recording_mode: str = "desktop"  # 默认录制模式（'browser' 或 'desktop'）
    browser_type: str = "chromium"  # 浏览器类型（'chromium', 'firefox', 'webkit'）
    browser_headless: bool = False  # 是否无头模式
    browser_start_url: Optional[str] = None  # 浏览器启动URL
    capture_network_requests: bool = True  # 是否捕获网络请求（浏览器模式）
    network_request_filter: str = "xhr_fetch"  # 网络请求过滤类型（'all', 'xhr_fetch', 'api_only'）
    network_request_timeout: float = 5.0  # 关联操作和请求的时间窗口（秒）
    debug_log_enabled: bool = False  # 是否启用调试日志（写入 .cursor/debug.log）
    # WebSocket 配置
    websocket: WebSocketConfig = field(default_factory=WebSocketConfig)
    # 用户数据目录配置
    persistent_user_data: bool = True  # 是否使用持久化用户数据目录（保留登录状态，默认启用）
    user_data_dir: Optional[str] = None  # 自定义用户数据目录路径（如果为 None，使用默认路径）


@dataclass
class UIConfig:
    """UI配置"""

    theme: str = "light"  # light, dark
    language: str = "zh_CN"  # zh_CN, en_US
    window_width: int = 1200
    window_height: int = 800


@dataclass
class AppConfig:
    """应用配置"""

    app_name: str = "Mexemplar"
    version: str = "0.1.0"
    debug: bool = False
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（不包含敏感信息）"""
        data = asdict(self)
        # 不序列化API密钥
        if "api_key" in data.get("ai", {}):
            data["ai"]["api_key"] = None
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        """从字典创建配置对象"""
        config = cls()

        if "database" in data:
            config.database = DatabaseConfig(**_filter_dataclass_fields(data["database"], DatabaseConfig))

        if "ai" in data:
            config.ai = AIConfig(**_filter_dataclass_fields(data["ai"], AIConfig))

        if "recording" in data:
            recording_data = _filter_dataclass_fields(data["recording"], RecordingConfig)
            # 如果配置中没有 debug_log_enabled，默认使用 False
            if "debug_log_enabled" not in recording_data:
                recording_data["debug_log_enabled"] = False
            config.recording = RecordingConfig(**recording_data)

        if "ui" in data:
            config.ui = UIConfig(**_filter_dataclass_fields(data["ui"], UIConfig))

        if "app_name" in data:
            config.app_name = data["app_name"]
        if "version" in data:
            config.version = data["version"]
        if "debug" in data:
            config.debug = data["debug"]

        return config


# ============================================================================
# 内部配置文件加载器（仅供 UnifiedConfigManager 内部使用）
# 公共 API 请使用 src.data.unified_config.get_unified_config()
# ============================================================================


class ConfigFileLoader:
    """
    配置文件加载器（内部使用）

    仅用于 UnifiedConfigManager 内部加载和保存配置文件
    公共 API 请使用 src.data.unified_config.get_unified_config()
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置文件加载器

        Args:
            config_path: 配置文件路径
        """
        if config_path is None:
            # 使用默认路径：data/config.json
            project_root = Path(__file__).parent.parent.parent
            config_dir = project_root / "data" / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = str(config_dir / "config.json")

        self.config_path = Path(config_path)

    def load(self) -> AppConfig:
        """
        加载配置文件

        Returns:
            AppConfig 配置对象
        """
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    config = AppConfig.from_dict(data)
                    logger.info(f"[配置文件] 已加载: {self.config_path}")
                    return config
            except Exception as e:
                logger.error(f"[配置文件] 加载失败: {e}")
                return AppConfig()
        else:
            logger.info("[配置文件] 不存在，使用默认配置")
            return AppConfig()

    def save(self, config: AppConfig):
        """
        保存配置文件

        Args:
            config: 配置对象
        """
        try:
            # 确保目录存在
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # 保存配置（不包含敏感信息）
            config_dict = config.to_dict()
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config_dict, f, indent=2, ensure_ascii=False)

            logger.info(f"[配置文件] 已保存: {self.config_path}")
        except Exception as e:
            logger.error(f"[配置文件] 保存失败: {e}")
            raise
