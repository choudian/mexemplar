import { requestJson } from "./client";

export type SkillCategory = "pending" | "published" | "failed";

export interface SkillSummary {
  toolId: string;
  name: string;
  description: string;
  status: "pending" | "published" | "failed" | "offline";
  source: string;
  trialSuccessCount: number;
  workflowId?: string | null;
  failureStage?: string | null;
  errorSummary?: string;
}

export interface SkillCategoryResponse {
  category: SkillCategory;
  count: number;
  items: SkillSummary[];
}

export function getSkills(category: SkillCategory): Promise<SkillCategoryResponse> {
  return requestJson<SkillCategoryResponse>(`/api/skills?category=${category}`);
}

export function startSkillTrial(toolId: string): Promise<{ accepted: boolean; workflowId?: string }> {
  return requestJson<{ accepted: boolean; workflowId?: string }>(`/api/skills/${encodeURIComponent(toolId)}/trial`, {
    method: "POST",
  });
}

export function replySkillTrial(toolId: string, content: string): Promise<{ accepted: boolean }> {
  return requestJson<{ accepted: boolean }>(`/api/skills/${encodeURIComponent(toolId)}/trial/reply`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

interface TrialMessage {
  role: "user" | "assistant";
  content: string;
}

export interface TrialHistoryResponse {
  messages: TrialMessage[];
  workflowId: string | null;
}

export function getSkillTrialHistory(toolId: string): Promise<TrialHistoryResponse> {
  return requestJson<TrialHistoryResponse>(`/api/skills/${encodeURIComponent(toolId)}/trial/messages`);
}

export function updateSkillMetadata(
  toolId: string,
  input: { name: string; description: string },
): Promise<{ toolId: string; referencedCompositions: string[] }> {
  return requestJson<{ toolId: string; referencedCompositions: string[] }>(
    `/api/skills/${encodeURIComponent(toolId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
    },
  );
}

export function deleteSkill(toolId: string): Promise<{ accepted: boolean }> {
  return requestJson<{ accepted: boolean }>(`/api/skills/${encodeURIComponent(toolId)}`, {
    method: "DELETE",
  });
}

export function retryFailure(workflowId: string): Promise<{ accepted: boolean }> {
  return requestJson<{ accepted: boolean }>(`/api/skills/failures/${encodeURIComponent(workflowId)}/retry`, {
    method: "POST",
  });
}

export function dismissFailure(workflowId: string): Promise<{ accepted: boolean }> {
  return requestJson<{ accepted: boolean }>(`/api/skills/failures/${encodeURIComponent(workflowId)}/dismiss`, {
    method: "POST",
  });
}
