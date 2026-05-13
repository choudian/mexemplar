import { requestJson } from "./client";
import type { DesktopApiClient } from "./client";

export type CompositionMode = "range" | "ordered";

export interface CompositionMember {
  memberId?: string;
  toolId: string;
  name?: string;
  description?: string;
  selectedOrder: number;
  executionOrder?: number | null;
}

export interface CompositionSummary {
  compositionId: string;
  name: string;
  description: string;
  mode: CompositionMode;
  status: "draft" | "published" | "offline";
  displayStatus?: "draft" | "published" | "offline" | "needs_review";
  needsReview: boolean;
  applicability: string;
  members: CompositionMember[];
}

export interface CompositionInput {
  name: string;
  description: string;
  mode: CompositionMode;
  applicability: string;
  members: CompositionMember[];
}

export async function listCompositions(): Promise<CompositionSummary[]> {
  const response = await requestJson<{ items: CompositionSummary[] }>("/api/compositions");
  return response.items ?? [];
}

export function createComposition(input: CompositionInput): Promise<CompositionSummary> {
  return requestJson<CompositionSummary>("/api/compositions", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateComposition(compositionId: string, input: CompositionInput): Promise<CompositionSummary> {
  return requestJson<CompositionSummary>(`/api/compositions/${encodeURIComponent(compositionId)}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function generateApplicability(
  compositionId: string,
  input: CompositionInput,
): Promise<{ applicability: string }> {
  return requestJson<{ applicability: string }>(
    `/api/compositions/${encodeURIComponent(compositionId)}/generate-applicability`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function recommendOrder(
  compositionId: string,
  input: CompositionInput,
): Promise<{ members: CompositionMember[]; reason: string }> {
  return requestJson<{ members: CompositionMember[]; reason: string }>(
    `/api/compositions/${encodeURIComponent(compositionId)}/recommend-order`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function startCompositionTrial(compositionId: string): Promise<{ accepted: boolean; sessionId?: string }> {
  return requestJson<{ accepted: boolean; sessionId?: string }>(
    `/api/compositions/${encodeURIComponent(compositionId)}/trial`,
    {
      method: "POST",
      body: JSON.stringify({ task: "" }),
    },
  );
}

export function publishComposition(compositionId: string): Promise<CompositionSummary> {
  return requestJson<CompositionSummary>(`/api/compositions/${encodeURIComponent(compositionId)}/publish`, {
    method: "POST",
  });
}

export type CompositionsResult = Record<string, unknown>;

export async function fetchCompositions(client: DesktopApiClient): Promise<CompositionsResult> {
  return client.request<CompositionsResult>("/api/compositions");
}
