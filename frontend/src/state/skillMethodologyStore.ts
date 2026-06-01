import { create } from "zustand";

import {
  getEntityEquipment,
  getMethodologyBootstrapStatus,
  getMethodologySkill,
  getMethodologySkillEquipmentAudit,
  getMethodologySkillHistory,
  listMethodologySkills,
  softDeleteMethodologySkill,
  updateEntityEquipment,
  updateMethodologySkill,
} from "../api/skillsMethodology";
import type {
  BootstrapStatusResponse,
  EntityEquipmentResponse,
  SkillDetail,
  SkillEquipmentAuditResponse,
  SkillFilterKey,
  SkillHistoryResponse,
  SkillSortKey,
  SkillMethodologySummary,
  TokenBudgetThresholds,
} from "../api/skillsMethodology";
import type { UiEvent } from "../api/client";
import type { SkillChangedEvent } from "../api/uiEvents";
import { createDebouncedRefresh, toErrorMessage } from "./helpers";

export interface SkillEditDraft {
  skill_id: string | null;
  name: string;
  description: string;
  trigger_conditions: string[];
  required_tools: string[];
  body_markdown: string;
  change_reason: string;
}

export interface BootstrapWarning {
  seedFilePath: string;
  lastSeedCheckAt: string | null;
}

interface SkillMethodologyState {
  hydrated: boolean;
  items: SkillMethodologySummary[];
  selectedSkillId: string | null;
  selectedDetail: SkillDetail | null;
  history: SkillHistoryResponse | null;
  equipmentAudit: SkillEquipmentAuditResponse | null;
  equipmentByEntity: Record<string, EntityEquipmentResponse>;
  tokenBudgetThresholds: TokenBudgetThresholds | null;
  sortKey: SkillSortKey;
  filterKey: SkillFilterKey;
  editDraft: SkillEditDraft;
  unreadBadgeCount: number;
  loading: boolean;
  loadingDetail: boolean;
  saving: boolean;
  lastError: string | null;
  bootstrapWarning: BootstrapWarning | null;

  load: () => Promise<void>;
  loadBootstrapStatus: () => Promise<void>;
  selectSkill: (skillId: string | null) => Promise<void>;
  setSortKey: (sortKey: SkillSortKey) => void;
  setFilterKey: (filterKey: SkillFilterKey) => void;
  setDraftField: <K extends keyof SkillEditDraft>(field: K, value: SkillEditDraft[K]) => void;
  saveDraft: () => Promise<boolean>;
  softDeleteSelected: () => Promise<boolean>;
  loadEquipment: (entityId: string) => Promise<void>;
  saveEquipment: (entityId: string, skillIds: string[]) => Promise<boolean>;
  dismissUnread: () => void;
  dismissBootstrapWarning: () => void;
  applyEvent: (event: UiEvent) => void;
}

const EMPTY_DRAFT: SkillEditDraft = {
  skill_id: null,
  name: "",
  description: "",
  trigger_conditions: [""],
  required_tools: [],
  body_markdown: "",
  change_reason: "",
};

const scheduleRefresh = createDebouncedRefresh();

function draftFromDetail(detail: SkillDetail): SkillEditDraft {
  return {
    skill_id: detail.skill_id,
    name: detail.name,
    description: detail.description,
    trigger_conditions: detail.trigger_conditions.length > 0 ? [...detail.trigger_conditions] : [""],
    required_tools: [...detail.required_tools],
    body_markdown: detail.body_markdown,
    change_reason: "",
  };
}

function normalizeList(values: string[]): string[] {
  return values.map((value) => value.trim()).filter(Boolean);
}

function skillEventId(payload: SkillChangedEvent["payload"]): string | null {
  const value = payload.skillId ?? payload.newSkillId ?? payload.chainRootId;
  return typeof value === "string" && value.trim() ? value : null;
}

function bootstrapWarningFromEvent(payload: SkillChangedEvent["payload"]): BootstrapWarning {
  const info = payload.bootstrapFallbackInfo;
  return {
    seedFilePath: String(info?.seedFilePath ?? ""),
    lastSeedCheckAt: null,
  };
}

export function estimateEquipmentTokens(items: Array<Pick<SkillMethodologySummary, "skill_id" | "name" | "description" | "trigger_conditions">>): number {
  const text = items.flatMap((item) => [
    item.skill_id,
    item.name,
    item.description,
    ...item.trigger_conditions,
  ]).join("\n");
  return Math.ceil((text.length / 4) * 1.2);
}

