from __future__ import annotations

import asyncio
import queue
import threading

from src.desktop_api.events import event_queue, install_blinker_event_adapter
from src.utils.events import emit
from src.business.agents.config import AgentType


def drain_events() -> None:
    while True:
        try:
            event_queue.queue.get_nowait()
        except queue.Empty:
            return


def test_assistant_blinker_events_map_to_frontend_progress(desktop_api_client):
    drain_events()
    install_blinker_event_adapter()

    emit(
        "agent_needs_user_input",
        sender=None,
        session_id="ast_1",
        agent_type="assistant",
        question="Need more detail",
    )

    event = event_queue.queue.get_nowait()
    assert event.type == "assistant.progress"
    assert event.scope == {"sessionId": "ast_1"}
    assert event.payload["question"] == "Need more detail"


def test_assistant_event_stream_returns_stable_event_shape(desktop_api_client):
    drain_events()
    event_queue.publish_nowait(
        "assistant.confirmation",
        {
            "requestId": "req_1",
            "actionType": "exec",
            "sanitizedSummary": "命令首行: npm test",
            "status": "active",
        },
        {"sessionId": "ast_1"},
    )

    async def read_one():
        stream = event_queue.stream()
        return await asyncio.wait_for(anext(stream), timeout=1)

    event = asyncio.run(read_one())
    assert event.type == "assistant.confirmation"
    assert event.scope == {"sessionId": "ast_1"}
    assert event.payload["sanitizedSummary"] == "命令首行: npm test"


def test_event_queue_accepts_background_thread_publications(desktop_api_client):
    drain_events()

    worker = threading.Thread(
        target=lambda: event_queue.publish_nowait(
            "assistant.progress",
            {"status": "running"},
            {"sessionId": "ast_thread"},
        )
    )
    worker.start()
    worker.join(timeout=1)

    assert not worker.is_alive()
    event = event_queue.queue.get_nowait()
    assert event.type == "assistant.progress"
    assert event.scope == {"sessionId": "ast_thread"}


def test_pm_agent_needs_user_input_routes_to_teaching_progress(desktop_api_client):
    drain_events()
    install_blinker_event_adapter()

    emit(
        "agent_needs_user_input",
        sender=None,
        workflow_id="rec_abc123",
        agent_type=AgentType.PM,
        question="这个操作的目标是什么？",
    )

    event = event_queue.queue.get_nowait()
    assert event.type == "teaching.progress"
    assert event.scope == {"workflowId": "rec_abc123"}
    assert event.payload["headline"] == "这个操作的目标是什么？"
    assert event.payload["question"] == "这个操作的目标是什么？"
    assert event.payload["sourceEvent"] == "agent_needs_user_input"


def test_trial_agent_needs_user_input_routes_to_trial_progress(desktop_api_client):
    drain_events()
    install_blinker_event_adapter()

    emit(
        "agent_needs_user_input",
        sender=None,
        workflow_id="rec_xyz789",
        agent_type=AgentType.TRIAL,
        question="试用结果是否符合预期？",
    )

    event = event_queue.queue.get_nowait()
    assert event.type == "trial.progress"
    assert event.scope == {"workflowId": "rec_xyz789"}
    assert event.payload["headline"] == "试用结果是否符合预期？"


def test_needs_user_input_without_agent_type_defaults_to_assistant(desktop_api_client):
    drain_events()
    install_blinker_event_adapter()

    emit(
        "agent_needs_user_input",
        sender=None,
        workflow_id="rec_default",
        question="generic question",
    )

    event = event_queue.queue.get_nowait()
    assert event.type == "assistant.progress"
    assert event.payload["question"] == "generic question"
