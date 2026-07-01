import { requestJson } from "./client";

export interface ImprovementProposalDto {
  id: string;
  sourceReviewId: string;
  findingIndex: number;
  status: "pending_review" | "approved" | "in_progress" | "done" | "failed" | "rejected";
  severity: string | null;
  findingType: string | null;
  what: string | null;
  evidence: string | null;
  suggestion: string | null;
  userSupplement: string | null;
  graphId: string | null;
  worktreeAvailable: boolean;
  branchName: string | null;
  resultTestsPassed: boolean | null;
  resultSummary: string | null;
  error: string | null;
  createdAt: string;
  decidedAt: string | null;
  completedAt: string | null;
}

export async function fetchImprovementProposals(
  status?: string,
  limit = 50,
): Promise<ImprovementProposalDto[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);
  const response = await requestJson<{ proposals: ImprovementProposalDto[] }>(
    `/api/improvement-proposals?${params}`,
  );
  return response.proposals ?? [];
}

export async function approveProposal(
  id: string,
  supplement = "",
): Promise<{ accepted: boolean; id?: string; status?: string; reason?: string }> {
  return requestJson(`/api/improvement-proposals/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ supplement }),
  });
}

export async function rejectProposal(
  id: string,
): Promise<{ accepted: boolean; id?: string; status?: string; reason?: string }> {
  return requestJson(`/api/improvement-proposals/${id}/reject`, {
    method: "POST",
  });
}
