"""
AgentUIBridge — UI 与 Orchestrator 的线程桥接

解决核心问题：Orchestrator.run_agent() 是同步阻塞方法，不能在 PyQt 主线程调用。
AgentUIBridge 将其放入后台 QThread，通过 PyQt 信号将结果安全传递给 UI。
"""

import logging
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from src.utils.events import connect
from .agent_orchestrator import AgentOrchestrator

logger = logging.getLogger(__name__)


class AgentWorker(QObject):
    """后台工作线程的执行体"""

    finished = pyqtSignal()

    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        agent_type: str,
        user_input: str,
        workflow_id: str,
    ):
        super().__init__()
        self._orchestrator = orchestrator
        self._agent_type = agent_type
        self._user_input = user_input
        self._workflow_id = workflow_id

    def run(self):
        """在后台线程中执行 Orchestrator"""
        try:
            self._orchestrator.run_agent(
                self._agent_type,
                self._user_input,
                self._workflow_id,
            )
        except Exception as e:
            logger.error(f"[AgentWorker] 执行失败: {e}", exc_info=True)
        finally:
            self.finished.emit()


class AgentUIBridge(QObject):
    """
    UI 与 Orchestrator 的桥梁

    监听 Orchestrator 发出的 blinker 事件，转换为 PyQt 信号传递给 UI。
    PyQt 信号是跨线程安全的（Qt::AutoConnection 自动使用 QueuedConnection）。
    """

    # UI 关注的 PyQt 信号
    question_received = pyqtSignal(str, str, str)  # workflow_id, agent_type, question
    error_occurred = pyqtSignal(str, str, str)  # workflow_id, agent_type, error
    progress_updated = pyqtSignal(str, str)  # workflow_id, event_name
    tool_saved_signal = pyqtSignal(str, str)  # workflow_id, tool_id

    def __init__(self, orchestrator: AgentOrchestrator):
        super().__init__()
        self._orchestrator = orchestrator
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[AgentWorker] = None  # 防止 GC 回收

        # 监听 Orchestrator 发出的 blinker 事件，转换为 PyQt 信号
        connect("agent_needs_user_input", self._on_needs_user_input)
        connect("agent_error", self._on_error)
        connect("requirement_confirmed", self._on_progress)
        connect("code_completed", self._on_progress)
        connect("review_passed", self._on_progress)
        connect("review_failed", self._on_progress)
        connect("tool_saved", self._on_tool_saved)
        connect("trial_success", self._on_progress)
        connect("triage_completed", self._on_progress)

    def start_agent(self, agent_type: str, user_input: str, workflow_id: str) -> None:
        """
        在后台线程中启动 Agent。UI 调用此方法，不阻塞主线程。
        """
        if self._worker_thread and self._worker_thread.isRunning():
            logger.warning("[AgentUIBridge] 上一个任务仍在运行，忽略本次请求")
            return

        self._worker_thread = QThread()
        self._worker = AgentWorker(self._orchestrator, agent_type, user_input, workflow_id)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.start()

    def reply_to_agent(self, agent_type: str, user_input: str, workflow_id: str) -> None:
        """
        用户回复 Agent 的提问。
        与 start_agent 相同机制（上一个 loop 返回 NEEDS_USER_INPUT 后线程已结束）。
        """
        self.start_agent(agent_type, user_input, workflow_id)

    # -------------------------------------------------------------------------
    # blinker 事件监听器 → PyQt 信号
    # -------------------------------------------------------------------------

    def _on_needs_user_input(self, sender, **kwargs):
        self.question_received.emit(
            kwargs.get("workflow_id", ""),
            kwargs.get("agent_type", ""),
            kwargs.get("question", ""),
        )

    def _on_error(self, sender, **kwargs):
        self.error_occurred.emit(
            kwargs.get("workflow_id", ""),
            kwargs.get("agent_type", ""),
            kwargs.get("error", ""),
        )

    def _on_progress(self, sender, **kwargs):
        # event_name 由 emit() 自动注入
        event_name = kwargs.get("event_name", "progress")
        self.progress_updated.emit(
            kwargs.get("workflow_id", ""),
            event_name,
        )

    def _on_tool_saved(self, sender, **kwargs):
        self.tool_saved_signal.emit(
            kwargs.get("workflow_id", ""),
            kwargs.get("tool_id", ""),
        )
