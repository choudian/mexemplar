import { requestJson } from "./client";
import type { DesktopApiClient } from "./client";

export interface AssistantSession {
  sessionId: string;
  title: string;
  preview: string;
  status: string;
  createdAt: string | null;
  updatedAt: string | null;
  dateLabel: string;
}

export interface AssistantMessage {
  sequence: number;
  role: "user" | "assistant";
  content: string;
  createdAt: string | null;
  rendering: "plain_text" | "safe_markdown";
}

export interface AssistantMessagesResponse {
  items: AssistantMessage[];
  hasMoreBefore: boolean;
  nextBeforeSequence: number | null;
}

export interface AssistantConfirmation {
  requestId: string;
  sessionId?: string;
  actionType: "write_file" | "edit_file" | "exec" | "unknown";
  sanitizedSummary: string;
  status: "queued" | "active" | "approved" | "denied" | "timed_out" | "cancelled";
  expiresAt?: string | null;
}

export async function listAssistantSessions(query = "", limit = 200): Promise<AssistantSession[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (query.trim()) {
    params.set("query", query.trim());
  }
  const response = await requestJson<{ items: AssistantSession[] }>(`/api/assistant/sessions?${params}`);
  return response.items ?? [];
}

export async function createAssistantSession(input: {
  title?: string;
  toolIds?: string[];
} = {}): Promise<string> {
  const response = await requestJson<{ sessionId: string }>("/api/assistant/sessions", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return response.sessionId;
}

export async function renameAssistantSession(sessionId: string, title: string): Promise<AssistantSession> {
  return requestJson<AssistantSession>(`/api/assistant/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export async function deleteAssistantSession(sessionId: string): Promise<void> {
  await requestJson<{ archived: boolean }>(`/api/assistant/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}

export function listAssistantMessages(
  sessionId: string,
  options: { limit?: number; beforeSequence?: number } = {},
): Promise<AssistantMessagesResponse> {
  const params = new URLSearchParams({ limit: String(options.limit ?? 10) });
  if (options.beforeSequence !== undefined) {
    params.set("beforeSequence", String(options.beforeSequence));
  }
  return requestJson<AssistantMessagesResponse>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/messages?${params}`,
  );
}

export function sendAssistantMessage(
  sessionId: string,
  content: string,
): Promise<{ accepted: boolean; sessionId: string }> {
  return requestJson<{ accepted: boolean; sessionId: string }>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: "POST",
      body: JSON.stringify({ content }),
    },
  );
}

export function decideAssistantConfirmation(
  requestId: string,
  decision: "approve" | "deny",
): Promise<{ requestId: string; decision: "approve" | "deny"; accepted: boolean }> {
  return requestJson<{ requestId: string; decision: "approve" | "deny"; accepted: boolean }>(
    `/api/assistant/confirmations/${encodeURIComponent(requestId)}/decision`,
    {
      method: "POST",
      body: JSON.stringify({ decision }),
    },
  );
}

export type AssistantResult = Record<string, unknown>;

export async function fetchAssistant(client: DesktopApiClient): Promise<AssistantResult> {
  return client.request<AssistantResult>("/api/assistant");
}
