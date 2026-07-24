"""Apply configured environment variables to this process.

The sidecar is launched by the desktop shell, not a terminal, so it inherits
none of the variables a shell profile would set. Everything downstream then
inherits that same bare environment: the LLM client's HTTP calls, external
coding CLIs, MCP servers, the exec tool, recording browsers.

A proxy is the most common gap, but not the only one — pointing a CLI at a
self-hosted backend needs `ANTHROPIC_BASE_URL` and friends. Rather than adding
a config field per scenario, the whole map is applied once at the entry point.
"""

from __future__ import annotations

import logging
import os
from typing import Mapping

logger = logging.getLogger(__name__)

# Names whose values must never reach a log line. Matched case-insensitively as
# substrings, so `ANTHROPIC_AUTH_TOKEN` and `http_proxy` (which can carry
# credentials in its userinfo) are both covered.
_SECRET_NAME_MARKERS = ("token", "key", "secret", "password", "auth", "proxy")


def _is_sensitive(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _SECRET_NAME_MARKERS)


def apply_process_env(values: Mapping[str, str] | None) -> list[str]:
    """Write *values* into ``os.environ``. Returns the names actually applied.

    Configured values win over inherited ones: an operator editing the config
    expects it to take effect, and the inherited environment is whatever the
    desktop shell happened to pass through.

    Only names are logged — a value may be a credential.
    """
    if not values:
        return []

    applied: list[str] = []
    for name, value in values.items():
        key = str(name).strip()
        if not key or value is None:
            continue
        text = str(value).strip()
        if not text:
            # Treat blank as "not set" rather than writing an empty string,
            # which would shadow a value the process could otherwise inherit.
            continue
        os.environ[key] = text
        applied.append(key)

    if applied:
        logger.info(
            "Applied %d configured environment variable(s): %s",
            len(applied),
            ", ".join(f"{name}=<hidden>" if _is_sensitive(name) else name for name in applied),
        )
    return applied
