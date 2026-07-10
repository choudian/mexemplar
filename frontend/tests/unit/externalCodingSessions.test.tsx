import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  abandonExternalCodingSession: vi.fn(),
  analyzeExternalCodingMerge: vi.fn(),
  confirmRollback: vi.fn(),
  createRollbackPlan: vi.fn(),
  decideExternalCodingPlan: vi.fn(),
  escalateExternalCodingSession: vi.fn(),
  getExternalCodingSession: vi.fn(),
  mergeExternalCodingSession: vi.fn(),
  refreshExternalCodingSession: vi.fn(),
  resumeExternalCodingSession: vi.fn(),
}));

vi.mock("../../src/api/externalCodingSessions", () => apiMocks);

import type { AssistantTaskSnapshot } from "../../src/api/assistantTasks";
import type {
  ExternalCodingSessionDetail,
  ExternalCodingSessionTaskSummary,
} from "../../src/api/externalCodingSessions";
import TaskNodeCard from "../../src/screens/assistant/TaskNodeCard";
import { useExternalCodingSessionStore } from "../../src/state/externalCodingSessionStore";

function makeTask(
  externalCodingSessions: ExternalCodingSessionTaskSummary[] = [],
): AssistantTaskSnapshot {
  return {
    taskId: "tsk-001",
    graphId: "graph-001",
    parentTaskId: "tsk-root",
    title: "实现外部 coding",
    descriptionPreview: "交给外部 coding agent 处理",
    status: "running",
    displayPhase: "running",
    requiresReview: false,
    requiresConfirmation: false,
    safeExplanation: "",
    externalCodingSessions,
  };
}

function makeDetail(
  overrides: Partial<ExternalCodingSessionDetail> = {},
): ExternalCodingSessionDetail {
  return {
    codingSessionId: "ecs-001",
    sessionId: "sess-001",
    ownerType: "task",
    ownerId: "tsk-001",
    tool: "claude_code",
    launchMode: "headless",
    status: "plan_ready",
    phase: "plan",
    selectedReason: "available quota",
    quotaState: "available",
    worktreePath: "E:\\private\\coding-worktree",
    branchName: "coding/ecs-001",
    artifactDir: "E:\\private\\artifacts",
    planPreview: "目标：实现外部 coding session。测试计划：vitest。",
    resultPreview: null,
    logTail: null,
    lastErrorCategory: null,
    lastErrorMessage: null,
    resumeCount: 0,
    reviewRecommended: true,
    reviewSkippedReason: null,
    createdAt: "2026-07-09T00:00:00",
    updatedAt: "2026-07-09T00:00:00",
    completedAt: null,
    attempts: [],
    quota: [],
    mergeRecords: [],
    rollbackDecisions: [],
    availableActions: ["inspect", "approve_plan", "reject_plan", "abandon"],
    artifacts: { handoff: {} },
    ...overrides,
  };
}

function summaryOf(
  detail: ExternalCodingSessionDetail,
): ExternalCodingSessionTaskSummary {
  return {
    codingSessionId: detail.codingSessionId,
    tool: detail.tool,
    status: detail.status,
    phase: detail.phase,
  };
}

function seedDetail(detail: ExternalCodingSessionDetail): void {
  useExternalCodingSessionStore.setState({
    detailsById: { [detail.codingSessionId]: detail },
  });
}

function renderExpanded(detail: ExternalCodingSessionDetail): void {
  seedDetail(detail);
  render(<TaskNodeCard task={makeTask([summaryOf(detail)])} />);
  fireEvent.doubleClick(screen.getByRole("button", { name: /任务 实现外部 coding/ }));
}

