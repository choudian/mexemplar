"""
McpServerRepository — MCP server 配置数据仓库。
"""

import json
import logging
from typing import Any, Optional

from src.data.models_sqlite import McpServer
from src.data.repos.base_repository import BaseRepository, ID_PREFIX_MCP_SERVER, generate_id
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)


class McpServerRepository(BaseRepository):
    """MCP server 配置仓库。"""

    def create_server(
        self,
        *,
        name: str,
        transport: str,
        command: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        secret_header_keys: list[str] | None = None,
        env: dict[str, str] | None = None,
        secret_env_keys: list[str] | None = None,
        is_preset: bool = False,
        preset_slug: str | None = None,
        enabled: bool = True,
    ) -> McpServer:
        """创建 MCP server 配置行。"""
        if self.get_by_name(name) is not None:
            raise ValueError(f"MCP server 名称已存在: {name}")

        now = utc_now_naive()
        row = McpServer(
            server_id=generate_id("mcs"),
            name=name,
            transport=transport,
            command=command,
            args_json=json.dumps(args) if args else None,
            url=url,
            headers_json=json.dumps(headers) if headers else None,
            secret_header_keys_json=json.dumps(secret_header_keys) if secret_header_keys else None,
            env_json=json.dumps(env) if env else None,
            secret_env_keys_json=json.dumps(secret_env_keys) if secret_env_keys else None,
            enabled=enabled,
            is_preset=is_preset,
            preset_slug=preset_slug,
            created_at=now,
            updated_at=now,
        )
        return self._add_and_flush(row)

    def get_by_id(self, server_id: str) -> McpServer | None:
        """按主键查询。"""
        return self.session.get(McpServer, server_id)

    def get_by_name(self, name: str) -> McpServer | None:
        """按名称查询（唯一）。"""
        return self.session.query(McpServer).filter(McpServer.name == name).first()

    def list_all(self) -> list[McpServer]:
        """列出所有 server 配置。"""
        return self.session.query(McpServer).order_by(McpServer.created_at).all()

    def list_enabled(self) -> list[McpServer]:
        """列出所有启用的 server。"""
        return (
            self.session.query(McpServer)
            .filter(McpServer.enabled.is_(True))
            .order_by(McpServer.created_at)
            .all()
        )

    def list_preset_slugs(self) -> list[str]:
        """列出所有预置 server 的 slug（N19: 引导种子数据用）。"""
        rows = (
            self.session.query(McpServer.preset_slug)
            .filter(McpServer.is_preset.is_(True), McpServer.preset_slug.isnot(None))
            .all()
        )
        return [r[0] for r in rows]

    def update_config(self, server_id: str, **fields: Any) -> McpServer | None:
        """更新 server 配置字段（合并更新）。"""
        row = self.get_by_id(server_id)
        if row is None:
            return None

        # JSON 字段需序列化
        json_fields = {
            "args_json": "args",
            "headers_json": "headers",
            "secret_header_keys_json": "secret_header_keys",
            "env_json": "env",
            "secret_env_keys_json": "secret_env_keys",
            "tools_json": "tools",
        }
        for json_col, param_name in json_fields.items():
            if param_name in fields:
                val = fields.pop(param_name)
                setattr(row, json_col, json.dumps(val) if val is not None else None)

        # 可更新字段白名单（禁止修改 server_id/created_at/name 等关键字段）
        # name 不可改：slug 由 name 派生，改名会导致 mcp__<slug>__<tool> 全名变化
        _ALLOWED_UPDATE_FIELDS = {
            "command", "url", "enabled",
            "is_preset", "preset_slug",
            "last_known_status", "last_error_message",
            "suggestion", "tool_count", "circuit_breaker_open",
        }

        for key, value in fields.items():
            if key in _ALLOWED_UPDATE_FIELDS:
                setattr(row, key, value)

        row.updated_at = utc_now_naive()
        return self._update_and_flush(row)

    def set_enabled(self, server_id: str, enabled: bool) -> McpServer | None:
        """设置 enabled 状态。"""
        row = self.get_by_id(server_id)
        if row is None:
            return None
        row.enabled = enabled
        row.updated_at = utc_now_naive()
        return self._update_and_flush(row)

    def update_status(
        self,
        server_id: str,
        status: str | None,
        error: str | None = None,
        suggestion: str | None = None,
        tool_count: int | None = None,
        tools_json: str | None = None,
        circuit_breaker_open: bool | None = None,
    ) -> McpServer | None:
        """更新运行时状态缓存。"""
        row = self.get_by_id(server_id)
        if row is None:
            return None
        if status is not None:
            row.last_known_status = status
        if error is not None:
            row.last_error_message = error
        if suggestion is not None:
            row.suggestion = suggestion
        if tool_count is not None:
            row.tool_count = tool_count
        if tools_json is not None:
            row.tools_json = tools_json
        if circuit_breaker_open is not None:
            row.circuit_breaker_open = circuit_breaker_open
        row.updated_at = utc_now_naive()
        return self._update_and_flush(row)

    def delete_server(self, server_id: str) -> bool:
        """删除 server 配置行。"""
        row = self.get_by_id(server_id)
        if row is None:
            return False
        self.session.delete(row)
        self._commit()
        return True
