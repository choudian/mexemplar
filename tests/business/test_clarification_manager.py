"""clarification_manager 单元测试（019）。

覆盖：输入校验、单选/多选/其他、answered/cancelled、超时、停止、关闭、
first-decision-wins 并发、signal 未注册、emit 异常、归属校验。
"""

import threading
import time

import pytest

import src.business.agents.tools.clarification_manager as cm


@pytest.fixture(autouse=True)
def reset_state():
    cm.reset_clarification_state_for_tests()
    yield
    cm.reset_clarification_state_for_tests()


class FakeSignal:
    def __init__(self):
        self.requested = []
        self.resolved = []

    def emit_requested(self, request_id):
        self.requested.append(request_id)

    def emit_resolved(self, request_id):
        p = cm.get_pending(request_id)
        self.resolved.append((request_id, p.status if p else None))


def _questions(multi=False):
    return [
        {
            "question": "选择执行方式？",
            "header": "执行方式",
            "multiSelect": multi,
            "options": [{"label": "按顺序"}, {"label": "并行"}],
        }
    ]


def _run_async(session_id="s1", questions=None):
    """在后台线程发起阻塞澄清，返回 (thread, result_holder)。"""
    holder = {}

    def worker():
        holder["result"] = cm.ask_user_question(questions or _questions(), session_id=session_id)

    t = threading.Thread(target=worker)
    t.start()
    # 等 pending 注册
    for _ in range(100):
        if cm.get_pending_for_session(session_id) is not None:
            break
        time.sleep(0.005)
    return t, holder


# ===== 输入校验 =====


def test_validation_question_count():
    sig = FakeSignal()
    cm.register_clarification_signal(sig)
    with pytest.raises(cm.ClarificationValidationError):
        cm.validate_and_normalize_questions([])
    with pytest.raises(cm.ClarificationValidationError):
        cm.validate_and_normalize_questions([_questions()[0]] * 5)


def test_validation_option_count_and_required():
    with pytest.raises(cm.ClarificationValidationError):
        cm.validate_and_normalize_questions([{"question": "q", "header": "h", "options": [{"label": "a"}]}])
    with pytest.raises(cm.ClarificationValidationError):
        cm.validate_and_normalize_questions([{"question": "", "header": "h", "options": [{"label": "a"}, {"label": "b"}]}])


def test_validation_duplicate_questions_and_labels():
    dup_q = _questions() + _questions()
    with pytest.raises(cm.ClarificationValidationError):
        cm.validate_and_normalize_questions(dup_q)
    with pytest.raises(cm.ClarificationValidationError):
        cm.validate_and_normalize_questions(
            [{"question": "q", "header": "h", "options": [{"label": "a"}, {"label": "a"}]}]
        )


def test_stable_ids_generated_ignoring_model_ids():
    normalized = cm.validate_and_normalize_questions(
        [{"question": "q", "header": "h", "questionId": "BAD", "options": [{"label": "a", "optionId": "BAD"}, {"label": "b"}]}]
    )
    assert normalized[0].question_id == "q1"
    assert normalized[0].options[0].option_id == "q1o1"
    assert normalized[0].options[1].option_id == "q1o2"


# ===== answered: 单选 / 多选 / 其他 =====


def test_answered_single_select():
    sig = FakeSignal()
    cm.register_clarification_signal(sig)
    t, holder = _run_async()
    pending = cm.get_pending_for_session("s1")
    out = cm.submit_decision("s1", pending.request_id, "submit", [{"questionId": "q1", "selectedOptionIds": ["q1o1"], "otherText": None}])
    t.join(timeout=2)
    assert out["status"] == "answered" and out["accepted"] is True
    assert holder["result"] == {
        "status": "answered",
        "answers": [{"question": "选择执行方式？", "selectedLabels": ["按顺序"], "otherText": None}],
    }
    assert sig.requested and sig.resolved[0][1] == "answered"


def test_answered_multi_select_with_other():
    sig = FakeSignal()
    cm.register_clarification_signal(sig)
    t, holder = _run_async(questions=_questions(multi=True))
    pending = cm.get_pending_for_session("s1")
    cm.submit_decision(
        "s1", pending.request_id, "submit",
        [{"questionId": "q1", "selectedOptionIds": ["q1o1", "q1o2"], "otherText": "额外说明"}],
    )
    t.join(timeout=2)
    ans = holder["result"]["answers"][0]
    assert ans["selectedLabels"] == ["按顺序", "并行"]
    assert ans["otherText"] == "额外说明"


def test_answered_only_other_text_single():
    sig = FakeSignal()
    cm.register_clarification_signal(sig)
    t, holder = _run_async()
    pending = cm.get_pending_for_session("s1")
    cm.submit_decision("s1", pending.request_id, "submit", [{"questionId": "q1", "selectedOptionIds": [], "otherText": "自定义"}])
    t.join(timeout=2)
    ans = holder["result"]["answers"][0]
    assert ans["selectedLabels"] == [] and ans["otherText"] == "自定义"


# ===== 答案校验失败（不结算） =====


