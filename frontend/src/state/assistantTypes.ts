import type { AssistantActivityStep, AssistantMessage, SubagentStatus } from "../api/assistant";

export type AssistantProgress = {
  // "cancelled"=用户主动停止（014）：视为非 running，解锁输入、不自动派发排队消息。
  status: "idle" | "running" | "waiting_for_user" | "succeeded" | "failed" | "cancelled";
  headline: string;
  // 后端运行代际令牌；停止时回传，避免迟到的旧停止请求误取消新一轮运行。
  runId?: string;
};

export type PendingAssistantMessage = Omit<AssistantMessage, "sequence"> & {
  optimisticId: string;
  sessionId: string;
};

// === 014-assistant-chat-transparency 生产态共享类型 ===

export type ActivityStepKind = "reasoning" | "tool_call" | "tool_result";

/** 主助理或子任务在一回合内的单步活动（来自 assistant.activity 事件 / transcript 重建）。 */
export type ActivityStep = AssistantActivityStep & {
  // null/缺省=主助理时间线；非空=归属某子任务卡片
  subagentId?: string | null;
};

/** 子任务卡片壳与状态（来自 assistant.subagent 事件 / 权威 listSubagents）。 */
export type Subagent = {
  subagentId: string;
  label: string;
  task: string;
  status: SubagentStatus;
  lastOutput?: string;
};

/** 单个"用户消息 -> 助理过程 -> 最终回复"回合承载自己的过程与子任务。 */
export type AssistantTurnActivity = {
  turnId: string;
  fromSequence?: number;
  beforeSequence?: number;
  steps: ActivityStep[];
  subagents: Subagent[];
  transcriptCompressed?: boolean;
  transcriptResynced?: boolean;
};

export type QueuedMessageState = "editing" | "queued";

/** 单条原地排队消息（前端临时状态，每会话至多一条；不持久化到后端）。 */
export type QueuedMessage = {
  text: string;
  state: QueuedMessageState;
};

export const idleProgress: AssistantProgress = { status: "idle", headline: "" };
