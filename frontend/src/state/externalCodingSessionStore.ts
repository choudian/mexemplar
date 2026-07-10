import { create } from "zustand";

import {
  abandonExternalCodingSession,
  analyzeExternalCodingMerge,
  confirmRollback,
  createRollbackPlan,
  decideExternalCodingPlan,
  escalateExternalCodingSession,
  getExternalCodingSession,
  mergeExternalCodingSession,
  refreshExternalCodingSession,
  resumeExternalCodingSession,
} from "../api/externalCodingSessions";
import type {
  ExternalCodingAvailableAction,
  ExternalCodingSessionDetail,
} from "../api/externalCodingSessions";
import { DesktopApiError } from "../api/client";

type ResumePhase = "plan" | "implement";

interface ExternalCodingSessionState {
  detailsById: Record<string, ExternalCodingSessionDetail>;
  loadingIds: string[];
  busyActionById: Record<string, ExternalCodingAvailableAction | undefined>;
  errorById: Record<string, string>;
  noticeById: Record<string, string>;
  load: (codingSessionId: string) => Promise<boolean>;
  refresh: (codingSessionId: string) => Promise<boolean>;
  approvePlan: (codingSessionId: string) => Promise<boolean>;
  rejectPlan: (codingSessionId: string, feedback: string) => Promise<boolean>;
  resume: (
    codingSessionId: string,
    instruction: string,
    phase?: ResumePhase,
  ) => Promise<boolean>;
  abandon: (codingSessionId: string, reason: string) => Promise<boolean>;
  escalateToUser: (codingSessionId: string, reason: string) => Promise<boolean>;
  analyzeMerge: (
    codingSessionId: string,
    targetBranch: string,
    targetWorktreePath: string,
  ) => Promise<boolean>;
  merge: (
    codingSessionId: string,
    mergeRecordId: string,
    agentDecision: string,
  ) => Promise<boolean>;
  planRollback: (codingSessionId: string, intentSummary: string) => Promise<boolean>;
  confirmRollback: (codingSessionId: string, rollbackId: string) => Promise<boolean>;
  refreshIfCached: (codingSessionId: string) => void;
  clearFeedback: (codingSessionId: string) => void;
  clear: () => void;
}

function addId(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids : [...ids, id];
}

function removeId(ids: string[], id: string): string[] {
  return ids.filter((item) => item !== id);
}

function toSafeErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof DesktopApiError)) {
    return fallback;
  }
  if (error.status === 401 || error.status === 403) {
    return "当前连接已失效，请重新打开应用后再试。";
  }
  if (error.status === 404) {
    return "这个 coding session 已不存在，请刷新任务详情。";
  }
  if (error.status === 409) {
    return "coding session 状态已变化，请刷新后再操作。";
  }
  if (error.status === 422) {
    return "当前状态或输入不允许执行此操作，请检查后重试。";
  }
  return fallback;
}

