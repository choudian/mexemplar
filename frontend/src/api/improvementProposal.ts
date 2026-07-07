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
  discussionSessionId: string | null;
  createdAt: string;
  decidedAt: string | null;
  completedAt: string | null;
}

export interface ProposalSourceAnchor {
  sessionId?: string;
  messageId?: string;
  sequence?: number;
  sourceReviewId?: string;
  findingIndex?: number;
  stepIndex?: number;
  toolName?: string;
  outputRef?: string;
}

export interface ProposalSourceEvidenceItem {
  id: string;
  kind: string;
  label: string;
  excerpt: string;
  truncated: boolean;
  anchor: ProposalSourceAnchor;
  reason: string;
}

export interface ProposalSourceMessageItem {
  kind: "message";
  messageId: string;
  sessionId: string;
  sequence: number;
  role: string;
  toolName: string | null;
  excerpt: string;
  truncated: boolean;
  createdAt: string | null;
  anchor: ProposalSourceAnchor;
}

export type ProposalSourceView = "overview" | "messages" | "prompt" | "timeline" | "tool_output";

export interface ProposalSourcePromptPackage {
  system: string;
  systemTruncated: boolean;
  userPayload: string;
  userPayloadTruncated: boolean;
  tools: Array<{ name: string; description: string }>;
}

export interface ProposalSourceTimelineItem {
  id: string;
  type: string;
  label: string;
  sequence?: number | null;
  role?: string | null;
  callId?: string | null;
  toolName?: string | null;
  argsPreview?: string | null;
  argsTruncated?: boolean;
  ok?: boolean;
  outcome?: string;
  resultSize?: number;
  outputRef?: string | null;
  excerpt?: string | null;
  truncated?: boolean;
  createdAt?: string | null;
  anchor?: ProposalSourceAnchor;
}

export interface ProposalSourceReference {
  referenceId: string;
  toolName?: string | null;
  kind?: string | null;
  sizeBytes?: number | null;
  contentType?: string | null;
  status?: string | null;
  expiresAt?: string | null;
}

export interface ProposalSourcePackage {
  proposalId: string;
  view: ProposalSourceView;
  scope: string;
  scopeNote?: string | null;
  proposal: Record<string, unknown>;
  source: {
    sourceReviewId?: string | null;
    findingIndex?: number | null;
    turnSessionId?: string | null;
    reviewStatus?: string | null;
    reviewedAt?: string | null;
    createdAt?: string | null;
    modelUsed?: string | null;
    available?: boolean;
  };
  review?: {
    verdict?: string;
    currentFinding?: Record<string, unknown> | null;
    findingCount?: number;
  } | null;
  evidence?: ProposalSourceEvidenceItem[] | null;
  nextActions?: Array<{ view: string; label: string; description: string }> | null;
  items?: ProposalSourceMessageItem[] | null;
  prompt?: ProposalSourcePromptPackage | null;
  timeline?: ProposalSourceTimelineItem[] | null;
  reference?: ProposalSourceReference | null;
  content?: string | null;
  contentTruncated?: boolean | null;
  error?: { code?: string; message?: string } | null;
  page?: {
    cursor?: string | null;
    nextCursor?: string | null;
    offset?: number | null;
    nextOffset?: number | null;
    limit: number;
    hasMore: boolean;
    bytesReturned?: number;
  } | null;
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

export async function openProposalDiscussion(
  id: string,
): Promise<{ sessionId: string; created: boolean }> {
  return requestJson(`/api/improvement-proposals/${id}/discussion`, {
    method: "POST",
  });
}

export async function fetchProposalSource(
  id: string,
  options: {
    view?: ProposalSourceView;
    cursor?: string | null;
    limit?: number;
    referenceId?: string | null;
    offset?: number | null;
    maxBytes?: number;
  } = {},
): Promise<ProposalSourcePackage> {
  const params = new URLSearchParams();
  params.set("view", options.view ?? "overview");
  params.set("limit", String(options.limit ?? 20));
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.referenceId) params.set("referenceId", options.referenceId);
  if (options.offset != null) params.set("offset", String(options.offset));
  if (options.maxBytes != null) params.set("maxBytes", String(options.maxBytes));
  return requestJson<ProposalSourcePackage>(
    `/api/improvement-proposals/${encodeURIComponent(id)}/source?${params}`,
  );
}