export const useSkillMethodologyStore = create<SkillMethodologyState>((set, get) => ({
  hydrated: false,
  items: [],
  selectedSkillId: null,
  selectedDetail: null,
  history: null,
  equipmentAudit: null,
  equipmentByEntity: {},
  tokenBudgetThresholds: null,
  sortKey: "recently_changed",
  filterKey: "all",
  editDraft: { ...EMPTY_DRAFT },
  unreadBadgeCount: 0,
  loading: false,
  loadingDetail: false,
  saving: false,
  lastError: null,
  bootstrapWarning: null,

  load: async () => {
    set({ loading: true, lastError: null });
    try {
      const response = await listMethodologySkills();
      set({ hydrated: true, items: response.items ?? [] });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载方法论列表。") });
    } finally {
      set({ loading: false });
    }
  },

  loadBootstrapStatus: async () => {
    try {
      const status: BootstrapStatusResponse = await getMethodologyBootstrapStatus();
      set({
        bootstrapWarning: status.fallback_used
          ? {
              seedFilePath: status.seed_file_path,
              lastSeedCheckAt: status.last_seed_check_at,
            }
          : null,
      });
    } catch (err) {
      // Bootstrap warning is advisory; app startup continues if this endpoint is unavailable.
      console.warn("[skillMethodologyStore] loadBootstrapStatus failed:", err);
    }
  },

  selectSkill: async (skillId) => {
    if (!skillId) {
      set({
        selectedSkillId: null,
        selectedDetail: null,
        history: null,
        equipmentAudit: null,
        editDraft: { ...EMPTY_DRAFT },
      });
      return;
    }
    set({ selectedSkillId: skillId, loadingDetail: true, lastError: null, unreadBadgeCount: 0 });
    try {
      const [detail, history, audit] = await Promise.all([
        getMethodologySkill(skillId),
        getMethodologySkillHistory(skillId),
        getMethodologySkillEquipmentAudit(skillId),
      ]);
      set({
        selectedSkillId: detail.skill_id,
        selectedDetail: detail,
        history,
        equipmentAudit: audit,
        editDraft: draftFromDetail(detail),
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载方法论详情。") });
    } finally {
      set({ loadingDetail: false });
    }
  },

  setSortKey: (sortKey) => set({ sortKey }),
  setFilterKey: (filterKey) => set({ filterKey }),

  setDraftField: (field, value) => {
    set((state) => ({ editDraft: { ...state.editDraft, [field]: value } }));
  },

  saveDraft: async () => {
    const draft = get().editDraft;
    if (!draft.skill_id) return false;
    const triggerConditions = normalizeList(draft.trigger_conditions);
    if (!draft.name.trim() || !draft.description.trim() || !draft.body_markdown.trim() || triggerConditions.length === 0) {
      set({ lastError: "名称、描述、触发条件和正文必须填写。" });
      return false;
    }
    const duplicate = get().items.find(
      (item) =>
        item.skill_id !== draft.skill_id &&
        item.name.trim().toLowerCase() === draft.name.trim().toLowerCase(),
    );
    if (duplicate) {
      set({ lastError: `方法论名称已被占用：${duplicate.name} (${duplicate.skill_id})` });
      return false;
    }
    set({ saving: true, lastError: null });
    try {
      const detail = await updateMethodologySkill(draft.skill_id, {
        name: draft.name.trim(),
        description: draft.description.trim(),
        trigger_conditions: triggerConditions,
        required_tools: normalizeList(draft.required_tools),
        body_markdown: draft.body_markdown.trim(),
        change_reason: draft.change_reason.trim() || "通过 SkillScreen 编辑",
      });
      await Promise.all([get().load(), get().selectSkill(detail.skill_id)]);
      return true;
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法保存方法论。") });
      return false;
    } finally {
      set({ saving: false });
    }
  },

  softDeleteSelected: async () => {
    const skillId = get().selectedSkillId;
    if (!skillId) return false;
    set({ saving: true, lastError: null });
    try {
      await softDeleteMethodologySkill(skillId);
      await get().load();
      await get().selectSkill(null);
      return true;
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法软删除方法论。") });
      return false;
    } finally {
      set({ saving: false });
    }
  },

  loadEquipment: async (entityId) => {
    set({ lastError: null });
    try {
      const equipment = await getEntityEquipment(entityId);
      set((state) => ({
        equipmentByEntity: { ...state.equipmentByEntity, [entityId]: equipment },
        tokenBudgetThresholds: equipment.token_budget_thresholds,
      }));
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载方法论装备。") });
    }
  },

  saveEquipment: async (entityId, skillIds) => {
    set({ saving: true, lastError: null });
    try {
      await updateEntityEquipment(entityId, {
        skills: skillIds.map((skill_id, equipped_order) => ({ skill_id, equipped_order })),
      });
      await Promise.all([get().loadEquipment(entityId), get().load()]);
      return true;
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法保存方法论装备。") });
      return false;
    } finally {
      set({ saving: false });
    }
  },

  dismissUnread: () => set({ unreadBadgeCount: 0 }),
  dismissBootstrapWarning: () => set({ bootstrapWarning: null }),

  applyEvent: (event) => {
    if (event.type === "skill.changed") {
      const payload = event.payload;
      set((state) => ({
        ...(payload.reason === "bootstrap_fallback_used"
          ? { bootstrapWarning: bootstrapWarningFromEvent(payload) }
          : {}),
        unreadBadgeCount: state.unreadBadgeCount + 1,
      }));
      scheduleRefresh(async () => {
        await get().load();
        const changedId = skillEventId(payload);
        const selected = get().selectedSkillId;
        if (selected && (!changedId || changedId === selected)) {
          await get().selectSkill(selected);
        }
      });
      return;
    }
    if (event.type === "skill.equipment.changed") {
      const entityId = event.payload.entityId ?? "";
      if (entityId) {
        scheduleRefresh(async () => { await Promise.all([get().loadEquipment(entityId), get().load()]); });
      }
    }
  },
}));
