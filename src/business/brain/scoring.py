"""Shared ranking helpers for brain memory retrieval and prompt injection."""

import math
from datetime import datetime, timezone


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
