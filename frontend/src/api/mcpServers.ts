import { requestJson } from "./client";

// ── Shared types ────────────────────────────────────────────────────

/** MCP server 连接状态，与后端 McpServerStatus 枚举同步。 */
export type McpServerStatus = "starting" | "running" | "disconnected" | "failed" | "stopped";

// ── Response types ──────────────────────────────────────────────────

export interface McpServerResponse {
  serverId: string;
  name: string;
  transport: string;
  command: string | null;
  args: string[] | null;
  url: string | null;
  envKeys: string[];
  envMissingKeys: string[];
  envPresence: Record<string, string>;
  headerKeys: string[];
  headerMissingKeys: string[];
  headerPresence: Record<string, string>;
  enabled: boolean;
  status: McpServerStatus | null;
  toolCount: number | null;
  presetSlug: string | null;
  lastError: string | null;
  suggestion: string | null;
  circuitBreakerOpen: boolean;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface McpServerTestConnectionResponse {
  success: boolean;
  toolCount: number;
  tools: Record<string, unknown>[];
  error: string | null;
}

export interface McpServerParsedPreview {
  name: string;
  transport: string;
  command: string | null;
  args: string[] | null;
  url: string | null;
  headers: Record<string, string> | null;
  env: Record<string, string> | null;
  detectedSecretKeys: string[];
  placeholderKeys: string[];
}

export interface McpServerJsonImportResponse {
  servers: McpServerParsedPreview[];
}

// ── Request types ───────────────────────────────────────────────────

export interface McpServerCreateRequest {
  name: string;
  transport?: string;
  command?: string | null;
  args?: string[] | null;
  url?: string | null;
  headers?: Record<string, string> | null;
  secretHeaderKeys?: string[] | null;
  env?: Record<string, string> | null;
  secretEnvKeys?: string[] | null;
  presetSlug?: string | null;
}

export interface McpServerUpdateRequest {
  name?: string | null;
  command?: string | null;
  args?: string[] | null;
  url?: string | null;
  headers?: Record<string, string> | null;
  secretHeaderKeys?: string[] | null;
  env?: Record<string, string> | null;
  secretEnvKeys?: string[] | null;
}

export interface McpServerJsonImportRequest {
  jsonText: string;
}

// ── API functions ───────────────────────────────────────────────────

export function listMcpServers(): Promise<McpServerResponse[]> {
  return requestJson<McpServerResponse[]>("/api/mcp-servers");
}

export function getMcpServer(serverId: string): Promise<McpServerResponse> {
  return requestJson<McpServerResponse>(
    `/api/mcp-servers/${encodeURIComponent(serverId)}`,
  );
}

export function createMcpServer(
  input: McpServerCreateRequest,
): Promise<McpServerResponse> {
  return requestJson<McpServerResponse>("/api/mcp-servers", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function importMcpServerJson(
  input: McpServerJsonImportRequest,
): Promise<McpServerJsonImportResponse> {
  return requestJson<McpServerJsonImportResponse>(
    "/api/mcp-servers/import-json",
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function testMcpServerConnection(
  serverId: string,
): Promise<McpServerTestConnectionResponse> {
  return requestJson<McpServerTestConnectionResponse>(
    `/api/mcp-servers/${encodeURIComponent(serverId)}/test-connection`,
    { method: "POST" },
  );
}

export function updateMcpServer(
  serverId: string,
  input: McpServerUpdateRequest,
): Promise<McpServerResponse> {
  return requestJson<McpServerResponse>(
    `/api/mcp-servers/${encodeURIComponent(serverId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
    },
  );
}

export function enableMcpServer(serverId: string): Promise<McpServerResponse> {
  return requestJson<McpServerResponse>(
    `/api/mcp-servers/${encodeURIComponent(serverId)}/enable`,
    { method: "POST" },
  );
}

export function disableMcpServer(serverId: string): Promise<McpServerResponse> {
  return requestJson<McpServerResponse>(
    `/api/mcp-servers/${encodeURIComponent(serverId)}/disable`,
    { method: "POST" },
  );
}

export function reconnectMcpServer(
  serverId: string,
): Promise<McpServerResponse> {
  return requestJson<McpServerResponse>(
    `/api/mcp-servers/${encodeURIComponent(serverId)}/reconnect`,
    { method: "POST" },
  );
}

export async function deleteMcpServer(serverId: string): Promise<void> {
  await requestJson<void>(
    `/api/mcp-servers/${encodeURIComponent(serverId)}`,
    { method: "DELETE" },
  );
}
