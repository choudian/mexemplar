import { sendAssistantMessage } from "../api/assistant";
import type { AssistantConfirmation, AssistantMessage, ClarificationRequest } from "../api/assistant";
import type { UiEvent } from "../api/client";
import { useAssistantTaskStore } from "./assistantTaskStore";
import type { AssistantState } from "./assistantStore";
import type { ActivityStep, AssistantProgress, Subagent } from "./assistantTypes";
import {
  appendActivityStep,
  beginOptimisticTurn,
  commitLiveTurn,
  isPendingEcho,
  migrateTurn,
  reconcilePendingMessages,
  resolveTurnId,
  rollbackOptimisticTurn,
  syncTurnsFromMessages,
  turnIdFromSequence,
  uniqueMessages,
  upsertSubagent,
} from "./assistantHelpers";

type SetAssistantState = (partial: Partial<AssistantState>) => void;
type GetAssistantState = () => AssistantState;

export interface ApplyAssistantEventContext {
  set: SetAssistantState;
  get: GetAssistantState;
  clearClarificationForSession: (
    set: SetAssistantState,
    get: GetAssistantState,
    sessionId: string,
  ) => void;
}

const MAX_LIVE_ACTIVITY_STEPS = 300;

function applyMessageEvent(event: UiEvent, set: SetAssistantState, get: GetAssistantState): boolean {
  if (event.type !== "assistant.message") return false;
  const message: AssistantMessage = event.payload;
  const eventSessionId = event.scope.sessionId ?? "";
  if (!eventSessionId) return true;
  const isActiveSession = eventSessionId === get().activeSessionId;
  const pendingEcho = get().pendingOptimisticMessages.find((pending) =>
    isPendingEcho(pending, eventSessionId, message),
  );
  const mergedMessages = isActiveSession
    ? uniqueMessages([...get().messages, message])
    : [message];
  const existingTurns = get().turnActivityBySession[eventSessionId] ?? {};
  let syncedTurns = syncTurnsFromMessages(mergedMessages, existingTurns);
  let activeTurnIdBySession = get().activeTurnIdBySession;
  if (message.role === "user") {
    const newTurnId = turnIdFromSequence(message.sequence);
    const currentActiveTurnId = get().activeTurnIdBySession[eventSessionId];
    const oldTurnId = pendingEcho?.optimisticId
      || (currentActiveTurnId?.startsWith("optimistic_") ? currentActiveTurnId : null);
    syncedTurns = migrateTurn(syncedTurns, oldTurnId, newTurnId, message.sequence);
    activeTurnIdBySession = { ...activeTurnIdBySession, [eventSessionId]: newTurnId };
  }
  const patch = {
    pendingOptimisticMessages: reconcilePendingMessages(
      get().pendingOptimisticMessages,
      eventSessionId,
      [message],
    ),
    turnActivityBySession: {
      ...get().turnActivityBySession,
      [eventSessionId]: syncedTurns,
    },
    activeTurnIdBySession,
  };
  set(isActiveSession ? { ...patch, messages: mergedMessages } : patch);
  return true;
}

function applyProgressEvent(event: UiEvent, set: SetAssistantState, get: GetAssistantState): boolean {
  if (event.type !== "assistant.progress") return false;
  const payload = event.payload;
  const status = (typeof payload["status"] === "string" ? payload["status"] : "running") as AssistantProgress["status"];
  const sessionId = event.scope.sessionId ?? get().activeSessionId ?? "";
  if (!sessionId) return true;
  const isActiveSession = sessionId === get().activeSessionId;
  const nextProgress: AssistantProgress = {
    status,
    headline: typeof payload["headline"] === "string" ? payload["headline"] : "",
    runId: typeof payload["runId"] === "string" ? payload["runId"] : undefined,
  };
  const nextStoppingBySession = {
    ...get().stoppingBySession,
    [sessionId]: status === "running" ? Boolean(get().stoppingBySession[sessionId]) : false,
  };
  const nextRetryingFailures = { ...get().retryingFailureBySession };
  if (status !== "running") {
    delete nextRetryingFailures[sessionId];
  }
  set({
    progress: isActiveSession ? nextProgress : get().progress,
    progressBySession: { ...get().progressBySession, [sessionId]: nextProgress },
    // 离开 running（含 cancelled/succeeded/failed/waiting）即清"停止中"过渡态、解锁输入；
    // 已产内容由先到的 assistant.message 事件追加保留（FR-008）。
    stopping: isActiveSession
      ? (status === "running" ? Boolean(nextStoppingBySession[sessionId]) : false)
      : get().stopping,
    stoppingBySession: nextStoppingBySession,
    retryingFailureBySession: nextRetryingFailures,
  });
  if (status !== "running") {
    flushQueuedMessageAfterRun(sessionId, status, set, get);
  }
  return true;
}

