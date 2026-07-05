import { create } from "zustand";

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
} from "../api/mcpServers";
import type {
  McpServerResponse,
  McpServerCreateRequest,
  McpServerUpdateRequest,
  McpServerParsedPreview,
} from "../api/mcpServers";
import { toErrorMessage } from "./helpers";
import type { UiEvent } from "../api/client";

export type McpTestResult = {
  success: boolean;
  toolCount: number;
  error: string | null;
};

export type McpStoreState = {
  hydrated: boolean;
  servers: McpServerResponse[];
  loading: boolean;
  lastError: string | null;
  importPreview: McpServerParsedPreview[] | null;
  testingServerId: string | null;
  testResult: McpTestResult | null;
  /** 防抖定时器 ID，合并快速连续的 tools.changed 事件 */
  _reloadTimer: number | null;

  load: () => Promise<void>;
  addServer: (input: McpServerCreateRequest) => Promise<void>;
  importJson: (jsonText: string) => Promise<void>;
  clearImportPreview: () => void;
  testConnection: (serverId: string) => Promise<void>;
  clearTestResult: () => void;
  updateServer: (serverId: string, input: McpServerUpdateRequest) => Promise<void>;
  enableServer: (serverId: string) => Promise<void>;
  disableServer: (serverId: string) => Promise<void>;
  reconnectServer: (serverId: string) => Promise<void>;
  deleteServer: (serverId: string) => Promise<void>;
  setError: (message: string | null) => void;
  applyEvent: (event: UiEvent) => void;
};

function replaceServer(
  servers: McpServerResponse[],
  next: McpServerResponse,
): McpServerResponse[] {
  return servers.map((s) => (s.serverId === next.serverId ? next : s));
}

export const useMcpStore = create<McpStoreState>((set, get) => ({
  hydrated: false,
  servers: [],
  loading: false,
  lastError: null,
  importPreview: null,
  testingServerId: null,
  testResult: null,
  _reloadTimer: null,

  setError: (message) => set({ lastError: message }),

  load: async () => {
    set({ loading: true, lastError: null });
    try {
      const response = await listMcpServers();
      set({ hydrated: true, servers: response });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载 MCP 服务器列表。") });
    } finally {
      set({ loading: false });
    }
  },

  addServer: async (input) => {
    set({ loading: true, lastError: null });
    try {
      await createMcpServer(input);
      await get().load();
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法添加 MCP 服务器。") });
    } finally {
      set({ loading: false });
    }
  },

  importJson: async (jsonText) => {
    set({ loading: true, lastError: null });
    try {
      const response = await importMcpServerJson({ jsonText });
      set({ importPreview: response.servers });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法解析 JSON 配置。") });
    } finally {
      set({ loading: false });
    }
  },

  clearImportPreview: () => set({ importPreview: null }),

  testConnection: async (serverId) => {
    set({ testingServerId: serverId, testResult: null, lastError: null });
    try {
      const result = await testMcpServerConnection(serverId);
      set({
        testResult: {
          success: result.success,
          toolCount: result.toolCount,
          error: result.error ?? null,
        },
      });
    } catch (error) {
      set({
        testResult: {
          success: false,
          toolCount: 0,
          error: toErrorMessage(error, "连接测试失败。"),
        },
      });
    } finally {
      set({ testingServerId: null });
    }
  },

  clearTestResult: () => set({ testResult: null }),

  updateServer: async (serverId, input) => {
    set({ loading: true, lastError: null });
    try {
      const updated = await updateMcpServer(serverId, input);
      set({ servers: replaceServer(get().servers, updated) });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法更新 MCP 服务器。") });
    } finally {
      set({ loading: false });
    }
  },

  enableServer: async (serverId) => {
    set({ loading: true, lastError: null });
    try {
      const updated = await enableMcpServer(serverId);
      set({ servers: replaceServer(get().servers, updated) });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法启用 MCP 服务器。") });
    } finally {
      set({ loading: false });
    }
  },

  disableServer: async (serverId) => {
    set({ loading: true, lastError: null });
    try {
      const updated = await disableMcpServer(serverId);
      set({ servers: replaceServer(get().servers, updated) });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法禁用 MCP 服务器。") });
    } finally {
      set({ loading: false });
    }
  },

  reconnectServer: async (serverId) => {
    set({ loading: true, lastError: null });
    try {
      const updated = await reconnectMcpServer(serverId);
      set({ servers: replaceServer(get().servers, updated) });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法重连 MCP 服务器。") });
    } finally {
      set({ loading: false });
    }
  },

  deleteServer: async (serverId) => {
    set({ lastError: null });
    const previous = get().servers;
    // Optimistic removal
    set({ servers: previous.filter((s) => s.serverId !== serverId) });
    try {
      await deleteMcpServer(serverId);
    } catch (error) {
      // Rollback on failure
      set({
        servers: previous,
        lastError: toErrorMessage(error, "无法删除 MCP 服务器。"),
      });
    }
  },

  applyEvent: (event) => {
    if (event.type === "tools.changed") {
      // 防抖：300ms 内多个 tools.changed 合并为一次 reload
      const state = get();
      if (state._reloadTimer !== null) {
        clearTimeout(state._reloadTimer);
      }
      set({
        _reloadTimer: window.setTimeout(() => {
          set({ _reloadTimer: null });
          void get().load();
        }, 300),
      });
    }
  },
}));
