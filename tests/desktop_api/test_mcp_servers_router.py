"""
T044/T050: MCP server API router 测试 — CRUD + 连接管理 + JSON 导入 + 断路器边界。

使用 FastAPI TestClient，mock McpServerService。
"""

import json
from collections.abc import Iterator
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.desktop_api.routers.mcp_servers import (
    McpServerCreateRequest,
    McpServerJsonImportRequest,
    McpServerUpdateRequest,
    router,
)


# ─── Fixtures ───


def _make_detail(
    server_id: str = "mcs_test",
    name: str = "test-server",
    transport: str = "stdio",
    command: str = "npx",
    enabled: bool = True,
    status: str | None = "stopped",
    tool_count: int | None = None,
    preset_slug: str | None = None,
    last_error: str | None = None,
    suggestion: str | None = None,
    circuit_breaker_open: bool = False,
) -> dict:
    """构造 McpServerResponse 兼容的详情 dict。"""
    return {
        "serverId": server_id,
        "name": name,
        "transport": transport,
        "command": command,
        "args": [],
        "url": None,
        "envKeys": [],
        "envMissingKeys": [],
        "envPresence": {},
        "headerKeys": [],
        "headerMissingKeys": [],
        "headerPresence": {},
        "enabled": enabled,
        "status": status,
        "toolCount": tool_count,
        "presetSlug": preset_slug,
        "lastError": last_error,
        "suggestion": suggestion,
        "circuitBreakerOpen": circuit_breaker_open,
        "createdAt": "2026-01-01T00:00:00",
        "updatedAt": "2026-01-01T00:00:00",
    }


@pytest.fixture
def mock_service():
    """模拟 McpServerService。"""
    svc = MagicMock()

    # 默认行为
    svc.add_server.return_value = _make_detail()
    svc.update_server.return_value = _make_detail(command="new-cmd")
    svc.delete_server.return_value = True
    svc.start_server.return_value = _make_detail(status="running")
    svc.stop_server.return_value = _make_detail(status="stopped")
    svc.reconnect_server.return_value = _make_detail(status="running")
    svc.list_servers.return_value = [_make_detail()]
    svc.get_server.return_value = _make_detail()
    svc.sdk_available = True
    svc._get_public_config.return_value = MagicMock()
    svc._start_and_register.return_value = [
        MagicMock(to_dict=lambda: {"name": "tool_a", "description": "", "inputSchema": {}})
    ]
    svc._get_server_detail.return_value = _make_detail()
    svc._process_manager = MagicMock()
    svc._registry = MagicMock()

    return svc


@pytest.fixture
def api_client(mock_service) -> TestClient:
    """创建注入 mock service 的 TestClient。"""

    def override_get_mcp_service() -> Iterator[MagicMock]:
        yield mock_service

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[router.routes[0].dependant.dependencies[0].call] = (
        override_get_mcp_service
    )

    # 更简洁：直接用 Depends override
    from src.desktop_api.routers.mcp_servers import get_mcp_service

    app.dependency_overrides[get_mcp_service] = lambda: mock_service

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


# ─── T044: US2 - 创建 + 列表 + 详情 + 测试连接 + JSON 导入 ───


class TestCreateMcpServer:
    """POST /api/mcp-servers: 创建 server。"""

    def test_create_server_success(self, api_client, mock_service):
        """正常创建 server 返回 201。"""
        mock_service.add_server.return_value = _make_detail(
            server_id="mcs_new", name="my-server"
        )

        resp = api_client.post(
            "/api/mcp-servers",
            json={
                "name": "my-server",
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "server"],
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "my-server"
        assert body["serverId"] == "mcs_new"

    def test_create_server_name_conflict_409(self, api_client, mock_service):
        """名称冲突返回 409。"""
        mock_service.add_server.side_effect = ValueError("MCP server 名称已存在: my-server")

        resp = api_client.post(
            "/api/mcp-servers",
            json={"name": "my-server", "transport": "stdio", "command": "npx"},
        )

        assert resp.status_code == 409
        assert "已存在" in resp.json()["detail"]

    def test_create_server_placeholder_rejection_422(self, api_client, mock_service):
        """包含未解析占位符返回 422。"""
        mock_service.add_server.side_effect = ValueError("以下环境变量占位符未解析: API_KEY")

        resp = api_client.post(
            "/api/mcp-servers",
            json={
                "name": "bad-srv",
                "transport": "stdio",
                "command": "npx",
                "env": {"API_KEY": "${MISSING}"},
            },
        )

        assert resp.status_code == 422
        assert "占位符" in resp.json()["detail"]

    def test_create_server_http_transport_422(self, api_client, mock_service):
        """HTTP transport 返回 422（CC-009）。"""
        mock_service.add_server.side_effect = ValueError("HTTP transport 尚未支持")

        resp = api_client.post(
            "/api/mcp-servers",
            json={"name": "http-srv", "transport": "http", "url": "http://example.com"},
        )

        assert resp.status_code == 422
        assert "HTTP" in resp.json()["detail"]


class TestListMcpServers:
    """GET /api/mcp-servers: 列出所有 server。"""

    def test_list_servers(self, api_client, mock_service):
        """返回 server 列表。"""
        mock_service.list_servers.return_value = [
            _make_detail(server_id="mcs_1", name="server-1"),
            _make_detail(server_id="mcs_2", name="server-2"),
        ]

        resp = api_client.get("/api/mcp-servers")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert body[0]["name"] == "server-1"
        assert body[1]["name"] == "server-2"


class TestGetMcpServer:
    """GET /api/mcp-servers/{id}: 获取单个 server。"""

    def test_get_server_found(self, api_client, mock_service):
        """存在的 server 返回详情。"""
        mock_service.get_server.return_value = _make_detail(
            server_id="mcs_x", name="found"
        )

        resp = api_client.get("/api/mcp-servers/mcs_x")

        assert resp.status_code == 200
        assert resp.json()["name"] == "found"

    def test_get_server_not_found_404(self, api_client, mock_service):
        """不存在的 server 返回 404。"""
        mock_service.get_server.return_value = None

        resp = api_client.get("/api/mcp-servers/mcs_missing")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]


