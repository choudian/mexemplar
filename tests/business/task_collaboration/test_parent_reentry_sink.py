"""ParentReentrySink graph_completed 去重测试（C1 配套）。

含失败图 root 不收口时，重复 ``_advance`` 触发 ``notify_graph_complete`` 不能堆积
``graph_completed`` 条目（否则反复唤醒主助理、污染 briefing、re_enqueue 永不清除）。
graph 级去重：未消费的同图完成通知只入队一次；drain 清空后允许再次通知。
"""

from __future__ import annotations

from src.business.task_collaboration.parent_reentry_sink import ParentReentrySink


def _make_sink(*, active=False, kick_result=True) -> ParentReentrySink:
    return ParentReentrySink(
        has_active_worker=lambda _session_id: active,
        kick_reentry_run=lambda _session_id, _graph_id: kick_result,
    )


def _graph_completed(entries: list[dict]) -> list[dict]:
    return [e for e in entries if e.get("event") == "graph_completed"]


def test_notify_graph_complete_dedupes_while_undrained():
    """同图未 drain 的重复完成通知不堆积。"""
    sink = _make_sink()
    sink.notify_graph_complete("g1", "s1")
    sink.notify_graph_complete("g1", "s1")
    sink.notify_graph_complete("g1", "s1")

    assert len(_graph_completed(sink.drain("s1"))) == 1


def test_notify_graph_complete_allowed_again_after_drain():
    """drain 清空后允许再次通知（主助理裁定 returned 图重跑后再次全终态）。"""
    sink = _make_sink()
    sink.notify_graph_complete("g1", "s1")
    sink.drain("s1")

    sink.notify_graph_complete("g1", "s1")
    assert len(_graph_completed(sink.drain("s1"))) == 1


def test_notify_graph_complete_independent_per_graph():
    """不同图的完成通知互不去重。"""
    sink = _make_sink()
    sink.notify_graph_complete("g1", "s1")
    sink.notify_graph_complete("g2", "s1")

    completed = _graph_completed(sink.drain("s1"))
    assert {e["graphId"] for e in completed} == {"g1", "g2"}


def test_drain_is_scoped_to_one_graph_inside_reused_session():
    sink = _make_sink(active=True)
    sink.dispatch({"sessionId": "s1", "graphId": "g1", "taskId": "t1"})
    sink.dispatch({"sessionId": "s1", "graphId": "g2", "taskId": "t2"})

    first_graph = sink.drain("s1", "g1")

    assert [entry["taskId"] for entry in first_graph] == ["t1"]
    assert sink.has_pending("s1", "g1") is False
    assert sink.has_pending("s1", "g2") is True
    assert [entry["taskId"] for entry in sink.drain("s1", "g2")] == ["t2"]


def test_notify_graph_complete_skips_missing_ids():
    """缺 session/graph 的完成通知被丢弃，不入队（与 dispatch 一致语义）。"""
    sink = _make_sink()
    sink.notify_graph_complete("", "s1")
    sink.notify_graph_complete("g1", "")

    assert sink.drain("s1") == []
    assert sink.has_pending("s1") is False


# === I18-7: dispatch payload validation ===


class TestDispatchPayloadValidation:
    """I18-7: dispatch with missing required fields → payload dropped, no kick."""

    def test_dispatch_missing_session_id_drops_payload(self):
        """dispatch with missing sessionId → payload dropped, no kick, nothing queued."""
        kick_calls: list[tuple[str, str]] = []

        def track_kick(session_id: str, graph_id: str) -> bool:
            kick_calls.append((session_id, graph_id))
            return True

        sink = ParentReentrySink(
            has_active_worker=lambda _sid: False,
            kick_reentry_run=track_kick,
        )
        sink.dispatch({"graphId": "g1", "taskId": "t1"})

        assert kick_calls == []
        assert sink.drain("s1") == []

    def test_dispatch_missing_graph_id_drops_payload(self):
        """dispatch with missing graphId → payload dropped, no kick, nothing queued."""
        kick_calls: list[tuple[str, str]] = []

        def track_kick(session_id: str, graph_id: str) -> bool:
            kick_calls.append((session_id, graph_id))
            return True

        sink = ParentReentrySink(
            has_active_worker=lambda _sid: False,
            kick_reentry_run=track_kick,
        )
        sink.dispatch({"sessionId": "s1", "taskId": "t1"})

        assert kick_calls == []
        assert sink.drain("s1") == []

    def test_dispatch_empty_dict_drops_payload(self):
        """dispatch with empty dict → payload dropped, no kick, nothing queued."""
        kick_calls: list[tuple[str, str]] = []

        def track_kick(session_id: str, graph_id: str) -> bool:
            kick_calls.append((session_id, graph_id))
            return True

        sink = ParentReentrySink(
            has_active_worker=lambda _sid: False,
            kick_reentry_run=track_kick,
        )
        sink.dispatch({})

        assert kick_calls == []
        assert sink.drain("s1") == []
