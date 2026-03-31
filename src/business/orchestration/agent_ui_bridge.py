"""
AgentUIBridge — UI 与 Orchestrator 的线程桥接

解决核心问题：Orchestrator.run_agent() 是同步阻塞方法，不能在 PyQt 主线程调用。
AgentUIBridge 将其放入后台 QThread，通过 PyQt 信号将结果安全传递给 UI。

支持多 worker 并行：assistant 和教技能流程可以同时运行。
"""

import logging
from typing import Dict, List, Optional, Set

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from src.utils.events import connect, emit
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


class RetryTeachingWorker(QObject):
    """教学重试工作线程"""

    finished = pyqtSignal()

    def __init__(self, orchestrator: AgentOrchestrator, workflow_id: str):
        super().__init__()
        self._orchestrator = orchestrator
        self._workflow_id = workflow_id

    def run(self):
        try:
            self._orchestrator.retry_teaching(self._workflow_id)
        except Exception as e:
            logger.error(f"[RetryTeachingWorker] 执行失败: {e}", exc_info=True)
            try:
                self._orchestrator.reset_retrying_status(self._workflow_id)
            except Exception:
                logger.error("[RetryTeachingWorker] 重置 retrying 状态失败", exc_info=True)
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

    # 失败追踪信号
    failure_updated_signal = pyqtSignal(str, str, str, bool)  # workflow_id, failed_stage, event_type, is_new
    retry_failed_signal = pyqtSignal(str, str)  # workflow_id, error

    def __init__(self, orchestrator: AgentOrchestrator):
        super().__init__()
        self._orchestrator = orchestrator
        # 多 worker 支持：按 key 隔离（workflow_id 或 session_id）
        self._worker_threads: Dict[str, QThread] = {}
        self._workers: Dict[str, QObject] = {}

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

        # 失败追踪 blinker 监听
        connect("teaching_failure_updated", self._on_failure_updated)
        connect("teaching_failure_resolved", self._on_failure_resolved)
        connect("teaching_failure_retrying", self._on_failure_retrying)

        # 当前正在重试的 workflow_id 集合
        # 线程安全说明：依赖 CPython GIL 下 set 基本操作近似原子，
        # 竞态窗口极窄，最坏情况仅是一次 toast 重复或缺失，不影响数据正确性。
        self._retrying_workflows: Set[str] = set()

    def is_retrying(self, workflow_id: str) -> bool:
        """查询指定 workflow 是否正在重试中"""
        return workflow_id in self._retrying_workflows

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
        worker = AgentWorker(
            self._orchestrator, agent_type, user_input,
            workflow_id=workflow_id, session_id=session_id,
        )
        self._run_in_background(worker_key, worker)

    def get_trial_messages(self, workflow_id: str) -> List[dict]:
        """同步获取 trial 历史消息，可在主线程调用

        设计说明：打破本类"所有 orchestrator 调用都走后台线程"的模式。
        纯 DB 只读查询，毫秒级，有意为之。不要将此模式用于耗时操作。
        """
        return self._orchestrator.get_trial_messages(workflow_id)

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
        """清理已完成的 worker（由 thread.finished 触发，线程已停止）"""
        thread = self._worker_threads.pop(worker_key, None)
        worker = self._workers.pop(worker_key, None)
        if thread:
            thread.deleteLater()
        if worker:
            worker.deleteLater()

    def _run_in_background(self, worker_key: str, worker: QObject, on_finished=None) -> bool:
        """通用后台线程调度。返回是否成功启动。"""
        existing = self._worker_threads.get(worker_key)
        if existing and existing.isRunning():
            logger.warning(f"[AgentUIBridge] worker {worker_key} 仍在运行，忽略请求")
            return False
        # 清理残留：旧线程已退出但 thread.finished 尚未交付，防止误删新 worker
        if existing:
            existing.finished.disconnect()
            self._cleanup_worker(worker_key)

        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        if on_finished:
            thread.finished.connect(on_finished)
        thread.finished.connect(lambda wk=worker_key: self._cleanup_worker(wk))
        thread.start()

        self._worker_threads[worker_key] = thread
        self._workers[worker_key] = worker
        return True

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
        workflow_id = kwargs.get("workflow_id") or ""
        agent_type = kwargs.get("agent_type") or ""
        # 重试中的教学 workflow 出错时，走专用信号避免重复 toast
        if workflow_id in self._retrying_workflows and agent_type in ("pm", "programmer", "trial"):
            self.retry_failed_signal.emit(
                workflow_id,
                kwargs.get("error") or "",
            )
            return
        self.error_occurred.emit(
            workflow_id,
            kwargs.get("session_id") or "",
            agent_type,
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

    # -------------------------------------------------------------------------
    # 失败追踪 blinker → PyQt 信号
    # -------------------------------------------------------------------------

    def _on_failure_event(self, event_type: str, sender, **kwargs):
        failed_stage = "" if event_type == "resolved" else (kwargs.get("failed_stage") or "")
        self.failure_updated_signal.emit(
            kwargs.get("workflow_id") or "",
            failed_stage,
            event_type,
            kwargs.get("is_new", False),
        )

    def _on_failure_updated(self, sender, **kwargs):
        self._on_failure_event("updated", sender, **kwargs)

    def _on_failure_resolved(self, sender, **kwargs):
        self._on_failure_event("resolved", sender, **kwargs)

    def _on_failure_retrying(self, sender, **kwargs):
        self._on_failure_event("retrying", sender, **kwargs)

    # -------------------------------------------------------------------------
    # 重试 / 忽略 / 启动重置
    # -------------------------------------------------------------------------

    def retry_teaching(self, workflow_id: str) -> None:
        """在后台线程中执行教学重试"""
        self._retrying_workflows.add(workflow_id)
        worker_key = workflow_id  # 与 start_agent 共享 worker 字典，防止并发
        worker = RetryTeachingWorker(self._orchestrator, workflow_id)
        on_cleanup = lambda wid=workflow_id: self._retrying_workflows.discard(wid)
        if not self._run_in_background(worker_key, worker, on_finished=on_cleanup):
            self._retrying_workflows.discard(workflow_id)

    def dismiss_failure(self, workflow_id: str) -> None:
        """忽略失败记录（主线程同步调用，仅 DB + emit，无阻塞）"""
        if workflow_id in self._retrying_workflows:
            logger.warning(f"[AgentUIBridge] 正在重试中，不允许忽略: {workflow_id}")
            return
        self._orchestrator.dismiss_failure(workflow_id)

    def reset_stale_retrying(self) -> None:
        """启动时重置所有 retrying 状态为 active（同步，可在预热线程调用）"""
        workflow_ids = self._orchestrator.reset_all_retrying()
        for wid in workflow_ids:
            emit(
                "teaching_failure_updated",
                sender=self._orchestrator,
                workflow_id=wid,
                failed_stage="",
                error_type="",
            )
