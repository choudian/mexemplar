import { create } from "zustand";

import {
  deleteSkill,
  dismissFailure,
  getSkills,
  retryFailure,
  updateSkillMetadata,
} from "../api/skills";
import { SKILL_CATEGORIES } from "../api/skills";
import type { SkillCategory, SkillSummary } from "../api/skills";
import type { UiEvent } from "../api/client";
import { useShellStore } from "./shellStore";
import { useTeachingStore } from "./teachingStore";
import { createDebouncedRefresh, toErrorMessage } from "./helpers";

type CategoryResult = { category: SkillCategory; items: SkillSummary[]; count: number };

export type SkillsState = {
  hydrated: boolean;
  activeCategory: SkillCategory;
  query: string;
  categories: Record<SkillCategory, SkillSummary[]>;
  counts: Record<SkillCategory, number>;
  busy: boolean;
  lastError: string | null;
  setCategory: (category: SkillCategory) => void;
  setQuery: (query: string) => void;
  loadAllCategories: () => Promise<void>;
  loadCategory: (category?: SkillCategory) => Promise<void>;
  openTrial: (toolId: string) => void;
  updateMetadata: (toolId: string, name: string, description: string) => Promise<void>;
  deleteSkill: (toolId: string) => Promise<void>;
  retryFailure: (workflowId: string) => Promise<void>;
  dismissFailure: (workflowId: string) => Promise<void>;
  applyEvent: (event: UiEvent) => void;
  markHydrated: () => void;
  setError: (message: string | null) => void;
};

const scheduleRefresh = createDebouncedRefresh();

function syncNavigationCounts(counts: Record<SkillCategory, number>): void {
  const nav = useShellStore.getState().navigation;
  if (
    nav.pendingSkillCount === counts.pending &&
    nav.publishedSkillCount === counts.published &&
    nav.failureCount === counts.failed
  ) {
    return;
  }
  useShellStore.setState({
    navigation: {
      ...nav,
      pendingSkillCount: counts.pending,
      publishedSkillCount: counts.published,
      failureCount: counts.failed,
    },
  });
}

function applyResults(
  set: (partial: Partial<SkillsState>) => void,
  get: () => SkillsState,
  results: CategoryResult[],
): void {
  const nextCategories = { ...get().categories };
  const nextCounts = { ...get().counts };
  for (const { category, items, count } of results) {
    nextCategories[category] = items;
    nextCounts[category] = count;
  }
  set({ hydrated: true, categories: nextCategories, counts: nextCounts });
  syncNavigationCounts(nextCounts);
}

async function withBusy(
  set: (partial: Partial<SkillsState>) => void,
  fn: () => Promise<CategoryResult[]>,
): Promise<CategoryResult[] | null> {
  set({ busy: true, lastError: null });
  try {
    return await fn();
  } catch (error) {
    set({ lastError: toErrorMessage(error, "无法加载技能列表。") });
    return null;
  } finally {
    set({ busy: false });
  }
}

export const useSkillsStore = create<SkillsState>((set, get) => ({
  hydrated: false,
  activeCategory: "pending",
  query: "",
  categories: { pending: [], published: [], failed: [] },
  counts: { pending: 0, published: 0, failed: 0 },
  busy: false,
  lastError: null,
  setCategory: (category) => set({ activeCategory: category }),
  setQuery: (query) => set({ query }),
  markHydrated: () => set({ hydrated: true }),
  setError: (error) => set({ lastError: error }),
  loadAllCategories: async () => {
    const results = await withBusy(set, () =>
      Promise.all(
        SKILL_CATEGORIES.map(async (category) => {
          const response = await getSkills(category);
          return { category, items: response.items ?? [], count: response.count ?? 0 };
        }),
      ),
    );
    if (results) applyResults(set, get, results);
  },
  loadCategory: async (category = get().activeCategory) => {
    const results = await withBusy(set, async () => {
      const response = await getSkills(category);
      return [{ category, items: response.items ?? [], count: response.count ?? 0 }];
    });
    if (results) applyResults(set, get, results);
  },
  openTrial: (toolId) => {
    useTeachingStore.getState().openSkillTrial(toolId);
  },
  updateMetadata: async (toolId, name, description) => {
    await updateSkillMetadata(toolId, { name, description });
    await get().loadCategory("published");
  },
  deleteSkill: async (toolId) => {
    try {
      await deleteSkill(toolId);
    } catch (error) {
      set({ lastError: toErrorMessage(error, "删除技能失败。") });
      return;
    }
    const prev = get();
    const nextCategories = { ...prev.categories };
    const nextCounts = { ...prev.counts };
    for (const cat of SKILL_CATEGORIES) {
      const filtered = prev.categories[cat].filter((s) => s.toolId !== toolId);
      if (filtered.length !== prev.categories[cat].length) {
        nextCategories[cat] = filtered;
        nextCounts[cat] = prev.counts[cat] - 1;
        break;
      }
    }
    set({ categories: nextCategories, counts: nextCounts });
    syncNavigationCounts(nextCounts);
  },
  retryFailure: async (workflowId) => {
    set({ busy: true, lastError: null });
    try {
      await retryFailure(workflowId);
    } catch (error) {
      set({ busy: false, lastError: toErrorMessage(error, "重试失败。") });
      return;
    }
    await get().loadAllCategories();
  },
  dismissFailure: async (workflowId) => {
    try {
      await dismissFailure(workflowId);
    } catch (error) {
      set({ lastError: toErrorMessage(error, "忽略失败记录失败。") });
      return;
    }
    const prev = get();
    const nextCategories = {
      ...prev.categories,
      failed: prev.categories.failed.filter((skill) => skill.workflowId !== workflowId),
    };
    const nextCounts = { ...prev.counts, failed: prev.counts.failed - 1 };
    set({ categories: nextCategories, counts: nextCounts });
    syncNavigationCounts(nextCounts);
  },
  applyEvent: (event) => {
    if (event.type === "skills.changed") {
      scheduleRefresh(() => get().loadAllCategories());
    }
  },
}));
