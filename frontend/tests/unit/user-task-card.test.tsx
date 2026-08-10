/**
 * ⑦ UserTaskCard 组件测试
 *
 * 验证：
 * - 折叠态显示标题
 * - 有推得动的暂停时显示「继续」按钮
 * - 撞缺陷时显示「需处理」标签 + 说明
 * - 等用户回答时不显示「继续」按钮
 * - 点继续后显示回报（动了/没动/原因）
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import type { UserTaskContinueResponse } from "../../src/api/userTasks";
import UserTaskCard from "../../src/screens/assistant/UserTaskCard";

function mockFetch(responseMap: Record<string, (url: string, init?: RequestInit) => unknown>) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    for (const [pattern, handler] of Object.entries(responseMap)) {
      if (url.includes(pattern)) {
        const body = handler(url, init);
        return {
          ok: true,
          status: 200,
          json: async () => body,
          text: async () => JSON.stringify(body),
        };
      }
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({ tasks: [], distribution: {} }),
      text: async () => "{}",
    };
  });
}

function jsonResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}

describe("UserTaskCard", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ distribution: {} })));
  });

  it("shows the task title in collapsed state", async () => {
    render(
      <UserTaskCard sessionId="s1" taskId="utsk_1" title="季度报告" onOpenFullGraph={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getAllByText("季度报告")[0]).toBeInTheDocument();
    });
    // 标题同时出现在折叠 summary 和展开 body 的 me-task-title 里
    expect(screen.getAllByText("季度报告").length).toBeGreaterThanOrEqual(1);
  });

  it("shows continue button when there are pushable suspensions", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          distribution: { running: 2, "suspended:system": 1, done: 3 },
        }),
      ),
    );
    render(
      <UserTaskCard sessionId="s1" taskId="utsk_1" title="季度报告" onOpenFullGraph={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getByTitle("继续这件事")).toBeInTheDocument();
    });
  });

  it("hides continue button when only waiting on user", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          distribution: { "suspended:user": 2, done: 1 },
        }),
      ),
    );
    render(
      <UserTaskCard sessionId="s1" taskId="utsk_1" title="季度报告" onOpenFullGraph={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getAllByText("季度报告")[0]).toBeInTheDocument();
    });
    expect(screen.queryByTitle("继续这件事")).not.toBeInTheDocument();
  });

  it("shows defect tag and notice when suspended:assistant > 0", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          distribution: { "suspended:assistant": 1, done: 2 },
        }),
      ),
    );
    render(
      <UserTaskCard sessionId="s1" taskId="utsk_1" title="季度报告" onOpenFullGraph={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getByText("需处理")).toBeInTheDocument();
    });
    // 展开后应有缺陷说明
    const summary = screen.getAllByText("季度报告")[0].closest("summary");
    if (summary) fireEvent.click(summary);
    await waitFor(() => {
      expect(screen.getByText(/遇到程序问题/)).toBeInTheDocument();
    });
  });

  it("displays continue report after clicking continue", async () => {
    const continueResponse: UserTaskContinueResponse = {
      pushed: [{ title: "整理区域明细" }],
      notPushed: [{ title: "华东区口径", reason: "在等你回答" }],
      total: 2,
      success: true,
    };
    let callCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/continue")) {
          callCount++;
          return jsonResponse(continueResponse);
        }
        return jsonResponse({
          distribution: { "suspended:system": 1, done: 1 },
        });
      }),
    );
    render(
      <UserTaskCard sessionId="s1" taskId="utsk_1" title="季度报告" onOpenFullGraph={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getByTitle("继续这件事")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTitle("继续这件事"));
    await waitFor(() => {
      expect(screen.getByText(/摊里动了/)).toBeInTheDocument();
    });
    expect(screen.getByText(/整理区域明细/)).toBeInTheDocument();
    expect(screen.getByText(/华东区口径/)).toBeInTheDocument();
  });

  it("shows failure message when nothing was pushed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/continue")) {
          return jsonResponse({
            pushed: [],
            notPushed: [],
            total: 0,
            success: false,
          });
        }
        return jsonResponse({
          distribution: { "suspended:system": 1 },
        });
      }),
    );
    render(
      <UserTaskCard sessionId="s1" taskId="utsk_1" title="季度报告" onOpenFullGraph={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getByTitle("继续这件事")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTitle("继续这件事"));
    await waitFor(() => {
      expect(screen.getByText("没有推动任何任务")).toBeInTheDocument();
    });
  });
});
