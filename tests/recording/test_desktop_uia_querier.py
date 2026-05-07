import time

from src.recording.desktop.uia_querier import UiaElementSummary, UiaQuerier


def test_uia_summary_serializes_expected_fields():
    summary = UiaElementSummary(name="保存", window_title="记事本", is_enabled=True)

    assert summary.to_dict()["name"] == "保存"
    assert summary.to_dict()["window_title"] == "记事本"


def test_uia_querier_degrades_without_throwing(monkeypatch):
    def fail_import(name, *args, **kwargs):
        if name == "uiautomation":
            raise ImportError("missing")
        return __import__(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fail_import)
    result = UiaQuerier().query_at(1, 2)

    assert result.degraded_reason == "ImportError"


def test_uia_querier_enforces_timeout_off_caller_thread(monkeypatch):
    querier = UiaQuerier()

    def slow_query(x, y):
        time.sleep(0.2)
        return UiaElementSummary(name="late")

    monkeypatch.setattr(querier, "_query_at_sync", slow_query)
    started_at = time.perf_counter()
    result = querier.query_at(1, 2, timeout_ms=10)
    elapsed = time.perf_counter() - started_at
    querier.close()

    assert result.degraded_reason == "timeout"
    assert elapsed < 0.2
