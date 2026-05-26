"""Epoch-scoped, byte-bounded in-process trace buffer.

TraceBuffer holds :class:`LLMTraceRecord` instances in memory under a
retention epoch.  When the epoch is invalidated (disable / clear / restart),
all existing records become stale and subsequent ``add_record`` calls are
rejected until a new epoch is created.

Capacity is governed by three budgets:
- ``max_records`` — maximum number of retained records
- ``max_record_bytes`` — per-record byte ceiling (oversized records are
  admitted with ``detail_availability="oversized_omitted"``)
- ``max_total_bytes`` — aggregate byte ceiling (oldest records evicted)

All public methods are thread-safe.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import Optional

from src.business.debug.models import LLMTraceRecord


class SharedRetentionBudget:
    """Ordered aggregate byte budget shared by diagnostic buffers."""

    def __init__(self, max_total_bytes: int) -> None:
        self._max_total_bytes = max(1, max_total_bytes)
        self._retained_bytes = 0
        self._reservations: OrderedDict[str, tuple[int, Callable[[], None]]] = OrderedDict()
        self._lock = threading.RLock()

    @property
    def max_total_bytes(self) -> int:
        return self._max_total_bytes

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def reserve(
        self,
        key: str,
        retained_bytes: int,
        evict: Callable[[], None],
    ) -> bool:
        """Reserve bytes, evicting older retained detail across buffer types."""
        if retained_bytes <= 0:
            return True
        with self._lock:
            if retained_bytes > self._max_total_bytes:
                return False
            self._release_unlocked(key)
            while self._retained_bytes + retained_bytes > self._max_total_bytes:
                _old_key, (old_bytes, old_evict) = next(iter(self._reservations.items()))
                old_evict()
                self._reservations.popitem(last=False)
                self._retained_bytes -= old_bytes
            self._reservations[key] = (retained_bytes, evict)
            self._retained_bytes += retained_bytes
            return True

    def release(self, key: str) -> None:
        with self._lock:
            self._release_unlocked(key)

    def get_retained_bytes(self) -> int:
        with self._lock:
            return self._retained_bytes

    def _release_unlocked(self, key: str) -> None:
        reservation = self._reservations.pop(key, None)
        if reservation is not None:
            self._retained_bytes = max(0, self._retained_bytes - reservation[0])


class TraceBuffer:
    """Process-local trace record buffer with epoch lifecycle.

    Parameters
    ----------
    max_records:
        Maximum number of records retained at once.
    max_record_bytes:
        Byte ceiling for a single record's retained detail.
    max_total_bytes:
        Aggregate byte ceiling across all retained records.
    """

    def __init__(
        self,
        max_records: int = 200,
        max_record_bytes: int = 1048576,
        max_total_bytes: int = 16777216,
        shared_budget: SharedRetentionBudget | None = None,
    ) -> None:
        self._max_records = max(1, max_records)
        self._max_record_bytes = max(1, max_record_bytes)
        self._max_total_bytes = max(1, max_total_bytes)
        self._budget = shared_budget or SharedRetentionBudget(self._max_total_bytes)

        self._lock = self._budget.lock
        self._epoch: str = ""
        self._records: deque[LLMTraceRecord] = deque()
        self._retained_bytes: int = 0

    # ---- epoch lifecycle ----

    def new_epoch(self) -> str:
        """Create a new retention epoch, clearing all existing records.

        Returns the new epoch identifier.
        """
        epoch = uuid.uuid4().hex
        with self._lock:
            self._release_retained_bytes_unlocked()
            self._epoch = epoch
            self._records.clear()
        return epoch

    def is_epoch_valid(self, epoch: str) -> bool:
        """Return ``True`` if *epoch* matches the current active epoch."""
        with self._lock:
            return self._epoch != "" and self._epoch == epoch

    def invalidate_epoch(self) -> None:
        """Invalidate the current epoch and purge all records."""
        with self._lock:
            self._release_retained_bytes_unlocked()
            self._epoch = ""
            self._records.clear()

    # ---- record management ----

    def add_record(self, record: LLMTraceRecord) -> bool:
        """Attempt to add *record* to the buffer.

        Returns ``True`` if accepted, ``False`` if the epoch is stale or
        the record lacks a valid epoch.

        Oversized records (exceeding ``max_record_bytes``) are accepted but
        have their content fields cleared and
        ``detail_availability`` set to ``"oversized_omitted"``; their
        ``retained_bytes`` is set to 0.

        When the aggregate byte budget would be exceeded, the oldest records
        are evicted until the new record fits or the deque is empty.
        """
        with self._lock:
            # Reject if no active epoch or epoch mismatch.
            if not self._epoch or not record.retention_epoch:
                return False
            if record.retention_epoch != self._epoch:
                return False

            record_bytes = (
                record.retained_bytes
                if record.retained_bytes > 0
                else _calculate_retained_bytes(record)
            )
            if record.retained_bytes != record_bytes:
                record = record.model_copy(update={"retained_bytes": record_bytes})

            # Ensure adding an omission marker does not displace detail that
            # would otherwise have made a new record fit.
            while len(self._records) >= self._max_records:
                self._evict_oldest_unlocked()

            # Handle oversized single record.
            if (
                record_bytes > self._max_record_bytes
                or record_bytes > self._budget.max_total_bytes
            ):
                record = _make_oversized(record)
                record_bytes = 0

            if record_bytes > 0:
                reserved = self._budget.reserve(
                    self._budget_key(record),
                    record_bytes,
                    lambda: self._evict_by_trace_id_unlocked(record.trace_id),
                )
                if not reserved:
                    record = _make_oversized(record)
                    record_bytes = 0

            self._records.append(record)
            self._retained_bytes += record_bytes
            return True

    def get_records(
        self,
        *,
        source: Optional[str] = None,
        session_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        method: Optional[str] = None,
        epoch: Optional[str] = None,
    ) -> list[LLMTraceRecord]:
        """Return matching records from the current epoch.

        If *epoch* is provided and does not match the active epoch, returns
        an empty list.  All other filters are optional substring/match
        filters applied in-memory.
        """
        with self._lock:
            if epoch is not None and epoch != self._epoch:
                return []
            results: list[LLMTraceRecord] = []
            for rec in self._records:
                if source is not None and rec.source != source:
                    continue
                if session_id is not None and rec.session_id != session_id:
                    continue
                if workflow_id is not None and rec.workflow_id != workflow_id:
                    continue
                if method is not None and rec.method != method:
                    continue
                results.append(rec)
            return results

    def get_record(self, trace_id: str) -> Optional[LLMTraceRecord]:
        """Return a single record by *trace_id*, or ``None``."""
        with self._lock:
            for rec in self._records:
                if rec.trace_id == trace_id:
                    return rec
        return None

    def clear(self) -> None:
        """Invalidate the current epoch and remove all records."""
        self.invalidate_epoch()

    # ---- stats ----

    def get_retained_bytes(self) -> int:
        """Total retained bytes across all buffered records."""
        with self._lock:
            return self._retained_bytes

    def get_record_count(self) -> int:
        """Number of records currently in the buffer."""
        with self._lock:
            return len(self._records)

    def _evict_oldest_unlocked(self) -> None:
        evicted = self._records.popleft()
        self._retained_bytes -= evicted.retained_bytes
        self._budget.release(self._budget_key(evicted))

    def _evict_by_trace_id_unlocked(self, trace_id: str) -> None:
        for record in self._records:
            if record.trace_id == trace_id:
                self._records.remove(record)
                self._retained_bytes -= record.retained_bytes
                return

    def _release_retained_bytes_unlocked(self) -> None:
        for record in self._records:
            self._budget.release(self._budget_key(record))
        self._retained_bytes = 0

    @staticmethod
    def _budget_key(record: LLMTraceRecord) -> str:
        return f"trace:{record.retention_epoch}:{record.trace_id}"


def _make_oversized(record: LLMTraceRecord) -> LLMTraceRecord:
    """Return a copy of *record* with content fields cleared and
    ``detail_availability`` set to ``"oversized_omitted"``.
    """
    return LLMTraceRecord(
        trace_id=record.trace_id,
        retention_epoch=record.retention_epoch,
        created_at=record.created_at,
        completed_at=record.completed_at,
        method=record.method,
        source=record.source,
        agent_type=record.agent_type,
        session_id=record.session_id,
        workflow_id=record.workflow_id,
        work_unit_id=record.work_unit_id,
        iteration=record.iteration,
        input_messages=None,
        input_media=None,
        input_tools=None,
        output_content=None,
        output_tool_calls=None,
        outcome=record.outcome,
        error_summary="",
        linked_transition_ids=record.linked_transition_ids,
        retained_bytes=0,
        detail_availability="oversized_omitted",
    )


def _calculate_retained_bytes(record: LLMTraceRecord) -> int:
    """Return retained diagnostic byte size for redacted payload fields."""
    total = 0
    for value in (
        record.input_messages,
        record.input_media,
        record.input_tools,
        record.output_content,
        record.output_tool_calls,
        record.error_summary,
    ):
        if value:
            total += len(str(value).encode("utf-8"))
    return total
