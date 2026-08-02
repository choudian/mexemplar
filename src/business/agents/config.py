"""
Agent 配置系统

定义不同 Agent 类型的配置和行为参数。
"""

from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
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
    EPHEMERAL_SUBAGENT = "ephemeral_subagent"
    SPECIALIST = "specialist"

    @property
    def display_name(self) -> str:
        return _AGENT_TYPE_DISPLAY_NAMES[self]


_AGENT_TYPE_DISPLAY_NAMES = {
    AgentType.PM: "需求分析",
    AgentType.PROGRAMMER: "技能学习",
    AgentType.TRIAL: "技能试用",
    AgentType.ASSISTANT: "AI 助手",
    AgentType.EPHEMERAL_SUBAGENT: "临时子代理",
    AgentType.SPECIALIST: "固定专员",
}


def subagent_label(agent_type: str | AgentType | None) -> str:
    """根据 agent_type 返回 UI 展示用的子任务标签。"""
    if agent_type is None:
        return "子助手"
    raw = agent_type.value if isinstance(agent_type, AgentType) else str(agent_type)
    if raw == AgentType.SPECIALIST.value:
        return "固定专员"
    return "子助手"


class ResultType(str, Enum):
    """Agent 运行结果类型"""

    COMPLETED = "completed"
    NEEDS_USER_INPUT = "needs_user_input"
    MAX_ITERATIONS_REACHED = "max_iterations_reached"
    ERROR = "error"
    # resumable_on_failure=True 的 Agent（如临时子代理）撞迭代上限或 LLM 调用最终失败时
    # 返回该状态：会话置为 suspended、工作历史完整保留，主代理可唤回续跑。
    PAUSED = "paused"
    # 用户主动"停止"触发的协作式取消（014-assistant-chat-transparency）：
    # AgentLoop 在安全节点命中 cancel_event 时置会话 suspended 并返回该状态。
    # 必须与不可恢复 ERROR 严格区分——停止是可恢复暂停，不是错误。
    CANCELLED = "cancelled"


@dataclass
class RetryConfig:
    """重试配置

    任何 LLM 调用异常都会触发重试，采用指数退避：
    delay = retry_delay * 2 ** retry_count。
    """

    max_retries: int = 3
    retry_delay: float = 1.0


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
    has_side_effects: bool = True
    is_concurrency_safe: bool = False
    # 需独占调用：与其他工具在同一批 tool_calls 中出现时，AgentLoop 不执行该批任一工具，
    # 全部记为 invalid_model_output 并完整配对返回（提示模型单独调用）。solo 时正常执行。
    # 与 is_interrupting 区分：独占工具非中断型，handler 返回 str 后 loop 在同一回合继续。
    requires_exclusive_call: bool = False
    pre_hook: Optional[PreHook] = None
    post_hook: Optional[PostHook] = None


@dataclass
class AgentConfig:
    """Agent 配置"""

    agent_type: AgentType
    system_prompt: str
    max_iterations: int = 10
    # retry 字段保留以兼容历史构造调用，但 AgentLoop 在运行时已不再消费它——
    # 实际重试参数由 unified_config 的 ai.retry_max_retries / ai.retry_delay 决定。
    retry: RetryConfig = field(default_factory=RetryConfig)
    text_as_user_input: bool = False
    # 为 True 时，LLM 直接返回文字（未调用任何工具）视为对用户的提问，
    # loop 返回 NEEDS_USER_INPUT 而非 COMPLETED。
    # 适用于需要持续与用户对话、不能自然结束的 Agent（如 PM/Trial）。
    # 主助理为 False：给用户回复统一走 reply_to_user 显式工具。
    resumable_on_failure: bool = False
    # 为 True 时，撞 max_iterations 或 LLM 调用经重试仍最终失败，
    # loop 不返回 MAX_ITERATIONS_REACHED/ERROR，而是把会话置 suspended 并返回 PAUSED，
    # 保留工作历史供主代理唤回续跑。用于临时子代理。
    global_pre_hooks: List[PreHook] = field(default_factory=list)
    global_post_hooks: List[PostHook] = field(default_factory=list)
    # 注入的执行体工作区根目录；None 时回退 Path.cwd()（主助理/普通执行体默认行为）。
    # 自我改进实施桥接（T020）在此填入 proposal 的隔离 git worktree 路径，使执行体的
    # 文件/exec 爆炸半径被 workspace policy 焊死在 worktree 内（FR-014a 承重假设）。
    workspace_root: Optional[Path] = None


class PauseReason(str, Enum):
    """PAUSED 的结构化原因。

    父侧需要区分"跑到预算了"、"等用户充值"和"等其他外部恢复"——三者能采取的
    动作不同。仅靠 ``error`` 文本无法可靠区分，故单列。
    """

    BUDGET_EXHAUSTED = "budget_exhausted"
    """撞迭代上限：工作完整保留，追加预算即可续跑。"""

    QUOTA_EXHAUSTED = "quota_exhausted"
    """模型额度已耗尽：只有用户充值后才能继续。"""

    EXTERNAL_UNAVAILABLE = "external_unavailable"
    """LLM 限流/网络等其他外部原因：需等外部恢复。"""


@dataclass
class AgentResult:
    """Agent 运行结果"""

    result_type: ResultType
    question: Optional[str] = None
    error: Optional[str] = None
    signal_tool: Optional[Any] = None  # ToolCallInfo，信号工具触发时携带
    pause_reason: Optional[str] = None  # PauseReason，仅 PAUSED 时有值
    iterations_used: Optional[int] = None  # 已跑轮数，供父侧判断是否追加预算
    max_iterations: Optional[int] = None  # 本次的轮次上限


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
# text_as_user_input=False：主助理给用户的回复统一走 reply_to_user 显式工具；
# 纯文本输出仍会落库并展示，但按 COMPLETED 结束本轮，不再转 NEEDS_USER_INPUT。
ASSISTANT_CONFIG = AgentConfig(
    agent_type=AgentType.ASSISTANT,
    system_prompt=ASSISTANT_SYSTEM_PROMPT,
    max_iterations=200,
    text_as_user_input=False,
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
