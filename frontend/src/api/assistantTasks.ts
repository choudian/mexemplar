import { requestJson } from "./client";
import type { ExternalCodingSessionTaskSummary } from "./externalCodingSessions";

export type TaskStatus =
  | "pending_dispatch"
  | "running"
  | "suspended"
  | "completed"
  | "failed"
  | "cancelled";

export type SuspendReason =
  | "waiting_user"
  | "waiting_system"
  | "user_stop"
  | "budget_exhausted"
  | "interrupted";

/** 暂停时球在谁手上——谁能让这个活继续。 */
export type WaitingOn = "user" | "assistant" | "system";

export type TaskDisplayPhase =
  | "running"
  | "reviewing"
  | "needs_attention"
  | "paused"
  | "done";

/**
 * 这个节点能不能由用户点「继续」推动。
 *
 * 判据必须与后端 `continue_graph` 的谓词一致：暂停中、且不是在等一个具体答案。
 * `waiting_user` 要的是回答问题（由 `answer_question` 复活），无参数的「继续」推不动它。
 *
 * 这个判断原本在四个组件里各抄了一遍 `displayPhase === "paused" && suspendReason === "user_stop"`
 * ——跟后端旧谓词犯同一个错，于是撞轮次预算暂停的活在卡片上**根本没有「继续」按钮**。
 * 抄四遍的判断迟早各自漂移，收敛到这里。
 *
 * ⚠️ 后端 `continue_graph` 的谓词加排除项时，**这里必须同步改**。判据是「用户点了
 * 继续之后，这个活能不能真的往前走」——不能的（例如将来的「撞上程序缺陷」：代码不改
 * 重试多少次都是同一个错）该给的是跳过 / 放弃 / 上报，不是继续。
 * 只改后端会让按钮还在、点下去后端拒绝、界面什么都不发生；只改这里则别的入口仍会白派一次。
 */
export function canContinueTask(task: {
  displayPhase?: TaskDisplayPhase | null;
  suspendReason?: SuspendReason | null;
}): boolean {
  return task.displayPhase === "paused" && task.suspendReason !== "waiting_user";
}

export interface AssistantActorRef {
  type: "ephemeral_subagent" | "specialist";
  id: string;
  label?: string | null;
}

export interface AssistantTaskSnapshot {
  taskId: string;
  graphId: string;
  parentTaskId?: string | null;
  title: string;
  descriptionPreview: string;
  status: TaskStatus;
  displayPhase: TaskDisplayPhase;
  requiresReview: boolean;
  requiresConfirmation: boolean;
  safeExplanation: string;
  suspendReason?: SuspendReason | null;
  waitingOn?: WaitingOn | null;
  assignee?: AssistantActorRef | null;
  adjudicationId?: string | null;
  updatedAt?: string | null;
  externalCodingSessions?: ExternalCodingSessionTaskSummary[];
}

export interface AssistantTaskEdgeSnapshot {
  sourceTaskId: string;
  targetTaskId: string;
  type: "dependency" | "delegation" | "question" | "meeting_channel" | "resource_request";
}

export interface AssistantTaskAdjudicationSnapshot {
  adjudicationId: string;
  taskId: string;
  safeSummary: string;
  deliveredStatus: "done" | "stuck" | "failed_input";
}

export interface AssistantTaskGraphSnapshot {
  graphId: string;
  sessionId: string;
  userMessageSequence?: number | null;
  version: number;
  tasks: AssistantTaskSnapshot[];
  edges: AssistantTaskEdgeSnapshot[];
  adjudications: AssistantTaskAdjudicationSnapshot[];
}

export interface AssistantTaskBoardItem {
  taskId: string;
  graphId: string;
  title: string;
  status: TaskStatus;
  claimStatus: "open" | "claimed";
  claimId?: string | null;
  assignee?: AssistantActorRef | null;
  updatedAt?: string | null;
}

export interface AssistantTaskBoardResponse {
  items: AssistantTaskBoardItem[];
}

export interface AssistantMeetingParticipant {
  type: "ephemeral_subagent" | "specialist";
  id: string;
  label?: string | null;
}

export interface AssistantMeetingMessage {
  sequence: number;
  senderId: string;
  content: string;
  createdAt?: string | null;
}

export interface AssistantMeetingTranscript {
  channelId: string;
  status: "open" | "concluded" | "closed_timeout" | "closed_abandoned";
  participants: AssistantMeetingParticipant[];
  turnsUsed: number;
  turnBudget: number;
  messages: AssistantMeetingMessage[];
  nextAfterSequence?: number | null;
  conclusion?: string | null;
}

