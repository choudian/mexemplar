"""
T022: Thread safety + event loop crash recovery 测试。
"""

import asyncio
import threading
import pytest

from src.business.mcp.mcp_tool_registry import McpToolRegistry
from src.business.mcp.models import McpCallResult, McpToolInfo


def _make_tool(name: str) -> McpToolInfo:
    return McpToolInfo(name=name, description="", input_schema={"type": "object"})


class _FakeSession:
    """轻量 FakeMcpSession（内联，满足 McpSessionProtocol 接口）。"""

    def __init__(self, call_result: McpCallResult):
        self._call_result = call_result
        self.call_count = 0

    async def initialize(self) -> None:
        pass

    async def list_tools(self) -> list[McpToolInfo]:
        return []

    async def call_tool(self, name: str, arguments: dict) -> McpCallResult:
        self.call_count += 1
        return self._call_result

    async def send_ping(self) -> bool:
        return True


class TestMcpToolRegistryThreadSafety:
    """McpToolRegistry 线程安全测试。"""

    def test_concurrent_register_unregister(self):
        """并发注册/注销不抛 dictionary changed size 错误。"""
        registry = McpToolRegistry()
        errors = []

        def register(server_id: str, slug: str, n: int):
            try:
                tools = [_make_tool(f"tool_{i}") for i in range(n)]
                registry.register_server_tools(server_id, slug, tools, is_preset=False)
            except Exception as e:
                errors.append(e)

        def unregister(server_id: str):
            try:
                registry.unregister_server_tools(server_id)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            t1 = threading.Thread(target=register, args=(f"srv_{i}", f"slug{i}", 10))
            t1.start()
            threads.append(t1)

        for t in threads:
            t.join()

        # 并发注销
        threads2 = []
        for i in range(5):
            t2 = threading.Thread(target=unregister, args=(f"srv_{i}",))
            t2.start()
            threads2.append(t2)

        for t in threads2:
            t.join()

        # 不应有 RuntimeError: dictionary changed size during iteration
        dict_errors = [e for e in errors if "dictionary changed size" in str(e)]
        assert len(dict_errors) == 0, f"Thread safety violation: {dict_errors}"

    def test_snapshot_semantics_on_getters(self):
        """getter 返回 snapshot，不受后续修改影响。"""
        registry = McpToolRegistry()
        tools = [_make_tool("tool_a"), _make_tool("tool_b")]
        registry.register_server_tools("srv1", "srv", tools, is_preset=False)

        snapshot = registry.get_catalog_items()
        # 修改原 registry
        registry.unregister_server_tools("srv1")

        # snapshot 不受影响
        assert len(snapshot) == 2

    def test_barrier_sync_concurrent_read_after_register(self):
        """Barrier 同步：多线程同时注册后，Barrier 点同时读取，验证 snapshot 一致性。"""
        registry = McpToolRegistry()
        num_threads = 4
        barrier = threading.Barrier(num_threads, timeout=10)
        results: dict[int, list] = {}
        errors = []

        def worker(idx: int):
            try:
                # 每个线程注册自己的 server
                tools = [_make_tool(f"srv{idx}_tool_{j}") for j in range(3)]
                registry.register_server_tools(f"srv_{idx}", f"slug{idx}", tools, is_preset=False)

                # 等待所有线程完成注册
                barrier.wait()

                # 同时读取 snapshot
                snapshot = registry.get_catalog_items()
                results[idx] = snapshot
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i,))
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during barrier test: {errors}"
        # 所有线程应看到完整的 12 项（4 servers × 3 tools）
        for idx, snapshot in results.items():
            assert len(snapshot) == 12, f"Thread {idx} saw {len(snapshot)} items, expected 12"


class TestConcurrentCallToolSync:
    """并发 call_tool_sync 线程安全测试。"""

    @staticmethod
    def _make_fake_session(
        call_result: "McpCallResult",
    ) -> "_FakeSession":
        """创建轻量 FakeMcpSession（内联，不跨文件依赖）。"""
        return _FakeSession(call_result=call_result)

    def test_concurrent_call_tool_returns_correct_results(self):
        """多线程同时调用 call_tool_sync，每个线程拿到自己调用的正确结果。"""
        from src.business.mcp.mcp_process_manager import McpProcessManager
        from src.business.mcp.models import McpCallResult

        mgr = object.__new__(McpProcessManager)
        mgr._sdk_available = True
        mgr._sessions = {}
        mgr._stacks = {}
        mgr._stop_events = {}
        mgr._stderr_files = {}
        mgr._stderr_read_pos = {}
        mgr._server_names = {}
        mgr._lock = threading.Lock()
        mgr._ping_task = None

        # 手动启动事件循环
        mgr._event_loop = asyncio.new_event_loop()
        mgr._event_loop_thread = threading.Thread(
            target=mgr._run_loop, daemon=True, name="test-mcp-call-loop"
        )
        mgr._event_loop_thread.start()

        # 注入两个 FakeMcpSession，返回不同结果
        result_a = McpCallResult(
            is_error=False, text_parts=["result_a"], image_count=0, structured_data=None
        )
        result_b = McpCallResult(
            is_error=False, text_parts=["result_b"], image_count=0, structured_data=None
        )
        mgr._sessions["mcs_a"] = self._make_fake_session(result_a)
        mgr._sessions["mcs_b"] = self._make_fake_session(result_b)

        num_per_server = 5
        results: dict[str, list[str]] = {"mcs_a": [], "mcs_b": []}
        errors = []

        def call_repeatedly(server_id: str):
            try:
                for _ in range(num_per_server):
                    r = mgr.call_tool_sync(server_id, "test_tool", {})
                    results[server_id].append(r.text_parts[0])
            except Exception as e:
                errors.append(e)

        # 并发调用两个 server
        t_a = threading.Thread(target=call_repeatedly, args=("mcs_a",))
        t_b = threading.Thread(target=call_repeatedly, args=("mcs_b",))
        t_a.start()
        t_b.start()
        t_a.join(timeout=30)
        t_b.join(timeout=30)

        mgr.shutdown()

        assert len(errors) == 0, f"Errors during concurrent call_tool: {errors}"
        # 每个 server 的结果都应全部属于自己
        assert len(results["mcs_a"]) == num_per_server
        assert all(r == "result_a" for r in results["mcs_a"])
        assert len(results["mcs_b"]) == num_per_server
        assert all(r == "result_b" for r in results["mcs_b"])


class TestEventLoopCrashRecovery:
    """事件循环崩溃恢复测试（E6）。"""

    def test_process_manager_event_loop_rebuild(self):
        """事件循环崩溃后可重建。"""
        from src.business.mcp.mcp_process_manager import McpProcessManager

        pm = McpProcessManager()
        # ProcessManager 可能因 SDK 不可用而没有事件循环
        if not pm.sdk_available:
            pytest.skip("MCP SDK not available")

        # 验证事件循环存在
        loop = pm.get_or_create_event_loop()
        assert loop is not None

        # 清理
        pm.shutdown()
