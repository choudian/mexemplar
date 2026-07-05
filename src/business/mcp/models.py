"""
MCP 业务模型 — 不含 SDK 类型的纯业务层类型（N9）。
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

logger = logging.getLogger(__name__)


class McpServerStatus(str, Enum):
    """MCP server 连接状态。"""

    STARTING = "starting"
    RUNNING = "running"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True)
class McpToolInfo:
    """单个 MCP 工具的缓存信息（业务层类型，N9）。不可变以保证线程安全。"""

    name: str  # 原始工具名（如 "list_prs"）
    description: str
    input_schema: dict[str, Any]  # JSON Schema

    def to_dict(self) -> dict:
        """序列化为 dict（用于 tools_json 缓存）。"""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "McpToolInfo":
        """从 dict 反序列化。"""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            input_schema=data.get("inputSchema", {}),
        )


@dataclass(frozen=True)
class McpCallResult:
    """业务层工具调用结果（不含 SDK 类型，N9）。不可变以保证线程安全。"""

    is_error: bool
    text_parts: list[str]
    image_count: int
    structured_data: dict[str, Any] | None  # 来自 SDK structuredContent


@dataclass(frozen=True)
class McpServerConfigPublic:
    """不含 secret 的 server 配置，可安全缓存、日志、序列化（N17）。不可变以保证线程安全。"""

    server_id: str
    name: str
    transport: Literal["stdio", "http"]  # "stdio" | "http"
    command: str | None
    args: list[str]
    url: str | None
    non_secret_env: dict[str, str]  # 仅非 secret 的 env 值
    non_secret_headers: dict[str, str]  # 仅非 secret 的 header 值
    secret_env_keys: list[str]  # secret 键名列表（不含值）
    secret_header_keys: list[str]
    enabled: bool
    is_preset: bool
    preset_slug: str | None
    tool_count: int | None = None
    last_known_status: McpServerStatus | None = None

    def __repr__(self) -> str:
        """RC5: repr 不泄漏 secret 值。"""
        return (
            f"McpServerConfigPublic(server_id={self.server_id!r}, "
            f"name={self.name!r}, transport={self.transport!r}, "
            f"secret_env_keys={self.secret_env_keys!r}, "
            f"secret_header_keys={self.secret_header_keys!r})"
        )

    @classmethod
    def from_row(cls, row) -> "McpServerConfigPublic":
        """从 ORM 行构建（不查 UnifiedConfigManager，不含 secret 值）。"""
        args: list[str] = []
        if row.args_json:
            try:
                args = json.loads(row.args_json)
            except (json.JSONDecodeError, TypeError):
                args = []

        non_secret_env: dict[str, str] = {}
        if row.env_json:
            try:
                non_secret_env = json.loads(row.env_json)
            except (json.JSONDecodeError, TypeError):
                logger.warning("[MCP] Corrupted env_json for server %s", row.server_id)

        non_secret_headers: dict[str, str] = {}
        if row.headers_json:
            try:
                non_secret_headers = json.loads(row.headers_json)
            except (json.JSONDecodeError, TypeError):
                non_secret_headers = {}

        secret_env_keys: list[str] = []
        if row.secret_env_keys_json:
            try:
                secret_env_keys = json.loads(row.secret_env_keys_json)
            except (json.JSONDecodeError, TypeError):
                secret_env_keys = []

        secret_header_keys: list[str] = []
        if row.secret_header_keys_json:
            try:
                secret_header_keys = json.loads(row.secret_header_keys_json)
            except (json.JSONDecodeError, TypeError):
                secret_header_keys = []

        # last_known_status: str → McpServerStatus | None
        raw_status = row.last_known_status
        status: McpServerStatus | None = None
        if raw_status is not None:
            try:
                status = McpServerStatus(raw_status)
            except ValueError:
                logger.warning("[MCP] Unknown status %r for server %s", raw_status, row.server_id)

        return cls(
            server_id=row.server_id,
            name=row.name,
            transport=row.transport,
            command=row.command,
            args=args,
            url=row.url,
            non_secret_env=non_secret_env,
            non_secret_headers=non_secret_headers,
            secret_env_keys=secret_env_keys,
            secret_header_keys=secret_header_keys,
            enabled=row.enabled,
            is_preset=row.is_preset,
            preset_slug=row.preset_slug,
            tool_count=row.tool_count,
            last_known_status=status,
        )


@dataclass
class McpLaunchPayload:
    """启动子进程用的完整配置（含合并后的 secret env）。

    生命周期严格限定在 McpProcessManager.start_server 内部，
    绝不暴露给上层、不缓存（N17/RC5）。
    """

    command: str
    args: list[str]
    merged_env: dict[str, str] = field(repr=False)  # RC5: dataclass repr 不显示
    url: str | None = None
    merged_headers: dict[str, str] = field(default_factory=dict, repr=False)

    def __repr__(self) -> str:
        """RC5: class-level __repr__（dunder 在 type 上查，实例属性 override 不生效）。"""
        return (
            f"McpLaunchPayload(command={self.command!r}, args={self.args!r}, "
            f"<{len(self.merged_env)} env vars masked>)"
        )
