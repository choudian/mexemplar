"""
MCP JSON 配置解析 — 支持三种粘贴导入格式 + secret 自动检测启发式。

格式 1: Claude Desktop 嵌套 mcpServers 格式
格式 2: 裸 stdio server 对象
格式 3: 裸 HTTP server 对象
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

# secret 自动检测关键词（E9，不区分大小写）
_SECRET_KEY_PATTERNS = re.compile(r"(token|key|secret|password|credential|auth)", re.IGNORECASE)


class McpJsonParseError(ValueError):
    """JSON 解析失败。"""

    pass


class McpServerParsedPreview:
    """解析后的 server 预览（不落库，返回前端确认/编辑）。"""

    def __init__(
        self,
        name: str,
        transport: str,
        command: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        env: dict[str, str] | None = None,
        detected_secret_keys: list[str] | None = None,
        placeholder_keys: list[str] | None = None,
    ):
        self.name = name
        self.transport = transport
        self.command = command
        self.args = args or []
        self.url = url
        self.headers = headers or {}
        self.env = env or {}
        self.detected_secret_keys = detected_secret_keys or []
        self.placeholder_keys = placeholder_keys or []

    def __repr__(self) -> str:
        # RC5: repr 遮罩 secret 值，防止意外泄漏到日志
        masked_env = {
            k: ("***" if k in self.detected_secret_keys else v) for k, v in self.env.items()
        }
        masked_headers = {
            k: ("***" if k in self.detected_secret_keys else v) for k, v in self.headers.items()
        }
        return (
            f"McpServerParsedPreview(name={self.name!r}, transport={self.transport!r}, "
            f"env=<{len(masked_env)} keys, masked>, headers=<{len(masked_headers)} keys, masked>)"
        )

    def to_dict(self) -> dict:
        """序列化为 API 响应 dict。secret 值被遮罩，只保留键名列表。"""
        # 遮罩 detected secret 值，防止通过预览 API 泄漏
        safe_env = {
            k: ("***" if k in self.detected_secret_keys else v) for k, v in self.env.items()
        }
        safe_headers = {
            k: ("***" if k in self.detected_secret_keys else v) for k, v in self.headers.items()
        }
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": self.args,
            "url": self.url,
            "headers": safe_headers,
            "env": safe_env,
            "detectedSecretKeys": self.detected_secret_keys,
            "placeholderKeys": self.placeholder_keys,
        }


def parse_mcp_json(json_text: str) -> list[McpServerParsedPreview]:
    """解析 MCP JSON 配置，自动检测格式。

    支持三种格式：
    1. 嵌套 mcpServers 格式: {"mcpServers": {"name": {...}, ...}}
    2. 裸 stdio server 对象: {"command": "...", "args": [...], "env": {...}}
    3. 裸 HTTP server 对象: {"url": "..."}

    Returns:
        解析后的 server 预览列表
    """
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise McpJsonParseError(f"JSON 格式无效: {e}") from e

    if not isinstance(data, dict):
        raise McpJsonParseError("JSON 必须是对象")

    # 格式 1: 嵌套 mcpServers
    if "mcpServers" in data and isinstance(data["mcpServers"], dict):
        servers = []
        for name, config in data["mcpServers"].items():
            if not isinstance(config, dict):
                continue
            servers.append(_parse_single_server(name, config))
        if not servers:
            raise McpJsonParseError("mcpServers 对象中没有有效的 server 配置")
        return servers

    # 格式 2/3: 裸 server 对象
    return [_parse_single_server("imported", data)]


def _parse_single_server(name: str, config: dict) -> McpServerParsedPreview:
    """解析单个 server 配置对象。"""
    command = config.get("command")
    url = config.get("url")
    args = config.get("args", [])
    env = config.get("env", {})
    headers = config.get("headers", {})

    # 确定传输类型
    if url and not command:
        transport = "http"
    else:
        transport = "stdio"

    # 类型校验
    if not isinstance(args, list):
        args = []
    if not isinstance(env, dict):
        env = {}
    if not isinstance(headers, dict):
        headers = {}

    # 检测 secret 键
    detected_secret_keys = _detect_secret_keys(env, headers)

    # 检测 ${VAR} 占位符
    placeholder_keys = _detect_placeholder_keys(env, headers)

    return McpServerParsedPreview(
        name=name,
        transport=transport,
        command=command,
        args=args,
        url=url,
        headers=headers,
        env=env,
        detected_secret_keys=detected_secret_keys,
        placeholder_keys=placeholder_keys,
    )


def _detect_secret_keys(env: dict, headers: dict) -> list[str]:
    """启发式检测 secret 键名（E9）。

    key 名包含 TOKEN/KEY/SECRET/PASSWORD/CREDENTIAL/AUTH 时自动标记为 secret。
    """
    secret_keys: list[str] = []

    for key in env:
        if _SECRET_KEY_PATTERNS.search(key):
            if key not in secret_keys:
                secret_keys.append(key)

    for key in headers:
        if _SECRET_KEY_PATTERNS.search(key):
            if key not in secret_keys:
                secret_keys.append(key)

    return secret_keys


def _detect_placeholder_keys(env: dict, headers: dict) -> list[str]:
    """检测 ${VAR} 占位符键名。"""
    placeholder_re = re.compile(r"\$\{[^}]+\}")
    keys: list[str] = []

    for key, value in env.items():
        if isinstance(value, str) and placeholder_re.search(value):
            if key not in keys:
                keys.append(key)

    for key, value in headers.items():
        if isinstance(value, str) and placeholder_re.search(value):
            if key not in keys:
                keys.append(key)

    return keys


def detect_secret_keys_in_dict(data: dict[str, str]) -> list[str]:
    """对外接口：检测 dict 中的 secret 键名。"""
    return _detect_secret_keys(data, {})
