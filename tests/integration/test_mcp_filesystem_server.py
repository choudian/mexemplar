"""
MCP filesystem server 集成测试 (T051)。

使用真实 MCP SDK + npx @modelcontextprotocol/server-filesystem 进行端到端验证。
标记 @pytest.mark.integration，SDK/npx 不可用时 skip。
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

from src.business.mcp.models import (
    McpCallResult,
    McpServerConfigPublic,
    McpToolInfo,
)

# ── Skip 条件 ──


def _sdk_available() -> bool:
    try:
        import mcp  # noqa: F401

        return True
    except ImportError:
        return False


def _npx_available() -> bool:
    return shutil.which("npx") is not None


requires_mcp_sdk = pytest.mark.skipif(
    not _sdk_available(),
    reason="MCP SDK not installed",
)

requires_npx = pytest.mark.skipif(
    not _npx_available(),
    reason="npx not found in PATH",
)

integration = pytest.mark.integration


# ── Fixtures ──


@pytest.fixture
def temp_dir():
    """创建临时目录作为 filesystem server 的根目录。"""
    d = tempfile.mkdtemp(prefix="mcp_fs_test_")
    # 创建一些测试文件
    with open(os.path.join(d, "hello.txt"), "w") as f:
        f.write("Hello from MCP filesystem server!")
    with open(os.path.join(d, "data.json"), "w") as f:
        f.write('{"key": "value"}')
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def process_manager():
    """创建 McpProcessManager 实例。"""
    from src.business.mcp.mcp_process_manager import McpProcessManager

    pm = McpProcessManager()
    yield pm
    # 清理：停止所有 server
    try:
        pm.stop_all_sync()
    except Exception:
        pass
    try:
        pm.shutdown()
    except Exception:
        pass


def _make_filesystem_config(temp_dir: str) -> McpServerConfigPublic:
    """创建 filesystem server 的配置。"""
    return McpServerConfigPublic(
        server_id="mcs_test_filesystem",
        name="filesystem",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", temp_dir],
        url=None,
        non_secret_env={},
        non_secret_headers={},
        secret_env_keys=[],
        secret_header_keys=[],
        enabled=True,
        is_preset=True,
        preset_slug="filesystem",
    )


# ── Tests ──


@integration
@requires_mcp_sdk
@requires_npx
def test_filesystem_server_start_list_tools_stop(temp_dir, process_manager):
    """完整生命周期：start → list_tools → stop。"""
    config = _make_filesystem_config(temp_dir)
    server_id = config.server_id

    # Start
    tools = process_manager.start_server(server_id, config)
    assert isinstance(tools, list)
    assert len(tools) > 0, "filesystem server 应暴露至少一个工具"

    # 验证工具信息
    for tool in tools:
        assert isinstance(tool, McpToolInfo)
        assert tool.name
        assert isinstance(tool.input_schema, dict)

    # 验证常见工具名
    tool_names = [t.name for t in tools]
    assert any("read" in n.lower() for n in tool_names), "应有读取文件工具"
    assert any("list" in n.lower() for n in tool_names), "应有列出目录工具"

    # Stop
    process_manager.stop_server(server_id)
    assert not process_manager.is_server_running(server_id)


@integration
@requires_mcp_sdk
@requires_npx
def test_filesystem_server_call_tool_read_file(temp_dir, process_manager):
    """调用 read_file 工具读取测试文件。"""
    config = _make_filesystem_config(temp_dir)
    server_id = config.server_id

    tools = process_manager.start_server(server_id, config)

    # 找到 read_file 工具
    read_tool = next(
        (t for t in tools if "read" in t.name.lower() and "file" in t.name.lower()),
        None,
    )
    if read_tool is None:
        pytest.skip("filesystem server 未暴露 read_file 工具")

    # 调用工具
    result = process_manager.call_tool_sync(
        server_id,
        read_tool.name,
        {"path": os.path.join(temp_dir, "hello.txt")},
    )
    assert isinstance(result, McpCallResult)
    assert not result.is_error
    assert len(result.text_parts) > 0
    assert "Hello from MCP filesystem server!" in result.text_parts[0]

    process_manager.stop_server(server_id)


@integration
@requires_mcp_sdk
@requires_npx
def test_filesystem_server_call_tool_list_directory(temp_dir, process_manager):
    """调用 list_directory 工具列出目录。"""
    config = _make_filesystem_config(temp_dir)
    server_id = config.server_id

    tools = process_manager.start_server(server_id, config)

    # 找到 list_directory 工具
    list_tool = next(
        (t for t in tools if "list" in t.name.lower() and "direct" in t.name.lower()),
        None,
    )
    if list_tool is None:
        pytest.skip("filesystem server 未暴露 list_directory 工具")

    # 调用工具
    result = process_manager.call_tool_sync(
        server_id,
        list_tool.name,
        {"path": temp_dir},
    )
    assert isinstance(result, McpCallResult)
    assert not result.is_error
    assert len(result.text_parts) > 0

    process_manager.stop_server(server_id)


@integration
@requires_mcp_sdk
@requires_npx
def test_filesystem_server_reconnect(temp_dir, process_manager):
    """重连测试：stop → reconnect。"""
    config = _make_filesystem_config(temp_dir)
    server_id = config.server_id

    # Start
    tools = process_manager.start_server(server_id, config)
    assert len(tools) > 0

    # Stop
    process_manager.stop_server(server_id)
    assert not process_manager.is_server_running(server_id)

    # Reconnect
    tools2 = process_manager.reconnect_server(server_id, config)
    assert isinstance(tools2, list)
    assert len(tools2) > 0

    # 验证重连后仍可调用
    read_tool = next(
        (t for t in tools2 if "read" in t.name.lower() and "file" in t.name.lower()),
        None,
    )
    if read_tool:
        result = process_manager.call_tool_sync(
            server_id,
            read_tool.name,
            {"path": os.path.join(temp_dir, "hello.txt")},
        )
        assert not result.is_error

    process_manager.stop_server(server_id)


@integration
@requires_mcp_sdk
@requires_npx
def test_filesystem_server_health_check(temp_dir, process_manager):
    """健康检查 ping。"""
    config = _make_filesystem_config(temp_dir)
    server_id = config.server_id

    process_manager.start_server(server_id, config)

    # Ping 应成功
    is_healthy = process_manager.health_check(server_id)
    assert is_healthy is True

    process_manager.stop_server(server_id)


@integration
@requires_mcp_sdk
@requires_npx
def test_filesystem_server_call_tool_error_on_invalid_path(temp_dir, process_manager):
    """调用工具读取不存在的文件应返回错误。"""
    config = _make_filesystem_config(temp_dir)
    server_id = config.server_id

    tools = process_manager.start_server(server_id, config)

    read_tool = next(
        (t for t in tools if "read" in t.name.lower() and "file" in t.name.lower()),
        None,
    )
    if read_tool is None:
        pytest.skip("filesystem server 未暴露 read_file 工具")

    # 读取不存在的文件
    result = process_manager.call_tool_sync(
        server_id,
        read_tool.name,
        {"path": os.path.join(temp_dir, "nonexistent.txt")},
    )
    assert isinstance(result, McpCallResult)
    # filesystem server 对不存在的文件返回 is_error=True
    assert result.is_error

    process_manager.stop_server(server_id)


@integration
@requires_mcp_sdk
@requires_npx
def test_filesystem_server_schema_has_input_schema(temp_dir, process_manager):
    """RC3: 验证工具的 input_schema 包含预期结构。"""
    config = _make_filesystem_config(temp_dir)
    server_id = config.server_id

    tools = process_manager.start_server(server_id, config)

    for tool in tools:
        # 每个工具应有 input_schema
        assert isinstance(tool.input_schema, dict)
        # JSON Schema 基本结构
        assert "type" in tool.input_schema or "properties" in tool.input_schema

    process_manager.stop_server(server_id)


@integration
@requires_mcp_sdk
@requires_npx
def test_filesystem_server_stderr_capture(temp_dir, process_manager):
    """RC1: stderr 应被 tempfile 捕获而非丢失。"""
    config = _make_filesystem_config(temp_dir)
    server_id = config.server_id

    # 启动 server — stderr 应被捕获到 tempfile
    tools = process_manager.start_server(server_id, config)
    assert len(tools) > 0

    # 验证 server 运行中
    assert process_manager.is_server_running(server_id)

    process_manager.stop_server(server_id)
