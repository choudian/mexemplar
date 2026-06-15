from __future__ import annotations

import queue
import threading

import pytest

from src.business.agents.config import AgentResult, ResultType
from src.business.agents.config import AgentType
from src.business.services.assistant_failure_service import AssistantFailureService
from src.data.models_sqlite import Message, Session
from src.data.repos import AssistantRunFailureRepository, MessageRepository, SessionRepository
from src.desktop_api.assistant_runtime import (
    AssistantRuntime,
    ContinueSubagentDirective,
    RetryDirective,
)
from src.desktop_api.events import event_queue


class FakeTaskWorker:
    def start(self) -> None:
        pass


class FailingOrchestrator:
    task_worker = FakeTaskWorker()

    def run_agent(self, *args, **kwargs) -> AgentResult:
        return AgentResult(result_type=ResultType.ERROR, error="LLM 调用失败")


class CompletingOrchestrator:
    task_worker = FakeTaskWorker()

    def run_agent(self, *args, **kwargs) -> AgentResult:
        return AgentResult(result_type=ResultType.COMPLETED)


class ResultOrchestrator:
    task_worker = FakeTaskWorker()

    def __init__(self, result: AgentResult) -> None:
        self.result = result

    def run_agent(self, *args, **kwargs) -> AgentResult:
        return self.result


class RecordingOrchestrator:
    task_worker = FakeTaskWorker()

    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    def run_agent(self, *args, **kwargs) -> AgentResult:
        self.calls.append((args, kwargs))
        return AgentResult(result_type=ResultType.COMPLETED)


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


class PersistingFailOrchestrator:
    task_worker = FakeTaskWorker()

    def __init__(self, *, edited: bool = False) -> None:
        self.edited = edited

    def run_agent(self, _agent_type, content, *, session_id, **_kwargs) -> AgentResult:
        if self.edited:
            MessageRepository().create(
                Message(
                    message_id="msg_edited_retry",
                    session_id=session_id,
                    sequence=MessageRepository().get_next_sequence(session_id),
                    role="user",
                    content=content,
                )
            )
        elif MessageRepository().get_last(session_id) is None:
            MessageRepository().create(
                Message(
                    message_id="msg_initial_failure",
                    session_id=session_id,
                    sequence=1,
                    role="user",
                    content=content,
                )
            )
        return AgentResult(result_type=ResultType.ERROR, error="timeout secret response")


class RetryCompletingOrchestrator:
    task_worker = FakeTaskWorker()

    def __init__(self) -> None:
        self.kwargs: dict | None = None

    def run_agent(self, _agent_type, _content, *, session_id, **kwargs) -> AgentResult:
        self.kwargs = kwargs
        MessageRepository().create(
            Message(
                message_id="msg_retry_answer",
                session_id=session_id,
                sequence=MessageRepository().get_next_sequence(session_id),
                role="assistant",
                content="done",
            )
        )
        return AgentResult(result_type=ResultType.COMPLETED)


