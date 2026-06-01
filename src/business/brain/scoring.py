"""Shared ranking helpers for brain memory retrieval and prompt injection."""

import math
from datetime import datetime, timezone

# 复合评分权重（热区 / 归档区检索公用）
HOT_RELEVANCE_WEIGHT = 0.35
HOT_RECENCY_WEIGHT = 0.25
HOT_EFFECTIVENESS_WEIGHT = 0.25
HOT_EXPLORATION_WEIGHT = 0.15

# 潜意识区权重
SUBCONSCIOUS_RECENCY_WEIGHT = 0.60
SUBCONSCIOUS_EFFECTIVENESS_WEIGHT = 0.25
SUBCONSCIOUS_EXPLORATION_WEIGHT = 0.15

# 新条目探索加分阈值
EXPLORATION_LOADED_THRESHOLD = 3

# 复用会话已加载条目的额外加分
HOT_REVIVED_SESSION_BONUS = 0.35


def compute_recency_score(created_at_value: object, *, half_life_days: float) -> float:
    """Return a timezone-safe exponential recency score with an explicit policy half-life."""
    if not created_at_value:
        return 0.5
    try:
        created_at = datetime.fromisoformat(str(created_at_value).replace("Z", "+00:00"))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = max(
            (datetime.now(timezone.utc) - created_at).total_seconds() / 86400,
            0,
        )
        return math.exp(-math.log(2) * age_days / half_life_days)
    except (TypeError, ValueError):
        return 0.5
