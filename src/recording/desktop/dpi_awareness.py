from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DpiAwarenessResult:
    ok: bool
    level: str
    reason: str | None = None