function flushQueuedMessageAfterRun(
  sessionId: string,
  status: AssistantProgress["status"],
  set: SetAssistantState,
  get: GetAssistantState,
): void {
  const queued = get().queuedMessageBySession[sessionId];
  if (!queued) return;
  // 全异步 busy：回合结束但当前图仍有在跑/待派发节点时，排队消息保持排队不自动外发
  // （回流回合跑完、任务终态后自然放行）。尽力判——多图场景漏判时由后端 busy 拒绝兜底回排队。
  const graph = useAssistantTaskStore.getState().currentGraph;
  const graphBusy =
    graph?.tasks.some(
      (task) => task.status === "running" || task.status === "pending_dispatch",
    ) ?? false;
  const map = { ...get().queuedMessageBySession };
  delete map[sessionId];
  const autoSend =
    queued.state === "queued" &&
    (status === "succeeded" || status === "waiting_for_user") &&
    !graphBusy;
  if (!autoSend) {
    set({
      queuedMessageBySession: map,
      draft: get().activeSessionId === sessionId ? queued.text : get().draft,
      draftBySession: { ...get().draftBySession, [sessionId]: queued.text },
    });
    return;
  }

  const autoRunningProgress: AssistantProgress = { status: "running", headline: "正在处理" };
  const begun = beginOptimisticTurn(get(), sessionId, queued.text);
  const queuedOptimisticId = begun.optimisticId;
  const requeueText = queued.text;
  const requeueQueued = () => ({
    ...get().queuedMessageBySession,
    [sessionId]: { text: requeueText, state: "queued" as const },
  });
  set({
    queuedMessageBySession: map,
    progress: get().activeSessionId === sessionId ? autoRunningProgress : get().progress,
    progressBySession: { ...get().progressBySession, [sessionId]: autoRunningProgress },
    ...begun.patch,
  });
  void sendAssistantMessage(sessionId, queued.text)
    .then((result) => {
      if (!result.accepted) {
        const busyProgress: AssistantProgress = { status: "running", headline: "上一条消息仍在处理中" };
        set({
          ...rollbackOptimisticTurn(get(), sessionId, queuedOptimisticId),
          queuedMessageBySession: requeueQueued(),
          progress: get().activeSessionId === sessionId ? busyProgress : get().progress,
          progressBySession: { ...get().progressBySession, [sessionId]: busyProgress },
        });
      } else {
        set({
          progress: get().activeSessionId === sessionId ? autoRunningProgress : get().progress,
          progressBySession: { ...get().progressBySession, [sessionId]: autoRunningProgress },
        });
      }
    })
    .catch(() => {
      set({
        ...rollbackOptimisticTurn(get(), sessionId, queuedOptimisticId),
        queuedMessageBySession: requeueQueued(),
      });
    });
}

function applyActivityEvent(event: UiEvent, set: SetAssistantState, get: GetAssistantState): boolean {
  if (event.type !== "assistant.activity") return false;
  const sessionId = event.scope.sessionId ?? "";
  if (!sessionId) return true;
  const turnId = resolveTurnId(get(), sessionId, "live");
  const payload = event.payload as Record<string, unknown>;
  const step: ActivityStep = {
    seq: typeof payload["seq"] === "number" ? payload["seq"] : 0,
    kind: (typeof payload["kind"] === "string" ? payload["kind"] : "reasoning") as ActivityStep["kind"],
    toolName: typeof payload["toolName"] === "string" ? payload["toolName"] : undefined,
    text: typeof payload["text"] === "string" ? payload["text"] : "",
    subagentId: typeof payload["subagentId"] === "string" ? payload["subagentId"] : null,
    redacted: payload["redacted"] === true,
  };
  set(
    commitLiveTurn(get(), sessionId, turnId, (turn) => ({
      ...turn,
      steps: appendActivityStep(turn.steps, step, MAX_LIVE_ACTIVITY_STEPS),
    })),
  );
  return true;
}

