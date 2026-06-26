"""录制过滤决策的纯数据协议(分层修复:从 recording 层下沉到 data 层)。

FilterDecision 与 MODE_TABLES 是 recording 与 data 两层共享的纯数据契约。
下沉到 data 层后,recording 层(``recording/filtering``)与 data 层
(``recording_repository``)都从本模块上调 import,恢复 Constitution Principle I
"执行层 → 数据层"的正向依赖方向。仅依赖 ``src.utils.timezone``,不反噬上层。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from src.utils.timezone import utc_now_naive

BROWSER_MODE_TABLES = frozenset(
    {
        "recording_sessions",
        "actions",
        "network_requests",
        "sibling_snapshots",
        "recording_screenshots",
    }
)
DESKTOP_MODE_TABLES = frozenset({"desktop_recordings", "desktop_actions"})
MODE_TABLES = {"browser": BROWSER_MODE_TABLES, "desktop": DESKTOP_MODE_TABLES}


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
