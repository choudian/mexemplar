/**
 * 会话打开时的过程恢复：主助理自己的步骤（建图、调工具那些 msg）只活在
 * 事件流里，应用一重启内存就归零。打开会话必须把它们补拉回来，否则卡片
 * 里只剩执行体，主助理做过什么全没了。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AssistantActivityStep } from "../../src/api/assistant";

const listAssistantMessages = vi.fn();
const listSubagents = vi.fn();
const getSubagentTranscript = vi.fn();
const getPendingClarification = vi.fn();

vi.mock("../../src/api/assistant", () => ({
  listAssistantMessages: (...a: unknown[]) => listAssistantMessages(...a),
  listSubagents: (...a: unknown[]) => listSubagents(...a),
  getSubagentTranscript: (...a: unknown[]) => getSubagentTranscript(...a),
  getPendingClarification: (...a: unknown[]) => getPendingClarification(...a),
  createAssistantSession: vi.fn(),
  decideAssistantConfirmation: vi.fn(),
  deleteAssistantSession: vi.fn(),
  listAssistantSessions: vi.fn(),
  renameAssistantSession: vi.fn(),
  retryAssistantMessage: vi.fn(),
  sendAssistantMessage: vi.fn(),
  setAssistantAutoApprove: vi.fn(),
  stopAssistantRun: vi.fn(),
  submitClarificationDecision: vi.fn(),
  triggerAssistantSegmentBoundary: vi.fn(),
  triggerAssistantSegmentIdle: vi.fn(),
}));

import { useAssistantStore } from "../../src/state/assistantStore";

const step = (seq: number, text: string): AssistantActivityStep => ({
  kind: "tool_call",
  toolName: "create_task_graph",
  text,
  seq,
});

/** 两轮对话：第 1 轮从 seq 1 起，第 2 轮从 seq 5 起。 */
const messagePage = {
  items: [
    { sequence: 1, role: "user", content: "第一轮请求", rendering: "text" },
    { sequence: 2, role: "assistant", content: "好的", rendering: "safe_markdown" },
    { sequence: 5, role: "user", content: "第二轮请求", rendering: "text" },
    { sequence: 6, role: "assistant", content: "在做了", rendering: "safe_markdown" },
  ],
  hasMoreBefore: false,
  nextBeforeSequence: null,
};

describe("打开会话时恢复主助理过程", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAssistantStore.setState({ turnActivityBySession: {}, activeSessionId: null });
    listAssistantMessages.mockResolvedValue(messagePage);
    listSubagents.mockResolvedValue([]);
    getPendingClarification.mockResolvedValue(null);
    getSubagentTranscript.mockResolvedValue({ steps: [], compressed: false });
  });

  it("每一轮的步骤都补拉回来，不只是最后一轮", async () => {
    getSubagentTranscript.mockImplementation((_s: string, _sub: unknown, opts: { afterSequence?: number }) =>
      Promise.resolve({
        steps: opts.afterSequence === 1 ? [step(2, "第一轮建了图")] : [step(6, "第二轮建了图")],
        compressed: false,
      }),
    );

    await useAssistantStore.getState().selectSession("s1");
    await vi.waitFor(() => {
      const turns = useAssistantStore.getState().turnActivityBySession["s1"];
      expect(turns?.["seq_1"]?.steps).toHaveLength(1);
      expect(turns?.["seq_5"]?.steps).toHaveLength(1);
    });

    const turns = useAssistantStore.getState().turnActivityBySession["s1"];
    expect(turns["seq_1"].steps[0].text).toBe("第一轮建了图");
    expect(turns["seq_5"].steps[0].text).toBe("第二轮建了图");
  });

  it("重启后恢复的执行体没有排序锚点（锚点只存在于实时事件流）", async () => {
    listSubagents.mockResolvedValue([
      {
        subagentId: "sub_1",
        label: "子助手",
        task: "分析 src/data/",
        status: "done",
        turnStartSequence: 1,
        taskId: "tsk_1",
      },
    ]);

    await useAssistantStore.getState().selectSession("s1");
    await vi.waitFor(() => {
      expect(useAssistantStore.getState().turnActivityBySession["s1"]?.["seq_1"]?.subagents).toHaveLength(1);
    });

    // anchorSeq 由 assistant.subagent 实时事件按当时最后一个步骤号记录，
    // 权威列表里没有这个信息——所以重启后必须由别处兜底，否则执行体
    // 会全部落到时间流末尾，不再按发生顺序穿插在主助理的动作之间。
    const restored = useAssistantStore.getState().turnActivityBySession["s1"]["seq_1"].subagents[0];
    expect(restored.anchorSeq).toBeUndefined();
    expect(restored.taskId).toBe("tsk_1");
  });

  it("过程恢复不会抹掉同时恢复的执行体卡片", async () => {
    listSubagents.mockResolvedValue([
      {
        subagentId: "sub_1",
        label: "子助手",
        task: "分析 src/data/",
        status: "done",
        turnStartSequence: 1,
        taskId: "tsk_1",
      },
    ]);
    // transcript 比 subagents 晚回来：它若拿请求发出前的旧快照展开，
    // 就会把已经写进同一个 turn 的执行体覆盖掉。
    let releaseTranscript: (() => void) | null = null;
    const gate = new Promise<void>((resolve) => {
      releaseTranscript = resolve;
    });
    getSubagentTranscript.mockImplementation(async () => {
      await gate;
      return { steps: [step(2, "主助理建了图")], compressed: false };
    });

    await useAssistantStore.getState().selectSession("s1");
    await vi.waitFor(() => {
      expect(useAssistantStore.getState().turnActivityBySession["s1"]?.["seq_1"]?.subagents).toHaveLength(1);
    });

    releaseTranscript!();
    await vi.waitFor(() => {
      expect(useAssistantStore.getState().turnActivityBySession["s1"]?.["seq_1"]?.steps).toHaveLength(1);
    });

    const turn = useAssistantStore.getState().turnActivityBySession["s1"]["seq_1"];
    expect(turn.steps[0].text).toBe("主助理建了图");
    expect(turn.subagents.map((s) => s.subagentId)).toEqual(["sub_1"]);
  });
});
