import { requestJson } from "./client";

export type TeachingMode = "browser" | "extension" | "desktop";
export type TeachingStage =
  | "selecting"
  | "recording"
  | "intent_confirmation"
  | "learning"
  | "trial_validation"
  | "published"
  | "failed"
  | "abandoned";

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

export function getTeachingReadiness(): Promise<{ modes: RecordingModeReadiness[] }> {
  return requestJson<{ modes: RecordingModeReadiness[] }>("/api/teaching/readiness");
}

export function createTeachingRun(mode: TeachingMode): Promise<TeachingRun> {
  return requestJson<TeachingRun>("/api/teaching/runs", {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
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

export function startTeachingTrial(workflowId: string): Promise<TeachingRun> {
  return requestJson<TeachingRun>(`/api/teaching/runs/${encodeURIComponent(workflowId)}/trial/start`, {
    method: "POST",
  });
}
