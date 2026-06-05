import { requestJson } from "./client";

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
  role: "user" | "assistant" | "summary";
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
  actionType: "write_file" | "edit_file" | "exec" | "skill.edit_protected" | "skill.soft_delete" | "unknown";
  sanitizedSummary: string;
  status: "queued" | "active" | "approved" | "denied" | "timed_out" | "cancelled";
  expiresAt?: string | null;
  affectedSkillId?: string;
  affectedEquipmentCount?: number;
  affectedSpecialistNames?: string[];
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
  options: {
    continueSubagent?: {
      subagentId: string;
      supplemental?: string;
    };
  } = {},
): Promise<{ accepted: boolean; sessionId: string }> {
  return requestJson<{ accepted: boolean; sessionId: string }>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: "POST",
      body: JSON.stringify({
        content,
        ...(options.continueSubagent ? { continueSubagent: options.continueSubagent } : {}),
      }),
    },
  );
}

export function stopAssistantRun(sessionId: string, runId?: string): Promise<{ accepted: boolean }> {
  return requestJson<{ accepted: boolean }>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/stop`,
    {
      method: "POST",
      ...(runId ? { body: JSON.stringify({ runId }) } : {}),
    },
  );
}

export interface AssistantActivityStep {
  kind: "reasoning" | "tool_call" | "tool_result";
  toolName?: string | null;
  text: string;
  seq: number;
}

export interface AssistantTranscript {
  steps: AssistantActivityStep[];
  compressed: boolean;
}

export function getSubagentTranscript(
  sessionId: string,
  subagentId?: string,
  options: { afterSequence?: number; beforeSequence?: number } = {},
): Promise<AssistantTranscript> {
  const params = new URLSearchParams();
  if (subagentId) {
    params.set("subagentId", subagentId);
  }
  if (options.afterSequence !== undefined) {
    params.set("afterSequence", String(options.afterSequence));
  }
  if (options.beforeSequence !== undefined) {
    params.set("beforeSequence", String(options.beforeSequence));
  }
  const query = params.toString();
  return requestJson<AssistantTranscript>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/transcript${query ? `?${query}` : ""}`,
  );
}

export type SubagentStatus = "running" | "done" | "suspended" | "failed";

export interface AssistantSubagentSummary {
  subagentId: string;
  label: string;
  task: string;
  status: SubagentStatus;
  lastOutput?: string | null;
  turnStartSequence?: number | null;
}

export async function listSubagents(sessionId: string): Promise<AssistantSubagentSummary[]> {
  const response = await requestJson<{ items: AssistantSubagentSummary[] }>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/subagents`,
  );
  return response.items ?? [];
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

export function triggerAssistantSegmentIdle(
  sessionId: string,
): Promise<{ segment_id: string | null; status: string | null }> {
  return requestJson<{ segment_id: string | null; status: string | null }>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/segment-idle`,
    { method: "POST" },
  );
}

export function triggerAssistantSegmentBoundary(
  sessionId: string,
  reason: "window_close" | "new_session" | "token_limit",
): Promise<{ segment_id: string | null; status: string | null }> {
  return requestJson<{ segment_id: string | null; status: string | null }>("/api/assistant/segment-boundary", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, reason }),
  });
}

export async function setAssistantAutoApprove(enabled: boolean): Promise<boolean> {
  const response = await requestJson<{ enabled: boolean }>("/api/assistant/confirmations/auto-approve", {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
  return response.enabled;
}
