"""
LangGraph Agent 图定义

定义 Agent 的状态流转图。
"""

from typing import Literal, Optional
from langgraph.graph import StateGraph, END

from .state import AgentState
from .checkpointer import get_memory_checkpointer


def create_tool_generation_graph():
    """
    创建工具生成流程的 Agent 图

    流程：录制数据 → 意图分析 → 用户确认 → 代码生成 → 保存工具
    支持用户在确认阶段提供反馈，循环回到确认阶段
    """
    from .nodes import (
        intent_analysis_node,
        intent_confirmation_node,
        code_generation_node,
    )

    # 创建状态图
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("intent_analysis", intent_analysis_node)
    workflow.add_node("intent_confirmation", intent_confirmation_node)
    workflow.add_node("code_generation", code_generation_node)

    # 设置入口点
    workflow.set_entry_point("intent_analysis")

    # 添加边
    workflow.add_edge("intent_analysis", "intent_confirmation")

    # 添加条件边：从 intent_confirmation 可以继续到 code_generation 或循环回自己
    def should_continue_or_confirm(state: AgentState) -> Literal["code_generation", "intent_confirmation", "END"]:
        """
        判断下一步：
        - 如果用户已确认，进入代码生成
        - 如果用户提供了反馈，再次进入确认阶段（循环）
        - 如果用户取消，结束
        """
        # 检查最后一条消息，判断用户操作
        messages = state.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, 'content'):
                content = last_message.content
                # 如果是用户确认的消息，继续代码生成
                if "用户已确认意图" in content:
                    return "code_generation"
                # 如果是 AI 对用户反馈的回复，循环回确认阶段
                # 这样会再次触发 interrupt
                elif content and not content.startswith("用户反馈："):
                    # 这是 AI 的回复，需要再次 interrupt 等待用户
                    return "intent_confirmation"

        # 默认继续代码生成
        return "code_generation"

    workflow.add_conditional_edges(
        "intent_confirmation",
        should_continue_or_confirm,
        {
            "code_generation": "code_generation",
            "intent_confirmation": "intent_confirmation",
        }
    )

    workflow.add_edge("code_generation", END)

    return workflow


def create_task_execution_graph():
    """
    创建任务执行流程的 Agent 图

    流程：用户意图 → 工具匹配 → (用户确认) → 执行工具 → 返回结果
    """
    from .nodes import (
        intent_understanding_node,
        tool_matching_node,
        tool_confirmation_node,
        tool_execution_node,
    )

    # 创建状态图
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("intent_understanding", intent_understanding_node)
    workflow.add_node("tool_matching", tool_matching_node)
    workflow.add_node("tool_confirmation", tool_confirmation_node)
    workflow.add_node("tool_execution", tool_execution_node)

    # 设置入口点
    workflow.set_entry_point("intent_understanding")

    # 添加条件边
    def should_confirm_tool(state: AgentState) -> Literal["tool_confirmation", "tool_execution"]:
        """判断是否需要用户确认工具调用"""
        if state.get("requires_user_confirmation", False):
            return "tool_confirmation"
        return "tool_execution"

    workflow.add_edge("intent_understanding", "tool_matching")
    workflow.add_conditional_edges(
        "tool_matching",
        should_confirm_tool,
        {
            "tool_confirmation": "tool_confirmation",
            "tool_execution": "tool_execution",
        }
    )
    workflow.add_edge("tool_confirmation", "tool_execution")
    workflow.add_edge("tool_execution", END)

    return workflow


def create_chat_graph():
    """
    创建普通对话流程的 Agent 图

    流程：用户消息 → LLM 回复 → 返回结果
    """
    from .nodes import chat_node

    # 创建状态图
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("chat", chat_node)

    # 设置入口点
    workflow.set_entry_point("chat")

    # 添加边
    workflow.add_edge("chat", END)

    return workflow


def create_agent_graph(
    conversation_type: str = "tool_generation",
    checkpointer=None
):
    """
    创建 Agent 图

    Args:
        conversation_type: 对话类型
            - 'tool_generation': 工具生成流程
            - 'task_execution': 任务执行流程
            - 'chat': 普通对话
        checkpointer: 状态持久化器（可选，默认使用内存存储）

    Returns:
        编译后的 Agent 图

    Usage:
        # 使用内存存储（默认）
        app = create_agent_graph("tool_generation")

        # 使用 SQLite 持久化
        from src.business.agent.checkpointer import get_checkpointer
        checkpointer = get_checkpointer()
        app = create_agent_graph("tool_generation", checkpointer)
        config = {"configurable": {"thread_id": "session-123"}}
        result = app.invoke(input, config)
    """
    # 根据对话类型选择对应的图
    if conversation_type == "tool_generation":
        workflow = create_tool_generation_graph()
    elif conversation_type == "task_execution":
        workflow = create_task_execution_graph()
    elif conversation_type == "chat":
        workflow = create_chat_graph()
    else:
        raise ValueError(f"Unknown conversation type: {conversation_type}")

    # 如果没有提供 checkpointer，使用内存存储
    if checkpointer is None:
        checkpointer = get_memory_checkpointer()

    # 编译图
    app = workflow.compile(checkpointer=checkpointer)

    return app
