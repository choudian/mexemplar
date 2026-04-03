"""
Agent Loop 核心

提供简洁的 while 循环驱动的 Agent 运行引擎。
"""

from .config import (
    AgentType,
    ResultType,
    RetryConfig,
    ToolSignal,
    ToolDefinition,
    AgentConfig,
    AgentResult,
    PM_CONFIG,
    PROGRAMMER_CONFIG,
    TRIAL_CONFIG,
    ASSISTANT_CONFIG,
    get_agent_config,
)
from .agent_loop import AgentLoop
from .builtin_tools import TALK_TO_USER_SCHEMA, LOAD_REFERENCE_SCHEMA
from .tool_helpers import make_tool_schema, make_signal_handler, error_json

__all__ = [
    # 配置
    "AgentType",
    "ResultType",
    "RetryConfig",
    "ToolSignal",
    "ToolDefinition",
    "AgentConfig",
    "AgentResult",
    "PM_CONFIG",
    "PROGRAMMER_CONFIG",
    "TRIAL_CONFIG",
    "ASSISTANT_CONFIG",
    "get_agent_config",
    # 核心类
    "AgentLoop",
    # 内置工具
    "TALK_TO_USER_SCHEMA",
    "LOAD_REFERENCE_SCHEMA",
    # 工具辅助函数
    "make_tool_schema",
    "make_signal_handler",
    "error_json",
]
