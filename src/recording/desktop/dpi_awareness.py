from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DpiAwarenessResult:
    ok: bool
    level: str
    reason: str | None = None