def test_single_select_multiple_options_rejected():
    cm.register_clarification_signal(FakeSignal())
    t, _ = _run_async()
    pending = cm.get_pending_for_session("s1")
    with pytest.raises(cm.ClarificationValidationError):
        cm.submit_decision("s1", pending.request_id, "submit", [{"questionId": "q1", "selectedOptionIds": ["q1o1", "q1o2"], "otherText": None}])
    # 未结算：仍 pending
    assert cm.get_pending_for_session("s1") is not None
    cm.settle_all_clarifications("shutdown")
    t.join(timeout=2)


def test_missing_answer_rejected():
    cm.register_clarification_signal(FakeSignal())
    t, _ = _run_async()
    pending = cm.get_pending_for_session("s1")
    with pytest.raises(cm.ClarificationValidationError):
        cm.submit_decision("s1", pending.request_id, "submit", [{"questionId": "q1", "selectedOptionIds": [], "otherText": ""}])
    cm.settle_all_clarifications("shutdown")
    t.join(timeout=2)


def test_other_text_too_long_rejected():
    cm.register_clarification_signal(FakeSignal())
    t, _ = _run_async()
    pending = cm.get_pending_for_session("s1")
    with pytest.raises(cm.ClarificationValidationError):
        cm.submit_decision("s1", pending.request_id, "submit", [{"questionId": "q1", "selectedOptionIds": [], "otherText": "x" * 1001}])
    cm.settle_all_clarifications("shutdown")
    t.join(timeout=2)


def test_unknown_option_id_rejected():
    cm.register_clarification_signal(FakeSignal())
    t, _ = _run_async()
    pending = cm.get_pending_for_session("s1")
    with pytest.raises(cm.ClarificationValidationError):
        cm.submit_decision("s1", pending.request_id, "submit", [{"questionId": "q1", "selectedOptionIds": ["q9o9"], "otherText": None}])
    cm.settle_all_clarifications("shutdown")
    t.join(timeout=2)


# ===== cancelled =====


def test_cancelled():
    sig = FakeSignal()
    cm.register_clarification_signal(sig)
    t, holder = _run_async()
    pending = cm.get_pending_for_session("s1")
    out = cm.submit_decision("s1", pending.request_id, "cancel", [])
    t.join(timeout=2)
    assert out["status"] == "cancelled" and out["accepted"] is True
    assert holder["result"] == {"status": "cancelled", "answers": []}
    assert sig.resolved[0][1] == "cancelled"


# ===== 超时 / 停止 / 关闭 =====


def test_timeout(monkeypatch):
    monkeypatch.setattr(cm, "CLARIFICATION_TIMEOUT_S", 0.15)
    sig = FakeSignal()
    cm.register_clarification_signal(sig)
    result = cm.ask_user_question(_questions(), session_id="s1")
    assert result == {"status": "timeout", "answers": []}
    assert sig.resolved and sig.resolved[0][1] == "timeout"


def test_settle_for_session_stopped():
    sig = FakeSignal()
    cm.register_clarification_signal(sig)
    t, holder = _run_async()
    pending = cm.get_pending_for_session("s1")
    settled = cm.settle_clarifications_for_session("s1", "stopped")
    t.join(timeout=2)
    assert settled == [pending.request_id]
    assert holder["result"]["status"] == "stopped"


def test_settle_all_shutdown():
    cm.register_clarification_signal(FakeSignal())
    t, holder = _run_async()
    cm.settle_all_clarifications("shutdown")
    t.join(timeout=2)
    assert holder["result"]["status"] == "shutdown"


# ===== first-decision-wins / 归属 / 边界 =====


def test_first_decision_wins_concurrent():
    cm.register_clarification_signal(FakeSignal())
    t, holder = _run_async()
    pending = cm.get_pending_for_session("s1")
    rid = pending.request_id
    results = []
    barrier = threading.Barrier(2)

    def submit(option):
        barrier.wait()
        try:
            results.append(cm.submit_decision("s1", rid, "submit", [{"questionId": "q1", "selectedOptionIds": [option], "otherText": None}]))
        except LookupError:
            results.append({"lookup_error": True})

    a = threading.Thread(target=submit, args=("q1o1",))
    b = threading.Thread(target=submit, args=("q1o2",))
    a.start(); b.start(); a.join(); b.join()
    t.join(timeout=2)
    # 恰好一个 accepted=True，另一个 accepted=False 或 LookupError（均不崩溃）
    accepted = [r for r in results if r.get("accepted") is True]
    assert len(accepted) == 1
    assert holder["result"]["status"] == "answered"


def test_session_ownership_mismatch():
    cm.register_clarification_signal(FakeSignal())
    t, _ = _run_async(session_id="s1")
    pending = cm.get_pending_for_session("s1")
    with pytest.raises(LookupError):
        cm.submit_decision("OTHER", pending.request_id, "cancel", [])
    cm.settle_all_clarifications("shutdown")
    t.join(timeout=2)


def test_signal_not_registered_returns_unavailable():
    # reset 已清空 signal
    result = cm.ask_user_question(_questions(), session_id="s1")
    assert result == {"status": "unavailable", "answers": []}


def test_emit_exception_does_not_hang(monkeypatch):
    class BadSignal:
        def emit_requested(self, request_id):
            raise RuntimeError("boom")

        def emit_resolved(self, request_id):
            pass

    cm.register_clarification_signal(BadSignal())
    with pytest.raises(RuntimeError):
        cm.ask_user_question(_questions(), session_id="s1")
    # pending 被清理，不悬挂
    assert cm.get_pending_for_session("s1") is None
