import { create } from "zustand";

import {
  createComposition,
  generateApplicability as requestApplicability,
  listCompositions,
  publishComposition,
  recommendOrder as requestRecommendedOrder,
  startCompositionTrial,
  updateComposition,
} from "../api/compositions";
import type { CompositionInput, CompositionMember, CompositionMode, CompositionSummary } from "../api/compositions";
import type { UiEvent } from "../api/client";
import { createDebouncedRefresh, toErrorMessage } from "./helpers";

const emptyDraft: CompositionInput = {
  name: "",
  description: "",
  mode: "range",
  applicability: "",
  members: [],
};

export type CompositionsState = {
  hydrated: boolean;
  items: CompositionSummary[];
  selectedId: string | null;
  draft: CompositionInput;
  busy: boolean;
  lastError: string | null;
  load: () => Promise<void>;
  select: (compositionId: string | null) => void;
  setDraftField: <K extends keyof CompositionInput>(key: K, value: CompositionInput[K]) => void;
  setMode: (mode: CompositionMode) => void;
  addMember: (member: CompositionMember) => void;
  moveMember: (toolId: string, direction: "up" | "down") => void;
  removeMember: (toolId: string) => void;
  generateApplicability: () => Promise<void>;
  recommendOrder: () => Promise<void>;
  save: () => Promise<void>;
  publish: (compositionId?: string) => Promise<void>;
  startTrial: (compositionId?: string) => Promise<void>;
  applyEvent: (event: UiEvent) => void;
  markHydrated: () => void;
  setError: (message: string | null) => void;
};

function toDraft(item: CompositionSummary): CompositionInput {
  return {
    name: item.name,
    description: item.description,
    mode: item.mode,
    applicability: item.applicability,
    members: item.members,
  };
}

const scheduleRefresh = createDebouncedRefresh();

export const useCompositionsStore = create<CompositionsState>((set, get) => ({
  hydrated: false,
  items: [],
  selectedId: null,
  draft: emptyDraft,
  busy: false,
  lastError: null,
  markHydrated: () => set({ hydrated: true }),
  setError: (message) => set({ lastError: message }),
  load: async () => {
    set({ busy: true, lastError: null });
    try {
      set({ items: await listCompositions(), hydrated: true });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载技能组合。") });
    } finally {
      set({ busy: false });
    }
  },
  select: (compositionId) => {
    const item = get().items.find((composition) => composition.compositionId === compositionId);
    set({ selectedId: compositionId, draft: item ? toDraft(item) : emptyDraft });
  },
  setDraftField: (key, value) => set({ draft: { ...get().draft, [key]: value } }),
  setMode: (mode) => {
    const members = get().draft.members.map((member, index) => ({
      ...member,
      executionOrder: mode === "ordered" ? index + 1 : null,
    }));
    set({ draft: { ...get().draft, mode, members } });
  },
  addMember: (member) => {
    if (get().draft.members.some((item) => item.toolId === member.toolId)) return;
    const members = [
      ...get().draft.members,
      {
        ...member,
        selectedOrder: get().draft.members.length + 1,
        executionOrder: get().draft.mode === "ordered" ? get().draft.members.length + 1 : null,
      },
    ];
    set({ draft: { ...get().draft, members } });
  },
  moveMember: (toolId, direction) => {
    const members = [...get().draft.members];
    const currentIndex = members.findIndex((member) => member.toolId === toolId);
    const nextIndex = direction === "up" ? currentIndex - 1 : currentIndex + 1;
    if (currentIndex < 0 || nextIndex < 0 || nextIndex >= members.length) return;
    const [member] = members.splice(currentIndex, 1);
    members.splice(nextIndex, 0, member);
    set({
      draft: {
        ...get().draft,
        members: members.map((item, index) => ({
          ...item,
          selectedOrder: index + 1,
          executionOrder: get().draft.mode === "ordered" ? index + 1 : null,
        })),
      },
    });
  },
  removeMember: (toolId) => {
    const draft = get().draft;
    const members: CompositionMember[] = [];
    for (const member of draft.members) {
      if (member.toolId === toolId) continue;
      const order = members.length + 1;
      members.push({
        ...member,
        selectedOrder: order,
        executionOrder: draft.mode === "ordered" ? order : null,
      });
    }
    set({ draft: { ...draft, members } });
  },
  generateApplicability: async () => {
    set({ busy: true, lastError: null });
    try {
      const response = await requestApplicability(get().selectedId ?? "draft", get().draft);
      set({ draft: { ...get().draft, applicability: response.applicability } });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法生成适用场景。") });
    } finally {
      set({ busy: false });
    }
  },
  recommendOrder: async () => {
    set({ busy: true, lastError: null });
    try {
      const response = await requestRecommendedOrder(get().selectedId ?? "draft", get().draft);
      if (response.members.length > 0) {
        set({ draft: { ...get().draft, members: response.members } });
      }
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法推荐顺序。") });
    } finally {
      set({ busy: false });
    }
  },
  save: async () => {
    set({ busy: true, lastError: null });
    try {
      const selectedId = get().selectedId;
      const saved = selectedId
        ? await updateComposition(selectedId, get().draft)
        : await createComposition(get().draft);
      const items = selectedId
        ? get().items.map((item) => (item.compositionId === selectedId ? saved : item))
        : [saved, ...get().items];
      set({ items, selectedId: saved.compositionId, draft: toDraft(saved) });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法保存技能组合。") });
    } finally {
      set({ busy: false });
    }
  },
  publish: async (compositionId = get().selectedId ?? "") => {
    if (!compositionId) return;
    const published = await publishComposition(compositionId);
    set({
      items: get().items.map((item) => (item.compositionId === compositionId ? published : item)),
      selectedId: published.compositionId,
      draft: toDraft(published),
    });
  },
  startTrial: async (compositionId = get().selectedId ?? "") => {
    if (!compositionId) return;
    await startCompositionTrial(compositionId);
  },
  applyEvent: (event) => {
    if (event.type === "compositions.changed") {
      scheduleRefresh(() => get().load());
    }
  },
}));
