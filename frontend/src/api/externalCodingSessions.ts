import { requestJson } from "./client";

export type ExternalCodingTool = "claude_code" | "codex_cli";
export type ExternalCodingLaunchMode = "headless" | "interactive";
export type ExternalCodingOwnerType = "task" | "workflow";
export type ExternalCodingPhase = "plan" | "implement" | "merge" | "rollback" | "done";
export type ExternalCodingStatus =
  | "created"
  | "planning"
  | "plan_ready"
  | "plan_approved"
  | "plan_rejected"
  | "implementing"
  | "interrupted"
  | "waiting_user"
  | "completed"
  | "merge_ready"
  | "merged"
  | "merge_blocked"
  | "rollback_proposed"
  | "rolled_back"
  | "abandoned"
  | "failed";
export type ExternalCodingAttemptStatus = "running" | "succeeded" | "failed" | "interrupted";
export type ExternalCodingConflictRisk = "low" | "overlap" | "conflict_predicted" | "unknown";
export type ExternalCodingMergeRecordStatus = "analysis_ready" | "merged" | "blocked" | "failed" | "rolled_back";
export type ExternalCodingRollbackDecisionStatus = "proposed" | "applied" | "blocked" | "failed";
export type ExternalCodingRollbackStrategy = "revert_commit" | "reverse_patch" | "reset_hard" | "manual";
export type ExternalCodingErrorCategory =
  | "quota_exhausted"
  | "missing_artifact"
  | "protocol_violation"
  | "process_error"
  | "login_required"
  | "network"
  | "model_unavailable"
  | "unknown";
export type ExternalCodingQuotaState = "available" | "low" | "exhausted" | "unknown";
export type ExternalCodingAvailableAction =
  | "inspect"
  | "approve_plan"
  | "reject_plan"
  | "resume"
  | "escalate_to_user"
  | "merge_analysis"
  | "merge"
  | "abandon"
  | "rollback_plan"
  | "confirm_rollback";

export interface ExternalCodingAttemptDetail {
  attemptId: string;
  codingSessionId: string;
  phase: ExternalCodingPhase;
  launchMode: ExternalCodingLaunchMode;
  commandSummary?: string | null;
  externalSessionRef?: string | null;
  status: ExternalCodingAttemptStatus;
  pid?: number | null;
  exitCode?: number | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  logPath?: string | null;
  logTail?: string | null;
  errorCategory?: ExternalCodingErrorCategory | null;
  errorMessage?: string | null;
}

export interface ExternalCodingQuotaObservation {
  observationId: string;
  tool: ExternalCodingTool;
  state: ExternalCodingQuotaState;
  source?: string | null;
  confidence: number;
  resetAt?: string | null;
  checkedAt?: string | null;
  safeDetail?: string | null;
}

export interface ExternalCodingMergeRecordDetail {
  mergeRecordId: string;
  codingSessionId: string;
  targetBranch?: string | null;
  targetWorktreePath?: string | null;
  preMergeHead?: string | null;
  codingBranchHead?: string | null;
  dirtyFiles: string[];
  changedFiles: string[];
  overlapFiles: string[];
  conflictRisk: ExternalCodingConflictRisk;
  agentDecision?: string | null;
  status: ExternalCodingMergeRecordStatus;
  mergeCommit?: string | null;
  error?: string | null;
  createdAt?: string | null;
  mergedAt?: string | null;
}

export interface ExternalCodingRollbackDecisionDetail {
  rollbackId: string;
  codingSessionId: string;
  mergeRecordId?: string | null;
  intentSummary?: string | null;
  chosenStrategy: ExternalCodingRollbackStrategy;
  safeExplanation?: string | null;
  requiresConfirmation: boolean;
  confirmedBy?: string | null;
  status: ExternalCodingRollbackDecisionStatus;
  createdAt?: string | null;
  appliedAt?: string | null;
}

export interface ExternalCodingArtifacts {
  handoff: Record<string, string | null>;
  plan?: Record<string, string | null> | null;
  result?: Record<string, string | null> | null;
}

export interface ExternalCodingSessionTaskSummary {
  codingSessionId: string;
  tool: ExternalCodingTool;
  status: ExternalCodingStatus;
  phase: ExternalCodingPhase;
}

export interface ExternalCodingSessionSummary {
  codingSessionId: string;
  sessionId?: string | null;
  ownerType: ExternalCodingOwnerType;
  ownerId: string;
  tool: ExternalCodingTool;
  launchMode: ExternalCodingLaunchMode;
  status: ExternalCodingStatus;
  phase: ExternalCodingPhase;
  selectedReason?: string | null;
  quotaState?: ExternalCodingQuotaState | null;
  worktreePath: string;
  branchName: string;
  artifactDir: string;
  planPreview?: string | null;
  resultPreview?: string | null;
  logTail?: string | null;
  lastErrorCategory?: string | null;
  lastErrorMessage?: string | null;
  resumeCount: number;
  reviewRecommended: boolean;
  reviewSkippedReason?: string | null;
  createdAt: string;
  updatedAt: string;
  completedAt?: string | null;
}

export interface ExternalCodingSessionDetail extends ExternalCodingSessionSummary {
  attempts: ExternalCodingAttemptDetail[];
  quota: ExternalCodingQuotaObservation[];
  mergeRecords: ExternalCodingMergeRecordDetail[];
  rollbackDecisions: ExternalCodingRollbackDecisionDetail[];
  availableActions: ExternalCodingAvailableAction[];
  artifacts: ExternalCodingArtifacts;
}

export interface ExternalCodingSessionListResponse {
  items: ExternalCodingSessionSummary[];
}

