from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from src.utils.timezone import utc_now_naive


@dataclass(frozen=True)
class FilterDecision:
    decision: Literal["filter", "keep"]
    source: str
    reason: str
    confidence: float = 1.0
    pattern_matched: str | None = None
    scores: dict[str, Any] | None = None
    request_id: str | None = None
    action_id: int | None = None
    recording_id: str | None = None
    request_timestamp: datetime | None = None
    action_timestamp: datetime | None = None
    timestamp: datetime = field(default_factory=utc_now_naive)

    def to_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "decision": self.decision,
            "source": self.source,
            "reason": self.reason,
        }
        if self.pattern_matched:
            summary["pattern_matched"] = self.pattern_matched
        return summary
