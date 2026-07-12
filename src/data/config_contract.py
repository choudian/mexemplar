"""Configuration contract shared by file loading, templates, and tests.

The contract derives ordinary file-backed keys from AppConfig. Only exceptional
paths need explicit rules, which keeps schema defaults as the single source of
truth.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import json
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


class ConfigScope(str, Enum):
    FILE_DB = "file_db"
    DB_ONLY = "db_only"
    RUNTIME_ONLY = "runtime_only"
    DEPRECATED = "deprecated"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ConfigRule:
    pattern: str
    scope: ConfigScope
    template_allowed: bool
    secret: bool = False
    replacement: str | None = None


@dataclass(frozen=True)
class ConfigViolation:
    path: str
    code: str


_SECRET_RULES = (
    "ai.api_key",
    "ai.vision_api_key",
    "ai.embedding_api_key",
    "ai.compression_model_api_key",
    "self_improvement.execution_review.model.api_key",
    "web.brave_api_key",
    "skill_store.skills_sh_api_key",
    "agent_tools.output.semantic_summary.api_key",
    "mcp.servers.*.env.*",
    "mcp.servers.*.headers.*",
)

_RULES = (
    ConfigRule(
        "memory.reference_steps_threshold",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "memory.reference_size_threshold",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "memory.compression_token_threshold",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "memory.compression_count_threshold",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "memory.compression_keep_recent",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "memory.compression_trigger_strategy",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    # This is a typed nested profile. The container itself is consumed by one
    # getter, while its leaves are derived from AppConfig below.
    ConfigRule(
        "self_improvement.execution_review.model",
        ConfigScope.FILE_DB,
        template_allowed=True,
    ),
    ConfigRule(
        "ai.compression_model_provider",
        ConfigScope.DEPRECATED,
        template_allowed=False,
        replacement="inherit the primary model profile",
    ),
    ConfigRule(
        "ai.compression_model_name",
        ConfigScope.DEPRECATED,
        template_allowed=False,
        replacement="inherit the primary model profile",
    ),
    ConfigRule(
        "ai.compression_model_api_key",
        ConfigScope.DEPRECATED,
        template_allowed=False,
        secret=True,
        replacement="inherit the primary model profile",
    ),
    ConfigRule(
        "ai.compression_model_base_url",
        ConfigScope.DEPRECATED,
        template_allowed=False,
        replacement="inherit the primary model profile",
    ),
    ConfigRule("debug", ConfigScope.DEPRECATED, template_allowed=False),
    ConfigRule("debug.*", ConfigScope.RUNTIME_ONLY, template_allowed=False),
    ConfigRule("ui.language", ConfigScope.DEPRECATED, template_allowed=False),
    ConfigRule("ui.window_width", ConfigScope.DEPRECATED, template_allowed=False),
    ConfigRule("ui.window_height", ConfigScope.DEPRECATED, template_allowed=False),
    ConfigRule("recording.record_mouse_move", ConfigScope.DEPRECATED, template_allowed=False),
    ConfigRule(
        "recording.enable_video_recording",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule("recording.video_fps", ConfigScope.DEPRECATED, template_allowed=False),
    ConfigRule("recording.video_quality", ConfigScope.DEPRECATED, template_allowed=False),
    ConfigRule(
        "recording.default_recording_mode",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule("recording.browser_type", ConfigScope.DEPRECATED, template_allowed=False),
    ConfigRule(
        "recording.browser_headless",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "recording.capture_network_requests",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "recording.network_request_filter",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "recording.network_request_timeout",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "recording.websocket.enabled",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "recording.websocket.ping_interval",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "recording.websocket.max_reconnect_attempts",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "recording.websocket.reconnect_delay",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "recording.websocket.message_queue_size",
        ConfigScope.DEPRECATED,
        template_allowed=False,
    ),
    ConfigRule(
        "mcp.servers.*.env.*",
        ConfigScope.DB_ONLY,
        template_allowed=False,
        secret=True,
    ),
    ConfigRule(
        "mcp.servers.*.headers.*",
        ConfigScope.DB_ONLY,
        template_allowed=False,
        secret=True,
    ),
)


def flatten_mapping(mapping: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Return dotted leaf paths without transforming their values."""

    result: dict[str, Any] = {}
    for key, value in mapping.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            result.update(flatten_mapping(value, path))
        else:
            result[path] = value
    return result


