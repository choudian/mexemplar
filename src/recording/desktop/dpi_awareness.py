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


def apply() -> DpiAwarenessResult:
    """Apply Windows Per-Monitor V2 DPI awareness before QApplication exists."""
    if sys.platform != "win32":
        return DpiAwarenessResult(ok=False, level="unsupported", reason="non_windows")

    try:
        context = ctypes.c_void_p(-4)
        ctypes.windll.user32.SetProcessDpiAwarenessContext(context)
        return DpiAwarenessResult(ok=True, level="per_monitor_v2")
    except Exception as exc:
        logger.info("[desktop dpi] Per-Monitor V2 failed: %s", exc)

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return DpiAwarenessResult(ok=True, level="per_monitor_v1")
    except Exception as exc:
        logger.info("[desktop dpi] Per-Monitor V1 failed: %s", exc)

    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return DpiAwarenessResult(ok=True, level="system")
    except Exception as exc:
        logger.warning("[desktop dpi] DPI awareness unavailable: %s", exc)
        return DpiAwarenessResult(ok=False, level="unavailable", reason=type(exc).__name__)
