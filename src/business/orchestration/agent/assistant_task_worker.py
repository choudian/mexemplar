import json
import logging
import threading
from typing import Callable, Optional

from src.data.repositories import PendingTaskRepository
from src.business.agents.config import AgentType


class AssistantTaskWorker:
    def __init__(
        self,
        tool_repo,
        run_agent: Callable,
        start_triage: Callable,
        *,
        pending_task_repo_factory: Callable[[], PendingTaskRepository] = PendingTaskRepository,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._tool_repo = tool_repo
        self._run_agent = run_agent
        self._start_triage = start_triage
        self._pending_task_repo_factory = pending_task_repo_factory
        self._logger = logger or logging.getLogger(__name__)
        self._task_queue_event = threading.Event()
        self._task_worker_running = False

    @property
    def is_running(self) -> bool:
        return self._task_worker_running

    @is_running.setter
    def is_running(self, value: bool) -> None:
        self._task_worker_running = value

    def start(self) -> None:
        if self._task_worker_running:
            return

        self._task_worker_running = True
        from src.business.agents.tools.assistant_tools import register_task_worker_notify

        register_task_worker_notify(self.notify_task_enqueued)
        threading.Thread(target=self.task_worker_loop, daemon=True).start()
        self._logger.info("[Orchestrator] 后台任务队列 Worker 已启动")

    def notify_task_enqueued(self) -> None:
        self._task_queue_event.set()

    def task_worker_loop(self) -> None:
        poll_interval = 5.0
        while self._task_worker_running:
            try:
                self.process_pending_tasks()
            except Exception as exc:
                self._logger.error(f"[TaskWorker] 处理异常: {exc}", exc_info=True)
            self._task_queue_event.clear()
            self._task_queue_event.wait(timeout=poll_interval)

    def process_pending_tasks(self) -> None:
        repo = self._pending_task_repo_factory()
        tasks = repo.get_pending()
        for task in tasks:
            try:
                repo.update_status(task.task_id, "processing")
                if task.task_type == "codify_tool":
                    self.process_codify_task(task)
                elif task.task_type == "fix_tool_bug":
                    self.process_bug_task(task)
                else:
                    self._logger.warning(f"[TaskWorker] 未知任务类型: {task.task_type}")
                    repo.update_status(task.task_id, "failed")
                    continue
                repo.update_status(task.task_id, "completed")
            except Exception as exc:
                self._logger.error(
                    f"[TaskWorker] 任务 {task.task_id} 处理失败: {exc}",
                    exc_info=True,
                )
                repo.update_status(task.task_id, "failed")

    def process_codify_task(self, task) -> None:
        payload = json.loads(task.payload or "{}")
        task_description = payload.get("task_description", "")
        execution_trace = payload.get("execution_trace", [])

        trace_text = "\n".join(
            f"- [{entry['type']}] {entry.get('name', '')}："
            f"{entry.get('args', '') or entry.get('content', '')[:200]}"
            for entry in execution_trace[:20]
        )
        initial_input = (
            "用户要求将以下任务做成可复用工具：\n\n"
            f"任务描述：{task_description}\n\n"
            f"执行记录：\n{trace_text}\n\n"
            "请基于执行记录分析任务逻辑，与用户确认工具的名称、参数和说明，然后生成代码。"
        )

        workflow_id = f"codify_{task.task_id[:8]}"
        self._run_agent(AgentType.PM, initial_input, workflow_id=workflow_id)

    def process_bug_task(self, task) -> None:
        payload = json.loads(task.payload or "{}")
        tool_id = payload.get("tool_id", "")
        error_message = payload.get("error_message", "")

        tool = self._tool_repo.get_by_id(tool_id)
        if not tool or not tool.workflow_id:
            message = f"fix_tool_bug 找不到可分诊的工具或 workflow_id: tool_id={tool_id}"
            self._logger.warning("[TaskWorker] %s", message)
            raise ValueError(message)

        self._start_triage(tool_id, error_message, tool.workflow_id)
