import { requestJson } from "./client";
import type { TeachingStage, TrialPreviewRequestedEvent } from "./uiEvents";

export type TeachingMode = "browser" | "extension" | "desktop";
export type { TeachingStage };

export interface RecordingModeReadiness {
  mode: TeachingMode;
  status: "ready" | "needs_setup" | "unavailable";
  message: string;
  actions: string[];
}

export interface TeachingRun {
  workflowId: string;
  mode: TeachingMode;
  stage: TeachingStage;
  readiness?: { modes: RecordingModeReadiness[] } | null;
  summary: Record<string, unknown>;
}

export type TrialPreviewRequest = TrialPreviewRequestedEvent["payload"];

type TrialPreviewDecisionStatus = "approved" | "denied" | "already_resolved" | "conflict" | "expired";

export type TrialPreviewDecisionResponse =
  | { requestId: string; decision: "approve" | "deny"; accepted: true; status: "approved" | "denied" }
  | {
      requestId: string;
      decision: "approve" | "deny";
      accepted: false;
      status: Exclude<TrialPreviewDecisionStatus, "approved" | "denied">;
    };

export function getTeachingReadiness(): Promise<{ modes: RecordingModeReadiness[] }> {
  return requestJson<{ modes: RecordingModeReadiness[] }>("/api/teaching/readiness");
}

export function createTeachingRun(mode: TeachingMode): Promise<TeachingRun> {
  return requestJson<TeachingRun>("/api/teaching/runs", {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

export function getTeachingRun(workflowId: string): Promise<TeachingRun> {
  return requestJson<TeachingRun>(`/api/teaching/runs/${encodeURIComponent(workflowId)}`);
}

export function startTeachingRecording(
  workflowId: string,
  mode: TeachingMode,
  windowMinimized = false,
): Promise<TeachingRun> {
  return requestJson<TeachingRun>(`/api/teaching/runs/${encodeURIComponent(workflowId)}/recording/start`, {
    method: "POST",
    body: JSON.stringify({ mode, windowMinimized }),
  });
}

export function stopTeachingRecording(workflowId: string): Promise<TeachingRun> {
  return requestJson<TeachingRun>(`/api/teaching/runs/${encodeURIComponent(workflowId)}/recording/stop`, {
    method: "POST",
  });
}

export function decideDesktopHealth(
  workflowId: string,
  decision: "continue" | "discard" | "rerecord",
): Promise<TeachingRun> {
  return requestJson<TeachingRun>(
    `/api/teaching/runs/${encodeURIComponent(workflowId)}/recording/desktop-health-decision`,
    {
      method: "POST",
      body: JSON.stringify({ decision }),
    },
  );
}

export function replyTeachingIntent(workflowId: string, content: string): Promise<TeachingRun> {
  return requestJson<TeachingRun>(`/api/teaching/runs/${encodeURIComponent(workflowId)}/intent/reply`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function decideTrialPreview(
  requestId: string,
  decision: "approve" | "deny",
): Promise<TrialPreviewDecisionResponse> {
  return requestJson<TrialPreviewDecisionResponse>(`/api/teaching/trial-preview/${encodeURIComponent(requestId)}/decision`, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });
}
