import { create } from "zustand";

import {
  createSpecialist,
  deleteSpecialist,
  getSpecialistVersions,
  listSpecialists,
  updateSpecialist,
} from "../api/brain";
import type {
  BrainSpecialist,
  SpecialistVersion,
} from "../api/brain";
import type { UiEvent } from "../api/client";
import { toErrorMessage } from "./helpers";

export interface SpecialistDraft {
  specialist_id: string | null;
  name: string;
  description: string;
  role_definition: string;
  tool_whitelist: string[];
  change_reason: string;
}

export interface RecruitmentToast {
  specialistId: string;
  name: string;
  reason: string;
  managementUrl: string;
}

export interface SpecialistState {
  items: BrainSpecialist[];
  total: number;
  selectedId: string | null;
  draft: SpecialistDraft;
  versions: SpecialistVersion[];
  loading: boolean;
  loadingVersions: boolean;
  saving: boolean;
  lastError: string | null;
  recruitmentToast: RecruitmentToast | null;

  load: () => Promise<void>;
  select: (specialistId: string | null) => void;
  setDraftField: <K extends keyof SpecialistDraft>(field: K, value: SpecialistDraft[K]) => void;
  toggleWhitelist: (toolId: string) => void;
  saveDraft: () => Promise<void>;
  deleteById: (specialistId: string) => Promise<void>;
  loadVersions: (specialistId: string) => Promise<void>;
  applyEvent: (event: UiEvent) => void;
  dismissRecruitmentToast: () => void;
}

const EMPTY_DRAFT: SpecialistDraft = {
  specialist_id: null,
  name: "",
  description: "",
  role_definition: "",
  tool_whitelist: [],
  change_reason: "",
};

function draftFromSpecialist(item: BrainSpecialist): SpecialistDraft {
  return {
    specialist_id: item.specialist_id,
    name: item.name,
    description: item.description,
    role_definition: item.role_definition,
    tool_whitelist: [...item.tool_whitelist],
    change_reason: "",
  };
}

export const useSpecialistStore = create<SpecialistState>((set, get) => ({
  items: [],
  total: 0,
  selectedId: null,
  draft: EMPTY_DRAFT,
  versions: [],
  loading: false,
  loadingVersions: false,
  saving: false,
  lastError: null,
  recruitmentToast: null,

  load: async () => {
    set({ loading: true, lastError: null });
    try {
      const response = await listSpecialists();
      set((state) => {
        const items = response.items ?? [];
        const selected = state.selectedId
          ? items.find((item) => item.specialist_id === state.selectedId)
          : null;
        if (state.selectedId && !selected) {
          return {
            items,
            total: response.total,
            selectedId: null,
            draft: { ...EMPTY_DRAFT },
            versions: [],
            loadingVersions: false,
          };
        }
        return {
          items,
          total: response.total,
          draft: selected ? draftFromSpecialist(selected) : state.draft,
        };
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载专员列表。") });
    } finally {
      set({ loading: false });
    }
  },

  select: (specialistId) => {
    if (!specialistId) {
      set({ selectedId: null, draft: { ...EMPTY_DRAFT }, versions: [], loadingVersions: false });
      return;
    }
    const item = get().items.find((candidate) => candidate.specialist_id === specialistId);
    set({
      selectedId: specialistId,
      draft: item ? draftFromSpecialist(item) : { ...EMPTY_DRAFT, specialist_id: specialistId },
    });
    void get().loadVersions(specialistId);
  },

  setDraftField: (field, value) => {
    set((state) => ({ draft: { ...state.draft, [field]: value } }));
  },

  toggleWhitelist: (toolId) => {
    set((state) => {
      const exists = state.draft.tool_whitelist.includes(toolId);
      return {
        draft: {
          ...state.draft,
          tool_whitelist: exists
            ? state.draft.tool_whitelist.filter((item) => item !== toolId)
            : [...state.draft.tool_whitelist, toolId],
        },
      };
    });
  },

  saveDraft: async () => {
    const draft = get().draft;
    set({ saving: true, lastError: null });
    try {
      if (draft.specialist_id) {
        await updateSpecialist(draft.specialist_id, {
          name: draft.name,
          description: draft.description,
          role_definition: draft.role_definition,
          tool_whitelist: draft.tool_whitelist,
          change_reason: draft.change_reason || "通过管理界面更新",
        });
      } else {
        const created = await createSpecialist({
          name: draft.name,
          description: draft.description,
          role_definition: draft.role_definition,
          tool_whitelist: draft.tool_whitelist,
        });
        set({ selectedId: created.specialist_id, draft: draftFromSpecialist(created) });
      }
      await get().load();
      const selectedId = get().selectedId;
      if (selectedId) {
        await get().loadVersions(selectedId);
      }
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法保存专员。") });
    } finally {
      set({ saving: false });
    }
  },

  deleteById: async (specialistId) => {
    set({ lastError: null });
    try {
      await deleteSpecialist(specialistId);
      set({ selectedId: null, draft: { ...EMPTY_DRAFT }, versions: [], loadingVersions: false });
      await get().load();
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法删除专员。") });
    }
  },

  loadVersions: async (specialistId) => {
    set({ loadingVersions: true, lastError: null });
    try {
      const response = await getSpecialistVersions(specialistId);
      if (get().selectedId === specialistId) {
        set({ versions: response.items ?? [] });
      }
    } catch (error) {
      if (get().selectedId === specialistId) {
        set({ lastError: toErrorMessage(error, "无法加载版本历史。") });
      }
    } finally {
      if (get().selectedId === specialistId) {
        set({ loadingVersions: false });
      }
    }
  },

  applyEvent: (event) => {
    if (event.type === "brain_specialist_recruited") {
      set({
        recruitmentToast: {
          specialistId: String(event.payload.specialistId ?? ""),
          name: String(event.payload.name ?? "新专员"),
          reason: String(event.payload.reason ?? ""),
          managementUrl: String(event.payload.managementUrl ?? "/brain/specialists"),
        },
      });
      void get().load();
      return;
    }
    if (event.type === "brain_specialist_changed") {
      void (async () => {
        await get().load();
        const selectedId = get().selectedId;
        if (selectedId) {
          await get().loadVersions(selectedId);
        }
      })();
    }
  },

  dismissRecruitmentToast: () => {
    set({ recruitmentToast: null });
  },
}));
