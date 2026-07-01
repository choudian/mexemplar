import { create } from "zustand";

import { useToastStore } from "./toastStore";

import {
  getBrainZones,
  getZoneEntries,
  getBrainSegments,
  retryBrainSegment,
  deleteBrainEntry,
  editBrainEntry,
  getEntryEvolution,
  getSkillPool,
  removeSkillFromPool,
  SkillPoolRemovalConflict,
} from "../api/brain";
import { fetchExecutionReviews } from "../api/executionReview";
import {
  fetchImprovementProposals,
  approveProposal,
  rejectProposal,
} from "../api/improvementProposal";
import type { ImprovementProposalDto } from "../api/improvementProposal";
import type {
  AffectedSpecialist,
  BrainZoneSummary,
  BrainZone,
  BrainEntryStatus,
  BrainSegmentStatus,
  BrainMemoryEntry,
  BrainSegment,
  SkillPoolItem,
} from "../api/brain";
import type { ExecutionReviewDto } from "../api/executionReview";
import type { UiEvent } from "../api/client";
import { createDebouncedRefresh, toErrorMessage } from "./helpers";

let _entriesSeq = 0;
const scheduleBrainRefresh = createDebouncedRefresh();

export interface BrainState {
  zones: BrainZoneSummary[];
  entries: BrainMemoryEntry[];
  entriesTotal: number;
  activeZone: BrainZone | null;
  segments: BrainSegment[];
  segmentsTotal: number;
  executionReviews: ExecutionReviewDto[];
  skillPool: SkillPoolItem[];
  evolutionChain: BrainMemoryEntry[];
  loadingZones: boolean;
  loadingEntries: boolean;
  loadingSegments: boolean;
  loadingExecutionReviews: boolean;
  loadingSkillPool: boolean;
  loadingEvolution: boolean;
  lastError: string | null;
  pendingSkillRemoval: {
    toolId: string;
    affectedSpecialists: AffectedSpecialist[];
  } | null;
  improvementProposals: ImprovementProposalDto[];
  loadingImprovementProposals: boolean;

  loadZones: () => Promise<void>;
  loadEntries: (zone: BrainZone, options?: { limit?: number; offset?: number; status?: BrainEntryStatus }) => Promise<void>;
  loadSegments: (options?: { limit?: number; offset?: number; status?: BrainSegmentStatus | "all" }) => Promise<void>;
  loadExecutionReviews: () => Promise<void>;
  loadSkillPool: () => Promise<void>;
  setActiveZone: (zone: BrainZone) => void;
  deleteEntry: (entryId: string) => Promise<void>;
  editEntry: (entryId: string, content: string, scope?: string) => Promise<void>;
  retrySegment: (segmentId: string) => Promise<void>;
  loadEvolution: (entryId: string) => Promise<void>;
  removeSkill: (toolId: string, force?: boolean) => Promise<void>;
  clearPendingSkillRemoval: () => void;
  loadImprovementProposals: (status?: string) => Promise<void>;
  approveImprovementProposal: (id: string, supplement?: string) => Promise<boolean>;
  rejectImprovementProposal: (id: string) => Promise<boolean>;
  applyEvent: (event: UiEvent) => void;
}

