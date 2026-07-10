"""
T013: mcp_json_import 单元测试 — 3-format parsing + batch import + secret detection + fuzz。
"""

import json
import pytest

from src.business.mcp.mcp_json_import import (
    McpJsonParseError,
    McpServerParsedPreview,
    parse_mcp_json,
    detect_secret_keys_in_dict,
)


class TestMcpJsonImport:
    """JSON 配置解析测试。"""

    # ─── 格式 1: 嵌套 mcpServers ───

    def test_parse_nested_mcp_servers_single(self):
        """解析单个嵌套 server。"""
        json_text = json.dumps(
            {
                "mcpServers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    }
                }
            }
        )
        result = parse_mcp_json(json_text)
        assert len(result) == 1
        assert result[0].name == "filesystem"
        assert result[0].transport == "stdio"
        assert result[0].command == "npx"

    def test_parse_nested_mcp_servers_multiple(self):
        """解析多个嵌套 server。"""
        json_text = json.dumps(
            {
                "mcpServers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                    },
                    "github": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-github"],
                        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"},
                    },
                }
            }
        )
        result = parse_mcp_json(json_text)
        assert len(result) == 2
        names = [r.name for r in result]
        assert "filesystem" in names
        assert "github" in names

    # ─── 格式 2: 裸 stdio ───

    def test_parse_bare_stdio(self):
        """解析裸 stdio server 对象。"""
        json_text = json.dumps(
            {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                "env": {"PATH": "/usr/bin"},
            }
        )
        result = parse_mcp_json(json_text)
        assert len(result) == 1
        assert result[0].transport == "stdio"
        assert result[0].command == "npx"

    def test_parse_bare_stdio_with_env(self):
        """解析带 env 的裸 stdio 对象。"""
        json_text = json.dumps(
            {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_abc123"},
            }
        )
        result = parse_mcp_json(json_text)
        assert len(result) == 1
        assert "GITHUB_PERSONAL_ACCESS_TOKEN" in result[0].detected_secret_keys

    # ─── 格式 3: 裸 HTTP ───

    def test_parse_bare_http(self):
        """解析裸 HTTP server 对象。"""
        json_text = json.dumps(
            {
                "url": "http://localhost:8000/mcp",
                "headers": {"Authorization": "Bearer token123"},
            }
        )
        result = parse_mcp_json(json_text)
        assert len(result) == 1
        assert result[0].transport == "http"
        assert result[0].url == "http://localhost:8000/mcp"

    # ─── Secret 检测 ───

    def test_detect_secret_keys(self):
        """启发式检测 secret 键名（E9）。"""
        env = {
            "PATH": "/usr/bin",
            "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx",
            "API_KEY": "sk-xxx",
            "SECRET_VAR": "secret_val",
            "PASSWORD": "pass123",
            "CREDENTIAL_FILE": "/path",
            "AUTH_TOKEN": "auth_xxx",
            "NORMAL_VAR": "value",
        }
        secrets = detect_secret_keys_in_dict(env)
        assert "GITHUB_PERSONAL_ACCESS_TOKEN" in secrets
        assert "API_KEY" in secrets
        assert "SECRET_VAR" in secrets
        assert "PASSWORD" in secrets
        assert "CREDENTIAL_FILE" in secrets
        assert "AUTH_TOKEN" in secrets
        assert "PATH" not in secrets
        assert "NORMAL_VAR" not in secrets

    def test_detect_secret_keys_in_headers(self):
        """检测 header 中的 secret 键。"""
        json_text = json.dumps(
            {
                "url": "http://localhost:8000/mcp",
                "headers": {"X-API-KEY": "sk-xxx", "Authorization": "Bearer xxx"},
            }
        )
        result = parse_mcp_json(json_text)
        assert "X-API-KEY" in result[0].detected_secret_keys

    # ─── ${VAR} 占位符检测 ───

    def test_detect_placeholder_keys(self):
        """检测 ${VAR} 占位符键名。"""
        json_text = json.dumps(
            {
                "command": "npx",
                "env": {"GITHUB_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"},
            }
        )
        result = parse_mcp_json(json_text)
        assert "GITHUB_TOKEN" in result[0].placeholder_keys

    # ─── 错误处理 ───

    def test_parse_invalid_json(self):
        """无效 JSON 抛 McpJsonParseError。"""
        with pytest.raises(McpJsonParseError):
            parse_mcp_json("not json at all")

    def test_parse_non_object_json(self):
        """非对象 JSON 抛错误。"""
        with pytest.raises(McpJsonParseError):
            parse_mcp_json(json.dumps([1, 2, 3]))

    def test_parse_empty_mcp_servers(self):
        """空 mcpServers 对象抛错误。"""
        with pytest.raises(McpJsonParseError):
            parse_mcp_json(json.dumps({"mcpServers": {}}))

    # ─── Fuzz 测试 ───

    def test_fuzz_malformed_configs(self):
        """各种畸形配置不崩溃。"""
        malformed = [
            '{"mcpServers": {"x": null}}',  # null config
            '{"mcpServers": {"x": 123}}',  # number config
            '{"command": "", "args": "not_array"}',  # wrong args type
            '{"url": "", "headers": "not_dict"}',  # wrong headers type
        ]
        for text in malformed:
            try:
                parse_mcp_json(text)
            except McpJsonParseError:
                pass  # 预期错误

    def test_parsed_preview_to_dict(self):
        """McpServerParsedPreview 序列化。"""
        preview = McpServerParsedPreview(
            name="test",
            transport="stdio",
            command="npx",
            detected_secret_keys=["KEY"],
        )
        d = preview.to_dict()
        assert d["name"] == "test"
        assert d["transport"] == "stdio"
        assert "KEY" in d["detectedSecretKeys"]
