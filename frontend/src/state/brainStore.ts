import { create } from "zustand";

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
  skillPool: SkillPoolItem[];
  evolutionChain: BrainMemoryEntry[];
  loadingZones: boolean;
  loadingEntries: boolean;
  loadingSegments: boolean;
  loadingSkillPool: boolean;
  loadingEvolution: boolean;
  lastError: string | null;
  pendingSkillRemoval: {
    toolId: string;
    affectedSpecialists: AffectedSpecialist[];
  } | null;

  loadZones: () => Promise<void>;
  loadEntries: (zone: BrainZone, options?: { limit?: number; offset?: number; status?: BrainEntryStatus }) => Promise<void>;
  loadSegments: (options?: { limit?: number; offset?: number; status?: BrainSegmentStatus | "all" }) => Promise<void>;
  loadSkillPool: () => Promise<void>;
  setActiveZone: (zone: BrainZone) => void;
  deleteEntry: (entryId: string) => Promise<void>;
  editEntry: (entryId: string, content: string, scope?: string) => Promise<void>;
  retrySegment: (segmentId: string) => Promise<void>;
  loadEvolution: (entryId: string) => Promise<void>;
  removeSkill: (toolId: string, force?: boolean) => Promise<void>;
  clearPendingSkillRemoval: () => void;
  applyEvent: (event: UiEvent) => void;
}

export const useBrainStore = create<BrainState>((set, get) => ({
  zones: [],
  entries: [],
  entriesTotal: 0,
  activeZone: null,
  segments: [],
  segmentsTotal: 0,
  skillPool: [],
  evolutionChain: [],
  loadingZones: false,
  loadingEntries: false,
  loadingSegments: false,
  loadingSkillPool: false,
  loadingEvolution: false,
  lastError: null,
  pendingSkillRemoval: null,

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
  },
}));
