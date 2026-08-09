import { requestJson } from "./client";

export interface UserTaskItem {
  taskId: string;
  title: string;
  description: string;
  status: string;
}

export interface UserTaskListResponse {
  tasks: UserTaskItem[];
}

/** 用户任务状态分布（供界面画分布条）。key 形如 done / running / suspended:user 等。 */
export type TaskDistribution = Record<string, number>;

export interface UserTaskDistributionResponse {
  taskId: string;
  distribution: TaskDistribution;
}

/** 用户点继续的结构化回报。 */
export interface UserTaskContinueReportItem {
  title: string;
  reason?: string;
  graphId?: string;
}

export interface UserTaskContinueResponse {
  pushed: UserTaskContinueReportItem[];
  notPushed: UserTaskContinueReportItem[];
  total: number;
  success: boolean;
}

export async function listUserTasks(
  sessionId: string,
  statusFilter = "open",
): Promise<UserTaskListResponse> {
  return requestJson<UserTaskListResponse>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/user-tasks?statusFilter=${encodeURIComponent(statusFilter)}`,
  );
}

export async function getUserTaskDistribution(
  sessionId: string,
  taskId: string,
): Promise<UserTaskDistributionResponse> {
  return requestJson<UserTaskDistributionResponse>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/user-tasks/${encodeURIComponent(taskId)}/distribution`,
  );
}

export async function continueUserTask(
  sessionId: string,
  taskId: string,
): Promise<UserTaskContinueResponse> {
  return requestJson<UserTaskContinueResponse>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/user-tasks/${encodeURIComponent(taskId)}/continue`,
    { method: "POST" },
  );
}
