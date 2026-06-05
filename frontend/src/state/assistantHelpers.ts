import type { AssistantMessage } from "../api/assistant";
import type { ActivityStep, AssistantTurnActivity, PendingAssistantMessage, Subagent } from "./assistantTypes";

export function emptyTurn(turnId: string): AssistantTurnActivity {
  return { turnId, steps: [], subagents: [] };
}

export function uniqueMessages(messages: AssistantMessage[]): AssistantMessage[] {
  const bySequence = new Map<number, AssistantMessage>();
  for (const message of messages) {
    bySequence.set(message.sequence, message);
  }
  return Array.from(bySequence.values()).sort((a, b) => a.sequence - b.sequence);
}

export function nextOptimisticId(): string {
  return `optimistic_${crypto.randomUUID()}`;
}

export function turnIdFromSequence(sequence: number): string {
  return `seq_${sequence}`;
}

export function turnIdFromMessage(message: AssistantMessage | PendingAssistantMessage): string | null {
  if (message.role !== "user") return null;
  return "optimisticId" in message ? message.optimisticId : turnIdFromSequence(message.sequence);
}

/** 更新 turnActivityBySession 中某个 turn 的辅助函数，替代 4 层嵌套 spread。 */
export function updateTurn(
  state: { turnActivityBySession: Record<string, Record<string, AssistantTurnActivity>> },
  sessionId: string,
  turnId: string,
  updater: (turn: AssistantTurnActivity) => AssistantTurnActivity,
): { turnActivityBySession: Record<string, Record<string, AssistantTurnActivity>> } {
  const turns = state.turnActivityBySession;
  const sessionTurns = turns[sessionId] ?? {};
  const existing = sessionTurns[turnId] ?? emptyTurn(turnId);
  return {
    turnActivityBySession: {
      ...turns,
      [sessionId]: { ...sessionTurns, [turnId]: updater(existing) },
    },
  };
}

export function getTurn(
  turnsBySession: Record<string, Record<string, AssistantTurnActivity>>,
  sessionId: string,
  turnId: string,
): AssistantTurnActivity {
  return turnsBySession[sessionId]?.[turnId] ?? emptyTurn(turnId);
}

/** 从 turnActivityBySession 中不可变地移除某个 turn（updateTurn 的镜像），替代各处手写 delete。 */
function removeTurn(
  state: { turnActivityBySession: Record<string, Record<string, AssistantTurnActivity>> },
  sessionId: string,
  turnId: string,
): { turnActivityBySession: Record<string, Record<string, AssistantTurnActivity>> } {
  const turns = state.turnActivityBySession;
  const sessionTurns = turns[sessionId];
  if (!sessionTurns || !(turnId in sessionTurns)) {
    return { turnActivityBySession: turns };
  }
  const nextSessionTurns = { ...sessionTurns };
  delete nextSessionTurns[turnId];
  return { turnActivityBySession: { ...turns, [sessionId]: nextSessionTurns } };
}

export function latestVisibleTurnId(
  sessionId: string,
  messages: AssistantMessage[],
  pendingMessages: PendingAssistantMessage[],
): string | null {
  const pendingForSession = pendingMessages.filter((message) => message.sessionId === sessionId);
  const all: Array<AssistantMessage | PendingAssistantMessage> = [...messages, ...pendingForSession];
  for (let i = all.length - 1; i >= 0; i -= 1) {
    const id = turnIdFromMessage(all[i]);
    if (id) return id;
  }
  return null;
}

/** 解析某会话实时事件应归属的 turnId：活跃 turn → 最近可见用户回合 → fallback。 */
export function resolveTurnId(
  state: {
    activeTurnIdBySession: Record<string, string>;
    messages: AssistantMessage[];
    pendingOptimisticMessages: PendingAssistantMessage[];
  },
  sessionId: string,
  fallback: string,
): string {
  return (
    state.activeTurnIdBySession[sessionId]
    || latestVisibleTurnId(sessionId, state.messages, state.pendingOptimisticMessages)
    || fallback
  );
}

/** 把一条实时事件并入当前回合：登记活跃 turn + 用 updater 单次改写该回合（避免 getTurn+updateTurn 双查）。 */
export function commitLiveTurn(
  state: {
    activeTurnIdBySession: Record<string, string>;
    turnActivityBySession: Record<string, Record<string, AssistantTurnActivity>>;
  },
  sessionId: string,
  turnId: string,
  updater: (turn: AssistantTurnActivity) => AssistantTurnActivity,
): {
  activeTurnIdBySession: Record<string, string>;
  turnActivityBySession: Record<string, Record<string, AssistantTurnActivity>>;
} {
  return {
    activeTurnIdBySession: { ...state.activeTurnIdBySession, [sessionId]: turnId },
    ...updateTurn(state, sessionId, turnId, updater),
  };
}

export function syncTurnsFromMessages(
  messages: AssistantMessage[],
  existing: Record<string, AssistantTurnActivity> = {},
): Record<string, AssistantTurnActivity> {
  const next: Record<string, AssistantTurnActivity> = { ...existing };
  let currentTurnId: string | null = null;
  for (const message of messages) {
    if (message.role !== "user") continue;
    const turnId = turnIdFromSequence(message.sequence);
    if (currentTurnId && next[currentTurnId]) {
      next[currentTurnId] = {
        ...next[currentTurnId],
        beforeSequence: message.sequence,
      };
    }
    next[turnId] = {
      ...emptyTurn(turnId),
      ...next[turnId],
      turnId,
      fromSequence: message.sequence,
    };
    currentTurnId = turnId;
  }
  return next;
}

