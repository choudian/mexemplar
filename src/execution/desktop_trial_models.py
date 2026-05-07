from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TrialResult:
    ok: bool
    summary: str
    details: dict[str, Any] | None
    exit_code: int | None
    timed_out: bool
    stdout_path: Path
    stderr_path: Path
    trial_id: str
