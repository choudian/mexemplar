"""Thread-safe bounded LRU cache backed by OrderedDict + RLock.

Provides a reusable alternative to the ad-hoc OrderedDict + threading.RLock
+ popitem(last=False) pattern duplicated across multiple modules.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Generic, Hashable, TypeVar

_K = TypeVar("_K", bound=Hashable)
_V = TypeVar("_V")


class BoundedLruCache(Generic[_K, _V]):
    """Thread-safe LRU cache with a fixed max-entries cap.

    Uses OrderedDict for O(1) insertion-order tracking and threading.RLock
    for thread safety.  Evicts the oldest entry when the cap is exceeded.

    Not suitable for:
    - Byte-budget eviction (use a dedicated class).
    - Half-eviction strategies (evict-oldest-half).
    - Non-reentrant lock requirements (uses RLock).

    Note on ``get`` vs ``get_entry``:
        ``get`` returns ``None`` for both "key absent" and "value is None".
        If you need to distinguish these cases, use ``get_entry`` which
        returns a ``(found, value)`` tuple.
    """

    _MISS = object()

    def __init__(self, max_entries: int) -> None:
        if max_entries < 1:
            raise ValueError(f"max_entries must be >= 1, got {max_entries}")
        self._max_entries = max_entries
        self._data: OrderedDict[_K, _V] = OrderedDict()
        self._lock = threading.RLock()

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def get(self, key: _K) -> _V | None:
        """Return the value for *key* if present, else None.

        Moves the entry to the end (most-recently used) on hit.

        Caveat: returns None for both "key absent" and "value is None".
        Use ``get_entry`` to distinguish these cases.
        """
        found, value = self.get_entry(key)
        return value if found else None

    def get_entry(self, key: _K) -> tuple[bool, _V | None]:
        """Return ``(found, value)`` for *key*.

        Moves the entry to the end (most-recently used) on hit.
        ``found`` is True when the key exists in the cache (even if the
        stored value is None), allowing callers to distinguish a cached
        None from a cache miss.
        """
        with self._lock:
            value = self._data.get(key, self._MISS)  # type: ignore[arg-type]
            if value is self._MISS:
                return False, None
            self._data.move_to_end(key)
            return True, value

    def put(self, key: _K, value: _V) -> None:
        """Insert or update *key* → *value*, evicting the oldest entry if over cap."""
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)

    def contains(self, key: _K) -> bool:
        """Return True if *key* is in the cache (without affecting LRU order)."""
        with self._lock:
            return key in self._data

    def remove(self, key: _K) -> _V | None:
        """Remove *key* and return its value, or None if not present."""
        with self._lock:
            return self._data.pop(key, None)

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