export const useExternalCodingSessionStore = create<ExternalCodingSessionState>((set, get) => {
  const fetchDetail = async (
    codingSessionId: string,
    refresh: boolean,
    showNotice: boolean,
  ): Promise<boolean> => {
    if (get().loadingIds.includes(codingSessionId)) {
      return false;
    }
    set((state) => ({
      loadingIds: addId(state.loadingIds, codingSessionId),
      errorById: { ...state.errorById, [codingSessionId]: "" },
    }));
    try {
      const detail = refresh
        ? await refreshExternalCodingSession(codingSessionId)
        : await getExternalCodingSession(codingSessionId);
      set((state) => ({
        detailsById: { ...state.detailsById, [codingSessionId]: detail },
        loadingIds: removeId(state.loadingIds, codingSessionId),
        noticeById: showNotice
          ? { ...state.noticeById, [codingSessionId]: "状态已更新。" }
          : state.noticeById,
      }));
      return true;
    } catch (error) {
      set((state) => ({
        loadingIds: removeId(state.loadingIds, codingSessionId),
        errorById: {
          ...state.errorById,
          [codingSessionId]: toSafeErrorMessage(
            error,
            refresh ? "暂时无法刷新 coding session，请稍后重试。" : "暂时无法加载 coding session，请稍后重试。",
          ),
        },
      }));
      return false;
    }
  };

  const runAction = async (
    codingSessionId: string,
    action: ExternalCodingAvailableAction,
    successMessage: string,
    fallbackError: string,
    mutation: () => Promise<ExternalCodingSessionDetail>,
  ): Promise<boolean> => {
    if (get().busyActionById[codingSessionId]) {
      return false;
    }
    set((state) => ({
      busyActionById: { ...state.busyActionById, [codingSessionId]: action },
      errorById: { ...state.errorById, [codingSessionId]: "" },
      noticeById: { ...state.noticeById, [codingSessionId]: "" },
    }));
    try {
      const detail = await mutation();
      set((state) => ({
        detailsById: { ...state.detailsById, [codingSessionId]: detail },
        busyActionById: { ...state.busyActionById, [codingSessionId]: undefined },
        noticeById: { ...state.noticeById, [codingSessionId]: successMessage },
      }));
      return true;
    } catch (error) {
      set((state) => ({
        busyActionById: { ...state.busyActionById, [codingSessionId]: undefined },
        errorById: {
          ...state.errorById,
          [codingSessionId]: toSafeErrorMessage(error, fallbackError),
        },
      }));
      return false;
    }
  };

  return {
    detailsById: {},
    loadingIds: [],
    busyActionById: {},
    errorById: {},
    noticeById: {},
    load: async (codingSessionId) => {
      if (get().detailsById[codingSessionId]) {
        return true;
      }
      return fetchDetail(codingSessionId, false, false);
    },
    refresh: (codingSessionId) => fetchDetail(codingSessionId, true, true),
    approvePlan: (codingSessionId) =>
      runAction(
        codingSessionId,
        "approve_plan",
        "计划已批准，coding session 将进入实现阶段。",
        "计划批准失败，请刷新后重试。",
        () => decideExternalCodingPlan(codingSessionId, "approved"),
      ),
    rejectPlan: (codingSessionId, feedback) =>
      runAction(
        codingSessionId,
        "reject_plan",
        "修改意见已发送。",
        "计划打回失败，请检查反馈后重试。",
        () => decideExternalCodingPlan(codingSessionId, "rejected", feedback),
      ),
    resume: (codingSessionId, instruction, phase) =>
      runAction(
        codingSessionId,
        "resume",
        "coding session 已继续。",
        "暂时无法继续 coding session，请稍后重试。",
        () => resumeExternalCodingSession(codingSessionId, { instruction, phase }),
      ),
    abandon: (codingSessionId, reason) =>
      runAction(
        codingSessionId,
        "abandon",
        "coding session 已放弃，记录仍会保留。",
        "放弃操作失败，请刷新后重试。",
        () => abandonExternalCodingSession(codingSessionId, reason),
      ),
    escalateToUser: (codingSessionId, reason) =>
      runAction(
        codingSessionId,
        "escalate_to_user",
        "已标记为等待用户处理。",
        "暂时无法更新等待状态，请稍后重试。",
        () => escalateExternalCodingSession(codingSessionId, reason),
      ),
    analyzeMerge: (codingSessionId, targetBranch, targetWorktreePath) =>
      runAction(
        codingSessionId,
        "merge_analysis",
        "合并风险分析已完成。",
        "合并风险分析失败，请检查目标后重试。",
        async () => {
          await analyzeExternalCodingMerge(codingSessionId, targetBranch, targetWorktreePath);
          return getExternalCodingSession(codingSessionId);
        },
      ),
    merge: (codingSessionId, mergeRecordId, agentDecision) =>
      runAction(
        codingSessionId,
        "merge",
        "合并操作已完成。",
        "合并未完成，请查看风险提示后重试。",
        async () => {
          const record = await mergeExternalCodingSession(
            codingSessionId,
            mergeRecordId,
            agentDecision,
          );
          const detail = await getExternalCodingSession(codingSessionId);
          if (record.status !== "merged") {
            set((state) => ({
              detailsById: { ...state.detailsById, [codingSessionId]: detail },
            }));
            throw new Error("merge did not reach merged status");
          }
          return detail;
        },
      ),
    planRollback: (codingSessionId, intentSummary) =>
      runAction(
        codingSessionId,
        "rollback_plan",
        "回滚方案已生成，请确认后执行。",
        "暂时无法生成回滚方案，请稍后重试。",
        async () => {
          await createRollbackPlan(codingSessionId, intentSummary);
          return getExternalCodingSession(codingSessionId);
        },
      ),
    confirmRollback: (codingSessionId, rollbackId) =>
      runAction(
        codingSessionId,
        "confirm_rollback",
        "回滚已执行。",
        "回滚未完成，请刷新状态后重试。",
        async () => {
          const decision = await confirmRollback(codingSessionId, rollbackId, "user");
          const detail = await getExternalCodingSession(codingSessionId);
          if (decision.status !== "applied") {
            set((state) => ({
              detailsById: { ...state.detailsById, [codingSessionId]: detail },
            }));
            throw new Error("rollback did not reach applied status");
          }
          return detail;
        },
      ),
    clearFeedback: (codingSessionId) =>
      set((state) => ({
        errorById: { ...state.errorById, [codingSessionId]: "" },
        noticeById: { ...state.noticeById, [codingSessionId]: "" },
      })),
    clear: () =>
      set({
        detailsById: {},
        loadingIds: [],
        busyActionById: {},
        errorById: {},
        noticeById: {},
      }),
    refreshIfCached: (codingSessionId) => {
      if (
        get().detailsById[codingSessionId] &&
        !get().busyActionById[codingSessionId]
      ) {
        void fetchDetail(codingSessionId, true, false);
      }
    },
  };
});
