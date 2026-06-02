from __future__ import annotations

import asyncio
import logging
import queue
import threading
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from src.desktop_api.schemas import UiEvent
from src.desktop_api.ui_event_projector import project_internal_event
from src.desktop_api.ui_event_types import UiEventDraft
from src.desktop_api.ui_events import (
    UiEventValidationError,
    build_ui_event,
    normalize_draft,
    trial_preview_manager,
)
from src.utils import events as backend_events

logger = logging.getLogger(__name__)

_REPLAY_BUFFER_SIZE = 256
_SUBSCRIBER_QUEUE_SIZE = 100
_RESYNC_DOMAINS = [
    "teaching",
    "tools",
    "compositions",
    "settings",
    "assistant",
    "brain",
    "skill",
]


@dataclass
class _Subscriber:
    subscriber_id: str
    queue: queue.Queue[UiEvent] = field(default_factory=lambda: queue.Queue(_SUBSCRIBER_QUEUE_SIZE))
    close_after_next_event: bool = False


class DesktopEventQueue:
    """Validated per-subscriber event hub for the desktop API event stream."""

    def __init__(self) -> None:
        self.queue: queue.Queue[UiEvent] = queue.Queue(maxsize=_REPLAY_BUFFER_SIZE)
        self.session_id = f"ui_sess_{uuid4().hex[:12]}"
        self._sequence = 0
        self._replay_buffer: deque[UiEvent] = deque(maxlen=_REPLAY_BUFFER_SIZE)
        self._non_replayable_sequences: deque[int] = deque(maxlen=_REPLAY_BUFFER_SIZE)
        # Deque and set must be kept in sync — see _remember_non_replayable_sequence_locked.
        self._non_replayable_sequence_set: set[int] = set()
        self._subscribers: dict[str, _Subscriber] = {}
        self._lock = threading.Lock()

    async def publish(
        self, event_type: str, payload: dict, scope: dict[str, str] | None = None
    ) -> UiEvent:
        return self.publish_nowait(event_type, payload, scope)

    def publish_nowait(
        self,
        event_type: str,
        payload: dict[str, Any],
        scope: dict[str, str] | None = None,
        causation_id: str | None = None,
    ) -> UiEvent:
        with self._lock:
            event = self._build_event_locked(event_type, payload, scope or {}, causation_id)
            terminal_drafts = self._publish_locked(event)
        self._publish_terminal_drafts(terminal_drafts)
        return event

    def _publish_terminal_drafts(self, drafts: list[UiEventDraft]) -> None:
        for draft in drafts:
            self.publish_draft_nowait(draft)

    def shutdown(self) -> None:
        terminal_drafts = trial_preview_manager.fail_pending("shutdown")
        self._publish_terminal_drafts(terminal_drafts)
        with self._lock:
            for subscriber in self._subscribers.values():
                subscriber.close_after_next_event = True

    def publish_draft_nowait(self, draft: UiEventDraft) -> UiEvent:
        normalized = normalize_draft(draft)
        return self.publish_nowait(
            normalized.event_type,
            normalized.payload,
            normalized.scope,
            normalized.causation_id,
        )

    def is_healthy(self) -> bool:
        return self.queue is not None

    async def stream(
        self,
        *,
        last_seen_sequence: int | None = None,
        event_session_id: str | None = None,
        force_resync_reason: str | None = None,
    ) -> AsyncIterator[UiEvent]:
        subscriber = self._subscribe(
            last_seen_sequence=last_seen_sequence,
            event_session_id=event_session_id,
            force_resync_reason=force_resync_reason,
        )
        try:
            while True:
                try:
                    event = await asyncio.to_thread(subscriber.queue.get, True, 0.5)
                except queue.Empty:
                    await asyncio.sleep(0)
                    continue
                yield event
                if subscriber.close_after_next_event:
                    break
        finally:
            terminal_drafts = self._unsubscribe(subscriber.subscriber_id)
            self._publish_terminal_drafts(terminal_drafts)

    def reset_for_tests(self) -> None:
        with self._lock:
            self.queue = queue.Queue(maxsize=_REPLAY_BUFFER_SIZE)
            self.session_id = f"ui_sess_{uuid4().hex[:12]}"
            self._sequence = 0
            self._replay_buffer.clear()
            self._non_replayable_sequences.clear()
            self._non_replayable_sequence_set.clear()
            self._subscribers.clear()
        trial_preview_manager.clear_for_tests()

    def _subscribe(
        self,
        *,
        last_seen_sequence: int | None,
        event_session_id: str | None,
        force_resync_reason: str | None = None,
    ) -> _Subscriber:
        subscriber = _Subscriber(subscriber_id=f"sub_{uuid4().hex[:12]}")
        with self._lock:
            self._subscribers[subscriber.subscriber_id] = subscriber
            if force_resync_reason:
                replay_events: list[UiEvent] = []
                resync_reason: str | None = force_resync_reason
            else:
                replay_events, resync_reason = self._replay_or_resync_locked(
                    last_seen_sequence=last_seen_sequence,
                    event_session_id=event_session_id,
                )
            if resync_reason is not None:
                subscriber.queue.put_nowait(
                    self._build_resync_event_locked(
                        reason=resync_reason,
                        domains=_RESYNC_DOMAINS,
                    )
                )
                subscriber.close_after_next_event = True
            elif len(replay_events) > _SUBSCRIBER_QUEUE_SIZE:
                subscriber.queue.put_nowait(
                    self._build_resync_event_locked(
                        reason="replay_overflow",
                        domains=_RESYNC_DOMAINS,
                    )
                )
                subscriber.close_after_next_event = True
            else:
                for event in replay_events:
                    subscriber.queue.put_nowait(event)
        return subscriber

    def _unsubscribe(self, subscriber_id: str) -> list[UiEventDraft]:
        with self._lock:
            self._subscribers.pop(subscriber_id, None)
            if self._subscribers:
                return []
            # fail_pending 在锁内调用，避免新订阅者在锁释放后加入时收到虚假拒绝事件
            return trial_preview_manager.fail_pending("disconnect")

    def _replay_or_resync_locked(
        self,
        *,
        last_seen_sequence: int | None,
        event_session_id: str | None,
    ) -> tuple[list[UiEvent], str | None]:
        if last_seen_sequence is None:
            return [], None
        if not event_session_id:
            return [], "invalid_cursor"
        if event_session_id != self.session_id:
            return [], "session_mismatch"
        if last_seen_sequence >= self._sequence:
            return [], None
        next_sequence = self._next_replayable_sequence_after_locked(last_seen_sequence)
        replay_events = [
            event for event in self._replay_buffer if event.sequence > last_seen_sequence
        ]
        if not replay_events:
            if next_sequence > self._sequence:
                return [], None
            return [], "replay_gap"
        if replay_events[0].sequence != next_sequence:
            return [], "replay_gap"
        return replay_events, None

    def _next_replayable_sequence_after_locked(self, sequence: int) -> int:
        expected = sequence + 1
        while expected in self._non_replayable_sequence_set:
            expected += 1
        return expected

    def _build_event_locked(
        self,
        event_type: str,
        payload: dict[str, Any],
        scope: dict[str, str],
        causation_id: str | None,
    ) -> UiEvent:
        self._sequence += 1
        return build_ui_event(
            event_type=event_type,
            payload=payload,
            scope=scope,
            sequence=self._sequence,
            session_id=self.session_id,
            causation_id=causation_id,
        )

    def _build_resync_event_locked(self, *, reason: str, domains: list[str]) -> UiEvent:
        self._sequence += 1
        sequence = self._sequence
        self._remember_non_replayable_sequence_locked(sequence)
        return build_ui_event(
            event_type="backend.resync_required",
            payload={
                "reason": reason,
                "domains": domains,
                "lastAvailableSequence": (
                    self._replay_buffer[0].sequence if self._replay_buffer else None
                ),
                "eventSessionId": self.session_id,
            },
            scope={},
            sequence=sequence,
            session_id=self.session_id,
            causation_id=None,
        )

    def _remember_non_replayable_sequence_locked(self, sequence: int) -> None:
        if (
            self._non_replayable_sequences.maxlen is not None
            and len(self._non_replayable_sequences) == self._non_replayable_sequences.maxlen
        ):
            dropped = self._non_replayable_sequences.popleft()
            self._non_replayable_sequence_set.discard(dropped)
        self._non_replayable_sequences.append(sequence)
        self._non_replayable_sequence_set.add(sequence)

    def _publish_locked(self, event: UiEvent) -> list[UiEventDraft]:
        terminal_drafts: list[UiEventDraft] = []
        self._replay_buffer.append(event)
        self._put_observer_event_locked(event)
        overflow_occurred = False
        for subscriber in list(self._subscribers.values()):
            if subscriber.close_after_next_event:
                continue
            try:
                subscriber.queue.put_nowait(event)
            except queue.Full:
                self._overflow_subscriber_locked(subscriber)
                overflow_occurred = True
        if overflow_occurred:
            terminal_drafts.extend(trial_preview_manager.fail_pending("overflow"))
        return terminal_drafts

    def _put_observer_event_locked(self, event: UiEvent) -> None:
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
        self.queue.put_nowait(event)

    def _overflow_subscriber_locked(self, subscriber: _Subscriber) -> None:
        while True:
            try:
                subscriber.queue.get_nowait()
            except queue.Empty:
                break
        subscriber.queue.put_nowait(
            self._build_resync_event_locked(
                reason="subscriber_overflow",
                domains=_RESYNC_DOMAINS,
            )
        )
        subscriber.close_after_next_event = True


