import { create } from "zustand";

import {
  deleteSkill,
  dismissFailure,
  getSkills,
  retryFailure,
  startSkillTrial,
  updateSkillMetadata,
} from "../api/skills";
import type { SkillCategory, SkillSummary } from "../api/skills";
import type { UiEvent } from "../api/client";

export type SkillsState = {
  hydrated: boolean;
  activeCategory: SkillCategory;
  query: string;
  categories: Record<SkillCategory, SkillSummary[]>;
  busy: boolean;
  lastError: string | null;
  setCategory: (category: SkillCategory) => void;
  setQuery: (query: string) => void;
  loadCategory: (category?: SkillCategory) => Promise<void>;
  runTrial: (toolId: string) => Promise<void>;
  updateMetadata: (toolId: string, name: string, description: string) => Promise<void>;
  deleteSkill: (toolId: string) => Promise<void>;
  retryFailure: (workflowId: string) => Promise<void>;
  dismissFailure: (workflowId: string) => Promise<void>;
  applyEvent: (event: UiEvent) => void;
  markHydrated: () => void;
  setError: (message: string | null) => void;
};

function message(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export const useSkillsStore = create<SkillsState>((set, get) => ({
  hydrated: false,
  activeCategory: "pending",
  query: "",
  categories: { pending: [], published: [], failed: [] },
  busy: false,
  lastError: null,
  setCategory: (category) => set({ activeCategory: category }),
  setQuery: (query) => set({ query }),
  markHydrated: () => set({ hydrated: true }),
  setError: (error) => set({ lastError: error }),
  loadCategory: async (category = get().activeCategory) => {
    set({ busy: true, lastError: null });
    try {
      const response = await getSkills(category);
      set({
        hydrated: true,
        categories: { ...get().categories, [category]: response.items ?? [] },
      });
    } catch (error) {
      set({ lastError: message(error, "无法加载技能列表。") });
    } finally {
      set({ busy: false });
    }
  },
  runTrial: async (toolId) => {
    await startSkillTrial(toolId);
  },
  updateMetadata: async (toolId, name, description) => {
    await updateSkillMetadata(toolId, { name, description });
    await get().loadCategory("published");
  },
  deleteSkill: async (toolId) => {
    await deleteSkill(toolId);
    set({
      categories: {
        ...get().categories,
        published: get().categories.published.filter((skill) => skill.toolId !== toolId),
        pending: get().categories.pending.filter((skill) => skill.toolId !== toolId),
      },
    });
  },
  retryFailure: async (workflowId) => {
    await retryFailure(workflowId);
    await get().loadCategory("failed");
  },
  dismissFailure: async (workflowId) => {
    await dismissFailure(workflowId);
    set({
      categories: {
        ...get().categories,
        failed: get().categories.failed.filter((skill) => skill.workflowId !== workflowId),
      },
    });
  },
  applyEvent: (event) => {
    if (event.type === "skills.changed") {
      void get().loadCategory(get().activeCategory);
    }
  },
}));
