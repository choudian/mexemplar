"""Shared redaction for text that may be persisted outside secret storage."""

from __future__ import annotations

import re

_SECRET_KEY_PATTERN = (
    r"[A-Za-z0-9_.-]*(?:api[_-]?key|access[_-]?token|token|secret|password|authorization)"
    r"[A-Za-z0-9_.-]*"
)
_SECRET_ASSIGNMENT_RE = re.compile(rf"(?i)\b({_SECRET_KEY_PATTERN})(\s*[:=]\s*)([^\s,;\"'}}]+)")
_JSON_SECRET_RE = re.compile(
    rf"(?i)([\"']{_SECRET_KEY_PATTERN}[\"']\s*:\s*)" r"([\"'][^\"']*[\"']|[^,\s}]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/=]+")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)


def redact_sensitive_text(value: object, *, redact_emails: bool = False) -> str:
    """Redact common secret assignments without retaining the matched value."""
    redacted = _PRIVATE_KEY_RE.sub("<redacted-private-key>", str(value))
    redacted = _JSON_SECRET_RE.sub(_redact_json_value, redacted)
    redacted = _SECRET_ASSIGNMENT_RE.sub(r"\1\2<redacted>", redacted)
    redacted = _BEARER_RE.sub("Bearer <redacted>", redacted)
    if redact_emails:
        redacted = _EMAIL_RE.sub("<redacted-email>", redacted)
    return redacted


def _redact_json_value(match: re.Match[str]) -> str:
    raw_value = match.group(2)
    if raw_value[:1] in {'"', "'"}:
        quote = raw_value[0]
        return f"{match.group(1)}{quote}<redacted>{quote}"
    return f"{match.group(1)}<redacted>"
