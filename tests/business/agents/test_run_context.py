"""014: Agent 运行上下文 / 取消注册表回归测试。

覆盖：
- E2 代际 token：陈旧 set 不误取消复用同一 session_id 的新一轮运行；pending 被 begin 消费后不残留。
- C2-E3 早停竞态：停止早于 begin() 登记 Event 时，该回合启动后仍被取消、不漏停。
- request_cancel 语义：有运行 → set 返回 True；无运行 → False。
"""

import pytest

from src.business.agents import run_context
from src.business.agents.run_context import CancelReason, CancelToken


@pytest.fixture(autouse=True)
def _clean_run_context():
    run_context.reset_for_tests()
    yield
    run_context.reset_for_tests()


class TestGenerationToken:
    def test_stale_event_set_does_not_cancel_reused_session(self):
        """E2：run1 结束后 run2 复用同一 session，旧 event 被 set 不影响 run2。"""
        sid = "sess-reuse"
        ctx1 = run_context.begin(sid)
        stale_event = ctx1.cancel_event
        run_context.end()

        ctx2 = run_context.begin(sid)
        # 每次运行配新 Event 与新代际
        assert ctx2.cancel_event is not stale_event
        assert ctx2.generation != ctx1.generation

        # 有人持有 run1 的旧 event 引用并 set —— 不得波及 run2
        stale_event.set()
        assert ctx2.cancel_event.is_set() is False
        current = run_context.get_current()
        assert current is ctx2
        assert current.cancel_event.is_set() is False

    def test_stale_run_id_does_not_cancel_reused_session(self):
        """E2：旧 run_id 的停止请求迟到，不得取消同 session 的新一轮运行。"""
        sid = "sess-reuse-run-id"
        ctx1 = run_context.begin(sid)
        stale_run_id = ctx1.run_id
        run_context.end()

        ctx2 = run_context.begin(sid)
        assert ctx2.run_id != stale_run_id

        assert run_context.request_cancel(sid, expected_run_id=stale_run_id) is False
        assert ctx2.cancel_event.is_set() is False

        assert run_context.request_cancel(sid, expected_run_id=ctx2.run_id) is True
        assert ctx2.cancel_event.is_set() is True

    def test_end_only_clears_own_generation(self):
        """end() 仅清除本代条目；request_cancel 在条目移除后返回 False（无运行）。"""
        sid = "sess-gen"
        run_context.begin(sid)
        run_context.end()
        # 运行已结束 → 无登记条目
        assert run_context.request_cancel(sid) is False


class TestEarlyStopRace:
    def test_cancel_before_begin_still_cancels_started_turn(self):
        """C2-E3：停止意图早于 begin() 登记，回合启动后仍立即取消。"""
        sid = "sess-early"
        # request_cancel 在尚无登记时返回 False（由 runtime 决定记 pending）
        assert run_context.request_cancel(sid) is False
        run_context.mark_pending_cancel(sid)

        ctx = run_context.begin(sid)
        assert ctx.cancel_event.is_set() is True
        assert run_context.get_current().cancel_event.is_set() is True

    def test_pending_consumed_and_not_leaked_to_next_turn(self):
        """pending 被 begin 消费一次；下一轮同会话运行不再被预取消。"""
        sid = "sess-pending"
        run_context.mark_pending_cancel(sid)
        first = run_context.begin(sid)
        assert first.cancel_event.is_set() is True
        run_context.end()

        second = run_context.begin(sid)
        assert second.cancel_event.is_set() is False


class TestRequestCancel:
    def test_request_cancel_sets_active_run_event(self):
        sid = "sess-active"
        ctx = run_context.begin(sid)
        assert run_context.request_cancel(sid) is True
        assert ctx.cancel_event.is_set() is True
        assert run_context.is_cancel_requested(sid) is True

    def test_request_cancel_without_run_returns_false(self):
        assert run_context.request_cancel("nope") is False
        assert run_context.is_cancel_requested("nope") is False

    def test_non_assistant_flow_has_no_context(self):
        """非助理流程从不 begin → get_current() 为 None（取消检查恒 False，零行为变化）。"""
        assert run_context.get_current() is None


class TestCancelToken:
    def test_cancel_reasons_are_limited_to_production_sources(self):
        assert {reason.value for reason in CancelReason} == {
            "user-cancel",
            "sibling_error",
        }

    def test_cancel_invokes_callbacks_once_with_first_reason(self):
        token = CancelToken()
        seen = []

        remove = token.add_callback(seen.append)

        assert token.cancel(CancelReason.SIBLING_ERROR) is True
        assert token.cancel(CancelReason.USER_CANCEL) is False
        remove()

        assert token.is_set() is True
        assert token.reason == CancelReason.SIBLING_ERROR
        assert seen == [CancelReason.SIBLING_ERROR]

    def test_late_callback_runs_immediately_and_removed_callback_does_not_run(self):
        token = CancelToken()
        removed = []
        late = []

        remove = token.add_callback(removed.append)
        remove()
        token.cancel(CancelReason.SIBLING_ERROR)
        token.add_callback(late.append)

        assert removed == []
        assert late == [CancelReason.SIBLING_ERROR]

    def test_request_cancel_propagates_structured_reason(self):
        sid = "sess-reason"
        ctx = run_context.begin(sid)
        seen = []
        ctx.cancel_token.add_callback(seen.append)

        assert run_context.request_cancel(sid, reason=CancelReason.USER_CANCEL) is True

        assert ctx.cancel_event is ctx.cancel_token
        assert ctx.cancel_event.wait(timeout=0) is True
        assert seen == [CancelReason.USER_CANCEL]
