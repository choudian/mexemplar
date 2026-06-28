import { requestJson } from "./client";

export interface ExecutionReviewFinding {
  type: string;
  what: string;
  evidence: string;
  severity: "high" | "med" | "low" | string;
  suggestion: string;
  worth_changing: boolean;
}

export interface ExecutionReviewDto {
  id: string;
  turnSessionId: string;
  verdict: string;
  findings: ExecutionReviewFinding[];
  advisory: boolean;
  modelUsed: string;
  createdAt: string;
  reviewedAt: string | null;
}

export async function fetchExecutionReviews(limit = 50): Promise<ExecutionReviewDto[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  const response = await requestJson<{ reviews: ExecutionReviewDto[] }>(`/api/execution-reviews?${params}`);
  return response.reviews ?? [];
}