function applySubagentEvent(event: UiEvent, set: SetAssistantState, get: GetAssistantState): boolean {
  if (event.type !== "assistant.subagent") return false;
  const sessionId = event.scope.sessionId ?? "";
  if (!sessionId) return true;
  const turnId = resolveTurnId(get(), sessionId, "live");
  const payload = event.payload as Record<string, unknown>;
  const subagentId = typeof payload["subagentId"] === "string" ? payload["subagentId"] : "";
  if (!subagentId) return true;
  set(
    commitLiveTurn(get(), sessionId, turnId, (turn) => {
      const prev = turn.subagents.find((item) => item.subagentId === subagentId);
      const lastStep = turn.steps[turn.steps.length - 1];
      const anchorSeq = prev?.anchorSeq ?? lastStep?.seq;
      const updated: Subagent = {
        subagentId,
        label: typeof payload["label"] === "string" ? payload["label"] : prev?.label ?? "子助手",
        task: typeof payload["task"] === "string" ? payload["task"] : prev?.task ?? "",
        status: (typeof payload["status"] === "string" ? payload["status"] : prev?.status ?? "running") as Subagent["status"],
        lastOutput: typeof payload["lastOutput"] === "string" ? payload["lastOutput"] : prev?.lastOutput,
        anchorSeq,
      };
      return { ...turn, subagents: upsertSubagent(turn.subagents, updated) };
    }),
  );
  return true;
}

function applyResyncEvent(event: UiEvent, get: GetAssistantState): boolean {
  if (event.type !== "backend.resync_required") return false;
  const sessionId = get().activeSessionId;
  if (sessionId) {
    void get().selectSession(sessionId);
    void get().refreshSubagents(sessionId);
    void get().refreshActivityTranscript(sessionId);
    void get().refreshPendingClarification(sessionId);
  }
  return true;
}

function applyErrorEvent(event: UiEvent, set: SetAssistantState, get: GetAssistantState): boolean {
  if (event.type !== "assistant.error") return false;
  const payload = event.payload;
  const message = typeof payload["message"] === "string" ? payload["message"] : "Assistant 处理失败";
  const sessionId = event.scope.sessionId ?? "";
  const failedProgress: AssistantProgress = { status: "failed", headline: message };
  set({
    progress: sessionId && sessionId !== get().activeSessionId ? get().progress : failedProgress,
    progressBySession: sessionId
      ? { ...get().progressBySession, [sessionId]: failedProgress }
      : get().progressBySession,
    lastError: sessionId && sessionId !== get().activeSessionId ? get().lastError : message,
  });
  return true;
}

function applyConfirmationEvent(event: UiEvent, set: SetAssistantState, get: GetAssistantState): boolean {
  if (event.type !== "assistant.confirmation") return false;
  const confirmation: AssistantConfirmation = event.payload;
  if (confirmation.sessionId && confirmation.sessionId !== get().activeSessionId) {
    if (
      confirmation.actionType !== "skill.edit_protected"
      && confirmation.actionType !== "skill.soft_delete"
    ) {
      return true;
    }
  }
  set({
    confirmations: [
      ...get().confirmations.filter((item) => item.requestId !== confirmation.requestId),
      confirmation,
    ],
  });
  return true;
}

function applyClarificationRequestedEvent(event: UiEvent, set: SetAssistantState, get: GetAssistantState): boolean {
  if (event.type !== "assistant.clarification_requested") return false;
  const clarification = event.payload as unknown as ClarificationRequest;
  const sid = clarification.sessionId;
  if (!sid) return true;
  set({
    pendingClarificationBySession: {
      ...get().pendingClarificationBySession,
      [sid]: clarification,
    },
  });
  return true;
}

function applyClarificationResolvedEvent(event: UiEvent, context: ApplyAssistantEventContext): boolean {
  if (event.type !== "assistant.clarification_resolved") return false;
  const { set, get, clearClarificationForSession } = context;
  const sid = String(event.payload["sessionId"] ?? event.scope.sessionId ?? "");
  const requestId = String(event.payload["requestId"] ?? "");
  if (!sid) return true;
  const current = get().pendingClarificationBySession[sid];
  if (!current || (requestId && current.requestId !== requestId)) {
    return true;
  }
  clearClarificationForSession(set, get, sid);
  return true;
}

export function applyAssistantEvent(event: UiEvent, context: ApplyAssistantEventContext): void {
  const { set, get } = context;
  if (applyMessageEvent(event, set, get)) return;
  if (applyProgressEvent(event, set, get)) return;
  if (applyActivityEvent(event, set, get)) return;
  if (applySubagentEvent(event, set, get)) return;
  if (applyResyncEvent(event, get)) return;
  if (applyErrorEvent(event, set, get)) return;
  if (applyConfirmationEvent(event, set, get)) return;
  if (applyClarificationRequestedEvent(event, set, get)) return;
  if (applyClarificationResolvedEvent(event, context)) return;
}
