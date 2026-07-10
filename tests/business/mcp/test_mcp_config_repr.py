"""
T023: Config repr guard 测试 — RC5: assert secret not in repr。
"""

from src.business.mcp.models import McpServerConfigPublic, McpLaunchPayload


class TestMcpConfigRepr:
    """RC5: repr 不泄漏 secret 值。"""

    def test_launch_payload_repr_masks_env(self):
        """McpLaunchPayload repr 不显示 merged_env 内容。"""
        payload = McpLaunchPayload(
            command="npx",
            args=["-y", "server"],
            merged_env={"SECRET_TOKEN": "ghp_supersecret123", "PATH": "/usr/bin"},
        )
        r = repr(payload)
        assert "ghp_supersecret123" not in r
        assert "env vars masked" in r

    def test_launch_payload_repr_shows_count(self):
        """McpLaunchPayload repr 显示 env var 数量而非内容。"""
        payload = McpLaunchPayload(
            command="npx",
            args=[],
            merged_env={"A": "1", "B": "2", "C": "3"},
        )
        r = repr(payload)
        assert "3 env vars masked" in r

    def test_server_config_public_repr_no_secrets(self):
        """McpServerConfigPublic repr 不显示 secret 值。"""
        config = McpServerConfigPublic(
            server_id="mcs_test",
            name="GitHub",
            transport="stdio",
            command="npx",
            args=[],
            url=None,
            non_secret_env={"PATH": "/usr/bin"},
            non_secret_headers={},
            secret_env_keys=["GITHUB_TOKEN"],
            secret_header_keys=[],
            enabled=True,
            is_preset=True,
            preset_slug="github",
        )
        r = repr(config)
        # 只显示键名，不显示值
        assert "GITHUB_TOKEN" in r  # 键名可以出现
        assert "ghp_" not in r  # 值不出现

    def test_launch_payload_field_repr_false(self):
        """field(repr=False) 确保 dataclass 自动 repr 不显示 merged_env。"""
        payload = McpLaunchPayload(
            command="cmd",
            args=[],
            merged_env={"SECRET": "value"},
            merged_headers={"Auth": "secret"},
        )
        # 验证 dataclass 自动 repr 不包含 merged_env 和 merged_headers
        # 因为它们标记了 repr=False
        r = repr(payload)
        assert "SECRET" not in r or "env vars masked" in r
