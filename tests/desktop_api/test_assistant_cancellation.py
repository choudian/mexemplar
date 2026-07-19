"""014 US1: AssistantRuntime.cancel_session + stop 端点 + pending 确认 fail-closed（行为契约）。"""

from __future__ import annotations

import queue
import threading
import time

from src.business.agents import run_context
from src.business.agents.config import AgentResult, ResultType
from src.business.agents.tools import builtin_general_tools as general_tools
from src.desktop_api.assistant_runtime import AssistantRuntime
from src.desktop_api.confirmations import install_confirmation_signal
from src.desktop_api.events import event_queue
from src.desktop_api import assistant_runtime as assistant_runtime_module
from src.desktop_api.routers import assistant as assistant_router


class FakeTaskWorker:
    def start(self) -> None:
        pass


class FakeChatService:
    def get_latest_display_sequence(self, session_id: str) -> int:
        return 0

    def get_display_messages_after(self, session_id: str, after_sequence: int) -> list:
        return []


class CancellableOrchestrator:
    """模拟协作式 loop：run_agent 在 worker 线程内轮询 run_context 的 cancel_event。"""

    task_worker = FakeTaskWorker()

    def set_parent_reentry_callback(self, callback) -> None:
        self.parent_reentry_callback = callback

    def __init__(self) -> None:
        self.entered = threading.Event()

    def run_agent(self, *args, **kwargs) -> AgentResult:
        self.entered.set()
        run_ctx = run_context.get_current()
        for _ in range(300):
            if run_ctx is not None and run_ctx.cancel_event.is_set():
                return AgentResult(result_type=ResultType.CANCELLED)
            time.sleep(0.01)
        return AgentResult(result_type=ResultType.COMPLETED)


class TwoRunOrchestrator:
    """第一轮快速完成；第二轮保持运行，用于验证旧 runId 不误停新运行。"""

    task_worker = FakeTaskWorker()

    def set_parent_reentry_callback(self, callback) -> None:
        self.parent_reentry_callback = callback

    def __init__(self) -> None:
        self.calls = 0
        self.first_entered = threading.Event()
        self.second_entered = threading.Event()
        self.release_second = threading.Event()
        self.second_context: run_context.RunContext | None = None

    def run_agent(self, *args, **kwargs) -> AgentResult:
        self.calls += 1
        if self.calls == 1:
            self.first_entered.set()
            return AgentResult(result_type=ResultType.COMPLETED)

        self.second_context = run_context.get_current()
        self.second_entered.set()
        while not self.release_second.is_set():
            if self.second_context is not None and self.second_context.cancel_event.is_set():
                return AgentResult(result_type=ResultType.CANCELLED)
            time.sleep(0.01)
        return AgentResult(result_type=ResultType.COMPLETED)


def _drain_events() -> None:
    while True:
        try:
            event_queue.queue.get_nowait()
        except queue.Empty:
            return


def _collect_events() -> list:
    events = []
    while True:
        try:
            events.append(event_queue.queue.get_nowait())
        except queue.Empty:
            return events


def test_cancel_session_running_turn_emits_cancelled_progress() -> None:
    run_context.reset_for_tests()
    _drain_events()
    orch = CancellableOrchestrator()
    runtime = AssistantRuntime(orchestrator_factory=lambda: orch, chat_service=FakeChatService())
    assert runtime.dispatch_message("sess-stop", "hello") is True
    assert orch.entered.wait(timeout=2)

    accepted = runtime.cancel_session("sess-stop")
    assert accepted is True

    with runtime._workers_lock:
        worker = runtime._workers.get("sess-stop")
    if worker is not None:
        worker.join(timeout=2)

    statuses = [(event.type, event.payload.get("status")) for event in _collect_events()]
    assert ("assistant.progress", "cancelled") in statuses
    assert ("assistant.progress", "succeeded") not in statuses
    run_context.reset_for_tests()


def test_cancel_session_settles_scheduling_confirmation(monkeypatch) -> None:
    """033 FR-006：停止主助理回合同时结算该会话的创建确认卡。"""
    run_context.reset_for_tests()
    settled: list[str] = []
    monkeypatch.setattr(
        assistant_runtime_module,
        "settle_scheduling_confirmations_for_session_stopped",
        lambda session_id: settled.append(session_id),
    )
    orch = CancellableOrchestrator()
    runtime = AssistantRuntime(orchestrator_factory=lambda: orch, chat_service=FakeChatService())
    assert runtime.dispatch_message("sess-scheduling-stop", "hello") is True
    assert orch.entered.wait(timeout=2)

    assert runtime.cancel_session("sess-scheduling-stop") is True

    with runtime._workers_lock:
        worker = runtime._workers.get("sess-scheduling-stop")
    if worker is not None:
        worker.join(timeout=2)
    assert settled == ["sess-scheduling-stop"]
    run_context.reset_for_tests()


def test_cancel_session_without_running_turn_returns_false() -> None:
    run_context.reset_for_tests()
    runtime = AssistantRuntime(
        orchestrator_factory=lambda: CancellableOrchestrator(),
        chat_service=FakeChatService(),
    )
    assert runtime.cancel_session("never-ran") is False
    run_context.reset_for_tests()


