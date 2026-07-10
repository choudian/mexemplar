"""Quota probing and tool selection for external coding tools."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from datetime import datetime, timezone

from src.execution.external_coding_quota import ExternalCodingQuotaRunner, SafeQuotaSnapshot
from src.utils.timezone import utc_now_naive

from .models import ExternalCodingTool, QuotaSignal, QuotaState

_SELECTION_ORDER = {
    QuotaState.AVAILABLE: 0,
    QuotaState.UNKNOWN: 1,
    QuotaState.LOW: 2,
    QuotaState.EXHAUSTED: 3,
}


class QuotaExhaustedError(ValueError):
    """Raised when selection would use an exhausted tool without override."""


def _now() -> str:
    return utc_now_naive().isoformat()


class QuotaProbe:
    """Normalize local quota availability without exposing raw credential data."""

    def __init__(
        self,
        *,
        command_by_tool: Mapping[str, str] | None = None,
        enabled: bool = True,
        low_threshold_percent: int = 80,
        timeout_seconds: int = 12,
        runner: ExternalCodingQuotaRunner | None = None,
    ):
        self._command_by_tool = dict(command_by_tool or {})
        self._enabled = enabled
        self._low_threshold_percent = max(1, min(int(low_threshold_percent), 99))
        self._timeout_seconds = max(1, min(int(timeout_seconds), 60))
        self._runner = runner or ExternalCodingQuotaRunner()

    def probe(self, tool: ExternalCodingTool) -> QuotaSignal:
        """Probe quota availability without retaining raw CLI account output."""
        command = self._command_by_tool.get(tool.value, tool.value)
        if not self._enabled:
            return QuotaSignal(
                tool=tool,
                state=QuotaState.UNKNOWN,
                source="quota_probe_disabled",
                confidence=0.0,
                checked_at=_now(),
            )
        if shutil.which(command) is None:
            return QuotaSignal(
                tool=tool,
                state=QuotaState.UNKNOWN,
                source="local_command_lookup",
                confidence=0.2,
                checked_at=_now(),
                safe_detail=f"{tool.value} command not found",
            )
        snapshot = self._probe_snapshot(tool, command)
        if snapshot is None or not snapshot.usage_percents:
            return QuotaSignal(
                tool=tool,
                state=QuotaState.UNKNOWN,
                source="local_usage_probe",
                confidence=0.25,
                checked_at=_now(),
                safe_detail="command available; normalized quota signal unavailable",
            )
        maximum = max(snapshot.usage_percents)
        if snapshot.reached or maximum >= 100:
            state = QuotaState.EXHAUSTED
        elif maximum >= self._low_threshold_percent:
            state = QuotaState.LOW
        else:
            state = QuotaState.AVAILABLE
        return QuotaSignal(
            tool=tool,
            state=state,
            source=snapshot.source,
            confidence=snapshot.confidence,
            checked_at=_now(),
            reset_at=_earliest_reset(snapshot),
            safe_detail=f"maximum normalized usage {maximum}%",
        )

    def _probe_snapshot(self, tool: ExternalCodingTool, command: str) -> SafeQuotaSnapshot | None:
        if tool == ExternalCodingTool.CLAUDE_CODE:
            return self._runner.probe_claude(
                command,
                timeout_seconds=self._timeout_seconds,
            )
        return self._runner.probe_codex(
            command,
            timeout_seconds=self._timeout_seconds,
        )

    def probe_all(self) -> dict[ExternalCodingTool, QuotaSignal]:
        return {tool: self.probe(tool) for tool in ExternalCodingTool}


def choose_tool(
    *,
    preference: str | None,
    signals: Mapping[ExternalCodingTool, QuotaSignal],
    explicit_exhausted_override: bool = False,
) -> tuple[ExternalCodingTool, str]:
    """Choose a tool based on normalized quota states.

    Exhausted tools are avoided unless explicitly requested and override is true.
    """
    requested = (preference or "auto").strip()
    if requested in {ExternalCodingTool.CLAUDE_CODE.value, ExternalCodingTool.CODEX_CLI.value}:
        tool = ExternalCodingTool(requested)
        signal = signals.get(tool)
        if signal and signal.state == QuotaState.EXHAUSTED and not explicit_exhausted_override:
            raise QuotaExhaustedError(
                f"{tool.value} quota is exhausted; explicit override is required"
            )
        reason = f"explicit tool={tool.value}; quota={signal.state.value if signal else 'unknown'}"
        return tool, reason

    ranked = sorted(
        ExternalCodingTool,
        key=lambda item: (
            _SELECTION_ORDER.get(signals.get(item, _unknown(item)).state, 99),
            item.value,
        ),
    )
    chosen = ranked[0]
    signal = signals.get(chosen, _unknown(chosen))
    if signal.state == QuotaState.EXHAUSTED and not explicit_exhausted_override:
        raise QuotaExhaustedError("all external coding tools are exhausted")
    reason = f"auto selected {chosen.value}; quota={signal.state.value}; source={signal.source}"
    return chosen, reason


def _unknown(tool: ExternalCodingTool) -> QuotaSignal:
    return QuotaSignal(
        tool=tool,
        state=QuotaState.UNKNOWN,
        source="not_checked",
        confidence=0.0,
        checked_at=_now(),
    )


def _earliest_reset(snapshot: SafeQuotaSnapshot) -> str | None:
    if not snapshot.reset_epochs:
        return None
    reset_epoch = min(snapshot.reset_epochs)
    return datetime.fromtimestamp(reset_epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")