class TestImportMcpJson:
    """POST /api/mcp-servers/import-json: JSON 粘贴导入。"""

    def test_import_json_success(self, api_client, mock_service):
        """有效 JSON 返回预览。"""
        from src.business.mcp.mcp_json_import import McpServerParsedPreview

        preview = McpServerParsedPreview(
            name="imported",
            transport="stdio",
            command="npx",
            args=["-y", "server"],
        )

        with patch(
            "src.desktop_api.routers.mcp_servers.parse_mcp_json",
            return_value=[preview],
        ):
            resp = api_client.post(
                "/api/mcp-servers/import-json",
                json={"jsonText": '{"mcpServers": {"imported": {"command": "npx"}}}'},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["servers"]) == 1
        assert body["servers"][0]["name"] == "imported"

    def test_import_json_invalid_422(self, api_client, mock_service):
        """无效 JSON 返回 422。"""
        from src.business.mcp.mcp_json_import import McpJsonParseError

        with patch(
            "src.desktop_api.routers.mcp_servers.parse_mcp_json",
            side_effect=McpJsonParseError("JSON 格式无效"),
        ):
            resp = api_client.post(
                "/api/mcp-servers/import-json",
                json={"jsonText": "not json"},
            )

        assert resp.status_code == 422


class TestTestConnection:
    """POST /api/mcp-servers/{id}/test-connection: 测试连接。"""

    def test_test_connection_success(self, api_client, mock_service):
        """连接成功返回工具列表。"""
        tool_mock = MagicMock()
        tool_mock.to_dict.return_value = {"name": "tool_a", "description": "", "inputSchema": {}}
        mock_service.test_connection.return_value = ([tool_mock], None)

        resp = api_client.post("/api/mcp-servers/mcs_test/test-connection")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["toolCount"] == 1

    def test_test_connection_failure(self, api_client, mock_service):
        """连接失败返回 success=False + error。"""
        mock_service.test_connection.return_value = ([], "spawn failed")

        resp = api_client.post("/api/mcp-servers/mcs_test/test-connection")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "spawn failed" in body["error"]

    def test_test_connection_sdk_unavailable(self, api_client, mock_service):
        """SDK 不可用时返回明确错误。"""
        mock_service.sdk_available = False

        resp = api_client.post("/api/mcp-servers/mcs_test/test-connection")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "SDK" in body["error"]

    def test_test_connection_server_not_found(self, api_client, mock_service):
        """server 不存在时返回 404。"""
        mock_service.get_server_detail.side_effect = LookupError("不存在")

        resp = api_client.post("/api/mcp-servers/mcs_missing/test-connection")

        assert resp.status_code == 404


# ─── T050: US3 - 更新 + 启用 + 禁用 + 重连 + 删除 ───


class TestUpdateMcpServer:
    """PATCH /api/mcp-servers/{id}: 更新 server 配置。"""

    def test_update_server_success(self, api_client, mock_service):
        """正常更新返回详情。"""
        mock_service.update_server.return_value = _make_detail(command="new-cmd")

        resp = api_client.patch(
            "/api/mcp-servers/mcs_test",
            json={"command": "new-cmd"},
        )

        assert resp.status_code == 200
        assert resp.json()["command"] == "new-cmd"

    def test_update_server_not_found_404(self, api_client, mock_service):
        """更新不存在的 server 返回 404。"""
        mock_service.update_server.side_effect = LookupError("不存在")

        resp = api_client.patch(
            "/api/mcp-servers/mcs_missing",
            json={"command": "new-cmd"},
        )

        assert resp.status_code == 404

    def test_update_server_validation_error_422(self, api_client, mock_service):
        """校验错误返回 422。"""
        mock_service.update_server.side_effect = ValueError("HTTP transport 尚未支持")

        resp = api_client.patch(
            "/api/mcp-servers/mcs_test",
            json={"command": "new-cmd"},
        )

        assert resp.status_code == 422


