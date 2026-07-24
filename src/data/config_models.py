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

import copy
import json
import logging
import dataclasses
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field, asdict

from src.utils.helpers import bundled_resource_path, get_default_data_dir, is_frozen

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
class AIConfig:
    """AI配置"""

    provider: str = "anthropic"  # anthropic, openai等
    api_key: Optional[str] = None
    model: str = "claude-sonnet-4-20250514"
    vision_model: str = "claude-3-5-sonnet-20241022"  # 多模态视觉模型名称
    vision_provider: Optional[str] = None  # 视觉模型提供商（为空则跟随主模型 provider）
    vision_api_key: Optional[str] = None  # 视觉模型专用 API key（为空则跟随主模型）
    vision_base_url: Optional[str] = None  # 视觉模型专用 endpoint（为空则跟随主模型）
    embedding_api_key: Optional[str] = None  # 向量检索专用 API key
    temperature: float = 0.7
    max_tokens: int = 32000
    timeout: int = 180
    base_url: Optional[str] = None  # 自定义 API endpoint（用于代理或兼容 API）

    # LLM 调用重试配置（agent_loop 层）
    # 任意异常都会触发重试，指数退避：delay = retry_delay * 2 ** retry_count
    retry_max_retries: int = 3  # 最大重试次数（最终调用次数 = max_retries + 1）
    retry_delay: float = 1.0  # 退避基数（秒）

    # 推理强度（仅作用于主对话；vision / 压缩调用强制 off）
    # 取值：off | low | medium | high
    # - Anthropic：映射到 thinking={"type":"enabled","budget_tokens":N}，启用时 temperature 强制 1
    # - OpenAI 兼容：映射到 reasoning_effort 参数（minimal/low/medium/high）
    # - 不支持思考的模型/provider：静默忽略
    thinking_level: str = "off"

    # 会话压缩调用配置
    compression_model_provider: str = "anthropic"  # 兼容保留；运行时跟随主对话模型 provider
    compression_model_name: str = "claude-3-5-haiku-20241022"  # 兼容保留；运行时跟随主对话模型名称
    compression_model_api_key: Optional[str] = None  # 兼容保留；运行时跟随主对话模型 API key
    compression_model_base_url: Optional[str] = None  # 兼容保留；运行时跟随主对话模型 endpoint
    compression_model_temperature: float = 0.5  # 会话压缩调用温度
    compression_model_max_tokens: int = 1024  # 会话压缩调用最大 tokens

    # 记忆机制配置
    memory_reference_steps_threshold: int = 3  # tool result 被引用替换前需要的 assistant 消息数
    memory_reference_size_threshold: int = 10000  # 触发引用替换的最小字符数
    memory_compression_token_threshold: int = 80000  # token 估算触发压缩的阈值
    memory_compression_count_threshold: Optional[int] = None  # 消息条数触发压缩的阈值（可选）
    memory_compression_keep_recent: int = 20  # 压缩时保留的最近消息数
    memory_compression_trigger_strategy: str = "token"  # token | count | combined
    # 一轮并发工具调用的结果字符总预算：单条已有 12000 上限，4 路并发时
    # 每条都不超限、加起来仍可撑爆一条消息。24000 = 允许两个满额结果并存。
    memory_tool_result_group_budget: int = 24000


@dataclass
class WebSocketConfig:
    """WebSocket 配置"""

    host: str = "127.0.0.1"  # 监听地址
    port: int = 8765  # 监听端口
    max_message_size: int = 50 * 1024 * 1024  # 服务端单条消息上限（字节）
    max_response_body_size: int = 5 * 1024 * 1024  # 扩展端响应体上限（字节）


@dataclass
class ProxyConfig:
    """录制代理配置"""

    host: str = "127.0.0.1"
    port: int = 8080


@dataclass
class LargeFieldConfig:
    """录制数据大字段占位与分段读取配置"""

    threshold_chars: int = 1000  # 占位触发阈值（字符数）
    preview_chars: int = 1000  # 占位预览最大长度（字符数）
    max_chunk_chars: int = 1000  # 单次分段读取 content 最大长度（字符数）