export function listExternalCodingSessions(params?: {
  sessionId?: string;
  ownerType?: string;
  ownerId?: string;
  status?: string;
  limit?: number;
}): Promise<ExternalCodingSessionListResponse> {
  const query = new URLSearchParams();
  if (params?.sessionId) query.set("sessionId", params.sessionId);
  if (params?.ownerType) query.set("ownerType", params.ownerType);
  if (params?.ownerId) query.set("ownerId", params.ownerId);
  if (params?.status) query.set("status", params.status);
  if (params?.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return requestJson<ExternalCodingSessionListResponse>(
    `/api/external-coding/sessions${qs ? `?${qs}` : ""}`,
  );
}

export function getExternalCodingSession(
  codingSessionId: string,
): Promise<ExternalCodingSessionDetail> {
  return requestJson<ExternalCodingSessionDetail>(
    `/api/external-coding/sessions/${encodeURIComponent(codingSessionId)}`,
  );
}

export function refreshExternalCodingSession(
  codingSessionId: string,
): Promise<ExternalCodingSessionDetail> {
  return requestJson<ExternalCodingSessionDetail>(
    `/api/external-coding/sessions/${encodeURIComponent(codingSessionId)}/refresh`,
    { method: "POST", body: "{}" },
  );
}

export function decideExternalCodingPlan(
  codingSessionId: string,
  decision: "approved" | "rejected" | "clarification_requested",
  feedback?: string,
  decidedBy: "agent" | "user" = "user",
): Promise<ExternalCodingSessionDetail> {
  return requestJson<ExternalCodingSessionDetail>(
    `/api/external-coding/sessions/${encodeURIComponent(codingSessionId)}/plan-decision`,
    {
      method: "POST",
      body: JSON.stringify({ decision, decidedBy, feedback: feedback ?? "" }),
    },
  );
}

export function resumeExternalCodingSession(
  codingSessionId: string,
  params?: { instruction?: string; phase?: "plan" | "implement" },
): Promise<ExternalCodingSessionDetail> {
  return requestJson<ExternalCodingSessionDetail>(
    `/api/external-coding/sessions/${encodeURIComponent(codingSessionId)}/resume`,
    {
      method: "POST",
      body: JSON.stringify({
        instruction: params?.instruction ?? "",
        phase: params?.phase ?? null,
      }),
    },
  );
}

export function abandonExternalCodingSession(
  codingSessionId: string,
  reason: string,
): Promise<ExternalCodingSessionDetail> {
  return requestJson<ExternalCodingSessionDetail>(
    `/api/external-coding/sessions/${encodeURIComponent(codingSessionId)}/abandon`,
    { method: "POST", body: JSON.stringify({ reason }) },
  );
}

export function recordExternalCodingReviewOutcome(
  codingSessionId: string,
  params: {
    independentlyReviewed: boolean;
    independentlyTested: boolean;
    skippedReason?: string;
  },
): Promise<ExternalCodingSessionDetail> {
  return requestJson<ExternalCodingSessionDetail>(
    `/api/external-coding/sessions/${encodeURIComponent(codingSessionId)}/review-outcome`,
    {
      method: "POST",
      body: JSON.stringify({
        independentlyReviewed: params.independentlyReviewed,
        independentlyTested: params.independentlyTested,
        skippedReason: params.skippedReason ?? "",
      }),
    },
  );
}

export function escalateExternalCodingSession(
  codingSessionId: string,
  reason: string,
): Promise<ExternalCodingSessionDetail> {
  return requestJson<ExternalCodingSessionDetail>(
    `/api/external-coding/sessions/${encodeURIComponent(codingSessionId)}/escalate-to-user`,
    { method: "POST", body: JSON.stringify({ reason }) },
  );
}

export function analyzeExternalCodingMerge(
  codingSessionId: string,
  targetBranch: string,
  targetWorktreePath: string,
): Promise<ExternalCodingMergeRecordDetail> {
  return requestJson<ExternalCodingMergeRecordDetail>(
    `/api/external-coding/sessions/${encodeURIComponent(codingSessionId)}/merge-analysis`,
    {
      method: "POST",
      body: JSON.stringify({ targetBranch, targetWorktreePath }),
    },
  );
}

export function mergeExternalCodingSession(
  codingSessionId: string,
  mergeRecordId: string,
  agentDecision?: string,
): Promise<ExternalCodingMergeRecordDetail> {
  return requestJson<ExternalCodingMergeRecordDetail>(
    `/api/external-coding/sessions/${encodeURIComponent(codingSessionId)}/merge`,
    {
      method: "POST",
      body: JSON.stringify({
        mergeRecordId,
        agentDecision: agentDecision ?? "",
      }),
    },
  );
}

export function createRollbackPlan(
  codingSessionId: string,
  intentSummary: string,
): Promise<ExternalCodingRollbackDecisionDetail> {
  return requestJson<ExternalCodingRollbackDecisionDetail>(
    `/api/external-coding/sessions/${encodeURIComponent(codingSessionId)}/rollback-plan`,
    { method: "POST", body: JSON.stringify({ intentSummary }) },
  );
}

export function confirmRollback(
  codingSessionId: string,
  rollbackId: string,
  confirmedBy: "agent" | "user" = "user",
): Promise<ExternalCodingRollbackDecisionDetail> {
  return requestJson<ExternalCodingRollbackDecisionDetail>(
    `/api/external-coding/sessions/${encodeURIComponent(codingSessionId)}/confirm-rollback`,
    { method: "POST", body: JSON.stringify({ rollbackId, confirmedBy }) },
  );
}
