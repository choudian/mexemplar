import json

from src.business.agents.tools import assistant_tools
from src.business.orchestration.agent.assistant_task_worker import AssistantTaskWorker
from src.data.models_sqlite import PendingAssistantTask, Tool
from src.data.repositories import PendingTaskRepository, ToolRepository


class _TaskPort:
    def __init__(self):
        self.triage_calls = []
        self.agent_calls = []

    def start_triage(self, tool_id: str, user_feedback: str, workflow_id: str) -> None:
        self.triage_calls.append((tool_id, user_feedback, workflow_id))

    def run_agent(self, agent_type, user_input, workflow_id=None, session_id=None) -> None:
        self.agent_calls.append((agent_type, user_input, workflow_id, session_id))


def test_report_tool_bug_enqueues_task_and_worker_starts_triage(in_memory_db, monkeypatch):
    monkeypatch.setattr(assistant_tools, "_task_worker_notify", None)
    notified = []
    assistant_tools.register_task_worker_notify(lambda: notified.append(True))
    ToolRepository().create(
        Tool(
            tool_id="tool-1",
            tool_name="Broken Tool",
            description="",
            execution_code="async def execute() -> dict:\n    return {}",
            workflow_id="wf-1",
            status="published",
        )
    )

    payload = json.loads(
        assistant_tools.report_tool_bug_handler(
            "Broken Tool",
            "boom",
            user_input='{"x": 1}',
        )
    )

    assert payload["success"] is True
    assert payload["worker_notified"] is True
    assert notified == [True]

    port = _TaskPort()
    worker = AssistantTaskWorker(ToolRepository(), port.run_agent, port.start_triage)
    worker.process_pending_tasks()

    task = PendingTaskRepository().get_by_id(payload["task_id"])
    assert task.status == "completed"
    assert port.triage_calls == [("tool-1", "boom", "wf-1")]


def test_bug_task_without_workflow_is_marked_failed(in_memory_db):
    PendingTaskRepository().create(
        PendingAssistantTask(
            task_id="task-missing-workflow",
            task_type="fix_tool_bug",
            payload=json.dumps({"tool_id": "missing", "error_message": "boom"}),
            status="pending",
        )
    )

    port = _TaskPort()
    worker = AssistantTaskWorker(ToolRepository(), port.run_agent, port.start_triage)
    worker.process_pending_tasks()

    task = PendingTaskRepository().get_by_id("task-missing-workflow")
    assert task.status == "failed"
    assert port.triage_calls == []