def test_stale_stop_run_id_does_not_cancel_new_turn() -> None:
    run_context.reset_for_tests()
    _drain_events()
    orch = TwoRunOrchestrator()
    runtime = AssistantRuntime(orchestrator_factory=lambda: orch, chat_service=FakeChatService())

    assert runtime.dispatch_message("sess-reuse", "first") is True
    assert orch.first_entered.wait(timeout=2)
    with runtime._workers_lock:
        worker = runtime._workers.get("sess-reuse")
    if worker is not None:
        worker.join(timeout=2)

    first_run_id = next(
        event.payload.get("runId")
        for event in _collect_events()
        if event.type == "assistant.progress"
        and event.payload.get("status") == "running"
        and event.payload.get("runId")
    )

    assert runtime.dispatch_message("sess-reuse", "second") is True
    assert orch.second_entered.wait(timeout=2)
    assert orch.second_context is not None
    assert orch.second_context.run_id != first_run_id

    assert runtime.cancel_session("sess-reuse", run_id=str(first_run_id)) is False
    assert orch.second_context.cancel_event.is_set() is False

    orch.release_second.set()
    with runtime._workers_lock:
        worker = runtime._workers.get("sess-reuse")
    if worker is not None:
        worker.join(timeout=2)
    statuses = [(event.type, event.payload.get("status")) for event in _collect_events()]
    assert ("assistant.progress", "cancelled") not in statuses
    run_context.reset_for_tests()


def test_stop_endpoint_reports_accepted_flag(desktop_api_client) -> None:
    class FakeRuntime:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []
            self.accepted = True

        def cancel_session(self, session_id: str, run_id: str | None = None) -> bool:
            self.calls.append((session_id, run_id))
            return self.accepted

    fake = FakeRuntime()
    desktop_api_client.app.dependency_overrides[assistant_router.get_assistant_runtime] = (
        lambda: fake
    )
    try:
        running = desktop_api_client.post("/api/assistant/sessions/sess-x/stop")
        fake.accepted = False
        idle = desktop_api_client.post(
            "/api/assistant/sessions/sess-x/stop",
            json={"runId": "run-old"},
        )
    finally:
        desktop_api_client.app.dependency_overrides.clear()

    assert running.status_code == 200
    assert running.json() == {"accepted": True}
    assert idle.json() == {"accepted": False}
    assert fake.calls == [("sess-x", None), ("sess-x", "run-old")]


def test_cancel_fail_closes_pending_confirmation() -> None:
    """T011a：回合阻塞在高危确认等待中点停止 → 该确认 fail-closed 当拒绝并唤醒回合 → CANCELLED。

    同时验证 CC-001 同步确认协议 first-decision-wins 不回归：被 fail-closed 的请求记为拒绝、
    已决策的请求不会被二次改写。
    """
    run_context.reset_for_tests()
    general_tools.reset_confirmation_state_for_tests()
    install_confirmation_signal()
    _drain_events()

    confirm_outcome: dict = {}
    entered = threading.Event()

    class ConfirmingOrchestrator:
        task_worker = FakeTaskWorker()

        def set_parent_reentry_callback(self, callback) -> None:
            self.parent_reentry_callback = callback

        def run_agent(self, *args, **kwargs) -> AgentResult:
            entered.set()
            # 模拟高危工具阻塞在确认等待中（worker 线程内，归属当前 run_context 会话）。
            # 走真实 _ask_user_confirm，由 run_context 捕获会话归属。
            confirm_outcome["approved"] = general_tools._ask_user_confirm(
                "rm -rf /", tool_name="exec"
            )
            run_ctx = run_context.get_current()
            if run_ctx is not None and run_ctx.cancel_event.is_set():
                return AgentResult(result_type=ResultType.CANCELLED)
            return AgentResult(result_type=ResultType.COMPLETED)

    runtime = AssistantRuntime(
        orchestrator_factory=lambda: ConfirmingOrchestrator(),
        chat_service=FakeChatService(),
    )
    try:
        assert runtime.dispatch_message("sess-confirm", "do dangerous") is True
        assert entered.wait(timeout=2)
        # 等确认请求真正登记（worker 进入 _ask_user_confirm 的 event.wait）
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with general_tools._confirm_lock:
                pending_for_session = [
                    p
                    for p in general_tools._pending_confirms.values()
                    if (p.session_id or "") == "sess-confirm" and not p.event.is_set()
                ]
            if pending_for_session:
                break
            time.sleep(0.01)
        assert pending_for_session, "高危确认未按会话归属登记"

        accepted = runtime.cancel_session("sess-confirm")
        assert accepted is True

        with runtime._workers_lock:
            worker = runtime._workers.get("sess-confirm")
        if worker is not None:
            worker.join(timeout=2)

        # 确认被 fail-closed 当拒绝（FR-006b），回合到取消检查点退出
        assert confirm_outcome.get("approved") is False
        statuses = [(event.type, event.payload.get("status")) for event in _collect_events()]
        assert ("assistant.progress", "cancelled") in statuses
    finally:
        general_tools.reset_confirmation_state_for_tests()
        run_context.reset_for_tests()
