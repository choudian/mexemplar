"""
Agent UI 桥接层

负责管理 Agent 生命周期、线程安全、PyQt 信号传递。
"""

import threading
import time
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal

from .graph import create_agent_graph
from .state import AgentState
from .checkpointer import get_memory_checkpointer, get_checkpointer_context


@dataclass
class AgentSession:
    """Agent 会话信息"""
    thread_id: str
    conversation_type: str
    status: str  # 'running' | 'interrupted' | 'completed' | 'error'
    created_at: float
    checkpointer: Any = None  # 每个 Agent 使用独立的 checkpointer


class AgentUIBridge(QObject):
    """
    Agent UI 桥接层

    职责：
    1. 管理 Agent 生命周期（启动、暂停、恢复）
    2. 处理线程管理（Agent 在后台线程运行）
    3. PyQt 信号传递（interrupt → UI，UI → resume）

    信号：
    - interrupt_requested: Agent 需要用户交互
    - response_ready: Agent 生成回复
    - error_occurred: Agent 执行出错
    - session_completed: Agent 会话完成
    """

    # PyQt 信号
    interrupt_requested = pyqtSignal(str, dict)  # (thread_id, interrupt_data)
    response_ready = pyqtSignal(str, str)  # (thread_id, response_text)
    error_occurred = pyqtSignal(str, str)  # (thread_id, error_message)
    session_completed = pyqtSignal(str)  # thread_id

    def __init__(self, parent=None, use_persistence: bool = False):
        super().__init__(parent)

        # 会话管理
        self._sessions: Dict[str, AgentSession] = {}

        # 线程管理
        self._agent_threads: Dict[str, threading.Thread] = {}

        # Agent 实例
        self._agents: Dict[str, Any] = {}

        # 是否使用持久化
        self._use_persistence = use_persistence

    def _get_checkpointer_context(self):
        """获取 checkpointer 上下文管理器"""
        if self._use_persistence:
            return get_checkpointer_context()
        else:
            # MemorySaver 不需要上下文管理器，包装一下保持接口一致
            from contextlib import contextmanager
            @contextmanager
            def memory_context():
                yield get_memory_checkpointer()
            return memory_context()

    def _create_checkpointer(self):
        """
        创建 Checkpointer 实例

        根据配置选择持久化或内存存储。

        Returns:
            Checkpointer 实例
        """
        if self._use_persistence:
            # 使用 SQLite 持久化
            from .checkpointer import get_checkpointer
            return get_checkpointer()
        else:
            # 使用内存存储
            return get_memory_checkpointer()

    def start_tool_generation(
        self,
        thread_id: str,
        compressed_data: Dict[str, Any],
        callback: Optional[Callable] = None
    ):
        """
        启动工具生成流程

        Args:
            thread_id: 会话 ID
            compressed_data: 压缩后的录制数据
            callback: 完成回调（可选）
        """
        # 创建会话（不在这里创建 checkpointer）
        session = AgentSession(
            thread_id=thread_id,
            conversation_type="tool_generation",
            status="running",
            created_at=time.time(),
            checkpointer=None  # 将在工作线程中创建
        )
        self._sessions[thread_id] = session

        # 启动后台线程
        def run_agent():
            try:
                # 在工作线程中创建 checkpointer（解决跨线程问题）
                checkpointer = self._create_checkpointer()
                session.checkpointer = checkpointer

                # 创建 Agent
                agent = create_agent_graph(
                    conversation_type="tool_generation",
                    checkpointer=checkpointer
                )
                self._agents[thread_id] = agent

                # 初始状态
                initial_state = {
                    "recording_data": compressed_data,
                    "conversation_type": "tool_generation"
                }

                # 执行 Agent
                config = {"configurable": {"thread_id": thread_id}}
                result = agent.invoke(initial_state, config)

                # 处理结果
                self._handle_agent_result(thread_id, result)

                # 调用回调
                if callback:
                    callback(result)

            except Exception as e:
                # 处理错误
                import traceback
                self._handle_agent_error(thread_id, f"{str(e)}\n{traceback.format_exc()}")

        # 启动线程
        thread = threading.Thread(target=run_agent, daemon=True)
        self._agent_threads[thread_id] = thread
        thread.start()

    def resume(self, thread_id: str, user_input: Dict[str, Any]):
        """
        恢复 Agent 执行

        Args:
            thread_id: 会话 ID
            user_input: 用户输入（从 interrupt 返回）
        """
        if thread_id not in self._sessions:
            self.error_occurred.emit(thread_id, f"Session not found: {thread_id}")
            return

        # 更新会话状态
        session = self._sessions[thread_id]
        session.status = "running"

        # 启动后台线程恢复执行
        def resume_agent():
            try:
                from langgraph.types import Command

                # 在当前线程中重新创建 checkpointer 和 agent（解决跨线程问题）
                checkpointer = self._create_checkpointer()
                session.checkpointer = checkpointer

                agent = create_agent_graph(
                    conversation_type=session.conversation_type,
                    checkpointer=checkpointer
                )
                self._agents[thread_id] = agent

                # 恢复执行（使用 Command）
                config = {"configurable": {"thread_id": thread_id}}
                result = agent.invoke(Command(resume=user_input), config)

                # 处理结果
                self._handle_agent_result(thread_id, result)

            except Exception as e:
                # 处理错误
                import traceback
                self._handle_agent_error(thread_id, f"{str(e)}\n{traceback.format_exc()}")

        # 启动线程
        thread = threading.Thread(target=resume_agent, daemon=True)
        thread.start()

    def start_chat_conversation(
        self,
        thread_id: str,
        user_message: str
    ):
        """
        启动普通对话流程

        Args:
            thread_id: 会话 ID
            user_message: 用户消息
        """
        # 创建会话（不在这里创建 checkpointer）
        session = AgentSession(
            thread_id=thread_id,
            conversation_type="chat",
            status="running",
            created_at=time.time(),
            checkpointer=None  # 将在工作线程中创建
        )
        self._sessions[thread_id] = session

        # 启动后台线程
        def run_agent():
            try:
                # 在工作线程中创建 checkpointer（解决跨线程问题）
                checkpointer = self._create_checkpointer()
                session.checkpointer = checkpointer

                # 创建 Agent
                agent = create_agent_graph(
                    conversation_type="chat",
                    checkpointer=checkpointer
                )
                self._agents[thread_id] = agent

                from langchain_core.messages import HumanMessage

                # 初始状态
                initial_state = {
                    "messages": [HumanMessage(content=user_message)],
                    "conversation_type": "chat"
                }

                # 执行 Agent
                config = {"configurable": {"thread_id": thread_id}}
                result = agent.invoke(initial_state, config)

                # 处理结果
                self._handle_agent_result(thread_id, result)

            except Exception as e:
                import traceback
                self._handle_agent_error(thread_id, f"{str(e)}\n{traceback.format_exc()}")

        # 启动线程
        thread = threading.Thread(target=run_agent, daemon=True)
        self._agent_threads[thread_id] = thread
        thread.start()

    def _handle_agent_result(self, thread_id: str, result: Dict[str, Any]):
        """
        处理 Agent 执行结果

        检查是否有 interrupt 或已完成
        """
        session = self._sessions.get(thread_id)
        if not session:
            return

        # 检查是否是 interrupt
        if "__interrupt__" in result:
            # Agent 被 interrupt，需要用户交互
            session.status = "interrupted"
            interrupt_list = result["__interrupt__"]
            # 提取第一个 interrupt 的值
            if interrupt_list:
                interrupt_data = {
                    "interrupts": [
                        {"value": intr.value, "id": intr.id}
                        for intr in interrupt_list
                    ]
                }

                # 检查是否有新消息（用于反馈对话）
                # 只有当消息数量 > 1 时才是反馈对话（首次只有 1 条分析结果消息）
                if "messages" in result and result["messages"] and len(result["messages"]) > 1:
                    # 发送最后一条消息（AI 的回复）
                    last_message = result["messages"][-1]
                    if hasattr(last_message, 'type') and last_message.type == 'ai':
                        response_text = getattr(last_message, "content", str(last_message))
                        # 确保不是确认消息（那是结束流程）
                        if "用户已确认意图" not in response_text:
                            # 在 interrupt 数据中包含 AI 回复
                            interrupt_data["ai_response"] = response_text

                self.interrupt_requested.emit(thread_id, interrupt_data)
        else:
            # Agent 执行完成
            session.status = "completed"
            self.session_completed.emit(thread_id)

            # 提取回复文本
            if "messages" in result and result["messages"]:
                last_message = result["messages"][-1]
                response_text = getattr(last_message, "content", str(last_message))
                self.response_ready.emit(thread_id, response_text)

    def _handle_agent_error(self, thread_id: str, error_message: str):
        """处理 Agent 错误"""
        session = self._sessions.get(thread_id)
        if session:
            session.status = "error"

        self.error_occurred.emit(thread_id, error_message)

    def get_session_status(self, thread_id: str) -> Optional[str]:
        """获取会话状态"""
        session = self._sessions.get(thread_id)
        return session.status if session else None

    def cleanup_session(self, thread_id: str):
        """清理会话资源"""
        if thread_id in self._sessions:
            del self._sessions[thread_id]
        if thread_id in self._agents:
            del self._agents[thread_id]
        if thread_id in self._agent_threads:
            del self._agent_threads[thread_id]
