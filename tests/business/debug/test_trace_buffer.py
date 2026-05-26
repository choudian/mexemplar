from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from src.business.debug.flow import FlowCorrelationService
from src.business.debug.models import LLMTraceRecord
from src.business.debug.trace_buffer import SharedRetentionBudget, TraceBuffer


def _record(
    trace_id: str,
    epoch: str,
    payload: str,
    *,
    method: str = "chat",
) -> LLMTraceRecord:
    return LLMTraceRecord(
        trace_id=trace_id,
        retention_epoch=epoch,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        method=method,
        source="agent_loop",
        input_messages=payload,
        output_content=f"out:{payload}",
    )


def test_record_count_capacity_evicts_oldest() -> None:
    buffer = TraceBuffer(max_records=3, max_record_bytes=1000, max_total_bytes=1000)
    epoch = buffer.new_epoch()

    for idx in range(4):
        assert buffer.add_record(_record(f"trace-{idx}", epoch, f"payload-{idx}"))

    records = buffer.get_records()
    assert [record.trace_id for record in records] == ["trace-1", "trace-2", "trace-3"]


def test_retained_bytes_are_calculated_from_redacted_payload_fields() -> None:
    buffer = TraceBuffer(max_records=10, max_record_bytes=1000, max_total_bytes=1000)
    epoch = buffer.new_epoch()

    assert buffer.add_record(_record("trace-1", epoch, "abc"))

    record = buffer.get_record("trace-1")
    assert record is not None
    assert record.retained_bytes == len("abcout:abc".encode("utf-8"))
    assert buffer.get_retained_bytes() == record.retained_bytes


def test_single_record_over_budget_omits_raw_detail() -> None:
    buffer = TraceBuffer(max_records=10, max_record_bytes=12, max_total_bytes=1000)
    epoch = buffer.new_epoch()

    assert buffer.add_record(_record("trace-large", epoch, "x" * 100))

    record = buffer.get_record("trace-large")
    assert record is not None
    assert record.detail_availability == "oversized_omitted"
    assert record.input_messages is None
    assert record.output_content is None
    assert record.retained_bytes == 0


def test_failed_record_over_budget_omits_error_summary_without_unaccounted_detail() -> None:
    buffer = TraceBuffer(max_records=10, max_record_bytes=12, max_total_bytes=1000)
    epoch = buffer.new_epoch()
    record = _record("trace-failure", epoch, "x" * 100).model_copy(
        update={"outcome": "failed", "error_summary": "sensitive failure detail"}
    )

    assert buffer.add_record(record)

    retained = buffer.get_record("trace-failure")
    assert retained is not None
    assert retained.detail_availability == "oversized_omitted"
    assert retained.error_summary == ""
    assert retained.retained_bytes == 0


def test_aggregate_byte_budget_evicts_oldest_records() -> None:
    buffer = TraceBuffer(max_records=10, max_record_bytes=100, max_total_bytes=24)
    epoch = buffer.new_epoch()

    assert buffer.add_record(_record("trace-1", epoch, "aaaa"))
    assert buffer.add_record(_record("trace-2", epoch, "bbbb"))
    assert buffer.add_record(_record("trace-3", epoch, "cccc"))

    records = buffer.get_records()
    assert [record.trace_id for record in records] == ["trace-2", "trace-3"]
    assert buffer.get_retained_bytes() <= 24


def test_trace_and_ephemeral_flow_detail_share_aggregate_byte_budget() -> None:
    budget = SharedRetentionBudget(10)
    buffer = TraceBuffer(
        max_records=10,
        max_record_bytes=10,
        max_total_bytes=10,
        shared_budget=budget,
    )
    epoch = buffer.new_epoch()
    flow = FlowCorrelationService(max_total_bytes=10, shared_budget=budget)
    flow.set_epoch(epoch)

    assert buffer.add_record(
        LLMTraceRecord(
            trace_id="trace-1",
            retention_epoch=epoch,
            input_messages="1234567890",
        )
    )
    detail = flow.add_detail("tr-1", "wf-1", "assistant_delegation", "abcdefghij")

    assert detail is not None
    assert detail.detail_availability == "full_text"
    assert detail.retained_bytes == 10
    assert buffer.get_record("trace-1") is None
    assert flow.retained_bytes == 10
    assert budget.get_retained_bytes() == 10


def test_new_trace_evicts_older_ephemeral_flow_detail_under_shared_budget() -> None:
    budget = SharedRetentionBudget(10)
    buffer = TraceBuffer(
        max_records=10,
        max_record_bytes=10,
        max_total_bytes=10,
        shared_budget=budget,
    )
    epoch = buffer.new_epoch()
    flow = FlowCorrelationService(max_total_bytes=10, shared_budget=budget)
    flow.set_epoch(epoch)
    detail = flow.add_detail("tr-1", "wf-1", "assistant_delegation", "abcdefghij")
    assert detail is not None

    assert buffer.add_record(
        LLMTraceRecord(
            trace_id="trace-1",
            retention_epoch=epoch,
            input_messages="1234567890",
        )
    )

    evicted_detail = flow.get_detail("tr-1")
    assert evicted_detail is not None
    assert evicted_detail.detail_availability == "oversized_omitted"
    assert evicted_detail.content == ""
    assert buffer.get_record("trace-1") is not None
    assert buffer.get_retained_bytes() == 10
    assert budget.get_retained_bytes() == 10


def test_stale_epoch_completion_is_rejected() -> None:
    buffer = TraceBuffer(max_records=10, max_record_bytes=100, max_total_bytes=1000)
    old_epoch = buffer.new_epoch()
    buffer.new_epoch()

    accepted = buffer.add_record(_record("stale", old_epoch, "payload"))

    assert accepted is False
    assert buffer.get_record("stale") is None


def test_invalidate_epoch_purges_and_rejects_writes() -> None:
    buffer = TraceBuffer(max_records=10, max_record_bytes=100, max_total_bytes=1000)
    epoch = buffer.new_epoch()
    assert buffer.add_record(_record("trace-1", epoch, "payload"))

    buffer.invalidate_epoch()

    assert buffer.get_record_count() == 0
    assert buffer.get_retained_bytes() == 0
    assert buffer.add_record(_record("trace-2", epoch, "payload")) is False


def test_concurrent_add_is_thread_safe() -> None:
    buffer = TraceBuffer(max_records=200, max_record_bytes=100, max_total_bytes=10000)
    epoch = buffer.new_epoch()

    def add(idx: int) -> bool:
        return buffer.add_record(_record(f"trace-{idx}", epoch, f"payload-{idx}"))

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(add, range(120)))

    assert all(results)
    assert buffer.get_record_count() == 120
