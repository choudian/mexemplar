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
  /** 这件事此刻是否真的在推进（后端权威判据，含图有没有在跑）。不要从
   *  distribution 自己推：图停掉之后剩下的「待开始」不会再被派发。 */
  active?: boolean;
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
  stillFinishing: UserTaskContinueReportItem[];
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
  /** plan=planner 的 DAG（展示局部图）；request=委派容器（节点平铺为执行体） */
  kind?: string | null;
  createdAt?: string | null;
  /** 建图那一刻的消息序号，用于把局部图按发生顺序插进卡片的流里 */
  userMessageSequence?: number | null;
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
