from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UiEventDraft:
    event_type: str
    payload: dict[str, Any]
    scope: dict[str, str]
    causation_id: str | None = None
