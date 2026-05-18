from __future__ import annotations

import asyncio
import queue
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.desktop_api.schemas import UiEvent
from src.utils import events as backend_events

EVENT_TYPE_MAP = {
    "agent_error": "assistant.error",
    "assistant_final_message": "assistant.message",
    "assistant_confirmation_requested": "assistant.confirmation",
    "requirement_confirmed": "teaching.progress",
    "code_completed": "teaching.progress",
    "review_passed": "teaching.progress",
    "review_failed": "teaching.progress",
    "recording_started": "recording.progress",
    "recording_stopped": "recording.progress",
    "recording_completed": "recording.progress",
    "desktop_action_count_changed": "recording.progress",
    "desktop_recording_degraded": "recording.progress",
    "desktop_recorder_start_failed": "recording.progress",
    "tool_saved": "skills.changed",
    "tool_published": "skills.changed",
    "skills_changed": "skills.changed",
    "composition_review_needed": "compositions.changed",
    "settings_changed": "settings.changed",
    "trial_requested": "trial.progress",
    "trial_success": "trial.progress",
    "trial_failed": "trial.progress",
    "teaching_failure_updated": "teaching.progress",
    "teaching_failure_resolved": "teaching.progress",
    "teaching_failure_retrying": "teaching.progress",
}


def _resolve_needs_user_input_event(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Route agent_needs_user_input to the correct frontend event type.

    PM and Trial agents route to teaching/trial progress so the
    teaching store picks them up.  Assistant and other types default to
    assistant.progress.
    """
    from src.business.agents.config import AgentType

    raw = payload.get("agent_type", "")
    agent_type: AgentType | None = None
    if isinstance(raw, AgentType):
        agent_type = raw
    elif isinstance(raw, str):
        try:
            agent_type = AgentType(raw)
        except ValueError:
            pass

    if agent_type == AgentType.PM:
        event_type = "teaching.progress"
    elif agent_type == AgentType.TRIAL:
        event_type = "trial.progress"
    else:
        event_type = "assistant.progress"

    # Map question to headline for frontend chat display
    question = payload.get("question")
    if question and isinstance(question, str):
        payload.setdefault("headline", question)

    return event_type, payload


@dataclass
class DesktopEventQueue:
    queue: queue.Queue[UiEvent] = field(default_factory=queue.Queue)

    async def publish(
        self, event_type: str, payload: dict, scope: dict[str, str] | None = None
    ) -> UiEvent:
        event = UiEvent(
            eventId=f"evt_{uuid4().hex[:12]}",
            type=event_type,
            scope=scope or {},
            payload=payload,
            createdAt=datetime.now(timezone.utc),
        )
        self.queue.put(event)
        return event

    def publish_nowait(
        self,
        event_type: str,
        payload: dict[str, Any],
        scope: dict[str, str] | None = None,
    ) -> UiEvent:
        event = UiEvent(
            eventId=f"evt_{uuid4().hex[:12]}",
            type=event_type,
            scope=scope or {},
            payload=payload,
            createdAt=datetime.now(timezone.utc),
        )
        self.queue.put_nowait(event)
        return event

    def is_healthy(self) -> bool:
        return self.queue is not None

    async def stream(self) -> AsyncIterator[UiEvent]:
        while True:
            try:
                yield await asyncio.to_thread(self.queue.get, True, 0.5)
            except queue.Empty:
                await asyncio.sleep(0)


event_queue = DesktopEventQueue()
_adapter_installed = False


def _scope_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    scope: dict[str, str] = {}
    for source_key, target_key in [
        ("session_id", "sessionId"),
        ("workflow_id", "workflowId"),
        ("recording_id", "workflowId"),
        ("tool_id", "toolId"),
        ("composition_id", "compositionId"),
    ]:
        value = payload.get(source_key)
        if value is not None:
            scope[target_key] = str(value)
    return scope


def install_blinker_event_adapter() -> None:
    global _adapter_installed
    if _adapter_installed:
        return

    def make_handler(signal_name: str):
        def handle_event(_sender: object, **kwargs: Any) -> None:
            event_name = str(kwargs.pop("event_name", signal_name))
            payload = dict(kwargs)
            payload.setdefault("sourceEvent", event_name)

            if event_name == "agent_needs_user_input":
                event_type, payload = _resolve_needs_user_input_event(payload)
            else:
                event_type = EVENT_TYPE_MAP.get(event_name, "backend.event")

            event_queue.publish_nowait(event_type, payload, _scope_from_payload(payload))

        return handle_event

    all_events = set(EVENT_TYPE_MAP) | {"agent_needs_user_input"}
    for event_name in all_events:
        backend_events.connect(event_name, make_handler(event_name), weak=False)
    _adapter_installed = True
