from __future__ import annotations

import queue
import threading

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
    def get_latest_display_sequence(self, session_id: str) -> int:
        return 0

    def get_display_messages_after(self, session_id: str, after_sequence: int) -> list:
        return []


class BlockingOrchestrator:
    task_worker = FakeTaskWorker()

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def run_agent(self, *args, **kwargs) -> AgentResult:
        self.calls += 1
        self.entered.set()
        self.release.wait(timeout=2)
        return AgentResult(result_type=ResultType.ERROR, error="stopped")


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


def test_assistant_runtime_only_starts_one_worker_per_session_under_race() -> None:
    orchestrator = BlockingOrchestrator()
    runtime = AssistantRuntime(
        orchestrator_factory=lambda: orchestrator,
        chat_service=FakeChatService(),
    )
    barrier = threading.Barrier(3)
    results: list[bool] = []

    def dispatch() -> None:
        barrier.wait()
        results.append(runtime.dispatch_message("ast-race", "hello"))

    callers = [threading.Thread(target=dispatch), threading.Thread(target=dispatch)]
    for caller in callers:
        caller.start()
    barrier.wait()
    for caller in callers:
        caller.join(timeout=1)

    assert sorted(results) == [False, True]
    assert orchestrator.entered.wait(timeout=1)
    assert orchestrator.calls == 1

    orchestrator.release.set()
    with runtime._workers_lock:
        worker = runtime._workers.get("ast-race")
    if worker is not None:
        worker.join(timeout=2)
