import { requestJson } from "./client";

// DTO 对齐 specs/033-scheduling-center/contracts/rest-api.md，字段一律 camelCase。

export type ScheduledTaskStatus = "active" | "paused" | "completed" | "expired";
export type ScheduleKind = "one_shot" | "recurring";
export type ScheduledTaskSource = "direct" | "todo";
export type ScheduledRunStatus =
  | "running"
  | "succeeded"
  | "failed"
  | "waiting_user"
  | "skipped";

export interface ScheduledTaskItem {
  scheduledTaskId: string;
  sourceType: ScheduledTaskSource;
  sourceRef: string;
  title: string;
  scheduleKind: ScheduleKind;
  scheduleDescription: string;
  status: ScheduledTaskStatus;
  unattendedAutoApprove: boolean;
  nextFireAt: string | null;
  lastFireAt: string | null;
  lastRunOutcome: ScheduledRunStatus | null;
  lastRunAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ScheduledTaskListResponse {
  items: ScheduledTaskItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface ScheduledTaskPatchInput {
  // 仅允许 status + unattendedAutoApprove（修改调度核心 = 删除重建，FR 第一批无修改能力）
  status?: "paused" | "active";
  unattendedAutoApprove?: boolean;
}

interface ScheduledTaskRunBase {
  runId: string;
  scheduledTaskId: string;
  startedAt: string;
  finishedAt: string | null;
  summary: string | null;
  failureReason: string | null;
}

export type ScheduledTaskStartedRunItem = ScheduledTaskRunBase & {
  status: "running";
  sessionId: string;
};

export type ScheduledTaskRunItem =
  | (ScheduledTaskRunBase & {
      status: "skipped";
      sessionId: null;
    })
  | (ScheduledTaskRunBase & {
      status: Exclude<ScheduledRunStatus, "running" | "skipped">;
      sessionId: string;
    })
  | ScheduledTaskStartedRunItem;

export interface ScheduledTaskRunListResponse {
  items: ScheduledTaskRunItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface TakeoverResponse {
  sessionId: string;
  recoveryDraft: string | null;
}

export interface SchedulingConfirmationDraft {
  title: string;
  scheduleDescription: string;
  instruction: string;
  scheduleKind: ScheduleKind;
  sourceType: ScheduledTaskSource;
}

export interface PendingSchedulingConfirmation {
  requestId: string;
  sessionId: string;
  draft: SchedulingConfirmationDraft;
  unattendedAutoApprove: boolean;
  expiresAt: string;
  status: "pending";
}

export interface PendingSchedulingConfirmationsResponse {
  items: PendingSchedulingConfirmation[];
}

export type SchedulingConfirmationDecision = "confirm" | "cancel";

export interface SchedulingConfirmationDecisionInput {
  decision: SchedulingConfirmationDecision;
  editedDraft?: SchedulingConfirmationDraft;
  unattendedAutoApprove?: boolean;
}

export interface ScheduledTaskListParams {
  status?: ScheduledTaskStatus;
  limit?: number;
  offset?: number;
}

export interface ScheduledRunListParams {
  limit?: number;
  offset?: number;
}

export function listScheduledTasks(
  params: ScheduledTaskListParams = {},
): Promise<ScheduledTaskListResponse> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  query.set("limit", String(params.limit ?? 100));
  query.set("offset", String(params.offset ?? 0));
  return requestJson<ScheduledTaskListResponse>(`/api/scheduled-tasks?${query}`);
}

export function getScheduledTask(taskId: string): Promise<ScheduledTaskItem> {
  return requestJson<ScheduledTaskItem>(
    `/api/scheduled-tasks/${encodeURIComponent(taskId)}`,
  );
}

export function patchScheduledTask(
  taskId: string,
  patch: ScheduledTaskPatchInput,
): Promise<ScheduledTaskItem> {
  return requestJson<ScheduledTaskItem>(
    `/api/scheduled-tasks/${encodeURIComponent(taskId)}`,
    { method: "PATCH", body: JSON.stringify(patch) },
  );
}

export function fireScheduledTaskNow(taskId: string): Promise<ScheduledTaskStartedRunItem> {
  return requestJson<ScheduledTaskStartedRunItem>(
    `/api/scheduled-tasks/${encodeURIComponent(taskId)}/fire-now`,
    { method: "POST" },
  );
}

export async function deleteScheduledTask(taskId: string): Promise<void> {
  await requestJson<void>(
    `/api/scheduled-tasks/${encodeURIComponent(taskId)}`,
    { method: "DELETE" },
  );
}

export function listScheduledTaskRuns(
  taskId: string,
  params: ScheduledRunListParams = {},
): Promise<ScheduledTaskRunListResponse> {
  const query = new URLSearchParams();
  query.set("limit", String(params.limit ?? 50));
  query.set("offset", String(params.offset ?? 0));
  return requestJson<ScheduledTaskRunListResponse>(
    `/api/scheduled-tasks/${encodeURIComponent(taskId)}/runs?${query}`,
  );
}

export function takeoverScheduledRun(
  taskId: string,
  runId: string,
): Promise<TakeoverResponse> {
  return requestJson<TakeoverResponse>(
    `/api/scheduled-tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/takeover`,
    { method: "POST" },
  );
}

export async function submitSchedulingConfirmationDecision(
  requestId: string,
  input: SchedulingConfirmationDecisionInput,
): Promise<ScheduledTaskItem | null> {
  // confirm 返回新建的 ScheduledTaskItem（204 之外的成功体）；cancel 后端返 204。
  // requestJson 把 204 归一成 undefined，这里统一返回 null 表示无 body。
  const result = await requestJson<ScheduledTaskItem | null>(
    `/api/scheduled-tasks/confirmations/${encodeURIComponent(requestId)}/decision`,
    { method: "POST", body: JSON.stringify(input) },
  );
  return result ?? null;
}

export function listPendingSchedulingConfirmations(): Promise<PendingSchedulingConfirmationsResponse> {
  return requestJson<PendingSchedulingConfirmationsResponse>(
    `/api/scheduled-tasks/confirmations/pending`,
  );
}
