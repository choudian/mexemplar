"""
Agent 配置系统

定义不同 Agent 类型的配置和行为参数。
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Dict, Any, Union

from src.business.agents.hook_models import (
    PostHook,
    PreHook,
)
from src.business.agents.prompts.pm_prompt import PM_SYSTEM_PROMPT
from src.business.agents.prompts.programmer_prompt import PROGRAMMER_SYSTEM_PROMPT
from src.business.agents.prompts.assistant_prompt import ASSISTANT_SYSTEM_PROMPT


class AgentType(str, Enum):
    """Agent 类型"""

    PM = "pm"
    PROGRAMMER = "programmer"
    TRIAL = "trial"
    ASSISTANT = "assistant"

    @property
    def display_name(self) -> str:
        return _AGENT_TYPE_DISPLAY_NAMES[self]


_AGENT_TYPE_DISPLAY_NAMES = {
    AgentType.PM: "需求分析",
    AgentType.PROGRAMMER: "技能学习",
    AgentType.TRIAL: "技能试用",
    AgentType.ASSISTANT: "AI 助手",
}


class ResultType(str, Enum):
    """Agent 运行结果类型"""

    COMPLETED = "completed"
    NEEDS_USER_INPUT = "needs_user_input"
    MAX_ITERATIONS_REACHED = "max_iterations_reached"
    ERROR = "error"


@dataclass
class RetryConfig:
    """重试配置"""

    max_retries: int = 3
    retry_delay: float = 1.0
    retryable_errors: List[str] = field(
        default_factory=lambda: [
            "rate_limit_exceeded",
            "timeout",
            "connection_error",
        ]
    )


@dataclass
class ToolSignal:
    """
    工具信号 — 工具 handler 返回此类型时，AgentLoop 中断循环。

    普通工具返回 str，信号工具返回 ToolSignal。
    Loop 只做 isinstance 检查，不关心具体是哪个工具。
    """

    result_type: "ResultType"
    display_text: str = "[已提交]"
    save_result: bool = True  # False 时 AgentLoop 不保存 tool result（用于失败快速分诊）


@dataclass
class ToolDefinition:
    """工具定义：FC schema + 实现函数的映射"""

    name: str
    schema: Dict[str, Any]
    handler: Callable[..., Union[str, ToolSignal]]
    is_interrupting: bool = False
    pre_hook: Optional[PreHook] = None
    post_hook: Optional[PostHook] = None


@dataclass
class AgentConfig:
    """Agent 配置"""

    agent_type: AgentType
    system_prompt: str
    max_iterations: int = 10
    retry: RetryConfig = field(default_factory=RetryConfig)
    text_as_user_input: bool = False
    # 为 True 时，LLM 直接返回文字（未调用任何工具）视为隐式 talk_to_user，
    # loop 返回 NEEDS_USER_INPUT 而非 COMPLETED。
    # 适用于需要持续与用户对话、不能自然结束的 Agent（如 PM Agent）。
    global_pre_hooks: List[PreHook] = field(default_factory=list)
    global_post_hooks: List[PostHook] = field(default_factory=list)


@dataclass
class AgentResult:
    """Agent 运行结果"""

    result_type: ResultType
    question: Optional[str] = None
    error: Optional[str] = None
    signal_tool: Optional[Any] = None  # ToolCallInfo，信号工具触发时携带


# =============================================================================
# 内置 Agent 配置
# =============================================================================

# PM Agent 配置
# system_prompt 含 {recording_id} 模板变量，由 Orchestrator 在启动时格式化
PM_CONFIG = AgentConfig(
    agent_type=AgentType.PM,
    system_prompt=PM_SYSTEM_PROMPT,
    max_iterations=50,
    text_as_user_input=True,
)

# Programmer Agent 配置
# system_prompt 含 {recording_id} 模板变量，由 Orchestrator 在启动时格式化
PROGRAMMER_CONFIG = AgentConfig(
    agent_type=AgentType.PROGRAMMER,
    system_prompt=PROGRAMMER_SYSTEM_PROMPT,
    max_iterations=30,
)

# Assistant Agent 配置
# system_prompt 含 {profile_section}/{memory_section}/{tools_section} 占位符，
# 由 Orchestrator 通过 format_assistant_prompt() 格式化后传入 system_prompt_override
ASSISTANT_CONFIG = AgentConfig(
    agent_type=AgentType.ASSISTANT,
    system_prompt=ASSISTANT_SYSTEM_PROMPT,
    max_iterations=200,
    text_as_user_input=True,
)


__all__ = [
    "AgentType",
    "ResultType",
    "RetryConfig",
    "ToolSignal",
    "ToolDefinition",
    "AgentConfig",
    "AgentResult",
    "PM_CONFIG",
    "PROGRAMMER_CONFIG",
    "ASSISTANT_CONFIG",
]