describe("TaskNodeCard external coding sessions", () => {
  beforeEach(() => {
    for (const mock of Object.values(apiMocks)) mock.mockReset();
    useExternalCodingSessionStore.getState().clear();
  });

  it("loads authoritative detail when the task card is expanded", async () => {
    const detail = makeDetail();
    apiMocks.getExternalCodingSession.mockResolvedValue(detail);

    render(<TaskNodeCard task={makeTask([summaryOf(detail)])} />);
    fireEvent.doubleClick(screen.getByRole("button", { name: /任务 实现外部 coding/ }));

    expect(screen.getByText("正在加载详情…")).toBeDefined();
    await waitFor(() =>
      expect(apiMocks.getExternalCodingSession).toHaveBeenCalledWith("ecs-001"),
    );
    expect(await screen.findByText("coding/ecs-001")).toBeDefined();
    expect(screen.getByRole("button", { name: "批准计划" })).toBeDefined();
  });

  it("approves a plan and shows completion feedback", async () => {
    const detail = makeDetail();
    const approved = makeDetail({
      status: "plan_approved",
      phase: "implement",
      availableActions: ["inspect", "abandon"],
    });
    apiMocks.decideExternalCodingPlan.mockResolvedValue(approved);
    renderExpanded(detail);

    fireEvent.click(screen.getByRole("button", { name: "批准计划" }));

    await waitFor(() =>
      expect(apiMocks.decideExternalCodingPlan).toHaveBeenCalledWith(
        "ecs-001",
        "approved",
      ),
    );
    expect(
      await screen.findByText("计划已批准，coding session 将进入实现阶段。"),
    ).toBeDefined();
  });

  it("requires feedback before rejecting a plan", async () => {
    const detail = makeDetail();
    apiMocks.decideExternalCodingPlan.mockResolvedValue(
      makeDetail({ status: "plan_rejected", availableActions: ["inspect", "resume", "abandon"] }),
    );
    renderExpanded(detail);

    fireEvent.click(screen.getByRole("button", { name: "打回计划" }));
    const confirmButton = screen.getByRole("button", { name: "确认" });
    expect(confirmButton).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox", { name: "计划修改意见" }), {
      target: { value: "补充失败路径测试。" },
    });
    expect(confirmButton).not.toBeDisabled();
    fireEvent.click(confirmButton);

    await waitFor(() =>
      expect(apiMocks.decideExternalCodingPlan).toHaveBeenCalledWith(
        "ecs-001",
        "rejected",
        "补充失败路径测试。",
      ),
    );
  });

  it("submits masked merge targets without rendering the local path", async () => {
    const detail = makeDetail({
      status: "completed",
      phase: "done",
      availableActions: ["inspect", "merge_analysis", "abandon"],
    });
    const analyzed = makeDetail({
      status: "merge_ready",
      phase: "merge",
      availableActions: ["inspect", "merge"],
    });
    apiMocks.analyzeExternalCodingMerge.mockResolvedValue({ mergeRecordId: "merge-1" });
    apiMocks.getExternalCodingSession.mockResolvedValue(analyzed);
    renderExpanded(detail);

    fireEvent.click(screen.getByRole("button", { name: "分析合并" }));
    const pathInput = screen.getByLabelText("合并目标工作区路径") as HTMLInputElement;
    expect(pathInput.type).toBe("password");
    fireEvent.change(screen.getByLabelText("合并目标分支"), {
      target: { value: "main" },
    });
    fireEvent.change(pathInput, { target: { value: "E:\\private\\main-worktree" } });
    expect(screen.queryByText(/main-worktree/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "开始分析" }));

    await waitFor(() =>
      expect(apiMocks.analyzeExternalCodingMerge).toHaveBeenCalledWith(
        "ecs-001",
        "main",
        "E:\\private\\main-worktree",
      ),
    );
  });

  it("requires an explicit decision before a risky merge", async () => {
    const detail = makeDetail({
      status: "merge_blocked",
      phase: "merge",
      availableActions: ["inspect", "merge", "abandon"],
      mergeRecords: [
        {
          mergeRecordId: "merge-1",
          codingSessionId: "ecs-001",
          dirtyFiles: ["one"],
          changedFiles: ["one", "two"],
          overlapFiles: ["one"],
          conflictRisk: "overlap",
          status: "analysis_ready",
        },
      ],
    });
    apiMocks.mergeExternalCodingSession.mockResolvedValue({ status: "merged" });
    apiMocks.getExternalCodingSession.mockResolvedValue(
      makeDetail({ status: "merged", phase: "done", availableActions: ["inspect", "rollback_plan"] }),
    );
    renderExpanded(detail);

    fireEvent.click(screen.getByRole("button", { name: "执行合并" }));
    expect(screen.getByText("文件存在重叠")).toBeDefined();
    const confirmButton = screen.getByRole("button", { name: "确认合并" });
    expect(confirmButton).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: "合并风险裁定说明" }), {
      target: { value: "已检查重叠内容，可以继续。" },
    });
    fireEvent.click(confirmButton);

    await waitFor(() =>
      expect(apiMocks.mergeExternalCodingSession).toHaveBeenCalledWith(
        "ecs-001",
        "merge-1",
        "已检查重叠内容，可以继续。",
      ),
    );
  });

  it("shows a safe rollback explanation and executes explicit confirmation", async () => {
    const detail = makeDetail({
      status: "rollback_proposed",
      phase: "rollback",
      availableActions: ["inspect", "confirm_rollback"],
      rollbackDecisions: [
        {
          rollbackId: "rollback-1",
          codingSessionId: "ecs-001",
          intentSummary: "撤销本次改动",
          chosenStrategy: "revert_commit",
          safeExplanation: "仅撤销本次提交，工作区位于 E:\\private\\repo。",
          requiresConfirmation: true,
          status: "proposed",
        },
      ],
    });
    apiMocks.confirmRollback.mockResolvedValue({ status: "applied" });
    apiMocks.getExternalCodingSession.mockResolvedValue(
      makeDetail({ status: "rolled_back", phase: "done", availableActions: ["inspect"] }),
    );
    renderExpanded(detail);

    fireEvent.click(screen.getByRole("button", { name: "确认回滚" }));
    expect(screen.getByText(/仅撤销本次提交/)).toHaveTextContent("[本地路径已隐藏]");
    expect(screen.queryByText(/private.*repo/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "执行回滚" }));

    await waitFor(() =>
      expect(apiMocks.confirmRollback).toHaveBeenCalledWith(
        "ecs-001",
        "rollback-1",
        "user",
      ),
    );
  });

  it("redacts local paths from previews, activity, and fallback errors", () => {
    const detail = makeDetail({
      planPreview: "修改 E:\\private\\project\\app.ts",
      logTail: "opened /home/alice/project/app.ts",
      lastErrorCategory: "unknown",
      lastErrorMessage: "failed at E:\\private\\project\\app.ts",
    });
    renderExpanded(detail);

    expect(screen.queryByText(/private|alice/)).toBeNull();
    expect(screen.getAllByText(/本地路径已隐藏/).length).toBeGreaterThanOrEqual(3);
  });

  it("shows when completed output has not been independently reviewed", () => {
    const detail = makeDetail({
      status: "completed",
      phase: "done",
      reviewRecommended: true,
      reviewSkippedReason:
        "Independent review/test has not yet been recorded; result not independently verified.",
      availableActions: ["inspect", "merge_analysis"],
    });

    renderExpanded(detail);

    expect(screen.getByText(/not independently verified/)).toBeDefined();
  });

  it("shows an actionable safe error when detail loading fails", async () => {
    const detail = makeDetail();
    apiMocks.getExternalCodingSession.mockRejectedValue(
      new Error("backend failed at E:\\private\\secret"),
    );

    render(<TaskNodeCard task={makeTask([summaryOf(detail)])} />);
    fireEvent.doubleClick(screen.getByRole("button", { name: /任务 实现外部 coding/ }));

    expect(
      await screen.findByText("暂时无法加载 coding session，请稍后重试。"),
    ).toBeDefined();
    expect(screen.queryByText(/private.*secret/)).toBeNull();
  });
});
