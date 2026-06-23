"""
统一配置管理模块

实现三层配置优先级：
1. 数据库配置（最高优先级，用户自定义）
2. 配置文件（默认值）
3. 代码默认值（fallback）

【架构约束】所有配置和 API Key 必须通过本模块管理。
不要硬编码配置，不要直接读取 config.json 文件。
详见 CLAUDE.md 核心约束 #4、#5
"""

import logging
import threading
from typing import Optional, Dict, Any, Callable, List
import dataclasses

from src.utils.helpers import normalize_thinking_level
from src.data.config_models import (
    AppConfig,
    AgentToolsDiscoveryConfig,
    AgentToolsFileConfig,
    AgentToolsOutputConfig,
    AgentToolsOutputSemanticSummaryConfig,
    AgentToolsProcessConfig,
    AgentToolsSearchConfig,
    ConfigFileLoader,
    LargeFieldConfig,
    RecordingDesktopConfig,
    RecordingNoiseFilterConfig,
    WebConfig,
)
from src.data.sqlalchemy_manager import SQLAlchemyManager, get_sqlalchemy_manager

logger = logging.getLogger(__name__)

SENSITIVE_CONFIG_KEYS = frozenset(
    {
        "ai.api_key",
        "ai.vision_api_key",
        "ai.embedding_api_key",
        "ai.compression_model_api_key",
        "web.brave_api_key",
        "agent_tools.output.semantic_summary.api_key",
    }
)


def _log_value(key: str, value: Any) -> Any:
    return "<redacted>" if key in SENSITIVE_CONFIG_KEYS and value else value