export const useBrainStore = create<BrainState>((set, get) => ({
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

  loadZones: async () => {
    set({ loadingZones: true, lastError: null });
    try {
      const response = await getBrainZones();
      set({ zones: response.zones ?? [] });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载分区信息。") });
    } finally {
      set({ loadingZones: false });
    }
  },

  loadEntries: async (zone, options = {}) => {
    const seq = ++_entriesSeq;
    set({ loadingEntries: true, lastError: null, activeZone: zone });
    try {
      const response = await getZoneEntries(zone, options);
      if (_entriesSeq !== seq) return;
      set({ entries: response.items, entriesTotal: response.total });
    } catch (error) {
      if (_entriesSeq !== seq) return;
      set({ lastError: toErrorMessage(error, "无法加载条目列表。") });
    } finally {
      if (_entriesSeq === seq) {
        set({ loadingEntries: false });
      }
    }
  },

  loadSegments: async (options = {}) => {
    set({ loadingSegments: true, lastError: null });
    try {
      const response = await getBrainSegments(options);
      set({ segments: response.items, segmentsTotal: response.total });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载 Segment 列表。") });
    } finally {
      set({ loadingSegments: false });
    }
  },

  loadExecutionReviews: async () => {
    set({ loadingExecutionReviews: true, lastError: null });
    try {
      const reviews = await fetchExecutionReviews(50);
      set({ executionReviews: reviews });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载执行复盘。") });
    } finally {
      set({ loadingExecutionReviews: false });
    }
  },

  loadSkillPool: async () => {
    set({ loadingSkillPool: true, lastError: null });
    try {
      const response = await getSkillPool();
      set({ skillPool: response.skills ?? [] });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载工具池。") });
    } finally {
      set({ loadingSkillPool: false });
    }
  },

  setActiveZone: (zone) => {
    set({ activeZone: zone });
  },

  deleteEntry: async (entryId) => {
    set({ lastError: null });
    try {
      await deleteBrainEntry(entryId);
      const { activeZone } = get();
      if (activeZone) {
        await get().loadEntries(activeZone);
      }
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法删除条目。") });
    }
  },

  editEntry: async (entryId, content, scope) => {
    set({ lastError: null });
    try {
      await editBrainEntry(entryId, { content, scope });
      const { activeZone } = get();
      if (activeZone) {
        await get().loadEntries(activeZone);
      }
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法编辑条目。") });
    }
  },

  retrySegment: async (segmentId) => {
    set({ lastError: null });
    try {
      await retryBrainSegment(segmentId);
      await get().loadSegments();
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法重试 Segment。") });
    }
  },

  loadEvolution: async (entryId) => {
    set({ loadingEvolution: true, lastError: null });
    try {
      const response = await getEntryEvolution(entryId);
      set({ evolutionChain: response.chain ?? [] });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载演化链。") });
    } finally {
      set({ loadingEvolution: false });
    }
  },

  removeSkill: async (toolId, force = false) => {
    set({ lastError: null, pendingSkillRemoval: null });
    try {
      await removeSkillFromPool(toolId, { force });
      set({ pendingSkillRemoval: null });
      await get().loadSkillPool();
    } catch (error) {
      if (error instanceof SkillPoolRemovalConflict) {
        set({
          pendingSkillRemoval: {
            toolId: error.toolId,
            affectedSpecialists: error.affectedSpecialists,
          },
        });
        return;
      }
      set({ lastError: toErrorMessage(error, "无法移除工具。") });
    }
  },

  clearPendingSkillRemoval: () => set({ pendingSkillRemoval: null }),

  loadImprovementProposals: async (status?: string) => {
    set({ loadingImprovementProposals: true, lastError: null });
    try {
      const proposals = await fetchImprovementProposals(status);
      set({ improvementProposals: proposals });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载改进提案。") });
    } finally {
      set({ loadingImprovementProposals: false });
    }
  },

  approveImprovementProposal: async (id: string, supplement = "") => {
    set({ lastError: null });
    try {
      const result = await approveProposal(id, supplement);
      if (!result.accepted) {
        // CAS miss：提案已被并发改动（如已批准），本次点击是 no-op，必须告知用户。
        useToastStore.getState().notifyError("该提案已被处理，无法重复批准。");
      }
      await get().loadImprovementProposals();
      return result.accepted;
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法批准提案。") });
      return false;
    }
  },

  rejectImprovementProposal: async (id: string) => {
    set({ lastError: null });
    try {
      const result = await rejectProposal(id);
      if (!result.accepted) {
        const message =
          result.reason === "cleanup_failed"
            ? "清理改进工作区失败，提案暂未弃用。稍后可重试。"
            : "该提案当前状态不允许拒绝。";
        useToastStore.getState().notifyError(message);
      }
      await get().loadImprovementProposals();
      return result.accepted;
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法拒绝提案。") });
      return false;
    }
  },

  applyEvent: (event) => {
    if (event.type === "brain_zone_changed") {
      scheduleBrainRefresh(async () => {
        const activeZone = get().activeZone;
        await Promise.all([
          get().loadZones(),
          activeZone ? get().loadEntries(activeZone) : Promise.resolve(),
        ]);
      });
    }
    if (event.type === "brain_context_ready") {
      void get().loadZones();
    }
    if (event.type === "tools.changed") {
      void get().loadSkillPool();
    }
    if (event.type === "improvement_proposal.changed") {
      void get().loadImprovementProposals();
    }
  },
}));