export type AssistantTodoStatus = "todo" | "doing" | "done" | "skipped";

export interface AssistantTodoItem {
  todoId: string;
  text: string;
  status: AssistantTodoStatus;
  sortOrder: number;
}

export interface AssistantTodoResponse {
  taskId: string;
  items: AssistantTodoItem[];
}

export interface CurrentAssistantTaskGraphResponse {
  graph: AssistantTaskGraphSnapshot | null;
}

export interface TaskGraphStopResponse {
  accepted: boolean;
  graphId: string;
  affectedTaskCount: number;
  cancelSignalAccepted?: boolean;
}

export interface TaskGraphContinueResponse {
  accepted: boolean;
  graphId: string;
  resumedTaskCount: number;
  startedAttemptCount?: number;
}

export type TaskAdjudicationDecision = "accepted" | "returned" | "abandoned";

export interface TaskAdjudicationDecisionResponse {
  accepted: boolean;
  adjudicationId: string;
  taskId: string;
  graphId: string;
  decision: TaskAdjudicationDecision;
  taskStatus: TaskStatus;
}

export async function getCurrentAssistantTaskGraph(
  sessionId: string,
): Promise<CurrentAssistantTaskGraphResponse> {
  return requestJson<CurrentAssistantTaskGraphResponse>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/task-graphs/current`,
  );
}

/** Fetch a specific historical task graph snapshot by graphId.
 * Used by the DAG viewer for scheduled run history. */
export async function getAssistantTaskGraph(
  sessionId: string,
  graphId: string,
): Promise<AssistantTaskGraphSnapshot> {
  return requestJson<AssistantTaskGraphSnapshot>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/task-graphs/${encodeURIComponent(graphId)}`,
  );
}

export async function stopAssistantTaskGraph(
  sessionId: string,
  graphId: string,
  runId?: string | null,
): Promise<TaskGraphStopResponse> {
  return requestJson<TaskGraphStopResponse>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/task-graphs/${encodeURIComponent(graphId)}/stop`,
    { method: "POST", body: JSON.stringify({ runId: runId ?? null }) },
  );
}

export async function continueAssistantTaskGraph(
  sessionId: string,
  graphId: string,
): Promise<TaskGraphContinueResponse> {
  return requestJson<TaskGraphContinueResponse>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/task-graphs/${encodeURIComponent(graphId)}/continue`,
    { method: "POST" },
  );
}

export async function decideAssistantTaskAdjudication(
  sessionId: string,
  adjudicationId: string,
  decision: TaskAdjudicationDecision,
  instruction = "",
): Promise<TaskAdjudicationDecisionResponse> {
  return requestJson<TaskAdjudicationDecisionResponse>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/task-adjudications/${encodeURIComponent(adjudicationId)}/decision`,
    { method: "POST", body: JSON.stringify({ decision, instruction }) },
  );
}

export async function getAssistantTaskBoard(
  sessionId: string,
): Promise<AssistantTaskBoardResponse> {
  return requestJson<AssistantTaskBoardResponse>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/task-board`,
  );
}

export async function getAssistantMeetingTranscript(
  sessionId: string,
  channelId: string,
  afterSequence?: number | null,
  limit?: number | null,
): Promise<AssistantMeetingTranscript> {
  const params = new URLSearchParams();
  if (afterSequence !== undefined && afterSequence !== null) {
    params.set("afterSequence", String(afterSequence));
  }
  if (limit !== undefined && limit !== null) {
    params.set("limit", String(limit));
  }
  const query = params.toString();
  return requestJson<AssistantMeetingTranscript>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/meetings/${encodeURIComponent(channelId)}${query ? `?${query}` : ""}`,
  );
}

export async function getAssistantTaskTodos(
  sessionId: string,
  taskId: string,
): Promise<AssistantTodoResponse> {
  return requestJson<AssistantTodoResponse>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/tasks/${encodeURIComponent(taskId)}/todos`,
  );
}

export async function updateAssistantTaskTodos(
  sessionId: string,
  taskId: string,
  executorType: "ephemeral_subagent" | "specialist",
  executorId: string,
  items: AssistantTodoItem[],
): Promise<AssistantTodoResponse> {
  return requestJson<AssistantTodoResponse>(
    `/api/assistant/sessions/${encodeURIComponent(sessionId)}/tasks/${encodeURIComponent(taskId)}/todos`,
    {
      method: "PUT",
      body: JSON.stringify({ executorType, executorId, items }),
    },
  );
}
