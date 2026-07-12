from __future__ import annotations

import time

import pytest

from src.business.brain import background_worker as worker_module
from src.business.brain.background_worker import BrainBackgroundWorker


class _Config:
    def get_brain_worker_tick_interval(self) -> float:
        return 0.01


@pytest.fixture(autouse=True)
def _reset_worker_globals():
    yield
    event = worker_module._brain_worker_event
    thread = worker_module._brain_worker_thread
    if event is not None:
        event.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=1)
    worker_module._brain_worker_running = False
    worker_module._brain_worker_event = None
    worker_module._brain_worker_thread = None
    worker_module._brain_worker_notify = None


def _replace_jobs(worker: BrainBackgroundWorker, calls: list[str]) -> None:
    for name in (
        "_process_pending_segments",
        "_recover_crashed_segments",
        "_run_decay_sweep",
        "_run_archive_layering",
        "_run_prediction_jobs",
        "_run_subconscious_distillation",
        "_run_invalidation_review",
        "_run_recruitment_scan",
        "_run_execution_review",
    ):
        setattr(worker, name, lambda name=name: calls.append(name))


def test_worker_llm_client_uses_configured_temperature(monkeypatch) -> None:
    import src.business.ai.llm_client as llm_client_module

    captured: dict[str, object] = {}

    class Config:
        def get_ai_provider(self) -> str:
            return "openai"

        def get_ai_model(self) -> str:
            return "background-model"

        def get_ai_api_key(self):
            return None

        def get_ai_base_url(self):
            return None

        def get_ai_temperature(self) -> float:
            return 0.35

        def get_ai_max_tokens(self) -> int:
            return 256

        def get_ai_thinking_level(self) -> str:
            return "off"

        def get_ai_request_timeout(self) -> float:
            return 12.0

    class FakeLLM:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.delenv("MEXEMPLAR_REAL_GRAND_TOUR", raising=False)
    monkeypatch.setattr(llm_client_module, "LangChainLLMClient", FakeLLM)

    client = BrainBackgroundWorker(config=Config())._get_llm_client()

    assert isinstance(client, FakeLLM)
    assert captured["temperature"] == 0.35


def test_worker_loop_runs_maintenance_jobs_in_order() -> None:
    worker = BrainBackgroundWorker(config=_Config())
    calls: list[str] = []
    _replace_jobs(worker, calls)
    worker._tick_event.wait = lambda timeout: worker._stop_event.set()

    worker._worker_loop()

    assert calls == [
        "_process_pending_segments",
        "_recover_crashed_segments",
        "_run_decay_sweep",
        "_run_archive_layering",
        "_run_prediction_jobs",
        "_run_subconscious_distillation",
        "_run_invalidation_review",
        "_run_recruitment_scan",
        "_run_execution_review",
    ]


def test_worker_loop_retries_after_tick_failure() -> None:
    """job 级别异常不应停止同一 tick 内的其他 job；部分失败不累计 _consecutive_tick_errors。"""
    worker = BrainBackgroundWorker(config=_Config())
    calls: list[str] = []
    wait_count = 0

    def process_pending() -> None:
        calls.append("_process_pending_segments")
        if calls.count("_process_pending_segments") == 1:
            raise RuntimeError("transient failure")

    def wait_for_next_tick(timeout: float) -> None:
        nonlocal wait_count
        wait_count += 1
        if wait_count == 2:
            worker._stop_event.set()

    _replace_jobs(worker, calls)
    worker._process_pending_segments = process_pending
    worker._tick_event.wait = wait_for_next_tick

    worker._worker_loop()

    all_jobs = [
        "_process_pending_segments",
        "_recover_crashed_segments",
        "_run_decay_sweep",
        "_run_archive_layering",
        "_run_prediction_jobs",
        "_run_subconscious_distillation",
        "_run_invalidation_review",
        "_run_recruitment_scan",
        "_run_execution_review",
    ]
    # tick 1: 所有 job 均运行（process_pending 失败但不中断其余 job）
    # tick 2: 所有 job 均成功
    assert calls == all_jobs + all_jobs
    # 部分失败（<全部 job）不累计连续失败计数，两 tick 后计数仍为 0
    assert worker._consecutive_tick_errors == 0


def test_start_and_stop_manage_worker_thread(monkeypatch) -> None:
    monkeypatch.setattr(worker_module, "connect", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker_module, "disconnect", lambda *_args, **_kwargs: None)
    worker = BrainBackgroundWorker(config=_Config())
    _replace_jobs(worker, [])

    worker.start()
    deadline = time.monotonic() + 1
    while not worker._running and time.monotonic() < deadline:
        time.sleep(0.01)

    assert worker._running is True
    assert worker_module._brain_worker_running is True
    assert worker_module._brain_worker_event is worker._tick_event
    assert worker_module._brain_worker_thread is worker._thread

    worker.stop()

    assert worker._thread is not None
    assert worker._thread.is_alive() is False
    assert worker._running is False
    assert worker_module._brain_worker_running is False
    assert worker_module._brain_worker_event is None
    assert worker_module._brain_worker_thread is None


def test_start_resets_consecutive_tick_errors(monkeypatch) -> None:
    monkeypatch.setattr(worker_module, "connect", lambda *_args, **_kwargs: None)

    class FakeThread:
        def __init__(self, *args, **kwargs) -> None:
            self.started = False

        def start(self) -> None:
            self.started = True

        def is_alive(self) -> bool:
            return False

        def join(self, timeout=None) -> None:
            return None

    monkeypatch.setattr(worker_module.threading, "Thread", FakeThread)
    worker = BrainBackgroundWorker(config=_Config())
    worker._consecutive_tick_errors = 9

    worker.start()

    assert worker._consecutive_tick_errors == 0