export function migrateTurn(
  turns: Record<string, AssistantTurnActivity>,
  oldTurnId: string | null | undefined,
  newTurnId: string,
  fromSequence?: number,
): Record<string, AssistantTurnActivity> {
  const next = { ...turns };
  const existing = oldTurnId ? next[oldTurnId] : undefined;
  const target = next[newTurnId] ?? emptyTurn(newTurnId);
  next[newTurnId] = {
    ...target,
    ...existing,
    turnId: newTurnId,
    // 调用方传 message.sequence；syncTurnsFromMessages 已把同值写到 target；乐观 turn 无 fromSequence
    fromSequence: fromSequence ?? target.fromSequence,
  };
  if (oldTurnId && oldTurnId !== newTurnId) {
    delete next[oldTurnId];
  }
  return next;
}

export function upsertSubagent(subagents: Subagent[], updated: Subagent): Subagent[] {
  return [...subagents.filter((item) => item.subagentId !== updated.subagentId), updated];
}

/**
 * 把一条活动步骤并入按 seq 升序的步骤列表并限高。
 * 后端 seq 单调递增，常态是顺序追加（O(1)）；仅在乱序/重发（seq<=末尾）时才去重+排序。
 */
export function appendActivityStep(
  steps: ActivityStep[],
  step: ActivityStep,
  max: number,
): ActivityStep[] {
  const last = steps[steps.length - 1];
  const next =
    !last || step.seq > last.seq
      ? [...steps, step]
      : [...steps.filter((s) => s.seq !== step.seq), step].sort((a, b) => a.seq - b.seq);
  return next.length > max ? next.slice(-max) : next;
}

export function removePendingOptimisticMessage(
  messages: PendingAssistantMessage[],
  optimisticId: string | null,
): PendingAssistantMessage[] {
  if (optimisticId === null) {
    return messages;
  }
  return messages.filter((message) => message.optimisticId !== optimisticId);
}

export function isPendingEcho(
  pending: PendingAssistantMessage,
  sessionId: string,
  message: AssistantMessage,
): boolean {
  return (
    pending.sessionId === sessionId
    && message.role === "user"
    && pending.content.trim() === message.content.trim()
  );
}

type OptimisticTurnState = {
  pendingOptimisticMessages: PendingAssistantMessage[];
  activeTurnIdBySession: Record<string, string>;
  turnActivityBySession: Record<string, Record<string, AssistantTurnActivity>>;
};

/**
 * 乐观发送的共享起手式：建一条乐观 user 消息、登记其为活跃 turn 并开空时间线。
 * 三个发送入口（sendDraft / continueSubagent / 排队自动派发）共用，避免重复 choreography。
 * 返回 optimisticId 与一份待并入 set 的状态 patch；各入口再叠加自己的 draft/progress/排队语义。
 */
export function beginOptimisticTurn(
  state: OptimisticTurnState,
  sessionId: string,
  content: string,
): { optimisticId: string; patch: OptimisticTurnState } {
  const optimisticId = nextOptimisticId();
  const message: PendingAssistantMessage = {
    optimisticId,
    sessionId,
    role: "user",
    content,
    createdAt: new Date().toISOString(),
    rendering: "plain_text",
  };
  return {
    optimisticId,
    patch: {
      pendingOptimisticMessages: [...state.pendingOptimisticMessages, message],
      activeTurnIdBySession: { ...state.activeTurnIdBySession, [sessionId]: optimisticId },
      ...updateTurn(state, sessionId, optimisticId, () => emptyTurn(optimisticId)),
    },
  };
}

/** 乐观发送失败回滚：移除乐观消息并清掉其 turn（draft / 排队等入口语义由调用方另行叠加）。 */
export function rollbackOptimisticTurn(
  state: {
    pendingOptimisticMessages: PendingAssistantMessage[];
    turnActivityBySession: Record<string, Record<string, AssistantTurnActivity>>;
  },
  sessionId: string,
  optimisticId: string,
): {
  pendingOptimisticMessages: PendingAssistantMessage[];
  turnActivityBySession: Record<string, Record<string, AssistantTurnActivity>>;
} {
  return {
    pendingOptimisticMessages: removePendingOptimisticMessage(state.pendingOptimisticMessages, optimisticId),
    ...removeTurn(state, sessionId, optimisticId),
  };
}

export function reconcilePendingMessages(
  pendingMessages: PendingAssistantMessage[],
  sessionId: string,
  authoritativeMessages: AssistantMessage[],
): PendingAssistantMessage[] {
  const removedIndices = new Set<number>();
  for (const message of authoritativeMessages) {
    const idx = pendingMessages.findIndex(
      (p, i) => !removedIndices.has(i) && isPendingEcho(p, sessionId, message),
    );
    if (idx !== -1) removedIndices.add(idx);
  }
  return pendingMessages.filter((_, i) => !removedIndices.has(i));
}
