// @vitest-environment jsdom
/**
 * ExecutorDrawer 渲染回归：数据到步骤行的渲染链路。
 *
 * 注意边界：jsdom 不做布局计算，这里测不出"步骤被超高标题挤出视口"那类问题——
 * 那条回归在 tests/e2e/executor-drawer.spec.ts 里用真实浏览器量可见高度。
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getExecutorDetailMock = vi.fn();

vi.mock("../../src/api/assistant", () => ({
  getExecutorDetail: (...args: unknown[]) => getExecutorDetailMock(...args),
}));

vi.mock("../../src/api/assistantTasks", () => ({
  getAssistantTaskTodos: vi.fn().mockResolvedValue({ items: [] }),
}));

import ExecutorDrawer from "../../src/screens/assistant/ExecutorDrawer";
import type { ExecutorDetail } from "../../src/api/assistant";

const detail: ExecutorDetail = {
  summary: {
    subagentId: "sess_exec_1",
    label: "子助手",
    task: "任务初探",
    status: "done",
    lastOutput: null,
    turnStartSequence: null,
  },
  steps: [
    { kind: "reasoning", seq: 1, text: "先看目录结构", toolName: null, redacted: false },
    { kind: "tool_call", seq: 2, text: '{"path":"src"}', toolName: "list_dir", redacted: false },
    { kind: "tool_result", seq: 3, text: "main.py", toolName: "list_dir", redacted: false },
  ],
  children: [],
};

describe("ExecutorDrawer 渲染", () => {
  beforeEach(() => {
    getExecutorDetailMock.mockReset();
  });
  afterEach(cleanup);

  it("加载成功后渲染步骤行（非空白）", async () => {
    getExecutorDetailMock.mockResolvedValue(detail);
    const { container } = render(
      <ExecutorDrawer
        sessionId="sess_main"
        initialExecutorSessionId="sess_exec_1"
        initialLabel="子助手"
        onClose={() => {}}
      />,
    );
    // 过渡态先出现，随后被真实步骤替换
    await waitFor(() => {
      expect(screen.getByText("先看目录结构")).toBeTruthy();
    });
    expect(getExecutorDetailMock).toHaveBeenCalledWith("sess_main", "sess_exec_1");
    // 三条步骤都在（非"还没有步骤。"空态）。工具步骤的 JSON 会被格式化并折叠进
    // <details>，所以按工具名和行数断言，不按原始字符串。
    expect(container.querySelectorAll("li.assistant-step")).toHaveLength(3);
    expect(screen.getAllByText("list_dir")).toHaveLength(2);
    expect(screen.queryByText("还没有步骤。")).toBeNull();
  });

  it("接口返回空步骤时显示空态文案（不是纯空白）", async () => {
    getExecutorDetailMock.mockResolvedValue({ ...detail, steps: [] });
    render(
      <ExecutorDrawer
        sessionId="sess_main"
        initialExecutorSessionId="sess_exec_1"
        initialLabel="子助手"
        onClose={() => {}}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("还没有步骤。")).toBeTruthy();
    });
  });
});
