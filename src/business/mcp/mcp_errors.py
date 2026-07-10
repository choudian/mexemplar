"""
MCP 错误分类映射 — 将原始异常映射为用户友好的 suggestion（N14/RC3）。
"""


class McpServerDisconnectedError(Exception):
    """MCP server 连接已断开。"""

    def __init__(self, server_id: str):
        self.server_id = server_id
        super().__init__(f"MCP server {server_id} 连接已断开")


class McpToolTimeoutError(Exception):
    """MCP 工具调用超时。"""

    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        super().__init__(f"MCP tool '{tool_name}' 调用超时（30s）")


class McpToolSchemaValidationError(Exception):
    """MCP 工具输出 schema 校验失败（RC3/N10）。"""

    def __init__(self, tool_name: str, detail: str):
        self.tool_name = tool_name
        self.detail = detail
        super().__init__(f"MCP tool '{tool_name}' 输出格式异常: {detail}")


class McpCircuitBreakerOpenError(Exception):
    """MCP server 断路器已打开（E8：连续失败超阈值）。"""

    def __init__(self, server_id: str):
        self.server_id = server_id
        super().__init__(f"MCP server {server_id} 连续失败，断路器已打开")


# ─── 启动阶段错误映射 ───

_STARTUP_ERROR_PATTERNS: list[tuple[list[str], str]] = [
    (
        ["enoent", "filenotfounderror", "not found", "找不到"],
        "找不到命令，请确认已安装并添加到系统 PATH",
    ),
    (
        ["econnrefused", "connectionrefused", "connection refused", "连接被拒绝"],
        "无法连接到 MCP server，请检查网络或配置",
    ),
    (
        ["401", "unauthorized", "authentication", "认证失败", "token"],
        "API token 无效或已过期，请检查凭证设置",
    ),
    (
        ["etimedout", "timeouterror", "timeout", "timed out", "超时"],
        "连接超时，请检查网络或 server 是否可达",
    ),
    (
        ["modulenotfound", "importerror", "no module named"],
        "MCP server 运行时不可用，请确认依赖已安装",
    ),
]


def classify_startup_error(error: Exception) -> str:
    """将启动阶段异常分类为用户友好的 suggestion。

    返回用户可直接操作的修复建议（P11）。
    """
    msg = str(error).lower()
    for patterns, suggestion in _STARTUP_ERROR_PATTERNS:
        if any(p in msg for p in patterns):
            return suggestion
    return "MCP server 启动失败，请检查配置或查看日志"


# ─── 运行时错误映射 ───

_RUNTIME_SUGGESTIONS: dict[type, str] = {
    McpServerDisconnectedError: "server 连接已断开，去工具列表重连后重试",
    McpToolTimeoutError: "工具调用超时（30s），server 可能过载或不可达",
    McpToolSchemaValidationError: "工具执行成功但输出格式异常，可能是 server 版本不匹配",
    McpCircuitBreakerOpenError: "server 连续失败，请重连后重试",
}


def classify_runtime_error(error: Exception) -> str:
    """将运行时异常分类为用户友好的 suggestion。

    返回用户可直接操作的修复建议（N14）。
    """
    for error_type, suggestion in _RUNTIME_SUGGESTIONS.items():
        if isinstance(error, error_type):
            return suggestion
    return "MCP 工具调用失败，请检查 server 状态或重试"
