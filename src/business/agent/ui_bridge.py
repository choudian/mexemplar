"""
Agent UI 桥接层

负责管理 Agent 生命周期、线程安全、PyQt 信号传递。
"""

import threading
import time
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal

from .graph import create_agent_graph
from .checkpointer import get_memory_checkpointer


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
    session_completed = pyqtSignal(str, object)  # (thread_id, tool_draft)

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

                # 关键修复：复用原有的 checkpointer 和 agent 实例
                # MemorySaver 是内存存储，必须使用同一实例才能保留 interrupt 状态
                checkpointer = session.checkpointer
                agent = self._agents.get(thread_id)

                if checkpointer is None or agent is None:
                    # 如果没有保存的实例，则需要重新创建（但这种情况可能导致状态丢失）
                    # 对于 SQLite checkpointer，可以重新连接；对于 MemorySaver，状态会丢失
                    if self._use_persistence:
                        # SQLite 可以重新连接
                        checkpointer = self._create_checkpointer()
                        session.checkpointer = checkpointer
                    else:
                        # MemorySaver 状态已丢失，这是一个错误状态
                        self._handle_agent_error(
                            thread_id,
                            "Session state lost: MemorySaver requires same instance for resume"
                        )
                        return

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

                # 从 interrupt value 中提取 ai_response（如果有）
                # ai_response 是在 intent_confirmation_node 中设置到 interrupt_data 里的
                first_interrupt_value = interrupt_list[0].value if interrupt_list else {}
                if isinstance(first_interrupt_value, dict) and "ai_response" in first_interrupt_value:
                    interrupt_data["ai_response"] = first_interrupt_value["ai_response"]

                self.interrupt_requested.emit(thread_id, interrupt_data)
        else:
            # Agent 执行完成
            session.status = "completed"

            # 提取 tool_draft（如果存在）
            tool_draft = result.get("tool_draft")

            # 发射完成信号（带上 tool_draft）
            self.session_completed.emit(thread_id, tool_draft)

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
