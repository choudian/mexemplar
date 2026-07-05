"""
McpSessionProtocol — 业务层 Session 抽象（N9）。

签名返回业务类型（McpToolInfo / McpCallResult），不泄漏 SDK 类型。
McpProcessManager 内部用 _SdkSessionAdapter 包装 SDK ClientSession 为此 Protocol。
"""

from typing import Protocol, runtime_checkable

from src.business.mcp.models import McpCallResult, McpToolInfo


@runtime_checkable
class McpSessionProtocol(Protocol):
    """业务层 Session 抽象（N9：签名返回业务类型，不泄漏 SDK 类型）。

    McpProcessManager._sessions: dict[str, McpSessionProtocol] 存此 Protocol 类型。
    测试可注入 FakeMcpSession（实现此 Protocol）直接塞 dict（RC4）。
    """

    async def initialize(self) -> None:
        """初始化 MCP session。内部吞掉 SDK InitializeResult。"""
        ...

    async def list_tools(self) -> list[McpToolInfo]:
        """列出 server 暴露的工具。SDK ListToolsResult → list[McpToolInfo]。"""
        ...

    async def call_tool(self, name: str, arguments: dict) -> McpCallResult:
        """调用工具。SDK CallToolResult → McpCallResult（N9）。"""
        ...

    async def send_ping(self) -> bool:
        """健康检查 ping。SDK EmptyResult → bool。"""
        ...
