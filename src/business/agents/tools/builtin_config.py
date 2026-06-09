"""Validated unified-config access for Agent built-in tools."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_config_int(
    getter: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    try:
        from src.data.unified_config import get_unified_config

        value = getattr(get_unified_config(), getter)()
    except Exception:
        logger.warning(
            "[agent_tools] unified config getter failed: getter=%s",
            getter,
            exc_info=True,
        )
        value = default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        logger.warning(
            "[agent_tools] unified config getter returned non-integer: getter=%s",
            getter,
        )
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed
