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
    discussionSessionId: null,
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
    discussionSessionId: null,
    createdAt: "2026-06-29T10:10:00",
    decidedAt: null,
    completedAt: null,
  },
] as const;

function sourcePackage(proposalId = "prop-1") {
  return {
    proposalId,
    view: "overview",
    scope: "session_tail",
    scopeNote: "第一版未存精确消息范围，以下为复盘会话尾部、文本命中和 skeleton 异常片段。",
    proposal: { id: proposalId, sourceReviewId: "rev-1", findingIndex: 0 },
    source: {
      sourceReviewId: "rev-1",
      findingIndex: 0,
      turnSessionId: "ast_source_1",
      reviewStatus: "completed",
      reviewedAt: "2026-06-29T10:02:00",
      createdAt: "2026-06-29T10:01:00",
      modelUsed: "test-model",
      available: true,
    },
    review: {
      verdict: "发现重复抓取风险",
      currentFinding: { what: "重复抓取同一 URL" },
      findingCount: 1,
    },
    evidence: [
      {
        id: "proposal_finding",
        kind: "review_finding",
        label: "当前 finding",
        excerpt: "重复抓取同一 URL\n两次读取同一页面\n增加请求级缓存",
        truncated: false,
        anchor: { sourceReviewId: "rev-1", findingIndex: 0 },
        reason: "提案直接来自这条复盘 finding",
      },
      {
        id: "tail_user_1",
        kind: "user_message",
        label: "最近用户消息",
        excerpt: "请检查这个页面",
        truncated: false,
        anchor: { sessionId: "ast_source_1", messageId: "msg_1", sequence: 1 },
        reason: "未找到精确消息范围时，用复盘会话尾部辅助定位",
      },
    ],
    nextActions: [
      {
        view: "messages",
        label: "查看原始消息片段",
        description: "分页读取来源会话的用户、助理和工具消息预览。",
      },
    ],
  };
}

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
      proposalSources: {},
      loadingProposalSourceId: null,
      proposalSourceError: null,
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
      if (url.includes("/api/improvement-proposals/") && url.includes("/source")) {
        return jsonResponse(sourcePackage(url.includes("prop-2") ? "prop-2" : "prop-1"));
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
    await screen.findByText("来源证据");
    expect(screen.getByText("当前 finding")).toBeInTheDocument();
    expect(screen.getByText("复盘 rev-1")).toBeInTheDocument();
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
      if (url.includes("/api/improvement-proposals/") && url.includes("/source")) {
        return jsonResponse(sourcePackage());
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
      if (url.includes("/api/improvement-proposals/") && url.includes("/source")) {
        return jsonResponse(sourcePackage());
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
      if (url.includes("/api/improvement-proposals/") && url.includes("/source")) {
        return jsonResponse(sourcePackage());
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
    expect(screen.getByLabelText("补充说明").closest(".brain-proposal-decision")).not.toBeNull();
    const actionButtons = screen.getByRole("button", { name: "批准" }).closest(".brain-action-buttons");
    expect(actionButtons).not.toBeNull();
    const actionLabels = Array.from((actionButtons as HTMLElement).querySelectorAll("button")).map((button) =>
      button.textContent?.trim(),
    );
    expect(actionLabels).toEqual(["讨论", "批准", "拒绝"]);

    fireEvent.change(screen.getByLabelText("补充说明"), { target: { value: "覆盖缓存层" } });
    fireEvent.click(screen.getByRole("button", { name: "批准" }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "批准" })).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: "拒绝" })).not.toBeInTheDocument();
  });

  test("detail renders reasoning chain and outcome zone by semantic region", async () => {
    const doneProposal = {
      ...proposals[0],
      id: "prop-done",
      status: "done",
      what: "重复抓取同一 URL",
      userSupplement: "优先覆盖缓存层",
      branchName: "improvement/prop-done",
      resultTestsPassed: true,
      resultSummary: "已加请求级缓存，12 个测试通过",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/brain/zones")) return jsonResponse({ zones: [] });
      if (url.includes("/api/brain/zones/hot/entries")) {
        return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
      }
      if (url.includes("/api/brain/segments")) return jsonResponse({ items: [], total: 0 });
      if (url.includes("/api/execution-reviews")) return jsonResponse({ reviews: [] });
      if (url.includes("/api/improvement-proposals/") && url.includes("/source")) {
        return jsonResponse(sourcePackage("prop-done"));
      }
      if (url.includes("/api/improvement-proposals")) {
        return jsonResponse({ proposals: [doneProposal] });
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
    await screen.findByText("当前 finding");

    const detail = within(screen.getByLabelText("改进提案详情"));
    expect(detail.getByRole("button", { name: "讨论" }).closest(".brain-proposal-followup")).not.toBeNull();

    // 论证链三个语义节点按序出现，"建议"是终点
    expect(detail.getByText("问题")).toBeInTheDocument();
    expect(detail.getByText("证据")).toBeInTheDocument();
    expect(detail.getByText("建议")).toBeInTheDocument();
    expect(detail.getByText("增加请求级缓存")).toBeInTheDocument();

    // 用户补充与机器实施结果各自成区
    expect(detail.getByText("你的补充")).toBeInTheDocument();
    expect(detail.getByText("优先覆盖缓存层")).toBeInTheDocument();
    expect(detail.getByText("实施情况")).toBeInTheDocument();
    expect(detail.getByText("improvement/prop-done")).toBeInTheDocument();
    expect(detail.getByText("测试通过")).toBeInTheDocument();

    // 已完成的提案不显示批准/拒绝，但可发起复盘讨论（US3）
    expect(detail.queryByRole("button", { name: "批准" })).not.toBeInTheDocument();
    expect(detail.getByRole("button", { name: "讨论" })).toBeEnabled();
  });

  test("discuss button opens session, navigates to assistant and selects it", async () => {
    const { useAssistantStore } = await import("../../src/state/assistantStore");
    const { useShellStore } = await import("../../src/state/shellStore");

    const selectSessionMock = vi.fn(async () => {});
    useAssistantStore.setState({ selectSession: selectSessionMock });
    useShellStore.setState({ activeRoute: "brain" });

    let discussionCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/brain/zones")) return jsonResponse({ zones: [] });
      if (url.includes("/api/brain/zones/hot/entries")) {
        return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
      }
      if (url.includes("/api/brain/segments")) return jsonResponse({ items: [], total: 0 });
      if (url.includes("/api/execution-reviews")) return jsonResponse({ reviews: [] });
      if (url.includes("/api/improvement-proposals/prop-1/discussion")) {
        expect(init?.method).toBe("POST");
        discussionCalls += 1;
        return jsonResponse({ sessionId: "ast_disc_001", created: true });
      }
      if (url.includes("/api/improvement-proposals/") && url.includes("/source")) {
        return jsonResponse(sourcePackage());
      }
      if (url.includes("/api/improvement-proposals")) {
        return jsonResponse({
          proposals:
            discussionCalls > 0
              ? [{ ...proposals[0], discussionSessionId: "ast_disc_001" }, proposals[1]]
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

    const detail = within(screen.getByLabelText("改进提案详情"));
    fireEvent.click(detail.getByRole("button", { name: "讨论" }));

    await waitFor(() => expect(selectSessionMock).toHaveBeenCalledWith("ast_disc_001"));
    expect(useShellStore.getState().activeRoute).toBe("assistant");
    expect(discussionCalls).toBe(1);

    // 绑定回写后按钮文案切换为"继续讨论"（US2）
    await waitFor(() =>
      expect(detail.getByRole("button", { name: "继续讨论" })).toBeInTheDocument(),
    );
  });

  test("discuss button is disabled while the request is pending", async () => {
    const pendingDiscussion: { resolve?: (value: Response) => void } = {};
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/brain/zones")) return jsonResponse({ zones: [] });
      if (url.includes("/api/brain/zones/hot/entries")) {
        return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
      }
      if (url.includes("/api/brain/segments")) return jsonResponse({ items: [], total: 0 });
      if (url.includes("/api/execution-reviews")) return jsonResponse({ reviews: [] });
      if (url.includes("/api/improvement-proposals/prop-1/discussion")) {
        return new Promise<Response>((resolve) => {
          pendingDiscussion.resolve = resolve;
        });
      }
      if (url.includes("/api/improvement-proposals/") && url.includes("/source")) {
        return jsonResponse(sourcePackage());
      }
      if (url.includes("/api/improvement-proposals")) {
        return jsonResponse({ proposals: [proposals[0], proposals[1]] });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<BrainScreen />);
    await settleAsyncUpdates();

    fireEvent.click(screen.getByRole("button", { name: /改进提案/ }));
    await waitFor(() => expect(screen.getByText("重复抓取同一 URL")).toBeInTheDocument());
    fireEvent.click(within(screen.getByLabelText("改进提案列表")).getByText("重复抓取同一 URL"));

    const detail = within(screen.getByLabelText("改进提案详情"));
    fireEvent.click(detail.getByRole("button", { name: "讨论" }));

    await waitFor(() => expect(detail.getByRole("button", { name: "讨论" })).toBeDisabled());

    pendingDiscussion.resolve?.(jsonResponse({ sessionId: "ast_disc_002", created: true }));
    await waitFor(() => expect(detail.getByRole("button", { name: /讨论/ })).toBeEnabled());
  });
});
