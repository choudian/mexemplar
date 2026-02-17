"""
LangGraph Agent 模块

本模块包含基于 LangGraph 的对话 Agent 实现，支持：
- 工具生成流程（录制 → 意图分析 → 用户确认 → 代码生成）
- 任务执行流程（用户意图 → 工具匹配 → 执行）
- 普通对话流程

核心组件：
- graph.py: Agent 状态图定义
- state.py: Agent 状态数据模型
- ui_bridge.py: UI 桥接层（线程管理、信号传递）
- nodes/: 各个节点实现
- prompts/: 提示词模板
- tools/: LangGraph Tools 适配器
- checkpointer/: 状态持久化
"""

from .state import AgentState, IntentData, ToolDraft
from .graph import create_agent_graph
from .ui_bridge import AgentUIBridge

__all__ = [
    "AgentState",
    "IntentData",
    "ToolDraft",
    "create_agent_graph",
    "AgentUIBridge",
]