@dataclass
class RecordingDesktopConfig:
    """桌面录制配置"""

    enable_clip: bool = True
    vision_model: Optional[str] = None


@dataclass
class RecordingNoiseFilterConfig:
    """录制噪声过滤配置"""

    enabled: bool = True
    blacklist_domains: list[str] = field(
        default_factory=lambda: [
            "doubleclick",
            "googletagmanager",
            "google-analytics",
            "sentry",
            "hotjar",
            "baidu-tongji",
        ]
    )
    first_party_whitelist: list[str] = field(default_factory=list)
    static_extensions: list[str] = field(
        default_factory=lambda: [
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".webp",
            ".ico",
            ".css",
            ".woff",
            ".woff2",
            ".ttf",
            ".otf",
            ".eot",
        ]
    )
    static_content_type_prefixes: list[str] = field(
        default_factory=lambda: [
            "image/",
            "font/",
            "text/css",
            "application/font-woff",
            "application/octet-stream",
        ]
    )


@dataclass
class RecordingConfig:
    """录制配置"""

    screenshot_quality: int = 85  # 截图质量 (1-100)
    # 截图配置
    screenshot_delay_after_action: float = 0.2  # 操作后截图延迟（秒）
    # 浏览器录制配置
    browser_start_url: Optional[str] = None  # 浏览器启动URL
    # WebSocket 配置
    websocket: WebSocketConfig = field(default_factory=WebSocketConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    noise_filter: RecordingNoiseFilterConfig = field(default_factory=RecordingNoiseFilterConfig)
    large_field: LargeFieldConfig = field(default_factory=LargeFieldConfig)
    desktop: RecordingDesktopConfig = field(default_factory=RecordingDesktopConfig)
    # 用户数据目录配置
    persistent_user_data: bool = True  # 是否使用持久化用户数据目录（保留登录状态，默认启用）
    user_data_dir: Optional[str] = None  # 自定义用户数据目录路径（如果为 None，使用默认路径）


@dataclass
class UIConfig:
    """UI配置"""

    theme: str = "mint"  # mint, indigo, dark, mono（外观基础主题）
    accent: str = ""  # 强调色 hex（如 #14B58C）；空串=用主题默认
    radius: str = "medium"  # sharp, medium, round（圆角档）
    density: str = "comfy"  # comfy, compact
    language: str = "zh_CN"  # zh_CN, en_US
    window_width: int = 1200
    window_height: int = 800


@dataclass
class WebConfig:
    """Web tool configuration."""

    search_backend: str = "auto"
    brave_api_key: Optional[str] = None


@dataclass
class SkillStoreConfig:
    """External skill store configuration."""

    skills_sh_api_key: Optional[str] = None


@dataclass
class BrainSegmentConfig:
    """大脑 Segment 配置"""

    idle_threshold_seconds: int = 300
    max_distillation_retries: int = 3


@dataclass
class BrainWorkerConfig:
    """大脑后台 Worker 配置"""

    tick_interval_seconds: int = 300
    prediction_verification_retries: int = 3


@dataclass
class BrainInjectionConfig:
    """大脑上下文注入配置"""

    persistent_top_n: int = 50
    hot_zone_top_n: int = 20
    subconscious_top_n: int = 10


@dataclass
class BrainDecayConfig:
    """大脑衰减配置"""

    fading_threshold: float = 0.3


@dataclass
class BrainRecruitmentConfig:
    """专员自动招募配置"""

    min_delegation_count: int = 5


@dataclass
class BrainSkillTokenBudgetConfig:
    """方法论装备清单 token 预算阈值。"""

    warn_threshold: int = 4096
    danger_threshold: int = 8192


@dataclass
class BrainSkillConfig:
    """方法论资产配置。"""

    token_budget: BrainSkillTokenBudgetConfig = field(default_factory=BrainSkillTokenBudgetConfig)
    seed_file_path: str = "src/business/brain/seed/how_to_create_skill_methodology.md"


@dataclass
class BrainConfig:
    """大脑配置"""

    segment: BrainSegmentConfig = field(default_factory=BrainSegmentConfig)
    worker: BrainWorkerConfig = field(default_factory=BrainWorkerConfig)
    injection: BrainInjectionConfig = field(default_factory=BrainInjectionConfig)
    decay: BrainDecayConfig = field(default_factory=BrainDecayConfig)
    recruitment: BrainRecruitmentConfig = field(default_factory=BrainRecruitmentConfig)
    skill: BrainSkillConfig = field(default_factory=BrainSkillConfig)


@dataclass
class AssistantTasksUnifiedDispatchConfig:
    enabled: bool = True


@dataclass
class AssistantTasksCutoverConfig:
    clean_start_guard: bool = True


@dataclass
class AssistantTasksDispatchConfig:
    max_workers: int = 4


@dataclass
class AssistantTasksGraphConfig:
    max_tasks: int = 200


@dataclass
class AssistantTasksBoardConfig:
    capacity: int = 50
    fallback_seconds: int = 60


@dataclass
class AssistantTasksRecruitmentConfig:
    min_fallback_count: int = 3


@dataclass
class AssistantTasksAttemptConfig:
    lease_seconds: int = 120


@dataclass
class AssistantTasksRecoveryConfig:
    scan_interval_seconds: int = 30


@dataclass
class AssistantTasksMeetingConfig:
    turn_budget: int = 12
    time_budget_seconds: int = 900
    mutual_wait_window: int = 4


@dataclass
class AssistantTasksApiConfig:
    default_limit: int = 50


@dataclass
class AssistantTasksComplexityConfig:
    step_threshold: int = 3
    domain_threshold: int = 2


@dataclass
class AssistantTasksPlannerConfig:
    specialist_name: str = "planner"


@dataclass
class AssistantTasksConfig:
    """Assistant task collaboration configuration."""

    unified_dispatch: AssistantTasksUnifiedDispatchConfig = field(
        default_factory=AssistantTasksUnifiedDispatchConfig
    )
    cutover: AssistantTasksCutoverConfig = field(default_factory=AssistantTasksCutoverConfig)
    dispatch: AssistantTasksDispatchConfig = field(default_factory=AssistantTasksDispatchConfig)
    graph: AssistantTasksGraphConfig = field(default_factory=AssistantTasksGraphConfig)
    board: AssistantTasksBoardConfig = field(default_factory=AssistantTasksBoardConfig)
    recruitment: AssistantTasksRecruitmentConfig = field(
        default_factory=AssistantTasksRecruitmentConfig
    )
    attempt: AssistantTasksAttemptConfig = field(default_factory=AssistantTasksAttemptConfig)
    recovery: AssistantTasksRecoveryConfig = field(default_factory=AssistantTasksRecoveryConfig)
    meeting: AssistantTasksMeetingConfig = field(default_factory=AssistantTasksMeetingConfig)
    api: AssistantTasksApiConfig = field(default_factory=AssistantTasksApiConfig)
    complexity: AssistantTasksComplexityConfig = field(
        default_factory=AssistantTasksComplexityConfig
    )
    planner: AssistantTasksPlannerConfig = field(default_factory=AssistantTasksPlannerConfig)


@dataclass
class ExternalCodingQuotaProbeConfig:
    enabled: bool = True
    timeout_seconds: int = 12
    low_threshold_percent: int = 80


@dataclass
class ExternalCodingClaudeConfig:
    command: str = "claude"
    effort: str = "max"


@dataclass
class ExternalCodingCodexConfig:
    command: str = "codex"
    reasoning_effort: str = "xhigh"


@dataclass
class ExternalCodingConfig:
    """Owner-bound external coding session defaults."""

    enabled: bool = True
    default_launch_mode: str = "headless"
    preferred_tool: str = "auto"
    artifact_root: str = "data/coding_sessions"
    worktree_root: str = ".worktrees/coding"
    log_tail_chars: int = 8000
    plan_timeout_seconds: int = 1800
    run_timeout_seconds: int = 7200
    autostart_enabled: bool = True
    quota_probe: ExternalCodingQuotaProbeConfig = field(
        default_factory=ExternalCodingQuotaProbeConfig
    )
    claude: ExternalCodingClaudeConfig = field(default_factory=ExternalCodingClaudeConfig)
    codex: ExternalCodingCodexConfig = field(default_factory=ExternalCodingCodexConfig)


@dataclass
class SelfImprovementExecutionReviewModelConfig:
    """可选的执行复盘模型 profile；全部为空时继承主 ai.* profile。"""

    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    thinking_level: Optional[str] = None
    timeout: Optional[float] = None


@dataclass
class SelfImprovementExecutionReviewConfig:
    """自我改进执行复盘配置。"""

    enabled: bool = True
    model: SelfImprovementExecutionReviewModelConfig = field(
        default_factory=SelfImprovementExecutionReviewModelConfig
    )
    max_per_session: int = 3


@dataclass
class SelfImprovementProposalsConfig:
    """自我改进提案配置。"""

    enabled: bool = True
    worktree_retention_max: int = 10
    dedup_cooldown_hours: int = 24


@dataclass
class SelfImprovementConfig:
    """自我改进配置。"""

    max_prompt_supplements_per_day: int = 3
    max_tool_creations_per_day: int = 1
    max_reflections_per_session: int = 5
    convergence_threshold: float = 0.01
    degradation_threshold: float = 0.10
    sandbox_window: int = 20
    rollback_monitor_window: int = 10
    avoidance_top_n: int = 5
    tool_gap_threshold: int = 3
    execution_review: SelfImprovementExecutionReviewConfig = field(
        default_factory=SelfImprovementExecutionReviewConfig
    )
    proposals: SelfImprovementProposalsConfig = field(
        default_factory=SelfImprovementProposalsConfig
    )


@dataclass
class AgentToolsFileConfig:
    """Agent built-in file tool limits."""

    default_max_lines: int = 200
    max_window_chars: int = 50000
    max_decode_bytes: int = 1048576


@dataclass
class AgentToolsOutputSemanticSummaryConfig:
    """Dedicated semantic summary model and bounded execution settings."""

    enabled: bool = True
    provider: str = "anthropic"
    model: str = ""
    base_url: str = ""
    api_key: Optional[str] = None
    temperature: float = 0.2
    trigger_chars: int = 20000
    max_input_chars: int = 120000
    chunk_chars: int = 20000
    max_map_chunks: int = 6
    map_concurrency: int = 3
    total_timeout_seconds: int = 12
    map_max_tokens: int = 500
    reduce_max_tokens: int = 900
    summary_max_chars: int = 4000


@dataclass
class AgentToolsOutputConfig:
    """Agent built-in output governance limits."""

    visible_char_cap: int = 12000
    raw_reference_threshold_chars: int = 20000
    max_artifact_bytes: int = 10485760
    retention_days: int = 14
    load_max_bytes: int = 131072
    semantic_summary: AgentToolsOutputSemanticSummaryConfig = field(
        default_factory=AgentToolsOutputSemanticSummaryConfig
    )


@dataclass
class AgentToolsSearchConfig:
    """Agent built-in search limits."""

    default_page_size: int = 100
    max_files_scanned: int = 50000
    max_bytes_per_file: int = 1048576
    max_elapsed_ms: int = 30000


@dataclass
class AgentToolsProcessConfig:
    """Agent built-in command/process limits."""

    default_timeout_ms: int = 30000
    max_timeout_ms: int = 600000
    log_tail_chars: int = 4000
    max_background_processes: int = 16
    event_buffer_size: int = 64
    stalled_threshold_ms: int = 10000
    chunk_threshold_chars: int = 4096


@dataclass
class AgentToolsDiscoveryConfig:
    """User capability catalog discovery and prompt limits."""

    full_catalog_max_items: int = 20
    full_catalog_max_chars: int = 6000
    search_default_limit: int = 10
    search_max_limit: int = 25
    result_description_max_chars: int = 500


@dataclass
class AgentToolsDelegationConfig:
    """Delegation context handoff limits (032)."""

    context_expansion_max_chars: int = 30000


@dataclass
class AgentToolsConfig:
    """Agent built-in foundational tool configuration."""

    file: AgentToolsFileConfig = field(default_factory=AgentToolsFileConfig)
    output: AgentToolsOutputConfig = field(default_factory=AgentToolsOutputConfig)
    search: AgentToolsSearchConfig = field(default_factory=AgentToolsSearchConfig)
    process: AgentToolsProcessConfig = field(default_factory=AgentToolsProcessConfig)
    discovery: AgentToolsDiscoveryConfig = field(default_factory=AgentToolsDiscoveryConfig)
    delegation: AgentToolsDelegationConfig = field(default_factory=AgentToolsDelegationConfig)
    max_parallel_workers: int = 4


@dataclass
class SchedulerConfig:
    """调度中心配置（033）——扁平键，避免嵌套 dataclass 解析。"""

    scan_interval_seconds: int = 30
    confirmation_timeout_seconds: int = 300


@dataclass
class AppConfig:
    """应用配置"""

    app_name: str = "Mexemplar"
    version: str = "0.1.0"
    ai: AIConfig = field(default_factory=AIConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    web: WebConfig = field(default_factory=WebConfig)
    skill_store: SkillStoreConfig = field(default_factory=SkillStoreConfig)
    brain: BrainConfig = field(default_factory=BrainConfig)
    assistant_tasks: AssistantTasksConfig = field(default_factory=AssistantTasksConfig)
    external_coding: ExternalCodingConfig = field(default_factory=ExternalCodingConfig)
    self_improvement: SelfImprovementConfig = field(default_factory=SelfImprovementConfig)
    agent_tools: AgentToolsConfig = field(default_factory=AgentToolsConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)

    def to_dict(self) -> Dict[str, Any]:
        """转换为可写配置字典（不含密钥等敏感信息）。"""
        from src.data.unified_config import SENSITIVE_CONFIG_KEYS
        from src.data.config_contract import omit_deprecated_paths

        data = asdict(self)
        # 不序列化任何密钥（api_key 等），避免明文写入 config.json。
        for dotted in SENSITIVE_CONFIG_KEYS:
            parts = dotted.split(".")
            node: Any = data
            for key in parts[:-1]:
                if not isinstance(node, dict) or key not in node:
                    node = None
                    break
                node = node[key]
            if isinstance(node, dict) and parts[-1] in node:
                node[parts[-1]] = None
        omit_deprecated_paths(data)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        """从字典创建配置对象"""
        config = cls()
        if "ai" in data:
            config.ai = AIConfig(**_filter_dataclass_fields(data["ai"], AIConfig))

        if "recording" in data:
            recording_data = _filter_dataclass_fields(data["recording"], RecordingConfig)
            for key, sub_cls in (
                ("websocket", WebSocketConfig),
                ("proxy", ProxyConfig),
                ("noise_filter", RecordingNoiseFilterConfig),
                ("large_field", LargeFieldConfig),
                ("desktop", RecordingDesktopConfig),
            ):
                val = recording_data.get(key)
                if isinstance(val, dict):
                    recording_data[key] = sub_cls(**_filter_dataclass_fields(val, sub_cls))
            config.recording = RecordingConfig(**recording_data)

        if "ui" in data:
            config.ui = UIConfig(**_filter_dataclass_fields(data["ui"], UIConfig))

        if "web" in data:
            config.web = WebConfig(**_filter_dataclass_fields(data["web"], WebConfig))

        if "skill_store" in data:
            config.skill_store = SkillStoreConfig(
                **_filter_dataclass_fields(data["skill_store"], SkillStoreConfig)
            )

        if "brain" in data:
            brain_data = _filter_dataclass_fields(data["brain"], BrainConfig)
            for key, sub_cls in (
                ("segment", BrainSegmentConfig),
                ("worker", BrainWorkerConfig),
                ("injection", BrainInjectionConfig),
                ("decay", BrainDecayConfig),
                ("recruitment", BrainRecruitmentConfig),
            ):
                val = brain_data.get(key)
                if isinstance(val, dict):
                    brain_data[key] = sub_cls(**_filter_dataclass_fields(val, sub_cls))
            skill_data = brain_data.get("skill")
            if isinstance(skill_data, dict):
                token_budget = skill_data.get("token_budget")
                if isinstance(token_budget, dict):
                    skill_data["token_budget"] = BrainSkillTokenBudgetConfig(
                        **_filter_dataclass_fields(token_budget, BrainSkillTokenBudgetConfig)
                    )
                brain_data["skill"] = BrainSkillConfig(
                    **_filter_dataclass_fields(skill_data, BrainSkillConfig)
                )
            config.brain = BrainConfig(**brain_data)

        if "assistant_tasks" in data:
            task_data = _filter_dataclass_fields(data["assistant_tasks"], AssistantTasksConfig)
            for key, sub_cls in (
                ("unified_dispatch", AssistantTasksUnifiedDispatchConfig),
                ("cutover", AssistantTasksCutoverConfig),
                ("dispatch", AssistantTasksDispatchConfig),
                ("graph", AssistantTasksGraphConfig),
                ("board", AssistantTasksBoardConfig),
                ("recruitment", AssistantTasksRecruitmentConfig),
                ("attempt", AssistantTasksAttemptConfig),
                ("recovery", AssistantTasksRecoveryConfig),
                ("meeting", AssistantTasksMeetingConfig),
                ("api", AssistantTasksApiConfig),
                ("complexity", AssistantTasksComplexityConfig),
                ("planner", AssistantTasksPlannerConfig),
            ):
                value = task_data.get(key)
                if isinstance(value, dict):
                    task_data[key] = sub_cls(**_filter_dataclass_fields(value, sub_cls))
            config.assistant_tasks = AssistantTasksConfig(**task_data)

        if "external_coding" in data:
            external_data = _filter_dataclass_fields(data["external_coding"], ExternalCodingConfig)
            for key, sub_cls in (
                ("quota_probe", ExternalCodingQuotaProbeConfig),
                ("claude", ExternalCodingClaudeConfig),
                ("codex", ExternalCodingCodexConfig),
            ):
                value = external_data.get(key)
                if isinstance(value, dict):
                    external_data[key] = sub_cls(**_filter_dataclass_fields(value, sub_cls))
            config.external_coding = ExternalCodingConfig(**external_data)

        if "scheduler" in data:
            config.scheduler = SchedulerConfig(
                **_filter_dataclass_fields(data["scheduler"], SchedulerConfig)
            )

        if "self_improvement" in data:
            si_data = _filter_dataclass_fields(data["self_improvement"], SelfImprovementConfig)
            execution_review = si_data.get("execution_review")
            if isinstance(execution_review, dict):
                execution_review_data = _filter_dataclass_fields(
                    execution_review,
                    SelfImprovementExecutionReviewConfig,
                )
                model_data = execution_review_data.get("model")
                if isinstance(model_data, dict):
                    execution_review_data["model"] = SelfImprovementExecutionReviewModelConfig(
                        **_filter_dataclass_fields(
                            model_data,
                            SelfImprovementExecutionReviewModelConfig,
                        )
                    )
                si_data["execution_review"] = SelfImprovementExecutionReviewConfig(
                    **execution_review_data
                )
            proposals = si_data.get("proposals")
            if isinstance(proposals, dict):
                si_data["proposals"] = SelfImprovementProposalsConfig(
                    **_filter_dataclass_fields(proposals, SelfImprovementProposalsConfig)
                )
            config.self_improvement = SelfImprovementConfig(**si_data)

        if "agent_tools" in data:
            agent_tools_data = _filter_dataclass_fields(data["agent_tools"], AgentToolsConfig)
            for key, sub_cls in (
                ("file", AgentToolsFileConfig),
                ("search", AgentToolsSearchConfig),
                ("process", AgentToolsProcessConfig),
                ("discovery", AgentToolsDiscoveryConfig),
                ("delegation", AgentToolsDelegationConfig),
            ):
                val = agent_tools_data.get(key)
                if isinstance(val, dict):
                    agent_tools_data[key] = sub_cls(**_filter_dataclass_fields(val, sub_cls))
            output_data = agent_tools_data.get("output")
            if isinstance(output_data, dict):
                semantic_data = output_data.get("semantic_summary")
                if isinstance(semantic_data, dict):
                    output_data["semantic_summary"] = AgentToolsOutputSemanticSummaryConfig(
                        **_filter_dataclass_fields(
                            semantic_data,
                            AgentToolsOutputSemanticSummaryConfig,
                        )
                    )
                agent_tools_data["output"] = AgentToolsOutputConfig(
                    **_filter_dataclass_fields(output_data, AgentToolsOutputConfig)
                )
            config.agent_tools = AgentToolsConfig(**agent_tools_data)

        if "app_name" in data:
            config.app_name = data["app_name"]
        if "version" in data:
            config.version = data["version"]
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
            # 使用默认路径：data/config/config.json
            config_dir = get_default_data_dir() / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            target_config_path = config_dir / "config.json"
            self._sync_startup_config(target_config_path)
            config_path = str(target_config_path)

        self.config_path = Path(config_path)
        self.raw_config: Dict[str, Any] = {}

    @staticmethod
    def _sync_startup_config(target_config_path: Path, working_dir: Optional[Path] = None) -> None:
        """
        启动时同步配置文件到 data/config/config.json。

        搜索顺序：
        1. working_dir（默认 cwd）下的 config.json
        2. working_dir 下的 config.example.json
        3. **仅打包态**：PyInstaller 解压目录下的 config.example.json
        4. 以上均不存在则跳过

        第 3 步限定打包态，是因为开发时 ``bundled_resource_path`` 解析到仓库根，
        那里总有 config.example.json——无条件回落会让"哪里都没有配置"这个分支
        在开发环境永远走不到。
        """
        current_dir = working_dir or Path.cwd()
        config_source = current_dir / "config.json"
        example_source = current_dir / "config.example.json"

        # 打包后 cwd 是安装目录、不含模板，须回落到 PyInstaller 解压目录
        bundled_example = (
            bundled_resource_path("config.example.json") if is_frozen() else None
        )

        if config_source.exists():
            source_path = config_source
        elif example_source.exists():
            source_path = example_source
        elif bundled_example is not None and bundled_example.exists():
            source_path = bundled_example
        else:
            logger.info(
                "[配置文件] 未找到 config.json 或 config.example.json，跳过启动同步"
            )
            return

        target_config_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if source_path.resolve() == target_config_path.resolve():
                logger.debug("[配置文件] 启动同步跳过：源文件与目标文件相同")
                return
        except Exception:
            # resolve 失败时继续尝试复制
            pass

        try:
            if target_config_path.exists():
                source_content = source_path.read_bytes()
                target_content = target_config_path.read_bytes()
                if source_content == target_content:
                    logger.debug("[配置文件] 启动同步跳过：源文件与目标文件内容一致")
                    return

            shutil.copy2(source_path, target_config_path)
            logger.info(f"[配置文件] 启动同步成功: {source_path} -> {target_config_path}")
        except Exception as e:
            logger.warning(f"[配置文件] 启动同步失败: {e}")

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
                    if isinstance(data, dict):
                        self.raw_config = copy.deepcopy(data)
                        from src.data.config_contract import DEFAULT_CONFIG_CONTRACT

                        deprecated_paths = DEFAULT_CONFIG_CONTRACT.deprecated_paths(data)
                        if deprecated_paths:
                            logger.warning(
                                "[配置文件] 已忽略弃用配置键: %s",
                                ", ".join(deprecated_paths),
                            )
                        non_file_paths = tuple(
                            path
                            for path in DEFAULT_CONFIG_CONTRACT.non_file_paths(data)
                            if path not in deprecated_paths
                        )
                        if non_file_paths:
                            logger.warning(
                                "[配置文件] 已忽略非文件配置键: %s",
                                ", ".join(non_file_paths),
                            )
                        unknown_paths = tuple(
                            violation.path
                            for violation in DEFAULT_CONFIG_CONTRACT.validate_mapping(
                                data,
                                template=False,
                            )
                            if violation.code == "unknown_path"
                        )
                        if unknown_paths:
                            logger.warning(
                                "[配置文件] 已忽略未支持配置键: %s",
                                ", ".join(unknown_paths),
                            )
                    config = AppConfig.from_dict(data)
                    logger.info(f"[配置文件] 已加载: {self.config_path}")
                    return config
            except Exception as e:
                self.raw_config = {}
                logger.error(f"[配置文件] 加载失败: {e}")
                return AppConfig()
        else:
            self.raw_config = {}
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
