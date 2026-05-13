from __future__ import annotations

from src.desktop_api.orchestrator_runtime import DesktopAgentRuntime


def test_runtime_retry_teaching_failure_calls_retry_coordinator():
    calls: list[str] = []
    task_worker_starts: list[bool] = []

    class FakeTaskWorker:
        def start(self) -> None:
            task_worker_starts.append(True)

    class FakeRetryCoordinator:
        def retry_teaching(self, workflow_id: str) -> None:
            calls.append(workflow_id)

    class FakeOrchestrator:
        task_worker = FakeTaskWorker()
        retry_coordinator = FakeRetryCoordinator()

    runtime = DesktopAgentRuntime(orchestrator_factory=FakeOrchestrator)

    runtime._run_teaching_retry("wf_retry")

    assert task_worker_starts == [True]
    assert calls == ["wf_retry"]