@lru_cache(maxsize=1)
def schema_leaf_paths() -> frozenset[str]:
    """Derive ordinary file-backed paths from the AppConfig dataclass."""

    from src.data.config_models import AppConfig

    data = dataclasses.asdict(AppConfig())
    return frozenset(flatten_mapping(data))


class ConfigContract:
    """A small interface for classifying and validating configuration paths."""

    def classify(self, path: str) -> ConfigRule:
        for rule in _RULES:
            if fnmatch.fnmatchcase(path, rule.pattern):
                return rule
        if path in schema_leaf_paths():
            return ConfigRule(
                path,
                ConfigScope.FILE_DB,
                template_allowed=True,
                secret=any(fnmatch.fnmatchcase(path, pattern) for pattern in _SECRET_RULES),
            )
        return ConfigRule(path, ConfigScope.UNKNOWN, template_allowed=False)

    def validate_schema(self, paths: set[str] | frozenset[str]) -> tuple[ConfigViolation, ...]:
        violations = [
            ConfigViolation(path, "unknown_schema_path")
            for path in paths
            if self.classify(path).scope is ConfigScope.UNKNOWN
        ]
        return tuple(sorted(violations, key=lambda violation: violation.path))

    def validate_mapping(
        self,
        mapping: Mapping[str, Any],
        *,
        template: bool,
    ) -> tuple[ConfigViolation, ...]:
        violations: list[ConfigViolation] = []
        for path, value in flatten_mapping(mapping).items():
            rule = self.classify(path)
            if rule.scope is ConfigScope.UNKNOWN:
                violations.append(ConfigViolation(path, "unknown_path"))
                continue
            if template and not rule.template_allowed:
                violations.append(ConfigViolation(path, "template_disallowed"))
            if template and rule.secret and value not in (None, ""):
                violations.append(ConfigViolation(path, "template_secret_present"))
        return tuple(sorted(violations, key=lambda violation: (violation.path, violation.code)))

    def deprecated_paths(self, mapping: Mapping[str, Any]) -> tuple[str, ...]:
        return tuple(
            sorted(
                path
                for path in flatten_mapping(mapping)
                if self.classify(path).scope is ConfigScope.DEPRECATED
            )
        )

    def non_file_paths(self, mapping: Mapping[str, Any]) -> tuple[str, ...]:
        """Return runtime-only, DB-only, and deprecated leaves in a file mapping."""

        non_file_scopes = {
            ConfigScope.DB_ONLY,
            ConfigScope.RUNTIME_ONLY,
            ConfigScope.DEPRECATED,
        }
        return tuple(
            sorted(
                path
                for path in flatten_mapping(mapping)
                if self.classify(path).scope in non_file_scopes
            )
        )


DEFAULT_CONFIG_CONTRACT = ConfigContract()


def validate_template_file(path: Path) -> tuple[ConfigViolation, ...]:
    """Strictly load and validate a shipped JSON template."""

    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return (ConfigViolation(str(path), "invalid_json"),)

    if not isinstance(data, Mapping):
        return (ConfigViolation(str(path), "template_not_object"),)
    return DEFAULT_CONFIG_CONTRACT.validate_mapping(data, template=True)


def omit_deprecated_paths(mapping: dict[str, Any]) -> None:
    """Remove deprecated leaves in place before serializing a user template."""

    for path in DEFAULT_CONFIG_CONTRACT.deprecated_paths(mapping):
        parts = path.split(".")
        node: dict[str, Any] | None = mapping
        for part in parts[:-1]:
            candidate = node.get(part) if node is not None else None
            if not isinstance(candidate, dict):
                node = None
                break
            node = candidate
        if node is not None:
            node.pop(parts[-1], None)
