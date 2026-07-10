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

import type { ExternalCodingSessionDetail } from "../../src/api/externalCodingSessions";
import { DesktopApiError } from "../../src/api/client";
import { useExternalCodingSessionStore } from "../../src/state/externalCodingSessionStore";

const detail = {
  codingSessionId: "ecs-1",
  availableActions: ["inspect"],
} as ExternalCodingSessionDetail;
const updatedDetail = {
  codingSessionId: "ecs-1",
  availableActions: ["inspect", "abandon"],
} as ExternalCodingSessionDetail;

async function flush(): Promise<void> {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

describe("externalCodingSessionStore", () => {
  beforeEach(() => {
    for (const mock of Object.values(apiMocks)) mock.mockReset();
    apiMocks.getExternalCodingSession.mockResolvedValue(detail);
    apiMocks.refreshExternalCodingSession.mockResolvedValue(detail);
    useExternalCodingSessionStore.getState().clear();
  });

  it("refreshes only a session already present in the cache after an event", async () => {
    useExternalCodingSessionStore.getState().refreshIfCached("ecs-1");
    await flush();
    expect(apiMocks.refreshExternalCodingSession).not.toHaveBeenCalled();

    await useExternalCodingSessionStore.getState().load("ecs-1");
    useExternalCodingSessionStore.getState().refreshIfCached("ecs-1");
    await flush();

    expect(apiMocks.getExternalCodingSession).toHaveBeenCalledWith("ecs-1");
    expect(apiMocks.refreshExternalCodingSession).toHaveBeenCalledWith("ecs-1");
    expect(
      useExternalCodingSessionStore.getState().noticeById["ecs-1"],
    ).toBeUndefined();
  });

  it("tracks a pending plan action and stores authoritative success state", async () => {
    let resolve!: (value: ExternalCodingSessionDetail) => void;
    apiMocks.decideExternalCodingPlan.mockReturnValue(
      new Promise<ExternalCodingSessionDetail>((done) => {
        resolve = done;
      }),
    );

    const operation = useExternalCodingSessionStore.getState().approvePlan("ecs-1");
    expect(useExternalCodingSessionStore.getState().busyActionById["ecs-1"]).toBe(
      "approve_plan",
    );

    resolve(updatedDetail);
    await expect(operation).resolves.toBe(true);
    expect(apiMocks.decideExternalCodingPlan).toHaveBeenCalledWith("ecs-1", "approved");
    expect(useExternalCodingSessionStore.getState().detailsById["ecs-1"]).toBe(
      updatedDetail,
    );
    expect(useExternalCodingSessionStore.getState().busyActionById["ecs-1"]).toBeUndefined();
    expect(useExternalCodingSessionStore.getState().noticeById["ecs-1"]).toContain(
      "计划已批准",
    );
  });

  it("wires plan feedback, resume, abandon, and escalation actions", async () => {
    apiMocks.decideExternalCodingPlan.mockResolvedValue(updatedDetail);
    apiMocks.resumeExternalCodingSession.mockResolvedValue(updatedDetail);
    apiMocks.abandonExternalCodingSession.mockResolvedValue(updatedDetail);
    apiMocks.escalateExternalCodingSession.mockResolvedValue(updatedDetail);
    const store = useExternalCodingSessionStore.getState();

    await store.rejectPlan("ecs-1", "补测试");
    await store.resume("ecs-1", "继续实现", "implement");
    await store.abandon("ecs-1", "方向变化");
    await store.escalateToUser("ecs-1", "需要完成登录");

    expect(apiMocks.decideExternalCodingPlan).toHaveBeenCalledWith(
      "ecs-1",
      "rejected",
      "补测试",
    );
    expect(apiMocks.resumeExternalCodingSession).toHaveBeenCalledWith("ecs-1", {
      instruction: "继续实现",
      phase: "implement",
    });
    expect(apiMocks.abandonExternalCodingSession).toHaveBeenCalledWith(
      "ecs-1",
      "方向变化",
    );
    expect(apiMocks.escalateExternalCodingSession).toHaveBeenCalledWith(
      "ecs-1",
      "需要完成登录",
    );
  });

  it("reloads authoritative detail after merge and rollback record actions", async () => {
    apiMocks.analyzeExternalCodingMerge.mockResolvedValue({ mergeRecordId: "merge-1" });
    apiMocks.mergeExternalCodingSession.mockResolvedValue({
      mergeRecordId: "merge-1",
      status: "merged",
    });
    apiMocks.createRollbackPlan.mockResolvedValue({ rollbackId: "rollback-1" });
    apiMocks.confirmRollback.mockResolvedValue({
      rollbackId: "rollback-1",
      status: "applied",
    });
    apiMocks.getExternalCodingSession.mockResolvedValue(updatedDetail);
    const store = useExternalCodingSessionStore.getState();

    await store.analyzeMerge("ecs-1", "main", "E:\\repo");
    await store.merge("ecs-1", "merge-1", "风险已检查");
    await store.planRollback("ecs-1", "只撤销本次改动");
    await store.confirmRollback("ecs-1", "rollback-1");

    expect(apiMocks.analyzeExternalCodingMerge).toHaveBeenCalledWith(
      "ecs-1",
      "main",
      "E:\\repo",
    );
    expect(apiMocks.mergeExternalCodingSession).toHaveBeenCalledWith(
      "ecs-1",
      "merge-1",
      "风险已检查",
    );
    expect(apiMocks.createRollbackPlan).toHaveBeenCalledWith(
      "ecs-1",
      "只撤销本次改动",
    );
    expect(apiMocks.confirmRollback).toHaveBeenCalledWith(
      "ecs-1",
      "rollback-1",
      "user",
    );
    expect(apiMocks.getExternalCodingSession).toHaveBeenCalledTimes(4);
    expect(useExternalCodingSessionStore.getState().detailsById["ecs-1"]).toBe(
      updatedDetail,
    );
  });

  it("does not report success when a merge audit record is failed", async () => {
    apiMocks.mergeExternalCodingSession.mockResolvedValue({
      mergeRecordId: "merge-1",
      status: "failed",
    });
    apiMocks.getExternalCodingSession.mockResolvedValue(updatedDetail);

    await expect(
      useExternalCodingSessionStore
        .getState()
        .merge("ecs-1", "merge-1", "风险已检查"),
    ).resolves.toBe(false);

    const state = useExternalCodingSessionStore.getState();
    expect(state.detailsById["ecs-1"]).toBe(updatedDetail);
    expect(state.errorById["ecs-1"]).toBe(
      "合并未完成，请查看风险提示后重试。",
    );
    expect(state.noticeById["ecs-1"]).toBe("");
  });

  it("projects API errors into actionable text without exposing backend detail", async () => {
    apiMocks.decideExternalCodingPlan.mockRejectedValue(
      new DesktopApiError(
        422,
        "invalid_state",
        "failed at E:\\private\\secret",
      ),
    );

    await expect(
      useExternalCodingSessionStore.getState().approvePlan("ecs-1"),
    ).resolves.toBe(false);

    const message = useExternalCodingSessionStore.getState().errorById["ecs-1"];
    expect(message).toBe("当前状态或输入不允许执行此操作，请检查后重试。");
    expect(message).not.toContain("private");
  });
});
