import { create } from "zustand";

import {
  discoverGithubSkills,
  installStoreSkill,
  listInstalledExternalSkills,
  previewStoreSkill,
  searchStoreSkills,
} from "../api/skillStore";
import type {
  DiscoveredGithubSkill,
  InstalledExternalSkill,
  StoreSkillPreview,
  StoreSkillSummary,
} from "../api/skillStore";
import { toErrorMessage } from "./helpers";

export type SkillStoreState = {
  items: StoreSkillSummary[];
  sourceAvailable: boolean;
  sourceMessage: string | null;
  query: string;
  loading: boolean;
  installed: InstalledExternalSkill[];
  githubSkills: DiscoveredGithubSkill[];
  githubMessage: string | null;
  discoveringGithub: boolean;
  preview: StoreSkillPreview | null;
  previewLoading: boolean;
  installing: boolean;
  lastError: string | null;

  search: (query: string) => Promise<void>;
  loadInstalled: () => Promise<void>;
  discoverGithub: (repo: string) => Promise<void>;
  clearGithubResults: () => void;
  openPreview: (sourceType: "skills_sh" | "github", sourceRef: string) => Promise<void>;
  closePreview: () => void;
  install: () => Promise<boolean>;
  uninstall: (installId: string) => Promise<void>;
};

export const useSkillStoreStore = create<SkillStoreState>((set, get) => ({
  items: [],
  sourceAvailable: true,
  sourceMessage: null,
  query: "",
  loading: false,
  installed: [],
  githubSkills: [],
  githubMessage: null,
  discoveringGithub: false,
  preview: null,
  previewLoading: false,
  installing: false,
  lastError: null,

  search: async (query: string) => {
    set({ query, loading: true, lastError: null });
    try {
      const response = await searchStoreSkills(query);
      set({
        items: response.items,
        sourceAvailable: response.sourceAvailable,
        sourceMessage: response.message,
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载技能市场。") });
    } finally {
      set({ loading: false });
    }
  },

  loadInstalled: async () => {
    try {
      const response = await listInstalledExternalSkills();
      set({ installed: response.items });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载已安装技能。") });
    }
  },

  discoverGithub: async (repo: string) => {
    set({ discoveringGithub: true, githubMessage: null, lastError: null });
    try {
      const response = await discoverGithubSkills(repo);
      set({ githubSkills: response.skills, githubMessage: response.message });
    } catch (error) {
      set({
        githubSkills: [],
        lastError: toErrorMessage(error, "无法从该仓库发现技能。"),
      });
    } finally {
      set({ discoveringGithub: false });
    }
  },

  clearGithubResults: () => set({ githubSkills: [], githubMessage: null }),

  openPreview: async (sourceType, sourceRef) => {
    set({ previewLoading: true, lastError: null });
    try {
      const preview = await previewStoreSkill(sourceType, sourceRef);
      set({ preview });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载技能预览。") });
    } finally {
      set({ previewLoading: false });
    }
  },

  closePreview: () => set({ preview: null }),

  install: async () => {
    const preview = get().preview;
    if (!preview || get().installing) return false;
    set({ installing: true, lastError: null });
    try {
      await installStoreSkill(preview.sourceType, preview.sourceRef);
      set({ preview: null });
      // 刷新已装列表与当前搜索结果的 installed 标识
      await get().loadInstalled();
      await get().search(get().query);
      return true;
    } catch (error) {
      set({ lastError: toErrorMessage(error, "安装失败。") });
      return false;
    } finally {
      set({ installing: false });
    }
  },

  uninstall: async (installId: string) => {
    set({ lastError: null });
    try {
      await uninstallExternalSkill(installId);
      await get().loadInstalled();
      await get().search(get().query);
    } catch (error) {
      set({ lastError: toErrorMessage(error, "卸载失败。") });
    }
  },
}));
