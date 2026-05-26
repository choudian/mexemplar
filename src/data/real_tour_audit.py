"""Process-local Real Grand Tour audit and budget guard.

This module is active only when ``MEXEMPLAR_REAL_GRAND_TOUR=1``.  It records
non-sensitive counters to the isolated real-tour data directory so the
Playwright runner can include actual sidecar-observed evidence in its summary
report.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable


class RealTourBudgetExceeded(RuntimeError):
    """Raised before a provider call that would exceed the real-tour budget."""


class RealTourCredentialMutationError(RuntimeError):
    """Raised when real-tour code attempts to mutate keyring credentials."""


class RealTourAuditIntegrityError(RuntimeError):
    """Raised when existing real-tour evidence is missing integrity."""


_LOCK = threading.Lock()
_STARTED_AT = time.monotonic()
_KEYRING_GUARD_INSTALLED = False


def is_real_tour_runtime() -> bool:
    return os.environ.get("MEXEMPLAR_REAL_GRAND_TOUR") == "1"


def record_paid_call(source: str) -> None:
    """Record one real provider call or fail before exceeding configured budgets."""
    if not is_real_tour_runtime():
        return

    with _LOCK:
        state = _read_state_unlocked()
        max_minutes = _positive_int(os.environ.get("MEXEMPLAR_REAL_GRAND_TOUR_MAX_MINUTES"), 20)
        max_calls = _positive_int(os.environ.get("MEXEMPLAR_REAL_GRAND_TOUR_MAX_PAID_CALLS"), 30)
        elapsed_ms = int((time.monotonic() - _STARTED_AT) * 1000)

        if elapsed_ms > max_minutes * 60_000:
            state["budgetExceeded"] = True
            state["lastBudgetReason"] = "elapsed_time"
            state["lastCallSource"] = source
            state["elapsedMs"] = elapsed_ms
            _write_state_unlocked(state)
            raise RealTourBudgetExceeded("real_tour_budget_exceeded")

        if int(state.get("paidCallCount", 0)) + 1 > max_calls:
            state["budgetExceeded"] = True
            state["lastBudgetReason"] = "paid_call_count"
            state["lastCallSource"] = source
            state["elapsedMs"] = elapsed_ms
            _write_state_unlocked(state)
            raise RealTourBudgetExceeded("real_tour_budget_exceeded")

        state["paidCallCount"] = int(state.get("paidCallCount", 0)) + 1
        state["lastCallSource"] = source
        state["elapsedMs"] = elapsed_ms
        _write_state_unlocked(state)


def record_credential_mutation(operation: str) -> None:
    """Record a forbidden keyring mutation attempt."""
    if not is_real_tour_runtime():
        return
    with _LOCK:
        state = _read_state_unlocked()
        state["credentialMutationCount"] = int(state.get("credentialMutationCount", 0)) + 1
        state["lastCredentialMutation"] = operation
        _write_state_unlocked(state)


def install_keyring_mutation_guard() -> None:
    """Patch keyring write/delete calls so real-tour mutations fail closed."""
    global _KEYRING_GUARD_INSTALLED
    if not is_real_tour_runtime() or _KEYRING_GUARD_INSTALLED:
        return
    try:
        import keyring
        if not hasattr(keyring, "set_password") or not hasattr(keyring, "delete_password"):
            raise ImportError("keyring mutation functions unavailable")
    except Exception as exc:
        raise RealTourCredentialMutationError(
            "credential_mutation_guard_unavailable"
        ) from exc

    def _forbid(operation: str) -> Callable[..., None]:
        def wrapper(*_args: Any, **_kwargs: Any) -> None:
            record_credential_mutation(operation)
            raise RealTourCredentialMutationError("credential_mutation_forbidden")

        return wrapper

    keyring.set_password = _forbid("set_password")  # type: ignore[assignment]
    keyring.delete_password = _forbid("delete_password")  # type: ignore[assignment]
    _KEYRING_GUARD_INSTALLED = True
    with _LOCK:
        state = _read_state_unlocked()
        state["keyringMutationGuard"] = "installed"
        _write_state_unlocked(state)


def _positive_int(value: str | None, fallback: int) -> int:
    try:
        parsed = int(str(value))
        return parsed if parsed > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def _audit_file() -> Path:
    configured = os.environ.get("MEXEMPLAR_REAL_GRAND_TOUR_AUDIT_FILE")
    if configured:
        return Path(configured)
    data_dir = os.environ.get("EXEMPLAR_DATA_DIR") or os.getcwd()
    return Path(data_dir) / "real-grand-tour-audit.json"


def _default_state() -> dict[str, Any]:
    return {
        "paidCallCount": 0,
        "credentialMutationCount": 0,
        "budgetExceeded": False,
        "elapsedMs": 0,
    }


def _read_state_unlocked() -> dict[str, Any]:
    path = _audit_file()
    if not path.exists():
        return _default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RealTourAuditIntegrityError("real_tour_audit_invalid") from exc
    return _validate_state(data)


def _write_state_unlocked(state: dict[str, Any]) -> None:
    path = _audit_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    validated = _validate_state(state)
    if path.exists():
        previous = _read_state_unlocked()
        if any(
            validated[key] < previous[key]
            for key in ("paidCallCount", "credentialMutationCount")
        ):
            raise RealTourAuditIntegrityError("real_tour_audit_counter_regression")

    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(validated, ensure_ascii=False, sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _validate_state(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise RealTourAuditIntegrityError("real_tour_audit_invalid")
    state = {**_default_state(), **data}
    for key in ("paidCallCount", "credentialMutationCount", "elapsedMs"):
        value = state.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RealTourAuditIntegrityError("real_tour_audit_invalid")
    if not isinstance(state.get("budgetExceeded"), bool):
        raise RealTourAuditIntegrityError("real_tour_audit_invalid")
    return state
