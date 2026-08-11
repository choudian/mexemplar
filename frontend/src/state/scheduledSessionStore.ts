import { create } from "zustand";

import { listAssistantMessages, sendAssistantMessage } from "../api/assistant";
import type { AssistantMessage } from "../api/assistant";
import { takeoverScheduledRun } from "../api/scheduledTasks";
import type { ScheduledTaskItem, ScheduledTaskRunItem } from "../api/scheduledTasks";
import type { UiEvent } from "../api/client";
import { toErrorMessage } from "./helpers";

/**
 * 调度中心「查看这一轮」弹窗的会话状态。
 *
 * 刻意与 ``assistantStore`` 完全独立，不共用 activeSessionId：
 *
 * - ``assistantStore.selectSession`` 会 ``sealPreviousSegment`` 封存上一个会话的大脑
 *   记忆边界。若弹窗复用它，用户在主助理聊到一半点开这个弹窗，主会话的记忆分段就被
 *   误封了——记忆边界该由用户真的换话题决定，不该被"顺手看一眼定时任务"触发。
 * - 主屏与弹窗同时活着，共用单值 ``messages`` 会互相覆盖。
 *
 * 代价是本 store 自己消费事件。作用域只有"看这一轮 + 接着说两句"，所以只处理消息与
 * 运行状态；任务图、执行体、失败恢复、澄清卡都不在这里，需要时由弹窗跳主助理屏。
 */

const MESSAGE_PAGE_SIZE = 50;

/** 调度投递给主助理的那条消息前缀，见 session_launcher.build_scheduled_execution_message。 */
const SCHEDULED_TRIGGER_PREFIX = "[系统调度触发";

/**
 * 这条消息是不是调度系统自己投的（而不是用户说的话）。
 *
 * 用户从没打过这段字，把它渲染成"你"的气泡是在说谎，而且会把内部 prompt 脚手架
 * 直接摊给用户看。前缀变了也只是退回普通气泡，不会报错。
 */
export function isScheduledTriggerMessage(message: AssistantMessage): boolean {
  return message.role === "user" && message.content.startsWith(SCHEDULED_TRIGGER_PREFIX);
}

function mergeMessage(messages: AssistantMessage[], next: AssistantMessage): AssistantMessage[] {
  const idx = messages.findIndex((item) => item.sequence === next.sequence);
  if (idx >= 0) {
    const copy = messages.slice();
    copy[idx] = next;
    return copy;
  }
  return [...messages, next].sort((a, b) => a.sequence - b.sequence);
}

export type ScheduledSessionState = {
  open: boolean;
  task: ScheduledTaskItem | null;
  run: ScheduledTaskRunItem | null;
  sessionId: string | null;
  messages: AssistantMessage[];
  loading: boolean;
  sending: boolean;
  /** 助理是否正在处理本会话（驱动"正在处理"提示与输入禁用）。 */
  running: boolean;
  draft: string;
  error: string | null;
  openRun: (task: ScheduledTaskItem, run: ScheduledTaskRunItem) => Promise<void>;
  close: () => void;
  setDraft: (draft: string) => void;
  send: () => Promise<void>;
  applyEvent: (event: UiEvent) => void;
};

export const useScheduledSessionStore = create<ScheduledSessionState>((set, get) => ({
  open: false,
  task: null,
  run: null,
  sessionId: null,
  messages: [],
  loading: false,
  sending: false,
  running: false,
  draft: "",
  error: null,

  openRun: async (task, run) => {
    if (!run.sessionId) return;
    const sessionId = run.sessionId;
    set({
      open: true,
      task,
      run,
      sessionId,
      messages: [],
      // 打开就是一次新的阅读，草稿不跨轮次残留。
      draft: "",
      error: null,
      loading: true,
      running: run.status === "running",
    });
    try {
      const page = await listAssistantMessages(sessionId, { limit: MESSAGE_PAGE_SIZE });
      // 期间用户可能已经关了弹窗或换了一轮，迟到的响应不许覆盖当前内容。
      if (get().sessionId !== sessionId) return;
      // 载荷不合预期时退化成空列表：这一屏可以没内容，但不能把 undefined 灌进渲染。
      set({ messages: Array.isArray(page?.items) ? page.items : [] });
    } catch (error) {
      if (get().sessionId !== sessionId) return;
      set({ error: toErrorMessage(error, "这一轮的对话记录加载失败。") });
    } finally {
      if (get().sessionId === sessionId) set({ loading: false });
    }
  },

  close: () =>
    set({
      open: false,
      task: null,
      run: null,
      sessionId: null,
      messages: [],
      draft: "",
      error: null,
      loading: false,
      sending: false,
      running: false,
    }),

  setDraft: (draft) => set({ draft }),

  send: async () => {
    const { sessionId, draft, sending, run } = get();
    const content = draft.trim();
    if (!sessionId || !content || sending) return;
    set({ sending: true, error: null });
    try {
      // waiting_user 的 run 还占着该任务的 active 槽位：不先接管就发消息，这一轮
      // 永远停在"等你回话"，下一次到点会被判成上轮没跑完而静默跳过。
      if (run && run.status === "waiting_user") {
        await takeoverScheduledRun(run.scheduledTaskId, run.runId);
        if (get().sessionId !== sessionId) return;
        set({ run: { ...run, status: "running" } as ScheduledTaskRunItem });
      }
      await sendAssistantMessage(sessionId, content);
      if (get().sessionId !== sessionId) return;
      // 消息本体由 assistant.message 事件回填，这里只清草稿并进入运行态。
      set({ draft: "", running: true });
    } catch (error) {
      if (get().sessionId !== sessionId) return;
      set({ error: toErrorMessage(error, "没发出去，待会儿再试一次。") });
    } finally {
      if (get().sessionId === sessionId) set({ sending: false });
    }
  },

  applyEvent: (event) => {
    const sessionId = get().sessionId;
    if (!get().open || !sessionId) return;
    if (event.scope.sessionId !== sessionId) return;

    if (event.type === "assistant.message") {
      set({ messages: mergeMessage(get().messages, event.payload as AssistantMessage) });
      return;
    }
    if (event.type === "assistant.progress") {
      const status = String((event.payload as { status?: unknown }).status ?? "");
      set({ running: status === "running" });
    }
  },
}));
