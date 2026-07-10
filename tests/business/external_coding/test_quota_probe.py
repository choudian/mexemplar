import sys

import pytest

from src.business.external_coding.models import ExternalCodingTool, QuotaSignal, QuotaState
from src.business.external_coding.quota_probe import QuotaProbe, choose_tool
from src.execution.external_coding_quota import SafeQuotaSnapshot


class FakeQuotaRunner:
    def __init__(
        self,
        *,
        claude: SafeQuotaSnapshot | None = None,
        codex: SafeQuotaSnapshot | None = None,
    ) -> None:
        self.claude = claude
        self.codex = codex

    def probe_claude(self, command: str, *, timeout_seconds: int):
        return self.claude

    def probe_codex(self, command: str, *, timeout_seconds: int):
        return self.codex


def _signal(tool: ExternalCodingTool, state: QuotaState) -> QuotaSignal:
    return QuotaSignal(
        tool=tool,
        state=state,
        source="test",
        confidence=1.0,
        checked_at="2026-07-09T00:00:00",
    )


def test_choose_tool_prefers_available_over_exhausted() -> None:
    tool, reason = choose_tool(
        preference="auto",
        signals={
            ExternalCodingTool.CLAUDE_CODE: _signal(
                ExternalCodingTool.CLAUDE_CODE, QuotaState.EXHAUSTED
            ),
            ExternalCodingTool.CODEX_CLI: _signal(
                ExternalCodingTool.CODEX_CLI, QuotaState.AVAILABLE
            ),
        },
    )

    assert tool == ExternalCodingTool.CODEX_CLI
    assert "available" in reason


def test_explicit_exhausted_tool_requires_override() -> None:
    with pytest.raises(ValueError, match="exhausted"):
        choose_tool(
            preference="claude_code",
            signals={
                ExternalCodingTool.CLAUDE_CODE: _signal(
                    ExternalCodingTool.CLAUDE_CODE, QuotaState.EXHAUSTED
                )
            },
        )


def test_unknown_quota_tools_are_still_selectable() -> None:
    """US4-AS2: Unknown quota still allows selection."""
    tool, reason = choose_tool(
        preference="auto",
        signals={
            ExternalCodingTool.CLAUDE_CODE: _signal(
                ExternalCodingTool.CLAUDE_CODE, QuotaState.UNKNOWN
            ),
            ExternalCodingTool.CODEX_CLI: _signal(ExternalCodingTool.CODEX_CLI, QuotaState.UNKNOWN),
        },
    )

    assert tool in {ExternalCodingTool.CLAUDE_CODE, ExternalCodingTool.CODEX_CLI}
    assert "unknown" in reason


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (
            SafeQuotaSnapshot(
                source="test",
                usage_percents=(24, 40),
                confidence=0.9,
            ),
            QuotaState.AVAILABLE,
        ),
        (
            SafeQuotaSnapshot(
                source="test",
                usage_percents=(81, 30),
                confidence=0.9,
            ),
            QuotaState.LOW,
        ),
        (
            SafeQuotaSnapshot(
                source="test",
                usage_percents=(45, 10),
                reached=True,
                confidence=0.9,
            ),
            QuotaState.EXHAUSTED,
        ),
    ],
)
def test_probe_normalizes_all_quota_states(
    snapshot: SafeQuotaSnapshot,
    expected: QuotaState,
) -> None:
    probe = QuotaProbe(
        command_by_tool={ExternalCodingTool.CLAUDE_CODE.value: sys.executable},
        runner=FakeQuotaRunner(claude=snapshot),
        low_threshold_percent=80,
    )

    signal = probe.probe(ExternalCodingTool.CLAUDE_CODE)

    assert signal.state == expected
    assert signal.source == "test"
    assert signal.safe_detail == f"maximum normalized usage {max(snapshot.usage_percents)}%"


def test_probe_exposes_only_normalized_reset_time() -> None:
    snapshot = SafeQuotaSnapshot(
        source="codex_app_server",
        usage_percents=(85,),
        reset_epochs=(1_800_000_000,),
        confidence=0.95,
    )
    probe = QuotaProbe(
        command_by_tool={ExternalCodingTool.CODEX_CLI.value: sys.executable},
        runner=FakeQuotaRunner(codex=snapshot),
    )

    signal = probe.probe(ExternalCodingTool.CODEX_CLI)

    assert signal.state == QuotaState.LOW
    assert signal.reset_at == "2027-01-15T08:00:00Z"
    assert "account" not in (signal.safe_detail or "").lower()
