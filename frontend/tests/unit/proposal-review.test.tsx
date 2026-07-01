import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import BrainScreen from "../../src/screens/BrainScreen";
import { useBrainStore } from "../../src/state/brainStore";
import { useSettingsStore } from "../../src/state/settingsStore";

function jsonResponse(payload: unknown): Response {
  return { ok: true, json: async () => payload } as Response;
}

async function settleAsyncUpdates(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

const proposals = [
  {
    id: "prop-1",
    sourceReviewId: "rev-1",
    findingIndex: 0,
    status: "pending_review",
    severity: "med",
    findingType: "efficiency",
    what: "重复抓取同一 URL",
    evidence: "两次读取同一页面",
    suggestion: "增加请求级缓存",
    userSupplement: null,
    graphId: null,
    worktreeAvailable: false,
    branchName: null,
    resultTestsPassed: null,
    resultSummary: null,
    error: null,
    createdAt: "2026-06-29T10:00:00",
    decidedAt: null,
    completedAt: null,
  },
  {
    id: "prop-2",
    sourceReviewId: "rev-2",
    findingIndex: 0,
    status: "pending_review",
    severity: "low",
    findingType: "robustness",
    what: "网络失败缺少退避",
    evidence: "重试立即发生",
    suggestion: "增加指数退避",
    userSupplement: null,
    graphId: null,
    worktreeAvailable: false,
    branchName: null,
    resultTestsPassed: null,
    resultSummary: null,
    error: null,
    createdAt: "2026-06-29T10:10:00",
    decidedAt: null,
    completedAt: null,
  },
] as const;

describe("proposal review UI", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    useBrainStore.setState({
      zones: [],
      entries: [],
      entriesTotal: 0,
      activeZone: null,
      segments: [],
      segmentsTotal: 0,
      executionReviews: [],
      skillPool: [],
      evolutionChain: [],
      loadingZones: false,
      loadingEntries: false,
      loadingSegments: false,
      loadingExecutionReviews: false,
      loadingSkillPool: false,
      loadingEvolution: false,
      lastError: null,
      pendingSkillRemoval: null,
      improvementProposals: [],
      loadingImprovementProposals: false,
    });
    useSettingsStore.setState({
      values: {
        "self_improvement.execution_review.enabled": true,
        "self_improvement.proposals.enabled": true,
      },
      draftValues: {},
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("displays proposals and routes approve/reject with supplement", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/brain/zones")) {
        return jsonResponse({ zones: [] });
      }
      if (url.includes("/api/brain/zones/hot/entries")) {
        return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
      }
      if (url.includes("/api/brain/segments")) {
        return jsonResponse({ items: [], total: 0 });
      }
      if (url.includes("/api/execution-reviews")) {
        return jsonResponse({ reviews: [] });
      }
      if (url.includes("/api/improvement-proposals/prop-1/approve")) {
        return jsonResponse({ accepted: true, id: "prop-1", status: "approved" });
      }
      if (url.includes("/api/improvement-proposals/prop-2/reject")) {
        return jsonResponse({ accepted: true, id: "prop-2", status: "rejected" });
      }
      if (url.includes("/api/improvement-proposals")) {
        return jsonResponse({ proposals });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<BrainScreen />);
    await settleAsyncUpdates();

    fireEvent.click(screen.getByRole("button", { name: /改进提案/ }));
    await waitFor(() => expect(screen.getByText("重复抓取同一 URL")).toBeInTheDocument());

    const list = screen.getByLabelText("改进提案列表");
    fireEvent.click(within(list).getByText("重复抓取同一 URL"));
    fireEvent.change(screen.getByLabelText("补充说明"), {
      target: { value: "先覆盖请求缓存测试" },
    });
    fireEvent.click(screen.getByRole("button", { name: "批准" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/improvement-proposals/prop-1/approve",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ supplement: "先覆盖请求缓存测试" }),
        }),
      ),
    );

    fireEvent.click(within(list).getByText("网络失败缺少退避"));
    fireEvent.click(screen.getByRole("button", { name: "拒绝" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/improvement-proposals/prop-2/reject",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  test("keeps supplement when approve is not accepted", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/brain/zones")) {
        return jsonResponse({ zones: [] });
      }
      if (url.includes("/api/brain/segments")) {
        return jsonResponse({ items: [], total: 0 });
      }
      if (url.includes("/api/execution-reviews")) {
        return jsonResponse({ reviews: [] });
      }
      if (url.includes("/api/improvement-proposals/prop-1/approve")) {
        return jsonResponse({ accepted: false, reason: "not_pending" });
      }
      if (url.includes("/api/improvement-proposals")) {
        return jsonResponse({ proposals });
      }
      return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<BrainScreen />);
    await settleAsyncUpdates();

    fireEvent.click(screen.getByRole("button", { name: /改进提案/ }));
    await waitFor(() => expect(screen.getByText("重复抓取同一 URL")).toBeInTheDocument());

    fireEvent.click(within(screen.getByLabelText("改进提案列表")).getByText("重复抓取同一 URL"));
    fireEvent.change(screen.getByLabelText("补充说明"), {
      target: { value: "先覆盖请求缓存测试" },
    });
    fireEvent.click(screen.getByRole("button", { name: "批准" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/improvement-proposals/prop-1/approve",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(screen.getByLabelText("补充说明")).toHaveValue("先覆盖请求缓存测试");
  });

  test("refreshes proposals from the proposal view", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/brain/zones")) {
        return jsonResponse({ zones: [] });
      }
      if (url.includes("/api/brain/segments")) {
        return jsonResponse({ items: [], total: 0 });
      }
      if (url.includes("/api/execution-reviews")) {
        return jsonResponse({ reviews: [] });
      }
      if (url.includes("/api/improvement-proposals")) {
        return jsonResponse({ proposals });
      }
      return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<BrainScreen />);
    await settleAsyncUpdates();

    fireEvent.click(screen.getByRole("button", { name: /改进提案/ }));
    await waitFor(() => expect(screen.getByText("重复抓取同一 URL")).toBeInTheDocument());
    fetchMock.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "刷新" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/improvement-proposals?limit=50",
        expect.any(Object),
      ),
    );
  });

  test("hides approve/reject actions after a proposal becomes approved", async () => {
    // 026 review CG-6:approve 后重拉必须反映 approved 状态;isPending=False 时
    // 批准/拒绝 + 补充说明整块隐藏。删掉 BrainScreen.tsx 的 isPending 条件、或重拉
    // 不刷新状态(原测试装置重拉返回同样的 pending_review,状态迁移无法被观察),此测试应红。
    let prop1Approved = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/brain/zones")) return jsonResponse({ zones: [] });
      if (url.includes("/api/brain/zones/hot/entries")) {
        return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
      }
      if (url.includes("/api/brain/segments")) return jsonResponse({ items: [], total: 0 });
      if (url.includes("/api/execution-reviews")) return jsonResponse({ reviews: [] });
      if (url.includes("/api/improvement-proposals/prop-1/approve")) {
        prop1Approved = true;
        return jsonResponse({ accepted: true, id: "prop-1", status: "approved" });
      }
      if (url.includes("/api/improvement-proposals")) {
        return jsonResponse({
          proposals: prop1Approved
            ? [{ ...proposals[0], status: "approved" }, proposals[1]]
            : [proposals[0], proposals[1]],
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<BrainScreen />);
    await settleAsyncUpdates();

    fireEvent.click(screen.getByRole("button", { name: /改进提案/ }));
    await waitFor(() => expect(screen.getByText("重复抓取同一 URL")).toBeInTheDocument());

    const list = screen.getByLabelText("改进提案列表");
    fireEvent.click(within(list).getByText("重复抓取同一 URL"));
    expect(screen.getByRole("button", { name: "批准" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("补充说明"), { target: { value: "覆盖缓存层" } });
    fireEvent.click(screen.getByRole("button", { name: "批准" }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "批准" })).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: "拒绝" })).not.toBeInTheDocument();
  });
});
