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

/** 某 user_task 名下一张图的摘要。 */
export interface UserTaskGraphSummary {
  graphId: string;
  rootTaskId: string;
  title: string;
  nodeCount: number;
  status: string;
  createdAt?: string | null;
}

export interface UserTaskGraphsResponse {
  graphs: UserTaskGraphSummary[];
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

export async function getUserTaskGraphs(
  sessionId: string,
  taskId: string,
): Promise<UserTaskGraphsResponse> {
  return requestJson<UserTaskGraphsResponse>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/user-tasks/${encodeURIComponent(taskId)}/graphs`,
  );
}
