"""
T015: mcp_errors 单元测试 — startup/runtime error classification + suggestion mapping。
"""

from src.business.mcp.mcp_errors import (
    McpCircuitBreakerOpenError,
    McpServerDisconnectedError,
    McpToolSchemaValidationError,
    McpToolTimeoutError,
    classify_startup_error,
    classify_runtime_error,
)


class TestMcpErrors:
    """错误分类映射测试。"""

    # ─── 启动阶段 ───

    def test_classify_startup_enoent(self):
        """ENOENT / FileNotFoundError → PATH 建议。"""
        exc = FileNotFoundError("spawn ENOENT: npx not found")
        suggestion = classify_startup_error(exc)
        assert "PATH" in suggestion

    def test_classify_startup_connection_refused(self):
        """ConnectionRefused → 网络建议。"""
        exc = ConnectionRefusedError("Connection refused on port 8000")
        suggestion = classify_startup_error(exc)
        assert "网络" in suggestion or "连接" in suggestion

    def test_classify_startup_auth_error(self):
        """401 / authentication → token 建议。"""
        exc = RuntimeError("401 Unauthorized: invalid token")
        suggestion = classify_startup_error(exc)
        assert "token" in suggestion.lower() or "凭证" in suggestion

    def test_classify_startup_timeout(self):
        """Timeout → 超时建议。"""
        exc = TimeoutError("Connection timed out after 30s")
        suggestion = classify_startup_error(exc)
        assert "超时" in suggestion

    def test_classify_startup_module_not_found(self):
        """ModuleNotFoundError → 依赖建议。"""
        exc = ModuleNotFoundError("No module named 'mcp'")
        suggestion = classify_startup_error(exc)
        assert "依赖" in suggestion

    def test_classify_startup_unknown(self):
        """未知错误 → 通用建议。"""
        exc = RuntimeError("Some unknown error")
        suggestion = classify_startup_error(exc)
        assert "检查配置" in suggestion or "查看日志" in suggestion

    # ─── 运行时 ───

    def test_classify_runtime_disconnected(self):
        """McpServerDisconnectedError → 重连建议。"""
        exc = McpServerDisconnectedError("mcs_abc")
        suggestion = classify_runtime_error(exc)
        assert "重连" in suggestion or "断开" in suggestion

    def test_classify_runtime_timeout(self):
        """McpToolTimeoutError → 超时建议。"""
        exc = McpToolTimeoutError("list_prs")
        suggestion = classify_runtime_error(exc)
        assert "超时" in suggestion

    def test_classify_runtime_schema_validation(self):
        """McpToolSchemaValidationError → 格式建议。"""
        exc = McpToolSchemaValidationError("list_prs", "output schema mismatch")
        suggestion = classify_runtime_error(exc)
        assert "格式" in suggestion or "版本" in suggestion

    def test_classify_runtime_circuit_breaker(self):
        """McpCircuitBreakerOpenError → 重连建议。"""
        exc = McpCircuitBreakerOpenError("mcs_abc")
        suggestion = classify_runtime_error(exc)
        assert "重连" in suggestion

    def test_classify_runtime_unknown(self):
        """未知运行时错误 → 通用建议。"""
        exc = ValueError("Some runtime error")
        suggestion = classify_runtime_error(exc)
        assert "检查" in suggestion or "重试" in suggestion

    # ─── 错误类属性 ───

    def test_disconnected_error_attributes(self):
        """McpServerDisconnectedError 包含 server_id。"""
        exc = McpServerDisconnectedError("mcs_test123")
        assert exc.server_id == "mcs_test123"

    def test_timeout_error_attributes(self):
        """McpToolTimeoutError 包含 tool_name。"""
        exc = McpToolTimeoutError("list_prs")
        assert exc.tool_name == "list_prs"

    def test_schema_validation_error_attributes(self):
        """McpToolSchemaValidationError 包含 tool_name 和 detail。"""
        exc = McpToolSchemaValidationError("list_prs", "schema mismatch")
        assert exc.tool_name == "list_prs"
        assert exc.detail == "schema mismatch"

    def test_circuit_breaker_error_attributes(self):
        """McpCircuitBreakerOpenError 包含 server_id。"""
        exc = McpCircuitBreakerOpenError("mcs_test456")
        assert exc.server_id == "mcs_test456"
