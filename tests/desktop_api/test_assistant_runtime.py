from __future__ import annotations

import queue

from src.business.agents.config import AgentResult, ResultType
from src.desktop_api.assistant_runtime import AssistantRuntime
from src.desktop_api.events import event_queue


class FakeTaskWorker:
    def start(self) -> None:
        pass


class FailingOrchestrator:
    task_worker = FakeTaskWorker()

    def run_agent(self, *args, **kwargs) -> AgentResult:
        return AgentResult(result_type=ResultType.ERROR, error="LLM 调用失败")


class FakeChatService:
    def get_display_messages_after(self, session_id: str, after_sequence: int) -> list:
        return []


def drain_events() -> None:
    while True:
        try:
            event_queue.queue.get_nowait()
        except queue.Empty:
            return


def test_assistant_runtime_does_not_publish_success_after_agent_error() -> None:
    drain_events()
    runtime = AssistantRuntime(
        orchestrator_factory=lambda: FailingOrchestrator(),
        chat_service=FakeChatService(),
    )

    runtime._run_assistant("ast_failure", "hello", 0)

    events = []
    while True:
        try:
            events.append(event_queue.queue.get_nowait())
        except queue.Empty:
            break

    assert ("assistant.progress", "succeeded") not in [
        (event.type, event.payload.get("status")) for event in events
    ]
    assert ("assistant.progress", "failed") in [
        (event.type, event.payload.get("status")) for event in events
    ]
