"""
Agent Loop 核心

提供简洁的 while 循环驱动的 Agent 运行引擎。
"""

from .config import (
    AgentType,
    ResultType,
    RetryConfig,
    AgentConfig,
    AgentResult,
    PM_CONFIG,
    PROGRAMMER_CONFIG,
    TRIAL_CONFIG,
    get_agent_config,
    get_agent_type_str,
)
from .agent_loop import AgentLoop
from .tool_registry import agent_tool, get_tool_schemas, execute_tool, clear_registry
from .validation import validate_parameters
from .builtin_tools import TALK_TO_USER_SCHEMA, LOAD_REFERENCE_SCHEMA

# 导入业务工具（触发注册）
from .tools import (
    query_recording_data,
    multimodal_analysis,
    syntax_check,
)

__all__ = [
    # 配置
    "AgentType",
    "ResultType",
    "RetryConfig",
    "AgentConfig",
    "AgentResult",
    "PM_CONFIG",
    "PROGRAMMER_CONFIG",
    "TRIAL_CONFIG",
    "get_agent_config",
    "get_agent_type_str",
    # 核心类
    "AgentLoop",
    # 工具注册
    "agent_tool",
    "get_tool_schemas",
    "execute_tool",
    "clear_registry",
    # 验证
    "validate_parameters",
    # 内置工具
    "TALK_TO_USER_SCHEMA",
    "LOAD_REFERENCE_SCHEMA",
    # 业务工具
    "query_recording_data",
    "multimodal_analysis",
    "syntax_check",
]
