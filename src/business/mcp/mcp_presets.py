"""
MCP 预置 server 默认配置（N19: 引导种子数据）。
"""

import platform
from typing import Any


def _npx_command() -> str:
    """Windows 下 npx 需通过 cmd /c 包装，否则 stdio_client 无法 spawn .cmd 文件。"""
    return "cmd" if platform.system() == "Windows" else "npx"


def _npx_args(base_args: list[str]) -> list[str]:
    """Windows 下在 npx args 前插入 /c npx。"""
    if platform.system() == "Windows":
        return ["/c", "npx", *base_args]
    return base_args


class PresetServerConfig:
    """预置 server 配置描述。"""

    def __init__(
        self,
        slug: str,
        name: str,
        command: str,
        args: list[str] | None = None,
        non_secret_env: dict[str, str] | None = None,
        description: str = "",
    ):
        self.slug = slug
        self.name = name
        self.command = command
        self.args = args or []
        self.non_secret_env = non_secret_env or {}
        self.description = description

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "non_secret_env": self.non_secret_env,
            "description": self.description,
        }


# Windows 下的 npx 调用需要通过 cmd /c 包装
_PRESET_SERVERS: list[PresetServerConfig] = [
    PresetServerConfig(
        slug="filesystem",
        name="filesystem",
        command=_npx_command(),
        args=_npx_args(["-y", "@modelcontextprotocol/server-filesystem"]),
        non_secret_env={},
        description="文件系统操作（读取/写入/搜索文件）",
    ),
    PresetServerConfig(
        slug="github",
        name="github",
        command=_npx_command(),
        args=_npx_args(["-y", "@modelcontextprotocol/server-github"]),
        non_secret_env={},
        description="GitHub 操作（PR/Issue/搜索等），需要 API token",
    ),
]


def load_preset_defaults() -> list[PresetServerConfig]:
    """加载预置 server 默认配置列表。"""
    return list(_PRESET_SERVERS)


def get_preset_by_slug(slug: str) -> PresetServerConfig | None:
    """按 slug 查找预置 server。"""
    for preset in _PRESET_SERVERS:
        if preset.slug == slug:
            return preset
    return None