event_queue = DesktopEventQueue()
_adapter_handlers: dict[str, Callable[..., Any]] = {}
_trial_preview_handler: Callable[..., Any] | None = None

_INTERNAL_EVENT_NAMES = [
    "agent_error",
    "agent_needs_user_input",
    "requirement_confirmed",
    "code_completed",
    "review_passed",
    "review_failed",
    "recording_started",
    "recording_stopped",
    "recording_completed",
    "desktop_action_count_changed",
    "desktop_recording_degraded",
    "desktop_recorder_start_failed",
    "desktop_trial_finished",
    "tool_saved",
    "tool_published",
    "tools_changed",
    "composition_review_needed",
    "settings_changed",
    "trial_requested",
    "trial_success",
    "trial_failed",
    "teaching_failure_updated",
    "teaching_failure_resolved",
    "teaching_failure_retrying",
    "brain_zone_changed",
    "brain_specialist_changed",
    "brain_specialist_recruited",
    "brain_context_ready",
    "brain_skill_changed",
    "brain_skill_equipment_changed",
    "brain_skill_supersede_completed",
    "brain_skill_bootstrap_fallback_used",
]


def _make_event_handler(signal_name: str) -> Callable[..., None]:
    def handle_event(_sender: object, **kwargs: Any) -> None:
        event_name = str(kwargs.pop("event_name", signal_name))
        payload = dict(kwargs)
        for draft in project_internal_event(event_name, payload):
            try:
                event_queue.publish_draft_nowait(draft)
            except UiEventValidationError as exc:
                logger.warning(
                    "Rejected unsafe UI event projection",
                    extra={"internal_event": event_name, "ui_event_type": draft.event_type},
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
                event_queue.publish_nowait(
                    "backend.resync_required",
                    {
                        "reason": "unsafe_projection_rejected",
                        "domains": _RESYNC_DOMAINS,
                        "eventSessionId": event_queue.session_id,
                    },
                )

    return handle_event


def _handle_trial_preview(_sender: object, **kwargs: Any) -> bool:
    kwargs.pop("event_name", None)
    workflow_id = str(kwargs.get("workflow_id") or "")
    trial_id = str(kwargs.get("trial_id") or "")
    if not workflow_id or not trial_id:
        logger.warning(
            "Rejected trial preview request without required identifiers",
            extra={
                "has_workflow_id": bool(workflow_id),
                "has_trial_id": bool(trial_id),
            },
        )
        return False
    return trial_preview_manager.create_request(
        workflow_id=workflow_id,
        trial_id=trial_id,
        code_preview=str(kwargs.get("code_preview") or ""),
        timeout_seconds=float(kwargs.get("timeout_seconds") or 30.0),
        publish=event_queue.publish_draft_nowait,
    )


def install_blinker_event_adapter() -> None:
    global _trial_preview_handler
    for event_name in _INTERNAL_EVENT_NAMES:
        handler = _adapter_handlers.get(event_name)
        if handler is None:
            handler = _make_event_handler(event_name)
            _adapter_handlers[event_name] = handler
        backend_events.connect(event_name, handler, weak=False)
    if _trial_preview_handler is None:
        _trial_preview_handler = _handle_trial_preview
    backend_events.connect("desktop_trial_preview_ready", _trial_preview_handler, weak=False)
