"""Token usage captured from LLM responses.

The provider reports what a request actually cost; this module keeps that number
instead of discarding it with the rest of the response object.

Two facts drive the design:

- ``input_tokens`` is the size of everything sent — system prompt, tool schemas
  and the full message history — which is exactly what compression needs to
  judge. Character estimation cannot see the system prompt or tool schemas at
  all, and under-counts Chinese text by roughly 38%.
- ``reasoning`` tokens never appear in the returned content, so estimating
  output from ``content`` is off by two orders of magnitude on reasoning models.

Hence ``source``: an estimated figure may drive compression triggers, but must
never be presented as a cost figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# Rough character-per-token ratios, used only when the provider reports nothing.
# Deliberately separate for CJK and latin text: a single divisor under-counts
# Chinese by ~38%, which would delay compression past the real limit.
_CJK_CHARS_PER_TOKEN = 1.8
_LATIN_CHARS_PER_TOKEN = 4.0


@dataclass(frozen=True)
class TokenUsage:
    """Token counts for a single LLM call."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0
    source: str = "actual"
    """``actual`` when the provider reported it, ``estimated`` when derived."""

    @property
    def is_actual(self) -> bool:
        return self.source == "actual"

    def to_dict(self) -> dict[str, Any]:
        return {
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "totalTokens": self.total_tokens,
            "cacheReadTokens": self.cache_read_tokens,
            "reasoningTokens": self.reasoning_tokens,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "TokenUsage | None":
        if not isinstance(raw, Mapping):
            return None
        try:
            return cls(
                input_tokens=int(raw.get("inputTokens") or 0),
                output_tokens=int(raw.get("outputTokens") or 0),
                total_tokens=int(raw.get("totalTokens") or 0),
                cache_read_tokens=int(raw.get("cacheReadTokens") or 0),
                reasoning_tokens=int(raw.get("reasoningTokens") or 0),
                source=str(raw.get("source") or "actual"),
            )
        except (TypeError, ValueError):
            return None


def _coerce_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number >= 0 else 0


def extract_token_usage(message: Any) -> TokenUsage | None:
    """Read LangChain's normalised ``usage_metadata`` off a response message.

    LangChain maps every OpenAI-compatible provider onto the same shape, so one
    reader covers all of them. Returns ``None`` when the provider reported
    nothing — callers fall back to :func:`estimate_token_usage`.
    """
    usage = getattr(message, "usage_metadata", None)
    if not isinstance(usage, Mapping):
        return None

    input_tokens = _coerce_int(usage.get("input_tokens"))
    output_tokens = _coerce_int(usage.get("output_tokens"))
    total = _coerce_int(usage.get("total_tokens")) or (input_tokens + output_tokens)
    if not (input_tokens or output_tokens or total):
        return None

    input_details = usage.get("input_token_details")
    output_details = usage.get("output_token_details")
    cache_read = (
        _coerce_int(input_details.get("cache_read"))
        if isinstance(input_details, Mapping)
        else 0
    )
    reasoning = (
        _coerce_int(output_details.get("reasoning"))
        if isinstance(output_details, Mapping)
        else 0
    )

    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
        cache_read_tokens=cache_read,
        reasoning_tokens=reasoning,
        source="actual",
    )


def estimate_tokens(text: str) -> int:
    """Estimate tokens for *text*, counting CJK and latin characters separately.

    Only ever a fallback for compression triggers. It cannot see the system
    prompt, tool schemas or reasoning tokens, so it is never a cost figure.
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿" or "぀" <= ch <= "ヿ")
    latin = len(text) - cjk
    return int(cjk / _CJK_CHARS_PER_TOKEN + latin / _LATIN_CHARS_PER_TOKEN) + 1


def estimate_token_usage(*, prompt: str = "", completion: str = "") -> TokenUsage:
    """Build an ``estimated`` usage record when the provider reported nothing."""
    input_tokens = estimate_tokens(prompt)
    output_tokens = estimate_tokens(completion)
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        source="estimated",
    )
