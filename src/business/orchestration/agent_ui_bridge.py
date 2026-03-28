"""
AgentUIBridge — UI 与 Orchestrator 的线程桥接

解决核心问题：Orchestrator.run_agent() 是同步阻塞方法，不能在 PyQt 主线程调用。
AgentUIBridge 将其放入后台 QThread，通过 PyQt 信号将结果安全传递给 UI。

支持多 worker 并行：assistant 和教技能流程可以同时运行。
"""

import logging
from typing import Dict, Optional

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
        workflow_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        super().__init__()
        self._orchestrator = orchestrator
        self._agent_type = agent_type
        self._user_input = user_input
        self._workflow_id = workflow_id
        self._session_id = session_id

    def run(self):
        """在后台线程中执行 Orchestrator"""
        try:
            self._orchestrator.run_agent(
                self._agent_type,
                self._user_input,
                workflow_id=self._workflow_id,
                session_id=self._session_id,
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

    支持多 worker 并行：按 worker_key（workflow_id 或 session_id）隔离 worker。
    """

    # UI 关注的 PyQt 信号（新增 session_id 参数）
    question_received = pyqtSignal(str, str, str, str)  # workflow_id, session_id, agent_type, question
    error_occurred = pyqtSignal(str, str, str, str)  # workflow_id, session_id, agent_type, error
    progress_updated = pyqtSignal(str, str)  # workflow_id, event_name
    tool_saved_signal = pyqtSignal(str, str, bool)  # workflow_id, tool_id, from_triage
    tool_published_signal = pyqtSignal(str, str)  # workflow_id, tool_id

    def __init__(self, orchestrator: AgentOrchestrator):
        super().__init__()
        self._orchestrator = orchestrator
        # 多 worker 支持：按 key 隔离（workflow_id 或 session_id）
        self._worker_threads: Dict[str, QThread] = {}
        self._workers: Dict[str, AgentWorker] = {}

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
        connect("tool_published", self._on_tool_published)

    def start_agent(
        self,
        agent_type: str,
        user_input: str,
        workflow_id: str = None,
        session_id: str = None,
    ) -> None:
        """
        在后台线程中启动 Agent。UI 调用此方法，不阻塞主线程。
        支持多 worker 并行：不同 workflow_id/session_id 的任务可以同时运行。
        """
        worker_key = session_id or workflow_id or "default"
        existing = self._worker_threads.get(worker_key)
        if existing and existing.isRunning():
            logger.warning(
                f"[AgentUIBridge] worker {worker_key} 仍在运行，忽略本次请求"
            )
            return

        thread = QThread()
        worker = AgentWorker(
            self._orchestrator, agent_type, user_input,
            workflow_id=workflow_id, session_id=session_id,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(lambda: self._cleanup_worker(worker_key))
        thread.start()

        self._worker_threads[worker_key] = thread
        self._workers[worker_key] = worker

    def reply_to_agent(
        self,
        agent_type: str,
        user_input: str,
        workflow_id: str = None,
        session_id: str = None,
    ) -> None:
        """
        用户回复 Agent 的提问。
        与 start_agent 相同机制（上一个 loop 返回 NEEDS_USER_INPUT 后线程已结束）。
        """
        self.start_agent(
            agent_type, user_input,
            workflow_id=workflow_id, session_id=session_id,
        )

    def _cleanup_worker(self, worker_key: str):
        """清理已完成的 worker"""
        self._worker_threads.pop(worker_key, None)
        self._workers.pop(worker_key, None)

    # -------------------------------------------------------------------------
    # blinker 事件监听器 → PyQt 信号
    # 注意：kwargs.get("key", "") 在 key 存在但值为 None 时返回 None，
    # 而 pyqtSignal(str) 不接受 None。统一用 `or ""` 兜底。
    # -------------------------------------------------------------------------

    def _on_needs_user_input(self, sender, **kwargs):
        self.question_received.emit(
            kwargs.get("workflow_id") or "",
            kwargs.get("session_id") or "",
            kwargs.get("agent_type") or "",
            kwargs.get("question") or "",
        )

    def _on_error(self, sender, **kwargs):
        self.error_occurred.emit(
            kwargs.get("workflow_id") or "",
            kwargs.get("session_id") or "",
            kwargs.get("agent_type") or "",
            kwargs.get("error") or "",
        )

    def _on_progress(self, sender, **kwargs):
        event_name = kwargs.get("event_name") or "progress"
        self.progress_updated.emit(
            kwargs.get("workflow_id") or "",
            event_name,
        )

    def _on_tool_saved(self, sender, **kwargs):
        self.tool_saved_signal.emit(
            kwargs.get("workflow_id") or "",
            kwargs.get("tool_id") or "",
            kwargs.get("from_triage", False),
        )

    def _on_tool_published(self, sender, **kwargs):
        self.tool_published_signal.emit(
            kwargs.get("workflow_id") or "",
            kwargs.get("tool_id") or "",
        )
