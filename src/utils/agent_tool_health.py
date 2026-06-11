"""Log-safe in-process health counters for Agent built-in tools."""

from __future__ import annotations

import threading

_DEFAULT_COUNTERS: dict[str, int] = {
    "compacted_outputs": 0,
    "compaction_fallbacks": 0,
    "raw_reference_create_failures": 0,
    "raw_reference_load_failures": 0,
    "retention_cleanup_failures": 0,
    "retention_cleanup_expired_metadata": 0,
    "retention_cleanup_removed_blobs": 0,
    "retention_cleanup_missing_blobs": 0,
    "retention_cleanup_orphaned_blobs": 0,
    "stale_mutation_rejections": 0,
    "missing_baseline_rejections": 0,
    "confirmation_fail_closed": 0,
    "process_cleanup_stopped": 0,
    "process_cleanup_failures": 0,
    # Backward-compatible alias used by the original output governance counter.
    "cleanup_failures": 0,
    "semantic_summary_attempts": 0,
    "semantic_summary_successes": 0,
    "semantic_summary_timeouts": 0,
    "semantic_summary_partial": 0,
    "semantic_summary_invalid": 0,
    "semantic_summary_map_failures": 0,
    "semantic_summary_reduce_failures": 0,
    "semantic_summary_input_chars": 0,
}

_counters: dict[str, int] = dict(_DEFAULT_COUNTERS)
_lock = threading.Lock()


def increment_agent_tool_health(**increments: int) -> None:
    """Increment one or more log-safe Agent built-in health counters."""
    with _lock:
        for key, delta in increments.items():
            _counters[key] = _counters.get(key, 0) + int(delta)


def record_retention_cleanup(result: dict[str, int]) -> None:
    """Record log-safe summary counters from ToolOutputRepository cleanup."""
    increment_agent_tool_health(
        retention_cleanup_expired_metadata=int(result.get("expiredMetadata", 0)),
        retention_cleanup_removed_blobs=int(result.get("removedBlobs", 0)),
        retention_cleanup_missing_blobs=int(result.get("missingBlobs", 0)),
        retention_cleanup_orphaned_blobs=int(result.get("orphanedBlobs", 0)),
        retention_cleanup_failures=int(result.get("failedBlobDeletes", 0)),
    )


def record_process_cleanup(result: dict[str, int]) -> None:
    """Record log-safe summary counters from ProcessManager cleanup."""
    increment_agent_tool_health(
        process_cleanup_stopped=int(result.get("stopped", 0)),
        process_cleanup_failures=int(result.get("failures", 0)),
    )


def get_agent_tool_health_counters() -> dict[str, int]:
    with _lock:
        return dict(_counters)


def reset_agent_tool_health_for_tests() -> None:
    with _lock:
        _counters.clear()
        _counters.update(_DEFAULT_COUNTERS)
