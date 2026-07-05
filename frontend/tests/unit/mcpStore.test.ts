import { afterEach, describe, expect, test, vi } from "vitest";

import { useMcpStore } from "../../src/state/mcpStore";
import type { McpServerResponse, McpServerParsedPreview, McpServerTestConnectionResponse } from "../../src/api/mcpServers";
import type { UiEvent } from "../../src/api/client";

// ── Mock API module ──────────────────────────────────────────────────
vi.mock("../../src/api/mcpServers", () => ({
  listMcpServers: vi.fn(),
  createMcpServer: vi.fn(),
  importMcpServerJson: vi.fn(),
  testMcpServerConnection: vi.fn(),
  updateMcpServer: vi.fn(),
  enableMcpServer: vi.fn(),
  disableMcpServer: vi.fn(),
  reconnectMcpServer: vi.fn(),
  deleteMcpServer: vi.fn(),
}));

import {
  listMcpServers,
  createMcpServer,
  importMcpServerJson,
  testMcpServerConnection,
  updateMcpServer,
  enableMcpServer,
  disableMcpServer,
  reconnectMcpServer,
  deleteMcpServer,
} from "../../src/api/mcpServers";

const mocked = {
  listMcpServers: vi.mocked(listMcpServers),
  createMcpServer: vi.mocked(createMcpServer),
  importMcpServerJson: vi.mocked(importMcpServerJson),
  testMcpServerConnection: vi.mocked(testMcpServerConnection),
  updateMcpServer: vi.mocked(updateMcpServer),
  enableMcpServer: vi.mocked(enableMcpServer),
  disableMcpServer: vi.mocked(disableMcpServer),
  reconnectMcpServer: vi.mocked(reconnectMcpServer),
  deleteMcpServer: vi.mocked(deleteMcpServer),
};

// ── Fixtures ─────────────────────────────────────────────────────────

