/**
 * ⑦ 执行体抽屉：打开期间自动跟进最新过程。
 *
 * 用户诉求：点进去看 msg 时要一直刷新最新的；不点进去就不用管。
 * 因此轮询只在抽屉打开且执行体仍在跑时进行，终态停、关闭停。
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ExecutorDrawer from "../../src/screens/assistant/ExecutorDrawer";
import TaskGraphDialog from "../../src/screens/assistant/TaskGraphDialog";

function detailWith(status: string, steps: { seq: number; kind: string; text: string }[]) {
  return {
    summary: {
      subagentId: "sub_1",
      label: "通用子代理",
      task: "查榜单",
      status,
      lastOutput: null,
      turnStartSequence: null,
      taskId: "tsk_1",
    },
    steps,
    children: [],
  };
}

function jsonResponse(data: unknown) {
  return { ok: true, status: 200, json: async () => data, text: async () => JSON.stringify(data) };
}

describe("ExecutorDrawer 自动刷新", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("执行体还在跑时，抽屉打开期间自动拉取最新过程", async () => {
    let call = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("executor-detail")) {
          call += 1;
          return jsonResponse(
            detailWith("running", [
              { seq: 1, kind: "tool_call", text: "第一步" },
              ...(call > 1 ? [{ seq: 2, kind: "tool_call", text: "第二步" }] : []),
            ]),
          );
        }
        return jsonResponse({ items: [] });
      }),
    );
    render(
      <ExecutorDrawer
        sessionId="s1"
        initialExecutorSessionId="sub_1"
        initialLabel="通用子代理"
        onClose={() => {}}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("第一步")).toBeInTheDocument();
    });
    expect(screen.queryByText("第二步")).not.toBeInTheDocument();

    // 到点自动刷新，新步骤出现，且旧内容不被清空（不闪加载态）
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => {
      expect(screen.getByText("第二步")).toBeInTheDocument();
    });
    expect(screen.getByText("第一步")).toBeInTheDocument();
  });

  it("执行体已终态时不再轮询", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("executor-detail")) {
        return jsonResponse(detailWith("done", [{ seq: 1, kind: "tool_call", text: "做完了" }]));
      }
      return jsonResponse({ items: [] });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <ExecutorDrawer
        sessionId="s1"
        initialExecutorSessionId="sub_1"
        initialLabel="通用子代理"
        onClose={() => {}}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("做完了")).toBeInTheDocument();
    });
    const detailCalls = () =>
      fetchMock.mock.calls.filter((c) => String(c[0]).includes("executor-detail")).length;
    const before = detailCalls();
    await vi.advanceTimersByTimeAsync(10000);
    expect(detailCalls()).toBe(before);
  });
});

describe("TaskGraphDialog 侧栏自动刷新", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("侧栏停在执行体上时，同样自动跟进最新过程", async () => {
    let call = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("executor-detail")) {
          call += 1;
          return jsonResponse(
            detailWith("running", [
              { seq: 1, kind: "tool_call", text: "弹窗第一步" },
              ...(call > 1 ? [{ seq: 2, kind: "tool_call", text: "弹窗第二步" }] : []),
            ]),
          );
        }
        if (url.includes("/todos")) return jsonResponse({ items: [] });
        // 图快照：两节点一条边，打开自动定位到在跑的那个
        const node = (id: string, title: string, phase: string, exec?: string) => ({
          taskId: id, graphId: "g1", parentTaskId: null, title,
          descriptionPreview: "", status: phase === "done" ? "done" : "running",
          displayPhase: phase, requiresReview: false, requiresConfirmation: false,
          safeExplanation: "",
          executorSessionId: exec ?? null,
          assignee: exec ? { type: "ephemeral_subagent", id: "e1", label: "通用子代理" } : null,
        });
        return jsonResponse({
          graphId: "g1", sessionId: "s1", version: 1,
          tasks: [node("t0", "准备", "done"), node("t1", "抓数据", "running", "sub_1")],
          edges: [{ sourceTaskId: "t0", targetTaskId: "t1", type: "dependency" }],
          adjudications: [],
        });
      }),
    );
    render(
      <TaskGraphDialog sessionId="s1" graphId="g1" taskTitle="季度报告" onClose={() => {}} />,
    );
    // 节点详情里点执行体卡片进入执行体视图（.me-agent 是卡片本身）
    await waitFor(() => {
      expect(document.querySelector("button.me-agent")).toBeTruthy();
    });
    fireEvent.click(document.querySelector("button.me-agent") as HTMLElement);
    await waitFor(() => {
      expect(screen.getByText("弹窗第一步")).toBeInTheDocument();
    });
    expect(screen.queryByText("弹窗第二步")).not.toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => {
      expect(screen.getByText("弹窗第二步")).toBeInTheDocument();
    });
  });
});