class TestEnableMcpServer:
    """POST /api/mcp-servers/{id}/enable: 启用 + 启动。"""

    def test_enable_server_success(self, api_client, mock_service):
        """启用 server 并启动。"""
        mock_service.enable_server.return_value = _make_detail(
            enabled=True, status="running"
        )

        resp = api_client.post("/api/mcp-servers/mcs_test/enable")

        assert resp.status_code == 200

    def test_enable_server_not_found_404(self, api_client, mock_service):
        """启用不存在的 server 返回 404。"""
        mock_service.enable_server.side_effect = LookupError("不存在")

        resp = api_client.post("/api/mcp-servers/mcs_missing/enable")

        assert resp.status_code == 404


class TestDisableMcpServer:
    """POST /api/mcp-servers/{id}/disable: 停止 + 禁用。"""

    def test_disable_server_success(self, api_client, mock_service):
        """禁用 server 并停止。"""
        mock_service.disable_server.return_value = _make_detail(
            enabled=False, status="stopped"
        )

        resp = api_client.post("/api/mcp-servers/mcs_test/disable")

        assert resp.status_code == 200

    def test_disable_server_not_found_404(self, api_client, mock_service):
        """禁用不存在的 server 返回 404。"""
        mock_service.disable_server.side_effect = LookupError("不存在")

        resp = api_client.post("/api/mcp-servers/mcs_missing/disable")

        assert resp.status_code == 404


class TestReconnectMcpServer:
    """POST /api/mcp-servers/{id}/reconnect: 重连。"""

    def test_reconnect_server_success(self, api_client, mock_service):
        """重连成功。"""
        mock_service.reconnect_server.return_value = _make_detail(status="running")

        resp = api_client.post("/api/mcp-servers/mcs_test/reconnect")

        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_reconnect_server_not_found_404(self, api_client, mock_service):
        """重连不存在的 server 返回 404。"""
        mock_service.reconnect_server.side_effect = LookupError("不存在")

        resp = api_client.post("/api/mcp-servers/mcs_missing/reconnect")

        assert resp.status_code == 404


class TestDeleteMcpServer:
    """DELETE /api/mcp-servers/{id}: 删除 server。"""

    def test_delete_server_success_204(self, api_client, mock_service):
        """删除成功返回 204。"""
        mock_service.delete_server.return_value = True

        resp = api_client.delete("/api/mcp-servers/mcs_test")

        assert resp.status_code == 204
        mock_service.delete_server.assert_called_once_with("mcs_test")

    def test_delete_server_not_found_404(self, api_client, mock_service):
        """删除不存在的 server 返回 404。"""
        mock_service.delete_server.return_value = False

        resp = api_client.delete("/api/mcp-servers/mcs_missing")

        assert resp.status_code == 404


class TestAutoRestartOnConfigChange:
    """配置变更自动重启。"""

    def test_update_triggers_auto_restart_if_running(self, api_client, mock_service):
        """运行中 server 配置变更触发重连。"""
        mock_service.update_server.return_value = _make_detail(status="running")

        resp = api_client.patch(
            "/api/mcp-servers/mcs_test",
            json={"args": ["--verbose"]},
        )

        assert resp.status_code == 200
        # update_server 内部检查 is_running 并 auto-restart
        mock_service.update_server.assert_called_once()


class TestSecretAutoDetection:
    """secret 自动检测。"""

    def test_create_server_passes_env_to_service(self, api_client, mock_service):
        """创建时 env 字段传递到 service 层（secret 自动检测在 service 内完成）。"""
        mock_service.add_server.return_value = _make_detail(name="secret-srv")

        resp = api_client.post(
            "/api/mcp-servers",
            json={
                "name": "secret-srv",
                "transport": "stdio",
                "command": "npx",
                "env": {"GITHUB_TOKEN": "ghp_abc", "PATH": "/usr/bin"},
            },
        )

        assert resp.status_code == 201
        # 验证 env 被传递到 add_server
        call_kwargs = mock_service.add_server.call_args[1]
        assert call_kwargs["env"]["GITHUB_TOKEN"] == "ghp_abc"

    def test_create_server_with_secret_env_keys(self, api_client, mock_service):
        """创建时 secretEnvKeys 传递到 service 层。"""
        mock_service.add_server.return_value = _make_detail(name="secret-srv2")

        resp = api_client.post(
            "/api/mcp-servers",
            json={
                "name": "secret-srv2",
                "transport": "stdio",
                "command": "npx",
                "env": {"GITHUB_TOKEN": "ghp_abc"},
                "secretEnvKeys": ["GITHUB_TOKEN"],
            },
        )

        assert resp.status_code == 201
        call_kwargs = mock_service.add_server.call_args[1]
        assert "GITHUB_TOKEN" in call_kwargs["secret_env_keys"]