function makeServer(overrides: Partial<McpServerResponse> = {}): McpServerResponse {
  return {
    serverId: "srv_1",
    name: "Test Server",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-test"],
    url: null,
    envKeys: [],
    envMissingKeys: [],
    envPresence: {},
    headerKeys: [],
    headerMissingKeys: [],
    headerPresence: {},
    enabled: true,
    status: "running",
    toolCount: 5,
    presetSlug: null,
    lastError: null,
    suggestion: null,
    circuitBreakerOpen: false,
    createdAt: "2026-07-01T00:00:00Z",
    updatedAt: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

const SERVER_1 = makeServer({ serverId: "srv_1", name: "Server 1" });
const SERVER_2 = makeServer({ serverId: "srv_2", name: "Server 2" });

const PREVIEW_1: McpServerParsedPreview = {
  name: "Imported Server",
  transport: "stdio",
  command: "npx",
  args: ["-y", "some-mcp-server"],
  url: null,
  headers: null,
  env: { API_KEY: "sk_123" },
  detectedSecretKeys: ["API_KEY"],
  placeholderKeys: [],
};

// ── Helpers ──────────────────────────────────────────────────────────

function resetStore(): void {
  useMcpStore.setState({
    hydrated: false,
    servers: [],
    loading: false,
    lastError: null,
    importPreview: null,
    testingServerId: null,
    testResult: null,
  });
}

// ── Tests ────────────────────────────────────────────────────────────

describe("mcpStore", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    resetStore();
  });

  // ── load (fetchServers) ──────────────────────────────────────────

  describe("load", () => {
    test("loads servers and marks hydrated", async () => {
      mocked.listMcpServers.mockResolvedValueOnce([SERVER_1, SERVER_2]);

      await useMcpStore.getState().load();

      const state = useMcpStore.getState();
      expect(state.servers).toHaveLength(2);
      expect(state.servers[0].serverId).toBe("srv_1");
      expect(state.servers[1].serverId).toBe("srv_2");
      expect(state.hydrated).toBe(true);
      expect(state.loading).toBe(false);
      expect(state.lastError).toBeNull();
    });

    test("handles empty server list", async () => {
      mocked.listMcpServers.mockResolvedValueOnce([]);

      await useMcpStore.getState().load();

      const state = useMcpStore.getState();
      expect(state.servers).toHaveLength(0);
      expect(state.hydrated).toBe(true);
      expect(state.loading).toBe(false);
    });

    test("sets error when load fails", async () => {
      mocked.listMcpServers.mockRejectedValueOnce(new Error("Network error"));

      await useMcpStore.getState().load();

      const state = useMcpStore.getState();
      expect(state.lastError).toBe("Network error");
      expect(state.loading).toBe(false);
      expect(state.hydrated).toBe(false);
    });

    test("sets fallback error message for non-Error throws", async () => {
      mocked.listMcpServers.mockRejectedValueOnce("string error");

      await useMcpStore.getState().load();

      const state = useMcpStore.getState();
      expect(state.lastError).toBe("无法加载 MCP 服务器列表。");
    });

    test("clears lastError at start of load", async () => {
      useMcpStore.setState({ lastError: "previous error" });
      mocked.listMcpServers.mockResolvedValueOnce([SERVER_1]);

      await useMcpStore.getState().load();

      expect(useMcpStore.getState().lastError).toBeNull();
    });

    test("sets loading true during fetch and false after", async () => {
      let resolveList!: (value: McpServerResponse[]) => void;
      mocked.listMcpServers.mockImplementationOnce(
        () => new Promise((resolve) => { resolveList = resolve; }),
      );

      const loadPromise = useMcpStore.getState().load();
      expect(useMcpStore.getState().loading).toBe(true);

      resolveList([SERVER_1]);
      await loadPromise;

      expect(useMcpStore.getState().loading).toBe(false);
    });
  });

  // ── addServer ────────────────────────────────────────────────────

  describe("addServer", () => {
    test("creates server then reloads list", async () => {
      mocked.createMcpServer.mockResolvedValueOnce(makeServer({ serverId: "srv_new" }));
      mocked.listMcpServers.mockResolvedValueOnce([SERVER_1, SERVER_2, makeServer({ serverId: "srv_new" })]);

      await useMcpStore.getState().addServer({
        name: "New Server",
        transport: "stdio",
        command: "npx",
      });

      expect(mocked.createMcpServer).toHaveBeenCalledWith({
        name: "New Server",
        transport: "stdio",
        command: "npx",
      });
      expect(mocked.listMcpServers).toHaveBeenCalled();
      expect(useMcpStore.getState().servers).toHaveLength(3);
    });

    test("sets error when create fails", async () => {
      mocked.createMcpServer.mockRejectedValueOnce(new Error("Create failed"));

      await useMcpStore.getState().addServer({ name: "Bad Server" });

      expect(useMcpStore.getState().lastError).toBe("Create failed");
      expect(useMcpStore.getState().loading).toBe(false);
    });

    test("sets fallback error message for non-Error create failure", async () => {
      mocked.createMcpServer.mockRejectedValueOnce(undefined);

      await useMcpStore.getState().addServer({ name: "Bad Server" });

      expect(useMcpStore.getState().lastError).toBe("无法添加 MCP 服务器。");
    });
  });

  // ── importJson ───────────────────────────────────────────────────

  describe("importJson", () => {
    test("parses JSON and sets importPreview", async () => {
      mocked.importMcpServerJson.mockResolvedValueOnce({
        servers: [PREVIEW_1],
      });

      await useMcpStore.getState().importJson('{"mcpServers":{"test":{}}}');

      expect(mocked.importMcpServerJson).toHaveBeenCalledWith({
        jsonText: '{"mcpServers":{"test":{}}}',
      });
      const state = useMcpStore.getState();
      expect(state.importPreview).toHaveLength(1);
      expect(state.importPreview![0].name).toBe("Imported Server");
      expect(state.loading).toBe(false);
    });

    test("sets error when import fails", async () => {
      mocked.importMcpServerJson.mockRejectedValueOnce(new Error("Invalid JSON"));

      await useMcpStore.getState().importJson("not-json");

      expect(useMcpStore.getState().lastError).toBe("Invalid JSON");
      expect(useMcpStore.getState().importPreview).toBeNull();
    });

    test("sets fallback error message for non-Error import failure", async () => {
      mocked.importMcpServerJson.mockRejectedValueOnce(42);

      await useMcpStore.getState().importJson("bad");

      expect(useMcpStore.getState().lastError).toBe("无法解析 JSON 配置。");
    });

    test("clearImportPreview resets importPreview to null", async () => {
      mocked.importMcpServerJson.mockResolvedValueOnce({
        servers: [PREVIEW_1],
      });
      await useMcpStore.getState().importJson("{}");
      expect(useMcpStore.getState().importPreview).not.toBeNull();

      useMcpStore.getState().clearImportPreview();

      expect(useMcpStore.getState().importPreview).toBeNull();
    });
  });

  // ── testConnection ───────────────────────────────────────────────

  describe("testConnection", () => {
    test("sets testResult on success", async () => {
      mocked.testMcpServerConnection.mockResolvedValueOnce({
        success: true,
        toolCount: 3,
        tools: [],
        error: null,
      });

      await useMcpStore.getState().testConnection("srv_1");

      const state = useMcpStore.getState();
      expect(state.testResult).toEqual({
        success: true,
        toolCount: 3,
        error: null,
      });
      expect(state.testingServerId).toBeNull();
    });

    test("sets testResult with error from response", async () => {
      mocked.testMcpServerConnection.mockResolvedValueOnce({
        success: false,
        toolCount: 0,
        tools: [],
        error: "Connection refused",
      });

      await useMcpStore.getState().testConnection("srv_1");

      const state = useMcpStore.getState();
      expect(state.testResult).toEqual({
        success: false,
        toolCount: 0,
        error: "Connection refused",
      });
    });

    test("sets failed testResult on API throw", async () => {
      mocked.testMcpServerConnection.mockRejectedValueOnce(new Error("Timeout"));

      await useMcpStore.getState().testConnection("srv_1");

      const state = useMcpStore.getState();
      expect(state.testResult).toEqual({
        success: false,
        toolCount: 0,
        error: "Timeout",
      });
      expect(state.testingServerId).toBeNull();
    });

    test("sets fallback error in testResult for non-Error throws", async () => {
      mocked.testMcpServerConnection.mockRejectedValueOnce("unknown");

      await useMcpStore.getState().testConnection("srv_1");

      const state = useMcpStore.getState();
      expect(state.testResult).toEqual({
        success: false,
        toolCount: 0,
        error: "连接测试失败。",
      });
    });

    test("sets testingServerId during test and clears after", async () => {
      let resolveTest!: (value: McpServerTestConnectionResponse) => void;
      mocked.testMcpServerConnection.mockImplementationOnce(
        () => new Promise<McpServerTestConnectionResponse>((resolve) => { resolveTest = resolve; }),
      );

      const testPromise = useMcpStore.getState().testConnection("srv_1");
      expect(useMcpStore.getState().testingServerId).toBe("srv_1");
      expect(useMcpStore.getState().testResult).toBeNull();

      resolveTest({
        success: true,
        toolCount: 1,
        tools: [],
        error: null,
      });
      await testPromise;

      expect(useMcpStore.getState().testingServerId).toBeNull();
    });

    test("clearTestResult resets testResult to null", async () => {
      mocked.testMcpServerConnection.mockResolvedValueOnce({
        success: true,
        toolCount: 1,
        tools: [],
        error: null,
      });
      await useMcpStore.getState().testConnection("srv_1");
      expect(useMcpStore.getState().testResult).not.toBeNull();

      useMcpStore.getState().clearTestResult();

      expect(useMcpStore.getState().testResult).toBeNull();
    });
  });

  // ── updateServer ─────────────────────────────────────────────────

  describe("updateServer", () => {
    test("replaces server in list with updated response", async () => {
      useMcpStore.setState({ servers: [SERVER_1, SERVER_2] });
      const updated = makeServer({ serverId: "srv_1", name: "Updated Name" });
      mocked.updateMcpServer.mockResolvedValueOnce(updated);

      await useMcpStore.getState().updateServer("srv_1", { name: "Updated Name" });

      expect(mocked.updateMcpServer).toHaveBeenCalledWith("srv_1", { name: "Updated Name" });
      const state = useMcpStore.getState();
      expect(state.servers).toHaveLength(2);
      expect(state.servers.find((s) => s.serverId === "srv_1")?.name).toBe("Updated Name");
      expect(state.loading).toBe(false);
    });

    test("sets error when update fails", async () => {
      useMcpStore.setState({ servers: [SERVER_1] });
      mocked.updateMcpServer.mockRejectedValueOnce(new Error("Update failed"));

      await useMcpStore.getState().updateServer("srv_1", { name: "X" });

      expect(useMcpStore.getState().lastError).toBe("Update failed");
      // Server list unchanged
      expect(useMcpStore.getState().servers[0].name).toBe("Server 1");
    });

    test("sets fallback error message for non-Error update failure", async () => {
      useMcpStore.setState({ servers: [SERVER_1] });
      mocked.updateMcpServer.mockRejectedValueOnce(null);

      await useMcpStore.getState().updateServer("srv_1", {});

      expect(useMcpStore.getState().lastError).toBe("无法更新 MCP 服务器。");
    });
  });

  // ── enableServer ─────────────────────────────────────────────────

  describe("enableServer", () => {
    test("replaces server with enabled response", async () => {
      useMcpStore.setState({
        servers: [makeServer({ serverId: "srv_1", enabled: false, status: "stopped" })],
      });
      const enabled = makeServer({ serverId: "srv_1", enabled: true, status: "running" });
      mocked.enableMcpServer.mockResolvedValueOnce(enabled);

      await useMcpStore.getState().enableServer("srv_1");

      expect(mocked.enableMcpServer).toHaveBeenCalledWith("srv_1");
      const state = useMcpStore.getState();
      expect(state.servers[0].enabled).toBe(true);
      expect(state.servers[0].status).toBe("running");
    });

    test("sets error when enable fails", async () => {
      useMcpStore.setState({ servers: [SERVER_1] });
      mocked.enableMcpServer.mockRejectedValueOnce(new Error("Enable failed"));

      await useMcpStore.getState().enableServer("srv_1");

      expect(useMcpStore.getState().lastError).toBe("Enable failed");
      expect(useMcpStore.getState().servers[0].enabled).toBe(true);
    });

    test("sets fallback error for non-Error enable failure", async () => {
      useMcpStore.setState({ servers: [SERVER_1] });
      mocked.enableMcpServer.mockRejectedValueOnce({});

      await useMcpStore.getState().enableServer("srv_1");

      expect(useMcpStore.getState().lastError).toBe("无法启用 MCP 服务器。");
    });
  });

  // ── disableServer ────────────────────────────────────────────────

  describe("disableServer", () => {
    test("replaces server with disabled response", async () => {
      useMcpStore.setState({
        servers: [makeServer({ serverId: "srv_1", enabled: true, status: "running" })],
      });
      const disabled = makeServer({ serverId: "srv_1", enabled: false, status: "stopped" });
      mocked.disableMcpServer.mockResolvedValueOnce(disabled);

      await useMcpStore.getState().disableServer("srv_1");

      expect(mocked.disableMcpServer).toHaveBeenCalledWith("srv_1");
      const state = useMcpStore.getState();
      expect(state.servers[0].enabled).toBe(false);
      expect(state.servers[0].status).toBe("stopped");
    });

    test("sets error when disable fails", async () => {
      useMcpStore.setState({ servers: [SERVER_1] });
      mocked.disableMcpServer.mockRejectedValueOnce(new Error("Disable failed"));

      await useMcpStore.getState().disableServer("srv_1");

      expect(useMcpStore.getState().lastError).toBe("Disable failed");
    });

    test("sets fallback error for non-Error disable failure", async () => {
      useMcpStore.setState({ servers: [SERVER_1] });
      mocked.disableMcpServer.mockRejectedValueOnce(false);

      await useMcpStore.getState().disableServer("srv_1");

      expect(useMcpStore.getState().lastError).toBe("无法禁用 MCP 服务器。");
    });
  });

  // ── reconnectServer ──────────────────────────────────────────────

  describe("reconnectServer", () => {
    test("replaces server with reconnected response", async () => {
      useMcpStore.setState({
        servers: [makeServer({ serverId: "srv_1", status: "disconnected" })],
      });
      const reconnected = makeServer({ serverId: "srv_1", status: "running", toolCount: 7 });
      mocked.reconnectMcpServer.mockResolvedValueOnce(reconnected);

      await useMcpStore.getState().reconnectServer("srv_1");

      expect(mocked.reconnectMcpServer).toHaveBeenCalledWith("srv_1");
      const state = useMcpStore.getState();
      expect(state.servers[0].status).toBe("running");
      expect(state.servers[0].toolCount).toBe(7);
    });

    test("sets error when reconnect fails", async () => {
      useMcpStore.setState({ servers: [SERVER_1] });
      mocked.reconnectMcpServer.mockRejectedValueOnce(new Error("Reconnect failed"));

      await useMcpStore.getState().reconnectServer("srv_1");

      expect(useMcpStore.getState().lastError).toBe("Reconnect failed");
    });

    test("sets fallback error for non-Error reconnect failure", async () => {
      useMcpStore.setState({ servers: [SERVER_1] });
      mocked.reconnectMcpServer.mockRejectedValueOnce(undefined);

      await useMcpStore.getState().reconnectServer("srv_1");

      expect(useMcpStore.getState().lastError).toBe("无法重连 MCP 服务器。");
    });
  });

  // ── deleteServer ─────────────────────────────────────────────────

  describe("deleteServer", () => {
    test("optimistically removes server", async () => {
      useMcpStore.setState({ servers: [SERVER_1, SERVER_2] });
      let resolveDelete!: (value: void) => void;
      mocked.deleteMcpServer.mockImplementationOnce(
        () => new Promise((resolve) => { resolveDelete = resolve; }),
      );

      const deletePromise = useMcpStore.getState().deleteServer("srv_1");

      // Server removed immediately (optimistic)
      expect(useMcpStore.getState().servers).toHaveLength(1);
      expect(useMcpStore.getState().servers[0].serverId).toBe("srv_2");

      resolveDelete();
      await deletePromise;

      // Still removed after API confirms
      expect(useMcpStore.getState().servers).toHaveLength(1);
      expect(useMcpStore.getState().lastError).toBeNull();
    });

    test("rolls back server on delete failure", async () => {
      useMcpStore.setState({ servers: [SERVER_1, SERVER_2] });
      mocked.deleteMcpServer.mockRejectedValueOnce(new Error("Delete forbidden"));

      await useMcpStore.getState().deleteServer("srv_1");

      const state = useMcpStore.getState();
      expect(state.servers).toHaveLength(2);
      expect(state.lastError).toBe("Delete forbidden");
    });

    test("sets fallback error on non-Error delete failure", async () => {
      useMcpStore.setState({ servers: [SERVER_1] });
      mocked.deleteMcpServer.mockRejectedValueOnce("str");

      await useMcpStore.getState().deleteServer("srv_1");

      expect(useMcpStore.getState().servers).toHaveLength(1);
      expect(useMcpStore.getState().lastError).toBe("无法删除 MCP 服务器。");
    });

    test("clears lastError at start of delete", async () => {
      useMcpStore.setState({ servers: [SERVER_1], lastError: "old error" });
      mocked.deleteMcpServer.mockResolvedValueOnce(undefined);

      await useMcpStore.getState().deleteServer("srv_1");

      expect(useMcpStore.getState().lastError).toBeNull();
    });
  });

  // ── setError ─────────────────────────────────────────────────────

  describe("setError", () => {
    test("sets lastError to provided message", () => {
      useMcpStore.getState().setError("Custom error");
      expect(useMcpStore.getState().lastError).toBe("Custom error");
    });

    test("clears lastError when null is passed", () => {
      useMcpStore.getState().setError("Some error");
      useMcpStore.getState().setError(null);
      expect(useMcpStore.getState().lastError).toBeNull();
    });
  });

  // ── state transitions ────────────────────────────────────────────

  describe("state transitions", () => {
    test("hydrated transitions from false to true on successful load", async () => {
      expect(useMcpStore.getState().hydrated).toBe(false);

      mocked.listMcpServers.mockResolvedValueOnce([]);
      await useMcpStore.getState().load();

      expect(useMcpStore.getState().hydrated).toBe(true);
    });

    test("hydrated stays false on failed load", async () => {
      mocked.listMcpServers.mockRejectedValueOnce(new Error("fail"));
      await useMcpStore.getState().load();

      expect(useMcpStore.getState().hydrated).toBe(false);
    });

    test("loading transitions true during operation and false after", async () => {
      let resolve!: (value: McpServerResponse[]) => void;
      mocked.listMcpServers.mockImplementationOnce(
        () => new Promise((resolve_) => { resolve = resolve_; }),
      );

      const loadPromise = useMcpStore.getState().load();
      expect(useMcpStore.getState().loading).toBe(true);

      resolve([]);
      await loadPromise;

      expect(useMcpStore.getState().loading).toBe(false);
    });

    test("lastError is null in initial state", () => {
      expect(useMcpStore.getState().lastError).toBeNull();
    });

    test("lastError is preserved across concurrent operations", async () => {
      // Set an error from one operation
      mocked.enableMcpServer.mockRejectedValueOnce(new Error("enable err"));
      await useMcpStore.getState().enableServer("srv_1");

      expect(useMcpStore.getState().lastError).toBe("enable err");

      // A successful operation clears lastError at start
      mocked.disableMcpServer.mockResolvedValueOnce(
        makeServer({ serverId: "srv_1", enabled: false }),
      );
      await useMcpStore.getState().disableServer("srv_1");

      expect(useMcpStore.getState().lastError).toBeNull();
    });
  });

  // ── tools.changed event refresh ──────────────────────────────────

  describe("applyEvent", () => {
    test("tools.changed triggers debounced load after 300ms", async () => {
      vi.useFakeTimers();
      mocked.listMcpServers.mockResolvedValueOnce([SERVER_1]);

      useMcpStore.getState().applyEvent({ type: "tools.changed" } as UiEvent);

      // load 还没调用（防抖中）
      expect(mocked.listMcpServers).not.toHaveBeenCalled();

      // 推进 300ms
      vi.advanceTimersByTime(300);
      await vi.runAllTimersAsync();

      expect(mocked.listMcpServers).toHaveBeenCalledTimes(1);
      expect(useMcpStore.getState().hydrated).toBe(true);

      vi.useRealTimers();
    });

    test("rapid tools.changed events coalesce into single load", async () => {
      vi.useFakeTimers();
      mocked.listMcpServers.mockResolvedValue([SERVER_1, SERVER_2]);

      // 快速连续发 3 个事件
      useMcpStore.getState().applyEvent({ type: "tools.changed" } as UiEvent);
      vi.advanceTimersByTime(100);
      useMcpStore.getState().applyEvent({ type: "tools.changed" } as UiEvent);
      vi.advanceTimersByTime(100);
      useMcpStore.getState().applyEvent({ type: "tools.changed" } as UiEvent);

      // 还在防抖窗口内，load 未调用
      expect(mocked.listMcpServers).not.toHaveBeenCalled();

      // 推进到防抖结束
      vi.advanceTimersByTime(300);
      await vi.runAllTimersAsync();

      // 只触发一次 load
      expect(mocked.listMcpServers).toHaveBeenCalledTimes(1);

      vi.useRealTimers();
    });

    test("non-tools.changed events are ignored", () => {
      vi.useFakeTimers();

      useMcpStore.getState().applyEvent({ type: "backend.resync_required" } as UiEvent);
      vi.advanceTimersByTime(500);

      expect(mocked.listMcpServers).not.toHaveBeenCalled();

      vi.useRealTimers();
    });
  });
});
