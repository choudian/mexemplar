"""Secret redaction for debug trace capture.

SecretRedactor maintains a thread-safe inventory of sentinel strings
(API keys, tokens, etc.) and replaces every occurrence with a fixed
mask before raw data enters the trace buffer.

Credential snapshot rotation is supported: both old and new sentinel
values remain masked until explicitly removed.
"""

from __future__ import annotations

import re
import threading
from typing import Union


_REDACTED = "***REDACTED***"


class SecretRedactor:
    """Thread-safe sentinel replacement engine.

    Usage::

        redactor = SecretRedactor()
        redactor.register_secret("sk-proj-abc123")

        safe = redactor.redact("my key is sk-proj-abc123")
        # -> "my key is ***REDACTED***"

    Sentinel registration is intentionally decoupled from configuration
    migration getters — the caller supplies plain values that are already
    in memory (e.g. from keyring or unified config).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Ordered by length descending so longer sentinel matches take priority.
        self._sentinels: list[str] = []
        # Pre-compiled regex updated on each registration.
        self._pattern: re.Pattern[str] = re.compile(r"(?!a)a")  # never-match sentinel

    # ---- public API ----

    def register_secret(self, secret: str) -> None:
        """Add *secret* to the redaction inventory.

        Empty or whitespace-only values are ignored.  Duplicate
        registrations are idempotent.
        """
        if not secret or not secret.strip():
            return
        with self._lock:
            if secret in self._sentinels:
                return
            self._sentinels.append(secret)
            self._rebuild_pattern()

    def redact(self, text: str) -> str:
        """Return *text* with every registered sentinel replaced by the mask."""
        if not text:
            return text
        with self._lock:
            pattern = self._pattern
        return pattern.sub(_REDACTED, text)

    def redact_json(self, data: Union[dict, list]) -> Union[dict, list]:
        """Recursively redact all string values in *data* (dict or list).

        Returns a new object; the input is never mutated.
        """
        if isinstance(data, dict):
            return {k: self._redact_value(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._redact_value(v) for v in data]
        return data

    # ---- internals ----

    def _redact_value(self, value: object) -> object:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return self.redact_json(value)
        if isinstance(value, list):
            return self.redact_json(value)
        return value

    def _rebuild_pattern(self) -> None:
        """Rebuild the alternation regex from current sentinel list.

        Must be called while holding ``self._lock``.
        """
        if not self._sentinels:
            self._pattern = re.compile(r"(?!a)a")
            return
        # Sort by length descending for greedy longest-match semantics.
        ordered = sorted(self._sentinels, key=len, reverse=True)
        escaped = [re.escape(s) for s in ordered]
        self._pattern = re.compile("|".join(escaped))