def seed_assistant_session(session_id: str, *, with_message: bool = False) -> None:
    SessionRepository().create(
        Session(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    if with_message:
        MessageRepository().create(
            Message(
                message_id=f"msg_{session_id}",
                session_id=session_id,
                sequence=1,
                role="user",
                content="original",
            )
        )


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


def test_continue_subagent_request_emits_fallback_when_main_assistant_does_not_resume(
    monkeypatch,
) -> None:
    class FakeObservability:
        def continue_subagent_started(self, *args, **kwargs) -> bool:
            return False

    monkeypatch.setattr(
        "src.business.agents.observability.AssistantObservability",
        FakeObservability,
    )
    drain_events()
    runtime = AssistantRuntime(
        orchestrator_factory=lambda: CompletingOrchestrator(),
        chat_service=FakeChatService(),
    )

    runtime._run_assistant(
        "ast_continue",
        "继续任务",
        0,
        ContinueSubagentDirective(
            subagent_id="sub_1",
            initial_return_transition_count=2,
        ),
    )

    events = []
    while True:
        try:
            events.append(event_queue.queue.get_nowait())
        except queue.Empty:
            break

    assert ("assistant.progress", "succeeded") in [
        (event.type, event.payload.get("status")) for event in events
    ]
    assert ("assistant.error", "continue_subagent_not_started") in [
        (event.type, event.payload.get("type")) for event in events
    ]


def test_runtime_passes_structured_continue_intent_to_orchestrator(monkeypatch) -> None:
    class FakeObservability:
        def continue_subagent_started(self, *args, **kwargs) -> bool:
            return True

    monkeypatch.setattr(
        "src.business.agents.observability.AssistantObservability",
        FakeObservability,
    )
    orchestrator = RecordingOrchestrator()
    runtime = AssistantRuntime(
        orchestrator_factory=lambda: orchestrator,
        chat_service=FakeChatService(),
    )

    runtime._run_assistant(
        "ast_continue_structured",
        "请继续任务",
        0,
        ContinueSubagentDirective(
            subagent_id="sub_1",
            supplemental="补充",
            initial_return_transition_count=0,
        ),
    )

    assert orchestrator.calls
    _, kwargs = orchestrator.calls[0]
    assert kwargs["assistant_continue_intent"] == {
        "subagent_id": "sub_1",
        "instruction": "补充",
    }


def test_runtime_rejects_foreign_subagent_transcript(monkeypatch) -> None:
    class FakeObservability:
        def find_subagent_summary(self, parent_session_id: str, subagent_id: str):
            return None

        def build_transcript(self, *args, **kwargs):
            raise AssertionError("foreign transcript should not be read")

    monkeypatch.setattr(
        "src.business.agents.observability.AssistantObservability",
        FakeObservability,
    )
    runtime = AssistantRuntime(
        orchestrator_factory=lambda: CompletingOrchestrator(),
        chat_service=FakeChatService(),
    )

    with pytest.raises(LookupError):
        runtime.get_transcript("parent", "foreign")


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


def test_terminal_failure_persists_then_publishes_user_message_before_failed_progress() -> None:
    drain_events()
    seed_assistant_session("ast_order")
    runtime = AssistantRuntime(orchestrator_factory=lambda: PersistingFailOrchestrator())

    runtime._run_assistant("ast_order", "hello", 0)

    events = []
    while True:
        try:
            events.append(event_queue.queue.get_nowait())
        except queue.Empty:
            break
    relevant = [
        event
        for event in events
        if event.type in ("assistant.message", "assistant.progress")
        and event.payload.get("status") != "running"
    ]

    assert relevant[0].type == "assistant.message"
    assert relevant[0].payload["role"] == "user"
    assert relevant[0].payload["failure"]["category"] == "network"
    assert "secret" not in str(relevant[0].payload)
    assert relevant[-1].type == "assistant.progress"
    assert relevant[-1].payload["status"] == "failed"
    assert AssistantRunFailureRepository().get_current("ast_order") is not None


def test_original_retry_reuses_user_message_and_resolves_failure() -> None:
    drain_events()
    seed_assistant_session("ast_retry_success", with_message=True)
    service = AssistantFailureService()
    service.record_terminal_failure(
        session_id="ast_retry_success",
        message_sequence=1,
        error="timeout",
    )
    prep = service.prepare_retry("ast_retry_success", 1, None)
    orchestrator = RetryCompletingOrchestrator()
    runtime = AssistantRuntime(
        orchestrator_factory=lambda: orchestrator,
        failure_service=service,
    )

    runtime._run_assistant(
        "ast_retry_success",
        prep.content,
        1,
        retry_directive=RetryDirective(
            failure_id=prep.failure_id,
            source_message_sequence=1,
            reuse_user_message=True,
        ),
    )

    assert orchestrator.kwargs is not None
    assert orchestrator.kwargs["assistant_reuse_user_message"] is True
    assert [m.role for m in MessageRepository().get_all("ast_retry_success")].count("user") == 1
    assert AssistantRunFailureRepository().get_current("ast_retry_success") is None


def test_cancelled_retry_restores_failure_to_actionable_state() -> None:
    drain_events()
    seed_assistant_session("ast_retry_cancelled", with_message=True)
    service = AssistantFailureService()
    service.record_terminal_failure(
        session_id="ast_retry_cancelled",
        message_sequence=1,
        error="timeout",
    )
    prep = service.prepare_retry("ast_retry_cancelled", 1, None)
    runtime = AssistantRuntime(
        orchestrator_factory=lambda: ResultOrchestrator(
            AgentResult(result_type=ResultType.CANCELLED)
        ),
        failure_service=service,
    )

    runtime._run_assistant(
        "ast_retry_cancelled",
        prep.content,
        1,
        retry_directive=RetryDirective(
            failure_id=prep.failure_id,
            source_message_sequence=1,
            reuse_user_message=True,
        ),
    )

    current = AssistantRunFailureRepository().get_current("ast_retry_cancelled")
    assert current is not None
    assert current.status == "failed"
    assert current.attempt_count == 2


def test_retry_waiting_for_user_resolves_source_failure() -> None:
    drain_events()
    seed_assistant_session("ast_retry_waiting", with_message=True)
    service = AssistantFailureService()
    service.record_terminal_failure(
        session_id="ast_retry_waiting",
        message_sequence=1,
        error="timeout",
    )
    prep = service.prepare_retry("ast_retry_waiting", 1, None)
    runtime = AssistantRuntime(
        orchestrator_factory=lambda: ResultOrchestrator(
            AgentResult(
                result_type=ResultType.NEEDS_USER_INPUT,
                question="请补充范围",
            )
        ),
        failure_service=service,
    )

    runtime._run_assistant(
        "ast_retry_waiting",
        prep.content,
        1,
        retry_directive=RetryDirective(
            failure_id=prep.failure_id,
            source_message_sequence=1,
            reuse_user_message=True,
        ),
    )

    assert AssistantRunFailureRepository().get_current("ast_retry_waiting") is None


def test_edited_retry_failure_moves_card_to_new_user_message() -> None:
    drain_events()
    seed_assistant_session("ast_retry_edited", with_message=True)
    service = AssistantFailureService()
    service.record_terminal_failure(
        session_id="ast_retry_edited",
        message_sequence=1,
        error="timeout",
    )
    prep = service.prepare_retry("ast_retry_edited", 1, "edited request")
    runtime = AssistantRuntime(
        orchestrator_factory=lambda: PersistingFailOrchestrator(edited=True),
        failure_service=service,
    )

    runtime._run_assistant(
        "ast_retry_edited",
        prep.content,
        1,
        retry_directive=RetryDirective(
            failure_id=prep.failure_id,
            source_message_sequence=1,
            reuse_user_message=False,
        ),
    )

    current = AssistantRunFailureRepository().get_current("ast_retry_edited")
    assert current is not None
    assert current.message_sequence == 2
    assert current.attempt_count == 2
    messages = [
        event.payload
        for event in list(event_queue.queue.queue)
        if event.type == "assistant.message"
    ]
    assert any(item["sequence"] == 1 and "failure" not in item for item in messages)
    assert any(item["sequence"] == 2 and "failure" in item for item in messages)