@dataclasses.dataclass
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
                logger.debug(
                    "[配置] 从缓存读取: %s = %s",
                    key,
                    _log_value(key, self._runtime_cache[key]),
                )
                return self._runtime_cache[key]

        # 2. 检查数据库配置
        db_value = self._sa.get_setting(key)
        if db_value is not None:
            with self._cache_lock:
                self._runtime_cache[key] = db_value
            logger.debug("[配置] 从数据库读取: %s = %s", key, _log_value(key, db_value))
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
            logger.info("[配置] 已缓存: %s = %s", key, _log_value(key, value))
        elif persist == "database":
            # 保存到数据库
            self._sa.set_setting(key, value, value_type)
            # 同时更新缓存
            with self._cache_lock:
                self._runtime_cache[key] = value
            logger.info("[配置] 已保存到数据库: %s = %s", key, _log_value(key, value))
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
        return self._get_secret("ai.vision_api_key") or self.get_ai_api_key()

    def get_ai_vision_base_url(self) -> Optional[str]:
        """获取视觉模型 endpoint（为空则返回 None，由 LangChain 根据 provider 自动选择默认 endpoint）"""
        return self.get("ai.vision_base_url", default=None)

    def get_ai_provider(self) -> str:
        """获取 AI 提供商"""
        return self.get("ai.provider", default="anthropic")

    def get_ai_api_key(self) -> Optional[str]:
        """从统一配置读取主模型 API 密钥。"""
        return self._get_secret("ai.api_key")

    def set_ai_api_key(self, api_key: str) -> None:
        """写入统一配置中的主模型 API 密钥。"""
        self._set_secret("ai.api_key", api_key)

    def clear_ai_api_key(self) -> None:
        """清除统一配置中的主模型 API 密钥。"""
        self._clear_secret("ai.api_key")

    def get_tool_output_summary_api_key(self) -> Optional[str]:
        """从统一配置读取工具输出摘要 API 密钥。"""
        return self._get_secret("agent_tools.output.semantic_summary.api_key")

    def set_tool_output_summary_api_key(self, api_key: str) -> None:
        """写入统一配置中的工具输出摘要 API 密钥。"""
        self._set_secret("agent_tools.output.semantic_summary.api_key", api_key)

    def clear_tool_output_summary_api_key(self) -> None:
        """清除统一配置中的工具输出摘要 API 密钥。"""
        self._clear_secret("agent_tools.output.semantic_summary.api_key")

    def get_ai_base_url(self) -> Optional[str]:
        """获取主 LLM 自定义 endpoint（用于代理）"""
        return self.get("ai.base_url", default=None)

    def get_ai_thinking_level(self) -> str:
        """主对话推理强度：off | low | medium | high。非法值回退到 off。"""
        raw = self.get("ai.thinking_level", default="off")
        return normalize_thinking_level(raw)

    def get_ai_request_timeout(self) -> float:
        """LLM HTTP 请求超时（秒，>0）。非法值回退到 180.0。

        对应 UI 设置页的 ai.timeout 字段。推理模型（reasoning_effort=high）
        + 长上下文场景下，上游响应可能数十秒，建议 ≥120s。
        """
        raw = self.get("ai.timeout", default=180.0)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            logger.warning(f"[配置] ai.timeout 非法值 {raw!r}，回退到 180.0")
            return 180.0
        if value <= 0:
            logger.warning(f"[配置] ai.timeout 必须为正 {value}，回退到 180.0")
            return 180.0
        return value

    def get_ai_retry_max_retries(self) -> int:
        """LLM 调用最大重试次数（>=0）。非法值回退到 3。"""
        raw = self.get("ai.retry_max_retries", default=3)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            logger.warning(f"[配置] ai.retry_max_retries 非法值 {raw!r}，回退到 3")
            return 3
        if value < 0:
            logger.warning(f"[配置] ai.retry_max_retries 不能为负 {value}，回退到 3")
            return 3
        return value

    def get_ai_retry_delay(self) -> float:
        """LLM 调用重试退避基数（秒，>=0）。非法值回退到 1.0。"""
        raw = self.get("ai.retry_delay", default=1.0)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            logger.warning(f"[配置] ai.retry_delay 非法值 {raw!r}，回退到 1.0")
            return 1.0
        if value < 0:
            logger.warning(f"[配置] ai.retry_delay 不能为负 {value}，回退到 1.0")
            return 1.0
        return value

    def get_ai_max_tokens(self) -> int:
        """LLM 单次回复最大 output tokens。非法值回退到 32000。"""
        raw = self.get("ai.max_tokens", default=32000)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            logger.warning(f"[配置] ai.max_tokens 非法值 {raw!r}，回退到 32000")
            return 32000
        if value <= 0:
            logger.warning(f"[配置] ai.max_tokens 必须为正 {value}，回退到 32000")
            return 32000
        return value

    def get_embedding_api_key(self) -> Optional[str]:
        """获取 embedding 服务 API 密钥（用于向量搜索）"""
        return self._get_secret("ai.embedding_api_key")

    # ===== 便捷方法：Web 工具配置 =====

    def get_web_search_backend(self) -> str:
        """获取 web_search provider backend。"""
        raw = self.get("web.search_backend", default=WebConfig().search_backend)
        value = str(raw or "auto").strip().lower()
        return value or "auto"

    def get_web_brave_api_key(self) -> Optional[str]:
        """从统一配置读取 Brave Search API Key。"""
        return self._get_secret("web.brave_api_key")

    def set_web_brave_api_key(self, api_key: str) -> None:
        """写入统一配置中的 Brave Search API Key。"""
        self._set_secret("web.brave_api_key", api_key)

    def clear_web_brave_api_key(self) -> None:
        """清除统一配置中的 Brave Search API Key。"""
        self._clear_secret("web.brave_api_key")

    # ===== 便捷方法：会话压缩调用配置 =====

    def get_compression_model_provider(self) -> str:
        """获取会话压缩使用的模型提供商（跟随主对话模型）"""
        return self.get_ai_provider()

    def get_compression_model_name(self) -> str:
        """获取会话压缩使用的模型名称（跟随主对话模型）"""
        return self.get_ai_model()

    def get_compression_model_api_key(
        self,
    ) -> Optional[str]:
        return self.get_ai_api_key()

    def get_compression_model_base_url(self) -> Optional[str]:
        """获取会话压缩使用的 endpoint（跟随主对话模型）"""
        return self.get_ai_base_url()

    def get_compression_model_temperature(self) -> float:
        """获取会话压缩调用温度"""
        return self.get("ai.compression_model_temperature", default=0.5)

    def get_compression_model_max_tokens(self) -> int:
        """获取会话压缩调用最大 tokens"""
        return self.get("ai.compression_model_max_tokens", default=1024)

    # ===== 便捷方法：记忆机制配置 =====

    def get_memory_reference_steps_threshold(self) -> int:
        """tool result 被引用替换前需要的 assistant 消息数"""
        return self.get("memory.reference_steps_threshold", default=3)

    def get_memory_reference_size_threshold(self) -> int:
        """触发引用替换的最小字符数"""
        return self.get("memory.reference_size_threshold", default=10000)

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

    # ===== 便捷方法：Agent 内建工具配置 =====

    def _get_bounded_positive_int(
        self,
        key: str,
        default: int,
        *,
        maximum: int | None = None,
        minimum: int = 1,
    ) -> int:
        raw = self.get(key, default=default)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            logger.warning("[配置] %s 非法值 %r，回退到 %d", key, raw, default)
            return default
        if value < minimum:
            logger.warning("[配置] %s 必须 >= %d，回退到 %d", key, minimum, default)
            return default
        if maximum is not None and value > maximum:
            logger.warning("[配置] %s 超过最大值 %d，截断", key, maximum)
            return maximum
        return value

    def get_agent_tools_file_config(self) -> AgentToolsFileConfig:
        return self._load_dataclass_config("agent_tools.file", AgentToolsFileConfig)

    def get_agent_tools_output_config(self) -> AgentToolsOutputConfig:
        output = self._load_dataclass_config("agent_tools.output", AgentToolsOutputConfig)
        output.semantic_summary = self.get_agent_tools_output_semantic_summary_config()
        return output

    def get_agent_tools_output_semantic_summary_config(
        self,
    ) -> AgentToolsOutputSemanticSummaryConfig:
        return self._load_dataclass_config(
            "agent_tools.output.semantic_summary",
            AgentToolsOutputSemanticSummaryConfig,
        )

    def get_agent_tools_search_config(self) -> AgentToolsSearchConfig:
        return self._load_dataclass_config("agent_tools.search", AgentToolsSearchConfig)

    def get_agent_tools_process_config(self) -> AgentToolsProcessConfig:
        return self._load_dataclass_config("agent_tools.process", AgentToolsProcessConfig)

    def get_agent_tools_discovery_config(self) -> AgentToolsDiscoveryConfig:
        return AgentToolsDiscoveryConfig(
            full_catalog_max_items=self.get_agent_tools_discovery_full_catalog_max_items(),
            full_catalog_max_chars=self.get_agent_tools_discovery_full_catalog_max_chars(),
            search_default_limit=self.get_agent_tools_discovery_search_default_limit(),
            search_max_limit=self.get_agent_tools_discovery_search_max_limit(),
            result_description_max_chars=(
                self.get_agent_tools_discovery_result_description_max_chars()
            ),
        )

    def get_agent_tools_discovery_full_catalog_max_items(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.discovery.full_catalog_max_items",
            20,
            maximum=1000,
        )

    def get_agent_tools_discovery_full_catalog_max_chars(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.discovery.full_catalog_max_chars",
            6000,
            minimum=500,
            maximum=100000,
        )

    def get_agent_tools_discovery_search_max_limit(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.discovery.search_max_limit",
            25,
            maximum=100,
        )

    def get_agent_tools_discovery_search_default_limit(self) -> int:
        maximum = self.get_agent_tools_discovery_search_max_limit()
        return self._get_bounded_positive_int(
            "agent_tools.discovery.search_default_limit",
            min(10, maximum),
            maximum=maximum,
        )

    def get_agent_tools_discovery_result_description_max_chars(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.discovery.result_description_max_chars",
            500,
            minimum=50,
            maximum=5000,
        )

    def get_agent_tools_file_default_max_lines(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.file.default_max_lines", 200, maximum=1000
        )

    def get_agent_tools_file_max_window_chars(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.file.max_window_chars", 50000, maximum=250000
        )

    def get_agent_tools_file_max_decode_bytes(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.file.max_decode_bytes", 1048576, maximum=10485760
        )

    def get_agent_tools_output_visible_char_cap(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.output.visible_char_cap", 12000, maximum=50000
        )

    def get_agent_tools_output_raw_reference_threshold_chars(self) -> int:
        visible = self.get_agent_tools_output_visible_char_cap()
        return self._get_bounded_positive_int(
            "agent_tools.output.raw_reference_threshold_chars",
            20000,
            minimum=visible,
        )

    def get_agent_tools_output_max_artifact_bytes(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.output.max_artifact_bytes", 10485760, maximum=104857600
        )

    def get_agent_tools_output_retention_days(self) -> int:
        return self._get_bounded_positive_int("agent_tools.output.retention_days", 14, maximum=90)

    def get_agent_tools_output_semantic_summary_enabled(self) -> bool:
        value = self.get("agent_tools.output.semantic_summary.enabled", default=True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def get_agent_tools_output_semantic_summary_provider(self) -> str:
        return (
            str(
                self.get(
                    "agent_tools.output.semantic_summary.provider",
                    default="anthropic",
                )
                or ""
            )
            .strip()
            .lower()
        )

    def get_agent_tools_output_semantic_summary_model(self) -> str:
        return str(self.get("agent_tools.output.semantic_summary.model", default="") or "").strip()

    def get_agent_tools_output_semantic_summary_base_url(self) -> str:
        return str(
            self.get("agent_tools.output.semantic_summary.base_url", default="") or ""
        ).strip()

    def get_agent_tools_output_semantic_summary_temperature(self) -> float:
        value = self.get("agent_tools.output.semantic_summary.temperature", default=0.2)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 0.2
        return min(2.0, max(0.0, parsed))

    def get_agent_tools_output_semantic_summary_trigger_chars(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.output.semantic_summary.trigger_chars",
            20000,
            minimum=1000,
            maximum=1000000,
        )

    def get_agent_tools_output_semantic_summary_max_input_chars(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.output.semantic_summary.max_input_chars",
            120000,
            minimum=1000,
            maximum=1000000,
        )

    def get_agent_tools_output_semantic_summary_chunk_chars(self) -> int:
        maximum = self.get_agent_tools_output_semantic_summary_max_input_chars()
        return self._get_bounded_positive_int(
            "agent_tools.output.semantic_summary.chunk_chars",
            20000,
            minimum=1000,
            maximum=maximum,
        )

    def get_agent_tools_output_semantic_summary_max_map_chunks(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.output.semantic_summary.max_map_chunks",
            6,
            maximum=20,
        )

    def get_agent_tools_output_semantic_summary_map_concurrency(self) -> int:
        maximum = self.get_agent_tools_output_semantic_summary_max_map_chunks()
        return self._get_bounded_positive_int(
            "agent_tools.output.semantic_summary.map_concurrency",
            3,
            maximum=min(10, maximum),
        )

    def get_agent_tools_output_semantic_summary_total_timeout_seconds(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.output.semantic_summary.total_timeout_seconds",
            12,
            maximum=120,
        )

    def get_agent_tools_output_semantic_summary_map_max_tokens(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.output.semantic_summary.map_max_tokens",
            500,
            minimum=64,
            maximum=4000,
        )

    def get_agent_tools_output_semantic_summary_reduce_max_tokens(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.output.semantic_summary.reduce_max_tokens",
            900,
            minimum=64,
            maximum=8000,
        )

    def get_agent_tools_output_semantic_summary_summary_max_chars(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.output.semantic_summary.summary_max_chars",
            4000,
            minimum=500,
            maximum=20000,
        )

    def get_agent_tools_output_load_max_bytes(self) -> int:
        """Per-call byte ceiling for load_tool_output raw retrieval.

        Bounds how much original output one load_tool_output window can pull into
        context. The result is exempt from governance summarization/compaction, so
        this ceiling (plus offset/maxBytes pagination) is the only size guard.
        """
        return self._get_bounded_positive_int(
            "agent_tools.output.load_max_bytes", 131072, maximum=1_048_576
        )

    def get_agent_tools_max_parallel_workers(self) -> int:
        """Maximum concurrent worker threads for concurrency-safe tool calls."""
        return self._get_bounded_positive_int("agent_tools.max_parallel_workers", 4, maximum=16)

    def get_agent_tools_search_default_page_size(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.search.default_page_size", 100, maximum=500
        )

    def get_agent_tools_search_max_files_scanned(self) -> int:
        return self._get_bounded_positive_int("agent_tools.search.max_files_scanned", 50000)

    def get_agent_tools_search_max_bytes_per_file(self) -> int:
        return self._get_bounded_positive_int("agent_tools.search.max_bytes_per_file", 1048576)

    def get_agent_tools_search_max_elapsed_ms(self) -> int:
        return self._get_bounded_positive_int("agent_tools.search.max_elapsed_ms", 30000)

    def get_agent_tools_process_default_timeout_ms(self) -> int:
        return self._get_bounded_positive_int("agent_tools.process.default_timeout_ms", 30000)

    def get_agent_tools_process_max_timeout_ms(self) -> int:
        default = self.get_agent_tools_process_default_timeout_ms()
        return self._get_bounded_positive_int(
            "agent_tools.process.max_timeout_ms", 600000, minimum=default
        )

    def get_agent_tools_process_log_tail_chars(self) -> int:
        visible = self.get_agent_tools_output_visible_char_cap()
        return self._get_bounded_positive_int(
            "agent_tools.process.log_tail_chars", 4000, maximum=visible
        )

    def get_agent_tools_process_max_background_processes(self) -> int:
        return self._get_bounded_positive_int("agent_tools.process.max_background_processes", 16)

    def get_agent_tools_process_event_buffer_size(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.process.event_buffer_size", 64, maximum=512
        )

    def get_agent_tools_process_stalled_threshold_ms(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.process.stalled_threshold_ms", 10000, maximum=600000
        )

    def get_agent_tools_process_chunk_threshold_chars(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.process.chunk_threshold_chars", 4096, maximum=65536
        )

    # ===== 便捷方法：Assistant Task Collaboration 配置 =====

    def get_assistant_tasks_unified_dispatch_enabled(self) -> bool:
        return bool(self.get("assistant_tasks.unified_dispatch.enabled", default=True))

    def get_assistant_tasks_clean_start_guard_enabled(self) -> bool:
        return bool(self.get("assistant_tasks.cutover.clean_start_guard", default=True))

    def get_assistant_tasks_dispatch_max_workers(self) -> int:
        return self._get_bounded_positive_int(
            "assistant_tasks.dispatch.max_workers",
            4,
            maximum=20,
        )

    def get_assistant_tasks_graph_max_tasks(self) -> int:
        return self._get_bounded_positive_int(
            "assistant_tasks.graph.max_tasks",
            200,
            minimum=2,
            maximum=1000,
        )

    def get_assistant_tasks_board_capacity(self) -> int:
        return self._get_bounded_positive_int(
            "assistant_tasks.board.capacity",
            50,
            maximum=200,
        )

    def get_assistant_tasks_board_fallback_seconds(self) -> int:
        return self._get_bounded_positive_int(
            "assistant_tasks.board.fallback_seconds",
            60,
            maximum=86400,
        )

    def get_assistant_tasks_recruitment_min_fallback_count(self) -> int:
        return self._get_bounded_positive_int(
            "assistant_tasks.recruitment.min_fallback_count",
            3,
            maximum=100,
        )

    def get_assistant_tasks_attempt_lease_seconds(self) -> int:
        return self._get_bounded_positive_int(
            "assistant_tasks.attempt.lease_seconds",
            120,
            minimum=10,
            maximum=3600,
        )

    def get_assistant_tasks_recovery_scan_interval_seconds(self) -> int:
        return self._get_bounded_positive_int(
            "assistant_tasks.recovery.scan_interval_seconds",
            30,
            minimum=5,
            maximum=600,
        )

    def get_assistant_tasks_meeting_turn_budget(self) -> int:
        return self._get_bounded_positive_int(
            "assistant_tasks.meeting.turn_budget",
            12,
            maximum=100,
        )

    def get_assistant_tasks_meeting_time_budget_seconds(self) -> int:
        return self._get_bounded_positive_int(
            "assistant_tasks.meeting.time_budget_seconds",
            900,
            minimum=30,
            maximum=7200,
        )

    def get_assistant_tasks_meeting_mutual_wait_window(self) -> int:
        """最近多少条消息用于判定互等死锁；默认 4（双方各 2 轮等待）。"""
        return self._get_bounded_positive_int(
            "assistant_tasks.meeting.mutual_wait_window",
            4,
            minimum=2,
            maximum=20,
        )

    def get_assistant_tasks_api_default_limit(self) -> int:
        return self._get_bounded_positive_int(
            "assistant_tasks.api.default_limit",
            50,
            maximum=200,
        )

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

    def get_proxy_host(self) -> str:
        """获取录制代理主机"""
        return self.get("recording.proxy.host", default="127.0.0.1")

    def get_proxy_port(self) -> int:
        """获取录制代理端口"""
        return self.get("recording.proxy.port", default=8080)

    def _load_dataclass_config(self, prefix: str, config_cls: type) -> Any:
        """通用 dataclass 配置加载：从 prefix.field_name 读取，回退到类默认值。"""
        defaults = config_cls()
        kwargs = {}
        for f in dataclasses.fields(config_cls):
            val = self.get(f"{prefix}.{f.name}", default=getattr(defaults, f.name))
            if isinstance(val, list):
                val = list(val)
            kwargs[f.name] = val
        return config_cls(**kwargs)

    def get_recording_noise_filter_config(self) -> RecordingNoiseFilterConfig:
        """获取录制噪声过滤配置。"""
        return self._load_dataclass_config("recording.noise_filter", RecordingNoiseFilterConfig)

    def get_recording_large_field_config(self) -> LargeFieldConfig:
        """获取录制数据大字段占位与分段读取配置。"""
        return self._load_dataclass_config("recording.large_field", LargeFieldConfig)

    def get_recording_desktop_config(self) -> RecordingDesktopConfig:
        """获取桌面录制配置。"""
        return self._load_dataclass_config("recording.desktop", RecordingDesktopConfig)

    def get_desktop_enable_clip(self) -> bool:
        """桌面录制是否生成 mp4 clip。"""
        value = self.get("recording.desktop.enable_clip", default=True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def get_desktop_vision_model(self) -> Optional[str]:
        """桌面录制 vision 模型；未单独配置时不启用桌面视觉工具。"""
        value = self.get("recording.desktop.vision_model", default=None)
        if value is not None:
            text = str(value).strip()
            if text and text.lower() not in {"none", "null"}:
                return text
        return None

    # ===== 便捷方法：大脑架构配置 =====

    def get_brain_segment_idle_threshold(self) -> int:
        """Segment 空闲防抖阈值（秒）"""
        return self.get("brain.segment.idle_threshold_seconds", default=300)

    def get_brain_segment_max_distillation_retries(self) -> int:
        """沉淀最大重试次数"""
        return self.get("brain.segment.max_distillation_retries", default=3)

    def get_brain_worker_tick_interval(self) -> int:
        """Background worker 周期扫描间隔（秒）"""
        return self.get("brain.worker.tick_interval_seconds", default=300)

    def get_brain_worker_prediction_verification_retries(self) -> int:
        """猜测验证最大重试次数"""
        return self.get("brain.worker.prediction_verification_retries", default=3)

    def get_brain_injection_persistent_top_n(self) -> int:
        """持久区注入 top-N 条目"""
        return self.get("brain.injection.persistent_top_n", default=50)

    def get_brain_injection_hot_zone_top_n(self) -> int:
        """热区注入 top-N 条目"""
        return self.get("brain.injection.hot_zone_top_n", default=20)

    def get_brain_injection_subconscious_top_n(self) -> int:
        """潜意识区注入 top-N 条目"""
        return self.get("brain.injection.subconscious_top_n", default=10)

    def get_brain_decay_fading_threshold(self) -> float:
        """relevance_score 低于此值转为 fading"""
        return self.get("brain.decay.fading_threshold", default=0.3)

    def get_brain_recruitment_min_delegation_count(self) -> int:
        """触发自动招募的最小委托次数"""
        return self.get("brain.recruitment.min_delegation_count", default=5)

    def _get_positive_int(self, key: str, default: int) -> int:
        raw = self.get(key, default=default)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            logger.warning("[配置] %s 非法，回退到 %d", key, default)
            return default
        return value if value > 0 else default

    def get_brain_skill_token_budget_warn_threshold(self) -> int:
        """方法论装备清单 token 计量警示阈值。"""
        return self._get_positive_int("brain.skill.token_budget.warn_threshold", 4096)

    def get_brain_skill_token_budget_danger_threshold(self) -> int:
        """方法论装备清单 token 计量危险阈值。"""
        return self._get_positive_int("brain.skill.token_budget.danger_threshold", 8192)

    def get_brain_skill_seed_file_path(self) -> str:
        """内置'如何创建方法论' seed 文件路径。"""
        value = self.get(
            "brain.skill.seed_file_path",
            default="src/business/brain/seed/how_to_create_skill_methodology.md",
        )
        text = str(value or "").strip()
        return text or "src/business/brain/seed/how_to_create_skill_methodology.md"

    # ===== 便捷方法：debug trace 配置 =====

    def get_debug_trace_enabled(self) -> bool:
        """debug trace 是否启用（默认关闭，仅由 authenticated control facade 通过 runtime 设置）"""
        with self._cache_lock:
            return self._runtime_cache.get("debug.trace.enabled") is True

    def get_debug_trace_max_records(self) -> int:
        """进程内 trace 最大记录数（正整数，默认 200）"""
        val = self.get("debug.trace.max_records", 200)
        try:
            v = int(val)
            return v if v > 0 else 200
        except (ValueError, TypeError):
            return 200

    def get_debug_trace_max_record_bytes(self) -> int:
        """单条 trace 最大字节数（正整数，默认 1 MiB）"""
        val = self.get("debug.trace.max_record_bytes", 1048576)
        try:
            v = int(val)
            return v if v > 0 else 1048576
        except (ValueError, TypeError):
            return 1048576

    def get_debug_trace_max_total_bytes(self) -> int:
        """trace 合计最大字节数（正整数，默认 16 MiB）"""
        val = self.get("debug.trace.max_total_bytes", 16777216)
        try:
            v = int(val)
            return v if v > 0 else 16777216
        except (ValueError, TypeError):
            return 16777216

    def get_debug_reference_max_response_bytes(self) -> int:
        """单次 reference expansion 最大响应字节数（正整数，默认 1 MiB）"""
        val = self.get("debug.reference.max_response_bytes", 1048576)
        try:
            v = int(val)
            return v if v > 0 else 1048576
        except (ValueError, TypeError):
            return 1048576

    # ===== 内部方法 =====

    def _get_secret(self, key: str) -> Optional[str]:
        value = self.get(key, default=None)
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    def _set_secret(self, key: str, value: str) -> None:
        normalized = value.strip()
        if not normalized:
            raise ValueError("密钥不能为空。")
        self.set(key, normalized)

    def _clear_secret(self, key: str) -> None:
        self.set(key, "")

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
