"""
T006: McpServerRepository 单元测试 — CRUD + name uniqueness + list filters + status update。
"""

import json
import pytest

from src.data.repos.mcp_server_repository import McpServerRepository
from src.data.repos.base_repository import ID_PREFIX_MCP_SERVER


class TestMcpServerRepository:
    """McpServerRepository CRUD 测试。"""

    def test_create_server_basic(self):
        """基本创建。"""
        with McpServerRepository() as repo:
            row = repo.create_server(
                name="test-server",
                transport="stdio",
                command="npx",
                args=["-y", "test-mcp-server"],
            )
            assert row.server_id.startswith(ID_PREFIX_MCP_SERVER)
            assert row.name == "test-server"
            assert row.transport == "stdio"
            assert row.command == "npx"
            assert row.enabled is True
            assert row.is_preset is False

    def test_create_server_with_env(self):
        """带环境变量创建。"""
        with McpServerRepository() as repo:
            row = repo.create_server(
                name="env-server",
                transport="stdio",
                command="npx",
                env={"PATH": "/usr/bin"},
                secret_env_keys=["API_KEY"],
            )
            env = json.loads(row.env_json)
            assert env == {"PATH": "/usr/bin"}
            secret_keys = json.loads(row.secret_env_keys_json)
            assert secret_keys == ["API_KEY"]

    def test_create_server_name_uniqueness(self):
        """名称唯一约束。"""
        with McpServerRepository() as repo:
            repo.create_server(
                name="unique-name",
                transport="stdio",
                command="cmd1",
            )
        with pytest.raises(ValueError, match="名称已存在"):
            with McpServerRepository() as repo:
                repo.create_server(
                    name="unique-name",
                    transport="stdio",
                    command="cmd2",
                )

    def test_get_by_id(self):
        """按 ID 查询。"""
        with McpServerRepository() as repo:
            created = repo.create_server(
                name="getbyid-server",
                transport="stdio",
                command="npx",
            )
        with McpServerRepository() as repo:
            found = repo.get_by_id(created.server_id)
            assert found is not None
            assert found.name == "getbyid-server"

    def test_get_by_id_not_found(self):
        """ID 不存在返回 None。"""
        with McpServerRepository() as repo:
            assert repo.get_by_id("mcs_nonexistent") is None

    def test_get_by_name(self):
        """按名称查询。"""
        with McpServerRepository() as repo:
            repo.create_server(
                name="findme-server",
                transport="stdio",
                command="npx",
            )
        with McpServerRepository() as repo:
            found = repo.get_by_name("findme-server")
            assert found is not None
            assert found.transport == "stdio"

    def test_list_all(self):
        """列出所有 server。"""
        with McpServerRepository() as repo:
            repo.create_server(name="list-a", transport="stdio", command="a")
            repo.create_server(name="list-b", transport="stdio", command="b")
        with McpServerRepository() as repo:
            all_servers = repo.list_all()
            names = [s.name for s in all_servers]
            assert "list-a" in names
            assert "list-b" in names

    def test_list_enabled(self):
        """只列出启用的 server。"""
        with McpServerRepository() as repo:
            repo.create_server(name="enabled-srv", transport="stdio", command="a", enabled=True)
            repo.create_server(name="disabled-srv", transport="stdio", command="b", enabled=False)
        with McpServerRepository() as repo:
            enabled = repo.list_enabled()
            names = [s.name for s in enabled]
            assert "enabled-srv" in names
            assert "disabled-srv" not in names

    def test_list_preset_slugs(self):
        """列出预置 server slug。"""
        with McpServerRepository() as repo:
            repo.create_server(
                name="Preset GitHub",
                transport="stdio",
                command="npx",
                is_preset=True,
                preset_slug="github",
            )
            repo.create_server(
                name="Custom Server",
                transport="stdio",
                command="custom",
            )
        with McpServerRepository() as repo:
            slugs = repo.list_preset_slugs()
            assert "github" in slugs

    def test_update_config(self):
        """更新配置字段。"""
        with McpServerRepository() as repo:
            row = repo.create_server(
                name="update-server",
                transport="stdio",
                command="old-cmd",
            )
            server_id = row.server_id
        with McpServerRepository() as repo:
            updated = repo.update_config(server_id, command="new-cmd")
            assert updated is not None
            assert updated.command == "new-cmd"

    def test_update_config_with_json_fields(self):
        """更新 JSON 字段（args/env/headers）。"""
        with McpServerRepository() as repo:
            row = repo.create_server(
                name="json-update-server",
                transport="stdio",
                command="npx",
            )
            server_id = row.server_id
        with McpServerRepository() as repo:
            updated = repo.update_config(
                server_id,
                args=["-y", "new-args"],
                env={"KEY": "value"},
            )
            assert updated is not None
            assert json.loads(updated.args_json) == ["-y", "new-args"]
            assert json.loads(updated.env_json) == {"KEY": "value"}

    def test_set_enabled(self):
        """设置 enabled 状态。"""
        with McpServerRepository() as repo:
            row = repo.create_server(
                name="toggle-server",
                transport="stdio",
                command="npx",
                enabled=True,
            )
            server_id = row.server_id
        with McpServerRepository() as repo:
            disabled = repo.set_enabled(server_id, False)
            assert disabled is not None
            assert disabled.enabled is False

    def test_update_status(self):
        """更新运行时状态。"""
        with McpServerRepository() as repo:
            row = repo.create_server(
                name="status-server",
                transport="stdio",
                command="npx",
            )
            server_id = row.server_id
        with McpServerRepository() as repo:
            updated = repo.update_status(
                server_id,
                status="running",
                tool_count=5,
            )
            assert updated is not None
            assert updated.last_known_status == "running"
            assert updated.tool_count == 5

    def test_update_status_all_optional_fields(self):
        """更新状态时设置 error/suggestion/tools_json/circuit_breaker_open。"""
        with McpServerRepository() as repo:
            row = repo.create_server(
                name="optional-fields-server",
                transport="stdio",
                command="npx",
            )
            server_id = row.server_id
        with McpServerRepository() as repo:
            updated = repo.update_status(
                server_id,
                status="failed",
                error="connection refused",
                suggestion="检查 server 是否运行",
                tool_count=0,
                tools_json='[{"name": "test"}]',
                circuit_breaker_open=True,
            )
            assert updated is not None
            assert updated.last_known_status == "failed"
            assert updated.last_error_message == "connection refused"
            assert updated.suggestion == "检查 server 是否运行"
            assert updated.tool_count == 0
            assert updated.tools_json == '[{"name": "test"}]'
            assert updated.circuit_breaker_open is True

    def test_update_status_nonexistent_returns_none(self):
        """更新不存在的 server 返回 None。"""
        with McpServerRepository() as repo:
            result = repo.update_status("mcs_nonexistent", status="running")
            assert result is None

    def test_update_config_nonexistent_returns_none(self):
        """更新不存在的 server 配置返回 None。"""
        with McpServerRepository() as repo:
            result = repo.update_config("mcs_nonexistent", name="test")
            assert result is None

    def test_delete_server(self):
        """删除 server。"""
        with McpServerRepository() as repo:
            row = repo.create_server(
                name="delete-server",
                transport="stdio",
                command="npx",
            )
            server_id = row.server_id
        with McpServerRepository() as repo:
            assert repo.delete_server(server_id) is True
        with McpServerRepository() as repo:
            assert repo.get_by_id(server_id) is None

    def test_delete_server_not_found(self):
        """删除不存在的 server 返回 False。"""
        with McpServerRepository() as repo:
            assert repo.delete_server("mcs_nonexistent") is False

    def test_preset_server_creation(self):
        """创建预置 server。"""
        with McpServerRepository() as repo:
            row = repo.create_server(
                name="filesystem",
                transport="stdio",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem"],
                is_preset=True,
                preset_slug="filesystem",
                enabled=False,
            )
            assert row.is_preset is True
            assert row.preset_slug == "filesystem"
            assert row.enabled is False
